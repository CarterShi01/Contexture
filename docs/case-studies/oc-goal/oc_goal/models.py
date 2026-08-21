"""Goal-domain values and their validation rules.

The domain model is deliberately ordinary Pydantic.  Contexture derives tool
schemas from the same annotations, so field constraints have one source and
there is no second reflection framework inside the application.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9._-]{0,30}[a-z0-9])?$"
HORIZON_PATTERN = r"^(\d{4}-Q[1-4]|\d{4}-\d{2}-\d{2})$"
TOKEN_PATTERN = r"^[a-z][a-z0-9_-]*$"
OWNER_PATTERN = r"^principal://[a-z][a-z0-9-]*$"

Slug = Annotated[str, Field(pattern=SLUG_PATTERN)]
Title = Annotated[str, Field(min_length=1, max_length=30)]
Why = Annotated[str, Field(min_length=10, max_length=500)]
Standard = Annotated[str, Field(min_length=5, max_length=300)]
Horizon = Annotated[str, Field(pattern=HORIZON_PATTERN)]
Criterion = Annotated[str, Field(min_length=5, max_length=200)]
FocusItem = Annotated[str, Field(min_length=1, max_length=200)]
ObjectName = Annotated[str, Field(pattern=r"^[A-Z][A-Za-z]{1,30}$")]
Criteria = Annotated[list[Criterion], Field(min_length=1)]
ObjectNames = Annotated[list[ObjectName], Field(min_length=1, max_length=12)]
Revision = Annotated[int, Field(ge=1)]
Budget = Annotated[int, Field(ge=0, le=100)]
Token = Annotated[str, Field(pattern=TOKEN_PATTERN)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class DomainValue(BaseModel):
    """Strict base for persisted values and tool argument objects."""

    model_config = ConfigDict(extra="forbid")


class ContextEnvironment(DomainValue):
    """External context a goal is allowed to request from its host."""

    session_policy: Literal["current", "none"] = "current"
    memory_scopes: list[Literal["principal", "project"]] = Field(
        default_factory=list
    )
    desk_policy: Literal["none", "explicit-refs"] = "none"
    notebook_policy: Literal["none", "explicit-refs"] = "none"
    inheritance: list[Literal["project", "goals", "workitem"]] = Field(
        default_factory=list
    )
    explicit_refs: list[str] = Field(default_factory=list)

    @field_validator("memory_scopes", "inheritance", "explicit_refs")
    @classmethod
    def unique_items(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("context lists cannot contain duplicate values")
        return values

    @field_validator("explicit_refs")
    @classmethod
    def stable_refs(cls, values: list[str]) -> list[str]:
        for value in values:
            _require_stable_uri(value)
        return values


class ContextBinding(DomainValue):
    """One persisted source, sink, or channel binding."""

    id: Token
    kind: Token
    ref: str | None = None
    operation: Token | None = None
    required: bool | None = None
    disabled: bool | None = None
    audience: list[Literal["user", "assistant"]] | None = None
    budget: NonNegativeInt | None = None

    @field_validator("ref")
    @classmethod
    def stable_ref(cls, value: str | None) -> str | None:
        if value is not None:
            _require_stable_uri(value)
        return value

    @field_validator("audience")
    @classmethod
    def unique_audience(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("binding audience cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def required_binding_is_enabled(self) -> "ContextBinding":
        if self.required and self.disabled:
            raise ValueError("a required context binding cannot be disabled")
        return self


class ContextConfig(DomainValue):
    """Persisted context policy for one Goal.

    This is the data contract only.  Compiling a receiver-specific context pack
    belongs to the host/application boundary and is intentionally not copied
    into this module.
    """

    version: Literal[1] = 1
    environment: ContextEnvironment = Field(default_factory=ContextEnvironment)
    sources: list[ContextBinding] = Field(default_factory=list)
    sinks: list[ContextBinding] = Field(default_factory=list)
    channels: list[ContextBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def goal_policy(self) -> "ContextConfig":
        unsupported = set(self.environment.inheritance) - {"project"}
        if unsupported:
            raise ValueError(
                f"Goal context cannot inherit: {sorted(unsupported)}"
            )
        for label in ("sources", "sinks", "channels"):
            ids = [binding.id for binding in getattr(self, label)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"context.{label} contains duplicate ids")
        return self


def default_goal_context() -> ContextConfig:
    """The context policy assigned to a newly created Goal."""

    return ContextConfig(
        environment=ContextEnvironment(
            memory_scopes=["project"],
            inheritance=["project"],
        )
    )


class ManagedValue(DomainValue):
    """Fields assigned by the write boundary, never by a tool caller."""

    owner_ref: Annotated[str, Field(pattern=OWNER_PATTERN)]
    revision: Revision
    created_at: str
    updated_at: str


class Area(ManagedValue):
    """Attention that never ends and therefore owns budget and a standard."""

    slug: Slug
    title: Title
    why: Why
    budget: Budget = 0
    standard: Standard = "TODO(founder): define what healthy means"
    status: Literal["active", "paused", "archived"] = "paused"
    objects: ObjectNames = Field(default_factory=lambda: ["Note"])


class Goal(ManagedValue):
    """A finite outcome with a horizon and observable success criteria."""

    slug: Slug
    area: Slug
    title: Title
    why: Why
    horizon: Horizon = "2099-Q4"
    success: Criteria = Field(
        default_factory=lambda: ["TODO(founder): define what success means"]
    )
    status: Literal["active", "done", "dropped"] = "active"
    context: ContextConfig = Field(default_factory=default_goal_context)


class Focus(ManagedValue):
    """The single current attention declaration."""

    main_thread: FocusItem
    week_top: list[FocusItem] = Field(default_factory=list)
    not_doing: list[FocusItem] = Field(default_factory=list)


def _require_stable_uri(value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("context ref must be a non-empty URI")
    if os.path.isabs(value) or value.startswith(("./", "../")):
        raise ValueError("context ref cannot contain a physical path")
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("context ref must be a stable URI")


__all__ = [
    "Area",
    "Budget",
    "ContextBinding",
    "ContextConfig",
    "ContextEnvironment",
    "Criteria",
    "Criterion",
    "FocusItem",
    "Focus",
    "Goal",
    "Horizon",
    "ObjectName",
    "ObjectNames",
    "Revision",
    "Slug",
    "Standard",
    "Title",
    "Why",
    "default_goal_context",
]
