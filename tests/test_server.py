"""How to serve, stated in a way that can disagree with its caller.

`ContextureOptions` exists because a keyword-argument passthrough cannot hold
an opinion. Most tests here are one opinion it holds, and each one guards a
mistake that would otherwise produce a **running server on a wrong assumption**
rather than an error — the failure mode worth paying a validation layer for.

The rest are about `ContextureServer` itself: that it builds once, and that
what it builds cannot be quietly replaced by a second answer.
"""

from __future__ import annotations

import unittest

from contexture import Principal
import sys
from pathlib import Path

from contexture.server import ContextureOptions, ServeError
from contexture.server.identity import Auth
from contexture.demo.role import KubernetesPlatform

sys.path.insert(0, str(Path(__file__).resolve().parent))

from serving import serve  # noqa: E402


class Verifier:
    async def verify(self, token: str) -> Principal | None:
        return None


def _auth() -> Auth:
    return Auth(
        verifier=Verifier(),
        issuer="https://idp.example",
        resource="https://mcp.example/mcp",
    )


class StdioTests(unittest.TestCase):
    def test_an_address_alongside_stdio_is_named_rather_than_discarded(self) -> None:
        """The SDK's stdio branch takes no keyword arguments at all.

        `run("stdio", port=9000)` used to drop the port without a word, which
        is how somebody spends an afternoon connecting to a port nothing is
        listening on.
        """

        with self.assertRaises(ServeError) as caught:
            ContextureOptions(transport="stdio", port=9000)

        self.assertIn("port", str(caught.exception))
        self.assertIn("streamable-http", str(caught.exception))

    def test_every_http_only_field_is_reported_at_once(self) -> None:
        """One run, one list — not one error per attempt."""

        with self.assertRaises(ServeError) as caught:
            ContextureOptions(transport="stdio", host="0.0.0.0", port=1, auth=_auth())

        message = str(caught.exception)
        for field in ("host", "port", "auth"):
            self.assertIn(field, message)

    def test_the_plain_default_is_stdio_and_says_nothing_else(self) -> None:
        options = ContextureOptions()

        self.assertEqual(options.transport, "stdio")
        self.assertEqual(options.transport_kwargs(), {})


class BindingSafetyTests(unittest.TestCase):
    """Two things that must be typed before a port faces anyone else."""

    def test_loopback_needs_neither_permission(self) -> None:
        options = ContextureOptions(transport="streamable-http")

        self.assertEqual(options.resolved_host, "127.0.0.1")
        self.assertEqual(options.url, "http://127.0.0.1:8000/mcp")

    def test_a_public_bind_without_allowed_headers_is_refused(self) -> None:
        """The SDK turns rebinding protection on for loopback and only loopback."""

        with self.assertRaises(ServeError) as caught:
            ContextureOptions(transport="streamable-http", host="0.0.0.0")

        self.assertIn("rebinding", str(caught.exception))

    def test_a_public_bind_without_auth_is_refused(self) -> None:
        with self.assertRaises(ServeError) as caught:
            ContextureOptions(
                transport="streamable-http",
                host="0.0.0.0",
                allowed_hosts=("mcp.example:*",),
            )

        self.assertIn("allow_anonymous", str(caught.exception))

    def test_serving_anonymously_in_public_is_possible_once_it_is_typed(self) -> None:
        options = ContextureOptions(
            transport="streamable-http",
            host="0.0.0.0",
            allowed_hosts=("mcp.example:*",),
            allow_anonymous=True,
        )

        self.assertIsNone(options.auth)

    def test_auth_alone_satisfies_the_second_check(self) -> None:
        options = ContextureOptions(
            transport="streamable-http",
            host="0.0.0.0",
            allowed_origins=("https://acme.example",),
            auth=_auth(),
        )

        self.assertIsNotNone(options.auth)


class OverrideTests(unittest.TestCase):
    def test_statelessness_is_a_position_rather_than_a_knob(self) -> None:
        """ADR 001's claim, defended where it would otherwise be turned off."""

        with self.assertRaises(ServeError) as caught:
            ContextureOptions(
                transport="streamable-http", sdk_overrides={"stateless_http": False}
            )

        self.assertIn("no session", str(caught.exception))

    def test_an_event_store_has_no_session_to_replay_into(self) -> None:
        with self.assertRaises(ServeError):
            ContextureOptions(
                transport="streamable-http", sdk_overrides={"event_store": object()}
            )

    def test_overrides_may_not_take_back_what_options_owns(self) -> None:
        with self.assertRaises(ServeError) as caught:
            ContextureOptions(
                transport="streamable-http", sdk_overrides={"port": 9000}
            )

        self.assertIn("port", str(caught.exception))

    def test_the_escape_hatch_still_reaches_the_sdk(self) -> None:
        """What the object has no opinion about goes through untouched."""

        kwargs = ContextureOptions(
            transport="streamable-http", sdk_overrides={"json_response": True}
        ).transport_kwargs()

        self.assertIs(kwargs["json_response"], True)

    def test_the_transport_arguments_pin_statelessness(self) -> None:
        kwargs = ContextureOptions(
            transport="streamable-http", host="127.0.0.1", port=9001, path="/ctx"
        ).transport_kwargs()

        self.assertIs(kwargs["stateless_http"], True)
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 9001)
        self.assertEqual(kwargs["streamable_http_path"], "/ctx")

    def test_allowed_headers_become_the_sdk_security_settings(self) -> None:
        kwargs = ContextureOptions(
            transport="streamable-http",
            host="0.0.0.0",
            allowed_hosts=("mcp.example:*",),
            allowed_origins=("https://acme.example",),
            allow_anonymous=True,
        ).transport_kwargs()

        security = kwargs["transport_security"]
        self.assertTrue(security.enable_dns_rebinding_protection)
        self.assertEqual(security.allowed_hosts, ["mcp.example:*"])
        self.assertEqual(security.allowed_origins, ["https://acme.example"])


class ServerTests(unittest.TestCase):
    def test_stating_the_transport_twice_is_refused(self) -> None:
        """Two ways to say one thing, and no way to tell which was meant."""

        server = serve(KubernetesPlatform)

        with self.assertRaises(ServeError) as caught:
            server.start(
                ContextureOptions(transport="stdio"), transport="streamable-http"
            )

        self.assertIn("not both", str(caught.exception))

    def test_a_server_can_be_built_with_auth_and_without(self) -> None:
        """Both shapes reach the SDK; the gateway is the same either way."""

        plain = serve(KubernetesPlatform).build()
        secured = serve(KubernetesPlatform).build(auth=_auth())

        self.assertIsNone(plain.settings.auth)
        self.assertIsNotNone(secured.settings.auth)

    def test_building_twice_hands_back_the_one_server(self) -> None:
        """`start` builds; a caller that already built must not get a second.

        Two `MCPServer`s over one assembly is two surfaces where the process
        serves one, and the one on the wire would be whichever was passed to
        the transport — decided by call order rather than by anybody.
        """

        server = serve(KubernetesPlatform)

        self.assertIs(server.build(), server.build())

    def test_a_second_build_with_different_auth_is_refused(self) -> None:
        """Silently keeping the first answer would decide who may knock."""

        server = serve(KubernetesPlatform)
        server.build()

        with self.assertRaises(ServeError) as caught:
            server.build(auth=_auth())

        self.assertIn("already built", str(caught.exception))

    def test_a_server_cannot_be_registered_into(self) -> None:
        """The phase boundary is structural, not a run-time flag.

        A graph is registered into a `ControllerManager` and sealed once; a
        server takes the sealed result. There is deliberately no method here
        that could add a node to something already being served, which is what
        the protocol forbids and what a flag could only complain about after
        the fact.
        """

        server = serve(KubernetesPlatform)

        for absent in ("add_role", "add_skill", "add_tool", "register_role", "publish"):
            self.assertFalse(hasattr(server, absent), absent)


if __name__ == "__main__":
    unittest.main()
