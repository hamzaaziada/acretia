"""Generate docs/s8/standards/*.md from om/intl/standards/*.yaml. Use --check to verify the committed pages are current."""
import sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from om.intl.standards import load, FIELDS, FIELD_LABELS
kb = load(force=True)
out = ROOT / "docs/s8/standards"
out.mkdir(parents=True, exist_ok=True)
def fold(s): return re.sub(r"\s+", " ", str(s)).strip()
def facts(e):
    L = []
    if e.get("verified_facts"):
        L += ["", "**Verified facts**"] + [f"- {v['fact']}: <{v['url']}>" for v in e["verified_facts"]]
    if e.get("unverified_facts"):
        L += ["", "**Unverified facts**"] + [f"- {u}" for u in e["unverified_facts"]]
    return L
def cites(cs): return "\n".join(f"- {c['standard']}, {c['ref']}: <{c['url']}>" for c in cs)
files = {}
for fid, f in kb.frameworks.items():
    p = f["presentation"]; cf = p["cash_flow"]
    L = [f"# {f['name']}", "", f"*Generated from `om/intl/standards/frameworks.yaml`. Authored by Acretia in its own words. Confidence: {f['confidence']}.*", "",
         f"**Issuer:** {f['issuer']}  ", f"**Jurisdictions:** {', '.join(f['jurisdictions'])}", "", "## Summary", fold(f["summary"]), "",
         "## Relationship to full IFRS", fold(f["relationship_to_ifrs"]), "", "## Effective dates and caveats"]
    L += [f"- {d}" for d in f["effective_dates"]]
    L += ["", "## Presentation", f"- **Profit or loss layout:** {p['pnl_layout']}", f"- **Balance sheet order:** {p['balance_sheet_order']}", f"- **OCI:** {p['oci']}", "",
          "### Required line items"]
    for st, items in p["required_line_items"].items():
        L += [f"**{st}**", ""] + [f"- {i}" for i in items] + [""]
    L += ["### Cash flow choices", f"- Method: {cf['method']}", f"- Interest paid: {cf['interest_paid']}", f"- Interest received: {cf['interest_received']}",
          f"- Dividends paid: {cf['dividends_paid']}", f"- Dividends received: {cf['dividends_received']}", "", "## Measurement bases"]
    L += [f"- {m}" for m in f["measurement_bases"]]
    L += ["", "## Key disclosures an analyst reads"] + [f"- {d}" for d in f["key_disclosures"]]
    diffs = [d for d in kb.differences if fid in d["frameworks"]]
    L += ["", "## Difference entries involving this framework"] + [f"- `{d['id']}` ({d['topic']}): recipe `{d['adjustment']}`" for d in diffs]
    L += facts(f) + ["", "## Sources", cites(f["citations"]), ""]
    files[f"{fid.lower()}.md"] = "\n".join(L)
# IFRS standards page
L = ["# IFRS standards the analyst reads", "", "*Generated from `om/intl/standards/ifrs_standards.yaml`. Own words, no copied standard text.*", ""]
for s in kb.standards:
    L += [f"## {s['standard']}: {s['title']}", fold(s["summary"]), ""]
    for f in FIELDS:
        if s.get(f): L += [f"- **{FIELD_LABELS[f]}:** {fold(s[f])}"]
    L += ["", "**Analyst impact:** " + fold(s["analyst_impact"]), ""]
    if s.get("adjustment"): L += [f"**Recipe:** `{s['adjustment']}`", ""]
    L += [f"*Basis: {s.get('basis', 'n/a')}; confidence: {s['confidence']}*", "", cites(s["citations"]), ""]
files["eas-standards.md"] = "\n".join(["# Egyptian Accounting Standards and their IFRS counterparts", "", "*Generated from `om/intl/standards/eas_standards.yaml`. Numbering marked unverified is from the 2015 reissue as recalled; confirm against FRA text.*", "", "| EAS | Title | IFRS counterpart | What differs | Confidence |", "|---|---|---|---|---|"] + [f"| {r['number']} | {r['title']} | {r['ifrs']} | {fold(r['differs'])} | {'verified' if r.get('verified') else 'unverified'} |" for r in kb.eas] + [""])
files["ifrs-standards.md"] = "\n".join(L)
# differences page
L = ["# Differences and analyst adjustment recipes", "", "*Generated from `om/intl/standards/differences.yaml`.*", ""]
topics = {}
for d in kb.differences: topics.setdefault(d["topic"], []).append(d)
for t, ds in topics.items():
    L += [f"## {t}", ""]
    for d in ds:
        L += [f"### `{d['id']}`", f"- **Frameworks:** {', '.join(d['frameworks'])}", f"- **Confidence:** {d['confidence']}", f"- **Summary:** {fold(d['summary'])}",
              f"- **Analyst impact:** {fold(d['analyst_impact'])}", f"- **Adjustment recipe:** `{d['adjustment']}`", "- **Citations:**"]
        L += [f"  - {c['standard']}, {c['ref']}: <{c['url']}>" for c in d["citations"]]
        L += facts(d) + [""]
files["differences.md"] = "\n".join(L)
rd = ["# S8.1 Accounting-standards knowledge base", "",
      "Machine-readable data lives in `om/intl/standards/*.yaml`; load it with `om.intl.standards.load()`. Everything is paraphrased; no standard text is copied. Entries marked `unverified` hold jurisdiction details (decree numbers, effective dates, article numbers) that have not been confirmed against the issuer text.", "",
      "## Pages", ""] + [f"- [{kb.frameworks[k]['name']}]({k.lower()}.md)" for k in kb.frameworks] + ["- [IFRS standards depth](ifrs-standards.md)", "- [EAS list and IFRS counterparts](eas-standards.md)", "- [Differences and recipes](differences.md)", "",
      "## API", "", "`load() -> KB`; `KB.frameworks`, `KB.differences`, `KB.find(topic, framework)`, `KB.answer(question) -> Answer(text, citations, entries)`. Retrieval is deterministic: tokenise, concept synonym table (English and some Arabic), IDF scoring, compose the answer from top entries.", "",
      "## Regenerating", "", "These pages are generated from the YAML; edit the YAML, not the pages.", ""]
files["README.md"] = "\n".join(rd)
if "--check" in sys.argv:
    stale = [n for n, t in files.items() if not (out / n).exists() or (out / n).read_text(encoding="utf-8") != t]
    if stale:
        print("stale:", sorted(stale)); sys.exit(1)
    print("docs up to date")
else:
    for n, t in files.items(): (out / n).write_text(t, encoding="utf-8")
    print(sorted(files))
