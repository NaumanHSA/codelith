"""
The code graph.

Two failure modes matter more than anything else here, because both produce a graph
that looks healthy and is wrong:

* **Inventing nodes.** The implementation this replaced did `MERGE (dep:File {path})`
  on every import target, so `import os` created a File node for `os`. A graph mostly
  composed of files that are not in the repository answers "what imports this" with
  confident nonsense.
* **Over-connecting.** Resolving a call to `run()` by matching the name anywhere in
  the repository links every `run` to every other one. Density is not accuracy, and
  impact analysis that over-reports is indistinguishable from noise.

So the assertions are mostly *absences*: what must not appear.
"""

from __future__ import annotations

from app.knowledge.builder import SourceFile
from app.knowledge.graph import build_code_graph

SESSION = '''
"""Database session."""
import os
from sqlalchemy.ext.asyncio import AsyncSession


def make_engine():
    return os.getenv("DATABASE_URL")


class SessionFactory:
    def build(self):
        return make_engine()
'''

SERVICE = '''
from app.db.session import make_engine
from app.utils.helpers import unrelated
import pydantic


class ProjectService:
    def start(self):
        return make_engine()

    def other(self):
        return unrelated()
'''

HELPERS = '''
def unrelated():
    return 1
'''


def _repo() -> list[SourceFile]:
    return [
        SourceFile(path="app/db/session.py", content=SESSION, language="python"),
        SourceFile(path="app/services/project.py", content=SERVICE, language="python"),
        SourceFile(path="app/utils/helpers.py", content=HELPERS, language="python"),
    ]


class TestOnlyRealThingsBecomeNodes:
    def test_stdlib_and_third_party_are_not_files(self) -> None:
        graph = build_code_graph(_repo())

        paths = {f["path"] for f in graph.files}
        assert paths == {
            "app/db/session.py",
            "app/services/project.py",
            "app/utils/helpers.py",
        }

    def test_every_import_edge_lands_on_a_file_we_saw(self) -> None:
        graph = build_code_graph(_repo())
        paths = {f["path"] for f in graph.files}

        assert graph.imports, "expected at least one internal import"
        for edge in graph.imports:
            assert edge["src"] in paths
            assert edge["dst"] in paths

    def test_stdlib_is_not_recorded_as_a_dependency(self) -> None:
        """`DEPENDS_ON typing` is not a dependency. On this repository the unfiltered
        version produced 4,862 package edges against 920 real ones."""
        graph = build_code_graph(_repo())
        packages = {p["name"] for p in graph.packages}

        assert "os" not in packages
        assert "__future__" not in packages
        assert "sqlalchemy" in packages
        assert "pydantic" in packages

    def test_a_package_is_recorded_by_its_distribution(self) -> None:
        """`sqlalchemy.ext.asyncio` is a dependency on `sqlalchemy`, not on a path
        into it — otherwise one library appears as a dozen unrelated ones."""
        graph = build_code_graph(_repo())

        assert {p["name"] for p in graph.packages} >= {"sqlalchemy", "pydantic"}
        assert not any("." in p["name"] for p in graph.packages)


class TestEdgesAreDeduplicated:
    def test_importing_several_names_is_one_edge(self) -> None:
        src = "from app.utils.helpers import unrelated\nfrom app.utils.helpers import other\n"
        files = [
            SourceFile(path="app/utils/helpers.py", content=HELPERS, language="python"),
            SourceFile(path="app/a.py", content=src, language="python"),
        ]

        graph = build_code_graph(files)

        assert len([e for e in graph.imports if e["src"] == "app/a.py"]) == 1

    def test_a_repeated_import_inside_functions_is_one_edge(self) -> None:
        """Deferred imports inside functions are a real pattern in this codebase —
        `revision_tasks` does it to avoid a cycle."""
        src = (
            "def a():\n    from app.utils.helpers import unrelated\n\n"
            "def b():\n    from app.utils.helpers import unrelated\n"
        )
        files = [
            SourceFile(path="app/utils/helpers.py", content=HELPERS, language="python"),
            SourceFile(path="app/a.py", content=src, language="python"),
        ]

        graph = build_code_graph(files)

        assert len(graph.imports) == 1


class TestCallResolution:
    def test_a_call_within_one_file_resolves(self) -> None:
        graph = build_code_graph(_repo())

        assert {
            "src_path": "app/db/session.py",
            "src_qname": "SessionFactory.build",
            "dst_path": "app/db/session.py",
            "dst_qname": "make_engine",
        } in graph.calls

    def test_a_call_through_an_import_resolves_to_the_defining_file(self) -> None:
        graph = build_code_graph(_repo())

        assert {
            "src_path": "app/services/project.py",
            "src_qname": "ProjectService.start",
            "dst_path": "app/db/session.py",
            "dst_qname": "make_engine",
        } in graph.calls

    def test_an_unimported_name_is_dropped_not_guessed(self) -> None:
        """Two files defining `handle`, one calling it without importing either.
        Matching by name would invent an edge to whichever was seen first."""
        files = [
            SourceFile(path="a.py", content="def handle():\n    return 1\n", language="python"),
            SourceFile(path="b.py", content="def handle():\n    return 2\n", language="python"),
            SourceFile(path="c.py", content="def go():\n    return handle()\n", language="python"),
        ]

        graph = build_code_graph(files)

        assert [c for c in graph.calls if c["src_path"] == "c.py"] == []

    def test_a_method_on_an_imported_class_resolves(self) -> None:
        """`svc.rekey_anchor()` yields only `rekey_anchor` — the receiver's type is
        not known. Resolving through the file the class was imported from is what
        makes "who calls this method" answerable at all."""
        files = [
            SourceFile(
                path="app/svc.py",
                content="class Service:\n    def rekey(self):\n        return 1\n",
                language="python",
            ),
            SourceFile(
                path="app/task.py",
                content=(
                    "from app.svc import Service\n\n"
                    "def run():\n    svc = Service()\n    return svc.rekey()\n"
                ),
                language="python",
            ),
        ]

        graph = build_code_graph(files)

        assert {
            "src_path": "app/task.py",
            "src_qname": "run",
            "dst_path": "app/svc.py",
            "dst_qname": "Service.rekey",
        } in graph.calls

    def test_an_ambiguous_name_across_two_imports_is_dropped(self) -> None:
        """Two imported modules both defining `run`. Picking either is how a call
        graph becomes confidently wrong, so neither edge is recorded."""
        files = [
            SourceFile(path="a.py", content="def run():\n    return 1\n", language="python"),
            SourceFile(path="b.py", content="def run():\n    return 2\n", language="python"),
            SourceFile(
                path="c.py",
                content="from a import run\nfrom b import run\n\ndef go():\n    return run()\n",
                language="python",
            ),
        ]

        graph = build_code_graph(files)

        assert [c for c in graph.calls if c["src_path"] == "c.py"] == []

    def test_every_call_edge_lands_on_a_symbol_we_recorded(self) -> None:
        graph = build_code_graph(_repo())
        symbols = {(s["path"], s["qname"]) for s in graph.symbols}

        for call in graph.calls:
            assert (call["src_path"], call["src_qname"]) in symbols
            assert (call["dst_path"], call["dst_qname"]) in symbols


class TestRelativeImports:
    def test_a_relative_import_resolves_against_the_importing_file(self) -> None:
        files = [
            SourceFile(path="pkg/util.py", content="def helper():\n    return 1\n", language="python"),
            SourceFile(
                path="pkg/main.py",
                content="from .util import helper\n\ndef go():\n    return helper()\n",
                language="python",
            ),
        ]

        graph = build_code_graph(files)

        assert {"src": "pkg/main.py", "dst": "pkg/util.py"} in graph.imports

    def test_a_package_init_satisfies_an_import_of_the_package(self) -> None:
        files = [
            SourceFile(path="pkg/__init__.py", content="X = 1\n", language="python"),
            SourceFile(path="app.py", content="import pkg\n", language="python"),
        ]

        graph = build_code_graph(files)

        assert {"src": "app.py", "dst": "pkg/__init__.py"} in graph.imports


class TestRobustness:
    def test_an_unparseable_file_does_not_break_the_run(self) -> None:
        """A file for a newer Python, a generated stub, or a truncated download.
        One bad file must not cost the whole graph."""
        files = [
            *_repo(),
            SourceFile(path="broken.py", content="def (((:\n", language="python"),
        ]

        graph = build_code_graph(files)

        assert "broken.py" in {f["path"] for f in graph.files}
        assert graph.imports  # the rest still resolved

    def test_a_file_with_no_provider_is_skipped(self) -> None:
        """
        A file nobody can parse must be absent rather than half-present.

        This used `ui/app.ts` until the TypeScript provider existed — which is the
        test doing its job: the premise "no provider owns this" stopped being true,
        and it said so. A stylesheet has no provider and is not likely to gain one.
        """
        files = [*_repo(), SourceFile(path="ui/theme.css", content="body { color: red }")]

        graph = build_code_graph(files)

        assert "ui/theme.css" not in {f["path"] for f in graph.files}

    def test_typescript_now_has_a_provider(self) -> None:
        """The other half of the phase above: `.ts` used to be unparseable here."""
        files = [SourceFile(path="ui/app.ts", content="export function go() { return 1 }\n")]

        graph = build_code_graph(files)

        assert "ui/app.ts" in {f["path"] for f in graph.files}
        assert {s["name"] for s in graph.symbols} == {"go"}

    def test_an_empty_repository_produces_an_empty_graph(self) -> None:
        graph = build_code_graph([])

        assert graph.counts() == {
            "files": 0, "modules": 0, "symbols": 0,
            "imports": 0, "packages": 0, "calls": 0,
        }


class TestModules:
    def test_modules_carry_the_role_the_extractor_assigned(self) -> None:
        """The graph must speak the KB's vocabulary, not invent a second one."""
        graph = build_code_graph(_repo(), module_roles={"app/db": "data_access"})

        roles = {m["key"]: m["role"] for m in graph.modules}
        assert roles["app/db"] == "data_access"
        assert roles["app/services"] == "unknown"

    def test_each_file_names_the_module_that_contains_it(self) -> None:
        graph = build_code_graph(_repo())

        keys = {m["key"] for m in graph.modules}
        for entry in graph.files:
            assert entry["module_key"] in keys
