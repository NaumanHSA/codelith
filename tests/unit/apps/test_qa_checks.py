"""
QA's neutral checks — secrets, containers, compose, CI — and the fingerprint that
recognises a finding again after an edit moves it.
"""

from __future__ import annotations

import textwrap

from codelith.apps.qa.checks.deploy import _compose, _dockerfile, _workflow
from codelith.apps.qa.checks.secrets import looks_secret
from codelith.apps.qa.findings import Finding, fingerprint_all
from codelith.apps.qa.service import mask, steps_for

ALL = frozenset({"config", "leakage", "security"})


def rules(found) -> list[str]:
    return sorted(f.rule for f in found)


class TestSecretsJudgement:
    def test_real_looking_values(self) -> None:
        assert looks_secret("a8Fk3LmQ9zX2pR7vWq")
        assert looks_secret("Pa55w0rd!")

    def test_names_placeholders_and_words_are_not(self) -> None:
        for value in ("password_hash", "change-me-in-production", "your-api-key-here", "lm-studio", "${DB_PASSWORD}", "OPENAI_API_KEY"):
            assert not looks_secret(value), value


class TestDockerfile:
    def test_root_unpinned_and_copy_everything(self) -> None:
        text = "FROM python\nWORKDIR /app\nCOPY . .\nCMD [\"python\", \"main.py\"]\n"
        assert rules(_dockerfile("Dockerfile", text, set(), ALL)) == [
            "config.docker-copies-everything",
            "config.docker-root",
            "config.docker-unpinned-image",
        ]

    def test_a_careful_dockerfile_has_nothing(self) -> None:
        text = "FROM python:3.12-slim AS build\nCOPY . .\nFROM build\nRUN useradd -r app\nUSER app\nCMD [\"app\"]\n"
        assert _dockerfile("Dockerfile", text, {".dockerignore"}, ALL) == []

    def test_a_secret_baked_into_the_image_is_masked(self) -> None:
        text = "FROM node:20\nENV API_KEY=abc123secret \\\n    PORT=3000\nUSER node\n"
        found = [f for f in _dockerfile("Dockerfile", text, set(), ALL) if f.rule == "leak.docker-secret"]
        assert len(found) == 1 and found[0].line == 2
        line, start, end = found[0].evidence["masks"][0]
        assert text.splitlines()[line - 1][start:end] == "abc123secret"


class TestCompose:
    TEXT = textwrap.dedent(
        """
        services:
          db:
            image: postgres:16
            ports: ["5432:5432"]
            environment:
              POSTGRES_PASSWORD: s3cretPass
              JWT_SECRET: change-me
          cache:
            image: redis:7
            ports: ["127.0.0.1:6379:6379"]
          app:
            build: .
            privileged: true
            environment:
              API_TOKEN: ${API_TOKEN}
        """
    )

    def test_what_it_finds(self) -> None:
        assert rules(_compose("docker-compose.yml", self.TEXT, ALL)) == [
            "config.compose-database-published",
            "leak.compose-placeholder-secret",
            "leak.compose-secret",
            "security.compose-privileged",
        ]


class TestWorkflow:
    TEXT = textwrap.dedent(
        """
        on: pull_request
        jobs:
          t:
            steps:
              - uses: actions/checkout@v4
              - uses: someone/thing@v2
              - uses: someone/pinned@0123456789abcdef0123456789abcdef01234567
              - run: echo "${{ github.event.pull_request.title }}"
              - run: echo ${{ secrets.TOKEN }}
        """
    )

    def test_what_it_finds(self) -> None:
        assert rules(_workflow("ci.yml", self.TEXT, ALL)) == [
            "config.ci-action-unpinned",
            "leak.ci-secret-echoed",
            "security.ci-script-injection",
        ]


class TestFingerprints:
    def _finding(self, line: int, snippet: str = "except Exception:") -> Finding:
        return Finding("py.swallowed-exception", "errors", "medium", "t", "m", "f", path="a.py", line=line, snippet=snippet)

    def test_moving_the_line_keeps_the_fingerprint(self) -> None:
        a, b = self._finding(10), self._finding(42)
        fingerprint_all([a])
        fingerprint_all([b])
        assert a.fingerprint == b.fingerprint

    def test_whitespace_does_not_matter_but_the_code_does(self) -> None:
        a, b, c = self._finding(1, "except Exception:"), self._finding(1, "    except   Exception :"), self._finding(1, "except BaseException:")
        for f in (a, b, c):
            fingerprint_all([f])
        assert a.fingerprint == b.fingerprint != c.fingerprint

    def test_two_identical_lines_in_a_file_are_two_findings(self) -> None:
        first, second = self._finding(5), self._finding(50)
        fingerprint_all([second, first])
        assert first.fingerprint != second.fingerprint


def test_masking_replaces_the_span_only() -> None:
    assert mask(["x", 'key = "abcdef123"'], 1, [[2, 7, 16]], "abcd••") == ["x", 'key = "abcd••"']


def test_a_run_reports_only_the_steps_its_areas_need() -> None:
    assert steps_for(["tests"]) == ["qa_prepare", "qa_code", "qa_untested", "qa_report"]
    assert "qa_secrets" in steps_for(["leakage"]) and "qa_untested" not in steps_for(["leakage"])
