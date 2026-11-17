"""Regenerates the S6 gate fixtures (synthetic SEC companyfacts-shaped JSON, page texts, .eml files).

Run: python3 tests/fixtures/s6gate/build.py   (deterministic; no network). All data is invented."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
M = 1e6


def _fact(val, end, start=None, accn=None, form="10-K"):
    d = {"val": val, "end": end, "form": form, "accn": accn, "filed": f"{int(end[:4]) + 1}-02-15"}
    if start:
        d["start"] = start
    return d


def companyfacts(cik, name, years=(2022, 2023, 2024), rev0=1000.0, growth=1.1, margin=0.2, cash0=300.0, debt=325.0):
    g = {}

    def put(concept, row, unit="USD"):
        g.setdefault(concept, {"units": {}})["units"].setdefault(unit, []).append(row)

    cash_prev = cash0
    for i, y in enumerate(years):
        s, e = f"{y}-01-01", f"{y}-12-31"
        accn = f"{cik:010d}-{y + 1 - 2000:02d}-000001"
        rev = round(rev0 * growth ** i, 1)
        cogs, rd, sga = round(0.55 * rev, 1), round(0.08 * rev, 1), round((0.25 - margin) * rev, 1)
        ebit = round(rev - cogs - rd - sga, 1)
        ie, ii = 20.0, 5.0
        pretax = round(ebit - ie + ii, 1)
        tax = round(0.21 * pretax, 1)
        ni = round(pretax - tax, 1)
        da, sbc, capex = round(0.05 * rev, 1), round(0.02 * rev, 1), round(0.06 * rev, 1)
        div, bb = round(0.2 * ni, 1), round(0.3 * ni, 1)
        cfo = round(ni + da + sbc - 10.0, 1)
        cfi = round(-capex - 5.0, 1)
        cff = round(-div - bb + 15.0, 1)
        chg = round(cfo + cfi + cff, 1)
        cash = round(cash_prev + chg, 1)
        ar, inv, ap = round(0.1 * rev, 1), round(0.08 * rev, 1), round(0.07 * rev, 1)
        ca = round(cash + ar + inv + 30.0, 1)
        ppe = 400.0 + 20 * i
        assets = round(ca + ppe + 100.0 + 60.0, 1)
        debt_c, debt_nc = 25.0, debt - 25.0
        cl = round(ap + debt_c + 40.0, 1)
        liab = round(cl + debt_nc + 50.0, 1)
        eq = round(assets - liab, 1)
        for c, v in (("Revenues", rev), ("CostOfRevenue", cogs), ("GrossProfit", round(rev - cogs, 1)),
                     ("ResearchAndDevelopmentExpense", rd), ("SellingGeneralAndAdministrativeExpense", sga),
                     ("OperatingIncomeLoss", ebit), ("InterestExpense", ie), ("InvestmentIncomeInterest", ii),
                     ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", pretax),
                     ("IncomeTaxExpenseBenefit", tax), ("NetIncomeLoss", ni), ("DepreciationDepletionAndAmortization", da),
                     ("ShareBasedCompensation", sbc), ("NetCashProvidedByUsedInOperatingActivities", cfo),
                     ("PaymentsToAcquirePropertyPlantAndEquipment", capex),
                     ("NetCashProvidedByUsedInInvestingActivities", cfi), ("PaymentsOfDividends", div),
                     ("PaymentsForRepurchaseOfCommonStock", bb), ("NetCashProvidedByUsedInFinancingActivities", cff),
                     ("CashAndCashEquivalentsPeriodIncreaseDecrease", chg)):
            put(c, _fact(round(v * M), e, s, accn))
        put("WeightedAverageNumberOfDilutedSharesOutstanding", _fact(100e6 - i * 1e6, e, s, accn), unit="shares")
        put("EarningsPerShareDiluted", _fact(round(ni * M / (100e6 - i * 1e6), 2), e, s, accn), unit="USD/shares")
        for c, v in (("CashAndCashEquivalentsAtCarryingValue", cash), ("AccountsReceivableNetCurrent", ar),
                     ("InventoryNet", inv), ("AssetsCurrent", ca), ("PropertyPlantAndEquipmentNet", ppe),
                     ("Goodwill", 100.0), ("Assets", assets), ("AccountsPayableCurrent", ap),
                     ("LongTermDebtCurrent", debt_c), ("LiabilitiesCurrent", cl), ("LongTermDebtNoncurrent", debt_nc),
                     ("Liabilities", liab), ("StockholdersEquity", eq), ("LiabilitiesAndStockholdersEquity", assets)):
            put(c, _fact(round(v * M), e, None, accn))
        cash_prev = cash
    return {"cik": cik, "entityName": name, "facts": {"us-gaap": g}}


def main():
    out = {"companyfacts_TSTA.json": companyfacts(4242, "Testco Inc."),
           "companyfacts_BUYA.json": companyfacts(5151, "Buyer Alpha Corp.", rev0=5000.0, cash0=2500.0, debt=900.0),
           "companyfacts_BUYB.json": companyfacts(5252, "Buyer Beta Corp.", rev0=800.0, cash0=60.0, debt=400.0)}
    for fn, obj in out.items():
        with open(os.path.join(HERE, fn), "w") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
    print("wrote", sorted(out))


if __name__ == "__main__":
    main()
