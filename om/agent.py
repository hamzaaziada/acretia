"""Sheets AI agent: turns an instruction into a validated set of cell edits (model-agnostic).

Flow (the browser drives the loop):
  1. /api/sheet/agent  -> context (sheet snapshot, selection, data catalogue, conventions) + instruction
                          -> Router.complete_json("sheets_agent", ...) -> edit plan {message, operations[]}
  2. Server-side validation: references, formula syntax (balanced parens / quotes), known functions,
     known OM() fields. Invalid operations are dropped and reported back.
  3. The browser applies the plan to a scratch copy, recalculates, and if the new cells produce formula
     errors (#NAME?, #REF!, #PARSE!, #CYCLE!, #DIV/0!, #VALUE!) it calls the agent again with those
     errors (max 2 repair rounds) before showing the preview. The user applies or discards.
Self-repair + strict validation is what makes smaller / cheaper models (e.g. DeepSeek) reliable here.
"""
from __future__ import annotations

import json
import re

from .llm import Part

FUNCTIONS = {"SUM", "AVERAGE", "MEDIAN", "MIN", "MAX", "COUNT", "COUNTA", "QUARTILE", "PERCENTILE", "IF", "IFERROR",
             "ISERROR", "ROUND", "ABS", "SQRT", "POWER", "AND", "OR", "NOT", "NPV", "CONCAT", "CONCATENATE", "LEN",
             "UPPER", "LOWER", "OM", "OMNAME", "MATRIX", "TRUE", "FALSE"}
FORMATS = ["", "num0", "num1", "num2", "pct", "x"]
REF = re.compile(r"^[A-Z]{1,2}[1-9]\d{0,3}$")
RANGE = re.compile(r"^([A-Z]{1,2}[1-9]\d{0,3})(?::([A-Z]{1,2}[1-9]\d{0,3}))?$")
MAX_COL, MAX_ROW = 26, 200

FIELD_BASES = {
    "revenue": "revenue", "gross_profit": "gross profit", "ebitda": "EBITDA (EBIT + D&A)", "ebit": "EBIT (operating income)",
    "net_income": "net income", "fcf": "free cash flow (CFO − capex)", "cfo": "cash from operations", "capex": "capital expenditures",
    "d_and_a": "depreciation & amortization",
}
PERIODS = {"ltm": "last twelve months", "fy": "latest fiscal year", "fy_minus1": "prior fiscal year"}

SYSTEM = """You are an investment-banking modelling assistant operating on a spreadsheet. You receive the
current sheet (cells as `REF: raw input → computed value`), the user's selection and an instruction.
Respond with a JSON edit plan. Follow professional modelling conventions:
- Every assumption goes in its own labelled input cell (hard-coded number); formulas reference it. Never
  bury numbers inside formulas (constants like 0.5, 1, 100 for unit conversion are fine).
- Label every row (column A) and every column header; state units in a header row (e.g. "$ in millions").
- Use the data functions for real data instead of typing numbers:
    =OM(ticker, field)   public-company field from SEC filings (fields listed below; $ fields are in millions)
    =OMNAME(ticker)      company name
    =MATRIX(matrix, document, column)  value from a data-room matrix (list below)
  Percent fields from OM (growth, margins, rule_of_40) are in percent units: divide by 100 for % format.
- Summary statistics for comps/precedents: Max, 75th percentile (QUARTILE(r,3)), Mean, Median, 25th percentile, Min;
  wrap in IFERROR(...,"NM").
- Use absolute references ($B$4) for assumptions referenced from many cells.
- Only these functions exist: SUM AVERAGE MEDIAN MIN MAX COUNT COUNTA QUARTILE PERCENTILE IF IFERROR ISERROR ROUND
  ABS SQRT POWER AND OR NOT NPV CONCAT LEN UPPER LOWER OM OMNAME MATRIX. Operators: + - * / ^ & % = <> < > <= >=.
- Formats: num0 (1,234), num1, num2, pct (0.153 → 15.3%), x (12.3x). Bold for headers and totals.
- Do not overwrite non-empty cells unless the instruction asks you to change them; place new blocks in empty
  space (below or to the right of existing content) and say where you put them.
- Grid is A..Z × 1..200. Keep edits minimal and purposeful. If the user only asks a question, answer in
  `message` with no operations.
- `message`: one to four sentences: what you did / your answer, referencing cells."""


def field_catalog(keys: list[str] | None = None) -> list[str]:
    keys = keys or []
    out = []
    for base, desc in FIELD_BASES.items():
        for per, pdesc in PERIODS.items():
            out.append(f"{base}_{per}: {desc}, {pdesc} ($m, USD)")
        out.append(f"{base}_growth_ltm_yoy: {desc} growth LTM vs prior LTM (%)")
        out.append(f"{base}_growth_fy: {desc} growth latest FY vs prior FY (%)")
    out += [f"margin_{m}_{p}: {m} margin ({p}, %)" for m in ("gross", "ebitda", "ebit", "net", "fcf") for p in ("ltm", "fy")]
    out += [f"expenses_revenue_pct_{e}_ltm: {e} expense as % of revenue (LTM)" for e in ("sm", "ga", "sga", "rd", "opex")]
    out += ["market_cap: market capitalisation ($m; needs licensed price)", "enterprise_value: EV ($m; needs price)",
            "ev_revenue_ltm / ev_ebitda_ltm / ev_ebit_ltm / ev_fcf_ltm / ev_gross_profit_ltm: EV multiples (x; need price)",
            "price_earnings_ltm, price_to_book, price_to_sales, price_to_free_cash_flow: equity multiples (x; need price)",
            "ev_bridge_total_debt_lcu, ev_bridge_cash_lcu, ev_bridge_minority_interest_lcu, ev_bridge_preferred_and_hybrid_lcu: EV bridge items ($m, reporting currency)",
            "lease_liabilities_lcu, total_equity_lcu, total_assets_lcu: balance sheet ($m)",
            "shares_out: shares outstanding (units, not millions)", "eps_diluted_fy: diluted EPS ($)",
            "rule_of_40_ltm_hist: revenue growth + EBITDA margin (%)", "ltm_end, last_fy_end, balance_sheet_date: dates",
            "name, sic_description, reporting_currency: descriptors"]
    if keys:
        known = {line.split(":")[0].split(" ")[0] for line in out}
        extra = [k for k in keys if k not in known and not k.startswith(("check_", "foreign", "is_", "nm_", "cik", "as_of"))]
        if extra:
            out.append("other fields: " + ", ".join(sorted(extra)))
    return out


def schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": ["set", "clear"]},
                        "cell": {"type": "string"},
                        "value": {"type": "string"},
                        "format": {"type": "string", "enum": FORMATS},
                        "bold": {"type": "boolean"},
                    },
                    "required": ["op", "cell", "value", "format", "bold"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["message", "operations"],
        "additionalProperties": False,
    }


def _ref_rc(ref: str) -> tuple[int, int]:
    m = re.fullmatch(r"([A-Z]{1,2})(\d+)", ref)
    c = 0
    for ch in m.group(1):
        c = c * 26 + ord(ch) - 64
    return int(m.group(2)), c


def snapshot(cells: dict, values: dict, limit: int = 600) -> str:
    """Compact, row-ordered sheet view for the prompt."""
    keys = sorted(cells, key=lambda k: _ref_rc(k))
    lines = []
    for k in keys[:limit]:
        raw = str(cells[k])
        v = values.get(k)
        shown = "" if v is None else (f"{v:.6g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
        lines.append(f"{k}: {raw}" + (f" → {shown}" if raw.startswith("=") and shown != "" else ""))
    if len(keys) > limit:
        lines.append(f"… {len(keys) - limit} more cells not shown")
    return "\n".join(lines) or "(empty sheet)"


def build_prompt(instruction: str, cells: dict, values: dict, selection: str | None, matrices: list[dict],
                 field_keys: list[str] | None = None, errors: list[str] | None = None, history: list[dict] | None = None):
    used_rows = max((_ref_rc(k)[0] for k in cells), default=0)
    used_cols = max((_ref_rc(k)[1] for k in cells), default=0)
    ctx = ["Available OM() fields:", *[f"- {f}" for f in field_catalog(field_keys)]]
    if matrices:
        ctx.append("\nAvailable matrices for MATRIX(matrix, document, column):")
        for m in matrices[:20]:
            ctx.append(f"- \"{m['name']}\": documents {m['documents'][:12]}; columns {m['columns']}")
    stable = "\n".join(ctx)                       # stable across calls -> cache-friendly prefix
    sheet = (f"Current sheet (used range A1:{chr(64 + max(used_cols, 1))}{max(used_rows, 1)}; first empty row {used_rows + 2}):\n"
             f"{snapshot(cells, values)}\n\nSelection: {selection or 'none'}")
    convo = ""
    if history:
        convo = "\n\nEarlier in this conversation:\n" + "\n".join(f"{h['role']}: {h['text'][:500]}" for h in history[-6:])
    task = f"{convo}\n\nInstruction: {instruction}"
    if errors:
        task += ("\n\nYour previous edit plan was applied to a scratch copy and produced these problems; return a "
                 "corrected COMPLETE plan (all operations, not only fixes):\n" + "\n".join(f"- {e}" for e in errors[:40]))
    return SYSTEM, [Part(stable, cache=True), Part(sheet), Part(task)], schema()


# --------------------------------------------------------------------------- validation
def check_formula(f: str, field_keys: set[str] | None = None) -> str | None:
    body = f[1:]
    if body.count('"') % 2:
        return "unbalanced quotes"
    stripped = re.sub(r'"[^"]*"', '""', body)
    depth = 0
    for ch in stripped:
        depth += ch == "("
        depth -= ch == ")"
        if depth < 0:
            return "unbalanced parentheses"
    if depth:
        return "unbalanced parentheses"
    for name in re.findall(r"([A-Za-z_][A-Za-z0-9_.]*)\s*\(", stripped):
        if name.upper() not in FUNCTIONS:
            return f"unknown function {name}"
    for ref in re.findall(r"\$?([A-Z]{1,2})\$?(\d+)", stripped):
        r, c = int(ref[1]), _ref_rc(ref[0] + "1")[1]
        if not (1 <= r <= MAX_ROW and 1 <= c <= MAX_COL):
            return f"reference {ref[0]}{ref[1]} outside the grid"
    if field_keys:
        for fld in re.findall(r'OM\s*\([^,]+,\s*"([a-z0-9_]+)"', body, flags=re.I):
            if fld not in field_keys:
                return f"unknown OM field {fld}"
    return None


def validate_plan(plan: dict, field_keys: set[str] | None = None) -> tuple[list[dict], list[str]]:
    ok, problems = [], []
    for i, op in enumerate(plan.get("operations", [])[:800]):
        cell = str(op.get("cell", "")).upper().replace("$", "")
        if op.get("op") == "clear":
            m = RANGE.match(cell)
            if not m:
                problems.append(f"operation {i}: bad range {cell!r}")
                continue
            ok.append({"op": "clear", "cell": cell})
            continue
        if not REF.match(cell) or not (1 <= _ref_rc(cell)[1] <= MAX_COL and _ref_rc(cell)[0] <= MAX_ROW):
            problems.append(f"operation {i}: bad cell {cell!r}")
            continue
        val = str(op.get("value", ""))
        if val.startswith("="):
            err = check_formula(val, field_keys)
            if err:
                problems.append(f"{cell}: {err} in {val}")
                continue
        fmt = op.get("format") if op.get("format") in FORMATS else ""
        ok.append({"op": "set", "cell": cell, "value": val, "format": fmt, "bold": bool(op.get("bold"))})
    return ok, problems


def run(router, instruction: str, cells: dict, values: dict, selection: str | None = None, matrices: list | None = None,
        field_keys: list[str] | None = None, errors: list[str] | None = None, history: list | None = None) -> dict:
    system, parts, sch = build_prompt(instruction, cells, values, selection, matrices or [], field_keys, errors, history)
    res = router.complete_json("sheets_agent", system, parts, sch, max_tokens=16000)
    ops, problems = validate_plan(res.data, set(field_keys) if field_keys else None)
    return {"message": res.data.get("message", ""), "operations": ops, "problems": problems,
            "model": res.model, "usage": res.usage, "repaired_json": res.repaired}


def matrices_for_prompt(db) -> list[dict]:
    out = []
    for m in db.execute("SELECT id, name, columns FROM matrices ORDER BY created_at DESC LIMIT 20"):
        docs = [r[0] for r in db.execute("SELECT d.title FROM matrix_rows r JOIN documents d ON d.doc_id=r.doc_id WHERE r.matrix_id=?", (m[0],))]
        out.append({"name": m[1], "documents": docs, "columns": [c["name"] for c in json.loads(m[2] or "[]")]})
    return out
