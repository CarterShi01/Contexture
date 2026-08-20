"""What counts as a first-class citizen.

Ported from one-creator's `domain/`, which answers exactly one question: what
makes an object first-class rather than a dict somebody agreed to be careful
with. Four pieces, and this demo keeps all four:

    Citizen    instance type: fields, persistence, invariants, idempotent upsert
    Document   the singleton variant — one instance, no primary key
    Field      field modifiers: founder_only / transition_only / server_managed,
               maxlen / truncate, nonempty, derived, invariant
    schema     type annotations → JSON Schema

What is deliberately **not** here is `Manager` — one-creator's operation surface,
carrying `@read` / `@write` / `@compile` and the addresses they were published
at. Contexture's Role, Tool, Skill and Resource are that layer, so bringing it
along would mean running two of them.

The dependency rule the original states as a hard constraint is kept:

    contexture (facade)  →  nothing here
    oc_goal.goal         →  oc_goal.citizens  →  stdlib only
    oc_goal.db           →  oc_goal.citizens

Nothing in this package imports `contexture`, and nothing imports sqlite. A
citizen whose truth lives in a database says so with `InjectedStore` and is
handed an implementation at composition time; `oc_goal/db/` is that
implementation, and it depends on this package rather than the other way round.
"""
from . import schema
from .citizen import (
    KEY_RE,
    BrokenRef,
    Citizen,
    CitizenError,
    CitizenNotFound,
    ConflictError,
    InvariantError,
    registry as citizen_registry,
    run_script,
)
from .document import Document, registry as document_registry
from .field import (
    MISSING,
    Field,
    derived,
    field,
    founder_only,
    invariant,
    item,
    maxlen,
    nonempty,
    server_managed,
    transition_only,
    truncate,
)
from .context_config import (
    CONTEXT_CONFIG_VERSION,
    ContextConfig,
    ContextContractError,
    ContextEnvironmentConfig,
    context_config_field,
    default_context_config,
)
from .operation import (
    OperationSpec,
    ValidatorSpec,
    cas,
    current_operation,
    operation_context,
)
from .store import InjectedDocumentStore, InjectedStore, StoreError

__all__ = [
    "BrokenRef",
    "CONTEXT_CONFIG_VERSION",
    "ContextConfig",
    "ContextContractError",
    "ContextEnvironmentConfig",
    "Citizen",
    "CitizenError",
    "CitizenNotFound",
    "ConflictError",
    "Document",
    "Field",
    "InjectedDocumentStore",
    "InjectedStore",
    "InvariantError",
    "KEY_RE",
    "MISSING",
    "OperationSpec",
    "StoreError",
    "ValidatorSpec",
    "cas",
    "citizen_registry",
    "context_config_field",
    "current_operation",
    "default_context_config",
    "derived",
    "document_registry",
    "field",
    "founder_only",
    "invariant",
    "item",
    "maxlen",
    "nonempty",
    "operation_context",
    "run_script",
    "schema",
    "server_managed",
    "transition_only",
    "truncate",
]
