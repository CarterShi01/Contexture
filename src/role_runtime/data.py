"""Data-source descriptors, role bindings, and provider interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Protocol

from .context import CompileLevel, ContextNode
from .errors import CapabilityDeniedError, ModelValidationError, NodeNotFoundError
from .types import CompiledContext, JsonObject


class DataAccess(str, Enum):
    """Access modes granted by a role-to-data binding."""

    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


class DataClassification(str, Enum):
    """A small host-side classification vocabulary."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass(slots=True, kw_only=True)
class DataSource(ContextNode):
    """A discoverable data descriptor whose content is loaded separately."""

    source_id: str
    uri: str
    provider_id: str
    media_type: str | None = None
    schema: JsonObject | None = None

    kind: ClassVar[str] = "data_source"

    def __post_init__(self) -> None:
        ContextNode.__post_init__(self)
        if not self.source_id.strip():
            raise ModelValidationError("Data source id must not be empty.")
        if not self.uri.strip():
            raise ModelValidationError(
                f"Data source {self.source_id!r} must have a URI."
            )
        if not self.provider_id.strip():
            raise ModelValidationError(
                f"Data source {self.source_id!r} must name a provider."
            )

    def _compile_active(self) -> CompiledContext:
        compiled: CompiledContext = {
            **self._compile_route(),
            "source_ref": self.source_id,
            "uri": self.uri,
            "provider_id": self.provider_id,
        }
        if self.media_type is not None:
            compiled["media_type"] = self.media_type
        if self.schema is not None:
            compiled["schema"] = self.schema
        return compiled


@dataclass(slots=True, kw_only=True)
class DataBinding:
    """A role-specific, least-privilege view of one data source."""

    source: DataSource
    access: DataAccess = DataAccess.READ
    classification: DataClassification = DataClassification.INTERNAL

    def can_read(self) -> bool:
        return self.access in {DataAccess.READ, DataAccess.READ_WRITE}

    def can_write(self) -> bool:
        return self.access in {DataAccess.WRITE, DataAccess.READ_WRITE}

    def require_read(self) -> None:
        if not self.can_read():
            raise CapabilityDeniedError(
                f"Data source {self.source.source_id!r} is not readable by this role."
            )

    def require_write(self) -> None:
        if not self.can_write():
            raise CapabilityDeniedError(
                f"Data source {self.source.source_id!r} is not writable by this role."
            )

    def compile_source(
        self,
        level: CompileLevel | str = CompileLevel.ROUTE,
    ) -> CompiledContext:
        return {
            **self.source.compile(level),
            "source_ref": self.source.source_id,
            "access": self.access.value,
            "classification": self.classification.value,
        }


@dataclass(slots=True, frozen=True, kw_only=True)
class DataReadResult:
    """Data returned by a provider after an authorized read."""

    content: Any
    media_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DataProvider(Protocol):
    """Runtime interface for loading and optionally writing data."""

    async def read(self, source: DataSource) -> DataReadResult:
        """Read the content addressed by the data source."""

    async def write(self, source: DataSource, value: Any) -> None:
        """Write content to the data source."""


@dataclass(slots=True)
class InMemoryDataProvider:
    """A deterministic provider used by examples and tests."""

    values: dict[str, Any] = field(default_factory=dict)

    async def read(self, source: DataSource) -> DataReadResult:
        if source.uri not in self.values:
            raise NodeNotFoundError(
                f"No in-memory value exists for URI {source.uri!r}."
            )
        return DataReadResult(
            content=self.values[source.uri],
            media_type=source.media_type,
            metadata={"uri": source.uri},
        )

    async def write(self, source: DataSource, value: Any) -> None:
        self.values[source.uri] = value
