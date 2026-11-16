"""Concept map: which XBRL tags feed each normalized metric.

Each chain is tried in order *per period*; the first concept with a value for that period wins,
and the concept used is recorded in provenance. Taxonomies: us-gaap (US filers), ifrs-full (20-F/40-F
filers reporting under IFRS), dei (cover page).
"""

G, I, D = "us-gaap", "ifrs-full", "dei"

# Flow (duration) metrics
DURATION = {
    "revenue": [(G, "Revenues"), (G, "RevenuesNetOfInterestExpense"),
                (G, "RevenueFromContractWithCustomerExcludingAssessedTax"),
                (G, "RevenueFromContractWithCustomerIncludingAssessedTax"), (G, "SalesRevenueNet"),
                (G, "SalesRevenueGoodsNet"), (G, "SalesRevenueServicesNet"),
                (I, "Revenue"), (I, "RevenueFromContractsWithCustomers")],
    "cost_of_revenue": [(G, "CostOfRevenue"), (G, "CostOfGoodsAndServicesSold"), (G, "CostOfGoodsSold"),
                        (G, "CostOfServices"), (I, "CostOfSales")],
    "gross_profit": [(G, "GrossProfit"), (I, "GrossProfit")],
    "ebit": [(G, "OperatingIncomeLoss"), (I, "ProfitLossFromOperatingActivities")],
    "d_and_a": [(G, "DepreciationDepletionAndAmortization"), (G, "DepreciationAndAmortization"),
                (G, "DepreciationAmortizationAndAccretionNet"),
                (I, "DepreciationAndAmortisationExpense"),
                (I, "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss")],
    "depreciation": [(G, "Depreciation"), (I, "DepreciationExpense")],
    "amortization": [(G, "AmortizationOfIntangibleAssets"), (I, "AmortisationExpense")],
    "net_income": [(G, "NetIncomeLoss"), (G, "NetIncomeLossAvailableToCommonStockholdersBasic"),
                   (I, "ProfitLossAttributableToOwnersOfParent"), (I, "ProfitLoss")],
    "cfo": [(G, "NetCashProvidedByUsedInOperatingActivities"),
            (G, "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
            (I, "CashFlowsFromUsedInOperatingActivities")],
    "capex": [(G, "PaymentsToAcquirePropertyPlantAndEquipment"), (G, "PaymentsToAcquireProductiveAssets"),
              (I, "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
              (I, "PurchaseOfPropertyPlantAndEquipment")],
    "sm": [(G, "SellingAndMarketingExpense"), (I, "SellingExpense")],
    "ga": [(G, "GeneralAndAdministrativeExpense"), (I, "AdministrativeExpense")],
    "sga": [(G, "SellingGeneralAndAdministrativeExpense"), (I, "SellingGeneralAndAdministrativeExpense")],
    "rd": [(G, "ResearchAndDevelopmentExpense"), (G, "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"),
           (I, "ResearchAndDevelopmentExpense")],
    "opex": [(G, "OperatingExpenses"), (I, "OperatingExpense")],
    "eps_diluted": [(G, "EarningsPerShareDiluted"), (I, "DilutedEarningsLossPerShare")],
    "diluted_shares": [(G, "WeightedAverageNumberOfDilutedSharesOutstanding"),
                       (I, "WeightedAverageNumberOfSharesOutstandingDiluted")],
}

# Stock (instant) metrics, read at one balance-sheet date
INSTANT = {
    "total_assets": [(G, "Assets"), (I, "Assets")],
    "total_liabilities": [(G, "Liabilities"), (I, "Liabilities")],
    "total_equity": [(G, "StockholdersEquity"), (I, "EquityAttributableToOwnersOfParent")],
    "cash": [(G, "CashAndCashEquivalentsAtCarryingValue"),
             (G, "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
             (I, "CashAndCashEquivalents")],
    "st_investments": [(G, "ShortTermInvestments"), (G, "MarketableSecuritiesCurrent"),
                       (G, "AvailableForSaleSecuritiesDebtSecuritiesCurrent"), (I, "CurrentInvestments")],
    "lt_debt_total": [(G, "LongTermDebt"), (G, "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"),
                      (I, "Borrowings")],
    "lt_debt_noncurrent": [(G, "LongTermDebtNoncurrent"), (G, "LongTermDebtAndCapitalLeaseObligations"),
                           (I, "NoncurrentPortionOfNoncurrentBorrowings"), (I, "NoncurrentBorrowings")],
    "lt_debt_current": [(G, "LongTermDebtCurrent"), (G, "LongTermDebtAndCapitalLeaseObligationsCurrent"),
                        (I, "CurrentPortionOfNoncurrentBorrowings"), (I, "CurrentBorrowings")],
    "st_borrowings": [(G, "ShortTermBorrowings"), (I, "ShorttermBorrowings")],
    "commercial_paper": [(G, "CommercialPaper")],
    "finance_lease": [(G, "FinanceLeaseLiability")],
    "operating_lease": [(G, "OperatingLeaseLiability"), (I, "LeaseLiabilities")],
    "preferred": [(G, "PreferredStockValue")],
    "temp_equity": [(G, "TemporaryEquityCarryingAmountAttributableToParent")],
    "minority_interest": [(G, "MinorityInterest"), (I, "NoncontrollingInterests")],
    "shares_out_cover": [(D, "EntityCommonStockSharesOutstanding")],
    "shares_out_bs": [(G, "CommonStockSharesOutstanding")],
}

UNIT_KIND = {"eps_diluted": "per_share", "diluted_shares": "shares",
             "shares_out_cover": "shares", "shares_out_bs": "shares"}

# SIC ranges treated as bank/insurer/broker balance sheets: EV = market cap.
FINANCIAL_SIC = [(6000, 6399), (6700, 6799)]
