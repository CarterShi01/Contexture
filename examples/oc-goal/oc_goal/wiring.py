"""Hand each citizen the store it declared but does not implement.

`Area`, `Goal` and `Focus` say *that* their truth is in a database and nothing
about which one — the criterion their store class states is "is the truth in
the repo? no → declare the contract, inject the implementation". This module is
the injection, and it is the only place the model layer and the sqlite layer
meet.

It binds and nothing more. No connection is opened, no table is created, no row
is read: `db.connect` runs the first time something actually asks for rows. So
importing this package stays free, which matters because `contexture serve`
imports it to find the role.
"""
from __future__ import annotations

from .citizens import StoreError
from .db import ObjectRows
from .goal.model import Area, Focus, Goal

_BOUND = False


def bind_stores(path: str | None = None) -> None:
    """Bind the three tables. Idempotent, so importing twice is harmless."""

    global _BOUND
    Area.__store__.bind(ObjectRows("area", path=path))
    Goal.__store__.bind(ObjectRows("goal", path=path))
    Focus.__store__.bind(ObjectRows("focus", path=path))
    _BOUND = True


def bound() -> bool:
    return _BOUND


def require_bound() -> None:
    if not _BOUND:
        raise StoreError("stores are not bound; call oc_goal.wiring.bind_stores()")


__all__ = ["bind_stores", "bound", "require_bound"]
