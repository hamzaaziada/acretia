"""Ask: cited research assistant over filings, data rooms, financials, funding rounds and precedents.

Fast, model-agnostic loop (works on DeepSeek, Claude, local models — anything with JSON output):
  1. PLAN    the model returns a batch of tool calls (≤ 6) for the question
  2. ACT     all calls run in parallel on local data (SQLite FTS, cached SEC facts) — milliseconds to seconds
  3. (one optional extra PLAN/ACT round if the model says it needs more)
  4. ANSWER  the model writes markdown with [n] citation markers, each mapped to a source id + supporting quote
  5. VERIFY  document quotes must appear verbatim in the cited passage; data citations must reference a
             value that was actually returned. Unverifiable citations are flagged, never silently kept.
With no model configured, `run_without_model` returns the same sources as a structured result.
"""
from __future__ import annotations

import csv
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .llm import LLMError, LLMRefusal, Part

MAX_CALLS = 6
TOOLS = {
    "search_documents": "Full-text search of SEC filings and data-room documents. args: {query (FTS syntax: words, \"phrases\", OR, NOT, prefix*), tickers?: [..], forms?: [..], room?: id, limit?: ≤10}",
    "company_financials": "Key financials and multiples from SEC filings for one company. args: {ticker, fields?: [field names]} — default fields cover revenue, growth, margins, EBITDA, net income, FCF, EV bridge, multiples",
    "funding_rounds": "Private funding rounds from SEC Form D. args: {company?, industry?, min_sold?, date_from? (YYYY-MM-DD), sort?: date|amount, limit?: ≤15}",
    "precedent_transactions": "M&A deals and multiples from merger-proxy fairness opinions. args: {query (target/acquirer/advisor words), limit?: ≤15}",
}
DEFAULT_FIELDS = ["name", "ltm_end", "revenue_ltm", "revenue_growth_ltm_yoy", "margin_gross_ltm", "ebitda_ltm", "margin_ebitda_ltm",
                  "net_income_ltm", "fcf_ltm", "revenue_fy", "revenue_fy_minus1", "ev_bridge_total_debt_lcu", "ev_bridge_cash_lcu",
                  "market_cap", "enterprise_value", "ev_revenue_ltm", "ev_ebitda_ltm", "price_earnings_ltm", "reporting_currency"]

PLAN_SYSTEM = """You are a senior research analyst at an investment bank. Plan the lookups needed to answer the
user's question using ONLY these tools (they query local databases of SEC filings, data-room documents,
financials, funding rounds and precedent deals):
{tools}
Return up to {max_calls} tool calls that together gather everything needed; make queries specific (company
names, tickers, exact phrases). Prefer several targeted calls in parallel over one broad call. If the
conversation already contains enough sources, return no calls."""

ANSWER_SYSTEM = """You are a senior research analyst writing for bankers and investors. Answer the question
using ONLY the sources provided (each has an id like D3, F1, R2, T4). Style: lead with the direct answer in
one or two sentences, then supporting detail in short paragraphs or bullets; include specific figures with
units and periods; no filler. Every factual sentence ends with citation markers like [1] or [1][2].
`citations` maps each marker number to a source id and a short verbatim quote (for documents: copied exactly
from the source text; for data sources F/R/T: the exact field and value, e.g. "revenue_ltm: 478834").
If the sources do not answer the question, say so plainly and suggest what to search next. Never invent
figures."""


def plan_schema() -> dict:
    return {"type": "object", "properties": {
        "tool_calls": {"type": "array", "items": {"type": "object", "properties": {
            "tool": {"type": "string", "enum": list(TOOLS)},
            "args": {"type": "object"}}, "required": ["tool", "args"]}},
        "reason": {"type": "string"}}, "required": ["tool_calls", "reason"]}


def answer_schema() -> dict:
    return {"type": "object", "properties": {
        "answer_markdown": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "object", "properties": {
            "n": {"type": "integer"}, "source_id": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["n", "source_id", "quote"], "additionalProperties": False}},
        "follow_ups": {"type": "array", "items": {"type": "string"}}},
        "required": ["answer_markdown", "citations", "follow_ups"], "additionalProperties": False}


class Tools:
    def __init__(self, index, data_service=None, rounds=None, deals_csv: Path | None = None):
        self.index, self.data, self.rounds, self.deals_csv = index, data_service, rounds, deals_csv

    def search_documents(self, query: str, tickers=None, forms=None, room=None, limit: int = 8) -> list[dict]:
        f = {}
        if tickers:
            f["tickers"] = [str(t).upper() for t in tickers]
        if forms:
            f["forms"] = list(forms)
        if room:
            f["room"] = room
        res = self.index.search(query, f, limit=min(int(limit or 8), 10), per_doc=2)
        out = []
        for d in res["results"]:
            for p in d["passages"]:
                text = self.index.db.execute("SELECT text FROM chunks WHERE chunk_id=?", (p["chunk_id"],)).fetchone()[0]
                out.append({"kind": "document", "chunk_id": p["chunk_id"], "doc_id": d["doc_id"], "company": d["company"],
                            "ticker": d["ticker"], "form": d["form"], "filed": d["filed"], "title": d["title"],
                            "section": p["section"], "url": d["url"], "text": text[:2200]})
        return out

    def company_financials(self, ticker: str, fields=None) -> list[dict]:
        if not self.data:
            return []
        row, prov = self.data.comps_row(str(ticker))
        flds = [f for f in (fields or DEFAULT_FIELDS) if f in row] or DEFAULT_FIELDS
        vals = {f: row.get(f) for f in flds if row.get(f) is not None}
        src = None
        for f in flds:
            p = prov.get(f) or prov.get(f"{f}_lcu")
            if p and p.get("facts"):
                f0 = p["facts"][0]
                src = f"https://www.sec.gov/Archives/edgar/data/{row['cik']}/{f0['accn'].replace('-', '')}/"
                break
        return [{"kind": "financials", "ticker": str(ticker).upper(), "company": row.get("name"), "values": vals,
                 "note": "$ figures in millions (USD unless reporting_currency differs); percent fields in %", "url": src}]

    def funding_rounds(self, company: str = "", industry: str = "", min_sold=None, date_from: str = "", sort: str = "date",
                       limit: int = 10) -> list[dict]:
        if not self.rounds:
            return []
        res = self.rounds.search(company or "", industry or "", "", float(min_sold) if min_sold else None, date_from or "",
                                 sort=sort if sort in ("date", "amount", "investors") else "date", limit=min(int(limit or 10), 15))
        return [{"kind": "round", **{k: r[k] for k in ("company", "industry", "city", "state", "country", "first_sale_date",
                                                         "last_filed", "amount_sold", "offering_amount", "investors", "securities",
                                                         "year_incorporated", "revenue_range", "url")}} for r in res["results"]]

    def precedent_transactions(self, query: str = "", limit: int = 10) -> list[dict]:
        if not self.deals_csv or not Path(self.deals_csv).exists():
            return []
        words = [w for w in (query or "").lower().split() if len(w) > 1]
        out = []
        with open(self.deals_csv, newline="") as fh:
            for r in csv.DictReader(fh):
                text = f"{r['target']} {r['acquirer']} {r['advisors']}".lower()
                if words and not any(w in text for w in words):
                    continue
                mults = {k: r[k] for k in r if r[k] and (k.startswith(("ev_", "equity_")) and not k.endswith(("_n", "_disagreement")))}
                out.append({"kind": "deal", "target": r["target"], "acquirer": r["acquirer"], "announced": r["announced"],
                            "advisors": r["advisors"], "multiples": mults, "url": (r["sources"] or "").split(" ")[0]})
                if len(out) >= min(int(limit or 10), 15):
                    break
        return out

    def run(self, call: dict) -> list[dict]:
        fn = getattr(self, call.get("tool", ""), None)
        if not fn or call["tool"] not in TOOLS:
            return []
        args = call.get("args") or {}
        try:
            import inspect
            params = inspect.signature(fn).parameters
            if any(p.kind == p.VAR_KEYWORD for p in params.values()):
                return fn(**args)
            return fn(**{k: v for k, v in args.items() if k in params})   # drop unknown args a model may invent
        except Exception as e:
            return [{"kind": "error", "tool": call["tool"], "error": repr(e)[:200]}]


# --------------------------------------------------------------------------- source registry
PREFIX = {"document": "D", "financials": "F", "round": "R", "deal": "T"}


class Sources:
    def __init__(self):
        self.items: dict[str, dict] = {}
        self._keys: dict[str, str] = {}

    def add(self, items: list[dict]) -> None:
        for it in items:
            if it.get("kind") not in PREFIX:
                continue
            k = json.dumps({k: it.get(k) for k in ("kind", "chunk_id", "ticker", "company", "first_sale_date", "target", "acquirer")}, sort_keys=True)
            if k in self._keys:
                continue
            sid = f"{PREFIX[it['kind']]}{sum(1 for s in self.items if s[0] == PREFIX[it['kind']]) + 1}"
            self._keys[k] = sid
            self.items[sid] = {"id": sid, **it}

    def render(self) -> str:
        blocks = []
        for sid, s in self.items.items():
            if s["kind"] == "document":
                blocks.append(f"[{sid}] {s['company']} {s['form']} filed {s['filed']} — {s.get('section') or ''}\n{s['text']}")
            elif s["kind"] == "financials":
                blocks.append(f"[{sid}] {s['company']} ({s['ticker']}) financials ({s['note']}): " + json.dumps(s["values"]))
            elif s["kind"] == "round":
                blocks.append(f"[{sid}] Form D round: " + json.dumps({k: v for k, v in s.items() if k not in ("id", "kind", "url")}))
            elif s["kind"] == "deal":
                blocks.append(f"[{sid}] Precedent deal: " + json.dumps({k: v for k, v in s.items() if k not in ("id", "kind", "url")}))
        return "\n\n".join(blocks) or "(no sources found)"


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    return re.sub(r"[^a-z0-9$%.,'\-]+", " ", s).strip()


def verify_citations(citations: list[dict], sources: Sources) -> list[dict]:
    out = []
    for c in citations:
        s = sources.items.get(str(c.get("source_id", "")).strip("[] "))
        q = c.get("quote") or ""
        ok = False
        if s and s["kind"] == "document":
            ok = bool(q) and _norm(q) in _norm(s["text"])
        elif s:
            blob = _norm(json.dumps(s, default=str))
            nums = re.findall(r"-?\d[\d,]*\.?\d*", q)
            ok = bool(nums) and all(_norm(n.replace(",", "")) in blob.replace(",", "") for n in nums)
        out.append({**c, "verified": ok, "exists": bool(s)})
    return out


# --------------------------------------------------------------------------- loop
def run(router, tools: Tools, question: str, history: list[dict] | None = None, scope: dict | None = None,
        progress=None) -> dict:
    t0 = time.time()
    scope = scope or {}
    sources = Sources()
    convo = "\n".join(f"{h['role']}: {h['text'][:800]}" for h in (history or [])[-6:])
    tool_text = "\n".join(f"- {k}: {v}" for k, v in TOOLS.items())
    scope_note = (f"\nScope: search_documents must use room={scope['room']} (the user's data room)." if scope.get("room") else
                  "\nScope: public filings only." if scope.get("public_only") else "")
    usage, models, calls_made = [], set(), []

    def step(msg):
        if progress:
            progress(msg)

    for round_no in range(2):
        step("Planning lookups…" if round_no == 0 else "Gathering more sources…")
        plan = router.complete_json(
            "ask", PLAN_SYSTEM.format(tools=tool_text, max_calls=MAX_CALLS) + scope_note,
            [Part(f"Conversation so far:\n{convo or '(none)'}"),
             Part(f"Sources gathered so far:\n{sources.render()[:6000] if sources.items else '(none)'}"),
             Part(f"Question: {question}")], plan_schema(), max_tokens=2000, effort="low")
        usage.append(plan.usage)
        models.add(plan.model)
        calls = plan.data.get("tool_calls", [])[:MAX_CALLS]
        if scope.get("room"):
            for c in calls:
                if c.get("tool") == "search_documents":
                    c.setdefault("args", {})["room"] = scope["room"]
        if not calls:
            break
        step(f"Running {len(calls)} lookup(s) in parallel…")
        with ThreadPoolExecutor(max_workers=6) as ex:
            for res in ex.map(tools.run, calls):
                sources.add(res)
        calls_made += calls
        if len(sources.items) >= 12:
            break
    step(f"Writing the answer from {len(sources.items)} sources…")
    ans = router.complete_json("ask", ANSWER_SYSTEM, [
        Part(f"Sources:\n{sources.render()}", cache=True),
        Part(f"Conversation so far:\n{convo or '(none)'}\n\nQuestion: {question}")], answer_schema(), max_tokens=6000)
    usage.append(ans.usage)
    models.add(ans.model)
    cites = verify_citations(ans.data.get("citations", []), sources)
    used = {c["source_id"] for c in cites if c["exists"]}
    return {"answer": ans.data.get("answer_markdown", ""), "citations": cites, "follow_ups": ans.data.get("follow_ups", [])[:4],
            "sources": [s for sid, s in sources.items.items() if sid in used] + [s for sid, s in sources.items.items() if sid not in used],
            "tool_calls": calls_made, "models": sorted(models), "seconds": round(time.time() - t0, 1),
            "verified": sum(c["verified"] for c in cites), "unverified": sum(not c["verified"] for c in cites),
            "usage": {k: sum((u or {}).get(k) or 0 for u in usage) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")}}


TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")


def run_without_model(tools: Tools, question: str, scope: dict | None = None, known_tickers: set[str] | None = None) -> dict:
    """No LLM: run sensible lookups directly and return structured sources (no prose)."""
    t0 = time.time()
    scope = scope or {}
    sources = Sources()
    q_words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9&.\-]{2,}", question)
               if w.lower() not in {"what", "which", "how", "the", "and", "for", "with", "does", "did", "are", "was", "about", "from", "this", "that", "their", "its"}]
    tickers = [t for t in TICKER_RE.findall(question) if known_tickers and t in known_tickers][:3]
    topic = [w for w in q_words if w not in tickers and w.lower() not in
             {"affected", "funding", "rounds", "round", "raise", "raised", "startups", "companies", "company", "say", "said"}]
    fts = " OR ".join(f'"{w}"*' for w in topic[:6]) or question
    doc_args = {"query": fts, "room": scope.get("room"), "limit": 8}
    if tickers and not scope.get("room"):
        doc_args["tickers"] = tickers              # keep document hits on the companies asked about
    calls = [{"tool": "search_documents", "args": doc_args}]
    calls += [{"tool": "company_financials", "args": {"ticker": t}} for t in tickers]
    if re.search(r"(?i)round|raise|raised|funding|venture|series|form d", question):
        names = [w for w in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", question) if w not in tickers and w.lower() not in
                 {"how", "what", "which", "who", "when", "the", "and", "series", "form", "did", "does"}]
        calls.append({"tool": "funding_rounds", "args": {"company": names[0] if len(names) == 1 else "", "sort": "amount",
                                                         "date_from": "", "limit": 10}})
    if re.search(r"(?i)deal|acqui|merger|precedent|m&a|takeover", question):
        calls.append({"tool": "precedent_transactions", "args": {"query": " ".join(q_words[:4])}})
    with ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(tools.run, calls):
            sources.add(res)
    return {"answer": "", "citations": [], "follow_ups": [], "sources": list(sources.items.values()), "tool_calls": calls,
            "models": [], "seconds": round(time.time() - t0, 2), "no_model": True}
