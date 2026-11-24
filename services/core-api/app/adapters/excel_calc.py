"""Sandboxed evaluator for the filed actuarial workbook.

Supports a deliberately small, auditable formula subset: arithmetic (+ - * / ^), comparisons,
cell references and ranges (with sheet prefixes), and the functions VLOOKUP, IF, ROUND, MIN, MAX,
SUM, AND, OR. Anything else (macros, external links, INDIRECT, volatile functions) is refused, so
the workbook cannot execute arbitrary logic.
"""
from __future__ import annotations

import io
import re
from decimal import ROUND_HALF_UP, Decimal

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

_TOKEN = re.compile(r"""
    (?P<num>\d+(?:\.\d+)?)
  | (?P<str>"[^"]*")
  | (?P<ref>(?:[A-Za-z_][A-Za-z0-9_]*!)?\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)
  | (?P<func>[A-Z]+(?=\())
  | (?P<bool>TRUE|FALSE)
  | (?P<op><>|>=|<=|[-+*/^=<>&])
  | (?P<lp>\()
  | (?P<rp>\))
  | (?P<comma>,)
  | (?P<ws>\s+)
""", re.X)
ALLOWED_FUNCS = {"VLOOKUP", "IF", "ROUND", "MIN", "MAX", "SUM", "AND", "OR"}


class CalcError(Exception):
    pass


def _tokens(expr: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m:
            raise CalcError(f"unsupported syntax at: {expr[pos:pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind or "", m.group()))
    return out


class Workbook:
    def __init__(self, data: bytes) -> None:
        wb = load_workbook(io.BytesIO(data), data_only=False)
        if getattr(wb, "vba_archive", None):
            raise CalcError("macro-enabled workbooks are not allowed")
        self.cells: dict[str, object] = {}
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if c.value is not None:
                        self.cells[f"{ws.title}!{c.coordinate}"] = c.value
        self.overrides: dict[str, object] = {}
        self._cache: dict[str, object] = {}

    def set(self, addr: str, value: object) -> None:
        self.overrides[addr] = value
        self._cache.clear()

    def get(self, addr: str, depth: int = 0) -> object:
        if depth > 50:
            raise CalcError("circular or too-deep reference")
        if addr in self.overrides:
            return self.overrides[addr]
        if addr in self._cache:
            return self._cache[addr]
        raw = self.cells.get(addr)
        if isinstance(raw, str) and raw.startswith("="):
            sheet = addr.split("!")[0]
            val = _Parser(_tokens(raw[1:]), self, sheet, depth).parse()
        else:
            val = raw
        self._cache[addr] = val
        return val

    def range(self, sheet: str, a: str, b: str, depth: int) -> list[list[object]]:
        ca, ra = re.match(r"\$?([A-Z]+)\$?(\d+)", a).groups()  # type: ignore[union-attr]
        cb, rb = re.match(r"\$?([A-Z]+)\$?(\d+)", b).groups()  # type: ignore[union-attr]
        rows = []
        for r in range(int(ra), int(rb) + 1):
            rows.append([self.get(f"{sheet}!{get_column_letter(c)}{r}", depth + 1)
                         for c in range(column_index_from_string(ca), column_index_from_string(cb) + 1)])
        return rows


class _Parser:
    def __init__(self, toks, wb: Workbook, sheet: str, depth: int) -> None:
        self.t, self.i, self.wb, self.sheet, self.depth = toks, 0, wb, sheet, depth

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, kind=None):
        tok = self.peek()
        if kind and tok[0] != kind:
            raise CalcError(f"expected {kind}, got {tok}")
        self.i += 1
        return tok

    def parse(self):
        v = self.comparison()
        if self.i != len(self.t):
            raise CalcError("trailing tokens")
        return v

    def comparison(self):
        left = self.additive()
        while self.peek()[0] == "op" and self.peek()[1] in ("=", "<>", ">", "<", ">=", "<="):
            op = self.take()[1]
            right = self.additive()
            left = {"=": left == right, "<>": left != right, ">": left > right, "<": left < right,
                    ">=": left >= right, "<=": left <= right}[op]
        return left

    def additive(self):
        left = self.term()
        while self.peek()[0] == "op" and self.peek()[1] in "+-":
            op = self.take()[1]
            right = self.term()
            left = left + right if op == "+" else left - right
        return left

    def term(self):
        left = self.power()
        while self.peek()[0] == "op" and self.peek()[1] in "*/":
            op = self.take()[1]
            right = self.power()
            left = left * right if op == "*" else left / right
        return left

    def power(self):
        base = self.unary()
        if self.peek() == ("op", "^"):
            self.take()
            return base ** self.unary()
        return base

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return -self.unary()
        return self.atom()

    def atom(self):
        kind, val = self.peek()
        if kind == "num":
            self.take()
            return float(val)
        if kind == "str":
            self.take()
            return val[1:-1]
        if kind == "bool":
            self.take()
            return val == "TRUE"
        if kind == "lp":
            self.take()
            v = self.comparison()
            self.take("rp")
            return v
        if kind == "ref":
            self.take()
            sheet, ref = (val.split("!") if "!" in val else (self.sheet, val))
            if ":" in ref:
                a, b = ref.split(":")
                return self.wb.range(sheet, a, b, self.depth)
            v = self.wb.get(f"{sheet}!{ref.replace('$', '')}", self.depth + 1)
            return 0.0 if v is None else v
        if kind == "func":
            name = self.take()[1]
            if name not in ALLOWED_FUNCS:
                raise CalcError(f"function {name} is not permitted")
            self.take("lp")
            args = []
            if self.peek()[0] != "rp":
                args.append(self.comparison())
                while self.peek()[0] == "comma":
                    self.take()
                    args.append(self.comparison())
            self.take("rp")
            return _call(name, args)
        raise CalcError(f"unexpected token {val!r}")


def _flat(args):
    for a in args:
        if isinstance(a, list):
            for row in a:
                yield from (x for x in (row if isinstance(row, list) else [row]) if isinstance(x, int | float))
        elif isinstance(a, int | float) and not isinstance(a, bool):
            yield a


def _call(name: str, a: list):
    if name == "IF":
        return a[1] if a[0] else (a[2] if len(a) > 2 else False)
    if name == "ROUND":
        q = Decimal(1).scaleb(-int(a[1]))
        return float(Decimal(str(a[0])).quantize(q, rounding=ROUND_HALF_UP))
    if name == "MIN":
        return min(_flat(a))
    if name == "MAX":
        return max(_flat(a))
    if name == "SUM":
        return sum(_flat(a))
    if name == "AND":
        return all(a)
    if name == "OR":
        return any(a)
    if name == "VLOOKUP":
        key, table, col = a[0], a[1], int(a[2])
        exact = len(a) < 4 or a[3] in (False, 0, 0.0)
        for row in table:
            if (row[0] == key) if exact else False:
                return row[col - 1]
        raise CalcError(f"VLOOKUP: {key!r} not found in filed table")
    raise CalcError(name)  # pragma: no cover
