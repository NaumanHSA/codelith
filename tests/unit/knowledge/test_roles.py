"""
Role inference.

Every case here is a real miss from run 1 against the neurosurfer repository, where
the path-only matcher put 23 of 45 modules — 13,770 LOC — on `unknown` and thereby
hid them from narrative selection, the planner's inventory and `key_files`
validation. The point of these tests is that those specific failures stay fixed.
"""

from __future__ import annotations

import pytest

from app.knowledge.constants import EntityKind, ModuleRole
from app.knowledge.roles import infer_role


def role(path: str, files: list[str] | None = None, **kw) -> str:
    return str(infer_role(path, files if files is not None else [f"{path}/x.py"], **kw))


class TestEvidenceBeatsConvention:
    def test_a_module_defining_routes_is_the_api_layer(self) -> None:
        """Whatever the directory is called. This is observed fact, not naming."""
        assert role("pkg/nowhere", entity_kinds={str(EntityKind.ROUTE)}) == ModuleRole.API

    def test_a_module_declaring_infra_resources_is_infra(self) -> None:
        assert role("pkg/misc", entity_kinds={str(EntityKind.INFRA_RESOURCE)}) == ModuleRole.INFRA

    def test_tests_win_outright(self) -> None:
        """A test module is a test module whatever it exercises."""
        assert (
            role("pkg/api", is_test=True, entity_kinds={str(EntityKind.ROUTE)})
            == ModuleRole.TEST
        )


class TestLeafOutranksAncestors:
    """`app/server/schemas` is a schema package that happens to live under a server."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("neurosurfer/app/server/schemas", ModuleRole.SCHEMA),
            ("neurosurfer/app/server/backends", ModuleRole.SERVICE),
            ("neurosurfer/app/server/api", ModuleRole.API),
            ("neurosurfer/app/cli/commands", ModuleRole.CLI),
        ],
    )
    def test_leaf_decides(self, path: str, expected: ModuleRole) -> None:
        assert role(path) == expected

    def test_ancestor_still_decides_when_the_leaf_says_nothing(self) -> None:
        assert role("neurosurfer/app/server/xyzzy") == ModuleRole.API


class TestPluralsAndCompounds:
    @pytest.mark.parametrize(
        "path,expected",
        [
            # `workflows` was a hint but the module was singular.
            ("neurosurfer/graph/workflow", ModuleRole.SERVICE),
            ("neurosurfer/graph/workflows", ModuleRole.SERVICE),
            # A stemmer previously mangled this one into `vectorstor`.
            ("neurosurfer/vectorstores", ModuleRole.DATA_ACCESS),
            ("neurosurfer/vectorstore", ModuleRole.DATA_ACCESS),
            ("app/repositories", ModuleRole.DATA_ACCESS),
        ],
    )
    def test_singular_and_plural_are_the_same_hint(self, path: str, expected: ModuleRole) -> None:
        assert role(path) == expected

    def test_compound_names_offer_their_pieces(self) -> None:
        assert role("pkg/task_queue") == ModuleRole.WORKER


class TestFilenameHintsMustDominate:
    def test_one_config_py_does_not_relabel_a_large_module(self) -> None:
        """
        Run 1 called a 13-file RAG package `config` on the strength of one config.py,
        which then decided which narratives and documents ever saw it.
        """
        files = ["rag/config.py"] + [f"rag/f{i}.py" for i in range(12)]
        assert role("neurosurfer/rag", files, symbol_count=9) == ModuleRole.SERVICE

    def test_a_small_module_of_config_files_is_config(self) -> None:
        assert role("pkg/zzz", ["pkg/settings.py", "pkg/__init__.py"]) == ModuleRole.CONFIG


class TestFallback:
    def test_unmatched_code_is_a_service_not_an_unknown(self) -> None:
        """`unknown` hides a module from three separate consumers; earn it."""
        assert role("neurosurfer/architect", symbol_count=12) == ModuleRole.SERVICE

    def test_a_module_with_nothing_in_it_stays_unknown(self) -> None:
        assert role("pkg/zzz", ["pkg/__init__.py"], symbol_count=0) == ModuleRole.UNKNOWN


def test_the_run_1_repository_has_no_unknown_modules() -> None:
    """
    The regression in aggregate: these are the real module paths from run 1, of which
    23 previously inferred to `unknown`.
    """
    paths = [
        "neurosurfer/agents", "neurosurfer/agents/agentic_loop", "neurosurfer/agents/context",
        "neurosurfer/agents/conversation", "neurosurfer/agents/oneshot", "neurosurfer/agents/react",
        "neurosurfer/agents/runtime", "neurosurfer/agents/subagents", "neurosurfer/app",
        "neurosurfer/app/agents", "neurosurfer/app/cli", "neurosurfer/app/cli/commands",
        "neurosurfer/app/server", "neurosurfer/app/server/api", "neurosurfer/app/server/backends",
        "neurosurfer/app/server/schemas", "neurosurfer/app/tools", "neurosurfer/architect",
        "neurosurfer/architect/nodes", "neurosurfer/cache", "neurosurfer/config",
        "neurosurfer/graph", "neurosurfer/graph/engine", "neurosurfer/graph/workflow",
        "neurosurfer/llm", "neurosurfer/llm/providers", "neurosurfer/mcp",
        "neurosurfer/observability", "neurosurfer/observability/exporters", "neurosurfer/prompts",
        "neurosurfer/rag", "neurosurfer/tools", "neurosurfer/tools/builtin",
        "neurosurfer/tools/builtin/python_exec", "neurosurfer/tools/builtin/web_search",
        "neurosurfer/tools/builtin/web_search/engines", "neurosurfer/tracing",
        "neurosurfer/vectorstores", "scripts", "tutorials/capstone",
    ]
    unknown = [p for p in paths if role(p, symbol_count=5) == ModuleRole.UNKNOWN]
    assert unknown == []
