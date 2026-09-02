"""
`codelith` — the command the landing page has always advertised.

Built on `argparse` and `rich`, both of which the project already depends on. A CLI
that is the recommended way in should not be the reason the install is heavier.

Exit codes are the contract for scripts: `0` success, `1` the command ran and the
answer was no, `2` the command was malformed. Anything raised as `CliError` is a
sentence for the user; anything else is a bug and keeps its traceback.
"""

from __future__ import annotations

import argparse
import sys

from codelith.cli.client import CliError
from codelith.cli.render import Output

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codelith",
        description="Read a codebase once. Use it many times.",
        epilog="Start with: codelith analyse .",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print one JSON document to stdout and nothing else.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("login", help="Sign in to a Codelith server and remember the token")
    p.add_argument("--email")
    p.add_argument("--password", help="Prompted for if omitted, which is the safer habit")
    p.add_argument("--api-url", help="Defaults to the stored value, then localhost:8000")

    p = sub.add_parser("analyse", aliases=["analyze"], help="Read a codebase into a knowledge base")
    p.add_argument("target", help="A path that exists, or a GitHub/GitLab/Bitbucket URL")
    p.add_argument("--name", help="What to call it. Defaults to the directory or repository name")
    p.add_argument("--branch", help="Branch to read. Defaults to the source's own default")
    p.add_argument(
        "--no-wait",
        action="store_true",
        help="Start the analysis and return immediately, rather than following it",
    )

    p = sub.add_parser("ask", help="Ask a question, grounded in the source")
    p.add_argument("question")
    p.add_argument("--project", help="Name or id. Optional when only one is analysed")

    p = sub.add_parser("status", help="What has been analysed")

    p = sub.add_parser("studio", help="Open the studio in a browser")
    p.add_argument("--url", help="Defaults to http://localhost:5173")
    p.add_argument("--no-open", action="store_true", help="Print the URL, do not open it")

    p = sub.add_parser("doctor", help="Check the configuration before it fails somewhere deep")

    p = sub.add_parser(
        "mcp",
        help="Serve the knowledge base over MCP, for Claude Code, Cursor and the rest",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    from codelith.cli import commands

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    handler = {
        "login": commands.cmd_login,
        "analyse": commands.cmd_analyse,
        "analyze": commands.cmd_analyse,
        "ask": commands.cmd_ask,
        "status": commands.cmd_status,
        "studio": commands.cmd_studio,
        "doctor": commands.cmd_doctor,
        "mcp": commands.cmd_mcp,
    }[args.command]

    o = Output(args.as_json)
    try:
        return handler(args, o)
    except CliError as exc:
        o.fail(str(exc))
        return 1
    except KeyboardInterrupt:
        # 130 is what a shell expects from SIGINT, and scripts branch on it.
        o.step("\n[dim]Stopped.[/dim]")
        return 130


def run() -> None:  # pragma: no cover - console-script shim
    sys.exit(main())
