"""
What the manifests get wrong, without opening a socket.

No network, deliberately: asking PyPI for current versions would send the name of every
package a user depends on — a fingerprint of their codebase — to a third party, and
"nothing leaves your box" is the product's headline claim.

**The false positives are the whole risk.** An audit that reports `pytest` as unused in
a repository full of tests is one nobody opens twice, so every case below is one that
was wrong on a real run before it was right.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codelith.apps.qa.dependencies import (
    DependencyIssue,
    DependencyReport,
    _conflicting,
    _canonical,
    _undeclared,
    _unpinned,
    _unused,
)


def _dep(name: str, specifier: str = ">=1.0", path: str = "pyproject.toml"):
    return SimpleNamespace(
        name=name, data_json={"specifier": specifier, "ecosystem": "pypi"}, source_path=path
    )


class TestUnpinned:
    def test_no_constraint_is_reported(self) -> None:
        out = _unpinned([_dep("build", specifier="")])

        assert out[0].issue is DependencyIssue.UNPINNED

    def test_a_constraint_is_not(self) -> None:
        assert _unpinned([_dep("anyio", ">=4.0")]) == []


class TestConflicting:
    def test_two_constraints_for_one_package(self) -> None:
        out = _conflicting([_dep("httpx", ">=0.27", "pyproject.toml"),
                            _dep("httpx", "<0.25", "requirements.txt")])

        assert out[0].issue is DependencyIssue.CONFLICTING
        assert ">=0.27" in out[0].detail and "<0.25" in out[0].detail

    def test_the_same_constraint_twice_is_not_a_conflict(self) -> None:
        assert _conflicting([_dep("httpx", ">=1"), _dep("httpx", ">=1")]) == []

    def test_naming_style_does_not_create_a_conflict(self) -> None:
        """`Python-Slugify` and `python_slugify` are one package to a registry."""
        assert _conflicting([_dep("Python-Slugify", ">=8"), _dep("python_slugify", ">=8")]) == []


class TestUndeclared:
    def test_an_import_with_no_manifest_entry_is_reported(self) -> None:
        out = _undeclared({"starlette"}, {"fastapi"})

        assert out[0].package == "starlette"
        assert "clean install would fail" in out[0].detail

    def test_an_alias_is_resolved(self) -> None:
        """`import yaml` installs `pyyaml`. Reporting that is the fastest way to be
        wrong about something the reader knows perfectly well."""
        assert _undeclared({"yaml"}, {"pyyaml"}) == []

    def test_a_namespace_package_is_resolved(self) -> None:
        """`import opentelemetry`, but what you install is `opentelemetry-sdk`.
        Declaring the distribution is correct."""
        assert _undeclared({"opentelemetry"}, {"opentelemetry-sdk"}) == []


class TestUnused:
    def test_a_declared_package_nobody_imports_is_reported(self) -> None:
        out = _unused([_dep("lxml")], {"httpx"})

        assert out[0].issue is DependencyIssue.UNUSED

    def test_tooling_is_never_unused(self) -> None:
        """`pytest` is invoked, not imported. Reporting it in a repository full of
        tests teaches a reader the list is noise."""
        assert _unused([_dep("pytest"), _dep("ruff"), _dep("mypy")], set()) == []

    @pytest.mark.parametrize(
        "package", ["mkdocs-material-extensions", "pytest-asyncio", "types-PyYAML", "pymdown-extensions"]
    )
    def test_plugin_families_are_never_unused(self, package: str) -> None:
        """A mkdocs plugin is named in `mkdocs.yml` and never appears in a `.py` file.
        Eight of nine "unused" findings on the first real run were exactly this."""
        assert _unused([_dep(package)], set()) == []

    def test_an_alias_counts_as_used(self) -> None:
        assert _unused([_dep("pyyaml")], {"yaml"}) == []

    def test_a_namespace_package_counts_as_used(self) -> None:
        assert _unused([_dep("opentelemetry-sdk")], {"opentelemetry"}) == []

    def test_the_wording_says_what_was_measured(self) -> None:
        """It can only see imports the analysis recorded — a package loaded by string
        name looks unused. "No import was found" is true; "it is unused" is not."""
        out = _unused([_dep("lxml")], {"httpx"})

        assert "No import of it was found" in out[0].detail


class TestTheSummary:
    def test_no_manifest_is_not_a_clean_bill(self) -> None:
        assert "No dependency manifest" in DependencyReport(no_manifest=True).summary

    def test_nothing_wrong_says_so(self) -> None:
        assert "look consistent" in DependencyReport(declared_count=43).summary


class TestCanonicalNames:
    @pytest.mark.parametrize(
        "raw,expected",
        [("Python-Slugify", "python-slugify"), ("python_slugify", "python-slugify"),
         ("  PyYAML ", "pyyaml"), ("ruamel.yaml", "ruamel-yaml")],
    )
    def test_names_normalise(self, raw: str, expected: str) -> None:
        assert _canonical(raw) == expected
