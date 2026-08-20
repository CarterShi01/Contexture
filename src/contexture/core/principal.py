"""Who is calling, as a fact the whole package can stand on.

A capability that behaves differently for different callers needs one thing
from the framework and only one: **the identity the request arrived with**. It
does not need a permission model, a role table, or a policy language. Those
belong to whoever wrote the capability, because only they know what their
system considers allowed.

So this module holds the fact and stops there. `Principal` says who; nothing
here says what they may do.

**Why this sits on the shared ground rather than in a sub-layer.** Three
different places need it and no two of them are neighbours: a business tool
reads it while deciding what to do, `server` builds it from whatever arrived on
the wire, and anything later that wants to vary an answer by caller will read
it too. Shared ground is exactly the place a fact like that goes — everything
may stand on it, and it stands on nothing. Putting it in `model` would force
`server` to import the object model to learn who was calling; putting it in
`server` would put it above the code that reads it.

**Nothing here knows what OAuth is.** A `Principal` is five plain fields. That
they usually arrive from a bearer token is a fact about `server`, and it is
`server`'s alone: this layer would be unchanged if identity came from a client
certificate, a signed header, or a unit test constructing one by hand — which
is, in fact, how it should be constructed in a unit test.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterator, Mapping

#: Where the current request's identity lives.
#:
#: A context variable rather than an argument threaded through every call, for
#: the same reason the official SDK, FastMCP, and mcp-go all made this choice:
#: identity is a property of the *request*, not of any one function's
#: signature, and threading it would put a parameter on capabilities that have
#: no interest in who is calling. It is task-local, so concurrent requests in
#: one process never see each other's caller.
_CURRENT: ContextVar["Principal | None"] = ContextVar(
    "contexture_principal", default=None
)


@dataclass(slots=True, frozen=True, kw_only=True)
class Principal:
    """The identity one request arrived with.

    Frozen, because a caller is not something a capability gets to edit
    half-way through serving them.

    **Two identities, not one.** `client_id` is the application that connected
    — Claude Code, Codex, some internal agent — and `subject` is the person it
    is acting for. They are different questions with different answers, and
    code that conflates them writes audit records nobody can act on. Either may
    be absent: a machine-to-machine token has no person behind it, and a
    verifier that does not look up a subject simply does not supply one.

    ::

        who = current_principal()
        if who is None:
            raise PermissionError("This tool needs an authenticated caller.")
        if "k8s.write" not in who.scopes:
            raise PermissionError(f"{who.subject} may not write.")
    """

    #: The person the caller is acting for — RFC 7662/9068 `sub`. Unique only
    #: within `issuer`, so the pair is the identity, never the subject alone.
    subject: str | None = None

    #: The application that connected, as the token's audience knows it.
    client_id: str | None = None

    #: Who vouched for this identity. Two subjects from two issuers may collide
    #: on the same string and be different people.
    issuer: str | None = None

    #: The permissions the token asserts. A `frozenset` because membership is
    #: the only question ever asked of it, and because a caller must not be
    #: able to grant themselves one by appending to a list they were handed.
    scopes: frozenset[str] = frozenset()

    #: Everything else the verifier saw, unedited. The escape hatch for
    #: identity models this dataclass does not have fields for — tenant ids,
    #: group memberships, entitlements. Read-only for the same reason `scopes`
    #: is.
    claims: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        # Normalised so that what a verifier finds convenient to build with is
        # never what a capability has to defend against. A verifier may hand in
        # a list of scopes and a plain dict of claims; nothing downstream can
        # mutate either.
        object.__setattr__(self, "scopes", frozenset(self.scopes))
        if not isinstance(self.claims, MappingProxyType):
            object.__setattr__(self, "claims", MappingProxyType(dict(self.claims)))

    def __repr__(self) -> str:
        """Name the identity and nothing else.

        A `Principal` ends up in log records and exception messages, and
        `claims` routinely holds an entire decoded token. Rendering all of it
        by default is how a token's contents reach a log aggregator that was
        never meant to hold them.
        """

        return (
            f"Principal(subject={self.subject!r}, client_id={self.client_id!r}, "
            f"issuer={self.issuer!r}, scopes={sorted(self.scopes)!r})"
        )


def current_principal() -> Principal | None:
    """Return who is calling, or `None` if nobody authenticated.

    **`None` is a real answer, not an error.** Over stdio there is no token and
    there never will be: the host launched this process, and the operating
    system already decided who that is. A capability that needs an identity
    must say so itself, because only it knows whether running unauthenticated
    is a problem — and a framework that invented an "anonymous" principal to
    avoid the branch would be answering that question on its behalf, wrongly,
    and silently.
    """

    return _CURRENT.get()


@contextmanager
def bound(principal: Principal | None) -> Iterator[None]:
    """Serve one request as `principal`. For the `server` layer to call.

    Public because `server` is a different package, not because a business
    application has any reason to call it — with one exception that earns the
    name: a test for a capability that reads `current_principal()` binds one
    here rather than standing up a server to get one.

    Always reset, never merely set: a worker task that keeps its context alive
    after a request would otherwise serve the next caller as the last one.
    """

    token = _CURRENT.set(principal)
    try:
        yield
    finally:
        _CURRENT.reset(token)


__all__ = ["Principal", "bound", "current_principal"]
