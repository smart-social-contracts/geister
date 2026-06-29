#!/usr/bin/env python3
"""
icp_candid.py — Candid text parser + icp canister-call helpers.

Phase 2 of the dfx → icp-cli migration (geister issue #18).

`icp canister call --candid <did> --json` produces:
    {"response_bytes": "<hex>", "response_candid": "(<candid text>)"}

With the --candid flag icp resolves field hashes to names, so response_candid
contains human-readable Candid like:
    (
      record {
        success = true;
        data = variant { Ok = "hello" };
      },
    )

This module parses that Candid text into Python objects and serialises the
result to JSON — matching the format that dfx --output json produced, so all
existing callers in realm_tools.py continue to work unchanged.

Public API
----------
parse_candid_response(envelope_json)  -> Any      (parse icp --json output)
find_candid_file(canister, realm_folder) -> str | None
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional


# ---------------------------------------------------------------------------
# .did file lookup
# ---------------------------------------------------------------------------

def find_candid_file(canister: str, realm_folder: str) -> Optional[str]:
    """Return the absolute path of the .did file for `canister`.

    Reads the `candid` field from dfx.json in `realm_folder`.  If the path is
    relative it is resolved relative to `realm_folder`.  Returns None if the
    file cannot be found.
    """
    dfx_json = os.path.join(realm_folder, "dfx.json")
    try:
        with open(dfx_json) as f:
            dfx = json.load(f)
        candid_rel = dfx.get("canisters", {}).get(canister, {}).get("candid", "")
        if not candid_rel:
            return None
        if not os.path.isabs(candid_rel):
            candid_rel = os.path.join(realm_folder, candid_rel)
        return candid_rel if os.path.exists(candid_rel) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Candid text parser
# ---------------------------------------------------------------------------

class _CandidParser:
    """Recursive-descent parser for Candid text format (as produced by icp-cli)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self._skip()

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _skip(self) -> None:
        """Skip whitespace and line comments."""
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch in " \t\n\r":
                self.pos += 1
            elif self.text[self.pos : self.pos + 2] == "//":
                while self.pos < len(self.text) and self.text[self.pos] != "\n":
                    self.pos += 1
            else:
                break

    def _peek(self) -> Optional[str]:
        return self.text[self.pos] if self.pos < len(self.text) else None

    def _consume(self, s: str) -> bool:
        if self.text[self.pos : self.pos + len(s)] == s:
            self.pos += len(s)
            self._skip()
            return True
        return False

    def _expect(self, s: str) -> None:
        if not self._consume(s):
            snippet = self.text[self.pos : self.pos + 20]
            raise ValueError(f"Expected {s!r} at pos {self.pos}, got {snippet!r}")

    def _keyword(self, kw: str) -> bool:
        """True if the next token is exactly the keyword `kw` (not just a prefix)."""
        end = self.pos + len(kw)
        if self.text[self.pos : end] != kw:
            return False
        if end < len(self.text) and (self.text[end].isalnum() or self.text[end] == "_"):
            return False
        return True

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def parse(self) -> Any:
        """Parse a Candid return tuple: (v1, v2, ...) → single value or list."""
        self._expect("(")
        values: list[Any] = []
        while self._peek() != ")" and self._peek() is not None:
            values.append(self._value())
            self._consume(",")
        self._expect(")")
        return values[0] if len(values) == 1 else values

    # ------------------------------------------------------------------
    # Value dispatch
    # ------------------------------------------------------------------

    def _value(self) -> Any:
        p = self._peek()
        if p is None:
            return None

        if self._keyword("record"):
            return self._record()
        if self._keyword("variant"):
            return self._variant()
        if self._keyword("vec"):
            return self._vec()
        if self._keyword("opt"):
            self._consume("opt")
            return self._value()
        if self._keyword("null"):
            self._consume("null")
            return None
        if self._keyword("true"):
            self._consume("true")
            return True
        if self._keyword("false"):
            self._consume("false")
            return False
        if self._keyword("principal"):
            self._consume("principal")
            return self._string()
        if self._keyword("blob"):
            self._consume("blob")
            return self._string()
        if self._keyword("func"):
            self._consume("func")
            return self._string()
        if self._keyword("service"):
            self._consume("service")
            return self._string()
        if p == '"':
            return self._string()
        if p in "0123456789" or (p in "+-" and self.pos + 1 < len(self.text) and self.text[self.pos + 1].isdigit()):
            return self._number()
        if p == "(":
            # nested parens (e.g. func references)
            self._consume("(")
            v = self._value()
            self._consume(")")
            return v
        if p.isalpha() or p == "_":
            return self._ident()
        return None

    # ------------------------------------------------------------------
    # Compound types
    # ------------------------------------------------------------------

    def _record(self) -> dict:
        self._consume("record")
        self._expect("{")
        result: dict = {}
        while self._peek() != "}" and self._peek() is not None:
            key = self._key()
            self._expect("=")
            val = self._value()
            result[key] = val
            self._consume(";")
        self._expect("}")
        return result

    def _variant(self) -> dict:
        self._consume("variant")
        self._expect("{")
        key = self._key()
        if self._consume("="):
            val: Any = self._value()
        else:
            val = None  # unit variant
        self._consume(";")
        self._expect("}")
        return {key: val}

    def _vec(self) -> list:
        self._consume("vec")
        self._expect("{")
        items: list = []
        while self._peek() != "}" and self._peek() is not None:
            items.append(self._value())
            self._consume(";")
        self._expect("}")
        return items

    # ------------------------------------------------------------------
    # Primitives
    # ------------------------------------------------------------------

    def _key(self) -> str:
        """Parse a record/variant key: identifier or numeric hash."""
        p = self._peek()
        if p and p.isdigit():
            # numeric field hash — keep as _HASH string
            start = self.pos
            while self.pos < len(self.text) and (self.text[self.pos].isdigit() or self.text[self.pos] == "_"):
                self.pos += 1
            raw = self.text[start : self.pos].replace("_", "")
            self._skip()
            return f"_{raw}"
        return self._ident()

    def _ident(self) -> str:
        if not self._peek() or not (self._peek().isalpha() or self._peek() == "_"):
            return ""
        start = self.pos
        while self.pos < len(self.text) and (self.text[self.pos].isalnum() or self.text[self.pos] == "_"):
            self.pos += 1
        ident = self.text[start : self.pos]
        self._skip()
        return ident

    def _string(self) -> str:
        self._expect('"')
        buf: list[str] = []
        while self.pos < len(self.text) and self.text[self.pos] != '"':
            ch = self.text[self.pos]
            if ch == "\\":
                self.pos += 1
                esc = self.text[self.pos]
                if esc == "n":
                    buf.append("\n")
                elif esc == "t":
                    buf.append("\t")
                elif esc == "r":
                    buf.append("\r")
                elif esc == '"':
                    buf.append('"')
                elif esc == "\\":
                    buf.append("\\")
                elif esc == "u":
                    # \u{NNNN}
                    self.pos += 1  # skip {
                    self.pos += 1
                    hex_start = self.pos
                    while self.pos < len(self.text) and self.text[self.pos] != "}":
                        self.pos += 1
                    buf.append(chr(int(self.text[hex_start : self.pos], 16)))
                else:
                    buf.append(esc)
            else:
                buf.append(ch)
            self.pos += 1
        self.pos += 1  # closing "
        self._skip()
        return "".join(buf)

    def _number(self) -> int | float:
        start = self.pos
        if self.text[self.pos] in "+-":
            self.pos += 1
        while self.pos < len(self.text) and (self.text[self.pos].isdigit() or self.text[self.pos] == "_"):
            self.pos += 1
        is_float = False
        if self.pos < len(self.text) and self.text[self.pos] == ".":
            is_float = True
            self.pos += 1
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self.pos += 1
        raw = self.text[start : self.pos].replace("_", "")
        self._skip()
        # skip optional type annotation e.g.  : nat32
        if self.pos < len(self.text) and self.text[self.pos] == ":":
            self.pos += 1
            self._skip()
            self._ident()  # skip the type keyword
        return float(raw) if is_float else int(raw)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def parse_candid_response(envelope_json: str) -> Any:
    """Parse the JSON envelope produced by `icp canister call --json`.

    Returns a Python object (dict / list / str / int / bool / None) matching
    what `dfx canister call --output json` would have returned for the same
    call, so all existing realm_tools.py callers work unchanged.

    Returns None on any parse failure (caller should fall back to dfx).
    """
    try:
        envelope = json.loads(envelope_json)
    except (json.JSONDecodeError, TypeError):
        return None

    candid_text = envelope.get("response_candid", "")
    if not candid_text:
        return None

    try:
        return _CandidParser(candid_text).parse()
    except Exception:
        return None


def candid_to_json(value: Any) -> str:
    """Serialise a parsed Candid value to a JSON string.

    Handles non-serialisable types gracefully (converts to str).
    """
    def _default(o: Any) -> Any:
        return str(o)

    return json.dumps(value, default=_default)


def parse(candid_text: str) -> Any:
    """Parse a Candid response_candid string into Python objects.

    Convenience alias used by realm_tools._run_dfx_call:
        parsed = icp_candid.parse(response_candid_string)
    """
    try:
        return _CandidParser(candid_text).parse()
    except Exception:
        return None
