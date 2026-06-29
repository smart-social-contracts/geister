"""
candid_text.py — Lightweight Candid-text → Python converter.

Used by realm_tools._run_icp_call (Phase 2 of the dfx→icp-cli migration,
geister issue #18) to convert `icp canister call --json`'s `response_candid`
field into a Python value that matches the shape produced by
`dfx canister call --output json`.

Supported types
---------------
  outer tuple    (val,) or (v1, v2, …) — single-element tuples are unwrapped
  record         record { field = value; … }
  variant        variant { Tag = value } or variant { Tag }
  vec            vec { v1; v2; … }
  opt            opt value   (null is handled as the None literal)
  text           "string"
  nat / int      123, -5, 1_000_000  (underscores stripped)
  float          3.14
  bool           true / false
  null           null
  principal      principal "aaaaa-aa"
  blob           blob "…"            (returned as hex/raw string)
  type annot     `: SomeType` — silently skipped after a value
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOK_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"'                       # string literal (handles escapes)
    r'|0x[0-9a-fA-F][0-9a-fA-F_]*'            # hex literal
    r'|[+-]?\d[\d_]*(?:\.\d[\d_]*)?'           # number (int or float, leading sign OK)
    r'|[a-zA-Z_][a-zA-Z0-9_]*'                # identifier / keyword
    r'|[(){};:=,<>]'                           # punctuation
)


def _tokenize(text: str) -> list[str]:
    return _TOK_RE.findall(text)


def _unescape(s: str) -> str:
    return (s.replace('\\"', '"')
             .replace('\\n', '\n')
             .replace('\\t', '\t')
             .replace('\\r', '\r')
             .replace('\\\\', '\\'))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    """Recursive-descent Candid-text parser."""

    def __init__(self, tokens: list[str]):
        self._t = tokens
        self._i = 0

    # ── Token helpers ─────────────────────────────────────────────────────

    def _peek(self) -> str:
        return self._t[self._i] if self._i < len(self._t) else ''

    def _next(self) -> str:
        tok = self._peek()
        self._i += 1
        return tok

    def _eat(self, expected: str) -> str:
        tok = self._next()
        if tok != expected:
            raise ValueError(f"candid_text: expected {expected!r}, got {tok!r} (pos {self._i})")
        return tok

    def _try_eat(self, tok: str) -> bool:
        if self._peek() == tok:
            self._i += 1
            return True
        return False

    def _skip_type_annotation(self) -> None:
        """Silently consume `: TypeName` (and simple generics like `opt text`)."""
        if self._peek() != ':':
            return
        self._next()  # ':'
        # Type may be a single identifier or a parenthesised expression; just eat the ident.
        if self._peek() and (self._peek()[0].isalpha() or self._peek()[0] == '_'):
            self._next()

    # ── Value dispatch ────────────────────────────────────────────────────

    def value(self) -> Any:  # noqa: C901 (complexity is inherent)
        tok = self._peek()

        if tok == '(':
            return self._tuple()
        if tok == 'record':
            return self._record()
        if tok == 'variant':
            return self._variant()
        if tok == 'vec':
            return self._vec()
        if tok == 'opt':
            return self._opt()
        if tok == 'blob':
            return self._blob()
        if tok == 'principal':
            return self._principal()
        if tok == 'true':
            self._next(); return True
        if tok == 'false':
            self._next(); return False
        if tok == 'null':
            self._next(); return None

        # String literal
        if tok and tok[0] == '"':
            self._next()
            return _unescape(tok[1:-1])

        # Number (int or float, possibly with leading sign)
        if tok and (tok[0].isdigit() or (tok[0] in '+-' and len(tok) > 1)):
            self._next()
            self._skip_type_annotation()
            raw = tok.replace('_', '')
            try:
                if '.' in raw or ('e' in raw.lower() and raw.lstrip('+-').replace('.', '', 1).isdigit()):
                    return float(raw)
                return int(raw, 0)  # handles 0x hex and decimal
            except ValueError:
                return tok

        # Bare identifier — may be a type keyword we don't recognise yet
        if tok and (tok[0].isalpha() or tok[0] == '_'):
            self._next()
            self._skip_type_annotation()
            return tok

        # Unknown token — advance to avoid infinite loop
        if tok:
            self._next()
        return None

    # ── Compound types ────────────────────────────────────────────────────

    def _tuple(self) -> Any:
        """Parse (val, val, …).  Single-element tuples are unwrapped."""
        self._eat('(')
        items: list[Any] = []
        while self._peek() != ')' and self._peek():
            items.append(self.value())
            self._try_eat(',')
        self._eat(')')
        return items[0] if len(items) == 1 else items

    def _record(self) -> dict:
        self._eat('record')
        self._eat('{')
        out: dict = {}
        while self._peek() != '}' and self._peek():
            key = self._record_key()
            self._eat('=')
            out[key] = self.value()
            self._try_eat(';')
        self._eat('}')
        return out

    def _record_key(self) -> str:
        tok = self._next()
        # Numeric hash fields (e.g. `1_234_567`) — keep as string key
        if tok.replace('_', '').isdigit():
            return tok.replace('_', '')
        return tok

    def _variant(self) -> dict:
        self._eat('variant')
        self._eat('{')
        tag = self._next()
        if self._peek() == '=':
            self._next()
            val = self.value()
        else:
            val = None
        self._try_eat(';')
        self._eat('}')
        return {tag: val}

    def _vec(self) -> list:
        self._eat('vec')
        self._eat('{')
        items: list[Any] = []
        while self._peek() != '}' and self._peek():
            items.append(self.value())
            self._try_eat(';')
        self._eat('}')
        return items

    def _opt(self) -> Any:
        self._eat('opt')
        return self.value()

    def _blob(self) -> str:
        self._eat('blob')
        tok = self._peek()
        if tok and tok[0] == '"':
            self._next()
            return tok[1:-1]
        return ''

    def _principal(self) -> str:
        self._eat('principal')
        tok = self._peek()
        if tok and tok[0] == '"':
            self._next()
            return tok[1:-1]
        return self._next()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse(candid_text: str) -> Any:
    """
    Parse a Candid-text string into Python-native types.

    The outer tuple is unwrapped (single-element → its value), mirroring the
    behaviour of `dfx canister call --output json`.  Returns None for empty or
    unparsable input rather than raising.
    """
    tokens = _tokenize(candid_text.strip())
    if not tokens:
        return None
    try:
        return _Parser(tokens).value()
    except Exception:
        return None
