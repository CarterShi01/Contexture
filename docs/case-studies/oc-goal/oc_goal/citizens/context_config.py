"""The persisted half of a citizen's context configuration.

One-creator's `domain/context.py` holds two things that change for different
reasons, and this demo needs one of them now:

    **data**      what a Goal row stores in its `context` column — which memory
                  scopes it may reach, what it inherits, which extra refs it
                  names. Persisted, versioned, edited under CAS. That is here.

    **compiler**  ContextSource / ContextSink / ContextInventory / ContextPack
                  and `compile_context`, which turn one Goal *instance* plus a
                  receiver and a budget into a trimmed pack. That is the piece
                  Contexture has no equivalent for, and it arrives in Phase 2.

The split is not arbitrary: the data half is a field on a citizen and belongs
with the citizen, while the compiler half is a second disclosure level that has
to be designed against Contexture's own, not ported blindly into it.

Copied verbatim from `domain/context.py`; the only change is dropping the
imports the compiler half needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .field import Field, field, item


CONTEXT_CONFIG_VERSION = 1
_SESSION_POLICIES = frozenset({"current", "none"})
_MEMORY_SCOPES = frozenset({"principal", "project"})
_EXTERNAL_POLICIES = frozenset({"none", "explicit-refs"})
_INHERITANCE = frozenset({"project", "goals", "workitem"})


class ContextContractError(ValueError):
    """A context declaration or instance configuration violates the contract."""

def _tuple(value):
    return tuple(value or ())

def _unique(values, label):
    items = tuple(values)
    if len(set(items)) != len(items):
        raise ContextContractError("%s contains duplicate values" % label)
    return items

def _mapping(value, label):
    if not isinstance(value, Mapping):
        raise ContextContractError("%s must be an object" % label)
    return dict(value)

def _keys(value, *, required, optional=(), label):
    data = _mapping(value, label)
    missing = sorted(set(required) - set(data))
    unknown = sorted(set(data) - set(required) - set(optional))
    if missing:
        raise ContextContractError("%s is missing keys: %s" % (label, missing))
    if unknown:
        raise ContextContractError("%s has unknown keys: %s" % (label, unknown))
    return data

@dataclass(frozen=True)
class ContextEnvironmentConfig:
    """Persist the environment capabilities an object may request or narrow."""

    session_policy: str = "current"
    memory_scopes: tuple[str, ...] = ()
    desk_policy: str = "none"
    notebook_policy: str = "none"
    inheritance: tuple[str, ...] = ()
    explicit_refs: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "memory_scopes",
                           _unique(self.memory_scopes, "memory_scopes"))
        object.__setattr__(self, "inheritance",
                           _unique(self.inheritance, "inheritance"))
        object.__setattr__(self, "explicit_refs",
                           _unique(self.explicit_refs, "explicit_refs"))
        if self.session_policy not in _SESSION_POLICIES:
            raise ContextContractError("unknown session policy: %s" % self.session_policy)
        if set(self.memory_scopes) - _MEMORY_SCOPES:
            raise ContextContractError("unknown memory scopes: %s" %
                                       sorted(set(self.memory_scopes) - _MEMORY_SCOPES))
        if self.desk_policy not in _EXTERNAL_POLICIES:
            raise ContextContractError("unknown desk policy: %s" % self.desk_policy)
        if self.notebook_policy not in _EXTERNAL_POLICIES:
            raise ContextContractError("unknown notebook policy: %s" % self.notebook_policy)
        if set(self.inheritance) - _INHERITANCE:
            raise ContextContractError("unknown inheritance values: %s" %
                                       sorted(set(self.inheritance) - _INHERITANCE))
        for ref in self.explicit_refs:
            _validate_ref(ref, "explicit_refs")

    @classmethod
    def from_mapping(cls, raw):
        data = _keys(raw, required=("session_policy", "memory_scopes", "desk_policy",
                                    "notebook_policy", "inheritance", "explicit_refs"),
                     label="context.environment")
        return cls(session_policy=data["session_policy"],
                   memory_scopes=_tuple(data["memory_scopes"]),
                   desk_policy=data["desk_policy"],
                   notebook_policy=data["notebook_policy"],
                   inheritance=_tuple(data["inheritance"]),
                   explicit_refs=_tuple(data["explicit_refs"]))

    def to_dict(self):
        return {
            "session_policy": self.session_policy,
            "memory_scopes": list(self.memory_scopes),
            "desk_policy": self.desk_policy,
            "notebook_policy": self.notebook_policy,
            "inheritance": list(self.inheritance),
            "explicit_refs": list(self.explicit_refs),
        }

@dataclass(frozen=True)
class ContextConfig:
    """Persist instance-specific bindings and narrowing rules with the host."""

    version: int
    environment: ContextEnvironmentConfig
    sources: tuple[Mapping[str, Any], ...] = ()
    sinks: tuple[Mapping[str, Any], ...] = ()
    channels: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self):
        if self.version != CONTEXT_CONFIG_VERSION:
            raise ContextContractError("unsupported context config version: %s" % self.version)
        for name in ("sources", "sinks", "channels"):
            rows = tuple(dict(item) for item in getattr(self, name))
            object.__setattr__(self, name, rows)
            _validate_bindings(rows, name)

    @classmethod
    def from_mapping(cls, raw, *, host_kind=None):
        data = _keys(raw, required=("version", "environment", "sources", "sinks", "channels"),
                     label="context")
        config = cls(version=data["version"],
                     environment=ContextEnvironmentConfig.from_mapping(data["environment"]),
                     sources=_tuple(data["sources"]), sinks=_tuple(data["sinks"]),
                     channels=_tuple(data["channels"]))
        config.validate_host(host_kind)
        return config

    def validate_host(self, host_kind):
        if host_kind == "goal" and "workitem" in self.environment.inheritance:
            raise ContextContractError("Goal context cannot inherit WorkItem context")
        allowed = {"goal": {"project"}, "project": {"goals"},
                   "workitem": {"project", "goals"}}.get(host_kind)
        if allowed is not None:
            extra = set(self.environment.inheritance) - allowed
            if extra:
                raise ContextContractError("%s context cannot inherit: %s" %
                                           (host_kind, sorted(extra)))
        return self

    def to_dict(self):
        return {"version": self.version, "environment": self.environment.to_dict(),
                "sources": [dict(item) for item in self.sources],
                "sinks": [dict(item) for item in self.sinks],
                "channels": [dict(item) for item in self.channels]}

def default_context_config(*, memory_scopes=(), desk_policy="none",
                           notebook_policy="none", inheritance=(), explicit_refs=()):
    """Build the persisted default without copying type-level inventory rules."""
    return ContextConfig(
        version=CONTEXT_CONFIG_VERSION,
        environment=ContextEnvironmentConfig(
            session_policy="current", memory_scopes=tuple(memory_scopes),
            desk_policy=desk_policy, notebook_policy=notebook_policy,
            inheritance=tuple(inheritance), explicit_refs=tuple(explicit_refs)),
        sources=(), sinks=(), channels=()).to_dict()

def context_config_field(*, factory=None, server_managed=False):
    """Return the strict nested Field used by context-enabled citizens."""
    environment = field(annotation=dict, shape={
        "session_policy": field(annotation=str, choices=tuple(sorted(_SESSION_POLICIES))),
        "memory_scopes": field(annotation=list, uniqueitems=True,
                               item=item(annotation=str, choices=tuple(sorted(_MEMORY_SCOPES)))),
        "desk_policy": field(annotation=str, choices=tuple(sorted(_EXTERNAL_POLICIES))),
        "notebook_policy": field(annotation=str, choices=tuple(sorted(_EXTERNAL_POLICIES))),
        "inheritance": field(annotation=list, uniqueitems=True,
                             item=item(annotation=str, choices=tuple(sorted(_INHERITANCE)))),
        "explicit_refs": field(annotation=list, uniqueitems=True,
                               item=item(annotation=str, minlen=1)),
    }, required=("session_policy", "memory_scopes", "desk_policy", "notebook_policy",
                 "inheritance", "explicit_refs"))
    binding = item(annotation=dict, shape={
        "id": field(annotation=str, pattern=r"^[a-z][a-z0-9_-]*$"),
        "kind": field(annotation=str, pattern=r"^[a-z][a-z0-9_-]*$"),
        "ref": field(annotation=str | None, minlen=1),
        "operation": field(annotation=str | None, pattern=r"^[a-z][a-z0-9_]*$"),
        "required": field(annotation=bool | None),
        "disabled": field(annotation=bool | None),
        "audience": field(annotation=list | None, uniqueitems=True,
                          item=item(annotation=str, choices=("user", "assistant"))),
        "budget": field(annotation=int | None, minimum=0),
    }, required=("id", "kind"))
    return Field(factory=factory or default_context_config, annotation=dict,
                 server_managed=server_managed, shape={
        "version": field(annotation=int, choices=(CONTEXT_CONFIG_VERSION,)),
        "environment": environment,
        "sources": field(annotation=list, item=binding),
        "sinks": field(annotation=list, item=binding),
        "channels": field(annotation=list, item=binding),
    }, required=("version", "environment", "sources", "sinks", "channels"))

def _validate_bindings(rows, label):
    ids = []
    for index, raw in enumerate(rows):
        data = _keys(raw, required=("id", "kind"),
                     optional=("ref", "operation", "required", "disabled",
                               "audience", "budget"), label="context.%s[%d]" % (label, index))
        _validate_token(data["id"], "%s id" % label)
        _validate_token(data["kind"], "%s kind" % label)
        ids.append(data["id"])
        if data.get("ref") is not None:
            _validate_ref(data["ref"], "%s ref" % label)
        if data.get("operation") is not None:
            _validate_token(data["operation"], "%s operation" % label)
        if data.get("required") and data.get("disabled"):
            raise ContextContractError("required %s binding cannot be disabled" % label)
        if data.get("budget") is not None and data["budget"] < 0:
            raise ContextContractError("%s budget must be non-negative" % label)
    _unique(ids, "context.%s ids" % label)

def _validate_token(value, label):
    import re
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
        raise ContextContractError("%s must be a token: %r" % (label, value))

def _validate_ref(value, label):
    import os
    from urllib.parse import urlparse
    if not isinstance(value, str) or not value:
        raise ContextContractError("%s must be a non-empty ref" % label)
    if os.path.isabs(value) or value.startswith(("./", "../")):
        raise ContextContractError("%s cannot contain a physical path" % label)
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise ContextContractError("%s must be a stable URI" % label)

__all__ = [
    "CONTEXT_CONFIG_VERSION",
    "ContextConfig",
    "ContextContractError",
    "ContextEnvironmentConfig",
    "context_config_field",
    "default_context_config",
]
