"""`python -m codelith.mcp` — stdio transport, which is what MCP clients launch."""

import asyncio

from codelith.mcp.server import main

if __name__ == "__main__":
    asyncio.run(main())
