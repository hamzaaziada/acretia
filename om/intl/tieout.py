"""Tie-out and confidence gate for extracted statements (S8.4).

`check` runs the arithmetic ties a real set of statements must satisfy, marks every figure that fails a hard tie
(or is low-confidence and uncorroborated) as `status="review"`, and raises the confidence of figures a passing hard
tie corroborates. `release` is the only door from an `ExtractedStatements` to an `om.statements.Statements`
(an `IntlStatements`): in strict mode it refuses (`ReleaseBlocked`) while a hard tie fails or a figure the model needs
is in review, so nothing unverified reaches `om.model3`.

Conventions (decisions, see DECISIONS.md D-S8-xx):
* Tolerance = n_terms x 0.5 x unit_scale / 1e6 + 1e-9, n_terms = every figure in the tie (the printed total is
  rounded too), in millions. Values are millions, as in `om.statements`.
* Signs are as `om.statements.LINES`: expenses (cogs, tax, x.zakat) are positive numbers.
* A column is restated when any of its figures has "restated" in `reasons`, or `ex.warnings` holds
  "restated:<YYYY-MM-DD>". A prior-comparative mismatch there is flagged (warning), not failed.
* A figure that matches the prior report counts as corroborated, like a passing hard tie (two independent reports).
* Derived figures (`source == "derived"`) are never tie-checked as sums and never corroborated by their own parts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import statements as stm
from ..contracts import Citation
from .types import ExtractedStatements, IntlItem, IntlStatements

REQUIRED = ("revenue", "ebit", "pretax", "net_income", "assets", "current_assets", "current_liabilities", "cfo", "cfi", "cff")
LOW_CONFIDENCE = 0.80
CORROBORATED = 0.95


@dataclass
class Tie:
    name: str
    period: object
    lhs: float
    rhs: float
    diff: float
    passed: bool
    figures: list                    # indices into ex.figures
    hard: bool = True
    tol: float = 0.0
    restated: bool = False


@dataclass
class TieReport:
    passed: bool                     # every hard tie passed
    ties: list
    warnings: list = field(default_factory=list)
    review: dict = field(default_factory=dict)       # figure index -> reasons added by this check
    corroborated: list = field(default_factory=list)  # figure indices raised to >= 0.95

    @property
    def failed(self) -> list:
        return [t for t in self.ties if not t.passed]


class ReleaseBlocked(Exception):
    def __init__(self, report: TieReport, review_items: list):
        self.report, self.review_items = report, review_items
        bad = [f"{t.name}@{t.period}" for t in report.failed if t.hard]
        keys = sorted({f"{f.key}@{f.period_end}" for f in review_items if f.key in REQUIRED})
        super().__init__(f"release blocked: failed ties {bad or 'none'}; required figures in review {keys or 'none'}")


def _index(ex) -> dict:
    by = {}
    for i, f in enumerate(ex.figures):
        if f.key and f.value is not None:
            by.setdefault((f.key, f.period_end), i)
    return by


def _restated(ex) -> set:
    out = {f.period_end for f in ex.figures if "restated" in (f.reasons or [])}
    for w in ex.warnings or []:
        m = re.fullmatch(r"restated:(\d{4}-\d{2}-\d{2})", str(w))
        if m:
            out.add(m.group(1))
    return {p if isinstance(p, str) else p.isoformat() for p in out}


def check(ex: ExtractedStatements, *, prior: ExtractedStatements | None = None) -> TieReport:
    figs, by = ex.figures, _index(ex)
    ties: list[Tie] = []
    warnings: list[str] = []

    def unit(*others):
        return max([ex.unit_scale] + [o.unit_scale for o in others])

    def add(name, period, lhs, rhs, idxs, *, hard=True, u=None):
        tol = len(idxs) * 0.5 * (u or unit()) / 1e6 + 1e-9
        d = lhs - rhs
        t = Tie(name, period, lhs, rhs, d, abs(d) <= tol, list(idxs), hard, tol)
        ties.append(t)
        return t

    # (i) figures that are the sum of their components
    for i, f in enumerate(figs):
        if not f.components or f.value is None or f.source == "derived":
            continue
        comps = [figs[j] for j in f.components if 0 <= j < len(figs)]
        if len(comps) != len(f.components) or any(c.value is None for c in comps):
            continue
        add(f"sum:{f.key or f.label}", f.period_end, f.value, sum(c.value for c in comps), [i] + list(f.components))

    for p in sorted({f.period_end for f in figs}):
        g = lambda k: figs[by[(k, p)]].value if (k, p) in by else None
        ix = lambda *ks: [by[(k, p)] for k in ks if (k, p) in by]

        if all(g(k) is not None for k in ("revenue", "cogs", "gross_profit")):
            add("revenue-cogs=gross_profit", p, g("revenue") - g("cogs"), g("gross_profit"), ix("revenue", "cogs", "gross_profit"))
        if g("assets") is not None and g("liabilities_equity") is not None:
            add("assets=liabilities+equity", p, g("assets"), g("liabilities_equity"), ix("assets", "liabilities_equity"))
        if g("assets") is not None and g("current_assets") is not None and g("x.noncurrent_assets") is not None:
            add("assets=current+noncurrent", p, g("assets"), g("current_assets") + g("x.noncurrent_assets"),
                ix("assets", "current_assets", "x.noncurrent_assets"))
        if g("liabilities") is not None and g("current_liabilities") is not None and g("x.noncurrent_liabilities") is not None:
            add("liabilities=current+noncurrent", p, g("liabilities"), g("current_liabilities") + g("x.noncurrent_liabilities"),
                ix("liabilities", "current_liabilities", "x.noncurrent_liabilities"))
        if g("liabilities_equity") is not None and g("liabilities") is not None and g("equity_total") is not None:
            add("liabilities_equity=liabilities+equity", p, g("liabilities_equity"), g("liabilities") + g("equity_total"),
                ix("liabilities_equity", "liabilities", "equity_total"))
        if all(g(k) is not None for k in ("cfo", "cfi", "cff", "net_change_cash")):
            add("cfo+cfi+cff=net_change_cash", p, g("cfo") + g("cfi") + g("cff") + (g("x.fx_effect_cash") or 0.0),
                g("net_change_cash"), ix("cfo", "cfi", "cff", "net_change_cash", "x.fx_effect_cash"))
        if all(g(k) is not None for k in ("x.cash_beginning", "net_change_cash", "x.cash_end")):
            add("cash_beginning+change=cash_end", p, g("x.cash_beginning") + g("net_change_cash") + (g("x.fx_effect_cash") or 0.0),
                g("x.cash_end"), ix("x.cash_beginning", "net_change_cash", "x.fx_effect_cash", "x.cash_end"))
        if g("x.cash_end") is not None and g("cash") is not None:    # soft: overdrafts / restricted cash differ
            t = add("cf_cash_end=bs_cash", p, g("x.cash_end"), g("cash"), ix("x.cash_end", "cash"), hard=False)
            if not t.passed:
                warnings.append(f"{p}: cash-flow closing cash ({t.lhs:,.3f}) differs from balance-sheet cash ({t.rhs:,.3f}); "
                                "overdraft or restricted cash?")
        profit = None if g("net_income") is None else g("net_income") + (g("x.nci_profit") or 0.0)
        pidx = ix("net_income", "x.nci_profit")
        if profit is not None and g("cf_net_income") is not None:
            cf = g("cf_net_income")
            if abs(cf - profit) > (len(pidx) + 1) * 0.5 * unit() / 1e6 + 1e-9 \
                    and g("pretax") is not None and abs(cf - g("pretax")) <= 2 * 0.5 * unit() / 1e6 + 1e-9:
                add("cf_start(pretax)=pretax", p, cf, g("pretax"), ix("cf_net_income", "pretax"))   # indirect CF from pretax
            else:
                add("is_profit=cf_net_income", p, profit, cf, pidx + ix("cf_net_income"))
        if profit is not None and g("pretax") is not None and g("tax") is not None:
            add("pretax-tax-zakat=profit", p, g("pretax") - g("tax") - (g("x.zakat") or 0.0), profit,
                ix("pretax", "tax", "x.zakat") + pidx)

    # (vii) prior-report comparatives
    if prior is not None:
        pby, restated = _index(prior), _restated(ex)
        for (k, p), i in sorted(by.items(), key=lambda kv: (str(kv[0][1]), kv[0][0])):
            if (k, p) not in pby:
                continue
            pv = prior.figures[pby[(k, p)]].value
            t = add(f"prior:{k}", p, figs[i].value, pv, [i], u=unit(prior))
            t.tol = 2 * 0.5 * unit(prior) / 1e6 + 1e-9
            t.passed = abs(t.diff) <= t.tol
            if not t.passed and p.isoformat() in restated:
                t.passed, t.restated = True, True
                warnings.append(f"{p}: {k} restated (now {t.lhs:,.3f}, previously {t.rhs:,.3f})")

    fail: dict[int, list] = {}
    ok: set[int] = set()
    for t in ties:
        if not t.hard:
            continue
        if not t.passed:
            for i in t.figures:
                fail.setdefault(i, []).append(f"tie-failed:{t.name}")
        elif not t.restated:
            ok.update(t.figures)
    review: dict[int, list] = {}
    corroborated: list[int] = []
    for i, f in enumerate(figs):
        if f.value is None:
            continue
        add_reasons = None
        if i in fail:
            add_reasons = fail[i]
        elif i in ok and f.source != "derived":
            f.confidence = max(f.confidence, CORROBORATED)
            if "tie-corroborated" not in f.reasons:
                f.reasons.append("tie-corroborated")
            corroborated.append(i)
        elif f.confidence < LOW_CONFIDENCE:
            add_reasons = [f"low-confidence:{f.confidence:.2f}"]
        if add_reasons:
            f.status = "review"
            for r in add_reasons:
                if r not in f.reasons:
                    f.reasons.append(r)
            review[i] = add_reasons
    return TieReport(all(t.passed for t in ties if t.hard), ties, warnings, review, corroborated)


def release(ex: ExtractedStatements, report: TieReport | None = None, *, strict: bool = True) -> IntlStatements:
    """The only constructor of IntlStatements. strict=True raises ReleaseBlocked on a failed hard tie or a required
    figure in review; strict=False releases with every review figure set to None (kept on `.review`)."""
    if report is None:
        report = check(ex)
    in_review = [f for f in ex.figures if f.status == "review"]
    if strict and (not report.passed or any(f.key in REQUIRED for f in in_review)):
        raise ReleaseBlocked(report, in_review)

    periods = sorted({f.period_end for f in ex.figures} | set(ex.periods))
    good, flagged = {}, {}
    for f in ex.figures:
        if f.key in stm.LINES and f.value is not None:
            (flagged if f.status == "review" else good).setdefault((f.key, f.period_end), f)
    data = {}
    for k in stm.LINES:
        row = []
        for p in periods:
            f = good.get((k, p))
            if f is not None:
                cit = Citation(doc_id=f.doc_id, sha256_span_hash=f.sha256_span_hash, page=f.page,
                               bbox_norm=tuple(f.bbox_norm), quote=f.raw, url=ex.source_url or None, as_of=p.isoformat())
                row.append(IntlItem(f.value, [], cit, f.confidence, f))
            elif (k, p) in flagged:
                row.append(IntlItem(None, [], None, flagged[(k, p)].confidence, flagged[(k, p)]))
            else:
                row.append(IntlItem(None))
        data[k] = row
    basis = {}
    for f in ex.figures:
        if f.source == "derived" and f.key:
            basis[f.key] = next((r.split(":", 1)[1] for r in f.reasons if r.startswith("basis:")), "derived")
    name = ex.company or "Company"
    s = IntlStatements(
        ticker=(name.split()[0].upper() if name.split() else "INTL"), name=name, cik=0, currency=ex.currency, years=periods,
        data=data, filings=[{"end": p.isoformat(), "filed": "", "form": f"{ex.standard or 'IFRS'} annual report", "accn": ex.doc_id[:12],
                             "url": ex.source_url or ""} for p in periods],
        warnings=[], financial_format=False, standard=ex.standard, language=ex.language, basis_flags=basis,
        review=list(in_review), release_report=report)
    s.warnings = list(report.warnings) + list(ex.warnings or []) + stm.audit(s)
    for f in in_review:
        s.warnings.append(f"review: {f.key or f.label} {f.period_end} p.{f.page} ({', '.join(f.reasons)})")
    return s
