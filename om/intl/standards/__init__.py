"""Accounting-standards knowledge base (S8.1). Deterministic: YAML data plus lexical retrieval, no model calls.

    kb = load()
    kb.frameworks            # {id: framework dict}
    kb.differences           # list of difference-entry dicts
    kb.find(topic=..., framework=...)
    kb.answer("How does IFRS 16 differ from ASC 842?") -> Answer(text, citations, entries)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).parent
RECIPE_IDS = (
    "ifrs16_to_pre16_ebitda", "lease_adjusted_net_debt", "capitalise_operating_leases", "zakat_as_tax", "by_nature_ebit",
    "ias29_restate", "fx_translate_period_end_average", "devaluation_fx_loss_normalise", "eosb_as_debt_like",
    "dev_cost_expense", "revaluation_reverse", "impairment_reversal_strip", "capitalised_interest_expense", "lifo_to_fifo",
    "gov_grant_gross_up", "associates_share_strip", "revenue_principal_agent_net", "eas_to_ifrs_map",
)

# Concept table: regex over normalised text -> concept token. Applied to both entries and questions, so any
# surface form of a concept ("right-of-use", "ASC 842", "operating lease") reaches the same entries.
CONCEPTS = [
    ("c_lease", r"\blease|\bleasing|right of use|\brou\b|ifrs 16|asc 842|eas 49|ind as 116|\brent\b|ايجار"),
    ("c_revenue", r"revenue|ifrs 15|asc 606|eas 48|ind as 115|performance obligation|principal|\bagent\b|gross vs net|ايراد|مبيعات"),
    ("c_inventory", r"inventor|\blifo\b|\bfifo\b|ias 2\b|weighted average cost|مخزون"),
    ("c_devcost", r"development cost|research and development|\br&d\b|\br and d\b|capitalis\w* development|ias 38|intangible"),
    ("c_reval", r"revalu|fair value model|revaluation surplus|ias 16\b"),
    ("c_impair", r"impair|write back|writeback|ias 36|recoverable amount|goodwill test"),
    ("c_borrow", r"borrowing cost|capitali[sz]ed interest|interest capitali|ias 23|qualifying asset"),
    ("c_assoc", r"associate|joint venture|\bjv\b|equity method|equity account|ias 28|ifrs 11|joint operation|significant influence"),
    ("c_hyper", r"hyperinflat|ias 29|inflation accounting|price index|monetary gain|general price"),
    ("c_fx", r"devalu|\bfloat\w*|egyptian pound|\begp\b|exchange rate|foreign exchange|\bfx\b|ias 21|eas 13|translation|currency|\bcta\b|exchange loss|exchange difference"),
    ("c_zakat", r"zakat|zakah|zatca|gazt|زكاه"),
    ("c_tax", r"\btax|ias 12|deferred tax|corporate tax|effective rate"),
    ("c_eosb", r"eosb|end of service|gratuity|termination benefit|indemnity|labou?r law|ias 19|employee benefit|نهايه الخدمه|مكافاه"),
    ("c_grant", r"government grant|\bgrant|subsid|government assistance|ias 20"),
    ("c_eas", r"\beas\b|egyptian accounting|\begypt|\bfra\b|مصر|معايير المحاسبه المصريه"),
    ("c_ksa", r"saudi|\bksa\b|socpa|tadawul|السعوديه"),
    ("c_uae", r"\buae\b|emirates|abu dhabi|dubai|gcc|الامارات"),
    ("c_uk", r"\buk\b|frs 102|united kingdom|companies act"),
    ("c_india", r"\bind as\b|india|schedule iii|mca\b"),
    ("c_us", r"us gaap|\bgaap\b|asc \d+|fasb|united states|\bsec\b"),
    ("c_presentation", r"by nature|by function|nature of expense|function of expense|operating profit|\bebit\b|ias 1\b|ifrs 18|presentation|line item|statement layout|\boci\b|current and non current|cost of sales|gross profit"),
    ("c_cashflow", r"cash flow|ias 7|asc 230|interest paid|dividends paid|operating cash"),
    ("c_credit", r"\becl\b|\bcecl\b|credit loss|ifrs 9|eas 47|loss allowance|financial instrument"),
    ("c_netdebt", r"net debt|leverage|enterprise value|\bev\b"),
    ("c_ebitda", r"ebitda"),
    ("c_pillar", r"pillar two|\bdmtt\b|top up tax|minimum tax|globe"),
    ("c_segment", r"segment|\bcodm\b|ifrs 8|operating decision maker"),
    ("c_eps", r"\beps\b|earnings per share|dilut|ias 33"),
    ("c_related", r"related part|key management|ias 24"),
    ("c_separate", r"separate financial|ias 27|eas 17|standalone accounts"),
    ("c_applicability", r"applicab|net worth|crore|roadmap"),
    ("c_mapping", r"eas \d+|map|equivalent|correspond"),
]
_CONCEPTS = [(c, re.compile(p)) for c, p in CONCEPTS]

STOP = set("""a an the of for to in on and or is are was be by with as at from how what which do does did vs versus
under between about it its this that these those can should would we i you my our their than then there when
where why who whom if not no any all each more most such into out up over per also may must will""".split())

_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "ـ": ""})
_AR_DIAC = re.compile(r"[ً-ٰٟ]")
_EAST = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalise(text: str) -> str:
    t = _AR_DIAC.sub("", str(text)).translate(_AR_MAP).translate(_EAST).lower()
    t = t.replace("&", " & ")
    t = re.sub(r"[-_/]", " ", t)
    t = re.sub(r"[^\w& ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(text: str) -> list[str]:
    n = normalise(text)
    out = [w for w in n.split() if w not in STOP and len(w) > 1 or w.isdigit()]
    out = [w for w in out if w not in STOP]
    # light stemming for plurals / -ing / -ed on plain words
    stem = []
    for w in out:
        if w.isascii() and len(w) > 4:
            for suf in ("ations", "ation", "ings", "ing", "es", "ed", "s"):
                if w.endswith(suf) and len(w) - len(suf) >= 4:
                    w = w[: -len(suf)]
                    break
        stem.append(w)
    return stem


def concepts(text: str) -> set[str]:
    n = normalise(text)
    return {c for c, rx in _CONCEPTS if rx.search(n)}


@dataclass
class Answer:
    text: str
    citations: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    confidence: str = "unverified"
    score: float = 0.0


class KB:
    def __init__(self, frameworks: dict, differences: list, standards: list):
        self.frameworks = frameworks
        self.differences = differences
        self.standards = standards
        self._entries = self._build_entries()
        self._index()

    # -- data access ------------------------------------------------------------------------------------------
    @property
    def entries(self) -> list:
        return self._entries

    def _build_entries(self) -> list:
        out = []
        for d in self.differences:
            out.append({**d, "kind": "difference"})
        for s in self.standards:
            out.append({**s, "kind": "standard", "topic": s.get("title", s["standard"]), "frameworks": ["IFRS"]})
        for fid, f in self.frameworks.items():
            pres = f.get("presentation", {})
            text = " ".join([f["summary"], f.get("relationship_to_ifrs", ""), str(pres.get("pnl_layout", "")),
                             str(pres.get("balance_sheet_order", "")), str(pres.get("oci", ""))])
            out.append({"id": f"fw-{fid}", "kind": "framework", "topic": f["name"], "frameworks": [fid], "summary": text,
                        "analyst_impact": " ".join(f.get("key_disclosures", [])[:3]), "citations": f["citations"],
                        "authored": "acretia", "confidence": f.get("confidence", "unverified"),
                        "keywords": [fid, f["name"], "presentation", "layout", "framework"] + list(f.get("jurisdictions", []))})
        return out

    def find(self, topic: str | None = None, framework: str | None = None) -> list:
        """Difference entries matching a topic (id, topic or keyword substring, concept-aware) and/or a framework."""
        res = [e for e in self.differences]
        if framework:
            fw = _fw_id(framework)
            res = [e for e in res if fw in e["frameworks"]]
        if topic:
            tn = normalise(topic)
            tc = concepts(topic)
            def hit(e):
                hay = normalise(" ".join([e["id"], e["topic"], " ".join(map(str, e.get("keywords", [])))]))
                return tn in hay or bool(tc and _topic_match(tn, tc, e))
            res = [e for e in res if hit(e)]
        return res

    # -- retrieval --------------------------------------------------------------------------------------------
    def _index(self):
        self._tok, self._con, df = [], [], {}
        for e in self._entries:
            head = " ".join([e["id"], e.get("topic", ""), " ".join(map(str, e.get("keywords", []))), e.get("standard", ""),
                             " ".join(c["standard"] for c in e["citations"])])
            body = " ".join([e["summary"], e.get("analyst_impact", ""), " ".join(e.get("disclosures", []) or [])])
            t_head, t_body = set(tokens(head)), set(tokens(body))
            self._tok.append((t_head, t_body))
            self._con.append((concepts(head), concepts(body)))
            for w in t_head | t_body:
                df[w] = df.get(w, 0) + 1
        n = len(self._entries)
        self._idf = {w: math.log(1 + n / c) for w, c in df.items()}

    def _score(self, q_tok, q_con, q_fw, i):
        e = self._entries[i]
        t_head, t_body = self._tok[i]
        c_head, c_body = self._con[i]
        s = 0.0
        for w in q_tok:
            idf = self._idf.get(w, 0.0)
            if w in t_head:
                s += 2.0 * idf
            elif w in t_body:
                s += 1.0 * idf
        for c in q_con:
            if c in c_head:
                s += 4.0
            elif c in c_body:
                s += 1.0
        if q_fw:
            fws = set(e["frameworks"])
            if fws & q_fw:
                s += 2.5 * len(fws & q_fw) / max(1, len(q_fw))
        if e["kind"] == "difference":
            s *= 1.15
        if e["kind"] == "framework" and not (q_con & {"c_presentation"}) and not q_fw:
            s *= 0.6
        return s

    def answer(self, question: str, k: int = 3) -> Answer:
        """Compose from the best standard-level entry (always, when the question names or strongly matches a standard),
        then the best difference/framework entries (up to k), full summaries, plus verified facts that match the query."""
        q_tok = tokens(question)
        q_con = concepts(question)
        q_fw = _question_frameworks(question)
        scored = sorted(((self._score(q_tok, q_con, q_fw, i), i) for i in range(len(self._entries))), reverse=True)
        top = [(s, i) for s, i in scored if s > 0]
        if not top or top[0][0] < 1.5 or (not q_con and not q_fw and top[0][0] < 5.0):
            return Answer("No entry in the knowledge base matches this question closely enough to answer it.", [], [], "unverified", 0.0)
        best = top[0][0]
        qn = " " + normalise(question) + " "
        named = {i for i, e in enumerate(self._entries) if e["kind"] == "standard" and f" {normalise(e['standard'])} " in qn}
        std_idx = None
        for s, i in top:
            if self._entries[i]["kind"] != "standard":
                continue
            if i in named or s >= 0.5 * best:
                std_idx = i
                break
        std_candidates = [i for s, i in top if i in named]
        if std_candidates:
            std_idx = std_candidates[0]
        picked_idx = [std_idx] if std_idx is not None else []
        best_other = next((s for s, i in top if self._entries[i]["kind"] != "standard"), best)
        for s, i in top:
            if len(picked_idx) >= k + (1 if std_idx is not None else 0):
                break
            if i in picked_idx or self._entries[i]["kind"] == "standard":
                continue
            if s >= 0.6 * best_other:
                picked_idx.append(i)
        if not picked_idx:
            picked_idx = [top[0][1]]
        picked = [self._entries[i] for i in picked_idx]
        qset = set(q_tok)
        parts, cits, seen = [], [], set()
        for e in picked:
            label = e["topic"] if e["kind"] != "standard" else f"{e['standard']} ({e['topic']})"
            part = f"{label} [{', '.join(e['frameworks'])}]: {_fold(e['summary'])}"
            if e.get("analyst_impact"):
                part += f" Analyst impact: {_fold(e['analyst_impact'])}"
            if e.get("adjustment"):
                part += f" Adjustment recipe: {e['adjustment']}."
            vf = [v["fact"] for v in e.get("verified_facts", []) if qset & set(tokens(v["fact"])) or q_con & concepts(v["fact"])]
            if vf:
                part += " Verified facts: " + "; ".join(vf) + "."
            parts.append(part)
            for c in e["citations"]:
                key = (c["standard"], c["ref"], c["url"])
                if key not in seen:
                    seen.add(key)
                    cits.append(dict(c))
        conf = "verified" if all(e.get("confidence") == "verified" for e in picked) else "unverified"
        return Answer("\n\n".join(parts), cits, picked, conf, best)


def _fold(t: str) -> str:
    return re.sub(r"\s+", " ", str(t)).strip()


_FW_ALIASES = {
    "ifrs": "IFRS", "eas": "EAS", "egypt": "EAS", "egyptian": "EAS", "socpa": "SOCPA-IFRS", "saudi": "SOCPA-IFRS",
    "ksa": "SOCPA-IFRS", "uae": "UAE-IFRS", "gcc": "UAE-IFRS", "frs102": "FRS102", "frs 102": "FRS102", "uk": "FRS102",
    "ind as": "IndAS", "indas": "IndAS", "india": "IndAS", "indian": "IndAS", "us gaap": "USGAAP", "usgaap": "USGAAP",
    "gaap": "USGAAP", "asc": "USGAAP", "fasb": "USGAAP", "us": "USGAAP",
}


def _fw_id(name: str) -> str:
    n = normalise(name)
    return _FW_ALIASES.get(n, name)


def _question_frameworks(q: str) -> set:
    n = " " + normalise(q) + " "
    out = set()
    for pat, fw in [(r"\bifrs\b", "IFRS"), (r"\beas\b|egypt|egyptian", "EAS"), (r"socpa|saudi|\bksa\b|zakat|zatca|tadawul", "SOCPA-IFRS"),
                    (r"\buae\b|emirates|gcc|dubai|abu dhabi", "UAE-IFRS"), (r"frs 102|\buk\b|united kingdom", "FRS102"),
                    (r"\bind as\b|india", "IndAS"), (r"us gaap|\bgaap\b|\basc \d+|fasb|united states|\bus\b", "USGAAP")]:
        if re.search(pat, n):
            out.add(fw)
    return out


def _topic_match(tn: str, tc: set, e: dict) -> bool:
    """A topic query matches an entry when it shares a head concept (topic/keywords) with it."""
    head = " ".join([e["id"], e["topic"], " ".join(map(str, e.get("keywords", [])))])
    return bool(tc & concepts(head))


_CACHE: KB | None = None


def load(force: bool = False) -> KB:
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    def rd(name, key):
        return yaml.safe_load((HERE / name).read_text(encoding="utf-8"))[key]
    fw = {f["id"]: f for f in rd("frameworks.yaml", "frameworks")}
    _CACHE = KB(fw, rd("differences.yaml", "differences"), rd("ifrs_standards.yaml", "standards"))
    return _CACHE


__all__ = ["load", "KB", "Answer", "RECIPE_IDS", "normalise", "tokens", "concepts"]
