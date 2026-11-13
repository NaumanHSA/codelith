"""
What kind of file each file is, for the atlas.

The order of the rules is the whole design: a test file that happens to declare a
route is still a test, a file that opens a database is data access whatever its module
is called, and the name of a file only decides when nothing analysis stored does.
"""

from __future__ import annotations

import pytest

from codelith.knowledge.atlas import FILE_KINDS, fact_kind, file_kind


class TestWhatAnalysisStoredDecides:
    def test_a_test_is_a_test_whatever_else_it_declares(self) -> None:
        """A test that starts a server is exercising a route, not serving one."""
        assert file_kind("tests/test_api.py", "service", True, {"route"}) == "test"

    def test_the_language_provider_recognises_a_test_the_module_flag_missed(self) -> None:
        """Go marks tests by suffix; the module flag is per package and can lag."""
        assert file_kind("pkg/server/handler_test.go", "service", False, set()) == "test"

    def test_an_entry_point_outranks_its_routes(self) -> None:
        assert file_kind("app/main.py", "api", False, {"entrypoint", "route"}) == "entry"

    def test_a_file_declaring_routes_is_the_api_surface(self) -> None:
        """224 of Neurosurfer's 355 files are `service` by role; this is what fixes that."""
        assert file_kind("app/server/routes.py", "service", False, {"route"}) == "api"

    def test_a_file_that_opens_a_datastore_is_data_access(self) -> None:
        assert file_kind("app/store.py", "service", False, {"datastore"}) == "data"

    def test_a_file_declaring_a_command_is_the_command_line(self) -> None:
        assert file_kind("app/cli/main.py", "service", False, {"cli_command"}) == "cli"

    @pytest.mark.parametrize(
        ("role", "kind"),
        [("api", "api"), ("data_access", "data"), ("schema", "model"), ("model", "model"),
         ("config", "config"), ("infra", "config"), ("utility", "util"), ("ui", "ui"),
         ("cli", "cli")],
    )
    def test_a_role_that_says_more_than_service_decides(self, role: str, kind: str) -> None:
        assert file_kind("src/anything.ts", role, False, set()) == kind


class TestTheNameDecidesOnlyWhenNothingElseDoes:
    @pytest.mark.parametrize("path", ["app/config.py", "src/settings.ts", "cmd/conf.go", "lib/app_config.py"])
    def test_configuration_is_named_alike_in_every_language(self, path: str) -> None:
        assert file_kind(path, "service", False, set()) == "config"

    @pytest.mark.parametrize("path", ["app/models.py", "src/types.ts", "pkg/models/user.go", "api/schemas.py"])
    def test_data_shapes_are_named_alike_in_every_language(self, path: str) -> None:
        assert file_kind(path, "service", False, set()) == "model"

    @pytest.mark.parametrize("path", ["app/utils.py", "src/helpers.ts", "pkg/util/strings.go", "lib/text_utils.py"])
    def test_helpers_are_named_alike_in_every_language(self, path: str) -> None:
        assert file_kind(path, "service", False, set()) == "util"

    def test_a_role_beats_the_name(self) -> None:
        """A utility module's `types.py` is still a utility, by what analysis said."""
        assert file_kind("lib/util/types.py", "utility", False, set()) == "util"

    def test_everything_else_is_a_service(self) -> None:
        assert file_kind("app/engine/loop.py", "service", False, set()) == "service"
        assert file_kind("app/engine/loop.py", None, False, set()) == "service"


class TestFactNodes:
    def test_an_environment_file_is_not_a_manifest(self) -> None:
        assert fact_kind("config_file", ".env.example") == "env"
        assert fact_kind("config_file", "pyproject.toml") == "config"

    def test_stores_and_outside_services(self) -> None:
        assert fact_kind("datastore", "Chroma") == "store"
        assert fact_kind("external_api", "api.openai.com") == "external"

    def test_every_kind_is_in_the_vocabulary_the_studio_draws(self) -> None:
        produced = {
            file_kind("tests/x.py", None, True, set()),
            file_kind("a.py", None, False, {"entrypoint"}),
            file_kind("a.py", None, False, {"route"}),
            file_kind("a.py", None, False, {"cli_command"}),
            file_kind("a.py", None, False, {"datastore"}),
            file_kind("config.py", None, False, set()),
            file_kind("models.py", None, False, set()),
            file_kind("a.py", "utility", False, set()),
            file_kind("a.ts", "ui", False, set()),
            file_kind("a.py", None, False, set()),
            fact_kind("config_file", ".env"),
            fact_kind("config_file", "x.toml"),
            fact_kind("datastore", "x"),
            fact_kind("external_api", "x"),
            # Project files a reading keeps.
            file_kind("pyproject.toml", None, False, set()),
            file_kind("poetry.lock", None, False, set()),
            file_kind(".env", None, False, set()),
            file_kind("Dockerfile", None, False, set()),
            file_kind(".github/workflows/ci.yml", None, False, set()),
            file_kind("Makefile", None, False, set()),
            file_kind("README.md", None, False, set()),
        }
        assert produced == set(FILE_KINDS)
