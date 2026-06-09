from __future__ import annotations

import logging
import sys


def configure_runtime_logging(level: str = "WARNING") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.WARNING),
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
        force=True,
    )

    # Noisy libraries
    for name in [
        "mcp",
        "mcp.client",
        "mcp.client.stdio",
        "httpx",
        "httpcore",
        "urllib3",
    ]:
        logging.getLogger(name).setLevel(getattr(logging, level.upper(), logging.WARNING))