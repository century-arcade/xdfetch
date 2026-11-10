"""Converters: one per format, chosen by sniffing content, never by file extension
(NYT, Condé, Washington Post and Daily Princetonian payloads are all `.json`).

A converter is a function `convert(data: bytes, ctx: Context) -> Puzzle` with a
`sniff(data: bytes) -> bool` beside it. It builds a Puzzle (xdfetch.xd) and lists in
`puzzle.tricky` whatever the source had that xd can't carry, instead of dropping it
silently. The built-in ones are registered in `_builtins()`.

Plugins
-------
Another installed package can add converters through the entry-point group
`xdfetch.converters`. In its pyproject.toml:

    [project.entry-points."xdfetch.converters"]
    myformat = "mypackage.myformat"

Each entry point resolves to either

- a `(name, sniff, convert)` tuple, or
- any object with `sniff` and `convert` attributes, such as a module that defines both
  functions; its `name` attribute names it if it has one, else the entry point's name.

Plugin converters are sniffed before the built-in ones (in entry-point name order), so a
plugin can take over a format, or a corner of one. A plugin's `convert` may also return
None, meaning "not mine after all": the next converter whose sniff accepts the data gets
it. That lets a plugin add an outlet's conventions on top of a built-in converter without
copying it: sniff the same bytes, and in `convert` either return None (the context isn't
that outlet's) or call the built-in (`xdfetch.convert.ipuz.convert(data, ctx)`, say) and
adjust the Puzzle it returns.

A plugin that fails to load, or isn't one of the shapes above, raises PluginError naming
the entry point the first time converters are listed; nothing is loaded at import.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.metadata
from collections.abc import Callable
from dataclasses import dataclass, field

from ..xd import Puzzle

PLUGIN_GROUP = "xdfetch.converters"


@dataclass
class Context:
    """What a converter knows besides the bytes. All of it is optional: from the command line
    there is only a filename. `id` names the outlet, an opaque string no converter looks
    at; `date` is the puzzle's date (a converter writes it as the Date header and checks
    the file's own date against it); `params` are the outlet's conventions (see each
    converter's docstring); `companions` are other files kept beside the puzzle, by name,
    for a plugin converter that needs them."""

    id: str = ""
    date: dt.date | None = None
    filename: str = ""
    source_url: str = ""
    params: dict[str, str] = field(default_factory=dict)
    companions: dict[str, bytes] = field(default_factory=dict)


Converter = Callable[[bytes, Context], Puzzle]
Sniff = Callable[[bytes], bool]
# a plugin's convert may return None to pass the data on
Entry = tuple[str, Sniff, Callable[[bytes, Context], Puzzle | None]]


class UnknownFormat(ValueError):
    pass


class ConvertError(ValueError):
    """The bytes are in a converter's format, but it can't make a puzzle of them."""

    fmt: str | None = None  # the converter's name, set by convert(); see format_of()


class PluginError(ConvertError):
    """A converter plugin that can't be loaded or used."""


def _builtins() -> list[Entry]:
    from . import ccjson, ccxml, conde, ipuz, nytjson, princetonian, puz, puzzlr, uclick, wapo

    return [
        ("uclick", uclick.sniff, uclick.convert),
        ("nytjson", nytjson.sniff, nytjson.convert),
        ("conde", conde.sniff, conde.convert),
        ("puzzlr", puzzlr.sniff, puzzlr.convert),
        ("wapo", wapo.sniff, wapo.convert),
        ("princetonian", princetonian.sniff, princetonian.convert),
        ("ipuz", ipuz.sniff, ipuz.convert),
        ("ccxml", ccxml.sniff, ccxml.convert),
        ("ccjson", ccjson.sniff, ccjson.convert),
        ("puz", puz.sniff, puz.convert),
    ]


def _plugins() -> list[Entry]:
    out: list[Entry] = []
    for ep in sorted(importlib.metadata.entry_points(group=PLUGIN_GROUP), key=lambda e: e.name):
        where = f"converter plugin {ep.name!r} ({ep.value})"
        try:
            obj = ep.load()
        except Exception as e:
            raise PluginError(f"{where} failed to load: {type(e).__name__}: {e}") from e
        if isinstance(obj, tuple):
            if len(obj) != 3:
                raise PluginError(f"{where} is a tuple of {len(obj)}, not (name, sniff, convert)")
            name, sniff, fn = obj
        else:
            name = getattr(obj, "name", None) or ep.name
            sniff, fn = getattr(obj, "sniff", None), getattr(obj, "convert", None)
        if not isinstance(name, str) or not callable(sniff) or not callable(fn):
            raise PluginError(f"{where} needs a name, a callable sniff and a callable convert")
        out.append((name, sniff, fn))
    return out


_CONVERTERS: list[Entry] | None = None


def converters() -> list[Entry]:
    """(name, sniff, convert) for every converter, plugins first."""
    global _CONVERTERS
    if _CONVERTERS is None:
        _CONVERTERS = _plugins() + _builtins()
    return _CONVERTERS


def _sniff(name: str, sniff: Sniff, data: bytes) -> bool:
    try:
        return bool(sniff(data))
    except Exception as e:  # only a plugin's sniff can get here; say whose
        raise PluginError(f"converter {name!r}: sniff failed: {type(e).__name__}: {e}") from e


def _blame(e: Exception, name: str) -> None:
    if getattr(e, "fmt", None) is None:
        with contextlib.suppress(AttributeError, TypeError):  # an exception that takes no attributes
            setattr(e, "fmt", name)  # noqa: B010


def format_of(e: BaseException) -> str | None:
    """The name of the converter an exception raised by convert() came out of. Converters can
    fail in ways they don't foresee on a damaged file (a KeyError, say); those exceptions are
    passed on as they are, with the name attached the same way as to a ConvertError."""
    fmt = getattr(e, "fmt", None)
    return fmt if isinstance(fmt, str) else None


def detect(data: bytes) -> str:
    """The name of the first converter whose sniff accepts the data."""
    for name, sniff, _ in converters():
        if _sniff(name, sniff, data):
            return name
    raise UnknownFormat("no converter recognises this file")


def convert(data: bytes, ctx: Context | None = None, fmt: str | None = None) -> tuple[str, Puzzle]:
    """Return (format name, puzzle). `fmt` names the converter to use instead of sniffing."""
    ctx = ctx or Context()
    for name, sniff, fn in converters():
        if (fmt and name == fmt) or (not fmt and _sniff(name, sniff, data)):
            try:
                puzzle = fn(data, ctx)
            except Exception as e:
                _blame(e, name)
                raise
            if puzzle is not None:
                return name, puzzle
    raise UnknownFormat(f"no converter for {fmt!r}" if fmt else "no converter recognises this file")
