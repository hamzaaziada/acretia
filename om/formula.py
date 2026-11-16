"""A small Excel formula evaluator, so models can be calculated (and verified) without Excel.

Covers the formula language our models and most banker models use: arithmetic (+ - * / ^ %, unary minus),
comparisons, & concatenation, cross-sheet references and ranges, defined names, and the functions
SUM AVERAGE MIN MAX ABS ROUND IF IFERROR ISERROR AND OR NOT CHOOSE NPV COUNTIF SUMPRODUCT LEFT LEN.

Circular references are solved the way Excel's iterative calculation does it: repeated recalculation until no
cell moves by more than the tolerance (or the iteration limit is hit, which is reported). Cells are evaluated
in dependency order, so models without circularity settle in one pass.
"""
from __future__ import annotations

import datetime as _dt
import math
import re

from .xlsx import col_index, split_ref


VALID_BUT_UNSUPPORTED = re.compile(r"(?<![\w{])\$?[A-Z]{1,3}:\$?[A-Z]{1,3}(?![\w(])|(?<![\w.])\$?\d+:\$?\d+(?![\w.])|\w\[|\{\s*-?[\d.]+\s*[,;]")


class XLError(Exception):
    pass


class Err:
    def __init__(self, code: str):
        self.code = code

    def __repr__(self):
        return self.code

    def __eq__(self, other):
        return isinstance(other, Err) and other.code == self.code

    def __hash__(self):
        return hash(self.code)


DIV0, VALUE, REF, NAME, NUM, NA = Err("#DIV/0!"), Err("#VALUE!"), Err("#REF!"), Err("#NAME?"), Err("#NUM!"), Err("#N/A")

TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<err>\#REF!|\#DIV/0!|\#N/A|\#VALUE!|\#NAME\?|\#NUM!|\#NULL!)
  | (?P<ref>(?:(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?(?![\w(]))
  | (?P<num>\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)
  | (?P<bool>TRUE|FALSE)(?![\w(])
  | (?P<func>[A-Za-z_][\w.]*)(?=\()
  | (?P<name>[A-Za-z_][\w.]*)
  | (?P<op><>|<=|>=|[-+*/^&=<>%(),:])
""", re.X)


def tokenize(s: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(s):
        m = TOKEN.match(s, i)
        if not m:
            raise XLError(f"can't parse formula at {s[i:i + 20]!r}")
        i = m.end()
        if m.lastgroup != "ws":
            out.append((m.lastgroup, m.group(0)))
    return out


# --------------------------------------------------------------------------- parser -> AST tuples
class _Parser:
    def __init__(self, tokens, sheet):
        self.t, self.i, self.sheet = tokens, 0, sheet

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, val=None):
        tok = self.peek()
        if val is not None and tok[1] != val:
            raise XLError(f"expected {val!r}, got {tok[1]!r}")
        self.i += 1
        return tok

    def parse(self):
        node = self.compare()
        if self.i != len(self.t):
            raise XLError(f"unexpected {self.peek()[1]!r}")
        return node

    def compare(self):
        node = self.concat()
        while self.peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.take()[1]
            node = ("bin", op, node, self.concat())
        return node

    def concat(self):
        node = self.add()
        while self.peek()[1] == "&":
            self.take()
            node = ("bin", "&", node, self.add())
        return node

    def add(self):
        node = self.mul()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.mul())
        return node

    def mul(self):
        node = self.power()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            node = ("bin", op, node, self.power())
        return node

    def power(self):
        node = self.unary()
        while self.peek()[1] == "^":
            self.take()
            node = ("bin", "^", node, self.unary())
        return node

    def unary(self):
        if self.peek()[1] in ("-", "+"):
            op = self.take()[1]
            inner = self.unary()
            return ("neg", inner) if op == "-" else inner
        node = self.primary()
        while self.peek()[1] == "%":
            self.take()
            node = ("bin", "/", node, ("num", 100.0))
        return node

    def primary(self):
        kind, val = self.take()
        if kind == "num":
            return ("num", float(val))
        if kind == "str":
            return ("str", val[1:-1].replace('""', '"'))
        if kind == "bool":
            return ("bool", val == "TRUE")
        if kind == "err":
            return ("err", val)
        if kind == "ref":
            return self.reference(val)
        if kind == "name":
            return ("name", val)
        if kind == "func":
            self.take("(")
            args = []
            if self.peek()[1] != ")":
                args.append(("blank",) if self.peek()[1] == "," else self.compare())      # f(a,,c): omitted argument
                while self.peek()[1] == ",":
                    self.take()
                    args.append(("blank",) if self.peek()[1] in (",", ")") else self.compare())
            self.take(")")
            return ("fn", val.upper(), args)
        if val == "(":
            node = self.compare()
            self.take(")")
            return node
        raise XLError(f"unexpected token {val!r}")

    def reference(self, text):
        sheet = self.sheet
        if "!" in text:
            sh, text = text.rsplit("!", 1)
            sheet = sh[1:-1].replace("''", "'") if sh.startswith("'") else sh
        if ":" in text:
            a, b = text.split(":")
            (r1, c1), (r2, c2) = split_ref(a), split_ref(b)
            return ("range", sheet, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))
        r, c = split_ref(text)
        return ("cell", sheet, r, c)


def parse(formula: str, sheet: str):
    return _Parser(tokenize(formula.lstrip("=")), sheet).parse()


def deps(node, names: dict, out: set) -> set:
    k = node[0]
    if k == "cell":
        out.add((node[1], node[2], node[3]))
    elif k == "range":
        _, sh, r1, c1, r2, c2 = node
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                out.add((sh, r, c))
    elif k == "name" and node[1] in names:
        deps(names[node[1]], names, out)
    elif k == "bin":
        deps(node[2], names, out), deps(node[3], names, out)
    elif k == "neg":
        deps(node[1], names, out)
    elif k == "fn":
        for a in node[2]:
            deps(a, names, out)
    return out


# --------------------------------------------------------------------------- evaluation
def _num(v):
    if isinstance(v, Err):
        raise _Raise(v)
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        raise _Raise(VALUE)


class _Raise(Exception):
    def __init__(self, err):
        self.err = err


def _flat(v):
    if isinstance(v, list):
        for x in v:
            yield from _flat(x)
    else:
        yield v


def _truthy(v):
    if isinstance(v, Err):
        raise _Raise(v)
    if isinstance(v, str):
        if v.upper() in ("TRUE", "FALSE"):
            return v.upper() == "TRUE"
        raise _Raise(VALUE)
    return bool(_num(v))


class Engine:
    def __init__(self, cells: dict, names: dict | None = None):
        """cells: {(sheet, row, col): value or "=formula"}; names: {name: "Sheet!$A$1"}."""
        self.raw = cells
        self.values: dict = {}
        self.ast: dict = {}
        self.names = {}
        self.unsupported: set = set()
        self.invalid: dict = {}
        for n, target in (names or {}).items():
            if n.startswith("_xlnm") or not target:
                continue
            try:
                self.names[n] = parse("=" + target, "")
            except XLError:
                continue
        self.parse_errors: dict = {}
        for k, v in cells.items():
            if isinstance(v, str) and v.startswith("="):
                try:
                    self.ast[k] = parse(v, k[0])
                except XLError as e:
                    self.parse_errors[k] = str(e)
                    if VALID_BUT_UNSUPPORTED.search(v):
                        self.unsupported.add("whole-column/row ranges, table references or array constants")
                    else:
                        self.invalid[k] = str(e)          # not valid Excel: a label typed as a formula, a template placeholder, etc.
            else:
                self.values[k] = v
        self.iterations = 0
        self.converged = True

    # ------------------------------------------------------------------ public
    def calculate(self, iterate: bool = True, max_iter: int = 1000, tol: float = 1e-13) -> dict:
        order = self._order()
        for k in self.parse_errors:
            self.values[k] = NAME
        for k in order:
            self.values.setdefault(k, 0.0)
        for it in range(1, (max_iter if iterate else 1) + 1):
            delta = 0.0
            for k in order:
                new = self._eval_cell(k)
                old = self.values.get(k)
                if isinstance(new, float) and isinstance(old, float):
                    delta = max(delta, abs(new - old) / max(1.0, abs(new)))
                elif new != old:
                    delta = max(delta, 1.0)
                self.values[k] = new
            self.iterations = it
            if delta <= tol:
                self.converged = True
                break
        else:
            self.converged = not iterate or delta <= tol
        return self.values

    # ------------------------------------------------------------------ internals
    def _order(self) -> list:
        graph = {k: [d for d in deps(a, self.names, set()) if d in self.ast] for k, a in self.ast.items()}
        seen, order = {}, []
        for start in graph:
            if start in seen:
                continue
            stack = [(start, iter(graph[start]))]
            seen[start] = 1
            while stack:
                node, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    stack.pop()
                    seen[node] = 2
                    order.append(node)
                elif nxt not in seen:
                    seen[nxt] = 1
                    stack.append((nxt, iter(graph[nxt])))
        return order

    def _eval_cell(self, k):
        try:
            v = self._ev(self.ast[k])
            if isinstance(v, list):
                v = v[0] if v else 0.0
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return NUM
            return v
        except _Raise as e:
            return e.err
        except ZeroDivisionError:
            return DIV0
        except (OverflowError, ValueError):
            return NUM

    def _get(self, sheet, r, c):
        v = self.values.get((sheet, r, c))
        return v

    def _ev(self, n):
        k = n[0]
        if k == "num":
            return n[1]
        if k == "str":
            return n[1]
        if k == "bool":
            return n[1]
        if k == "err":
            raise _Raise(Err(n[1]))
        if k == "cell":
            return self._get(n[1], n[2], n[3])
        if k == "blank":
            return None
        if k == "range":
            _, sh, r1, c1, r2, c2 = n
            return [self._get(sh, r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
        if k == "name":
            if n[1] not in self.names:
                raise _Raise(NAME)
            return self._ev(self.names[n[1]])
        if k == "neg":
            v = self._ev(n[1])
            if isinstance(v, list):
                return [-_num(x) if not isinstance(x, Err) else x for x in v]
            return -_num(v)
        if k == "bin":
            return self._bin(n[1], self._ev(n[2]), self._ev(n[3]))
        if k == "fn":
            return self._fn(n[1], n[2])
        raise XLError(f"bad node {k}")

    def _bin(self, op, a, b):
        if isinstance(a, list):
            a = a[0] if a else None
        if isinstance(b, list):
            b = b[0] if b else None
        if op == "&":
            for x in (a, b):
                if isinstance(x, Err):
                    raise _Raise(x)
            return f"{_text(a)}{_text(b)}"
        if op in ("=", "<>", "<", ">", "<=", ">="):
            for x in (a, b):
                if isinstance(x, Err):
                    raise _Raise(x)
            if isinstance(a, str) or isinstance(b, str):
                x, y = _text(a).upper(), _text(b).upper()
                if not (isinstance(a, str) and isinstance(b, str)) and op not in ("=", "<>"):
                    x, y = (1, 0) if isinstance(a, str) else (0, 1)        # text sorts after numbers
            else:
                x, y = _num(a), _num(b)
            return {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
        x, y = _num(a), _num(b)
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            if y == 0:
                raise _Raise(DIV0)
            return x / y
        if op == "^":
            if x < 0 and y != int(y):
                raise _Raise(NUM)
            return x ** y
        raise XLError(op)

    def _fn(self, f, args):
        ev = self._ev
        if f == "IF":
            cond = _truthy(_scalar(ev(args[0])))
            if cond:
                return ev(args[1]) if len(args) > 1 else True
            return ev(args[2]) if len(args) > 2 else False
        if f == "IFERROR":
            v = self._safe(args[0])
            return ev(args[1]) if isinstance(_scalar(v), Err) else v
        if f == "ISERR":
            v = self._safe(args[0])
            if isinstance(v, list):
                return [isinstance(x, Err) and x != NA for x in v]
            return isinstance(v, Err) and v != NA
        if f == "ISERROR":
            v = self._safe(args[0])
            if isinstance(v, list):
                return [isinstance(x, Err) for x in v]
            return isinstance(v, Err)
        if f == "CHOOSE":
            i = int(_num(_scalar(ev(args[0]))))
            if not 1 <= i < len(args):
                raise _Raise(VALUE)
            return ev(args[i])
        if f in ("IFS", "SWITCH"):
            return self._lazy(f, args)
        vals = [ev(a) for a in args]
        if f in ("SUM", "AVERAGE", "MIN", "MAX"):
            nums = []
            for v, a in zip(vals, args):
                for x in _flat(v):
                    if isinstance(x, Err):
                        raise _Raise(x)
                    if a[0] == "range" and (x is None or isinstance(x, (str, bool))):
                        continue
                    if x is None:
                        continue
                    nums.append(_num(x))
            if f == "SUM":
                return float(sum(nums))
            if not nums:
                if f == "AVERAGE":
                    raise _Raise(DIV0)
                return 0.0
            return {"AVERAGE": sum(nums) / len(nums), "MIN": min(nums), "MAX": max(nums)}[f]
        if f == "ABS":
            return abs(_num(_scalar(vals[0])))
        if f == "ROUND":
            n = int(_num(_scalar(vals[1]))) if len(vals) > 1 else 0
            x = _num(_scalar(vals[0]))
            q = 10 ** n
            return math.floor(abs(x) * q + 0.5) / q * (1 if x >= 0 else -1)
        if f in ("AND", "OR"):
            bs = [_truthy(x) for v in vals for x in _flat(v) if x is not None]
            return all(bs) if f == "AND" else any(bs)
        if f == "NOT":
            return not _truthy(_scalar(vals[0]))
        if f == "NPV":
            r = _num(_scalar(vals[0]))
            flows = [x for v in vals[1:] for x in _flat(v)]
            total, t = 0.0, 0
            for x in flows:
                if x is None or isinstance(x, str):
                    continue
                t += 1
                total += _num(x) / (1 + r) ** t
            return total
        if f == "COUNTIF":
            crit = _scalar(vals[1])
            items = list(_flat(vals[0]))
            if isinstance(crit, str):
                m = re.match(r"^(<>|<=|>=|=|<|>)?(.*)$", crit)
                op, target = m.group(1) or "=", m.group(2)
                try:
                    tnum = float(target)
                except ValueError:
                    tnum = None
            else:
                op, target, tnum = "=", crit, _num(crit)
            n = 0
            for x in items:
                if isinstance(x, Err) or x is None:
                    continue
                if tnum is not None and isinstance(x, (int, float)) and not isinstance(x, bool):
                    a, b = float(x), tnum
                elif isinstance(x, str):
                    a, b = x.upper(), str(target).upper()
                else:
                    continue
                if {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]:
                    n += 1
            return float(n)
        if f == "SUMPRODUCT":
            arrays = [list(_flat(v)) for v in vals]
            total = 0.0
            for row in zip(*arrays):
                p = 1.0
                for x in row:
                    if isinstance(x, Err):
                        raise _Raise(x)
                    p *= _num(x) if not isinstance(x, str) else 0.0
                total += p
            return total
        if f == "LEFT":
            s = _text(_scalar(vals[0]))
            n = int(_num(_scalar(vals[1]))) if len(vals) > 1 else 1
            return s[:n]
        if f == "LEN":
            return float(len(_text(_scalar(vals[0]))))
        if f in ("MEDIAN", "PERCENTILE", "PERCENTILE.INC", "QUARTILE", "QUARTILE.INC", "COUNT", "COUNTA", "STDEV", "STDEV.S"):
            items = [x for x in _flat(vals[0] if f.startswith(("PERCENTILE", "QUARTILE")) else vals)]
            nums = [float(x) for x in items if isinstance(x, (int, float)) and not isinstance(x, bool)]
            if f == "COUNT":
                return float(len(nums))
            if f == "COUNTA":
                return float(sum(1 for x in items if x not in (None, "")))
            for x in items:
                if isinstance(x, Err):
                    raise _Raise(x)
            if not nums:
                raise _Raise(NUM)
            nums.sort()
            if f == "MEDIAN":
                k = len(nums)
                return nums[k // 2] if k % 2 else (nums[k // 2 - 1] + nums[k // 2]) / 2
            if f.startswith("STDEV"):
                if len(nums) < 2:
                    raise _Raise(DIV0)
                mu = sum(nums) / len(nums)
                return math.sqrt(sum((x - mu) ** 2 for x in nums) / (len(nums) - 1))
            q = _num(_scalar(vals[1]))
            q = q / 4 if f.startswith("QUARTILE") else q
            if not 0 <= q <= 1:
                raise _Raise(NUM)
            pos = q * (len(nums) - 1)
            lo = int(math.floor(pos))
            return nums[lo] + (nums[min(lo + 1, len(nums) - 1)] - nums[lo]) * (pos - lo)
        if f in ("ISNUMBER", "ISTEXT", "ISBLANK"):
            v = _scalar(self._safe(args[0]))
            return {"ISNUMBER": isinstance(v, (int, float)) and not isinstance(v, bool), "ISTEXT": isinstance(v, str) and v != "",
                    "ISBLANK": v is None}[f]
        if f in ("COLUMNS", "ROWS"):
            node = args[0]
            if node[0] == "range":
                return float(node[5] - node[3] + 1 if f == "COLUMNS" else node[4] - node[2] + 1)
            return 1.0
        if f in ("SQRT", "LN", "EXP", "INT", "SIGN"):
            x = _num(_scalar(vals[0]))
            if f == "SQRT" and x < 0 or f == "LN" and x <= 0:
                raise _Raise(NUM)
            return {"SQRT": math.sqrt, "LN": math.log, "EXP": math.exp, "INT": math.floor, "SIGN": lambda v: (v > 0) - (v < 0)}[f](x) * 1.0
        if f in ("POWER", "MOD", "ROUNDUP", "ROUNDDOWN"):
            x, y = _num(_scalar(vals[0])), _num(_scalar(vals[1])) if len(vals) > 1 else 0.0
            if f == "POWER":
                return x ** y
            if f == "MOD":
                if y == 0:
                    raise _Raise(DIV0)
                return x - y * math.floor(x / y)
            q = 10 ** int(y)
            return (math.ceil(abs(x) * q - 1e-12) if f == "ROUNDUP" else math.floor(abs(x) * q + 1e-12)) / q * (1 if x >= 0 else -1)
        if f == "SUMIF":
            rng, crit = list(_flat(vals[0])), _scalar(vals[1])
            sums = list(_flat(vals[2])) if len(vals) > 2 else rng
            return float(sum(_num(sv) for x, sv in zip(rng, sums) if _match(x, crit) and isinstance(sv, (int, float))))
        if f in ("INDEX",):
            node = args[0]
            items = list(_flat(vals[0]))
            r = int(_num(_scalar(vals[1]))) if len(vals) > 1 else 1
            c = int(_num(_scalar(vals[2]))) if len(vals) > 2 else 1
            if node[0] == "range":
                width = node[5] - node[3] + 1
                if node[4] == node[2] and len(vals) == 2:      # single row: INDEX(row, n)
                    r, c = 1, r
                i = (r - 1) * width + (c - 1)
            else:
                i = 0
            if not 0 <= i < len(items):
                raise _Raise(REF)
            return items[i]
        if f == "MATCH":
            look, items = _scalar(vals[0]), list(_flat(vals[1]))
            mode = int(_num(_scalar(vals[2]))) if len(vals) > 2 else 1
            for i, x in enumerate(items):
                if mode == 0 and _match(x, look):
                    return float(i + 1)
            if mode == 1:
                best = None
                for i, x in enumerate(items):
                    if isinstance(x, (int, float)) and _num(x) <= _num(look):
                        best = i + 1
                if best:
                    return float(best)
            raise _Raise(NA)
        if f in ("IRR",):
            flows = [_num(x) for x in _flat(vals[0]) if isinstance(x, (int, float))]
            r = 0.1
            for _ in range(100):
                npv = sum(cf / (1 + r) ** t for t, cf in enumerate(flows))
                d = sum(-t * cf / (1 + r) ** (t + 1) for t, cf in enumerate(flows))
                if d == 0:
                    break
                nr = r - npv / d
                if abs(nr - r) < 1e-10:
                    return nr
                r = nr
            raise _Raise(NUM)
        if f == "TEXT":
            v = _scalar(vals[0])
            fmt = _text(_scalar(vals[1]))
            if not isinstance(v, (int, float)):
                return _text(v)
            dec = len(fmt.split(".")[1].rstrip('%x"')) if "." in fmt else 0
            if "%" in fmt:
                return f"{v * 100:,.{dec}f}%"
            out = f"{v:,.{dec}f}" if "," in fmt else f"{v:.{dec}f}"
            return ("$" if "$" in fmt else "") + out + ("x" if "x" in fmt else "")
        return _ext(self, f, args, vals)

    def _lazy(self, f, args):
        ev = self._ev
        if f == "IFS":
            if len(args) < 2 or len(args) % 2:
                raise _Raise(NA)
            for i in range(0, len(args), 2):
                if _truthy(_scalar(ev(args[i]))):
                    return ev(args[i + 1])
            raise _Raise(NA)
        key = _scalar(ev(args[0]))
        if isinstance(key, Err):
            raise _Raise(key)
        rest = args[1:]
        for i in range(0, len(rest) - 1, 2):
            cand = _scalar(ev(rest[i]))
            if isinstance(cand, Err):
                raise _Raise(cand)
            if _eq(key, cand):
                return ev(rest[i + 1])
        if len(rest) % 2:
            return ev(rest[-1])
        raise _Raise(NA)

    def shape(self, node):
        """(rows, cols) of a range-valued argument node, or None when it is not a plain range."""
        if node[0] == "range":
            return node[4] - node[2] + 1, node[5] - node[3] + 1
        if node[0] == "name" and node[1] in self.names:
            return self.shape(self.names[node[1]])
        return None

    def _safe(self, node):
        try:
            return self._ev(node)
        except _Raise as e:
            return e.err
        except ZeroDivisionError:
            return DIV0


def _match(x, crit) -> bool:
    if isinstance(crit, str):
        m = re.match(r"^(<>|<=|>=|=|<|>)?(.*)$", crit)
        op, target = m.group(1) or "=", m.group(2)
        try:
            t = float(target)
        except ValueError:
            t = None
        if t is not None and isinstance(x, (int, float)) and not isinstance(x, bool):
            a, b = float(x), t
        elif isinstance(x, str):
            a, b = x.upper(), target.upper()
        else:
            return False
    else:
        if not isinstance(x, (int, float)) or isinstance(x, bool):
            return False
        op, a, b = "=", float(x), float(crit)
    return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


def _scalar(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return format(v, ".15g") if v != int(v) else str(int(v))
    return str(v)


# --------------------------------------------------------------------------- workbook helpers
def from_workbook(wb) -> Engine:
    """Engine over an om.xlsx.Workbook being written."""
    cells = {(sh.name, r, c): cell.value for sh in wb.sheets for (r, c), cell in sh.cells.items()}
    names = {n: t for n, t in wb.names.items()}
    return Engine(cells, names)


def calculate_workbook(wb, iterate: bool | None = None) -> Engine:
    """Calculate a Workbook and store each formula's result as its cached value (written into the file)."""
    eng = from_workbook(wb)
    eng.calculate(iterate=wb.iterate if iterate is None else iterate)
    for sh in wb.sheets:
        for (r, c), cell in sh.cells.items():
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.cached = eng.values.get((sh.name, r, c))
    return eng


def from_book(book) -> Engine:
    """Engine over a workbook read with om.xlsx.read (formulas re-evaluated from scratch)."""
    cells = {}
    for name, grid in book.sheets.items():
        for (r, c), cell in grid.items():
            cells[(name, r, c)] = cell.formula if cell.formula else cell.value
    return Engine(cells, {k: v for k, v in book.names.items() if v})


# --------------------------------------------------------------------------- extended function library
def _isnum(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _eq(a, b) -> bool:
    """Excel '=' between two scalars (text case-insensitive, no cross-type equality; blank equals 0 or "")."""
    if a is None:
        a = "" if isinstance(b, str) else 0.0
    if b is None:
        b = "" if isinstance(a, str) else 0.0
    if isinstance(a, str) and isinstance(b, str):
        return a.upper() == b.upper()
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _isnum(a) and _isnum(b):
        return float(a) == float(b)
    return False


def _wild(pattern: str) -> "re.Pattern":
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "~" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 1
        elif ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out), re.S | re.I)


def _cmatch(x, crit) -> bool:
    """COUNTIF-style criterion test (operators, wildcards, numbers, blanks) for one cell value."""
    crit = _scalar(crit)
    if isinstance(crit, Err):
        return isinstance(x, Err) and x == crit
    if isinstance(crit, bool):
        return isinstance(x, bool) and x == crit
    if crit is None:
        crit = 0.0
    if _isnum(crit):
        return _isnum(x) and float(x) == float(crit)
    m = re.match(r"^(<>|<=|>=|=|<|>)?(.*)$", str(crit), re.S)
    op, target = m.group(1) or "=", m.group(2)
    try:
        num = float(target.strip()) if target.strip() else None
    except ValueError:
        num = None
    if op in ("=", "<>"):
        if target == "":
            eq = x is None or x == ""
        elif num is not None:
            eq = _isnum(x) and float(x) == num
        else:
            eq = isinstance(x, str) and bool(_wild(target).fullmatch(x))
        return eq if op == "=" else not eq
    if num is not None:
        if not _isnum(x):
            return False
        a, b = float(x), num
    else:
        if not isinstance(x, str):
            return False
        a, b = x.upper(), target.upper()
    return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


def _nums(items) -> list:
    return [float(x) for x in items if _isnum(x)]


def _ifs_rows(vals, start: int, n: int) -> list:
    """Indices matching every (range, criterion) pair in vals[start:]."""
    pairs = vals[start:]
    if not pairs or len(pairs) % 2:
        raise _Raise(VALUE)
    rngs = [list(_flat(pairs[i])) for i in range(0, len(pairs), 2)]
    if any(len(r) != n for r in rngs):
        raise _Raise(VALUE)
    crits = [_scalar(pairs[i]) for i in range(1, len(pairs), 2)]
    return [i for i in range(n) if all(_cmatch(r[i], c) for r, c in zip(rngs, crits))]


def _ymd(serial: float):
    n = int(math.floor(serial))
    if n < 0:
        raise _Raise(NUM)
    if n == 0:
        return 1900, 1, 0
    if n == 60:
        return 1900, 2, 29                                        # Excel's phantom 1900-02-29
    d = _dt.date(1899, 12, 31) + _dt.timedelta(days=n - 1) if n < 60 else _dt.date(1899, 12, 30) + _dt.timedelta(days=n)
    return d.year, d.month, d.day


def _serial(y: int, m: int, d: int) -> float:
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    if not 0 <= y <= 9999:
        raise _Raise(NUM)
    base = _dt.date(y if y >= 1900 else y + 1900, m, 1) + _dt.timedelta(days=d - 1)
    if base < _dt.date(1900, 3, 1):
        return float((base - _dt.date(1899, 12, 31)).days)
    return float((base - _dt.date(1899, 12, 30)).days)


def _eom(y: int, m: int) -> int:
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    nxt = _dt.date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - _dt.timedelta(days=1)).day


def _shift_month(serial: float, months: int):
    y, m, d = _ymd(serial)
    t = (y * 12 + m - 1) + months
    return t // 12, t % 12 + 1, d


def _tvm(rate, nper, pmt, pv, fv, typ):
    """Residual of the annuity identity; zero at the solution."""
    if rate == 0:
        return pv + pmt * nper + fv
    g = (1 + rate) ** nper
    return pv * g + pmt * (1 + rate * typ) * (g - 1) / rate + fv


def _lookup_approx(look, keys):
    hit = None
    for i, k in enumerate(keys):
        if _isnum(look) and _isnum(k):
            if float(k) <= float(look):
                hit = i
            else:
                break
        elif isinstance(look, str) and isinstance(k, str):
            if k.upper() <= look.upper():
                hit = i
            else:
                break
    return hit


def _newton(fn, r0: float):
    r = r0
    for _ in range(200):
        h = 1e-7
        y = fn(r)
        d = (fn(r + h) - y) / h
        if d == 0:
            break
        nr = r - y / d
        if nr <= -1:
            nr = (r - 1) / 2
        if abs(nr - r) < 1e-12:
            return nr
        r = nr
    return None


def _ext(eng, f, args, vals):
    """Functions beyond the core set; same semantics as Excel, checked against LibreOffice in tests."""
    def sc(i, d=None):
        return _scalar(vals[i]) if i < len(vals) else d

    def num(i, d=0.0):
        return _num(sc(i)) if i < len(vals) and sc(i) is not None else d

    def flat(i):
        return list(_flat(vals[i]))

    def txt(i):
        v = sc(i)
        if isinstance(v, Err):
            raise _Raise(v)
        return _text(v)

    def typ(i):
        return 1 if i < len(vals) and sc(i) is not None and _num(sc(i)) != 0 else 0

    # ---- lookup
    if f in ("VLOOKUP", "HLOOKUP"):
        look, items = sc(0), flat(1)
        if isinstance(look, Err):
            raise _Raise(look)
        rows, cols = eng.shape(args[1]) or (len(items), 1)
        idx = int(math.floor(num(2)))
        approx = _truthy(sc(3)) if len(vals) > 3 and sc(3) is not None else True
        vert = f == "VLOOKUP"
        if idx < 1:
            raise _Raise(VALUE)
        if idx > (cols if vert else rows):
            raise _Raise(REF)
        keys = [items[r * cols] for r in range(rows)] if vert else items[:cols]
        if approx:
            hit = _lookup_approx(look, keys)
        else:
            hit = None
            for i, k in enumerate(keys):
                if isinstance(look, str) and isinstance(k, str) and ("*" in look or "?" in look):
                    ok = bool(_wild(look).fullmatch(k))
                else:
                    ok = k is not None and _eq(k, look)
                if ok:
                    hit = i
                    break
        if hit is None:
            raise _Raise(NA)
        out = items[hit * cols + idx - 1] if vert else items[(idx - 1) * cols + hit]
        return 0.0 if out is None else out
    if f == "LOOKUP":
        keys = flat(1)
        res = flat(2) if len(vals) > 2 else keys
        hit = _lookup_approx(sc(0), keys)
        if hit is None or hit >= len(res):
            raise _Raise(NA)
        return 0.0 if res[hit] is None else res[hit]
    if f == "XLOOKUP":
        look, keys, ret = sc(0), flat(1), flat(2)
        mode = int(num(4)) if len(vals) > 4 and sc(4) is not None else 0
        rev = len(vals) > 5 and sc(5) is not None and int(num(5)) < 0
        order = list(range(len(keys) - 1, -1, -1) if rev else range(len(keys)))
        hit = None
        for i in order:
            k = keys[i]
            if mode == 2 and isinstance(look, str):
                ok = isinstance(k, str) and bool(_wild(look).fullmatch(k))
            else:
                ok = k is not None and _eq(k, look)
            if ok:
                hit = i
                break
        if hit is None and mode in (-1, 1) and _isnum(look):
            for i in order:
                k = keys[i]
                if not _isnum(k):
                    continue
                if (mode == -1 and k <= look and (hit is None or k > keys[hit])) or (mode == 1 and k >= look and (hit is None or k < keys[hit])):
                    hit = i
        if hit is None:
            if len(vals) > 3 and args[3][0] != "blank":
                return sc(3)
            raise _Raise(NA)
        rs = eng.shape(args[2])
        if rs and rs[1] > 1 and rs[0] == len(keys):               # column lookup, wide return: first cell of the matched row
            return ret[hit * rs[1]]
        if hit >= len(ret):
            raise _Raise(REF)
        return 0.0 if ret[hit] is None else ret[hit]

    # ---- conditional aggregates
    if f in ("AVERAGEIF", "SUMIFS", "AVERAGEIFS", "COUNTIFS", "MAXIFS", "MINIFS"):
        if f == "AVERAGEIF":
            rng = flat(0)
            tgt = flat(2) if len(vals) > 2 else rng
            tgt = tgt + [None] * (len(rng) - len(tgt))
            picked = [tgt[i] for i in range(len(rng)) if _cmatch(rng[i], sc(1))]
        elif f == "COUNTIFS":
            return float(len(_ifs_rows(vals, 0, len(flat(0)))))
        else:
            tgt = flat(0)
            picked = [tgt[i] for i in _ifs_rows(vals, 1, len(tgt))]
        for x in picked:
            if isinstance(x, Err):
                raise _Raise(x)
        nums = _nums(picked)
        if f == "SUMIFS":
            return float(sum(nums))
        if f in ("AVERAGEIF", "AVERAGEIFS"):
            if not nums:
                raise _Raise(DIV0)
            return sum(nums) / len(nums)
        if not nums:
            return 0.0
        return max(nums) if f == "MAXIFS" else min(nums)

    # ---- dates
    if f in ("YEAR", "MONTH", "DAY"):
        y, m, d = _ymd(num(0))
        return float({"YEAR": y, "MONTH": m, "DAY": d}[f])
    if f == "DATE":
        y, m, d = int(num(0)), int(num(1)), int(num(2))
        if y < 0 or y > 9999:
            raise _Raise(NUM)
        return _serial(y, m, d)
    if f in ("EOMONTH", "EDATE"):
        y, m, d = _shift_month(num(0), int(num(1)))
        if f == "EOMONTH":
            return _serial(y, m, _eom(y, m))
        return _serial(y, m, min(d, _eom(y, m)))

    # ---- text
    if f == "CONCATENATE":
        return "".join(txt(i) for i in range(len(vals)))
    if f == "CONCAT":
        out = []
        for v in vals:
            for x in _flat(v):
                if isinstance(x, Err):
                    raise _Raise(x)
                out.append(_text(x))
        return "".join(out)
    if f == "TEXTJOIN":
        delim, skip = txt(0), _truthy(sc(1))
        parts = []
        for v in vals[2:]:
            for x in _flat(v):
                if isinstance(x, Err):
                    raise _Raise(x)
                if skip and (x is None or x == ""):
                    continue
                parts.append(_text(x))
        return delim.join(parts)
    if f == "RIGHT":
        n, s = int(num(1, 1.0)), txt(0)
        if n < 0:
            raise _Raise(VALUE)
        return s[len(s) - n:] if 0 < n < len(s) else ("" if n == 0 else s)
    if f == "MID":
        start, n = int(num(1)), int(num(2))
        if start < 1 or n < 0:
            raise _Raise(VALUE)
        return txt(0)[start - 1:start - 1 + n]
    if f == "UPPER":
        return txt(0).upper()
    if f == "LOWER":
        return txt(0).lower()
    if f == "TRIM":
        return re.sub(" +", " ", txt(0)).strip(" ")
    if f == "SUBSTITUTE":
        s, old, new = txt(0), txt(1), txt(2)
        if old == "":
            return s
        if len(vals) > 3 and sc(3) is not None:
            k = int(num(3))
            if k < 1:
                raise _Raise(VALUE)
            pos = -1
            for _ in range(k):
                pos = s.find(old, pos + 1)
                if pos < 0:
                    return s
            return s[:pos] + new + s[pos + len(old):]
        return s.replace(old, new)
    if f == "VALUE":
        v = sc(0)
        if isinstance(v, Err):
            raise _Raise(v)
        if v is None:
            return 0.0
        if _isnum(v):
            return float(v)
        if isinstance(v, bool):
            raise _Raise(VALUE)
        t = str(v).strip().replace(",", "").replace("$", "").strip()
        pct = t.endswith("%")
        t = t[:-1].strip() if pct else t
        if t.startswith("(") and t.endswith(")"):
            t = "-" + t[1:-1]
        try:
            x = float(t)
        except ValueError:
            raise _Raise(VALUE)
        return x / 100 if pct else x

    # ---- statistics
    if f in ("LARGE", "SMALL"):
        xs = flat(0)
        for x in xs:
            if isinstance(x, Err):
                raise _Raise(x)
        nums = sorted(_nums(xs), reverse=(f == "LARGE"))
        k = int(math.ceil(num(1)))
        if k < 1 or k > len(nums):
            raise _Raise(NUM)
        return nums[k - 1]
    if f in ("RANK", "RANK.EQ"):
        x = _num(sc(0))
        xs = flat(1)
        for y in xs:
            if isinstance(y, Err):
                raise _Raise(y)
        nums = _nums(xs)
        if x not in nums:
            raise _Raise(NA)
        asc = len(vals) > 2 and sc(2) is not None and _truthy(sc(2))
        return float(1 + sum(1 for y in nums if (y < x if asc else y > x)))
    if f == "PRODUCT":
        p, seen = 1.0, False
        for v, a in zip(vals, args):
            for x in _flat(v):
                if isinstance(x, Err):
                    raise _Raise(x)
                if a[0] in ("range", "name") and not _isnum(x):
                    continue
                if x is None:
                    continue
                p *= _num(x)
                seen = True
        return p if seen else 0.0
    if f == "COUNTBLANK":
        return float(sum(1 for x in flat(0) if x is None or x == ""))
    if f == "NA":
        raise _Raise(NA)

    # ---- financial
    if f == "RATE":
        nper, pmt, pv, fv, t = num(0), num(1), num(2), num(3, 0.0), typ(4)
        r = _newton(lambda x: _tvm(x, nper, pmt, pv, fv, t), num(5, 0.1))
        if r is None:
            raise _Raise(NUM)
        return r
    if f in ("PMT", "FV", "PV", "NPER"):
        rate = num(0)
        if f == "PMT":
            nper, pv, fv, t = num(1), num(2), num(3, 0.0), typ(4)
            if nper == 0:
                raise _Raise(NUM)
            if rate == 0:
                return -(pv + fv) / nper
            g = (1 + rate) ** nper
            return -(pv * g + fv) * rate / ((1 + rate * t) * (g - 1))
        if f == "FV":
            nper, pmt, pv, t = num(1), num(2), num(3, 0.0), typ(4)
            if rate == 0:
                return -(pv + pmt * nper)
            g = (1 + rate) ** nper
            return -(pv * g + pmt * (1 + rate * t) * (g - 1) / rate)
        if f == "PV":
            nper, pmt, fv, t = num(1), num(2), num(3, 0.0), typ(4)
            if rate == 0:
                return -(fv + pmt * nper)
            g = (1 + rate) ** nper
            return -(fv + pmt * (1 + rate * t) * (g - 1) / rate) / g
        pmt, pv, fv, t = num(1), num(2), num(3, 0.0), typ(4)
        if rate == 0:
            if pmt == 0:
                raise _Raise(NUM)
            return -(pv + fv) / pmt
        a, b = pmt * (1 + rate * t) / rate - fv, pv + pmt * (1 + rate * t) / rate
        if b == 0 or a / b <= 0:
            raise _Raise(NUM)
        return math.log(a / b) / math.log(1 + rate)
    if f in ("XNPV", "XIRR"):
        vs, ds = flat(1 if f == "XNPV" else 0), flat(2 if f == "XNPV" else 1)
        for x in vs + ds:
            if isinstance(x, Err):
                raise _Raise(x)
        if len(vs) != len(ds) or not vs:
            raise _Raise(NUM)
        cf = [_num(x) for x in vs]
        dd = [math.floor(_num(x)) for x in ds]
        if any(d < dd[0] for d in dd):
            raise _Raise(NUM)
        t = [(d - dd[0]) / 365.0 for d in dd]

        def npv(r):
            return sum(c / (1 + r) ** ti for c, ti in zip(cf, t))
        if f == "XNPV":
            r = _num(sc(0))
            if r <= -1:
                raise _Raise(NUM)
            return npv(r)
        if not (any(c > 0 for c in cf) and any(c < 0 for c in cf)):
            raise _Raise(NUM)
        r = _newton(npv, num(2, 0.1))
        if r is not None:
            return r
        lo, hi = -0.999999, 1e6                                   # bracketed fallback
        if npv(lo) * npv(hi) > 0:
            raise _Raise(NUM)
        for _ in range(300):
            mid = (lo + hi) / 2
            if npv(lo) * npv(mid) <= 0:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2
    eng.unsupported.add(f)
    raise _Raise(NAME)
