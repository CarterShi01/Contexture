"""Small validating coercions shared by the protocol-facing descriptors."""

from __future__ import annotations

from typing import Any

from .errors import ModelValidationError


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelValidationError(
            f"Expected a string, received {type(value).__name__}."
        )
    return value


def optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ModelValidationError(
            f"Expected a boolean, received {type(value).__name__}."
        )
    return value
