"""Package and protocol constants.

The package version lives here rather than in the root `__init__` so that any
layer can report it without importing the facade above itself.
"""

PACKAGE_NAME = "contexture"
PACKAGE_VERSION = "0.0.4"

MCP_PROTOCOL_VERSION = "2026-07-28"
JSON_RPC_VERSION = "2.0"

PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"
