"""Puzzle file formats, and turning their bytes into .xd.

A format is picked by looking at the bytes, never the file extension: sites serve
puzzles under all kinds of names.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

import ipuz
import puz
from xdformat import IncompletePuzzleParse, PuzzleParseError, xdfile
from xdformat.ipuz2xd import parse_ipuz
from xdformat.puz2xd import parse_puz


class ConvertError(Exception):
    """The bytes are a puzzle we can't read, or not a puzzle at all."""


@dataclass(frozen=True)
class Format:
    name: str
    sniff: Callable[[bytes], bool]
    convert: Callable[[bytes, str], xdfile]  # (data, filename) -> xdfile


PUZ_MAGIC = b"ACROSS&DOWN\x00"


def sniff_puz(data: bytes) -> bool:
    return data[2:14] == PUZ_MAGIC


def sniff_ipuz(data: bytes) -> bool:
    text = data.lstrip(b"\xef\xbb\xbf").strip()
    if text.startswith(b"ipuz(") and text.endswith(b")"):  # JSONP, as some sites serve it
        text = text[5:-1]
    if not text.startswith(b"{"):
        return False
    try:
        kinds = json.loads(text).get("kind", [])
    except (ValueError, AttributeError):
        return False
    return any(isinstance(k, str) and k.startswith("http://ipuz.org/crossword") for k in kinds)


FORMATS: list[Format] = [
    Format("puz", sniff_puz, parse_puz),
    Format("ipuz", sniff_ipuz, parse_ipuz),
]


def identify(data: bytes) -> Format | None:
    return next((f for f in FORMATS if f.sniff(data)), None)


def convert(data: bytes, filename: str = "") -> str:
    """The .xd text for a puzzle file's bytes."""
    fmt = identify(data)
    if fmt is None:
        raise ConvertError(f"{filename or 'input'}: not a puzzle format xdfetch knows")
    try:
        xd = fmt.convert(data, filename)
    except (PuzzleParseError, IncompletePuzzleParse, ipuz.IPUZException, puz.PuzzleFormatError) as e:
        raise ConvertError(f"{filename or 'input'}: not a valid {fmt.name} file ({e})") from e
    except Exception as e:  # the parsers fail in other ways on damaged files (e.g. UnicodeDecodeError)
        raise ConvertError(f"{filename or 'input'}: not a valid {fmt.name} file ({type(e).__name__}: {e})") from e
    return xd.to_unicode()
