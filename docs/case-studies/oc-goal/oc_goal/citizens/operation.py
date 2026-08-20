"""Typed contract for a first-class citizen's operations.

`OperationSpec` is the single description of one operation: Manager dispatch,
Citizen post-write validation, manifest generation and MCP reflection all read
the same object rather than assembling loose ``__dunder__`` attributes.
"""
import shlex
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidatorSpec:
    """An in-repo validation command that must exist and must succeed."""

    name: str
    argv: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "argv", tuple(self.argv))
        if not self.name or not self.argv:
            raise ValueError("ValidatorSpec 必须有 name 与 argv")
        if any(not isinstance(item, str) or not item for item in self.argv):
            raise TypeError("ValidatorSpec.argv 必须是非空字符串")

    def command(self):
        return "python3 " + shlex.join(self.argv)


@dataclass(frozen=True)
class Precondition:
    """A condition that must hold before a write. CAS (optimistic locking) is the
    only kind today.

    `field` is the instance field compared (`revision`); `param` is the signature
    parameter carrying the expectation (`expected_revision`). They are separate
    because they should *not* share a name: the parameter is the version the
    caller believes, the field is the actual version, and one name for both hides
    the direction.
    """

    kind: str
    field: str
    param: str

    def __post_init__(self):
        if self.kind != "cas":
            raise ValueError("目前只支持 cas 前置,收到:%s" % self.kind)
        if not self.field or not self.param:
            raise ValueError("Precondition 必须有 field 与 param")


def cas(field="revision", param=None):
    """Optimistic lock: `field`'s current value must equal the caller's `param`."""
    return Precondition("cas", field, param or ("expected_%s" % field))


# The write family: all of these change truth, so all may carry
# target/validators/writes/approval/precondition. `read` and `compile` are not in
# the family and are rejected if they declare a write contract.
WRITE_KINDS = ("write", "transition", "append", "document", "amend")


@dataclass(frozen=True)
class OperationSpec:
    """The static contract of a Manager method."""

    kind: str
    target: type | None = None
    patch_fields: tuple[str, ...] = ()
    approval: type | None = None
    validators: tuple[ValidatorSpec, ...] = ()
    writes: tuple[str, ...] = ()
    status: str = "implemented"
    precondition: "Precondition | None" = None
    # transition only: which field changes, to what, from which states (empty = any)
    state_field: str | None = None
    to_state: str | None = None
    from_states: tuple[str, ...] = ()
    # Fields written with the state in the same CAS replacement. Only
    # `transition_only` is accepted: these are this transition's evidence, not
    # data changed along the way. See `manager.transition`.
    sets: tuple[str, ...] = ()
    # append only: which array field to append to, which keys dedupe on (empty = none)
    into: str | None = None
    identity: tuple[str, ...] = ()
    # Which parameter holds the entries. Empty means the signature's single extra parameter.
    entries_param: str | None = None
    # amend only: which parameter holds the selection, which element keys may change.
    select_param: str | None = None
    amend_keys: tuple[str, ...] = ()
    # write only: upsert (default) | create (create-only, with an idempotency key)
    mode: str = "upsert"
    idempotency_param: str | None = None
    # Fields compared to decide "same request replayed". Empty = no idempotency;
    # any collision is a ConflictError.
    idempotent_on: tuple[str, ...] = ()
    # Who decides the primary key: given = the caller (a slug), derived = the
    # system (`wi_<hex>`). Under derived the signature has no key parameter —
    # asking a caller for a value it cannot compute only yields a fake parameter.
    key_source: str = "given"
    # Host-injected parameters, kept off the tool surface: caller identity,
    # request context, provenance. They are in the signature but reflection
    # generates no parameter — a caller-chosen `created_by_ref` would let anyone
    # create work on someone else's behalf, and owner is the root of every later
    # filter.
    injected: tuple[str, ...] = ()
    # Three visibilities on the hand surface, shared by the write family:
    #   tool     registered as a tool and in the L3 disclosure bundle (default)
    #   hidden   registered as a tool but not in L3 — available, not advertised
    #   internal implementation-layer only; reflection registers no tool
    # `internal` exists for the shape where one hand-written façade dispatches to
    # two typed writes: surfacing both would give the hand's LLM two verbs for one
    # thing, which is exactly the entropy being suppressed.
    exposure: str = "tool"

    def __post_init__(self):
        object.__setattr__(self, "patch_fields", tuple(self.patch_fields))
        object.__setattr__(self, "validators", tuple(self.validators))
        object.__setattr__(self, "writes", tuple(self.writes))
        object.__setattr__(self, "from_states", tuple(self.from_states))
        object.__setattr__(self, "sets", tuple(self.sets))
        object.__setattr__(self, "idempotent_on", tuple(self.idempotent_on))
        object.__setattr__(self, "injected", tuple(self.injected))
        object.__setattr__(self, "amend_keys", tuple(self.amend_keys))
        object.__setattr__(self, "identity", tuple(self.identity))
        if self.kind not in ("read", "compile", *WRITE_KINDS):
            raise ValueError("未知 operation kind:%s" % self.kind)
        if self.status not in ("implemented", "planned", "deprecated"):
            raise ValueError("未知 operation status:%s" % self.status)
        if self.exposure not in ("tool", "hidden", "internal"):
            raise ValueError("未知 operation exposure:%s" % self.exposure)
        if self.exposure != "tool" and self.kind not in WRITE_KINDS:
            raise ValueError("exposure 只对写族有意义 —— 读面的暴露由 @read(visibility=) 管")
        if any(not isinstance(item, str) or not item for item in (*self.patch_fields, *self.writes)):
            raise TypeError("patch_fields/writes 必须是非空字符串")
        if len(set(self.patch_fields)) != len(self.patch_fields):
            raise ValueError("patch_fields 不得重复")

        writing = self.kind in WRITE_KINDS
        if writing and self.target is None:
            raise ValueError("%s operation 必须声明 target" % self.kind)
        if not writing and any(
                (self.target, self.patch_fields, self.approval, self.validators,
                 self.writes, self.precondition)):
            raise ValueError("只有写族 operation 可以声明写契约")
        if any(not isinstance(item, ValidatorSpec) for item in self.validators):
            raise TypeError("validators 必须是 ValidatorSpec")
        if self.precondition is not None and not isinstance(self.precondition, Precondition):
            raise TypeError("precondition 必须是 Precondition")

        # ── Per-kind required fields ──────────────────────────────────────
        if self.kind == "transition":
            if not (self.state_field and self.to_state):
                raise ValueError("transition 必须声明 state_field 与 to_state")
            if self.patch_fields:
                raise ValueError("transition 不改普通字段 —— 要改就拆成两个操作")
            if len(set(self.sets)) != len(self.sets):
                raise ValueError("sets 不得重复")
            if self.state_field in self.sets:
                raise ValueError("state_field 已经由 to= 决定,不该再出现在 sets 里")
        elif self.sets:
            raise ValueError("sets 只对 kind=transition 有意义")
        if self.kind == "append":
            if not self.into:
                raise ValueError("append 必须声明 into(追加进哪个数组字段)")
            if self.patch_fields:
                raise ValueError("append 不改普通字段")
        if self.kind == "amend":
            if not self.into:
                raise ValueError("amend 必须声明 into(改哪个数组字段的元素)")
            if not self.select_param:
                raise ValueError("amend 必须声明 select(哪个参数装着「选中哪几条」)")
            if not self.amend_keys:
                raise ValueError("amend 必须声明 sets(允许改元素的哪几个键)—— "
                                 "不声明就等于开放整条改写,而那正是 append-only 要防的")
            if self.patch_fields:
                raise ValueError("amend 不改公民自己的字段,只改数组元素的键")
        elif self.select_param or self.amend_keys:
            raise ValueError("select/sets(元素键)只对 kind=amend 有意义")
        if self.kind == "document":
            if not self.patch_fields:
                raise ValueError("document 必须声明 fields(要 patch 哪几个字段)")
            if self.precondition is not None:
                raise ValueError("document 暂不支持 CAS —— 单例没有 revision 字段的先例,"
                                 "要加就先给目标文档长一个 server_managed 计数器")
        if self.kind == "write":
            if self.mode not in ("upsert", "create"):
                raise ValueError("未知 write mode:%s" % self.mode)
            if self.mode != "create" and (self.idempotency_param or self.idempotent_on):
                raise ValueError("idempotency_param / idempotent_on 只对 mode=create 有意义")
            if self.key_source not in ("given", "derived"):
                raise ValueError("未知 key_source:%s" % self.key_source)
            if self.key_source == "derived" and self.mode != "create":
                raise ValueError("key_source=derived 只对 mode=create 有意义 —— "
                                 "改一条既有记录当然得说改哪条")
            if self.idempotent_on and not self.idempotency_param:
                raise ValueError("声明了 idempotent_on 就必须有 idempotency_param —— "
                                 "没有幂等键,「重放」这件事无从谈起")
            if set(self.injected) & set(self.patch_fields):
                raise ValueError("injected 与 fields 不得重叠 —— 一个参数要么是宿主注入的,"
                                 "要么是调用方给的字段,不能两者都是")
        elif self.mode != "upsert" or self.idempotency_param or self.idempotent_on:
            raise ValueError("mode/idempotency_param/idempotent_on 只对 kind=write 有意义")

    # ── For reflection ────────────────────────────────────────────────────
    @property
    def command_exposure(self):
        """The manifest's `command_exposure`. Only `tool` reaches L3."""
        return "l3" if self.exposure == "tool" else "hidden"

    @property
    def writes_truth(self):
        return self.kind in WRITE_KINDS

    @property
    def manifest_kind(self):
        """The manifest's `kind` field, one notch finer than OperationSpec.kind, using
        the manifest vocabulary (`upsert` / `create` / `cas-update` /
        `terminal-<state>` / `append-<into>`).
        """
        if self.kind == "write":
            if self.mode == "create":
                return "create"
            return "cas-update" if self.precondition else "upsert"
        if self.kind == "transition":
            return "terminal-%s" % self.to_state
        if self.kind == "append":
            return "append-%s" % self.into
        if self.kind == "amend":
            if not self.into:
                raise ValueError("amend 必须声明 into(改哪个数组字段的元素)")
            if not self.select_param:
                raise ValueError("amend 必须声明 select(哪个参数装着「选中哪几条」)")
            if not self.amend_keys:
                raise ValueError("amend 必须声明 sets(允许改元素的哪几个键)—— "
                                 "不声明就等于开放整条改写,而那正是 append-only 要防的")
            if self.patch_fields:
                raise ValueError("amend 不改公民自己的字段,只改数组元素的键")
        elif self.select_param or self.amend_keys:
            raise ValueError("select/sets(元素键)只对 kind=amend 有意义")
        if self.kind == "document":
            return "patch"
        if self.kind == "amend":
            return "amend-%s" % self.into
        return self.kind


_CURRENT = ContextVar("domain_current_operation", default=None)


def current_operation():
    """The operation `Manager.invoke()` is currently executing, or None."""
    return _CURRENT.get()


@contextmanager
def operation_context(spec):
    token = _CURRENT.set(spec)
    try:
        yield spec
    finally:
        _CURRENT.reset(token)


__all__ = ["OperationSpec", "Precondition", "ValidatorSpec", "WRITE_KINDS",
           "cas", "current_operation", "operation_context"]
