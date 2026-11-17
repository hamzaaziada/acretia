"""Deck eval (S3.10): corpus of 20 briefs, a reliability run, determinism checks, results files and scorecard rows.

Offline only: no network, no live model, the critic is not run. Live model rows in `scorecard.csv` carry no score
(D-021: live evals run through the adapter with keys supplied by the user)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = ROOT / "evals" / "decks" / "briefs"
RESULTS_DIR = ROOT / "evals" / "decks" / "results"
SCORECARD = ROOT / "scorecard.csv"
MODELS = ("claude-frontier", "gpt-frontier", "open-weight")
BENCHES = ("bench_presenton", "bench_ppteval", "bench_slidesbench")
BENCH_NOTE = "not run: needs a live model (and Docker for Presenton); ledger decision borrow_ideas"


# ------------------------------------------------------------------ corpus
def load_corpus(directory: Path | None = None) -> list[dict]:
    """The briefs, in file order: [{name, path, brief: {brief, ghost, spec}}]."""
    import yaml
    out = []
    for p in sorted((directory or CORPUS_DIR).glob("*.yaml")):
        out.append({"name": p.stem, "path": str(p), "brief": yaml.safe_load(p.read_text(encoding="utf-8"))})
    return out


def _vhash(rep) -> str:
    return hashlib.sha256("|".join(v["kept"]["png_sha256"] for v in rep.visuals).encode()).hexdigest()


def _record(name: str, rep, spec: dict, extra: dict | None = None) -> dict:
    rules = [f["rule"] for f in rep.findings]
    rec = {"name": name, "deck_id": spec.get("deck_id"), "lang": spec.get("lang", "en"), "slides": rep.slides, "ok": rep.ok,
           "critical": rep.critical, "major": rep.major,
           "variety": sum(r in ("variety", "templated") for r in rules),
           "unsourced": sum(r == "unsourced_number" for r in rules), "art_direction": rep.art_direction,
           "build_seconds": rep.total_seconds, "numbers_digest": rep.numbers_digest, "visual_hash": _vhash(rep),
           "visual_candidates_min": min((len(v["candidates"]) for v in rep.visuals), default=0), "critic": rep.critic,
           "archetypes": [s.get("archetype") for s in spec.get("slides", [])], "error": rep.error,
           "findings": [f"{f['severity']} {f['rule']} s{f['slide']}: {f['message'][:100]}" for f in rep.findings
                        if f["severity"] in ("critical", "major")][:8]}
    rec.update(extra or {})
    return rec


def build_brief(brief: dict, *, seed: int, out: str | None = None, name: str = "") -> dict:
    """One corpus deck through `deck_from_brief` (offline-spec mode: approved ghost + spec, no adapter)."""
    from om.deck import engine
    res = engine.deck_from_brief(brief, approve=True, seed=seed, critic=False, out=out)
    d = res["report"]
    spec = brief["spec"]
    if d.get("mode") != "offline-spec":
        return {"name": name, "deck_id": spec.get("deck_id"), "ok": False, "critical": 1, "major": 0, "slides": 0, "variety": 0,
                "unsourced": 0, "error": d.get("error", "not built"), "lang": spec.get("lang", "en"), "archetypes": [],
                "art_direction": "", "build_seconds": 0, "numbers_digest": "", "findings": [], "visual_hash": ""}

    class _R:                                                        # report dict -> attribute view
        def __init__(self, d):
            self.__dict__.update(d)
    return _record(name, _R(d), spec, {"pptx": res["pptx"], "mode": d["mode"], "ghost_lint_major": sum(
        l["severity"] == "major" for l in brief["ghost"].get("lint", []))})


def run_corpus(*, out_dir: str | None = None, limit: int | None = None) -> list[dict]:
    """Build every corpus deck with a fixed seed (1000 + index). Style log goes to a temp dir (learning log untouched)."""
    corpus = load_corpus()[:limit]
    recs = []
    with _isolated_data():
        for i, item in enumerate(corpus, 1):
            out = str(Path(out_dir) / f"{item['name']}.pptx") if out_dir else None
            recs.append(build_brief(item["brief"], seed=1000 + i, out=out, name=item["name"]))
    return recs


class _isolated_data:
    def __enter__(self):
        self._old = os.environ.get("ACRETIA_DATA")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["ACRETIA_DATA"] = self._tmp.name
        return self

    def __exit__(self, *a):
        if self._old is None:
            os.environ.pop("ACRETIA_DATA", None)
        else:
            os.environ["ACRETIA_DATA"] = self._old
        self._tmp.cleanup()


# ------------------------------------------------------------------ reliability
def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return round(xs[k], 3)


def run_reliability(n: int = 100, seed: int = 7) -> dict:
    from evals.decks.reliability import generate
    from om.deck import engine
    specs = generate.specs(n, seed)
    recs = []
    with _isolated_data():
        for i, sp in enumerate(specs):
            rep = engine.build(sp, seed=seed + i, critic=False)
            recs.append(_record(sp["deck_id"], rep, sp))
        det = determinism(specs, 5, seed)
    ok = sum(r["ok"] and r["critical"] == 0 for r in recs)
    t10 = [r["build_seconds"] for r in recs if r["slides"] == 10]
    return {"n": n, "seed": seed, "success": ok, "success_rate": round(ok / n, 4) if n else 0.0,
            "arabic": sum(r["lang"] == "ar" for r in recs), "ten_slide": len(t10),
            "ten_slide_share": round(len(t10) / n, 3) if n else 0.0,
            "p50_10_slide_s": _pct(t10, 0.5), "p90_10_slide_s": _pct(t10, 0.9), "unsourced": sum(r["unsourced"] for r in recs),
            "critical_total": sum(r["critical"] for r in recs), "major_total": sum(r["major"] for r in recs),
            "variety_total": sum(r["variety"] for r in recs), "determinism": det,
            "failures": [{"deck_id": r["deck_id"], "findings": r["findings"], "error": r["error"]} for r in recs if not r["ok"]][:20],
            "decks": [{k: r[k] for k in ("deck_id", "lang", "slides", "critical", "major", "build_seconds")} for r in recs]}


def determinism(specs: list[dict], k: int = 5, seed: int = 7) -> dict:
    """Two seeds per spec: identical numbers_digest, different kept-visual hashes."""
    from om.deck import engine
    picked = [s for s in specs if any(sl.get("visual") for sl in s["slides"])][:k]
    rows = []
    for s in picked:
        a = engine.build(s, seed=seed * 101 + 1, critic=False)
        b = engine.build(s, seed=seed * 101 + 2, critic=False)
        rows.append({"deck_id": s["deck_id"], "same_numbers": a.numbers_digest == b.numbers_digest and bool(a.numbers_digest),
                     "different_visuals": _vhash(a) != _vhash(b)})
    return {"checked": len(rows), "same_numbers": sum(r["same_numbers"] for r in rows),
            "different_visuals": sum(r["different_visuals"] for r in rows), "rows": rows,
            "ok": bool(rows) and all(r["same_numbers"] and r["different_visuals"] for r in rows)}


# ------------------------------------------------------------------ summary and files
def summarize(corpus: list[dict] | None, rel: dict | None) -> dict:
    out: dict = {"generated_by": "scripts/eval_s3.py", "offline": True, "critic": "not run live", "live_models": "not run live (D-021)"}
    if corpus is not None:
        archs = {a for r in corpus for a in r["archetypes"]}
        arts = {r["art_direction"] for r in corpus if r["art_direction"]}
        out["corpus"] = {"n": len(corpus), "arabic": sum(r["lang"] == "ar" for r in corpus),
                         "ten_slide": sum(r["slides"] == 10 for r in corpus),
                         "zero_critical": sum(r["critical"] == 0 and r["ok"] for r in corpus),
                         "zero_critical_share": round(sum(r["critical"] == 0 and r["ok"] for r in corpus) / max(1, len(corpus)), 4),
                         "major_total": sum(r["major"] for r in corpus), "max_major": max((r["major"] for r in corpus), default=0),
                         "variety_total": sum(r["variety"] for r in corpus), "unsourced_total": sum(r["unsourced"] for r in corpus),
                         "distinct_archetypes": len(archs), "distinct_art_directions": len(arts), "art_directions": sorted(arts),
                         "decks": [{k: r.get(k) for k in ("name", "lang", "slides", "critical", "major", "variety", "unsourced", "art_direction",
                                                          "build_seconds", "numbers_digest", "visual_candidates_min", "findings")} for r in corpus]}
    if rel is not None:
        out["reliability"] = rel
    return out


def write_results(summary: dict, directory: Path | None = None) -> tuple[Path, Path]:
    d = directory or RESULTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    jp, mp = d / "summary.json", d / "summary.md"
    jp.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    L = ["# Deck eval results (offline)", "", "Offline run: replay/offline spec path, critic not run live, no live model rows (D-021). "
         "All figures in the corpus are synthetic.", ""]
    c, r = summary.get("corpus"), summary.get("reliability")
    if c:
        L += ["## Corpus", "", f"- Decks: {c['n']} ({c['arabic']} Arabic, {c['ten_slide']} with exactly 10 slides)",
              f"- 0 critical: {c['zero_critical']}/{c['n']}; major total {c['major_total']} (max {c['max_major']} per deck)",
              f"- Variety findings: {c['variety_total']}; unsourced numbers: {c['unsourced_total']}",
              f"- Distinct archetypes: {c['distinct_archetypes']}; art directions: {c['distinct_art_directions']} ({', '.join(c['art_directions'])})",
              "", "| Deck | Lang | Slides | Critical | Major | Variety | Unsourced | Art direction | Build s |", "|---|---|---|---|---|---|---|---|---|"]
        for d_ in c["decks"]:
            L.append(f"| {d_['name']} | {d_['lang']} | {d_['slides']} | {d_['critical']} | {d_['major']} | {d_['variety']} | {d_['unsourced']} | "
                     f"{d_['art_direction']} | {d_['build_seconds']} |")
        L.append("")
    if r:
        dt = r["determinism"]
        L += ["## Reliability", "", f"- Specs: {r['n']} (seed {r['seed']}); {r['arabic']} Arabic; {r['ten_slide']} with exactly 10 slides",
              f"- Success (0 critical): {r['success']}/{r['n']} = {r['success_rate']:.1%}",
              f"- 10-slide build time: p50 {r['p50_10_slide_s']} s, p90 {r['p90_10_slide_s']} s",
              f"- Unsourced numbers: {r['unsourced']}; variety findings: {r['variety_total']}; major total {r['major_total']}",
              f"- Determinism: {dt['same_numbers']}/{dt['checked']} same numbers_digest, {dt['different_visuals']}/{dt['checked']} different visuals", ""]
        if r["failures"]:
            L += ["### Failures", ""] + [f"- {f['deck_id']}: {'; '.join(f['findings'][:2]) or f['error']}" for f in r["failures"]] + [""]
    mp.write_text("\n".join(L) + "\n", encoding="utf-8")
    return jp, mp


# ------------------------------------------------------------------ scorecard
def _row(*cells) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(cells)
    return buf.getvalue()


def scorecard_rows(corpus: list[dict] | None, rel: dict | None) -> dict[str, list[str]]:
    """New S3 rows keyed by group (corpus, offline, reliability, bench)."""
    out: dict[str, list[str]] = {}
    if corpus is not None:
        out["corpus"] = [_row("S3", f"deck_{r['name']}__{m}", 1, "",
                              f"model={m}; not run live (D-021); offline: critical={r['critical']} major={r['major']} variety={r['variety']} build_s={r['build_seconds']}")
                         for r in corpus for m in MODELS]
        share = sum(r["critical"] == 0 and r["ok"] for r in corpus) / max(1, len(corpus))
        out["offline"] = [_row("S3.10", "deck_corpus_offline", len(corpus), f"{share:.3f}",
                               f"offline; share of decks with 0 critical; major={sum(r['major'] for r in corpus)} "
                               f"variety={sum(r['variety'] for r in corpus)} unsourced={sum(r['unsourced'] for r in corpus)}; critic skipped offline")]
    if rel is not None:
        out["reliability"] = [_row("S3.10", "deck_reliability_offline", rel["n"], f"{rel['success_rate']:.3f}",
                                   f"offline; 0-critical success rate; 10-slide build p50={rel['p50_10_slide_s']}s p90={rel['p90_10_slide_s']}s; "
                                   f"unsourced={rel['unsourced']}")]
    out["bench"] = [_row("S3.10", b, "", "", BENCH_NOTE) for b in BENCHES]
    return out


def write_scorecard(corpus: list[dict] | None, rel: dict | None, path: Path | None = None) -> Path:
    """Replace this stage's S3 rows; every other stage's rows are kept byte for byte. A part that was not run keeps its old rows."""
    p = Path(path or SCORECARD)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else ["stage,eval,n,score,notes"]
    if not lines:
        lines = ["stage,eval,n,score,notes"]
    new = scorecard_rows(corpus, rel)
    old_s3 = [l for l in lines if l.startswith(("S3,", "S3.10,"))]
    keep = [l for l in lines if not l.startswith(("S3,", "S3.10,"))]

    def group_of(l: str) -> str:
        e = l.split(",", 2)[1]
        return ("offline" if e == "deck_corpus_offline" else "reliability" if e == "deck_reliability_offline"
                else "bench" if e.startswith("bench_") else "corpus")
    merged: dict[str, list[str]] = {}
    for l in old_s3:
        merged.setdefault(group_of(l), []).append(l)
    merged.update(new)
    s3 = [l for g in ("corpus", "offline", "reliability", "bench") for l in merged.get(g, [])]
    p.write_text("\n".join(keep + s3) + "\n", encoding="utf-8")
    return p


# ------------------------------------------------------------------ samples
def _have(cmd: str) -> bool:
    return subprocess.run(["which", cmd], capture_output=True).returncode == 0


def render_samples(out_dir: Path, *, names=("04-sell-side-pitchbook", "05-ic-dental-platform", "14-ar-saudi-ipo-readiness"), dpi: int = 80) -> dict:
    """pptx + per-slide PNGs for three corpus decks, plus one PNG per art direction. Needs LibreOffice and pdftoppm."""
    from om.deck.theme import Theme
    from om.deck.visuals import generate, library, score
    out_dir.mkdir(parents=True, exist_ok=True)
    corpus = {c["name"]: c for c in load_corpus()}
    info: dict = {"decks": [], "art": []}
    can_render = _have("soffice") and _have("pdftoppm")
    with _isolated_data():
        for name in names:
            item = corpus[name]
            idx = list(corpus).index(name) + 1
            pptx = out_dir / f"{name}.pptx"
            rec = build_brief(item["brief"], seed=1000 + idx, out=str(pptx), name=name)
            entry = {"name": name, "pptx": pptx.name, "slides": rec["slides"], "png": []}
            if can_render:
                with tempfile.TemporaryDirectory() as td:
                    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", td, str(pptx)], capture_output=True, timeout=300)
                    pdf = Path(td) / f"{name}.pdf"
                    if pdf.exists():
                        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(out_dir / name)], capture_output=True, timeout=300)
                entry["png"] = sorted(p.name for p in out_dir.glob(f"{name}-*.png"))
            info["decks"].append(entry)
        theme = Theme.house()
        for sid, st in library.STYLES.items():
            cands = generate.candidates(f"{st.description}", sid, 3, kind=st.kinds[0], theme=theme, adapter=None,
                                        image_status={"available": False, "reason": "offline"}, seed=7, job_id="samples")
            best, _ = score.choose(cands, theme, adapter=None, concept=st.description, job_id="samples")
            (out_dir / f"art-{sid}.png").write_bytes(best.png)
            info["art"].append({"style": sid, "file": f"art-{sid}.png", "source": best.source, "kind": st.kinds[0]})
    info["rendered"] = can_render
    return info
