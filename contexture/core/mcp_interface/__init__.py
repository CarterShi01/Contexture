"""What this server exposes on each of MCP's three primitives.

One module per primitive, so that the answer to *what does this server put in
front of a host?* is a directory listing rather than a search.

    tool.py       the four entry points every declaration projects onto
    resource.py   content a host may take up on its own
    prompt.py     capabilities a person triggers by name

The three are split by **who decides when it is used** — the protocol's own
axis, not this project's. See this package's README.

**Nothing here imports the SDK.** Declaring what a primitive carries and
putting it on a wire are two jobs, and only the second belongs to `server`.
"""

from .prompt import Prompt
from .resource import Resource
from .tool import GATEWAY, GATEWAY_TOOLS, GatewayTool

__all__ = [
    "GATEWAY",
    "GATEWAY_TOOLS",
    "GatewayTool",
    "Prompt",
    "Resource",
]
