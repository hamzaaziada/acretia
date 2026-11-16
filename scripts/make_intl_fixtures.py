#!/usr/bin/env python3
"""Generate the synthetic S8 report fixtures and their ground truth.

Every fixture is made by us from a ground-truth spec (no third-party report is
committed). Statements are computed so that subtotals, the balance sheet and
the cash-flow-to-cash tie hold exactly. Native PDFs are printed from HTML by
headless Chrome/Chromium (real text layer); scanned PDFs are rasterised
(pdftoppm, 200 dpi), degraded (noise, blur, 0.5-1.5 degree skew) and saved as
image-only PDFs.

    python3 scripts/make_intl_fixtures.py            # (re)generate into tests/fixtures/intl/
    python3 scripts/make_intl_fixtures.py --check    # regenerate in a temp dir, verify ground truth
                                                     # and the extracted text layer (no byte equality)

Fonts: DejaVu Sans (Bitstream Vera licence, system package fonts-dejavu-core).
"""
import argparse
import hashlib
import html
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "fixtures", "intl")
GENERATOR = "scripts/make_intl_fixtures.py"
sys.path.insert(0, ROOT)

# --------------------------------------------------------------------------- digits
_EAST = str.maketrans("0123456789,.", "٠١٢٣٤٥٦٧٨٩٬٫")


def r(x):
    return int(round(x))


def fmt_num(n, d, eastern, bracket):
    """Printed token for stored integer n (units of 10**-d)."""
    if n == 0:
        return "-"
    a = abs(n)
    s = f"{a // 10 ** d:,}" + (f".{a % 10 ** d:0{d}d}" if d else "")
    if eastern:
        s = s.translate(_EAST)
    return f"({s})" if bracket else s


def edigits(s, eastern):
    return s.translate(_EAST) if eastern else s


# --------------------------------------------------------------------------- spec
SPECS = {
    "nile_a": dict(
        company="Nile Valley Foods S.A.E.", company_ar="وادي النيل للأغذية (ش.م.م)", currency="EGP",
        scale=1e3, d=0, fy_month=6, standard="EAS", seed=11, rev0=3_800_000, eastern=False,
        years=[date(2022, 6, 30), date(2023, 6, 30), date(2024, 6, 30)], rate=0.17, tax_rate=0.225,
        goodwill=False, leases=False, by_nature=False, zakat=False, eosb=False),
    "redsea": dict(
        company="Red Sea Cement Co.", company_ar="شركة البحر الأحمر للأسمنت", currency="SAR",
        scale=1e6, d=1, fy_month=12, standard="SOCPA-IFRS", seed=23, rev0=48_000, eastern=False,
        years=[date(2022, 12, 31), date(2023, 12, 31), date(2024, 12, 31)], rate=0.055, tax_rate=0.2,
        goodwill=True, leases=False, by_nature=True, zakat=True, eosb=True),
    "gulf": dict(
        company="Gulf Retail PJSC", company_ar="الخليج للتجزئة (ش.م.ع)", currency="AED",
        scale=1e3, d=0, fy_month=12, standard="IFRS", seed=37, rev0=2_600_000, eastern=False,
        years=[date(2022, 12, 31), date(2023, 12, 31), date(2024, 12, 31)], rate=0.06, tax_rate=0.09,
        goodwill=True, leases=True, by_nature=False, zakat=False, eosb=False),
}

# fixture file -> (spec, columns (current index, prior index), language, kind, digits eastern override)
FIXTURES = [
    dict(file="nile_valley_ar_native_fy2024.pdf", spec="nile_a", cur=2, kind="native", language="ar"),
    dict(file="nile_valley_ar_scanned_fy2024.pdf", spec="nile_a", cur=2, kind="scanned", language="ar",
         raster_of="nile_valley_ar_native_fy2024.pdf", skew=[0.9, -1.3, 0.6, 1.1]),
    dict(file="nile_valley_ar_native_fy2023.pdf", spec="nile_a", cur=1, kind="native", language="ar", eastern=True),
    dict(file="red_sea_cement_en_native_fy2024.pdf", spec="redsea", cur=2, kind="native", language="en"),
    dict(file="red_sea_cement_en_scanned_fy2024.pdf", spec="redsea", cur=2, kind="scanned", language="en",
         raster_of="red_sea_cement_en_native_fy2024.pdf", skew=[-0.8, 1.4, -0.5, 1.0]),
    dict(file="gulf_retail_bi_native_fy2024.pdf", spec="gulf", cur=2, kind="native", language="bi"),
]


# --------------------------------------------------------------------------- numbers chain
def make_chain(sp):
    """Three consecutive fiscal years of an internally consistent set of statements.

    Values are integers in units of 10**-d of the printed unit, in the om.statements
    sign convention (expenses positive). Keys prefixed '_' are unmapped lines.
    """
    rng = random.Random(sp["seed"])
    ys = []
    for t in range(3):
        y = {}
        prev = ys[-1] if ys else None
        rev = sp["rev0"] if t == 0 else r(prev["revenue"] * (1 + rng.uniform(0.07, 0.15)))
        y["revenue"] = rev
        cogs_ratio = rng.uniform(0.62, 0.68)
        y["cogs"] = r(rev * cogs_ratio)
        # balance-sheet drivers that follow activity
        if t == 0:
            y["ar"] = r(rev * 0.13)
            y["inventory"] = r(y["cogs"] * 0.19)
            y["ap"] = r(y["cogs"] * 0.15)
            y["_oca"] = r(rev * 0.03)
            y["cash"] = r(rev * 0.08)
            y["ppe"] = r(rev * 0.55)
            y["intangibles"] = r(rev * 0.03)
            y["goodwill"] = r(rev * 0.04) if sp["goodwill"] else 0
            y["debt_current"] = r(rev * 0.06)
            y["debt_noncurrent"] = r(rev * 0.14)
            y["x.provisions"] = r(rev * 0.03)
            y["x.share_capital"] = r(rev * 0.25)
            y["_reserves"] = r(rev * 0.08)
            if sp["leases"]:
                y["x.rou_assets"] = r(rev * 0.07)
                lt = r(rev * 0.075)
                y["x.lease_liabilities_current"] = r(lt * 0.18)
                y["x.lease_liabilities_noncurrent"] = lt - y["x.lease_liabilities_current"]
            if sp["eosb"]:
                y["x.eosb"] = r(rev * 0.025)
            else:
                y["_oncl"] = r(rev * 0.025)
            ppe_dep = r(y["ppe"] * 0.07)
            rou_dep = r(y.get("x.rou_assets", 0) * 0.14)
            lease_total = y.get("x.lease_liabilities_current", 0) + y.get("x.lease_liabilities_noncurrent", 0)
        else:
            y["ar"] = r(rev * rng.uniform(0.125, 0.135))
            y["inventory"] = r(y["cogs"] * rng.uniform(0.18, 0.2))
            y["ap"] = r(y["cogs"] * rng.uniform(0.145, 0.155))
            for k in ("_oca", "intangibles", "goodwill", "debt_current", "x.provisions", "x.share_capital",
                      "_reserves", "x.eosb", "_oncl"):
                if k in prev:
                    y[k] = prev[k]
            ppe_dep = r(prev["ppe"] * 0.07)
            rou_dep = r(prev.get("x.rou_assets", 0) * 0.14)
            lease_total = (prev.get("x.lease_liabilities_current", 0) + prev.get("x.lease_liabilities_noncurrent", 0))
        # income statement
        debt_base = (prev["debt_current"] + prev["debt_noncurrent"]) if prev else (y["debt_current"] + y["debt_noncurrent"])
        lease_interest = r(lease_total * 0.06) if sp["leases"] else 0
        y["interest_expense"] = r(debt_base * sp["rate"]) + lease_interest
        if sp["leases"]:
            y["x.lease_interest"] = lease_interest
            y["x.rou_depreciation"] = rou_dep
        y["interest_income"] = r(rev * 0.004)
        y["x.other_income"] = r(rev * rng.uniform(0.005, 0.015))
        da = ppe_dep + rou_dep
        if sp["by_nature"]:
            y["x.raw_materials"] = r(rev * rng.uniform(0.40, 0.44))
            y["x.employee_costs"] = r(rev * rng.uniform(0.09, 0.11))
            y["x.depreciation"] = da
            y["x.other_opex"] = r(rev * rng.uniform(0.06, 0.08))
            y["cogs"] = 0
            opx = y["x.raw_materials"] + y["x.employee_costs"] + y["x.depreciation"] + y["x.other_opex"]
            y["_ebit_calc"] = rev + y["x.other_income"] - opx
            y["pretax"] = y["_ebit_calc"] - y["interest_expense"] + y["interest_income"]
            y["x.zakat"] = r(y["pretax"] * 0.025 * 0.8)
            y["tax"] = r(y["pretax"] * sp["tax_rate"] * 0.2)
            y["net_income"] = y["pretax"] - y["x.zakat"] - y["tax"]
        else:
            y["gross_profit"] = rev - y["cogs"]
            y["sga"] = r(rev * rng.uniform(0.10, 0.13))
            y["ebit"] = y["gross_profit"] - y["sga"] + y["x.other_income"]
            y["pretax"] = y["ebit"] - y["interest_expense"] + y["interest_income"]
            y["tax"] = r(y["pretax"] * sp["tax_rate"])
            y["net_income"] = y["pretax"] - y["tax"]
        ni = y["net_income"]
        # flows
        if t == 0:
            d_ar, d_inv, d_ap = r(y["ar"] * 0.05), r(y["inventory"] * 0.04), r(y["ap"] * 0.05)
            capex = r(rev * 0.07)
            issue = r(rev * 0.01)
            div = r(ni * 0.3)
            princ = r(rou_dep * 0.8)
        else:
            d_ar, d_inv, d_ap = y["ar"] - prev["ar"], y["inventory"] - prev["inventory"], y["ap"] - prev["ap"]
            capex = r(rev * rng.uniform(0.05, 0.09))
            issue = r(rev * rng.uniform(-0.01, 0.03))
            div = r(ni * 0.3)
            princ = r(rou_dep * 0.8)
            y["ppe"] = prev["ppe"] + capex - ppe_dep
            y["debt_noncurrent"] = prev["debt_noncurrent"] + issue
            if sp["leases"]:
                add = r(rev * 0.012)
                y["x.rou_assets"] = prev["x.rou_assets"] + add - rou_dep
                lt = lease_total + add - princ
                y["x.lease_liabilities_current"] = r(lt * 0.18)
                y["x.lease_liabilities_noncurrent"] = lt - y["x.lease_liabilities_current"]
        y["cf_net_income"] = ni
        y["da"] = da
        y["_d_ar"], y["_d_inv"], y["_d_ap"] = -d_ar, -d_inv, d_ap
        y["cfo"] = ni + da - d_ar - d_inv + d_ap
        y["capex"] = capex
        y["cfi"] = -capex
        y["_debt"] = issue
        y["dividends"] = div
        y["_lease_pay"] = princ if sp["leases"] else 0
        y["cff"] = issue - div - y["_lease_pay"]
        y["net_change_cash"] = y["cfo"] + y["cfi"] + y["cff"]
        if t == 0:
            y["x.cash_beginning"] = y["cash"] - y["net_change_cash"]
            y["x.retained_earnings"] = 0     # plug below
        else:
            y["x.cash_beginning"] = prev["cash"]
            y["cash"] = prev["cash"] + y["net_change_cash"]
            y["x.retained_earnings"] = prev["x.retained_earnings"] + ni - div
        y["x.cash_end"] = y["x.cash_beginning"] + y["net_change_cash"]
        # totals
        y["current_assets"] = y["cash"] + y["ar"] + y["inventory"] + y["_oca"]
        y["x.noncurrent_assets"] = y["ppe"] + y.get("x.rou_assets", 0) + y["goodwill"] + y["intangibles"]
        y["assets"] = y["current_assets"] + y["x.noncurrent_assets"]
        y["current_liabilities"] = (y["ap"] + y["debt_current"] + y["x.provisions"]
                                    + y.get("x.lease_liabilities_current", 0))
        y["x.noncurrent_liabilities"] = (y["debt_noncurrent"] + y.get("x.lease_liabilities_noncurrent", 0)
                                         + y.get("x.eosb", y.get("_oncl", 0)))
        y["liabilities"] = y["current_liabilities"] + y["x.noncurrent_liabilities"]
        if t == 0:
            y["x.retained_earnings"] = (y["assets"] - y["liabilities"] - y["x.share_capital"] - y["_reserves"])
            assert y["x.retained_earnings"] > 0, "base-year equity plug must be positive"
        y["equity_total"] = y["x.share_capital"] + y["_reserves"] + y["x.retained_earnings"]
        y["liabilities_equity"] = y["liabilities"] + y["equity_total"]
        assert y["assets"] == y["liabilities_equity"], (t, y["assets"], y["liabilities_equity"])
        assert y["x.cash_end"] == y["cash"], (t, y["x.cash_end"], y["cash"])
        assert y["pretax"] > 0 and ni > 0
        ys.append(y)
    return ys


# --------------------------------------------------------------------------- statement layouts
# row: (id/key, EN label, AR label, flags) flags: t total, n negative-printed(expense) , s section header, note
def layout(sp):
    L = []

    def S(en, ar):
        L.append(("IS", None, en, ar, "s", None))

    is_rows = []
    if sp["by_nature"]:
        is_rows = [
            ("revenue", "Revenue", "الإيرادات", "", 20),
            ("x.other_income", "Other income", "إيرادات أخرى", "", 21),
            ("x.raw_materials", "Raw materials and consumables used", "المواد الخام والمستهلكات المستخدمة", "n", 22),
            ("x.employee_costs", "Employee benefits expense", "مصروفات منافع الموظفين", "n", 23),
            ("x.depreciation", "Depreciation and amortisation", "الإهلاك والاستنفاد", "n", 7),
            ("x.other_opex", "Other operating expenses", "مصروفات تشغيلية أخرى", "n", 24),
            ("interest_expense", "Finance costs", "تكاليف التمويل", "n", 15),
            ("interest_income", "Finance income", "إيرادات التمويل", "", None),
            ("pretax", "Profit before zakat and income tax", "الربح قبل الزكاة وضريبة الدخل", "t", None),
            ("x.zakat", "Zakat", "الزكاة", "n", 25),
            ("tax", "Income tax", "ضريبة الدخل", "n", 25),
            ("net_income", "Net profit for the year", "صافي ربح السنة", "t", None),
        ]
    else:
        is_rows = [
            ("revenue", "Revenue", "الإيرادات", "", 20),
            ("cogs", "Cost of revenue", "تكلفة الإيرادات", "n", 21),
            ("gross_profit", "Gross profit", "مجمل الربح", "t", None),
            ("sga", "Selling, general and administrative expenses", "مصروفات البيع والمصروفات العمومية والإدارية", "n", 22),
            ("x.other_income", "Other income", "إيرادات أخرى", "", 23),
            ("ebit", "Operating profit", "ربح التشغيل", "t", None),
            ("interest_income", "Finance income", "إيرادات التمويل", "", None),
            ("interest_expense", "Finance costs", "تكاليف التمويل", "n", 15),
            ("pretax", "Profit before income tax", "الربح قبل ضريبة الدخل", "t", None),
            ("tax", "Income tax expense", "ضريبة الدخل", "n", 24),
            ("net_income", "Net profit for the year", "صافي ربح السنة", "t", None),
        ]
    bs = [
        ("#", "Assets", "الأصول", "s", None),
        ("#", "Current assets", "الأصول المتداولة", "s", None),
        ("cash", "Cash and cash equivalents", "النقدية وما في حكمها", "", 5),
        ("ar", "Trade and other receivables", "العملاء والمدينون الآخرون", "", 6),
        ("inventory", "Inventories", "المخزون", "", 8),
        ("_oca", "Prepayments and other current assets", "مدفوعات مقدمة وأصول متداولة أخرى", "", None),
        ("current_assets", "Total current assets", "إجمالي الأصول المتداولة", "t", None),
        ("#", "Non-current assets", "الأصول غير المتداولة", "s", None),
        ("ppe", "Property, plant and equipment", "الأصول الثابتة", "", 7),
    ]
    if sp["leases"]:
        bs.append(("x.rou_assets", "Right-of-use assets", "أصول حق الاستخدام", "", 9))
    bs += [
        ("goodwill", "Goodwill", "الشهرة", "", 10),
        ("intangibles", "Intangible assets", "الأصول غير الملموسة", "", 10),
        ("x.noncurrent_assets", "Total non-current assets", "إجمالي الأصول غير المتداولة", "t", None),
        ("assets", "Total assets", "إجمالي الأصول", "t", None),
        ("#", "Liabilities", "الالتزامات", "s", None),
        ("#", "Current liabilities", "الالتزامات المتداولة", "s", None),
        ("ap", "Trade and other payables", "الموردون والدائنون الآخرون", "", 11),
        ("debt_current", "Short-term borrowings", "قروض قصيرة الأجل", "", 12),
        ("x.provisions", "Provisions", "المخصصات", "", 13),
    ]
    if sp["leases"]:
        bs.append(("x.lease_liabilities_current", "Lease liabilities - current", "التزامات عقود الإيجار - متداولة", "", 9))
    bs += [
        ("current_liabilities", "Total current liabilities", "إجمالي الالتزامات المتداولة", "t", None),
        ("#", "Non-current liabilities", "الالتزامات غير المتداولة", "s", None),
        ("debt_noncurrent", "Long-term borrowings", "قروض طويلة الأجل", "", 12),
    ]
    if sp["leases"]:
        bs.append(("x.lease_liabilities_noncurrent", "Lease liabilities - non-current", "التزامات عقود الإيجار - غير متداولة", "", 9))
    if sp["eosb"]:
        bs.append(("x.eosb", "Employees' end of service benefits", "مكافأة نهاية الخدمة للموظفين", "", 14))
    else:
        bs.append(("_oncl", "Other non-current liabilities", "التزامات أخرى غير متداولة", "", None))
    bs += [
        ("x.noncurrent_liabilities", "Total non-current liabilities", "إجمالي الالتزامات غير المتداولة", "t", None),
        ("liabilities", "Total liabilities", "إجمالي الالتزامات", "t", None),
        ("#", "Equity", "حقوق الملكية", "s", None),
        ("x.share_capital", "Share capital", "رأس المال", "", 16),
        ("_reserves", "Reserves", "الاحتياطيات", "", 17),
        ("x.retained_earnings", "Retained earnings", "الأرباح المرحلة", "", None),
        ("equity_total", "Total equity", "إجمالي حقوق الملكية", "t", None),
        ("liabilities_equity", "Total equity and liabilities", "إجمالي حقوق الملكية والالتزامات", "t", None),
    ]
    cf = [
        ("#", "Operating activities", "الأنشطة التشغيلية", "s", None),
        ("cf_net_income", "Net profit for the year", "صافي ربح السنة", "", None),
        ("da", "Depreciation and amortisation", "الإهلاك والاستنفاد", "", 7),
        ("_d_ar", "Change in trade and other receivables", "التغير في العملاء والمدينون", "", None),
        ("_d_inv", "Change in inventories", "التغير في المخزون", "", None),
        ("_d_ap", "Change in trade and other payables", "التغير في الموردون والدائنون", "", None),
        ("cfo", "Net cash from operating activities", "صافي النقدية من الأنشطة التشغيلية", "t", None),
        ("#", "Investing activities", "الأنشطة الاستثمارية", "s", None),
        ("capex", "Purchase of property, plant and equipment", "مدفوعات لشراء أصول ثابتة", "n", 7),
        ("cfi", "Net cash used in investing activities", "صافي النقدية المستخدمة في الأنشطة الاستثمارية", "t", None),
        ("#", "Financing activities", "الأنشطة التمويلية", "s", None),
        ("_debt", "Proceeds from borrowings, net", "متحصلات من القروض، بالصافي", "", 12),
    ]
    if sp["leases"]:
        cf.append(("_lease_pay", "Payment of principal portion of lease liabilities", "سداد الجزء الأصلي من التزامات الإيجار", "n", 9))
    cf += [
        ("dividends", "Dividends paid", "توزيعات الأرباح المدفوعة", "n", None),
        ("cff", "Net cash from (used in) financing activities", "صافي النقدية من (المستخدمة في) الأنشطة التمويلية", "t", None),
        ("net_change_cash", "Net change in cash and cash equivalents", "صافي التغير في النقدية وما في حكمها", "t", None),
        ("x.cash_beginning", "Cash and cash equivalents at beginning of year", "النقدية وما في حكمها في أول السنة", "", None),
        ("x.cash_end", "Cash and cash equivalents at end of year", "النقدية وما في حكمها في آخر السنة", "t", None),
    ]
    stm = [("IS", "Statement of profit or loss", "قائمة الأرباح أو الخسائر",
            [("#" if False else row[0], row[1], row[2], row[3], row[4]) for row in is_rows]),
           ("BS", "Statement of financial position", "قائمة المركز المالي", bs),
           ("CF", "Statement of cash flows", "قائمة التدفقات النقدية", cf)]
    if sp["leases"]:
        stm.append(("NOTE", "Note 9 - Leases", "إيضاح ٩ - عقود الإيجار", [
            ("x.rou_depreciation", "Depreciation charge on right-of-use assets", "إهلاك أصول حق الاستخدام", "", None),
            ("x.lease_interest", "Interest expense on lease liabilities", "فوائد التزامات عقود الإيجار", "", None),
        ]))
    return stm


# --------------------------------------------------------------------------- HTML
AR_MONTHS = {1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو", 7: "يوليو",
             8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"}
EN_MONTHS = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]
UNIT_EN = {("EGP", 1e3): "(All amounts in EGP '000)", ("SAR", 1e6): "(All amounts in SAR million)",
           ("AED", 1e3): "(All amounts in AED'000)"}
UNIT_AR = {("EGP", 1e3): "(جميع المبالغ بالألف جنيه مصري)", ("SAR", 1e6): "(جميع المبالغ بالمليون ريال سعودي)",
           ("AED", 1e3): "(جميع المبالغ بالألف درهم إماراتي)"}

CSS = """
@page { size: A4; margin: 14mm 13mm; }
html { font-family: 'DejaVu Sans', sans-serif; color: #111; }
body { margin: 0; font-size: 10.4pt; }
section.page { page-break-after: always; }
section.page:last-child { page-break-after: auto; }
h1 { font-size: 15pt; margin: 0 0 3px 0; }
h2 { font-size: 12.5pt; margin: 0 0 3px 0; font-weight: bold; }
.sub, .unit { font-size: 10pt; margin: 0 0 3px 0; }
.unit { margin-bottom: 9px; }
table { width: 100%; border-collapse: collapse; }
th { font-size: 9.5pt; border-bottom: 1.5px solid #000; padding: 4px 5px; }
td { padding: 3.6px 5px; vertical-align: top; }
td.n, th.n { text-align: right; white-space: nowrap; width: 17%; }
td.note, th.note { text-align: center; width: 7%; }
tr.t td { font-weight: bold; border-top: 1px solid #000; }
tr.s td { font-weight: bold; padding-top: 8px; }
.foot { margin-top: 14px; font-size: 8.6pt; }
.rtl { direction: rtl; }
body.bi { font-size: 8.8pt; }
body.bi table { table-layout: fixed; }
body.bi td { padding: 2.4px 4px; }
body.bi td.n, body.bi th.n { width: auto; }
body.bi td.note, body.bi th.note { width: auto; }
"""


def d_en(dt):
    return f"{dt.day} {EN_MONTHS[dt.month]} {dt.year}"


def d_ar(dt, eastern):
    return f"{edigits(str(dt.day), eastern)} {AR_MONTHS[dt.month]} {edigits(str(dt.year), eastern)}"


def figure_rows(sp, ys, cols, lang, eastern):
    """Yield per statement: (code, title_en, title_ar, [row dicts]) with printed tokens."""
    out = []
    for code, ten, tar, rows in layout(sp):
        rr = []
        for key, en, ar, flags, note in rows:
            if key == "#":
                rr.append(dict(section=True, en=en, ar=ar))
                continue
            # layout rows are (key,en,ar,flags,note); section rows use ('#', en, ar, 's', None)
            pass
        out.append((code, ten, tar, rows))
    return out


def build_pages(sp, spec_fx, ys, cols, eastern):
    """Return (html, truth) for one fixture."""
    lang = spec_fx["language"]
    d = sp["d"]
    ccy, scale = sp["currency"], sp["scale"]
    pages = []
    truth = []
    page_no = 0
    for code, ten, tar, rows in layout(sp):
        page_no += 1
        body = []
        for row in rows:
            key, en, ar, flags, note = row
            if flags == "s":
                body.append(("s", en, ar, None, [], None))
                continue
            vals = [ys[c][key] for c in cols]
            toks = []
            for c, v in zip(cols, vals):
                neg = "n" in flags
                signed = -v if neg else v
                toks.append(fmt_num(signed, d, eastern, signed < 0))
            body.append(("t" if "t" in flags else "r", en, ar, note, toks, key))
            if not key.startswith("_"):
                for c, v, tok in zip(cols, vals, toks):
                    truth.append(dict(key=key, label=ar if lang == "ar" else en, label_en=en, label_ar=ar,
                                      period_end=sp["years"][c].isoformat(), value=round(v / 10 ** d * scale / 1e6, 6),
                                      page=page_no, statement=code, raw=tok, nil=(v == 0)))
        pages.append((code, ten, tar, body))
    # html
    rtl = lang == "ar"
    h = ["<!doctype html><html lang='%s' dir='%s'><head><meta charset='utf-8'><style>%s</style></head><body class='%s'>"
         % ("ar" if rtl else "en", "rtl" if rtl else "ltr", CSS, lang)]
    cur_dt, prior_dt = sp["years"][cols[0]], sp["years"][cols[1]]
    for code, ten, tar, body in pages:
        is_pos = code == "BS"
        h.append("<section class='page'>")
        if lang == "ar":
            h.append(f"<h1>{html.escape(sp['company_ar'])}</h1><h2>{tar}</h2>")
            if code == "BS":
                h.append(f"<div class='sub'>كما في {d_ar(cur_dt, eastern)}</div>")
            elif code == "NOTE":
                h.append(f"<div class='sub'>للسنة المنتهية في {d_ar(cur_dt, eastern)}</div>")
            else:
                h.append(f"<div class='sub'>عن السنة المنتهية في {d_ar(cur_dt, eastern)}</div>")
            h.append(f"<div class='unit'>{UNIT_AR[(ccy, scale)]}</div>")
        elif lang == "bi":
            h.append(f"<h1>{html.escape(sp['company'])} &nbsp;|&nbsp; <span dir='rtl'>{html.escape(sp['company_ar'])}</span></h1>"
                     f"<h2>{ten} &nbsp;|&nbsp; <span dir='rtl'>{tar}</span></h2>")
            verb_en = "As at" if code == "BS" else "For the year ended"
            verb_ar = "كما في" if code == "BS" else "للسنة المنتهية في"
            h.append(f"<div class='sub'>{verb_en} {d_en(cur_dt)} &nbsp;|&nbsp; <span dir='rtl'>{verb_ar} "
                     f"{d_ar(cur_dt, False)}</span></div>")
            h.append(f"<div class='unit'>{UNIT_EN[(ccy, scale)]} &nbsp;|&nbsp; <span dir='rtl'>{UNIT_AR[(ccy, scale)]}</span></div>")
        else:
            h.append(f"<h1>{html.escape(sp['company'])}</h1><h2>{ten}</h2>")
            verb = "As at" if code == "BS" else "For the year ended"
            h.append(f"<div class='sub'>{verb} {d_en(cur_dt)}</div>")
            h.append(f"<div class='unit'>{UNIT_EN[(ccy, scale)]}</div>")
        # table
        def head(dt):
            if lang == "ar":
                return d_ar(dt, eastern)
            return d_en(dt)
        note_h = {"ar": "إيضاح", "en": "Note", "bi": "Note"}[lang]
        if lang == "bi":
            h.append(f"<table><colgroup><col style='width:34%'><col style='width:5%'><col style='width:13%'><col style='width:13%'><col style='width:35%'></colgroup><thead><tr><th style='text-align:left'>Particulars</th><th class='note'>{note_h}</th>"
                     f"<th class='n'>{d_en(cur_dt)}</th><th class='n'>{d_en(prior_dt)}</th>"
                     f"<th dir='rtl' style='text-align:right'>البيان</th></tr></thead><tbody>")
        else:
            lab_h = "البيان" if lang == "ar" else "Particulars"
            h.append(f"<table><thead><tr><th style='text-align:start'>{lab_h}</th><th class='note'>{note_h}</th>"
                     f"<th class='n'>{head(cur_dt)}</th><th class='n'>{head(prior_dt)}</th></tr></thead><tbody>")
        for kind, en, ar, note, toks, key in body:
            cls = {"t": "t", "s": "s", "r": ""}[kind]
            if kind == "s":
                if lang == "bi":
                    h.append(f"<tr class='s'><td>{en}</td><td></td><td></td><td></td><td dir='rtl' style='text-align:right'>{ar}</td></tr>")
                else:
                    h.append(f"<tr class='s'><td colspan='4'>{ar if lang == 'ar' else en}</td></tr>")
                continue
            nt = "" if note is None else edigits(str(note), eastern)
            ncell = "".join(f"<td class='n'><bdi dir='ltr'>{t}</bdi></td>" for t in toks)
            if lang == "bi":
                h.append(f"<tr class='{cls}'><td>{html.escape(en)}</td><td class='note'>{nt}</td>{ncell}"
                         f"<td dir='rtl' style='text-align:right'>{html.escape(ar)}</td></tr>")
            else:
                lab = ar if lang == "ar" else en
                h.append(f"<tr class='{cls}'><td>{html.escape(lab)}</td><td class='note'>{nt}</td>{ncell}</tr>")
        h.append("</tbody></table>")
        foot = ("تعتبر الإيضاحات المرفقة جزءاً لا يتجزأ من هذه القوائم المالية" if lang == "ar" else
                "The accompanying notes form an integral part of these financial statements")
        if lang == "bi":
            foot += " &nbsp;|&nbsp; <span dir='rtl'>تعتبر الإيضاحات المرفقة جزءاً لا يتجزأ من هذه القوائم المالية</span>"
        h.append(f"<div class='foot'>{foot}</div></section>")
    h.append("</body></html>")
    return "\n".join(h), truth


# --------------------------------------------------------------------------- rendering
def _chrome():
    for n in ("google-chrome", "chromium", "chromium-browser", "google-chrome-stable"):
        p = shutil.which(n)
        if p:
            return p
    raise SystemExit("no Chrome/Chromium found (needed to print native fixtures)")


def html_to_pdf(html_text, pdf_path, workdir):
    hp = os.path.join(workdir, "page.html")
    with open(hp, "w", encoding="utf-8") as fh:
        fh.write(html_text)
    cmd = [_chrome(), "--headless=new", "--no-sandbox", "--disable-gpu",
           "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", "file://" + hp]
    p = subprocess.run(cmd, capture_output=True, timeout=60, shell=False)
    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) < 500:
        raise SystemExit("chrome failed: " + p.stderr.decode("utf-8", "replace")[-400:])


def degrade_to_scan(native_pdf, out_pdf, skews, seed):
    """Rasterise at 200 dpi, add noise/blur/skew, save as an image-only PDF."""
    import numpy as np
    from PIL import Image, ImageFilter
    rng = np.random.default_rng(seed)
    with tempfile.TemporaryDirectory(prefix="acretia_scan_") as td:
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-png", native_pdf, os.path.join(td, "p")],
                       check=True, capture_output=True, timeout=180, shell=False)
        pngs = sorted(f for f in os.listdir(td) if f.endswith(".png"))
        imgs = []
        for i, f in enumerate(pngs):
            im = Image.open(os.path.join(td, f)).convert("L")
            a = np.asarray(im, dtype=np.float32)
            a = 238.0 + (a - 255.0) * 0.93                                   # greyer paper, slightly lighter ink
            a += rng.normal(0, 3.5, a.shape)                                 # sensor noise
            specks = rng.random(a.shape) < 0.0002                            # dust
            a[specks] -= 90
            im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.65))
            ang = skews[i % len(skews)]
            im = im.rotate(ang, resample=Image.BICUBIC, expand=False, fillcolor=238)
            imgs.append(im)
        imgs[0].save(out_pdf, "PDF", resolution=200.0, save_all=True, append_images=imgs[1:], quality=30)


def pdftotext(path):
    p = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, timeout=120, shell=False)
    return p.stdout.decode("utf-8", "replace")


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# --------------------------------------------------------------------------- build
def build_all(outdir):
    os.makedirs(outdir, exist_ok=True)
    chains = {k: make_chain(sp) for k, sp in SPECS.items()}
    entries = {}
    with tempfile.TemporaryDirectory(prefix="acretia_fx_") as work:
        for fx in FIXTURES:
            sp = SPECS[fx["spec"]]
            eastern = fx.get("eastern", sp["eastern"])
            cols = (fx["cur"], fx["cur"] - 1)
            htm, truth = build_pages(sp, fx, chains[fx["spec"]], cols, eastern)
            path = os.path.join(outdir, fx["file"])
            if fx["kind"] == "native":
                html_to_pdf(htm, path, work)
            else:
                nat = os.path.join(outdir, fx["raster_of"])
                degrade_to_scan(nat, path, fx["skew"], seed=sp["seed"] + 5)
            entries[fx["file"]] = dict(
                file=fx["file"], sha256=sha256(path), kind=fx["kind"], language=fx["language"],
                generator=GENERATOR, company=sp["company"], currency=sp["currency"],
                unit_scale=sp["scale"], fiscal_year_end_month=sp["fy_month"], standard=sp["standard"],
                digits="eastern_arabic" if eastern else "western",
                periods=[sp["years"][cols[1]].isoformat(), sp["years"][cols[0]].isoformat()],
                pages=len(set(t["page"] for t in truth)), bytes=os.path.getsize(path),
                derived_from=fx.get("raster_of"), ground_truth=truth)
    return [entries[f["file"]] for f in FIXTURES]


def ties_ok(truth):
    """Re-verify the accounting identities from ground-truth values alone."""
    by = {}
    for t in truth:
        by.setdefault(t["period_end"], {})[t["key"]] = t["value"]
    errs = []
    for p, v in by.items():
        def eq(a, b, name):
            if a in v and b in v and abs(v[a] - v[b]) > 1e-6:
                errs.append(f"{p} {name}: {a}={v[a]} vs {b}={v[b]}")
        eq("assets", "liabilities_equity", "BS balances")
        eq("x.cash_end", "cash", "cash ties")
        if "revenue" in v and "net_income" in v and "pretax" in v:
            tax = v.get("tax", 0) + v.get("x.zakat", 0)
            if abs(v["pretax"] - tax - v["net_income"]) > 1e-6:
                errs.append(f"{p} NI")
        if "cfo" in v:
            if abs(v["cfo"] + v["cfi"] + v["cff"] - v["net_change_cash"]) > 1e-6:
                errs.append(f"{p} CF sum")
            if abs(v["cf_net_income"] - v["net_income"]) > 1e-6:
                errs.append(f"{p} CF NI")
        if "current_assets" in v and abs(v["current_assets"] + v["x.noncurrent_assets"] - v["assets"]) > 1e-6:
            errs.append(f"{p} assets")
    return errs


def _digits_only(s):
    sys.path.insert(0, ROOT)
    from om.intl.numparse import normalise_digits
    return re.sub(r"\D", "", normalise_digits(s))


def check():
    mpath = os.path.join(OUT, "manifest.json")
    with open(mpath, encoding="utf-8") as fh:
        man = json.load(fh)
    bad = []
    with tempfile.TemporaryDirectory(prefix="acretia_chk_") as td:
        fresh = build_all(td)
        committed = {e["file"]: e for e in man["fixtures"]}
        if set(committed) != {e["file"] for e in fresh}:
            bad.append("fixture set differs from manifest")
        for e in fresh:
            c = committed.get(e["file"])
            if not c:
                continue
            for k in ("kind", "language", "generator", "company", "currency", "unit_scale",
                      "fiscal_year_end_month", "ground_truth", "periods", "digits"):
                if c.get(k) != e.get(k):
                    bad.append(f"{e['file']}: {k} differs from regenerated ground truth")
            errs = ties_ok(e["ground_truth"])
            bad += [f"{e['file']}: tie {m}" for m in errs]
            # committed file integrity
            cp = os.path.join(OUT, e["file"])
            if not os.path.exists(cp):
                bad.append(f"{e['file']}: missing")
            elif sha256(cp) != c["sha256"]:
                bad.append(f"{e['file']}: committed bytes differ from manifest sha256")
            # text layer of the regenerated file
            txt = pdftotext(os.path.join(td, e["file"]))
            if e["kind"] == "native":
                have = {t for t in re.findall(r"[\d٠-٩۰-۹][\d٠-٩۰-۹,.٫٬]*", txt)}
                have_digits = {_digits_only(t) for t in have}
                missing = [g["raw"] for g in e["ground_truth"]
                           if g["raw"] != "-" and _digits_only(g["raw"]) not in have_digits]
                if missing:
                    bad.append(f"{e['file']}: {len(missing)} tokens missing from text layer, e.g. {missing[:4]}")
            else:
                if re.search(r"\d", txt):
                    bad.append(f"{e['file']}: scanned fixture has a text layer")
            n = subprocess.run(["pdfinfo", os.path.join(td, e["file"])], capture_output=True, shell=False).stdout.decode()
            m = re.search(r"Pages:\s+(\d+)", n)
            if not m or int(m.group(1)) != e["pages"]:
                bad.append(f"{e['file']}: page count {m.group(1) if m else '?'} != {e['pages']}")
    for b in bad:
        print("FAIL", b)
    if not bad:
        print(f"OK: {len(man['fixtures'])} fixtures, ground truth and text layers verified")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        sys.exit(check())
    fixtures = build_all(OUT)
    man = dict(generator=GENERATOR, note="Synthetic reports generated by our own script; ground-truth values are "
               "reporting-currency millions in the om.statements sign convention (expenses positive).",
               fixtures=fixtures)
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    for f in fixtures:
        print(f"{f['file']}: {f['bytes'] // 1024} KB, {f['pages']} pages, {len(f['ground_truth'])} figures")


if __name__ == "__main__":
    main()
