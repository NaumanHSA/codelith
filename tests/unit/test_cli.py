"""
The command line, and the small decisions it makes before it calls anything.

Most of the CLI is a thin client — it makes one or two HTTP calls and prints the
answer, and testing that would mostly be testing `httpx`. What is worth pinning is
the reasoning it does *first*: what the user meant by a target, which codebase they
meant when they did not say, and the promise that `--json` puts one document on
stdout and nothing else.

That last one is a contract, not a preference. `codelith status --json | jq` breaks
the moment a spinner or a "signed in" line lands on the same stream.
"""

from __future__ import annotations

import argparse
import json

import pytest

from codelith.cli import build_parser, main
from codelith.cli.client import CliError
from codelith.cli.commands import _find_project, _pretty, resolve_source
from codelith.cli.render import Output


class TestResolvingWhatTheUserPointedAt:
    def test_an_existing_directory_is_local(self, tmp_path) -> None:
        kind, path, name = resolve_source(str(tmp_path))
        assert kind == "local"
        assert path == str(tmp_path.resolve())
        assert name == tmp_path.name

    def test_a_bare_host_needs_no_scheme(self) -> None:
        """`codelith analyse github.com/acme/repo` is what the landing page shows."""
        kind, url, name = resolve_source("github.com/acme/neurosurfer")
        assert (kind, url, name) == (
            "github",
            "https://github.com/acme/neurosurfer",
            "neurosurfer",
        )

    @pytest.mark.parametrize(
        "target,kind",
        [
            ("https://gitlab.com/acme/thing", "gitlab"),
            ("https://bitbucket.org/acme/thing", "bitbucket"),
            ("https://www.github.com/acme/thing", "github"),
            ("git@example.com", None),
        ],
    )
    def test_known_hosts(self, target: str, kind: str | None) -> None:
        if kind is None:
            with pytest.raises(CliError):
                resolve_source(target)
        else:
            assert resolve_source(target)[0] == kind

    def test_the_git_suffix_does_not_become_the_name(self) -> None:
        assert resolve_source("github.com/acme/thing.git")[2] == "thing"

    def test_a_directory_wins_over_a_url_shaped_name(self, tmp_path) -> None:
        """A directory called `github.com` is a directory. Disk is checked first."""
        d = tmp_path / "github.com"
        d.mkdir()
        assert resolve_source(str(d))[0] == "local"

    def test_a_host_without_a_repository_is_refused(self) -> None:
        with pytest.raises(CliError, match="owner/name"):
            resolve_source("github.com/acme")


class TestChoosingACodebase:
    class _Api:
        def __init__(self, projects):
            self._projects = projects

        def projects(self):
            return self._projects

    ONE = [{"id": 4, "name": "neurosurfer"}]
    TWO = ONE + [{"id": 5, "name": "enigma"}]

    def test_one_codebase_needs_no_naming(self) -> None:
        assert _find_project(self._Api(self.ONE), None)["id"] == 4

    def test_two_codebases_must_be_disambiguated(self) -> None:
        with pytest.raises(CliError, match="Which codebase"):
            _find_project(self._Api(self.TWO), None)

    def test_by_id_and_by_name(self) -> None:
        assert _find_project(self._Api(self.TWO), "5")["name"] == "enigma"
        assert _find_project(self._Api(self.TWO), "ENIGMA")["id"] == 5

    def test_nothing_analysed_says_what_to_do(self) -> None:
        with pytest.raises(CliError, match="codelith analyse"):
            _find_project(self._Api([]), None)

    def test_an_unknown_name_is_not_silently_the_first_one(self) -> None:
        with pytest.raises(CliError, match="No codebase"):
            _find_project(self._Api(self.TWO), "nope")


class TestJsonIsMachineReadable:
    """
    The contract: under `--json`, stdout carries one document and nothing else.
    Prose and progress go to stderr or are suppressed.
    """

    def test_prose_is_suppressed_and_the_result_is_parseable(self, capsys) -> None:
        o = Output(as_json=True)
        o.say("this must not appear")
        o.step("nor this")
        o.result({"ok": True, "codebases": [4, 5]})

        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"ok": True, "codebases": [4, 5]}
        assert "must not appear" not in captured.out

    def test_without_json_nothing_lands_on_stdout_as_json(self, capsys) -> None:
        o = Output(as_json=False)
        o.result({"ok": True})
        assert capsys.readouterr().out == ""


class TestCredentials:
    def test_environment_beats_the_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("CODELITH_HOME", str(tmp_path))
        monkeypatch.setenv("CODELITH_API_URL", "http://elsewhere:9000")
        monkeypatch.setenv("CODELITH_TOKEN", "from-env")
        # Re-read the module-level paths, which are resolved from CODELITH_HOME.
        import importlib

        from codelith.cli import client as client_mod

        importlib.reload(client_mod)
        creds = client_mod.Credentials.load()
        assert creds.api_url == "http://elsewhere:9000"
        assert creds.token == "from-env"
        importlib.reload(client_mod)

    def test_a_trailing_slash_never_doubles_up(self, tmp_path, monkeypatch) -> None:
        """
        Every request is built as `f"{api_url}/api/v1{path}"`, so one stray slash in
        a stored config turns every call into a 404. Normalised on load, which is the
        only path a command takes.
        """
        monkeypatch.setenv("CODELITH_HOME", str(tmp_path))
        monkeypatch.setenv("CODELITH_API_URL", "http://x:8000/")
        monkeypatch.delenv("CODELITH_TOKEN", raising=False)
        import importlib

        from codelith.cli import client as client_mod

        importlib.reload(client_mod)
        try:
            assert client_mod.Credentials.load().api_url == "http://x:8000"
        finally:
            monkeypatch.undo()
            importlib.reload(client_mod)


class TestTheParser:
    def test_every_command_is_reachable(self) -> None:
        parser = build_parser()
        for argv in (
            ["status"],
            ["doctor"],
            ["studio"],
            ["login"],
            ["ask", "why"],
            ["analyse", "."],
            ["analyze", "."],  # the American spelling is an alias, not a second command
            ["mcp"],
        ):
            assert parser.parse_args(argv).command is not None

    def test_no_command_prints_help_and_exits_two(self, capsys) -> None:
        """`2` is the conventional shell code for "you typed it wrong"."""
        assert main([]) == 2
        assert "Read a codebase once" in capsys.readouterr().out


def test_agent_names_read_as_prose() -> None:
    assert _pretty("composition_writer_agent") == "Composition writer"
    assert _pretty("kb_persister_agent") == "Kb persister"


class TestTheMcpCommand:
    """
    `codelith mcp` is what an editor launches, and the contract is narrow: stdin and
    stdout carry JSON-RPC and nothing else.

    It exists so `.mcp.json` can say `{"command": "codelith", "args": ["mcp"]}`. The
    documented invocation used to be a Python module path plus a `PYTHONPATH`, which
    only worked from inside a checkout.
    """

    def test_it_prints_nothing_to_stdout(self, capsys, monkeypatch) -> None:
        """
        One line of prose on stdout is a parse error on the client — and the failure
        surfaces as "the server is broken", not as "the server said hello".
        """
        import codelith.mcp.server as server_mod
        from codelith.cli import commands

        served: list[bool] = []

        async def _fake_serve():
            served.append(True)

        monkeypatch.setattr(server_mod, "main", _fake_serve)

        assert commands.cmd_mcp(argparse.Namespace(), Output(as_json=False)) == 0
        assert served == [True]
        assert capsys.readouterr().out == ""
