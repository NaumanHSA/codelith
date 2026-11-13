"""
A home for every file. What analysis said is kept; everything else is placed from the
code — tests with the tests, files for running the code with those, and the rest by
their folder or their imports — and each placement says why.
"""

from codelith.knowledge.services import OTHER, SCRIPTS, SETUP, TESTS, assign, place_files


def _parts(placed):
    return {path: p.part for path, p in placed.items()}


class TestWhatAnalysisSaidIsKept:
    def test_a_named_file_stays_where_analysis_put_it(self) -> None:
        placed = place_files(
            {"app/api/routes.py": "HTTP API", "app/api/other.py": None},
            {"app/api/routes.py": "api", "app/api/other.py": "service"},
            [("app/api/other.py", "app/store/db.py")],
        )
        assert placed["app/api/routes.py"].part == "HTTP API"
        assert placed["app/api/routes.py"].group == "component"

    def test_even_a_test_analysis_placed_stays_there(self) -> None:
        placed = place_files({"app/orders/test_orders.py": "Orders"}, {"app/orders/test_orders.py": "test"}, [])
        assert placed["app/orders/test_orders.py"].part == "Orders"

    def test_assign_says_which_pass_placed_a_module(self) -> None:
        architecture = {"services": [{"name": "Core", "modules": ["app.core.engine", "app.core.rules"]}]}
        why: dict[str, str] = {}
        got = assign(architecture, ["app.core", "app.core.engine", "app.core.rules", "app.core.engine.step"], why)
        assert got["app.core"] == got["app.core.engine.step"] == "Core"
        assert why["app.core.engine"].startswith("Analysis listed it")
        assert "2 of the 2 modules inside it" in why["app.core"]
        assert "`app.core.engine`" in why["app.core.engine.step"]


class TestFilesAnalysisSkipped:
    def test_tests_go_to_the_tests(self) -> None:
        placed = place_files({"tests/test_a.py": None}, {"tests/test_a.py": "test"}, [])
        assert placed["tests/test_a.py"].part == TESTS and placed["tests/test_a.py"].group == "tests"

    def test_files_for_running_the_code_go_to_build_and_run(self) -> None:
        placed = place_files({"pyproject.toml": None, "Dockerfile": None}, {"pyproject.toml": "manifest", "Dockerfile": "deploy"}, [])
        assert {p.part for p in placed.values()} == {SETUP}

    def test_a_clear_majority_of_folder_mates_decides(self) -> None:
        named = {
            "app/store/db.py": "Storage",
            "app/store/cache.py": "Storage",
            "app/store/queue.py": "Storage",
            "app/store/skipped.py": None,
        }
        placed = place_files(named, dict.fromkeys(named, "service"), [("app/store/skipped.py", "app/web/x.py")])
        assert placed["app/store/skipped.py"].part == "Storage"
        assert "3 of the 3 placed files beside it" in placed["app/store/skipped.py"].reason

    def test_a_split_folder_falls_to_imports(self) -> None:
        named = {
            "app/services/auth.py": "Auth",
            "app/services/billing.py": "Billing",
            "app/services/jobs.py": None,
            "app/db/models.py": "Persistence",
            "app/db/repo.py": "Persistence",
        }
        edges = [("app/services/jobs.py", "app/db/models.py"), ("app/services/jobs.py", "app/db/repo.py")]
        placed = place_files(named, dict.fromkeys(named, "service"), edges)
        assert placed["app/services/jobs.py"].part == "Persistence"
        assert placed["app/services/jobs.py"].reason == "It imports 2 files in this part."

    def test_being_imported_counts_as_much_as_importing(self) -> None:
        named = {"app/api/a.py": "API", "app/api/b.py": "API", "lib/helper.py": None}
        edges = [("app/api/a.py", "lib/helper.py"), ("app/api/b.py", "lib/helper.py")]
        placed = place_files(named, dict.fromkeys(named, "service"), edges)
        assert placed["lib/helper.py"].part == "API"
        assert placed["lib/helper.py"].reason == "2 files in this part import it."

    def test_imports_from_tests_say_nothing_about_where_a_file_belongs(self) -> None:
        named = {"tests/test_a.py": None, "tests/test_b.py": None, "lonely.py": None}
        edges = [("tests/test_a.py", "lonely.py"), ("tests/test_b.py", "lonely.py")]
        placed = place_files(named, {"tests/test_a.py": "test", "tests/test_b.py": "test", "lonely.py": "service"}, edges)
        assert placed["lonely.py"].part == OTHER

    def test_a_placement_becomes_evidence_for_the_next_round(self) -> None:
        # b imports a, a imports the store: a is placed first, then b from a.
        named = {"app/db/one.py": "Persistence", "x/a.py": None, "y/b.py": None}
        edges = [("x/a.py", "app/db/one.py"), ("y/b.py", "x/a.py")]
        placed = place_files(named, dict.fromkeys(named, "service"), edges)
        assert placed["x/a.py"].part == placed["y/b.py"].part == "Persistence"

    def test_the_order_files_are_given_in_does_not_matter(self) -> None:
        named = {"app/db/one.py": "Persistence", "app/api/r.py": "API", "z/mid.py": None, "a/mid.py": None}
        edges = [("z/mid.py", "app/db/one.py"), ("a/mid.py", "app/api/r.py"), ("a/mid.py", "z/mid.py")]
        kinds = dict.fromkeys(named, "service")
        forward = _parts(place_files(named, kinds, edges))
        backward = _parts(place_files(dict(reversed(list(named.items()))), kinds, list(reversed(edges))))
        assert forward == backward

    def test_a_script_with_no_ties_goes_to_scripts(self) -> None:
        placed = place_files({"scripts/seed.py": None, "main.py": None}, {"scripts/seed.py": "service", "main.py": "entry"}, [])
        assert placed["scripts/seed.py"].part == placed["main.py"].part == SCRIPTS

    def test_what_nothing_ties_anywhere_is_other_and_says_so(self) -> None:
        placed = place_files({"misc/loop.py": None}, {"misc/loop.py": "service"}, [])
        assert placed["misc/loop.py"].part == OTHER
        assert placed["misc/loop.py"].reason.startswith("Nothing ties it")

    def test_a_single_folder_mate_settles_a_file_with_no_imports(self) -> None:
        placed = place_files({"pkg/a.py": "Core", "pkg/b.py": None}, {"pkg/a.py": "service", "pkg/b.py": "service"}, [])
        assert placed["pkg/b.py"].part == "Core"
        assert "1 file beside it is in this part" in placed["pkg/b.py"].reason
