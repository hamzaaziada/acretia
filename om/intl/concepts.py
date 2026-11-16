"""IFRS taxonomy (`ifrs-full`) concepts -> canonical statement keys (S8.2).

`IFRS_TO_KEY` maps the local names of `ifrs-full` elements an analyst meets on the primary statements to a key of
`om.statements.LINES` or to an `x.` key of `om.intl.labels.EXTRA_KEYS`. ESEF filings use `ifrs-full` for primary
lines and filer extensions for the rest; an extension concept is resolved through its English label with
`om.intl.labels.match` (`concept_to_key(qname, label=...)`).

One concept maps to one key. `ProfitLoss` is the profit including non-controlling interests, which is the
cash-flow starting line (`cf_net_income`); the income-statement `net_income` is the owners' share
(`ProfitLossAttributableToOwnersOfParent`), as in `om.statements.LINES`.
"""
from __future__ import annotations

import re

NS = "ifrs-full"

# ordered: the first concept listed for a key is the preferred one in key_to_concepts()
IFRS_TO_KEY: dict[str, str] = {
    # ---- income statement
    "Revenue": "revenue",
    "RevenueFromContractsWithCustomers": "revenue",
    "RevenueFromSaleOfGoods": "revenue",
    "RevenueFromRenderingOfServices": "revenue",
    "CostOfSales": "cogs",
    "GrossProfit": "gross_profit",
    "ResearchAndDevelopmentExpense": "rd",
    "SellingGeneralAndAdministrativeExpense": "sga",
    "ProfitLossFromOperatingActivities": "ebit",
    "FinanceCosts": "interest_expense",
    "InterestExpense": "interest_expense",
    "InterestExpenseOnBorrowings": "interest_expense",
    "FinanceIncome": "interest_income",
    "InterestRevenueCalculatedUsingEffectiveInterestMethod": "interest_income",
    "InvestmentIncome": "interest_income",
    "ProfitLossBeforeTax": "pretax",
    "ProfitLossFromContinuingOperationsBeforeTax": "pretax",
    "IncomeTaxExpenseContinuingOperations": "tax",
    "IncomeTaxExpense": "tax",
    "CurrentTaxExpenseIncome": "tax",
    "ProfitLossAttributableToOwnersOfParent": "net_income",
    "ProfitLossFromContinuingOperations": "net_income",
    "WeightedAverageNumberOfSharesOutstandingDiluted": "diluted_shares",
    "AdjustmentsForWeightedAverageNumberOfOrdinarySharesOutstandingDilutiveEffect": "diluted_shares",
    "DilutedEarningsLossPerShare": "eps_diluted",
    "DilutedEarningsLossPerShareFromContinuingOperations": "eps_diluted",
    "BasicEarningsLossPerShare": "x.eps_basic",
    "BasicEarningsLossPerShareFromContinuingOperations": "x.eps_basic",
    "DistributionCosts": "x.selling_expenses",
    "SellingExpense": "x.selling_expenses",
    "AdministrativeExpense": "x.admin_expenses",
    "OtherIncome": "x.other_income",
    "OtherOperatingIncome": "x.other_income",
    "OtherGainsLosses": "x.other_income",
    "OtherExpenseByFunction": "x.other_opex",
    "OtherExpenseByNature": "x.other_opex",
    "OtherOperatingExpense": "x.other_opex",
    "EmployeeBenefitsExpense": "x.employee_costs",
    "WagesAndSalaries": "x.employee_costs",
    "RawMaterialsAndConsumablesUsed": "x.raw_materials",
    "IncreaseDecreaseInInventoriesOfFinishedGoodsAndWorkInProgress": "x.changes_in_inventories",
    "DepreciationExpense": "da",
    "DepreciationPropertyPlantAndEquipment": "x.depreciation",
    "AmortisationExpense": "da",
    "AmortisationIntangibleAssetsOtherThanGoodwill": "x.amortisation",
    "DepreciationRightofuseAssets": "x.rou_depreciation",
    "ZakatExpense": "x.zakat",
    "InterestExpenseOnLeaseLiabilities": "x.lease_interest",
    "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod": "x.share_of_associates",
    "ShareOfProfitLossOfAssociatesAccountedForUsingEquityMethod": "x.share_of_associates",
    "ShareOfProfitLossOfJointVenturesAccountedForUsingEquityMethod": "x.share_of_associates",
    "ProfitLossAttributableToNoncontrollingInterests": "x.nci_profit",
    "GainsLossesOnNetMonetaryPosition": "x.fx_gain_loss",
    "NetForeignExchangeGainLoss": "x.fx_gain_loss",
    "ForeignExchangeGainLossRecognisedInProfitOrLoss": "x.fx_gain_loss",
    "FinanceIncomeCost": "x.finance_costs_net",
    "FinanceCostsNet": "x.finance_costs_net",
    "ImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss": "x.impairment",
    "ImpairmentLossRecognisedInProfitOrLoss": "x.impairment",
    # ---- comprehensive income
    "OtherComprehensiveIncome": "x.oci_total",
    "OtherComprehensiveIncomeNetOfTax": "x.oci_total",
    "ComprehensiveIncome": "x.total_comprehensive_income",
    "ComprehensiveIncomeAttributableToOwnersOfParent": "x.total_comprehensive_income",
    "ExchangeDifferencesOnTranslationNetOfTax": "x.fx_translation_oci",
    "ExchangeDifferencesOnTranslation": "x.fx_translation_oci",
    # ---- balance sheet: assets
    "CashAndCashEquivalents": "cash",
    "CashAndBankBalancesAtCentralBanks": "cash",
    "CurrentInvestments": "sti",
    "OtherCurrentFinancialAssets": "sti",
    "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss": "sti",
    "TradeAndOtherCurrentReceivables": "ar",
    "CurrentTradeReceivables": "ar",
    "TradeReceivables": "ar",
    "Inventories": "inventory",
    "CurrentAssets": "current_assets",
    "PropertyPlantAndEquipment": "ppe",
    "Goodwill": "goodwill",
    "IntangibleAssetsOtherThanGoodwill": "intangibles",
    "IntangibleAssetsAndGoodwill": "intangibles",
    "Assets": "assets",
    "RightofuseAssets": "x.rou_assets",
    "InvestmentProperty": "x.investment_property",
    "NoncurrentAssets": "x.noncurrent_assets",
    "OtherCurrentAssets": "x.other_current_assets",
    "CurrentPrepaymentsAndCurrentAccruedIncome": "x.other_current_assets",
    "OtherNoncurrentAssets": "x.other_noncurrent_assets",
    "NoncurrentFinancialAssets": "x.other_noncurrent_assets",
    "OtherNoncurrentFinancialAssets": "x.other_noncurrent_assets",
    "DeferredTaxAssets": "x.deferred_tax_assets",
    "InvestmentsInAssociatesAccountedForUsingEquityMethod": "x.investments_associates",
    "InvestmentsInJointVenturesAccountedForUsingEquityMethod": "x.investments_associates",
    "InvestmentsInAssociatesAndJointVenturesAccountedForUsingEquityMethod": "x.investments_associates",
    "CapitalisedDevelopmentExpenditure": "x.capitalised_dev",
    "InternallyGeneratedIntangibleAssets": "x.capitalised_dev",
    # ---- balance sheet: liabilities and equity
    "TradeAndOtherCurrentPayables": "ap",
    "TradeAndOtherPayables": "ap",
    "CurrentBorrowings": "debt_current",
    "CurrentPortionOfNoncurrentBorrowings": "debt_current",
    "ShorttermBorrowings": "debt_current",
    "CurrentLiabilities": "current_liabilities",
    "NoncurrentPortionOfNoncurrentBorrowings": "debt_noncurrent",
    "NoncurrentBorrowings": "debt_noncurrent",
    "Borrowings": "debt_noncurrent",
    "Liabilities": "liabilities",
    "EquityAttributableToOwnersOfParent": "equity_parent",
    "EquityAndLiabilities": "liabilities_equity",
    "Equity": "equity_total",
    "CurrentLeaseLiabilities": "x.lease_liabilities_current",
    "CurrentPortionOfLeaseLiabilities": "x.lease_liabilities_current",
    "NoncurrentLeaseLiabilities": "x.lease_liabilities_noncurrent",
    "LeaseLiabilities": "x.lease_liabilities_noncurrent",
    "NoncurrentLiabilities": "x.noncurrent_liabilities",
    "NoncurrentRecognisedLiabilitiesDefinedBenefitPlan": "x.eosb",
    "PostemploymentBenefitLiabilityDefinedBenefitPlan": "x.eosb",
    "LiabilitiesForPostemploymentBenefitObligations": "x.eosb",
    "EmployeeBenefitsLiabilities": "x.eosb",
    "OtherCurrentLiabilities": "x.other_current_liabilities",
    "OtherCurrentPayables": "x.other_current_liabilities",
    "CurrentTaxLiabilitiesCurrent": "x.other_current_liabilities",
    "CurrentContractLiabilities": "x.contract_liabilities",
    "ContractLiabilities": "x.contract_liabilities",
    "OtherNoncurrentLiabilities": "x.other_noncurrent_liabilities",
    "OtherNoncurrentPayables": "x.other_noncurrent_liabilities",
    "DeferredTaxLiabilities": "x.deferred_tax_liabilities",
    "Provisions": "x.provisions",
    "OtherProvisions": "x.provisions",
    "CurrentProvisions": "x.provisions",
    "NoncurrentProvisions": "x.provisions",
    "DeferredIncomeClassifiedAsNoncurrent": "x.gov_grants",
    "GovernmentGrants": "x.gov_grants",
    "IssuedCapital": "x.share_capital",
    "RetainedEarnings": "x.retained_earnings",
    "NoncontrollingInterests": "x.nci_equity",
    "StatutoryReserve": "x.statutory_reserve",
    "LegalReserve": "x.statutory_reserve",
    "OtherReserves": "x.other_reserves",
    "SharePremium": "x.other_reserves",
    "TreasuryShares": "x.treasury_shares",
    # ---- cash flow
    "ProfitLoss": "cf_net_income",
    "AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss": "da",
    "DepreciationAndAmortisationExpense": "da",
    "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss": "da",
    "AdjustmentsForDepreciationAndAmortisationExpense": "da",
    "AdjustmentsForSharebasedPayments": "sbc",
    "ShareBasedPaymentArrangements": "sbc",
    "CashFlowsFromUsedInOperatingActivities": "cfo",
    "CashFlowsFromUsedInOperations": "cfo",
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": "capex",
    "PurchaseOfPropertyPlantAndEquipment": "capex",
    "PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssetsClassifiedAsInvestingActivities": "capex",
    "CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities": "acquisitions",
    "CashFlowsFromUsedInInvestingActivities": "cfi",
    "DividendsPaidClassifiedAsFinancingActivities": "dividends",
    "DividendsPaid": "dividends",
    "PaymentsToAcquireOrRedeemEntitysShares": "buybacks",
    "PaymentsToAcquireTreasuryShares": "buybacks",
    "CashFlowsFromUsedInFinancingActivities": "cff",
    "IncreaseDecreaseInCashAndCashEquivalents": "net_change_cash",
    "IncreaseDecreaseInCashAndCashEquivalentsBeforeEffectOfExchangeRateChanges": "net_change_cash",
    "CashAndCashEquivalentsAtBeginningOfPeriod": "x.cash_beginning",
    "CashAndCashEquivalentsAtEndOfPeriod": "x.cash_end",
    "EffectOfExchangeRateChangesOnCashAndCashEquivalents": "x.fx_effect_cash",
    "PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities": "x.lease_payments",
    "RepaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities": "x.lease_payments",
    "InterestPaidClassifiedAsOperatingActivities": "x.interest_paid",
    "InterestPaidClassifiedAsFinancingActivities": "x.interest_paid",
    "InterestPaid": "x.interest_paid",
    "IncomeTaxesPaidRefundClassifiedAsOperatingActivities": "x.tax_paid",
    "IncomeTaxesPaidClassifiedAsOperatingActivities": "x.tax_paid",
    "IncomeTaxesPaid": "x.tax_paid",
    "ProceedsFromBorrowingsClassifiedAsFinancingActivities": "x.borrowings_proceeds",
    "ProceedsFromBorrowings": "x.borrowings_proceeds",
    "RepaymentsOfBorrowingsClassifiedAsFinancingActivities": "x.borrowings_repaid",
    "RepaymentsOfBorrowings": "x.borrowings_repaid",
}

_QNAME_BRACE = re.compile(r"^\{([^}]*)\}(.+)$")
_PREFIXES = ("ifrs-full", "ifrs_full", "ifrs", "ifrs-smes")
_NS_MARKERS = ("ifrs.org/taxonomy", "xbrl.ifrs.org")
_BY_KEY: dict[str, list] = {}
for _c, _k in IFRS_TO_KEY.items():
    _BY_KEY.setdefault(_k, []).append(f"{NS}:{_c}")
_LOWER = {c.lower(): c for c in IFRS_TO_KEY}


def split_qname(qname: str) -> tuple:
    """(namespace_or_prefix, local_name) from `ifrs-full:X`, `ifrs-full_X` or `{ns}X`; ns is "" when absent."""
    q = (qname or "").strip()
    m = _QNAME_BRACE.match(q)
    if m:
        return m.group(1), m.group(2)
    if ":" in q:
        p, _, n = q.partition(":")
        return p, n
    for pref in _PREFIXES:
        if q.startswith(pref + "_"):
            return pref, q[len(pref) + 1:]
    return "", q


def is_ifrs_namespace(ns: str) -> bool:
    n = ns.lower()
    return n in _PREFIXES or any(m in n for m in _NS_MARKERS)


def concept_to_key(qname: str, *, label: str | None = None, statement: str | None = None) -> str | None:
    """Canonical key for an XBRL concept. `ifrs-full` concepts resolve through IFRS_TO_KEY. Any other namespace (an
    ESEF filer extension or a local taxonomy) falls back to matching `label` (its English standard label) with
    `om.intl.labels.match`; the fallback only returns a key when the match confidence is >= 0.8."""
    ns, name = split_qname(qname)
    if not name:
        return None
    if is_ifrs_namespace(ns) or not ns:
        key = IFRS_TO_KEY.get(name) or IFRS_TO_KEY.get(_LOWER.get(name.lower(), ""))
        if key:
            return key
        if is_ifrs_namespace(ns) and label is None:
            return None
    if label:
        from . import labels
        m = labels.match(label, statement=statement)
        if m is not None and m.confidence >= 0.8:
            return m.key
    return None


def key_to_concepts(key: str) -> list:
    """`ifrs-full:` concept names (qualified) for a key, preferred first; [] when the key has none."""
    return list(_BY_KEY.get(key, []))
