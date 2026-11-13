"""
The files it takes to install, configure and run the code: which they are, what kind
each is, and that a real environment file never keeps a value.
"""

from pathlib import Path

import pytest

from codelith.knowledge.detectors import (
    MASK,
    mask_values,
    project_file_kind,
    project_file_language,
    read_project_files,
)


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("pyproject.toml", "manifest"),
        ("requirements.txt", "manifest"),
        ("ui/package.json", "manifest"),
        ("go.mod", "manifest"),
        ("pom.xml", "manifest"),
        ("poetry.lock", "lockfile"),
        ("ui/pnpm-lock.yaml", "lockfile"),
        ("go.sum", "lockfile"),
        (".env", "env"),
        (".env.production", "env"),
        (".env.example", "env"),
        ("Dockerfile", "deploy"),
        ("docker/Dockerfile.prod", "deploy"),
        ("docker-compose.yml", "deploy"),
        ("k8s/deployment.yaml", "deploy"),
        ("infra/main.tf", "deploy"),
        (".github/workflows/ci.yml", "ci"),
        (".gitlab-ci.yml", "ci"),
        ("Makefile", "tooling"),
        ("alembic.ini", "tooling"),
        (".python-version", "tooling"),
        ("ui/tsconfig.app.json", "tooling"),
        ("README.md", "docs"),
        ("ui/README.md", "docs"),
        ("CONTRIBUTING.md", "docs"),
    ],
)
def test_project_files_are_recognised(path: str, kind: str) -> None:
    assert project_file_kind(path) == kind


@pytest.mark.parametrize(
    "path",
    [
        "setup.py",  # source code a provider parses: a file of the reading already
        "app/settings.py",
        "docs/guide/architecture.md",  # documentation, not setting the project up
        "tests/fixtures/repo/pyproject.toml",  # a fixture's manifest is not this project's
        "examples/basic/package.json",
        "app/data.yaml",
        "LICENSE",
    ],
)
def test_other_files_are_not(path: str) -> None:
    assert project_file_kind(path) is None


def test_each_is_highlighted_as_what_it_is() -> None:
    assert project_file_language("Dockerfile") == "dockerfile"
    assert project_file_language("pyproject.toml") == "toml"
    assert project_file_language("ui/pnpm-lock.yaml") == "yaml"
    assert project_file_language("Makefile") == "makefile"
    assert project_file_language(".env.example") == "env"


def test_values_are_masked_and_names_kept() -> None:
    text = "# keys\nexport API_KEY=sk-live-123\nEMPTY=\nURL = postgres://u:p@h/db\n\n"
    masked = mask_values(text)
    assert "sk-live-123" not in masked and "postgres://" not in masked
    assert masked == f"# keys\nexport API_KEY={MASK}\nEMPTY=\nURL = {MASK}\n\n"


def test_reading_a_checkout_masks_a_real_env_and_keeps_a_template(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=hunter2\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("SECRET=change-me\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "package.json").write_text("{}", encoding="utf-8")

    files = {f.path: f for f in read_project_files(tmp_path)}
    assert set(files) == {".env", ".env.example", "pyproject.toml"}
    assert files[".env"].masked and "hunter2" not in files[".env"].content
    assert not files[".env.example"].masked and "change-me" in files[".env.example"].content


def test_a_binary_file_is_not_kept(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_bytes(b"all:\n\x00\x01\x02")
    assert read_project_files(tmp_path) == []
