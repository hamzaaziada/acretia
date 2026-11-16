"""Private funding rounds from SEC Form D (Regulation D exempt offerings), quarterly DERA data sets.

Every US company raising money privately under Reg D files a Form D within 15 days of the first sale.
The SEC publishes all filings as quarterly ZIPs (2008 Q1 onward). Each round here carries: issuer, location,
industry group, year of incorporation, revenue range (when disclosed), securities offered, total offering
amount, amount sold, number of investors, first-sale date, exemptions and the filing link.

Rules
- Pooled investment funds (VC/PE/hedge fund vehicles) are excluded by default: they are fund raises, not
  company rounds. Real estate offerings can be excluded with exclude_real_estate.
- Amendments (D/A) are chained to their original filing and collapsed into one round; the latest
  amounts win (amount sold only grows as the round closes).
- Form D has no valuation field. Amounts are as reported; "Indefinite" offering amounts are kept as null.
- Personal data is minimised: related-person names are not stored, only the count.
"""
from __future__ import annotations

import csv
import io
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path

INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets"

SCHEMA = """
CREATE TABLE IF NOT EXISTS funding_rounds(
  round_id TEXT PRIMARY KEY,            -- accession of the original filing
  latest_accession TEXT, cik INTEGER, company TEXT, city TEXT, state TEXT, country TEXT, jurisdiction TEXT,
  entity_type TEXT, year_incorporated INTEGER, industry TEXT, revenue_range TEXT,
  securities TEXT, exemptions TEXT, first_sale_date TEXT, yet_to_occur INTEGER,
  offering_amount REAL, amount_sold REAL, amount_remaining REAL, investors INTEGER, non_accredited INTEGER,
  minimum_investment REAL, sales_commission REAL, finders_fee REAL, proceeds_to_insiders REAL,
  related_persons INTEGER, filings INTEGER, first_filed TEXT, last_filed TEXT, quarter TEXT, url TEXT,
  category TEXT);
CREATE INDEX IF NOT EXISTS ix_fr_cik ON funding_rounds(cik);
CREATE INDEX IF NOT EXISTS ix_fr_date ON funding_rounds(first_sale_date);
CREATE INDEX IF NOT EXISTS ix_fr_ind ON funding_rounds(industry);
CREATE INDEX IF NOT EXISTS ix_fr_cat ON funding_rounds(category);
CREATE TABLE IF NOT EXISTS formd_quarters(quarter TEXT PRIMARY KEY, loaded_at REAL, filings INTEGER, rounds INTEGER);
"""
VEHICLE_INDUSTRIES = {"Investing", "REITS and Finance", "Pooled Investment Fund", "Other Banking and Financial Services"}
REAL_ESTATE_INDUSTRIES = {"Other Real Estate", "Commercial", "Residential", "Construction", "REITS and Finance"}
VEHICLE_NAME = re.compile(
    r"(?i)\b(fund|funds|feeder|master|portfolio|conglomerate|income|credit|lending|capital partners|investors?,? (llc|lp|l\.p\.)|"
    r"(co-?)?invest(ment)?s? (llc|lp|l\.p\.)|opportunit(y|ies)|series [a-z0-9]+ of|spv|trust|separate account|annuity|"
    r"variable (life|universal)|insurance co(mpany)?( of [a-z ]+)?$|life insurance co(mpany)?|ppvul|vul)\b|\b(l\.?p\.?|lp)\s*$")
REAL_ESTATE_NAME = re.compile(r"(?i)\b(apartments?|propert(y|ies)|realty|real estate|reit|multifamily|self[- ]storage|"
                              r"housing|residences?|plaza|tower|lofts?|land|acquisitions? (llc|lp))\b")


def classify(industry: str, name: str, investors: int, first_sale: str | None, filed: str | None) -> str:
    """company | vehicle | real_estate (public_pipe is assigned later from the listed-company list).
    Form D only flags pooled funds explicitly; many vehicles file as 'Other'."""
    if industry in REAL_ESTATE_INDUSTRIES or REAL_ESTATE_NAME.search(name):
        return "real_estate"
    if industry in VEHICLE_INDUSTRIES or VEHICLE_NAME.search(name):
        return "vehicle"
    if investors >= 1000:          # retail-scale evergreen products, not company rounds
        return "vehicle"
    if first_sale and filed and first_sale < f"{int(filed[:4]) - 2}{filed[4:]}":   # still selling 2+ years after first sale
        return "vehicle"
    return "company"


US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split())


def list_quarters(sec) -> dict[str, str]:
    """quarter ('2026Q3') -> absolute zip URL, read from the SEC index page (paths vary by quarter)."""
    html = sec._get(INDEX_URL).decode("utf-8", "ignore")
    out = {}
    for href in re.findall(r'href="([^"]*?(\d{4})q([1-4])_d\.zip)"', html):
        url = href[0] if href[0].startswith("http") else "https://www.sec.gov" + href[0]
        out[f"{href[1]}Q{href[2]}"] = url
    return dict(sorted(out.items(), reverse=True))


def _num(s: str | None) -> float | None:
    s = (s or "").strip().replace(",", "")
    try:
        return float(s) if s and s.lower() not in ("indefinite", "n/a", "none") else None
    except ValueError:
        return None


def _date(s: str | None) -> str | None:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _tsv(z: zipfile.ZipFile, name: str):
    member = next(n for n in z.namelist() if n.upper().endswith(f"/{name}.TSV") or n.upper() == f"{name}.TSV")
    with z.open(member) as fh:
        yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"), delimiter="\t")


def parse_quarter(data: bytes, quarter: str, exclude_real_estate: bool = False) -> list[dict]:
    z = zipfile.ZipFile(io.BytesIO(data))
    subs = {r["ACCESSIONNUMBER"]: r for r in _tsv(z, "FORMDSUBMISSION") if (r.get("TESTORLIVE") or "LIVE").upper() == "LIVE"}
    issuers = {}
    for r in _tsv(z, "ISSUERS"):
        if r.get("IS_PRIMARYISSUER_FLAG", "").upper() == "YES":
            issuers[r["ACCESSIONNUMBER"]] = r
    related: dict[str, int] = {}
    for r in _tsv(z, "RELATEDPERSONS"):
        related[r["ACCESSIONNUMBER"]] = related.get(r["ACCESSIONNUMBER"], 0) + 1
    out = []
    for o in _tsv(z, "OFFERING"):
        acc = o["ACCESSIONNUMBER"]
        sub, iss = subs.get(acc), issuers.get(acc)
        if not sub or not iss:
            continue
        industry = (o.get("INDUSTRYGROUPTYPE") or "").strip()
        if industry == "Pooled Investment Fund" or (o.get("ISPOOLEDINVESTMENTFUNDTYPE") or "").lower() == "true":
            continue
        if exclude_real_estate and ("Real Estate" in industry or industry in ("Commercial", "Residential", "REITS and Finance")):
            continue
        secs = [name for flag, name in (("ISEQUITYTYPE", "equity"), ("ISDEBTTYPE", "debt"), ("ISOPTIONTOACQUIRETYPE", "options/warrants"),
                                        ("ISSECURITYTOBEACQUIREDTYPE", "securities on exercise"), ("ISTENANTINCOMMONTYPE", "tenant-in-common"),
                                        ("ISMINERALPROPERTYTYPE", "mineral property"), ("ISBUSINESSCOMBINATIONTRANS", "business combination"))
                if (o.get(flag) or "").lower() == "true"]
        if (o.get("ISOTHERTYPE") or "").lower() == "true":
            secs.append((o.get("DESCRIPTIONOFOTHERTYPE") or "other").strip()[:60])
        st = (iss.get("STATEORCOUNTRY") or "").strip()
        cik = int(iss.get("CIK") or 0)
        yr = (iss.get("YEAROFINC_VALUE_ENTERED") or "").strip()
        out.append({
            "accession": acc, "previous": (o.get("PREVIOUSACCESSIONNUMBER") or "").strip() or None,
            "is_amendment": (o.get("ISAMENDMENT") or "").lower() == "true" or sub.get("SUBMISSIONTYPE") == "D/A",
            "filed": _date(sub.get("FILING_DATE")), "cik": cik, "company": (iss.get("ENTITYNAME") or "").strip(),
            "city": (iss.get("CITY") or "").strip().title(), "state": st if st in US_STATES else None,
            "country": "US" if st in US_STATES else (iss.get("STATEORCOUNTRYDESCRIPTION") or st).strip().title(),
            "jurisdiction": (iss.get("JURISDICTIONOFINC") or "").strip().title(),
            "entity_type": (iss.get("ENTITYTYPE") or "").strip(),
            "year_incorporated": int(yr) if yr.isdigit() else None,
            "industry": industry, "revenue_range": (o.get("REVENUERANGE") or "").strip() or None,
            "securities": ", ".join(secs), "exemptions": (o.get("FEDERALEXEMPTIONS_ITEMS_LIST") or "").strip(),
            "first_sale_date": _date(o.get("SALE_DATE")), "yet_to_occur": (o.get("YETTOOCCUR") or "").lower() == "true",
            "offering_amount": _num(o.get("TOTALOFFERINGAMOUNT")), "amount_sold": _num(o.get("TOTALAMOUNTSOLD")),
            "amount_remaining": _num(o.get("TOTALREMAINING")), "investors": int(_num(o.get("TOTALNUMBERALREADYINVESTED")) or 0),
            "non_accredited": int(_num(o.get("NUMBERNONACCREDITEDINVESTORS")) or 0),
            "minimum_investment": _num(o.get("MINIMUMINVESTMENTACCEPTED")), "sales_commission": _num(o.get("SALESCOMM_DOLLARAMOUNT")),
            "finders_fee": _num(o.get("FINDERSFEE_DOLLARAMOUNT")), "proceeds_to_insiders": _num(o.get("GROSSPROCEEDSUSED_DOLLARAMOUNT")),
            "related_persons": related.get(acc, 0), "quarter": quarter,
            "category": classify(industry, (iss.get("ENTITYNAME") or ""), int(_num(o.get("TOTALNUMBERALREADYINVESTED")) or 0),
                                 _date(o.get("SALE_DATE")), _date(sub.get("FILING_DATE"))),
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/",
        })
    return out


class Rounds:
    def __init__(self, db):
        self.db = db
        self.db.executescript(SCHEMA.replace("CREATE INDEX IF NOT EXISTS ix_fr_cat ON funding_rounds(category);", ""))
        if "category" not in {r[1] for r in self.db.execute("PRAGMA table_info(funding_rounds)")}:
            self.db.execute("ALTER TABLE funding_rounds ADD COLUMN category TEXT")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_fr_cat ON funding_rounds(category)")

    def upsert(self, filings: list[dict]) -> int:
        """Chain amendments to their original filing; latest filing's amounts win."""
        filings = sorted(filings, key=lambda f: (f["filed"] or "", f["accession"]))
        n = 0
        for f in filings:
            root = f["accession"]
            if f["is_amendment"] and f["previous"]:
                r = self.db.execute("SELECT round_id FROM funding_rounds WHERE round_id=? OR latest_accession=?",
                                    (f["previous"], f["previous"])).fetchone()
                root = r["round_id"] if r else f["previous"]
            elif f["is_amendment"]:
                # amendment without a reference: attach to this issuer's round with the same first-sale date
                r = self.db.execute("SELECT round_id FROM funding_rounds WHERE cik=? AND first_sale_date IS ? ORDER BY last_filed DESC LIMIT 1",
                                    (f["cik"], f["first_sale_date"])).fetchone()
                root = r["round_id"] if r else root
            prev = self.db.execute("SELECT * FROM funding_rounds WHERE round_id=?", (root,)).fetchone()
            if prev and prev["last_filed"] and f["filed"] and f["filed"] < prev["last_filed"]:
                # an older filing of a round we already hold (quarters can load in any order): extend history only
                self.db.execute("""UPDATE funding_rounds SET filings=filings+1, first_filed=MIN(first_filed, ?),
                                   amount_sold=MAX(COALESCE(amount_sold,0), COALESCE(?,0)),
                                   related_persons=MAX(related_persons, ?) WHERE round_id=?""",
                                (f["filed"], f["amount_sold"], f["related_persons"], root))
                n += 1
                continue
            sold = f["amount_sold"]
            if prev and prev["amount_sold"] and (sold is None or sold < prev["amount_sold"]):
                sold = prev["amount_sold"]
            vals = {**{k: f[k] for k in ("cik", "company", "city", "state", "country", "jurisdiction", "entity_type", "year_incorporated",
                                         "industry", "revenue_range", "securities", "exemptions", "first_sale_date", "offering_amount",
                                         "amount_remaining", "investors", "non_accredited", "minimum_investment", "sales_commission",
                                         "finders_fee", "proceeds_to_insiders", "quarter", "url", "category")},
                    "round_id": root, "latest_accession": f["accession"], "yet_to_occur": int(f["yet_to_occur"]), "amount_sold": sold,
                    "filings": (prev["filings"] + 1) if prev else 1,
                    "first_filed": min(x for x in (prev["first_filed"], f["filed"]) if x) if prev and prev["first_filed"] else f["filed"],
                    "related_persons": max(f["related_persons"], prev["related_persons"] or 0) if prev else f["related_persons"],
                    "last_filed": f["filed"]}
            cols = ",".join(vals)
            self.db.execute(f"INSERT OR REPLACE INTO funding_rounds({cols}) VALUES({','.join('?' * len(vals))})", list(vals.values()))
            n += 1
        self.db.commit()
        return n

    def load_quarter(self, sec, quarter: str, url: str, cache_dir: Path, exclude_real_estate: bool = False,
                     public_ciks: set[int] | None = None) -> dict:
        path = Path(cache_dir) / f"{quarter}_d.zip"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(sec._get(url, timeout=600))
        filings = parse_quarter(path.read_bytes(), quarter, exclude_real_estate)
        for f in filings:   # listed companies raising privately are PIPEs, not venture rounds
            if public_ciks and f["cik"] in public_ciks and f["category"] == "company":
                f["category"] = "public_pipe"
        self.upsert(filings)
        rounds = self.db.execute("SELECT COUNT(*) FROM funding_rounds WHERE quarter=?", (quarter,)).fetchone()[0]
        self.db.execute("INSERT OR REPLACE INTO formd_quarters VALUES(?,?,?,?)", (quarter, time.time(), len(filings), rounds))
        self.db.commit()
        return {"quarter": quarter, "filings": len(filings), "rounds": rounds}

    # ------------------------------------------------------------------ query
    def search(self, q: str = "", industry: str = "", state: str = "", min_sold: float | None = None,
               date_from: str = "", date_to: str = "", equity_only: bool = False, sort: str = "date",
               limit: int = 50, offset: int = 0, category: str = "company") -> dict:
        w, args = self._where(q, industry, state, min_sold, date_from, date_to, equity_only, category)
        order = {"date": "first_filed DESC, amount_sold DESC", "amount": "amount_sold DESC",
                 "investors": "investors DESC"}.get(sort, "first_filed DESC")
        total = self.db.execute(f"SELECT COUNT(*), COALESCE(SUM(amount_sold),0) FROM funding_rounds WHERE {w}", args).fetchone()
        rows = [dict(r) for r in self.db.execute(f"SELECT * FROM funding_rounds WHERE {w} ORDER BY {order} LIMIT ? OFFSET ?",
                                                 args + [limit, offset])]
        return {"total": total[0], "total_sold": total[1], "results": rows}

    def stats(self, **filters) -> dict:
        res = self.search(**filters, limit=1)
        w_sql, args = self._where(**filters)
        cats = [dict(r) for r in self.db.execute(
            "SELECT category, COUNT(*) AS rounds, COALESCE(SUM(amount_sold),0) AS sold FROM funding_rounds GROUP BY category")]
        by_q = [dict(r) for r in self.db.execute(
            f"""SELECT substr(first_sale_date,1,4)||'-Q'||((CAST(substr(first_sale_date,6,2) AS INTEGER)+2)/3) AS sale_quarter,
                       COUNT(*) AS rounds, COALESCE(SUM(amount_sold),0) AS sold
                FROM funding_rounds WHERE {w_sql} AND first_sale_date IS NOT NULL
                GROUP BY sale_quarter ORDER BY sale_quarter""", args)]
        by_q = [{"quarter": r["sale_quarter"], "rounds": r["rounds"], "sold": r["sold"]} for r in by_q]
        by_ind = [dict(r) for r in self.db.execute(
            f"SELECT industry, COUNT(*) AS rounds, COALESCE(SUM(amount_sold),0) AS sold FROM funding_rounds WHERE {w_sql} "
            f"GROUP BY industry ORDER BY sold DESC LIMIT 15", args)]
        med = self._median(w_sql, args)
        return {"rounds": res["total"], "total_sold": res["total_sold"], "median_sold": med, "categories": cats,
                "by_quarter": by_q[-24:], "by_industry": by_ind,
                "quarters_loaded": [dict(r) for r in self.db.execute("SELECT * FROM formd_quarters ORDER BY quarter DESC")]}

    def _where(self, q="", industry="", state="", min_sold=None, date_from="", date_to="", equity_only=False,
               category="company", **_):
        where, args = ["1=1"], []
        if category and category != "all":
            where.append("category = ?")
            args.append(category)
        for w in (q or "").split():
            where.append("company LIKE ?")
            args.append(f"%{w}%")
        for cond, val in (("industry = ?", industry), ("first_sale_date >= ?", date_from), ("first_sale_date <= ?", date_to)):
            if val:
                where.append(cond)
                args.append(val)
        if state:
            where.append("(state = ? OR country = ?)")
            args += [state.upper(), state]
        if min_sold:
            where.append("amount_sold >= ?")
            args.append(min_sold)
        if equity_only:
            where.append("securities LIKE '%equity%'")
        return " AND ".join(where), args

    def _median(self, w_sql, args):
        n = self.db.execute(f"SELECT COUNT(*) FROM funding_rounds WHERE {w_sql} AND amount_sold > 0", args).fetchone()[0]
        if not n:
            return None
        r = self.db.execute(f"SELECT amount_sold FROM funding_rounds WHERE {w_sql} AND amount_sold > 0 ORDER BY amount_sold LIMIT 1 OFFSET ?",
                            args + [n // 2]).fetchone()
        return r[0]

    def industries(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT industry FROM funding_rounds WHERE industry <> '' ORDER BY industry")]

    def export_csv(self, path: Path, **filters) -> int:
        w_sql, args = self._where(**filters)
        rows = self.db.execute(f"SELECT * FROM funding_rounds WHERE {w_sql} ORDER BY first_sale_date DESC", args).fetchall()
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            if rows:
                w.writerow(rows[0].keys())
            for r in rows:
                w.writerow(list(r))
        return len(rows)


def public_ciks(universe_csv: Path) -> set[int]:
    """CIKs of exchange-listed companies (SEC company_tickers_exchange)."""
    if not Path(universe_csv).exists():
        return set()
    with open(universe_csv, newline="") as fh:
        return {int(r["cik"]) for r in csv.DictReader(fh) if r.get("exchange") not in ("", "OTC", "None", None)}
