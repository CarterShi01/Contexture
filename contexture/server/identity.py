"""Where a caller's identity comes from, and what this server does about it.

This module is the whole of Contexture's involvement in authentication, and
the shape of it is deliberate:

    the framework   wires the protocol up correctly and hands the identity on
    the business    decides whether a token is genuine, and what it may do
    nobody here     issues tokens

**No verifier ships with this package.** Not even a convenient JWT one. A
built-in verifier would arrive with defaults, defaults get copied into
production, and a wrong default in OAuth is a vulnerability rather than a
nuisance. A verifier from whoever issues your tokens is better than one written
here, every time, so this module defines the socket and not the plug.

**No authorization server either.** The SDK can be made to issue tokens —
`OAuthAuthorizationServerProvider` — and this package deliberately does not
expose it. Running the login, the consent screen and the token endpoint is an
identity provider's job; a context server that also minted credentials would be
holding a responsibility it cannot discharge.

What is left is the part a business developer should not have to get right:
answering `401` with the pointer that lets a client find the authorization
server (RFC 9728), publishing the protected-resource metadata that pointer
leads to, and requiring that a token was issued *for this server* rather than
some other one (RFC 8707). Those are protocol facts with one correct answer,
which is exactly the kind of thing a framework owes its user — the same reason
`configure_logging` exists rather than every project remembering that stdio
owns stdout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.provider import TokenVerifier as SDKTokenVerifier
from mcp.server.auth.settings import AuthSettings

from ..core.errors import ModelValidationError
from ..core.principal import Principal


@runtime_checkable
class TokenVerifier(Protocol):
    """Decide whether a bearer token is genuine, and who it belongs to.

    One method, implemented by the business::

        class OktaVerifier:
            async def verify(self, token: str) -> Principal | None:
                claims = okta.decode(token, audience="https://mcp.acme.com/mcp")
                if claims is None:
                    return None
                return Principal(
                    subject=claims["sub"],
                    client_id=claims.get("azp"),
                    issuer=claims["iss"],
                    scopes=frozenset(claims.get("scope", "").split()),
                    claims=claims,
                )

    Note what the signature does **not** mention: `mcp`. A business writes
    against `Principal` and this protocol, and the SDK stays on this side of
    the boundary — which is the same claim the whole package rests on, applied
    to the one place where it would be easiest to give up.

    Returning `None` means "not a valid token" and becomes a `401` carrying the
    pointer a client needs to go and get a real one. Raising means something
    broke; that is a `500`, and it should stay one — an identity provider being
    unreachable is not the caller's fault and must not be reported as their
    credentials being bad.

    **Validate the audience.** A token issued for another service must be
    refused here, or this server becomes a way to spend somebody else's
    credentials (RFC 8707). No framework can check this for you: only your
    verifier knows what your `resource` is called at your issuer.
    """

    async def verify(self, token: str) -> Principal | None:
        """Return who the token belongs to, or `None` if it is not valid."""

        ...


@dataclass(slots=True, frozen=True, kw_only=True)
class Auth:
    """How this server checks who is calling.

    ::

        Auth(
            verifier=OktaVerifier(),
            issuer="https://acme.okta.com",
            resource="https://mcp.acme.com/mcp",
        )

    Three facts, and each is needed by somebody other than this process:
    `issuer` and `resource` are what a client is told when it arrives without a
    token, so that it can go and get one; `verifier` is what happens when it
    comes back with one.
    """

    #: The business's implementation. See `TokenVerifier`.
    verifier: TokenVerifier

    #: The authorization server that issues tokens for this resource. Published
    #: in the protected-resource metadata; this server never talks to it.
    issuer: str

    #: **This server's own name**, as the issuer knows it — the audience a
    #: token must be minted for. Usually the public URL of the MCP endpoint.
    #:
    #: Stated rather than derived from `host` and `port`, because behind a
    #: proxy or an ingress they are not the same string, and guessing wrong
    #: produces metadata that sends clients to ask for the wrong audience.
    resource: str

    #: Scopes required to reach the server at all, enforced before any MCP
    #: message is read. This is the door, not a policy: it answers "may you
    #: come in", never "may you do this". Per-capability decisions belong to
    #: the capability, which reads `current_principal()` and decides for
    #: itself.
    required_scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.verifier, TokenVerifier):
            raise ModelValidationError(
                f"{type(self.verifier).__name__} is not a TokenVerifier: it "
                "needs one method, `async def verify(self, token: str) -> "
                "Principal | None`."
            )
        for name in ("issuer", "resource"):
            if not str(getattr(self, name)).strip():
                raise ModelValidationError(
                    f"Auth needs a non-empty {name}; it is published in this "
                    "server's protected-resource metadata, and a client that "
                    "arrives without a token reads it to find out where to "
                    "get one."
                )

    def settings(self) -> AuthSettings:
        """Render as the SDK's own configuration object."""

        try:
            return AuthSettings(
                issuer_url=self.issuer,  # type: ignore[arg-type]
                resource_server_url=self.resource,  # type: ignore[arg-type]
                required_scopes=list(self.required_scopes) or None,
            )
        except ValueError as exc:
            raise ModelValidationError(
                f"Auth(issuer={self.issuer!r}, resource={self.resource!r}) is "
                f"not usable: {exc}. Both must be absolute http(s) URLs."
            ) from exc

    def sdk_verifier(self) -> SDKTokenVerifier:
        """Adapt the business's verifier to the one the SDK's middleware calls."""

        return _Adapter(self.verifier)


@dataclass(slots=True, frozen=True)
class _Adapter(SDKTokenVerifier):
    """The business's verifier, wearing the SDK's interface.

    The SDK's middleware wants an `AccessToken`; a business writes `Principal`.
    Rather than making one of them learn the other's type, the two are
    translated here — the single place in the package that knows both.
    """

    verifier: TokenVerifier

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = await self.verifier.verify(token)
        if principal is None:
            return None
        return _as_access_token(token, principal)


def _as_access_token(token: str, principal: Principal) -> AccessToken:
    """Carry a `Principal` across the SDK, losslessly.

    The identity has to survive a round trip: the SDK's middleware stores an
    `AccessToken` and hands that back at the gateway, so whatever a verifier
    supplied has to be recoverable from it. Mapping every field — rather than
    keeping a side table keyed by token string — is what makes that true
    without this module holding onto credentials it has no use for.

    `issuer` travels inside `claims` under `iss`, which is where it lives in a
    real token and where the SDK's own `principal_components` looks for it. An
    `iss` the verifier already supplied is left alone.
    """

    claims: dict[str, Any] = dict(principal.claims)
    if principal.issuer is not None:
        claims.setdefault("iss", principal.issuer)
    return AccessToken(
        token=token,
        # The SDK's field is a plain `str`; a machine token with no client
        # identity round-trips as empty rather than as the string "None".
        client_id=principal.client_id or "",
        scopes=sorted(principal.scopes),
        subject=principal.subject,
        claims=claims or None,
    )


def principal_of(token: AccessToken | None) -> Principal | None:
    """Recover the identity from whatever the SDK is holding.

    Deliberately written against `AccessToken` rather than against `_Adapter`'s
    output, so that it keeps working for a deployment that bypasses `Auth` and
    installs an SDK-native verifier through `sdk_overrides`. Such a server
    still gets a usable `current_principal()`, because this reads the fields
    any verifier fills in rather than a private convention of ours.
    """

    if token is None:
        return None
    claims = token.claims or {}
    issuer = claims.get("iss")
    return Principal(
        subject=token.subject,
        client_id=token.client_id or None,
        issuer=str(issuer) if issuer is not None else None,
        scopes=frozenset(token.scopes),
        claims=claims,
    )


__all__ = ["Auth", "TokenVerifier", "principal_of"]
