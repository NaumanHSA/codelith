"""Knowledge-base construction from parsed source — pure, no DB, no LLM."""

from __future__ import annotations

import textwrap

import pytest

from codelith.knowledge.builder import (
    SourceFile,
    build_modules,
    chunk_files,
    entities_from_api_specs,
    merge_entities,
)
from codelith.knowledge.constants import EntityKind, ModuleRole

ROUTES_PY = textwrap.dedent(
    '''
    from fastapi import APIRouter
    router = APIRouter()

    @router.get("/items/{item_id}", response_model=ItemOut)
    async def get_item(item_id: int):
        """Fetch one item."""
        return {}

    @router.post("/items")
    async def create_item(payload: dict):
        return {}
    '''
)

SERVICE_PY = textwrap.dedent(
    '''
    import os

    TIMEOUT = int(os.getenv("ITEM_TIMEOUT", "30"))

    class ItemService:
        """Business logic for items."""

        async def create(self, payload: dict) -> dict:
            return payload
    '''
)


def _files() -> list[SourceFile]:
    return [
        SourceFile(path="app/api/routes.py", content=ROUTES_PY),
        SourceFile(path="app/services/item_service.py", content=SERVICE_PY),
        SourceFile(path="tests/test_items.py", content="def test_x():\n    assert True\n"),
    ]


class TestModules:
    def test_files_group_into_modules_by_directory(self) -> None:
        result = build_modules(_files())
        assert {m["path"] for m in result.modules} == {"app/api", "app/services", "tests"}

    def test_roles_are_inferred(self) -> None:
        by_path = {m["path"]: m for m in build_modules(_files()).modules}

        assert by_path["app/api"]["role"] == ModuleRole.API
        assert by_path["app/services"]["role"] == ModuleRole.SERVICE
        assert by_path["tests"]["role"] == ModuleRole.TEST

    def test_test_modules_are_flagged(self) -> None:
        by_path = {m["path"]: m for m in build_modules(_files()).modules}

        assert by_path["tests"]["is_test"] is True
        assert by_path["app/api"]["is_test"] is False

    def test_symbols_are_captured_with_metadata(self) -> None:
        by_path = {m["path"]: m for m in build_modules(_files()).modules}
        symbols = {s["name"]: s for s in by_path["app/services"]["symbols_json"]}

        assert symbols["ItemService"]["kind"] == "class"
        assert symbols["create"]["parent"] == "ItemService"
        assert symbols["TIMEOUT"]["kind"] == "constant"

    def test_modules_sorted_by_size(self) -> None:
        modules = build_modules(_files()).modules
        assert modules == sorted(modules, key=lambda m: m["loc"], reverse=True)

    def test_unknown_extensions_are_skipped_not_failed(self) -> None:
        result = build_modules([SourceFile(path="README.md", content="# hi")])

        assert result.modules == []
        assert result.skipped == 1

    def test_ignored_directories_never_reach_the_kb(self) -> None:
        result = build_modules(
            [SourceFile(path="ui/node_modules/pkg/setup.py", content="x = 1")]
        )
        assert result.modules == []
        assert result.skipped == 0  # skipped by the ignore list, not counted as unknown


class TestEntities:
    def test_routes_are_detected_with_handler_and_method(self) -> None:
        routes = {
            e["name"]: e
            for e in build_modules(_files()).entities
            if e["kind"] == EntityKind.ROUTE
        }

        assert set(routes) == {"GET /items/{item_id}", "POST /items"}
        assert routes["GET /items/{item_id}"]["data_json"]["handler"] == "get_item"
        assert routes["GET /items/{item_id}"]["source_path"] == "app/api/routes.py"

    def test_env_vars_are_detected(self) -> None:
        names = {
            e["name"] for e in build_modules(_files()).entities
            if e["kind"] == EntityKind.ENV_VAR
        }
        assert "ITEM_TIMEOUT" in names

    def test_dependencies_come_from_manifests_not_extensions(self) -> None:
        """pyproject.toml is claimed by filename — no provider owns `.toml`."""
        manifest = SourceFile(
            path="pyproject.toml",
            content='[project]\nname="x"\ndependencies=["fastapi>=0.1","httpx"]\n',
        )
        deps = {
            e["name"]: e for e in build_modules([manifest]).entities
            if e["kind"] == EntityKind.DEPENDENCY
        }

        assert set(deps) == {"fastapi", "httpx"}
        assert deps["fastapi"]["data_json"]["specifier"] == ">=0.1"

    def test_requirements_txt_ignores_comments_and_flags(self) -> None:
        req = SourceFile(
            path="requirements.txt",
            content="# comment\n-r other.txt\nfastapi==1.0\n\nhttpx\n",
        )
        names = {
            e["name"] for e in build_modules([req]).entities
            if e["kind"] == EntityKind.DEPENDENCY
        }
        assert names == {"fastapi", "httpx"}

    def test_entities_are_deduplicated(self) -> None:
        """The same env var read in two files is recorded once."""
        dup = [
            SourceFile(path="a.py", content='import os\nX = os.getenv("SHARED")\n'),
            SourceFile(path="b.py", content='import os\nY = os.getenv("SHARED")\n'),
        ]
        env = [e for e in build_modules(dup).entities if e["kind"] == EntityKind.ENV_VAR]
        assert len(env) == 1

    def test_invalid_entity_kinds_are_dropped(self) -> None:
        """A provider emitting an unknown kind must not poison the KB."""
        from codelith.languages import registry
        from codelith.languages.base import DetectedEntity

        provider = registry.get("python")
        original = provider.detect_entities
        provider.detect_entities = lambda p, s, sym: [  # type: ignore[method-assign]
            DetectedEntity(kind="not_a_real_kind", name="x")
        ]
        try:
            result = build_modules([SourceFile(path="a.py", content="x = 1")])
            assert result.entities == []
        finally:
            provider.detect_entities = original  # type: ignore[method-assign]

    def test_merge_entities_drops_cross_source_duplicates(self) -> None:
        a = [{"kind": "route", "name": "GET /x"}]
        b = [{"kind": "route", "name": "GET /x"}, {"kind": "route", "name": "GET /y"}]
        assert len(merge_entities(a, b)) == 2

    def test_openapi_routes_are_language_neutral(self) -> None:
        class Spec:
            path = "openapi.yaml"
            endpoints = [{"method": "get", "path": "/health", "summary": "Health"}]

        routes = entities_from_api_specs([Spec()])
        assert routes[0]["name"] == "GET /health"
        assert routes[0]["data_json"]["source"] == "openapi"


class TestManifestDiscovery:
    """
    Regression: the code parser only yields files with a language extension, so
    `pyproject.toml` never reached the extractor and the KB recorded zero
    dependencies — observed on a real run.
    """

    def test_finds_manifests_the_code_parser_would_miss(self, tmp_path) -> None:
        from codelith.knowledge.builder import read_manifest_files

        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname="x"\ndependencies=["fastapi","httpx"]\n'
        )
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("x = 1")

        found = read_manifest_files(tmp_path)

        assert [f.path for f in found] == ["pyproject.toml"]
        deps = [e for e in build_modules(found).entities if e["kind"] == EntityKind.DEPENDENCY]
        assert {d["name"] for d in deps} == {"fastapi", "httpx"}

    def test_finds_nested_manifests(self, tmp_path) -> None:
        from codelith.knowledge.builder import read_manifest_files

        (tmp_path / "svc").mkdir()
        (tmp_path / "svc" / "requirements.txt").write_text("httpx\n")

        assert [f.path for f in read_manifest_files(tmp_path)] == ["svc/requirements.txt"]

    def test_skips_vendored_manifests(self, tmp_path) -> None:
        from codelith.knowledge.builder import read_manifest_files

        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "requirements.txt").write_text("evil\n")

        assert read_manifest_files(tmp_path) == []

    def test_missing_directory_is_not_an_error(self) -> None:
        from codelith.knowledge.builder import read_manifest_files

        assert read_manifest_files("/nope/does/not/exist") == []


class TestChunking:
    def test_chunks_carry_line_ranges_and_language(self) -> None:
        content = "\n".join(f"line {i}" for i in range(100))
        chunks = chunk_files([SourceFile(path="a.py", content=content)])

        assert len(chunks) > 1
        assert chunks[0]["start_line"] == 1
        assert chunks[0]["language"] == "python"
        assert all(c["chunk_type"] == "code" for c in chunks)

    def test_chunks_overlap(self) -> None:
        content = "\n".join(f"line {i}" for i in range(100))
        chunks = chunk_files([SourceFile(path="a.py", content=content)], chunk_lines=40, overlap=5)
        assert chunks[1]["start_line"] < chunks[0]["end_line"]

    def test_blank_and_ignored_files_produce_nothing(self) -> None:
        assert chunk_files([SourceFile(path="a.py", content="")]) == []
        assert chunk_files([SourceFile(path="node_modules/a.py", content="x=1")]) == []


class TestDocTypeSuggestions:
    @pytest.mark.parametrize(
        "kinds,expected",
        [
            ({"route": 12}, "api"),
            ({"infra_resource": 3}, "deployment"),
            ({"entrypoint": 1}, "getting_started"),
        ],
    )
    def test_evidence_drives_suggestions(self, kinds, expected) -> None:
        from codelith.knowledge.roles import suggest_doc_types

        types = {s["doc_type"] for s in suggest_doc_types(kinds, {"service": 2})}
        assert expected in types
        assert "architecture" in types  # always offered

    def test_no_routes_means_no_api_doc_offered(self) -> None:
        from codelith.knowledge.roles import suggest_doc_types

        types = {s["doc_type"] for s in suggest_doc_types({}, {"service": 1})}
        assert "api" not in types

    def test_suggestions_are_ordered_by_confidence(self) -> None:
        from codelith.knowledge.roles import suggest_doc_types

        out = suggest_doc_types({"route": 40, "infra_resource": 2}, {"service": 5})
        assert out == sorted(out, key=lambda s: s["confidence"], reverse=True)


class TestChunkingMetadata:
    """
    Chunk line spans must describe the text actually stored.

    Run 1: 34% of chunks hit the old 1,500-char cap and then reported a 40-line span
    while holding ~36 lines, and `SectionContextBuilder._format()` labelled each one
    `path:start-end` as though it were complete.
    """

    @staticmethod
    def _chunk(source: str):
        from codelith.knowledge.builder import SourceFile, chunk_files

        return chunk_files([SourceFile(path="pkg/mod.py", content=source, language="python")])

    def test_line_span_matches_stored_content(self) -> None:
        source = "\n".join(
            line
            for i in range(40)
            for line in (f"def f{i}():", f'    """doc {i}"""', f"    return {i}", "")
        )
        for chunk in self._chunk(source):
            stored = len(chunk["content"].splitlines())
            claimed = chunk["end_line"] - chunk["start_line"] + 1
            assert stored == claimed, chunk["content"][:80]

    def test_a_long_unit_is_split_rather_than_truncated(self) -> None:
        """No band of source may end up in no chunk at all."""
        body = "\n".join(f"    x{i} = {i} * 1000000" for i in range(400))
        source = f"def enormous():\n{body}\n"
        chunks = self._chunk(source)
        covered: set[int] = set()
        for chunk in chunks:
            covered |= set(range(chunk["start_line"], chunk["end_line"] + 1))
        real = {i for i, line in enumerate(source.splitlines(), start=1) if line.strip()}
        assert real - covered == set()

    def test_files_with_no_symbols_still_chunk(self) -> None:
        assert self._chunk("\n".join(f"VALUE_{i} = {i}" for i in range(200)))

    def test_chunks_start_at_declarations_where_possible(self) -> None:
        """
        Functions become their own chunks instead of arbitrary 40-line windows. Bodies
        are padded past the merge threshold — a small file is deliberately kept whole
        rather than shattered into fragments too small to retrieve.
        """
        def fn(name: str) -> str:
            body = "\n".join(f"    {name}_{i} = {i} * 12345" for i in range(30))
            return f"def {name}():\n{body}\n"

        source = '"""Module docstring."""\n\nimport os\n\n\n' + "\n\n".join(
            fn(n) for n in ("alpha", "beta", "gamma")
        )
        starts = {c["content"].splitlines()[0].strip() for c in self._chunk(source)}
        assert sum(1 for s in starts if s.startswith("def ")) >= 2, starts
