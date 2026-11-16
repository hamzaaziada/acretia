"""Full annual financial statements from SEC XBRL, every number with its filing.

For each fiscal year (periods picked by real start/end dates, latest-filed value wins, as in om.facts):
  income statement  revenue, cost of revenue, R&D, SG&A, operating income, interest, pre-tax, tax, net income,
                    diluted shares and EPS
  balance sheet     the classified lines bankers model (cash, investments, receivables, inventory, PP&E,
                    goodwill, intangibles, payables, debt) plus the reported totals
  cash flow         net income, D&A, stock comp, operating cash flow, capex, acquisitions, investing,
                    dividends, buybacks, financing, net change in cash

Lines a filer doesn't tag separately are not invented: the model shows them as "other" lines calculated from
the reported totals, so every subtotal ties to the filing by construction and the size of each "other" line
is itself a check on the mapping (see `warnings`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .concepts import DURATION, G, I, INSTANT
from .facts import ANNUAL, Company, Fact

M = 1e6

# key -> (statement, kind, sign, label, chain). sign -1 = shown as an outflow / expense.
# chain entries are (taxonomy, concept); a list of chains means "sum these components" (used when no total is tagged).
LINES: dict[str, tuple] = {
    # ---------------- income statement (duration)
    "revenue": ("IS", "d", 1, "Revenue", DURATION["revenue"]),
    "cogs": ("IS", "d", -1, "Cost of revenue", DURATION["cost_of_revenue"] + [(G, "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization")]),
    "gross_profit": ("IS", "d", 1, "Gross profit (reported)", DURATION["gross_profit"]),
    "rd": ("IS", "d", -1, "Research & development", DURATION["rd"]),
    "sga": ("IS", "d", -1, "Selling, general & administrative", [[(G, "SellingGeneralAndAdministrativeExpense")],
                                                                 [(G, "SellingAndMarketingExpense"), (G, "GeneralAndAdministrativeExpense")],
                                                                 [(I, "SellingGeneralAndAdministrativeExpense")],
                                                                 [(I, "SellingExpense"), (I, "AdministrativeExpense")]]),
    "ebit": ("IS", "d", 1, "Operating income (reported)", DURATION["ebit"]),
    "interest_expense": ("IS", "d", -1, "Interest expense", [(G, "InterestExpense"), (G, "InterestExpenseNonoperating"),
                                                             (G, "InterestExpenseDebt"), (G, "InterestAndDebtExpense"),
                                                             (I, "FinanceCosts"), (I, "InterestExpense")]),
    "interest_income": ("IS", "d", 1, "Interest income", [(G, "InvestmentIncomeInterest"), (G, "InterestIncomeOther"),
                                                           (G, "InvestmentIncomeInterestAndDividend"), (I, "FinanceIncome"),
                                                           (I, "InterestRevenueCalculatedUsingEffectiveInterestMethod")]),
    "pretax": ("IS", "d", 1, "Pre-tax income (reported)", [
        (G, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
        (G, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
        (G, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"), (I, "ProfitLossBeforeTax")]),
    "tax": ("IS", "d", -1, "Income tax", [(G, "IncomeTaxExpenseBenefit"), (I, "IncomeTaxExpenseContinuingOperations")]),
    "net_income": ("IS", "d", 1, "Net income to common (reported)", DURATION["net_income"]),
    "diluted_shares": ("IS", "d", 1, "Diluted weighted shares (m)", DURATION["diluted_shares"]),
    "eps_diluted": ("IS", "d", 1, "Diluted EPS (reported)", DURATION["eps_diluted"]),
    # ---------------- balance sheet (instant)
    "cash": ("BS", "i", 1, "Cash & equivalents", [(G, "CashAndCashEquivalentsAtCarryingValue"), (I, "CashAndCashEquivalents")]),
    "sti": ("BS", "i", 1, "Short-term investments", [(G, "MarketableSecuritiesCurrent"), (G, "ShortTermInvestments"),
                                                     (G, "AvailableForSaleSecuritiesDebtSecuritiesCurrent"), (G, "DebtSecuritiesCurrent"), (I, "CurrentInvestments"),
                                                     (I, "OtherCurrentFinancialAssets")]),
    "ar": ("BS", "i", 1, "Accounts receivable", [(G, "AccountsReceivableNetCurrent"), (G, "ReceivablesNetCurrent"),
                                                (I, "TradeAndOtherCurrentReceivables"), (I, "CurrentTradeReceivables")]),
    "inventory": ("BS", "i", 1, "Inventory", [(G, "InventoryNet"), (G, "InventoryFinishedGoods"), (I, "Inventories")]),
    "current_assets": ("BS", "i", 1, "Total current assets (reported)", [(G, "AssetsCurrent"), (I, "CurrentAssets")]),
    "ppe": ("BS", "i", 1, "PP&E, net", [(G, "PropertyPlantAndEquipmentNet"),
                                        (G, "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"),
                                        (I, "PropertyPlantAndEquipment")]),
    "goodwill": ("BS", "i", 1, "Goodwill", [(G, "Goodwill"), (I, "Goodwill")]),
    "intangibles": ("BS", "i", 1, "Intangible assets, net", [(G, "IntangibleAssetsNetExcludingGoodwill"), (G, "FiniteLivedIntangibleAssetsNet"),
                                                             (I, "IntangibleAssetsOtherThanGoodwill")]),
    "assets": ("BS", "i", 1, "Total assets (reported)", INSTANT["total_assets"]),
    "ap": ("BS", "i", 1, "Accounts payable", [(G, "AccountsPayableCurrent"), (G, "AccountsPayableTradeCurrent"),
                                              (G, "AccountsPayableAndAccruedLiabilitiesCurrent"), (I, "TradeAndOtherCurrentPayables")]),
    "debt_current": ("BS", "i", 1, "Short-term debt", [[(G, "DebtCurrent")],
                                                       [(G, "CommercialPaper"), (G, "LongTermDebtCurrent"), (G, "ShortTermBorrowings"),
                                                        (G, "LongTermDebtAndCapitalLeaseObligationsCurrent"), (G, "OtherShortTermBorrowings")],
                                                       [(I, "CurrentBorrowings")], [(I, "CurrentPortionOfNoncurrentBorrowings"), (I, "ShorttermBorrowings")]]),
    "current_liabilities": ("BS", "i", 1, "Total current liabilities (reported)", [(G, "LiabilitiesCurrent"), (I, "CurrentLiabilities")]),
    "debt_noncurrent": ("BS", "i", 1, "Long-term debt", [(G, "LongTermDebtNoncurrent"), (G, "LongTermDebtAndCapitalLeaseObligations"),
                                                         (G, "LongTermDebtAndFinanceLeaseObligationsNoncurrent"),
                                                         (I, "NoncurrentPortionOfNoncurrentBorrowings"), (I, "NoncurrentBorrowings")]),
    "liabilities": ("BS", "i", 1, "Total liabilities (reported)", INSTANT["total_liabilities"]),
    "equity_parent": ("BS", "i", 1, "Shareholders' equity (reported)", INSTANT["total_equity"]),
    "liabilities_equity": ("BS", "i", 1, "Total liabilities & equity (reported)", [(G, "LiabilitiesAndStockholdersEquity"), (I, "EquityAndLiabilities")]),
    "equity_total": ("BS", "i", 1, "Total equity incl. NCI (reported)", [(G, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"), (I, "Equity")]),
    # ---------------- cash flow (duration)
    "cf_net_income": ("CF", "d", 1, "Net income (incl. NCI)", [(G, "ProfitLoss"), (G, "NetIncomeLoss"), (I, "ProfitLoss")]),
    "da": ("CF", "d", 1, "Depreciation & amortization", [[c] for c in DURATION["d_and_a"]]
           + [[(G, "Depreciation"), (G, "AmortizationOfIntangibleAssets")], [(I, "DepreciationExpense"), (I, "AmortisationExpense")]]),
    "sbc": ("CF", "d", 1, "Stock-based compensation", [(G, "ShareBasedCompensation"), (G, "AllocatedShareBasedCompensationExpense"),
                                                       (I, "AdjustmentsForSharebasedPayments")]),
    "cfo": ("CF", "d", 1, "Cash from operations (reported)", DURATION["cfo"]),
    "capex": ("CF", "d", -1, "Capital expenditure", DURATION["capex"]),
    "acquisitions": ("CF", "d", -1, "Acquisitions, net of cash", [(G, "PaymentsToAcquireBusinessesNetOfCashAcquired"),
                                                                 (I, "CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities")]),
    "cfi": ("CF", "d", 1, "Cash from investing (reported)", [(G, "NetCashProvidedByUsedInInvestingActivities"),
                                                             (G, "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"),
                                                             (I, "CashFlowsFromUsedInInvestingActivities")]),
    "dividends": ("CF", "d", -1, "Dividends paid", [(G, "PaymentsOfDividends"), (G, "PaymentsOfDividendsCommonStock"), (G, "PaymentsOfOrdinaryDividends"),
                                                    (I, "DividendsPaidClassifiedAsFinancingActivities")]),
    "buybacks": ("CF", "d", -1, "Share repurchases", [(G, "PaymentsForRepurchaseOfCommonStock"), (I, "PaymentsToAcquireOrRedeemEntitysShares")]),
    "cff": ("CF", "d", 1, "Cash from financing (reported)", [(G, "NetCashProvidedByUsedInFinancingActivities"),
                                                             (G, "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"),
                                                             (I, "CashFlowsFromUsedInFinancingActivities")]),
    "net_change_cash": ("CF", "d", 1, "Net change in cash (reported)", [
        (G, "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"),
        (G, "CashAndCashEquivalentsPeriodIncreaseDecrease"),
        (G, "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect"),
        (I, "IncreaseDecreaseInCashAndCashEquivalents")]),
}

# registered so om.facts.Company can resolve them like its own metrics
for _k, (_st, _kind, _sign, _label, _chain) in LINES.items():
    _flat = [c for part in _chain for c in part] if _chain and isinstance(_chain[0], list) else _chain
    (DURATION if _kind == "d" else INSTANT).setdefault(f"st.{_k}", _flat)
    for _j, _part in enumerate(_chain if _chain and isinstance(_chain[0], list) else []):
        for _t, _c in _part:
            (DURATION if _kind == "d" else INSTANT).setdefault(f"st.{_k}.{_c}", [(_t, _c)])
from .concepts import UNIT_KIND  # noqa: E402
UNIT_KIND.setdefault("st.diluted_shares", "shares")
UNIT_KIND.setdefault("st.eps_diluted", "per_share")


@dataclass
class Item:
    value: float | None          # $m (shares: millions; EPS: per share), sign as reported in XBRL
    facts: list = field(default_factory=list)

    def source(self) -> str:
        if not self.facts:
            return ""
        return "\n".join(f"{f.taxonomy}:{f.concept} = {f.val:,.0f} {f.unit}, {f.start or ''}{'–' if f.start else ''}{f.end}, "
                         f"{f.form} filed {f.filed}, accn {f.accn}" for f in self.facts)


@dataclass
class Statements:
    ticker: str
    name: str
    cik: int
    currency: str
    years: list[date]                      # fiscal year ends, oldest first
    data: dict                             # key -> [Item per year]
    filings: list[dict]                    # per year: form, accn, url
    warnings: list[str]
    financial_format: bool = False

    def get(self, key: str, i: int) -> float | None:
        return self.data[key][i].value

    def label(self, key: str) -> str:
        return LINES[key][3]


def _url(cik: int, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/"


def _pick(facts: dict, end: date, duration: bool) -> Fact | None:
    best = None
    for k, f in facts.items():
        e = k[1] if duration else k
        if abs((e - end).days) > 4:
            continue
        if duration and not (ANNUAL[0] <= f.days <= ANNUAL[1]):
            continue
        if best is None or f.filed > best.filed:
            best = f
    return best


def _value(co: Company, key: str, end: date) -> Item:
    st, kind, sign, label, chain = LINES[key]
    duration = kind == "d"
    scale = 1.0 if key == "eps_diluted" else M
    if chain and isinstance(chain[0], list):                 # alternatives, each a sum of components
        for part in chain:
            got = [_pick(co.facts(f"st.{key}.{c}"), end, duration) for _, c in part]
            got = [f for f in got if f is not None]
            if got:
                return Item(sum(f.val for f in got) / scale, got)
        return Item(None)
    f = _pick(co.facts(f"st.{key}"), end, duration)
    return Item(f.val / scale, [f]) if f else Item(None)


def build(cf: dict, ticker: str, years: int = 5, sic: int | None = None, as_of: date | None = None) -> Statements:
    co = Company(cf, as_of=as_of)
    ends = sorted({f.end for f in co.annuals("revenue")} | {f.end for f in co.annuals("net_income")})
    # fiscal years that have both a revenue (or net income) figure and a balance sheet
    bs_ends = set(co.facts("st.assets"))
    ends = [e for e in ends if any(abs((e - b).days) <= 4 for b in bs_ends)][-years:]
    data = {k: [_value(co, k, e) for e in ends] for k in LINES}
    filings = []
    for i, e in enumerate(ends):
        fs = [it.facts[0] for k, items in data.items() for it in [items[i]] if it.facts]
        tenk = [f for f in fs if f.form.startswith(("10-K", "20-F", "40-F")) and abs((f.end - e).days) <= 4]
        pick = max(tenk or fs, key=lambda f: f.filed) if fs else None
        filings.append({"end": e.isoformat(), "form": pick.form if pick else "", "accn": pick.accn if pick else "",
                        "filed": pick.filed.isoformat() if pick else "", "url": _url(co.cik, pick.accn) if pick else ""})
    fin = bool(sic and any(a <= sic <= b for a, b in ((6000, 6399), (6700, 6799))))
    s = Statements(ticker.upper(), co.name or ticker, co.cik, co.ccy, ends, data, filings, [], fin)
    s.warnings = audit(s)
    return s


def audit(s: Statements) -> list[str]:
    """Mapping checks: reported totals that are missing, and 'other' lines too large to be plausible."""
    w = []
    for i, e in enumerate(s.years):
        fy = f"FY{e.year}"
        g = lambda k: s.get(k, i)
        for k in ("revenue", "ebit", "pretax", "net_income", "assets", "current_assets", "current_liabilities", "cfo", "cfi", "cff"):
            if g(k) is None:
                w.append(f"{fy}: {s.label(k)} is not tagged")
        rev = g("revenue") or 0
        if rev and g("gross_profit") is not None and g("cogs") is not None and abs(rev - g("cogs") - g("gross_profit")) > 0.005 * rev:
            w.append(f"{fy}: revenue − cost of revenue ({rev - g('cogs'):,.0f}) ≠ reported gross profit ({g('gross_profit'):,.0f})")
        if rev and g("ebit") is not None:
            gp = g("gross_profit") if g("gross_profit") is not None else rev - (g("cogs") or 0)
            other = g("ebit") - gp + (g("rd") or 0) + (g("sga") or 0)
            if abs(other) > 0.15 * rev:
                w.append(f"{fy}: other operating items are {other / rev:+.0%} of revenue; a cost line may be untagged or mis-mapped")
        ca, a = g("current_assets"), g("assets")
        if ca is not None:
            parts = sum(x or 0 for x in (g("cash"), g("sti"), g("ar"), g("inventory")))
            if ca - parts < -0.005 * ca:
                w.append(f"{fy}: current-asset lines ({parts:,.0f}) exceed reported current assets ({ca:,.0f})")
        if a and g("liabilities_equity") and abs(a - g("liabilities_equity")) > 0.001 * a:
            w.append(f"{fy}: total assets ≠ total liabilities & equity in the filing")
        if all(g(k) is not None for k in ("cfo", "cfi", "cff", "net_change_cash")):
            fx = g("net_change_cash") - g("cfo") - g("cfi") - g("cff")
            if abs(fx) > 0.05 * max(abs(g("cfo")), 1):
                w.append(f"{fy}: FX/other cash-flow difference is {fx:,.0f}, large against operating cash flow")
    return w


def liabilities(s: Statements, i: int) -> float | None:
    """Reported total liabilities; else total L&E less total equity (many filers don't tag Liabilities)."""
    v = s.get("liabilities", i)
    if v is not None:
        return v
    le = s.get("liabilities_equity", i)
    eq = s.get("equity_total", i) if s.get("equity_total", i) is not None else s.get("equity_parent", i)
    return le - eq if le is not None and eq is not None else None
