"""macOS NFD filenames vs Linux NFC lookups.

macOS stores Korean names as decomposed Hangul (NFD). A model often rewrites
the same name to composed Hangul (NFC). Linux and S3 do not treat those as
the same path, so an NFC lookup misses an object placed from a Mac.
"""

from __future__ import annotations

import os
import re
import unicodedata

_QUOTED_PATH = re.compile(r"""(['"])([^'"]+)\1""")
_BARE_PATH = re.compile(r"(?:(?:\.\./|\./|/)[^\s'\"`;|&<>]+)")


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value or "")


def nfd(value: str) -> str:
    return unicodedata.normalize("NFD", value or "")


def path_spellings(path: str) -> list[str]:
    """Unique original / NFC / NFD spellings of one path."""
    cleaned = (path or "").strip()
    if not cleaned:
        return []
    out: list[str] = []
    for form in (cleaned, nfc(cleaned), nfd(cleaned)):
        if form and form not in out:
            out.append(form)
    return out


def _join(parent: str, name: str) -> str:
    if parent in ("", "."):
        return name
    if parent == "/":
        return "/" + name
    return parent.rstrip("/") + "/" + name


def _match_entry(parent: str, name: str) -> str | None:
    """Return the directory entry that is the same name in NFC or NFD."""
    for form in path_spellings(name):
        if os.path.lexists(_join(parent, form)):
            return form
    list_dir = "/" if parent == "/" else ("." if parent in ("", ".") else parent)
    try:
        entries = os.listdir(list_dir)
    except OSError:
        return None
    want = nfc(name)
    for entry in entries:
        if nfc(entry) == want:
            return entry
    return None


def resolve_existing_path(path: str) -> str:
    """Return the on-disk spelling of ``path``.

    If neither form exists, return the NFC spelling so new files stay composed.
    """
    raw = (path or "").strip().replace("\\", "/")
    if not raw:
        return raw
    for cand in path_spellings(raw):
        if os.path.lexists(cand):
            return cand

    absolute = raw.startswith("/")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts:
        return nfc(raw)

    current = "/" if absolute else ""
    for index, part in enumerate(parts):
        parent = "/" if current == "/" else (current or ".")
        matched = _match_entry(parent, part)
        if matched is None:
            tail = "/".join(nfc(piece) for piece in parts[index:])
            if current in ("", "/"):
                return ("/" + tail) if absolute else tail
            return current.rstrip("/") + "/" + tail
        current = _join("/" if current == "/" else current, matched)
    return current or nfc(raw)


def rewrite_command_unicode_paths(command: str) -> str:
    """Point shell/Python path literals at the spelling that exists on disk."""
    if not command or not any(ord(ch) > 127 for ch in command):
        return command

    def replace(body: str) -> str:
        if "/" not in body:
            return body
        resolved = resolve_existing_path(body)
        if resolved != body and os.path.lexists(resolved):
            return resolved
        return body

    def repl_quoted(match: re.Match[str]) -> str:
        quote, body = match.group(1), match.group(2)
        updated = replace(body)
        if updated == body:
            return match.group(0)
        return f"{quote}{updated}{quote}"

    rewritten = _QUOTED_PATH.sub(repl_quoted, command)

    def repl_bare(match: re.Match[str]) -> str:
        return replace(match.group(0))

    return _BARE_PATH.sub(repl_bare, rewritten)
