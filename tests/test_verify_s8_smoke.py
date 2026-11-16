"""Smoke test: the S8 gate's assertion registry covers every G-id in docs/s8/gate-spec.md."""
import importlib.util
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_gate():
    spec = importlib.util.spec_from_file_location("verify_s8", os.path.join(ROOT, "scripts", "verify_s8.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _spec_ids():
    """{section id: [numbered item ids]} from the gate spec."""
    out, cur = {}, None
    for line in open(os.path.join(ROOT, "docs", "s8", "gate-spec.md"), encoding="utf-8"):
        m = re.match(r"\*\*G(\d+)\b", line)
        if m:
            cur = f"G{m.group(1)}"
            out[cur] = []
            continue
        if line.startswith("**") or line.startswith("## "):
            cur = None if not m else cur
        m = re.match(r"^(\d+)\. ", line)
        if cur and m:
            out[cur].append(f"{cur}.{m.group(1)}")
    return out


class GateRegistry(unittest.TestCase):
    def test_every_spec_id_has_an_assertion(self):
        gate = _load_gate()
        spec = _spec_ids()
        self.assertEqual(sorted(spec, key=lambda g: int(g[1:])), [f"G{i}" for i in range(13)])
        missing = []
        for sec, items in spec.items():
            if items:
                missing += [i for i in items if i not in gate.GATES]
            elif not any(g.startswith(sec + ".") for g in gate.GATES):
                missing.append(sec)
        self.assertEqual(missing, [])
        for g, d in gate.GATES.items():
            self.assertTrue(callable(d["fn"]), g)


if __name__ == "__main__":
    unittest.main()
