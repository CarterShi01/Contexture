"""Shared type aliases."""

from __future__ import annotations

from typing import Any, TypeAlias

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
CompiledContext: TypeAlias = dict[str, Any]
RequestId: TypeAlias = str | int
