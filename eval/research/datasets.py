"""Dataset loaders for the S6.3 research evals.

Datasets are DOWNLOADED at runtime by an explicit ``fetch`` command into ``data/evals/<name>/`` (``data/`` is
gitignored) and never vendored. ``manifest.json`` (committed) records url, sha256, size and fetched_at of every file.
Loaders never touch the network: a dataset that was not fetched raises ``DatasetUnavailable``.

    python3 -m eval.research.datasets fetch [vals_v1 vals_v2 financebench btb ...]
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA_ROOT = REPO / "data" / "evals"
MANIFEST = HERE / "manifest.json"
FIXTURES = HERE / "fixtures"

# Pinned sources (commit/revision hashes verified with git ls-remote / the HF API when this file was written).
SOURCES = {
    "vals_v1": {"licence": "MIT (code repo vals-ai/finance-agent; check vals.ai terms for the question set)",
                "files": [("public.csv", "https://raw.githubusercontent.com/vals-ai/finance-agent/"
                                         "72239d10448c9dc9654f30466372fc932f8b509f/data/public.csv")]},
    "vals_v2": {"licence": "MIT (code repo vals-ai/finance-agent-v2); public set = 27 of 926 questions",
                "files": [("public.csv", "https://raw.githubusercontent.com/vals-ai/finance-agent-v2/"
                                         "3ef5e4a279e7daeef5a4149da55ccccc879a88d0/data/public.csv")]},
    "financebench": {"licence": "CC-BY-NC-4.0 (HuggingFace PatronusAI/financebench): local scoring only",
                     "files": [("financebench_merged.jsonl",
                                "https://huggingface.co/datasets/PatronusAI/financebench/resolve/"
                                "e04404e3a97f69f79c14d42f24981a1c9c3bcd18/financebench_merged.jsonl")]},
    "btb": {"licence": "CC-BY-4.0 (HF handshake-ai-research/bankertoolbench, tag noai); code Apache-2.0",
            "files": [("tasks.jsonl", "https://huggingface.co/datasets/handshake-ai-research/bankertoolbench/"
                                      "resolve/6407cdc22a218d59a1e41d8598679d02d821d6ff/tasks.jsonl")]},
}
SUITES = {"vals": ["vals_v1", "vals_v2"], "financebench": ["financebench"], "btb": ["btb"]}


class DatasetUnavailable(RuntimeError):
    """The dataset is not present locally (not fetched) or is not public."""


@dataclass
class EvalItem:
    id: str
    question: str
    gold_answer: str
    gold_evidence: list = field(default_factory=list)   # [{"doc": str, "page": int|None, "quote": str}]
    tickers: list = field(default_factory=list)
    category: str = ""
    dataset: str = ""
    meta: dict = field(default_factory=dict)


_TICKER = re.compile(r"\b(?:NASDAQ|NYSE|NYSEARCA|AMEX)\s*:\s*([A-Z][A-Z.\-]{0,9})")


def tickers_in(text: str) -> list:
    out = []
    for t in _TICKER.findall(text or ""):
        if t not in out:
            out.append(t)
    return out


def _criteria(rubric_json: str) -> list:
    try:
        rub = json.loads(rubric_json or "[]")
    except ValueError:
        return []
    return [str(r.get("criteria", "")).strip() for r in rub if isinstance(r, dict) and r.get("criteria")]


def parse_vals_csv(text: str, dataset: str = "vals_v1") -> list:
    items = []
    for i, row in enumerate(csv.DictReader(io.StringIO(text)), 1):
        q = (row.get("Question") or "").strip()
        if not q:
            continue
        crit = _criteria(row.get("Rubric") or "")
        gold = (row.get("Answer") or "").strip() or "; ".join(crit)
        items.append(EvalItem(f"{dataset}-{i:03d}", q, gold, [], tickers_in(q), (row.get("Question Type") or "").strip(),
                              dataset, {"expert_minutes": (row.get("Expert time (mins)") or "").strip(),
                                        "rubric_criteria": crit}))
    return items


def parse_financebench_jsonl(text: str) -> list:
    items = []
    for line in text.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        ev = []
        for e in r.get("evidence") or []:
            page = e.get("evidence_page_num")
            ev.append({"doc": e.get("doc_name") or r.get("doc_name") or "", "quote": e.get("evidence_text") or "",
                       "page": int(page) + 1 if isinstance(page, int) else None})   # FinanceBench pages are 0-based
        items.append(EvalItem(str(r.get("financebench_id")), r.get("question", ""), str(r.get("answer", "")), ev, [],
                              r.get("question_type", ""), "financebench",
                              {"company": r.get("company", ""), "doc_name": r.get("doc_name", ""),
                               "doc_period": r.get("doc_period", ""), "reasoning": r.get("question_reasoning", "")}))
    return items


def parse_btb_jsonl(text: str) -> list:
    items = []
    for line in text.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        try:
            rubric = json.loads(r.get("aggregated_rubric_json") or "[]")
        except ValueError:
            rubric = []
        cat = " / ".join(x for x in (r.get("workflow_cat"), r.get("workflow_subcat")) if x)
        # prompt_context / formatting_context are ignored: BTB says to omit them in realistic evaluations.
        items.append(EvalItem(str(r.get("task_id")), r.get("final_prompt", ""), "", [], tickers_in(r.get("final_prompt", "")),
                              cat, "btb", {"product": r.get("product", ""), "rubric_criteria": len(rubric),
                                           "needs_deliverable_grader": True}))
    return items


def _read(name: str, root: Path | None, fname: str) -> str:
    base = Path(root) if root else DATA_ROOT
    p = base / name / fname
    if not p.is_file():
        raise DatasetUnavailable(f"{name}: {p} not found; run `python3 -m eval.research.datasets fetch {name}` "
                                 f"(network, explicit) first")
    return p.read_text(encoding="utf-8")


def load_vals_v1(root=None):
    return parse_vals_csv(_read("vals_v1", root, "public.csv"), "vals_v1")


def load_vals_v2(root=None):
    return parse_vals_csv(_read("vals_v2", root, "public.csv"), "vals_v2")


def load_financebench(root=None):
    return parse_financebench_jsonl(_read("financebench", root, "financebench_merged.jsonl"))


def load_btb(root=None):
    return parse_btb_jsonl(_read("btb", root, "tasks.jsonl"))


LOADERS = {"vals_v1": load_vals_v1, "vals_v2": load_vals_v2, "financebench": load_financebench, "btb": load_btb}


def load(name: str, root=None) -> list:
    if name not in LOADERS:
        raise KeyError(f"unknown dataset {name!r}; known: {sorted(LOADERS)}")
    return LOADERS[name](root)


def fetch(name: str, root=None, *, opener=None, manifest_path=None, now=None) -> list:
    """Download one dataset (the ONLY network entry point), record sha256 in the manifest. Returns manifest entries."""
    if name not in SOURCES:
        raise KeyError(f"unknown dataset {name!r}; known: {sorted(SOURCES)}")
    opener = opener or (lambda url: urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "acretia-evals"}),
                                                          timeout=120).read())
    base = (Path(root) if root else DATA_ROOT) / name
    base.mkdir(parents=True, exist_ok=True)
    mp = Path(manifest_path) if manifest_path else MANIFEST
    man = json.loads(mp.read_text()) if mp.is_file() else {}
    entries = []
    for fname, url in SOURCES[name]["files"]:
        data = opener(url)
        (base / fname).write_bytes(data)
        entries.append({"file": fname, "url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                        "fetched_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")})
    man[name] = {"licence": SOURCES[name]["licence"], "files": entries}
    mp.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
    return entries


def verify_checksums(name: str, root=None, manifest_path=None) -> bool:
    mp = Path(manifest_path) if manifest_path else MANIFEST
    man = json.loads(mp.read_text()) if mp.is_file() else {}
    base = (Path(root) if root else DATA_ROOT) / name
    return bool(man.get(name)) and all(
        (base / f["file"]).is_file() and hashlib.sha256((base / f["file"]).read_bytes()).hexdigest() == f["sha256"]
        for f in man[name]["files"])


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] != "fetch":
        print("usage: python3 -m eval.research.datasets fetch [name ...]   names: " + ", ".join(sorted(SOURCES)))
        return 2
    for n in (a[1:] or sorted(SOURCES)):
        try:
            for e in fetch(n):
                print(f"{n}: {e['file']} {e['bytes']} bytes sha256={e['sha256'][:12]}")
        except Exception as ex:   # one dataset failing (offline / moved) must not hide the others
            print(f"{n}: FAILED {type(ex).__name__}: {ex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
