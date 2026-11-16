"""Web app + JSON API (stdlib http.server). Run: python3 open_multiples.py serve

Pages:  /            Search (public filings or a data room)
        /rooms.html  Data rooms: upload files/folders/VDR exports, connectors, documents
        /matrix.html Matrix: documents × questions with cited answers
Long jobs (matrix runs, connector syncs) run in background threads with their own SQLite connection.
Binds to 127.0.0.1 by default; there is no authentication yet, so do not expose it on a network.
"""
from __future__ import annotations

import json
import mimetypes
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .search import Index

STATIC = Path(__file__).resolve().parent / "static"
MAX_UPLOAD = 200 * 1024 * 1024
JOBS: dict[str, dict] = {}   # "matrix:<id>" / "sync:<room>" -> live status


def _filters(qs: dict) -> dict:
    g = lambda k: (qs.get(k) or [""])[0].strip()  # noqa: E731
    f = {}
    if g("tickers"):
        f["tickers"] = [t for t in g("tickers").replace(",", " ").split() if t]
    if g("forms"):
        f["forms"] = [x.strip() for x in g("forms").split(",") if x.strip()]
    for k in ("date_from", "date_to", "section", "sort", "room"):
        if g(k):
            f[k] = g(k)
    if g("scope") == "public":
        f["public_only"] = True
    return f


def _job(key: str, fn) -> None:
    def work():
        JOBS[key] = {"state": "running", "done": 0, "total": 0}
        try:
            JOBS[key] = {"state": "done", **fn(JOBS[key])}
        except SystemExit as e:
            JOBS[key] = {"state": "error", "error": str(e)}
        except Exception as e:
            JOBS[key] = {"state": "error", "error": repr(e)[:300]}
    threading.Thread(target=work, daemon=True).start()


def make_handler(index: Index, db_path: Path, data_dir: Path):
    from . import connectors as conn
    from . import settings
    from . import sheets as sh
    from .llm import Router
    from .matrix import Column, MatrixStore, make_client
    from .rooms import Rooms
    store = MatrixStore(index)
    rooms = Rooms(index, data_dir)
    sheets = sh.Sheets(index.db)
    from .formd import Rounds
    rounds = Rounds(index.db)
    dsvc = sh.DataService(index, data_dir)
    deals_csv = data_dir / "out" / "ma_deals.csv"

    def run_matrix(mid: int, effort: str):
        def fn(status):
            s = MatrixStore(Index(db_path))
            return s.run(mid, make_client("auto"), effort=effort, progress=lambda i, n: status.update(done=i, total=n))
        _job(f"matrix:{mid}", fn)

    resolve_lock = threading.Lock()

    def data_svc_resolve(calls):
        # comps rows hit SEC + SQLite; keep resolution serialized on the shared connection
        with resolve_lock:
            return dsvc.resolve(calls)

    from . import studio as stdo
    studio_store = stdo.Studio(data_dir)
    studio_running: set[str] = set()

    def studio_pipeline():
        from . import images as imgs
        try:
            ip = imgs.make_image_provider()
        except imgs.ImageError:
            ip = None
        return stdo.Pipeline(studio_store, Router(), ip, brand=settings.brand())

    def studio_advance(rid: str):
        if rid in studio_running:
            return

        def work():
            studio_running.add(rid)
            try:
                studio_pipeline().advance(rid)
            finally:
                studio_running.discard(rid)
        threading.Thread(target=work, daemon=True).start()

    def studio_ready() -> dict:
        from . import images as imgs
        r = Router()
        out = {s_: {"model": r.describe(s_), "ok": r.available(s_)} for s_ in ("storyboard", "slide_review", "slide_build")}
        try:
            ok = imgs.make_image_provider() is not None
        except imgs.ImageError:
            ok = False
        out["image"] = {"model": imgs.describe(), "ok": ok}
        out["render"] = {"ok": bool(__import__("shutil").which("pdftoppm")) and bool(__import__("shutil").which("soffice") or
                         Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists())}
        return out

    def start_check(fn) -> str:
        import uuid
        cid = uuid.uuid4().hex[:12]

        def job(status):
            idx = Index(db_path)
            notes: list[str] = []
            out = fn(idx, notes.append)
            return {**out, "log": notes[:20]}
        _job(f"check:{cid}", job)
        return cid

    def _check_file(idx, log, name, ext, body, room, tie, notes):
        from . import consistency as cs
        from .llm import Router as _R
        if ext == ".xlsx":
            from . import modelcheck
            return {"kind": "workbook", "name": name, **cs.check_workbook(body, name=name), "model_grade": modelcheck.grade(body)}
        if room:
            rep = cs.check_room(idx, Rooms(idx, data_dir), int(room), router=_R(), deck=body, deck_name=name, log=log)
            return {"kind": "deck+room", "name": name, **rep}
        return {"kind": "deck", "name": name, **cs.check_deck(body, name=name, data_service=sh.DataService(idx, data_dir) if tie else None,
                                                            universe=cs.load_universe(data_dir / "universe.csv"), tie=tie, notes=notes, log=log)}

    def run_sync(rid: int, cid: int | None):
        def fn(status):
            r = Rooms(Index(db_path), data_dir)
            return {"results": conn.sync(r, rid, cid, progress=lambda n: status.update(done=n))}
        _job(f"sync:{rid}", fn)

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        # ------------------------------------------------------------------ helpers
        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            if self.path.startswith("/api/settings"):
                self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self, write: bool) -> bool:
            """Only this app, on this machine: localhost Host header (stops DNS rebinding) and, for anything that
            changes state, a same-origin request (stops other websites in your browser from posting here)."""
            host = (self.headers.get("Host") or "").lower()
            name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            if name not in ("localhost", "127.0.0.1", "[::1]"):
                self._json({"error": "forbidden host"}, 403)
                return False
            if write:
                origin = self.headers.get("Origin")
                site = self.headers.get("Sec-Fetch-Site")
                if (origin and origin.lower() not in (f"http://{host}", f"https://{host}")) or site in ("cross-site", "same-site"):
                    self._json({"error": "cross-site request refused"}, 403)
                    return False
            return True

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_UPLOAD:
                raise ValueError(f"upload larger than {MAX_UPLOAD // 2**20} MB")
            return self.rfile.read(n) if n else b""

        # ------------------------------------------------------------------ GET
        def do_GET(self):
            if not self._allowed(write=False):
                return
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            q = (qs.get("q") or [""])[0]
            arg = lambda k: (qs.get(k) or [None])[0]  # noqa: E731
            try:
                routes = {
                    "/api/search": lambda: index.search(q, _filters(qs), limit=20, offset=int(arg("page") or 0) * 20),
                    "/api/facets": lambda: index.facets(q, _filters(qs)),
                    "/api/trend": lambda: index.trend(q, _filters(qs)),
                    "/api/passage": lambda: index.passage(int(arg("id")), context=2),
                    "/api/stats": lambda: {**index.stats(), "rooms": len(rooms.list())},
                    "/api/saved": lambda: index.saved(),
                    "/api/alerts": lambda: index.alerts(mark=False),
                    "/api/matrices": lambda: store.list(),
                    "/api/matrix": lambda: {**store.view(int(arg("id"))), "run": JOBS.get(f"matrix:{arg('id')}")},
                    "/api/rooms": lambda: rooms.list(),
                    "/api/room": lambda: {**rooms.get(int(arg("id"))), "documents": rooms.documents(int(arg("id"))),
                                          "connectors": conn.connectors(rooms, int(arg("id"))),
                                          "events": rooms.events(int(arg("id")), 20), "sync": JOBS.get(f"sync:{arg('id')}")},
                    "/api/engine": lambda: (lambda c, r: {"engine": "llm" if c else "extractive",
                                                          "model": c.describe("matrix") if c else None,
                                                          "agent_model": r.describe("sheets_agent") if r.available("sheets_agent") else None})(
                        make_client("auto"), __import__("om.llm", fromlist=["Router"]).Router()),
                    "/api/sheets": lambda: sheets.list(),
                    "/api/sheet": lambda: sheets.get(int(arg("id"))),
                    "/api/fields": lambda: [{"key": k, "label": lab} for k, lab in sh.COMPS_FIELDS],
                    "/api/rounds": lambda: rounds.search(arg("q") or "", arg("industry") or "", arg("state") or "",
                                                         float(arg("min_sold")) if arg("min_sold") else None,
                                                         arg("date_from") or "", arg("date_to") or "", arg("equity_only") == "1",
                                                         arg("sort") or "date", 50, int(arg("page") or 0) * 50,
                                                         arg("category") or "company"),
                    "/api/rounds/stats": lambda: {**rounds.stats(q=arg("q") or "", industry=arg("industry") or "", state=arg("state") or "",
                                                                 min_sold=float(arg("min_sold")) if arg("min_sold") else None,
                                                                 date_from=arg("date_from") or "", equity_only=arg("equity_only") == "1",
                                                                 category=arg("category") or "company"),
                                                  "industries": rounds.industries()},
                    "/api/settings": lambda: {**settings.status(),
                                              "stages": {s: Router().describe(s) for s in ("ask", "matrix", "sheets_agent", "check", "storyboard", "slide_review", "slide_build")}},
                    "/api/ask/status": lambda: JOBS.get(f"ask:{arg('id')}") or {"state": "unknown"},
                    "/api/check/status": lambda: JOBS.get(f"check:{arg('id')}") or {"state": "unknown"},
                    "/api/studio/runs": lambda: studio_store.list(),
                    "/api/studio/run": lambda: {**studio_store.load(arg("id")), "running": arg("id") in studio_running},
                    "/api/studio/ready": studio_ready,
                    "/api/settings/models": lambda: settings.list_models(),
                }
                if u.path in routes:
                    return self._json(routes[u.path]())
                if u.path == "/api/matrix/export":
                    with tempfile.NamedTemporaryFile(suffix=".csv") as tf:
                        store.export_csv(int(arg("id")), tf.name)
                        body = Path(tf.name).read_bytes()
                    return self._send(200, body, "text/csv", {"Content-Disposition": f'attachment; filename="matrix_{arg("id")}.csv"'})
                if u.path == "/api/studio/file":
                    p = studio_store.path(arg("id"), arg("name"))
                    if not p.is_file():
                        return self._json({"error": "file not found"}, 404)
                    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                    disp = "attachment" if p.suffix == ".pptx" else "inline"
                    return self._send(200, p.read_bytes(), ctype, {"Content-Disposition": f'{disp}; filename="{p.name}"'})
                if u.path == "/api/file":
                    p = rooms.file_path(int(arg("doc_id")))
                    if not p:
                        return self._json({"error": "file not found"}, 404)
                    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                    disp = "inline" if ctype in ("application/pdf", "text/plain", "text/csv") else "attachment"
                    return self._send(200, p.read_bytes(), ctype, {"Content-Disposition": f'{disp}; filename="{p.name}"'})
            except KeyError as e:
                return self._json({"error": str(e)}, 404)
            except Exception as e:
                return self._json({"error": str(e)}, 400)
            name = "index.html" if u.path in ("/", "") else unquote(u.path.lstrip("/"))
            path = (STATIC / name).resolve()
            if path.is_file() and STATIC in path.parents:
                ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                if ctype.startswith("text/"):
                    ctype += "; charset=utf-8"
                return self._send(200, path.read_bytes(), ctype)
            self._json({"error": "not found"}, 404)

        # ------------------------------------------------------------------ PUT (uploads: raw body, path in query)
        def do_PUT(self):
            if not self._allowed(write=True):
                return
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            try:
                if u.path == "/api/room/upload":
                    rid = int(qs["id"][0])
                    rel = qs.get("path", [""])[0]
                    res = rooms.add_file(rid, rel, self._body(), source=qs.get("source", ["upload"])[0])
                    out = res.as_dict()
                    rooms.log(rid, "upload", {"path": rel, **{k: out[k] for k in ("added", "updated", "unchanged", "skipped", "failed")}})
                    return self._json(out)
                if u.path == "/api/check/file":
                    name = qs.get("name", ["file"])[0]
                    ext = Path(name).suffix.lower()
                    if ext not in (".pptx", ".xlsx"):
                        return self._json({"error": "upload a PowerPoint (.pptx) or Excel (.xlsx) file"}, 400)
                    body = self._body()
                    room = qs.get("room", [""])[0]
                    tie, notes = qs.get("tie", ["1"])[0] == "1", qs.get("notes", ["0"])[0] == "1"
                    return self._json({"id": start_check(lambda idx, log: _check_file(idx, log, name, ext, body, room, tie, notes))})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
            self._json({"error": "not found"}, 404)

        # ------------------------------------------------------------------ POST
        def do_POST(self):
            if not self._allowed(write=True):
                return
            u = urlparse(self.path)
            try:
                data = json.loads(self._body() or b"{}")
                if u.path == "/api/saved":
                    index.save(data["name"], data["query"], data.get("filters") or {})
                    return self._json({"ok": True})
                if u.path == "/api/saved/delete":
                    index.delete_saved(data["name"])
                    return self._json({"ok": True})
                if u.path == "/api/rooms":
                    return self._json({"id": rooms.create(data["name"].strip(), data.get("description", ""))})
                if u.path == "/api/room/connector":
                    return self._json(conn.add_connector(rooms, int(data["id"]), dict(data["config"])))
                if u.path == "/api/room/sync":
                    rid = int(data["id"])
                    if JOBS.get(f"sync:{rid}", {}).get("state") == "running":
                        return self._json({"error": "sync already running"}, 409)
                    run_sync(rid, data.get("connector_id"))
                    return self._json({"ok": True})
                if u.path == "/api/room/remove":
                    rooms.remove(int(data["doc_id"]))
                    return self._json({"ok": True})
                if u.path == "/api/matrix/create":
                    f = data.get("filters") or {}
                    n = int(data.get("max_rows") or 25)
                    if data.get("room") and not data.get("query"):
                        doc_ids = [d["doc_id"] for d in rooms.documents(int(data["room"]))][:n]
                    else:
                        if data.get("room"):
                            f["room"] = data["room"]
                        doc_ids = [d["doc_id"] for d in index.search(data["query"], f, limit=n)["results"]]
                    mid = store.create(data["name"], doc_ids, [Column(**c) for c in data.get("columns") or []])
                    return self._json({"id": mid, "rows": len(doc_ids)})
                if u.path == "/api/sheets":
                    from . import templates as tp
                    kind = data.get("template") or "blank"
                    tick = (data.get("ticker") or "").strip() or "AAPL"
                    if kind == "comps":
                        ts = [t for t in re.split(r"[\s,]+", data.get("tickers", "")) if t]
                        cells, meta = tp.comps(ts, data.get("target"))
                        default = f"Comps — {' '.join(ts[:4])}"
                    elif kind == "precedents":
                        cells, meta = tp.precedents(deals_csv, data.get("query", ""))
                        default = f"Precedents{' — ' + data['query'] if data.get('query') else ''}"
                    elif kind == "dcf":
                        cells, meta = tp.dcf(tick)
                        default = f"DCF — {tick.upper()}"
                    elif kind == "lbo":
                        cells, meta = tp.lbo(tick)
                        default = f"LBO — {tick.upper()}"
                    else:
                        cells, meta, default = {}, {}, "Untitled"
                    return self._json({"id": sheets.create(data.get("name") or default, cells, meta)})
                if u.path == "/api/sheet/save":
                    sheets.save(int(data["id"]), data["cells"], data.get("meta"), data.get("name"))
                    return self._json({"ok": True})
                if u.path == "/api/sheet/delete":
                    sheets.delete(int(data["id"]))
                    return self._json({"ok": True})
                if u.path == "/api/ask":
                    import uuid
                    from . import ask as ak
                    qid = uuid.uuid4().hex[:12]
                    scope = data.get("scope") or {}
                    question, history = data["question"].strip(), data.get("history") or []

                    def ask_job(status):
                        idx = Index(db_path)
                        tools = ak.Tools(idx, sh.DataService(idx, data_dir), Rounds(idx.db), deals_csv)
                        router = Router()
                        if not router.available("ask"):
                            known = {r[0] for r in idx.db.execute("SELECT DISTINCT ticker FROM documents WHERE ticker IS NOT NULL")}
                            uni = data_dir / "universe.csv"
                            if uni.exists():
                                import csv as _csv
                                with open(uni, newline="") as fh:
                                    known |= {r["ticker"] for r in _csv.DictReader(fh)}
                            return ak.run_without_model(tools, question, scope, known)
                        return ak.run(router, tools, question, history, scope, progress=lambda m: status.update(step=m))
                    _job(f"ask:{qid}", ask_job)
                    return self._json({"id": qid})
                if u.path == "/api/settings":
                    return self._json(settings.save(data_dir.parent / ".env", data.get("set") or {}))
                if u.path == "/api/settings/test":
                    return self._json(settings.test(data.get("stage") or "sheets_agent"))
                if u.path == "/api/sheet/agent":
                    from . import agent as ag
                    from .llm import LLMError   # Router comes from the enclosing scope (a local import would shadow it)
                    router = Router()
                    if not router.available("sheets_agent"):
                        return self._json({"error": "no_model", "detail": "No AI model is configured for the sheets agent. "
                                           "Set OM_MODEL_SHEETS_AGENT (or OM_MODEL_DEFAULT) and a provider key in .env, e.g. "
                                           "OM_MODEL_DEFAULT=deepseek:deepseek-chat + DEEPSEEK_API_KEY. Slash commands "
                                           "(/comps, /dcf, /lbo, /precedents) work without a model."}, 400)
                    row = index.db.execute("SELECT row FROM comps_cache LIMIT 1").fetchone()
                    keys = list(json.loads(row[0]).keys()) if row else None
                    try:
                        out = ag.run(router, data["instruction"], data.get("cells") or {}, data.get("values") or {},
                                     data.get("selection"), ag.matrices_for_prompt(index.db), keys,
                                     data.get("errors"), data.get("history"))
                    except LLMError as e:
                        return self._json({"error": "model_error", "detail": str(e)}, 502)
                    return self._json(out)
                if u.path == "/api/sheet/resolve":
                    return self._json(data_svc_resolve(data.get("calls") or []))
                if u.path == "/api/sheet/xlsx":
                    s = sheets.get(int(data["id"]))
                    body = sh.to_xlsx(s["name"], s["cells"], data.get("values") or {})
                    return self._send(200, body, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                      {"Content-Disposition": f'attachment; filename="{re.sub(r"[^A-Za-z0-9 _.-]", "_", s["name"])}.xlsx"'})
                if u.path == "/api/studio/start":
                    brief = (data.get("brief") or "").strip()
                    if not brief:
                        return self._json({"error": "write a brief first"}, 400)
                    ticks = [t for t in re.split(r"[\s,]+", data.get("tickers") or "") if t]
                    with resolve_lock:
                        ctx = stdo.build_context(dsvc, index, rooms, ticks, data.get("room") or None, data.get("context") or "")
                    rid = studio_store.create(brief, data.get("persona") or "md", data.get("mode") or "auto", ctx,
                                              {"slides": int(data.get("slides") or 6), "tickers": ticks, "room": data.get("room"),
                                               "token_budget": max(50_000, int(data.get("token_budget") or 0)) if data.get("token_budget") else None})
                    studio_advance(rid)
                    return self._json({"id": rid})
                if u.path == "/api/studio/approve":
                    studio_pipeline().approve_image(data["id"], int(data["n"]), bool(data.get("approve")),
                                                    [c for c in (data.get("comments") or []) if c.strip()])
                    studio_advance(data["id"])
                    return self._json({"ok": True})
                if u.path == "/api/studio/redo":
                    rid, picks = data["id"], [int(n) for n in data.get("slides") or []]
                    if not picks:
                        return self._json({"error": "pick at least one slide"}, 400)

                    def redo_job():
                        studio_running.add(rid)
                        try:
                            studio_pipeline().redo(rid, picks, (data.get("note") or "").strip(), int(data.get("budget") or 200_000))
                        finally:
                            studio_running.discard(rid)
                    if rid in studio_running:
                        return self._json({"error": "this deck is still running"}, 409)
                    threading.Thread(target=redo_job, daemon=True).start()
                    return self._json({"ok": True})
                if u.path == "/api/studio/resume":
                    run = studio_store.load(data["id"])
                    if run["status"] == "error":
                        run["status"], run["error"] = "queued", None
                        studio_store.save(run)
                    studio_advance(data["id"])
                    return self._json({"ok": True})
                if u.path == "/api/check/room":
                    from . import consistency as cs
                    rid = int(data["room"])
                    return self._json({"id": start_check(lambda idx, log: {"kind": "room", "name": Rooms(idx, data_dir).get(rid)["name"],
                                                                           **cs.check_room(idx, Rooms(idx, data_dir), rid, router=Router(), log=log)})})
                if u.path == "/api/model":
                    from . import model3, modelcheck
                    ticker = (data.get("ticker") or "").strip().upper()
                    if not ticker:
                        return self._json({"error": "give a ticker"}, 400)
                    with resolve_lock:
                        st = dsvc.statements(ticker)
                    body, meta = model3.build(st, scenario=int(data.get("scenario") or 1), circ=0 if data.get("circ") in (0, "0", False) else 1)
                    g = modelcheck.grade(body)
                    summary = {"score": g["score"], "production_ready": g["production_ready"],
                               "failing": [r["title"] for r in g["graders"] if not r["passed"]], "warnings": meta["warnings"]}
                    return self._send(200, body, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                      {"Content-Disposition": f'attachment; filename="{ticker} three-statement model.xlsx"',
                                       "X-Model-Grade": json.dumps(summary)[:4000]})
                if u.path == "/api/deck":
                    from . import decks as dk
                    kind = data.get("kind") or ""
                    if kind == "answer" and data.get("ask_id"):
                        job = JOBS.get(f"ask:{data['ask_id']}") or {}
                        if job.get("state") != "done":
                            return self._json({"error": "answer not ready"}, 409)
                        data["result"] = job
                    if kind == "dcf" and data.get("id") and not data.get("cells"):
                        data["cells"] = sheets.get(int(data["id"]))["cells"]
                    with resolve_lock:   # deck builders read SEC data through the shared connection
                        deck, stem = dk.build(kind, data, data_service=dsvc, index=index, rounds=rounds,
                                              brand=settings.brand())
                    body = deck.save()
                    fname = re.sub(r"[^A-Za-z0-9 _.-]", "_", stem)[:80] + ".pptx"
                    return self._send(200, body, "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                      {"Content-Disposition": f'attachment; filename="{fname}"'})
                if u.path == "/api/matrix/column":
                    store.add_column(int(data["id"]), Column(**data["column"]))
                    return self._json({"ok": True})
                if u.path == "/api/matrix/run":
                    mid = int(data["id"])
                    if JOBS.get(f"matrix:{mid}", {}).get("state") == "running":
                        return self._json({"error": "already running"}, 409)
                    run_matrix(mid, data.get("effort") or "medium")
                    return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
            self._json({"error": "not found"}, 404)

    return H


def serve(index: Index, db_path: Path, data_dir: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    srv = ThreadingHTTPServer((host, port), make_handler(index, db_path, data_dir))
    print(f"web app on http://{host}:{port}  (Ctrl-C to stop)")
    srv.serve_forever()
