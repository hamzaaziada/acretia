#!/usr/bin/env python3
"""open-multiples — public-company comps built only from free, reusable sources.

  python3 open_multiples.py universe                       # SEC ticker -> CIK list (needs SEC_USER_AGENT)
  python3 open_multiples.py build AAPL MSFT NVDA           # compute comps for tickers
  python3 open_multiples.py build --cik 320193 789019      # ...or by SEC CIK (works without the ticker list)
  python3 open_multiples.py build --all [--limit 500]      # every SEC filer with a listed ticker
  python3 open_multiples.py show AAPL                      # one company, every field with its source filing
  python3 open_multiples.py bulk-download                  # nightly companyfacts.zip instead of per-company calls

Options for build/show: --prices FILE.csv | --twelvedata   (market cap / EV / multiples need a price)
                        --as-of YYYY-MM-DD                (point in time: only filings filed by that date)
Config (.env): SEC_USER_AGENT="Your Name your@email.com"  TWELVEDATA_API_KEY=...
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from om.fx import FX  # noqa: E402
from om.metrics import compute  # noqa: E402
from om.prices import CsvPrices, TwelveDataPrices  # noqa: E402
from om.sec import SecClient  # noqa: E402

DATA = ROOT / "data"
RAW = DATA / "raw"
OUT = DATA / "out"
BULK = RAW / "companyfacts.zip"


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    try:
        from om import keystore, settings
        moved = settings.migrate(env)
        if moved:
            print(f"moved {', '.join(moved)} from .env to the {keystore.backend()}", file=sys.stderr)
        keystore.load_into_env(sorted(settings.SECRET_VARS))
    except Exception as e:  # never block startup on the key store
        print(f"key store unavailable: {e}", file=sys.stderr)


def client() -> SecClient:
    return SecClient(os.environ.get("SEC_USER_AGENT", ""), RAW / "sec")


def universe(sec: SecClient, refresh: bool = False) -> list[dict]:
    path = DATA / "universe.csv"
    if path.exists() and not refresh:
        with open(path, newline="") as fh:
            return list(csv.DictReader(fh))
    rows = sec.tickers()
    DATA.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["cik", "name", "ticker", "exchange"])
        w.writeheader()
        w.writerows(rows)
    print(f"universe: {len(rows):,} listed securities -> {path.relative_to(ROOT)}")
    return [{k: str(v) for k, v in r.items()} for r in rows]


def resolve(sec: SecClient, tickers: list[str], ciks: list[int], all_: bool, limit: int | None) -> list[int]:
    out = list(ciks)
    if tickers or all_:
        uni = universe(sec)
        if all_:
            seen = set()
            for r in uni:
                if r.get("exchange") in ("", "OTC", "None", None):
                    continue
                c = int(r["cik"])
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        by_t = {r["ticker"].upper(): int(r["cik"]) for r in uni}
        for t in tickers:
            if t.upper() not in by_t:
                print(f"  ! unknown ticker {t}")
            else:
                out.append(by_t[t.upper()])
    out = list(dict.fromkeys(out))
    return out[:limit] if limit else out


def price_source(args):
    if args.prices:
        return CsvPrices(Path(args.prices))
    if args.twelvedata:
        key = os.environ.get("TWELVEDATA_API_KEY")
        if not key:
            raise SystemExit("Set TWELVEDATA_API_KEY in .env")
        return TwelveDataPrices(key)
    return None


def build_one(sec, cik, prices, fx, as_of):
    cfacts = sec.companyfacts(cik, BULK if BULK.exists() else None)
    sub = sec.submissions(cik)
    quote = None
    if prices:
        for t in sub.get("tickers") or []:
            quote = prices.get(t, as_of)
            if quote:
                break
    return compute(cfacts, sub, quote, fx, as_of)


def cmd_build(args) -> None:
    sec = client()
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    ciks = resolve(sec, args.tickers, args.cik or [], args.all, args.limit)
    if not ciks:
        raise SystemExit("Nothing to build: pass tickers, --cik or --all")
    prices, fx = price_source(args), FX(RAW / "fx")
    rows, provs, errors = [], {}, []
    print(f"building {len(ciks):,} companies (SEC limit respected: <=8 req/s)…")
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(build_one, sec, c, prices, fx, as_of): c for c in ciks}
        for i, f in enumerate(cf.as_completed(futs), 1):
            c = futs[f]
            try:
                row, prov = f.result()
                rows.append(row)
                provs[c] = prov
            except FileNotFoundError:
                errors.append((c, "no XBRL company facts"))
            except Exception as e:  # keep going, report at the end
                errors.append((c, repr(e)[:200]))
            if i % 100 == 0:
                print(f"  {i:,}/{len(ciks):,}")
    OUT.mkdir(parents=True, exist_ok=True)
    tag = f"_asof_{args.as_of}" if args.as_of else ""
    rows.sort(key=lambda r: -(r.get("market_cap") or r.get("revenue_ltm") or 0))
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT / f"public_comps{tag}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(OUT / f"public_comps{tag}.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    with open(OUT / f"provenance{tag}.jsonl", "w") as fh:
        for c, p in provs.items():
            fh.write(json.dumps({"cik": c, "fields": p}) + "\n")
    print(f"done: {len(rows):,} companies -> data/out/public_comps{tag}.csv (+ .jsonl, provenance{tag}.jsonl)")
    if errors:
        print(f"  {len(errors)} skipped, e.g. {errors[:3]}")


def cmd_show(args) -> None:
    sec = client()
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    ciks = resolve(sec, [args.ticker] if not args.ticker.isdigit() else [], [int(args.ticker)] if args.ticker.isdigit() else [], False, None)
    row, prov = build_one(sec, ciks[0], price_source(args), FX(RAW / "fx"), as_of)
    print(f"\n{row['name']}  (CIK {row['cik']}, {row['ticker']}, {row['exchange']}, SIC {row['sic']} {row['sic_description']})")
    print(f"reporting currency {row['reporting_currency']} · LTM to {row['ltm_end']} · balance sheet {row['balance_sheet_date']}\n")
    for k, v in row.items():
        if k in ("name", "cik", "ticker", "exchange", "sic", "sic_description") or v is None or v == "":
            continue
        val = f"{v:,.2f}" if isinstance(v, float) else v
        src = ""
        p = prov.get(k)
        if p and p.get("facts"):
            f0 = p["facts"][0]
            accn = f0["accn"].replace("-", "")
            src = f"  ← {p['basis']}: {f0['concept']} {f0['form']} filed {f0['filed']}  https://www.sec.gov/Archives/edgar/data/{row['cik']}/{accn}/"
        print(f"  {k:<42} {val}{src}")


def cmd_ma(args) -> None:
    from om import ma
    sec = client()
    if args.url:
        m = re.match(r".*/data/(\d+)/(\d{18})/(.+)$", args.url)
        if not m:
            raise SystemExit("--url must be an sec.gov/Archives/edgar/data/<cik>/<accession>/<file> link")
        a = m.group(2)
        hits = [{"accession": f"{a[:10]}-{a[10:12]}-{a[12:]}", "file": m.group(3), "cik": int(m.group(1)),
                 "form": args.form or "?", "filed": "", "company": args.company or "", "url": args.url}]
    else:
        start = date.fromisoformat(args.date_from)
        end = date.fromisoformat(args.date_to) if args.date_to else date.today()
        print(f"searching EDGAR full text {start} → {end} …")
        hits = ma.discover(sec, start, end, max_hits=args.limit)
        print(f"  {len(hits)} filing documents mention a precedent-transactions analysis")
    all_obs, all_an, errors = [], [], []

    def one(h):
        raw = sec.get_text(h["url"], f"filings/{h['accession']}/{h['file']}")
        return ma.extract(raw, h)

    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(one, h): h for h in hits}
        for i, f in enumerate(cf.as_completed(futs), 1):
            try:
                o, a = f.result()
                all_obs += o
                all_an += a
            except Exception as e:
                errors.append((futs[f]["url"], repr(e)[:160]))
            if i % 25 == 0:
                print(f"  parsed {i}/{len(hits)}")
    OUT.mkdir(parents=True, exist_ok=True)
    obs_rows = [ma.as_dict(o) for o in all_obs]
    an_rows = [{**ma.as_dict(a), "summary": json.dumps(a.summary), "reference_range": json.dumps(a.reference_range)}
               for a in all_an]
    deals = ma.consolidate(all_obs)
    for name, rows in (("ma_precedent_observations", obs_rows), ("ma_analyses", an_rows), ("ma_deals", deals)):
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with open(OUT / f"{name}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols or ["empty"])
            w.writeheader()
            w.writerows(rows)
    with_mult = sum(1 for d in deals if any(k.startswith(("ev_", "equity_")) and not k.endswith(("_n", "_disagreement")) for k in d))
    print(f"done: {len(all_an)} banker analyses, {len(obs_rows)} observations, {len(deals)} unique deals "
          f"({with_mult} with at least one multiple) -> data/out/ma_*.csv")
    if errors:
        print(f"  {len(errors)} documents failed, e.g. {errors[:2]}")


SEARCH_DB = DATA / "search.db"


def cmd_ingest(args) -> None:
    from om import docs
    from om.search import Index
    sec, idx = client(), Index(SEARCH_DB)
    ciks = resolve(sec, args.tickers, args.cik or [], args.all, args.limit)
    forms = [f.strip() for f in args.forms.split(",")] if args.forms else docs.DEFAULT_FORMS
    refs = []
    for c in ciks:
        sub = sec.submissions(c)
        for r in docs.list_filings(sub, forms, args.since, args.until, args.max_per_company):
            refs.append(r)
            if not args.no_exhibits:
                refs.extend(docs.exhibits(sec, r))
    todo = [r for r in refs if not idx.has(r.url)]
    print(f"{len(ciks)} companies · {len(refs)} documents listed · {len(todo)} new to index")

    def fetch(r):
        raw = sec.get_text(r.url, f"filings/{r.accession}/{r.file}")
        return r, docs.passages(raw)

    added = 0
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(fetch, r) for r in todo]
        for i, f in enumerate(cf.as_completed(futs), 1):
            try:
                r, (ps, n) = f.result()
                added += idx.add(r, ps, n)  # sqlite writes stay on this thread
            except Exception as e:
                print(f"  ! {e!r:.150}")
            if i % 20 == 0 or i == len(todo):
                print(f"  indexed {i}/{len(todo)} documents ({added:,} passages)")
    st = idx.stats()
    print(f"index: {st['documents']:,} documents · {st['passages']:,} passages · {st['companies']} companies · {st['from']} → {st['to']}")


def _search_filters(args) -> dict:
    f = {}
    if args.ticker:
        f["tickers"] = args.ticker
    if args.form:
        f["forms"] = args.form
    for k in ("date_from", "date_to", "section", "sort"):
        if getattr(args, k, None):
            f[k] = getattr(args, k)
    return f


def cmd_search(args) -> None:
    from om.search import Index
    idx = Index(SEARCH_DB)
    f = _search_filters(args)
    res = idx.search(args.query, f, limit=args.limit)
    print(f'\n"{args.query}" — {res["total_documents"]:,} documents, {res["total_passages"]:,} passages\n')
    for d in res["results"]:
        print(f"{d['filed']}  {d['ticker'] or '':<6} {d['form']:<8} {d['title'][:60]}  ({d['hits']} hits)")
        print(f"   {d['url']}")
        for p in d["passages"]:
            snip = re.sub(r"</?mark>", "**", p["snippet"])
            print(f"   [{p['section'] or '—'}] {snip}")
        print()
    if args.trend:
        print("mentions by filing quarter:")
        for t in idx.trend(args.query, f):
            print(f"   {t['quarter']}  {t['documents']:>4} docs  {'█' * min(60, t['documents'])}")
    if args.save:
        idx.save(args.save, args.query, f)
        print(f"saved as '{args.save}' — `alerts` will report new matches")


def cmd_alerts(args) -> None:
    from om.search import Index
    for a in Index(SEARCH_DB).alerts(mark=not args.peek):
        print(f"\n[{a['name']}] \"{a['query']}\" — {a['new_documents']} new documents")
        for d in a["results"][:10]:
            print(f"   {d['filed']} {d['ticker'] or ''} {d['form']} {d['title'][:60]}  {d['url']}")


def _parse_columns(specs: list[str]):
    """'Name::question' or 'Name:type::question' -> Column."""
    from om.matrix import COLUMN_TYPES, Column
    cols = []
    for s in specs:
        if "::" not in s:
            raise SystemExit(f'column must look like "Name::question" or "Name:number::question", got {s!r}')
        head, q = s.split("::", 1)
        name, _, typ = head.partition(":")
        typ = typ.strip() or "text"
        if typ not in COLUMN_TYPES:
            raise SystemExit(f"column type must be one of {COLUMN_TYPES}")
        cols.append(Column(name.strip(), q.strip(), typ))
    return cols


def cmd_matrix(args) -> None:
    from om.matrix import MatrixStore, make_client
    from om.search import Index
    idx = Index(SEARCH_DB)
    store = MatrixStore(idx)
    if args.action == "list":
        for m in store.list():
            cols = [c["name"] for c in json.loads(m["columns"])]
            print(f"{m['id']:>3}  {m['name']:<30} {m['rows']:>4} rows  columns: {', '.join(cols)}")
        return
    if args.action == "create":
        f = {}
        if args.ticker:
            f["tickers"] = args.ticker
        if args.form:
            f["forms"] = args.form
        if args.date_from:
            f["date_from"] = args.date_from
        if args.query:
            docs = idx.search(args.query, f, limit=args.max_rows)["results"]
            doc_ids = [d["doc_id"] for d in docs]
        else:
            where, params = idx._where(f)
            doc_ids = [r[0] for r in idx.db.execute(
                f"SELECT d.doc_id FROM documents d LEFT JOIN chunks c ON 0 WHERE 1=1 {where} ORDER BY d.filed DESC LIMIT ?",
                params + [args.max_rows])]
        mid = store.create(args.name, doc_ids, _parse_columns(args.column or []))
        print(f"matrix '{args.name}' (id {mid}): {len(doc_ids)} rows × {len(args.column or [])} columns. "
              f"Run: python3 open_multiples.py matrix run {args.name}")
        return
    mid = store.get_id(args.name)
    if args.action == "add-column":
        for c in _parse_columns(args.column or []):
            store.add_column(mid, c)
        print("column(s) added — `matrix run` fills only the missing cells")
    elif args.action == "run":
        client = make_client(args.engine)
        print(f"engine: {client.describe('matrix') if client else 'extractive (no model configured: quotes the best-matching passage)'}")
        stats = store.run(mid, client, only_missing=not args.rerun, workers=args.workers, effort=args.effort,
                          progress=lambda i, n: print(f"  row {i}/{n}", flush=True))
        print(json.dumps(stats, indent=1))
    elif args.action == "show":
        v = store.view(mid)
        for r in v["rows"]:
            d = r["doc"]
            print(f"\n{d['ticker']} {d['form']} {d['filed']}  {d['url']}")
            for c in v["columns"]:
                cell = r["cells"].get(c["name"])
                if not cell:
                    print(f"   {c['name']}: —")
                    continue
                mark = {"ok": "✓", "extracted": "❝", "unverified": "?", "not_found": "∅"}.get(cell["status"], "!")
                print(f"   {mark} {c['name']}: {cell['answer'][:160]}")
    elif args.action == "export":
        out = OUT / f"matrix_{args.name}.csv"
        OUT.mkdir(parents=True, exist_ok=True)
        store.export_csv(mid, out)
        print(f"-> {out}")


def cmd_room(args) -> None:
    from om import connectors as conn
    from om.rooms import Rooms
    from om.search import Index
    rooms = Rooms(Index(SEARCH_DB), DATA)
    if args.action == "list":
        for r in rooms.list():
            print(f"{r['id']:>3}  {r['name']:<30} {r['documents']:>5} docs {r['pages']:>6} pages")
        return
    if args.action == "create":
        print(f"room '{args.name}' created (id {rooms.create(args.name)})")
        return
    rid = rooms.get(args.name)["id"]
    if args.action == "import":
        for p in args.paths:
            res = rooms.add_path(rid, Path(p), source="vdr-export" if p.lower().endswith(".zip") else "folder")
            out = res.as_dict()
            print(f"{p}: {out['added']} added · {out['updated']} updated · {out['unchanged']} unchanged · "
                  f"{out['skipped']} skipped · {out['failed']} failed")
            for w in out["warnings"][:10]:
                print(f"   ! {w}")
            rooms.log(rid, "import", {"path": p, **{k: out[k] for k in ("added", "updated", "unchanged", "skipped", "failed")}})
    elif args.action == "connect":
        cfg = {"type": args.type}
        for kv in args.set or []:
            k, _, v = kv.partition("=")
            cfg[k.strip()] = v.strip()
        print(json.dumps(conn.add_connector(rooms, rid, cfg), indent=1))
    elif args.action == "sync":
        print(json.dumps(conn.sync(rooms, rid, progress=lambda n: print(f"  {n} files fetched", flush=True)), indent=1))
    elif args.action == "docs":
        for d in rooms.documents(rid):
            print(f"  {d['form']:<5} {d['pages'] or '':>4}p {d['passages']:>4} passages  {d['path']}")
        for c in conn.connectors(rooms, rid):
            print(f"  connector #{c['id']} {c['type']} {c.get('path') or c.get('folder_id') or c.get('share_url') or ''}")


def cmd_rounds(args) -> None:
    from om.formd import Rounds, list_quarters, public_ciks
    from om.search import Index
    rounds = Rounds(Index(SEARCH_DB).db)
    if args.action == "load":
        sec = client()
        qs = list_quarters(sec)
        wanted = args.quarter or list(qs)[:args.last]
        listed = public_ciks(DATA / "universe.csv") or public_ciks(Path(universe(sec) and DATA / "universe.csv"))
        for q in sorted(wanted):   # oldest first, so amendments find their originals
            if q not in qs:
                print(f"  ! {q} not on the SEC index (available: {', '.join(list(qs)[:6])}…)")
                continue
            r = rounds.load_quarter(sec, q, qs[q], RAW / "formd", args.exclude_real_estate, listed)
            print(f"  {q}: {r['filings']:,} operating-company filings -> {r['rounds']:,} rounds")
        st = rounds.stats()
        print(f"company rounds: {st['rounds']:,} · ${st['total_sold'] / 1e9:,.1f}bn sold · median ${(st['median_sold'] or 0) / 1e6:,.1f}m")
        print("by category: " + " · ".join(f"{c['category']} {c['rounds']:,}" for c in st["categories"]))
    elif args.action == "search":
        res = rounds.search(" ".join(args.query or []), args.industry or "", args.state or "", args.min_sold,
                            args.date_from or "", "", args.equity_only, args.sort, args.limit, category=args.category)
        print(f"{res['total']:,} rounds · ${res['total_sold'] / 1e6:,.0f}m sold\n")
        for r in res["results"]:
            sold = f"${r['amount_sold'] / 1e6:,.1f}m" if r["amount_sold"] else "—"
            print(f"  {r['first_sale_date'] or r['first_filed']}  {sold:>10}  {r['investors']:>4} inv  {r['company'][:40]:<40} "
                  f"{(r['industry'] or '')[:22]:<22} {r['city']}, {r['state'] or r['country']}")
    elif args.action == "export":
        OUT.mkdir(parents=True, exist_ok=True)
        n = rounds.export_csv(OUT / "funding_rounds.csv")
        print(f"{n:,} rounds -> data/out/funding_rounds.csv")


def cmd_check(args) -> None:
    from om import consistency as cs
    from om.llm import Router
    from om.rooms import Rooms
    from om.search import Index
    from om.sheets import DataService
    idx = Index(SEARCH_DB)
    rooms = Rooms(idx, DATA)
    if args.room:
        rep = cs.check_room(idx, rooms, rooms.get(args.target)["id"], router=Router(), log=print)
    else:
        path = Path(args.target).expanduser()
        data = path.read_bytes()
        if path.suffix.lower() == ".xlsx":
            rep = cs.check_workbook(data, name=path.name)
        elif args.against_room:
            rep = cs.check_room(idx, rooms, rooms.get(args.against_room)["id"], router=Router(), deck=data, deck_name=path.name, log=print)
        else:
            rep = cs.check_deck(data, name=path.name, data_service=None if args.no_tie else DataService(idx, DATA),
                                universe=cs.load_universe(DATA / "universe.csv"), tie=not args.no_tie, notes=args.notes, log=print)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
        return
    c = rep["counts"]
    print(f"{c['high']} high · {c['medium']} medium · {c['low']} low   ({rep['facts']} figures read)")
    if rep.get("tie_out") and rep["tie_out"]["checked"]:
        t = rep["tie_out"]
        print(f"SEC tie-out: {t['matched']} of {t['checked']} company figures match")
    for i in rep["issues"]:
        print(f"\n[{i['severity'].upper()}] {i['title']}")
        if i.get("detail"):
            print(f"    {i['detail']}")
        for g in i.get("groups", []):
            for it in g[:2]:
                print(f"    - {it['value']}  ({it.get('where', '')})")
    if not rep["issues"]:
        print("No inconsistencies found.")


def cmd_deck(args) -> None:
    from om import decks, settings
    from om.formd import Rounds
    from om.search import Index
    from om.sheets import DataService
    idx = Index(SEARCH_DB)
    req = {"tickers": args.tickers, "ticker": args.tickers[0] if args.tickers else "",
           "filters": {"industry": args.industry} if args.industry else {}}
    if args.kind in ("comps", "tearsheet") and not args.tickers:
        raise SystemExit(f"deck {args.kind}: give ticker(s), e.g. deck {args.kind} AAPL MSFT")
    deck, stem = decks.build(args.kind, req, data_service=DataService(idx, DATA), index=idx, rounds=Rounds(idx.db),
                             brand=settings.brand())
    out = Path(args.out) if args.out else OUT / (re.sub(r"[^A-Za-z0-9 _.-]", "_", stem) + ".pptx")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(deck.save())
    print(f"wrote {out}  ({len(deck.slides)} slides)")


def cmd_model(args) -> None:
    from om import model3, modelcheck
    from om.search import Index
    from om.sheets import DataService
    st = DataService(Index(SEARCH_DB), DATA).statements(args.ticker, years=args.years)
    body, meta = model3.build(st, scenario=args.scenario, circ=0 if args.no_circ else 1)
    out = Path(args.out) if args.out else OUT / f"{st.ticker} three-statement model.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    g = modelcheck.grade(body)
    print(f"wrote {out}")
    print(f"{st.name}: FY{meta['years'][0][:4]}–FY{meta['years'][-1][:4]} actuals + {meta['forecast_years']} forecast years; "
          f"solver {'converged' if meta['converged'] else 'did NOT converge'} in {meta['iterations']} iterations")
    _print_grade(g)
    for w in meta["warnings"]:
        print(f"  note: {w}")


def _print_grade(g: dict) -> None:
    print(f"grade {g['score']}/100 — {'production-ready' if g['production_ready'] else 'NOT production-ready'}")
    for r in g["graders"]:
        print(f"  {'n/a ' if r['passed'] is None else 'PASS' if r['passed'] else 'FAIL'}  {r['title']}: {r['detail']}")
        if r["passed"] is False:
            for c in r["cells"][:6]:
                print(f"        {c}")


def cmd_grade(args) -> None:
    from om import modelcheck
    g = modelcheck.grade(Path(args.file).expanduser().read_bytes())
    if args.json:
        print(json.dumps(g, indent=2, default=str))
    else:
        _print_grade(g)


def cmd_bench(args) -> None:
    from datetime import date as _date

    from om import bench
    from om.search import Index
    from om.sheets import DataService
    ds = DataService(Index(SEARCH_DB), DATA)
    from om.sec import SecClient
    sec = SecClient(os.environ.get("SEC_USER_AGENT", ""), RAW / "sec")
    companies = []
    for t in args.tickers or ["AAPL", "MSFT", "COST", "NVDA", "ASML"]:
        cik = ds._cik(t)
        if cik is None:
            print(f"skip {t}: unknown ticker")
            continue
        companies.append((t.upper(), sec.companyfacts(cik)))
    res = bench.run(companies, OUT / "bench" / _date.today().isoformat(), with_libreoffice=args.libreoffice,
                    audit_ticker=(args.tickers or ["AAPL"])[0].upper())
    print(bench.report(res))
    print(f"wrote {OUT / 'bench' / _date.today().isoformat()}")


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("universe")
    sp.add_parser("bulk-download")
    pm = sp.add_parser("ma", help="M&A precedent-transaction multiples from merger filings")
    pm.add_argument("--from", dest="date_from", default=f"{date.today().year}-01-01")
    pm.add_argument("--to", dest="date_to")
    pm.add_argument("--limit", type=int, help="max filing documents")
    pm.add_argument("--url", help="parse one filing document instead of searching")
    pm.add_argument("--form")
    pm.add_argument("--company")
    pi = sp.add_parser("ingest", help="index SEC filings for full-text search")
    pi.add_argument("tickers", nargs="*", default=[])
    pi.add_argument("--cik", nargs="*", type=int)
    pi.add_argument("--all", action="store_true")
    pi.add_argument("--limit", type=int, help="max companies")
    pi.add_argument("--forms", help="comma-separated, default: 10-K,10-Q,8-K,20-F,6-K,DEF 14A,DEFM14A,S-1,S-4…")
    pi.add_argument("--since")
    pi.add_argument("--until")
    pi.add_argument("--max-per-company", type=int)
    pi.add_argument("--no-exhibits", action="store_true")
    ps = sp.add_parser("search", help="search indexed filings")
    ps.add_argument("query")
    ps.add_argument("--ticker", nargs="*")
    ps.add_argument("--form", nargs="*")
    ps.add_argument("--from", dest="date_from")
    ps.add_argument("--to", dest="date_to")
    ps.add_argument("--section", help='e.g. "Risk Factors"')
    ps.add_argument("--sort", choices=["relevance", "date"])
    ps.add_argument("--limit", type=int, default=10)
    ps.add_argument("--trend", action="store_true", help="show mentions per quarter")
    ps.add_argument("--save", metavar="NAME", help="save as an alert")
    pa = sp.add_parser("alerts", help="new matches for saved searches since last run")
    pa.add_argument("--peek", action="store_true", help="don't mark as seen")
    px = sp.add_parser("matrix", help="documents × questions grid answered by Claude with citations")
    px.add_argument("action", choices=["create", "add-column", "run", "show", "export", "list"])
    px.add_argument("name", nargs="?")
    px.add_argument("--query", help="rows = documents matching this search")
    px.add_argument("--ticker", nargs="*")
    px.add_argument("--form", nargs="*")
    px.add_argument("--from", dest="date_from")
    px.add_argument("--max-rows", type=int, default=25)
    px.add_argument("--column", action="append", help='"Name::question" or "Name:number::question" (repeatable)')
    px.add_argument("--rerun", action="store_true", help="re-answer cells that already have answers")
    px.add_argument("--workers", type=int, default=4)
    px.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    px.add_argument("--engine", default="auto",
                    help='auto (configured model, else extractive) | extractive | <provider>[:<model>], '
                         'e.g. deepseek, deepseek:deepseek-reasoner, anthropic, openai:gpt-4.1, ollama:qwen2.5:14b')
    pr = sp.add_parser("room", help="data rooms: create, import VDR exports/folders, connectors, sync")
    pr.add_argument("action", choices=["create", "list", "import", "connect", "sync", "docs"])
    pr.add_argument("name", nargs="?")
    pr.add_argument("paths", nargs="*", help="files, folders or .zip exports to import")
    pr.add_argument("--type", choices=["synced_folder", "box", "sharepoint", "dropbox"])
    pr.add_argument("--set", action="append", metavar="KEY=VALUE", help="connector setting, e.g. path=~/Box/Deal or folder_id=123")
    pf = sp.add_parser("rounds", help="private funding rounds from SEC Form D")
    pf.add_argument("action", choices=["load", "search", "export"])
    pf.add_argument("query", nargs="*")
    pf.add_argument("--last", type=int, default=4, help="load the N most recent quarters (default 4)")
    pf.add_argument("--quarter", nargs="*", help="specific quarters, e.g. 2026Q3 2025Q4")
    pf.add_argument("--exclude-real-estate", action="store_true")
    pf.add_argument("--industry")
    pf.add_argument("--state")
    pf.add_argument("--min-sold", type=float)
    pf.add_argument("--from", dest="date_from")
    pf.add_argument("--equity-only", action="store_true")
    pf.add_argument("--sort", default="date", choices=["date", "amount", "investors"])
    pf.add_argument("--category", default="company", choices=["company", "public_pipe", "vehicle", "real_estate", "all"])
    pf.add_argument("--limit", type=int, default=25)
    pc = sp.add_parser("check", help="consistency check: a deck (.pptx), a model (.xlsx) or a data room")
    pc.add_argument("target", help="path to .pptx / .xlsx, or a data room name with --room")
    pc.add_argument("--room", action="store_true", help="target is a data room name")
    pc.add_argument("--against-room", help="also compare the deck with this data room")
    pc.add_argument("--no-tie", action="store_true", help="don't tie company figures to SEC filings")
    pc.add_argument("--notes", action="store_true", help="include speaker notes")
    pc.add_argument("--json", action="store_true", help="print the full report as JSON")
    pd = sp.add_parser("deck", help="build a PowerPoint: comps, company profile (tearsheet) or funding-market update")
    pd.add_argument("kind", choices=["comps", "tearsheet", "rounds"])
    pd.add_argument("tickers", nargs="*")
    pd.add_argument("--industry")
    pd.add_argument("--out", help="output .pptx path (default data/out/<name>.pptx)")
    pm3 = sp.add_parser("model", help="integrated three-statement model + DCF (.xlsx) from SEC filings, graded")
    pm3.add_argument("ticker")
    pm3.add_argument("--scenario", type=int, choices=[1, 2, 3], default=1, help="1 base, 2 upside, 3 downside")
    pm3.add_argument("--no-circ", action="store_true", help="interest on opening balances (no circularity)")
    pm3.add_argument("--years", type=int, default=5, help="years of actuals (default 5)")
    pm3.add_argument("--out", help="output .xlsx path (default data/out/<TICKER> three-statement model.xlsx)")
    pg = sp.add_parser("grade", help="grade any Excel model: errors, checks, balance, hard-codes, consistency, colours, circularity, sources")
    pg.add_argument("file")
    pg.add_argument("--json", action="store_true")
    pb = sp.add_parser("bench", help="OM-Bench: build and grade models, plant errors and measure what the graders catch")
    pb.add_argument("tickers", nargs="*")
    pb.add_argument("--libreoffice", action="store_true", help="also prove our calculated values match LibreOffice")
    sp.add_parser("models", help="show which model serves each stage")
    pv = sp.add_parser("serve", help="local search web UI")
    pv.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8765))
    for name in ("build", "show"):
        p = sp.add_parser(name)
        if name == "build":
            p.add_argument("tickers", nargs="*", default=[])
            p.add_argument("--cik", nargs="*", type=int)
            p.add_argument("--all", action="store_true")
            p.add_argument("--limit", type=int)
        else:
            p.add_argument("ticker")
        p.add_argument("--prices")
        p.add_argument("--twelvedata", action="store_true")
        p.add_argument("--as-of")
    args = ap.parse_args()
    if args.cmd == "universe":
        universe(client(), refresh=True)
    elif args.cmd == "bulk-download":
        client().download_bulk_facts(BULK)
    elif args.cmd == "build":
        cmd_build(args)
    elif args.cmd == "ma":
        cmd_ma(args)
    elif args.cmd == "ingest":
        cmd_ingest(args)
    elif args.cmd == "search":
        cmd_search(args)
    elif args.cmd == "alerts":
        cmd_alerts(args)
    elif args.cmd == "matrix":
        cmd_matrix(args)
    elif args.cmd == "room":
        cmd_room(args)
    elif args.cmd == "rounds":
        cmd_rounds(args)
    elif args.cmd == "deck":
        cmd_deck(args)
    elif args.cmd == "model":
        cmd_model(args)
    elif args.cmd == "grade":
        cmd_grade(args)
    elif args.cmd == "bench":
        cmd_bench(args)
    elif args.cmd == "check":
        cmd_check(args)
    elif args.cmd == "models":
        from om.llm import STAGES, Router
        r = Router()
        for stage, desc in STAGES.items():
            print(f"  {stage:<14} {r.describe(stage):<40} {desc}")
        print("\nConfigure in .env: OM_MODEL_DEFAULT=deepseek:deepseek-chat, OM_MODEL_MATRIX=anthropic:claude-opus-5-5, plus provider keys.")
    elif args.cmd == "serve":
        from om.search import Index
        from om.web import serve
        serve(Index(SEARCH_DB), SEARCH_DB, DATA, port=args.port)
    else:
        cmd_show(args)


if __name__ == "__main__":
    main()
