# S8 shared contract (Boss)

All S8 packets build against these interfaces. Field names are binding; add fields, never rename.

## `om/intl/types.py` (S8.4 owns)

```python
@dataclass
class Figure:                       # one number read from a report
    key: str | None                 # om.statements.LINES key, or None when unmapped
    label: str                      # label as printed (original script)
    value: float | None             # reporting-currency MILLIONS, sign as om.statements expects (expenses negative
                                    # where LINES sign is -1 and the report shows them as deductions)
    raw: str                        # the printed number token, untouched
    scale: float                    # multiplier the printed unit implies (1e3 for '000) before conversion to millions
    period_end: date
    period_start: date | None
    statement: str | None           # "IS" | "BS" | "CF" | "OCI" | "EQ"
    page: int                       # 1-based
    bbox_norm: tuple                # bbox of the number token, top-left origin, [0,1]
    label_bbox: tuple | None
    confidence: float               # 0..1 combined (ocr x parse x mapping), after tie corroboration
    ocr_conf: float | None          # 0..1 raw OCR word confidence; None for native text
    source: str                     # "native" | "ocr"
    doc_id: str                     # sha256 of the PDF bytes (om.pdfdoc convention)
    sha256_span_hash: str           # om.pdfdoc.span_hash(page, raw, bbox_norm)
    status: str = "ok"              # "ok" | "review"
    reasons: list = field(default_factory=list)
    row: int | None = None          # row index within its statement table (extractor-assigned)
    is_total: bool = False          # printed as a subtotal/total row
    components: list | None = None  # indices into ExtractedStatements.figures that this total sums (same period)

@dataclass
class ExtractedStatements:
    doc_id: str
    company: str
    currency: str                   # ISO 4217
    unit_scale: float               # printed unit (1, 1e3, 1e6)
    periods: list                   # period-end dates, oldest first
    figures: list                   # Figure
    standard: str | None            # "IFRS" | "EAS" | "SOCPA-IFRS" | ...
    language: str                   # "en" | "ar" | "bi"
    fiscal_year_end_month: int
    source_url: str | None = None
    warnings: list = field(default_factory=list)

class IntlItem(om.statements.Item):   # facts=[]; adds citation: om.contracts.Citation, confidence: float, figure: Figure
    def source(self) -> str: ...      # "p.<page> bbox <x0,y0,x1,y1> conf <c> '<raw>' <doc_id[:12]>"

class IntlStatements(om.statements.Statements):
    standard: str | None; language: str; basis_flags: dict; review: list; release_report: "TieReport"
```

`IntlStatements.data` holds an `IntlItem` for every `om.statements.LINES` key and period (value None when not
reported), so `om.model3.build` runs unchanged. `filings[i]` = `{"form": "<standard> annual report", "accn": doc_id[:12],
"url": source_url or ""}`. Only `om/intl/tieout.py` constructs `IntlStatements`.

## Other modules

| Module | Owner | Public API |
|---|---|---|
| `om/intl/numparse.py` | S8.3a | `parse_number(token) -> ParsedNumber(value: float|None, is_nil, negative, kind: "number"|"nil"|"note_ref"|"year"|"percent"|"text")`, `normalise_digits(s)`, `detect_unit(text) -> (currency|None, scale|None)`, `parse_period_header(text) -> date|None` |
| `om/intl/ocr.py` | S8.3a | `ocr_page_image(png_bytes, langs="ara+eng", psm=...) -> list[OcrWord(text, conf 0..1, bbox_norm)]`, `ocr_pdf(path, pages=None, dpi=300) -> om.pdfdoc.PdfDoc` with Word.ocr=True and per-word confidence available (`word_conf: dict[span_hash, float]` on the doc or a `conf` attribute on Word subclass) |
| `om/intl/labels.py` | S8.2 | `normalise_ar(s)`, `normalise_label(s)`, `match(label, *, statement=None) -> LabelMatch(key, confidence, sign_hint, lang, is_total)` or None |
| `om/intl/concepts.py` | S8.2 | `IFRS_TO_KEY: dict[str, str]`, `concept_to_key(qname) -> str | None`, `key_to_concepts(key) -> list[str]` |
| `om/intl/standards/` | S8.1 | `load() -> KB`; `KB.frameworks`, `KB.differences`, `KB.find(topic=None, framework=None)`, `KB.answer(question) -> Answer(text, citations, entries)` (deterministic retrieval) |
| `om/intl/tieout.py` | S8.4 | `check(ex, *, prior=None) -> TieReport(passed, ties: list[Tie(name, period, lhs, rhs, diff, passed, figures)])`, `release(ex, report=None, *, strict=True) -> IntlStatements`, `ReleaseBlocked` |
| `om/intl/review.py` | S8.4 | `queue(ex, report, *, pdf=None) -> list[ReviewItem(figure, reasons, page, bbox_norm, crop_png: bytes|None)]`, `to_jsonl(items)` |
| `om/intl/fx.py` | S8.6a | `IntlFX(rates_path)`, `.rate(ccy, day)`, `.average(ccy, start, end)`, `.devaluation_flags(ccy, start, end, threshold=0.15)`, `translate(statements, to_ccy, fx)` (BS end rate, flows average) |
| `om/intl/calendar.py` | S8.6a | `calendarise(values_by_fy_end: dict[date, float], target_month=12) -> dict[date, float]` + weights |
| `om/intl/adjust.py` | S8.6a | recipe functions named by KB recipe ids, e.g. `ifrs16_to_pre16_ebitda`, `lease_adjusted_net_debt`, `zakat_as_tax`, `by_nature_ebit`, `ias29_restate`, `eosb_as_debt_like`, ...; `RECIPES: dict[str, callable]` |
| `om/intl/extract.py` | S8.3b (wave 2) | `extract(pdf, *, company=None, hints=None) -> ExtractedStatements` |

## Numbers and signs

- Values are stored in reporting-currency millions (printed value x scale / 1e6).
- Brackets, a leading or trailing minus and the Arabic minus all mean negative.
- Statements keep the sign convention of `om.statements.LINES`: for lines with sign -1 (cogs, sga, tax, capex,
  dividends ...) the stored value is the value as XBRL would report it (a positive expense). When a report prints
  an expense in brackets, the extractor flips it to positive for those keys and records `reasons += ["sign:deduction"]`.

## Keys beyond `om.statements.LINES`

`Figure.key` may also be one of `om.intl.labels.EXTRA_KEYS`, all prefixed `x.`: `x.zakat`, `x.rou_assets`,
`x.lease_liabilities_current`, `x.lease_liabilities_noncurrent`, `x.lease_interest`, `x.rou_depreciation`, `x.eosb`,
`x.employee_costs`, `x.raw_materials`, `x.depreciation`, `x.amortisation`, `x.other_opex`, `x.other_income`,
`x.fx_gain_loss`, `x.share_of_associates`, `x.nci_profit`, `x.oci_total`, `x.total_comprehensive_income`,
`x.investment_property`, `x.cash_beginning`, `x.cash_end`, `x.fx_effect_cash`, `x.selling_expenses`, `x.admin_expenses`,
`x.gov_grants`, `x.capitalised_dev`, `x.provisions`, `x.retained_earnings`, `x.share_capital`, `x.nci_equity`,
`x.noncurrent_assets`, `x.noncurrent_liabilities`, `x.eps_basic`, `x.changes_in_inventories`, `x.finance_costs_net`.
The labels packet may add more `x.` keys; it never removes these.

Derived figures (e.g. EBIT computed from a by-nature P&L) have `source="derived"`, `components` set, `confidence`
= min of components, the union bbox of the components on their page, and a `basis_flags` entry on release.

## Adjustment recipe ids (S8.1 references them, S8.6a implements them in `om.intl.adjust.RECIPES`)

`ifrs16_to_pre16_ebitda`, `lease_adjusted_net_debt`, `capitalise_operating_leases`, `zakat_as_tax`, `by_nature_ebit`,
`ias29_restate`, `fx_translate_period_end_average`, `devaluation_fx_loss_normalise`, `eosb_as_debt_like`,
`dev_cost_expense`, `revaluation_reverse`, `impairment_reversal_strip`, `capitalised_interest_expense`, `lifo_to_fifo`,
`gov_grant_gross_up`, `associates_share_strip`, `revenue_principal_agent_net`, `eas_to_ifrs_map`.
Signature: `fn(values: dict[str, float | None], **params) -> dict` with keys `adjusted` (dict), `flags` (list[str]),
`explain` (one sentence, our words).
