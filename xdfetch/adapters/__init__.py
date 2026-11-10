"""Adapters by name: xdfetch's own, then those other packages add.

`get(name)` looks in ADAPTERS (the built-ins) first, then in the entry-point group
`xdfetch.adapters`, where the entry point's name is the adapter's name and its object is
the Adapter subclass:

    [project.entry-points."xdfetch.adapters"]
    mysite = "mypackage.adapters:MySiteAdapter"

A built-in name can't be taken over by a plugin. Entry points are looked up on each call,
so nothing is imported until an adapter is asked for.
"""

from __future__ import annotations

from importlib import metadata

from .amuse import AmuseAdapter
from .base import Adapter, Fetched, MissingSecret, Target
from .conde import CondeAdapter
from .nyt import NytAdapter
from .page import PageAdapter
from .princetonian import PrincetonianAdapter
from .url import UrlAdapter

ENTRY_POINT_GROUP = "xdfetch.adapters"

ADAPTERS: dict[str, type[Adapter]] = {
    UrlAdapter.name: UrlAdapter,
    NytAdapter.name: NytAdapter,
    CondeAdapter.name: CondeAdapter,
    PageAdapter.name: PageAdapter,
    PrincetonianAdapter.name: PrincetonianAdapter,
    AmuseAdapter.name: AmuseAdapter,
}


class AdapterError(KeyError):
    """No adapter by that name, or a plugin that can't be loaded. A KeyError, as a missing name always was."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


def plugin_names() -> list[str]:
    """Names of the adapters installed packages add (not loaded)."""
    return sorted({ep.name for ep in metadata.entry_points(group=ENTRY_POINT_GROUP)} - set(ADAPTERS))


def get(name: str) -> type[Adapter]:
    if name in ADAPTERS:
        return ADAPTERS[name]
    eps = [ep for ep in metadata.entry_points(group=ENTRY_POINT_GROUP) if ep.name == name]
    if not eps:
        known = ", ".join(sorted(ADAPTERS)) + "".join(f", {n} (plugin)" for n in plugin_names())
        raise AdapterError(
            f"no adapter named {name!r}: not built in, and no installed package provides it "
            f"(entry point group {ENTRY_POINT_GROUP}); known: {known}"
        )
    if len({ep.value for ep in eps}) > 1:
        raise AdapterError(
            f"adapter {name!r} is provided by more than one installed package: {', '.join(ep.value for ep in eps)}"
        )
    ep = eps[0]
    where = f"adapter plugin {name!r} ({ep.value})"
    try:
        cls = ep.load()
    except Exception as e:
        raise AdapterError(f"{where} failed to load: {e.__class__.__name__}: {e}") from e
    if not (isinstance(cls, type) and issubclass(cls, Adapter)):
        raise AdapterError(f"{where} is not an xdfetch.adapters.Adapter subclass")
    return cls


__all__ = ["ADAPTERS", "Adapter", "AdapterError", "Fetched", "MissingSecret", "Target", "get", "plugin_names"]
