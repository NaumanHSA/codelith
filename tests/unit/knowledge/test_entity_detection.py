"""
Entity detection.

The taxonomy declared thirteen kinds and the extractor produced four, so the nine
added here are the point of the phase. But the risk they carry is asymmetric: a
missed `datastore` is a gap, while a *wrong* one propagates into documentation,
diagrams and answers at once, and nothing downstream can tell it was inferred.

So most of these cases are about restraint — what must **not** be detected. Three of
them are regressions found by running the detectors over this repository, where the
patterns matched the comments that document them:

* `is_entrypoint` matched the comment explaining the `__main__` idiom, making the
  Python provider an entrypoint of every system it analysed.
* `os.getenv("X")` in a docstring became an environment variable named `X`.
* `https://example.com` in a Docusaurus config template became an integration.
"""

from __future__ import annotations

from app.knowledge.constants import EntityKind
from app.knowledge.detectors import detect_file_entities
from app.languages.providers.python import PythonProvider

provider = PythonProvider()


def entities(source: str, path: str = "app/thing.py") -> list:
    symbols = provider.extract_symbols(source, path)
    return provider.detect_entities(path, source, symbols)


def kinds(source: str, kind: str, path: str = "app/thing.py") -> list[str]:
    return [e.name for e in entities(source, path) if str(e.kind) == str(kind)]


class TestProseIsNotMinedForFacts:
    """The three regressions above. Each was found by pointing the detectors at this
    codebase and reading the output, not by imagining a case."""

    def test_a_commented_main_guard_is_not_an_entrypoint(self) -> None:
        source = '# This gates the `__name__ == "__main__"` heuristic.\nX = 1\n'

        assert provider.is_entrypoint("app/languages/providers/python.py", source) is False

    def test_a_real_main_guard_still_is(self) -> None:
        source = 'def go():\n    pass\n\nif __name__ == "__main__":\n    go()\n'

        assert provider.is_entrypoint("app/thing.py", source) is True

    def test_an_env_var_in_a_docstring_is_not_extracted(self) -> None:
        source = '"""Reads os.getenv("FAKE_VAR") to decide."""\nX = 1\n'

        assert kinds(source, EntityKind.ENV_VAR) == []

    def test_an_env_var_in_a_comment_is_not_extracted(self) -> None:
        source = '#: os.getenv("X"), os.environ["Y"]\nX = 1\n'

        assert kinds(source, EntityKind.ENV_VAR) == []

    def test_a_real_env_var_read_is_extracted(self) -> None:
        source = 'import os\n\nDB = os.getenv("DATABASE_URL")\nK = os.environ["API_KEY"]\n'

        assert set(kinds(source, EntityKind.ENV_VAR)) == {"DATABASE_URL", "API_KEY"}

    def test_a_url_in_a_docstring_is_not_an_integration(self) -> None:
        source = '"""See https://docs.example.org/guide for details."""\nX = 1\n'

        assert kinds(source, EntityKind.EXTERNAL_API) == []

    def test_a_placeholder_host_is_not_an_integration(self) -> None:
        """A Docusaurus config template carries `url: 'https://example.com'`. It is a
        real string literal, and it is not an integration."""
        source = "CONFIG = {'url': 'https://example.com'}\n"

        assert kinds(source, EntityKind.EXTERNAL_API) == []


class TestDatastores:
    def test_a_sqlalchemy_engine_is_a_datastore(self) -> None:
        source = (
            "from sqlalchemy.ext.asyncio import create_async_engine\n\n"
            "engine = create_async_engine(URL)\n"
        )

        assert kinds(source, EntityKind.DATASTORE) == ["SQLAlchemy async engine"]

    def test_redis_neo4j_and_s3_are_recognised(self) -> None:
        source = (
            "import boto3, redis\nfrom neo4j import AsyncGraphDatabase\n\n"
            "r = redis.Redis(host='x')\n"
            "d = AsyncGraphDatabase.driver(URI)\n"
            "s = boto3.client('s3')\n"
        )

        assert set(kinds(source, EntityKind.DATASTORE)) == {"Redis", "Neo4j", "Amazon S3"}

    def test_a_bare_connect_call_needs_a_driver_import(self) -> None:
        """`connect` is far too common a name to trust alone — a websocket client, a
        signal handler and a test helper all have one."""
        source = "def go(sock):\n    return sock.connect(addr)\n"

        assert kinds(source, EntityKind.DATASTORE) == []

    def test_connect_counts_when_a_driver_was_imported(self) -> None:
        source = "import asyncpg\n\nasync def go():\n    return await asyncpg.connect(DSN)\n"

        assert kinds(source, EntityKind.DATASTORE) == ["DB-API connection"]

    def test_an_unknown_boto_service_is_not_a_datastore(self) -> None:
        """`boto3.client('ses')` is email, not storage."""
        source = "import boto3\n\nc = boto3.client('ses')\n"

        assert kinds(source, EntityKind.DATASTORE) == []


class TestExternalApis:
    def test_an_sdk_client_names_its_vendor(self) -> None:
        source = "from openai import AsyncOpenAI\n\nclient = AsyncOpenAI(api_key=K)\n"

        assert kinds(source, EntityKind.EXTERNAL_API) == ["OpenAI"]

    def test_an_http_client_is_only_an_integration_with_a_base_url(self) -> None:
        """A bare `httpx.AsyncClient()` says nothing about what it talks to."""
        bare = "import httpx\n\nc = httpx.AsyncClient()\n"
        aimed = "import httpx\n\nc = httpx.AsyncClient(base_url='https://api.stripe.com/v1')\n"

        assert kinds(bare, EntityKind.EXTERNAL_API) == []
        assert kinds(aimed, EntityKind.EXTERNAL_API) == ["api.stripe.com"]

    def test_localhost_is_configuration_not_an_integration(self) -> None:
        source = "BASE = 'http://localhost:1234/v1'\n"

        assert kinds(source, EntityKind.EXTERNAL_API) == []

    def test_one_api_with_many_endpoints_is_one_entity(self) -> None:
        source = (
            "A = 'https://api.github.com/repos'\n"
            "B = 'https://api.github.com/users'\n"
            "C = 'https://api.github.com/issues'\n"
        )

        assert kinds(source, EntityKind.EXTERNAL_API) == ["api.github.com"]


class TestCliCommands:
    def test_a_click_command_is_detected(self) -> None:
        source = "import click\n\n@click.command()\ndef serve():\n    pass\n"

        assert kinds(source, EntityKind.CLI_COMMAND) == ["serve"]

    def test_a_typer_command_is_detected(self) -> None:
        source = "app = typer.Typer()\n\n@app.command()\ndef build():\n    pass\n"

        assert kinds(source, EntityKind.CLI_COMMAND) == ["build"]

    def test_an_http_route_is_not_a_cli_command(self) -> None:
        """`@router.get(...)` and `@app.command(...)` are one character apart in
        shape. Confusing them would put HTTP routes in the CLI reference."""
        source = '@router.get("/users")\nasync def list_users():\n    pass\n'

        assert kinds(source, EntityKind.CLI_COMMAND) == []
        assert kinds(source, EntityKind.ROUTE) == ["GET /users"]


class TestScheduledWork:
    def test_a_celery_task_is_scheduled_work(self) -> None:
        source = "@celery_app.task(name='x')\ndef run_it():\n    pass\n"

        assert kinds(source, EntityKind.SCHEDULED_TASK) == ["run_it"]

    def test_a_cron_expression_is_detected(self) -> None:
        source = "SCHEDULE = {'nightly': '0 3 * * *'}\n"

        assert kinds(source, EntityKind.SCHEDULED_TASK) == ["0 3 * * *"]

    def test_ordinary_prose_is_not_a_cron_expression(self) -> None:
        """Five whitespace-separated words is a very common shape for a sentence."""
        source = "MESSAGE = 'this has five words here'\n"

        assert kinds(source, EntityKind.SCHEDULED_TASK) == []


class TestEvents:
    def test_a_task_dispatch_is_an_event(self) -> None:
        source = "def go():\n    return run_revision.delay(7)\n"

        assert kinds(source, EntityKind.EVENT) == ["run_revision"]

    def test_a_named_pubsub_channel_is_an_event(self) -> None:
        source = "def go(r):\n    r.publish('jobs:cancelled', payload)\n"

        assert kinds(source, EntityKind.EVENT) == ["jobs:cancelled"]

    def test_a_publish_with_no_literal_channel_is_skipped(self) -> None:
        """A channel computed at runtime cannot be named, and a guess would be wrong
        for every value it takes."""
        source = "def go(r, chan):\n    r.publish(chan, payload)\n"

        assert kinds(source, EntityKind.EVENT) == []


class TestServices:
    def test_conventional_names_are_services(self) -> None:
        source = "class RevisionService:\n    pass\n\nclass DocPageRepository:\n    pass\n"

        assert set(kinds(source, EntityKind.SERVICE)) == {"RevisionService", "DocPageRepository"}

    def test_a_private_class_is_not_a_component(self) -> None:
        source = "class _CacheStore:\n    pass\n"

        assert kinds(source, EntityKind.SERVICE) == []

    def test_a_nested_class_is_not_a_component(self) -> None:
        source = "class Outer:\n    class InnerService:\n        pass\n"

        assert kinds(source, EntityKind.SERVICE) == []

    def test_an_ordinary_class_is_not_a_service(self) -> None:
        source = "class Block:\n    pass\n"

        assert kinds(source, EntityKind.SERVICE) == []


class TestFileEntities:
    def test_config_and_infrastructure_are_classified(self) -> None:
        rows = detect_file_entities([
            ".env.example", "pyproject.toml", "alembic.ini",
            "Dockerfile", "docker-compose.yml", "infra/main.tf",
            ".github/workflows/ci.yml", "k8s/api-deployment.yaml",
        ])
        by_kind = {}
        for row in rows:
            by_kind.setdefault(row["kind"], []).append(row["name"])

        assert set(by_kind[str(EntityKind.CONFIG_FILE)]) == {
            ".env.example", "pyproject.toml", "alembic.ini"
        }
        assert set(by_kind[str(EntityKind.INFRA_RESOURCE)]) == {
            "Dockerfile", "docker-compose.yml", "main.tf", "ci.yml", "api-deployment.yaml"
        }

    def test_a_plain_yaml_is_not_infrastructure(self) -> None:
        """`.yml` alone means nothing — it is a compose file, a CI pipeline or an
        application fixture depending entirely on where it sits."""
        rows = detect_file_entities(["app/fixtures/sample.yml", "docs/config.yaml"])

        assert [r for r in rows if r["kind"] == str(EntityKind.INFRA_RESOURCE)] == []

    def test_a_test_suite_is_the_directory_not_each_file(self) -> None:
        """A repository with 400 test files has a handful of suites. One entity per
        file would drown every other fact in the knowledge base."""
        rows = detect_file_entities([
            "tests/unit/test_a.py", "tests/unit/test_b.py",
            "tests/integration/test_c.py", "app/main.py",
        ])
        suites = [r for r in rows if r["kind"] == str(EntityKind.TEST_SUITE)]

        assert len(suites) == 1
        assert suites[0]["name"] == "tests"
        assert suites[0]["data_json"]["files"] == 3

    def test_every_entity_points_at_a_real_path(self) -> None:
        rows = detect_file_entities(["Dockerfile", ".env", "tests/test_a.py"])

        assert all(r["source_path"] for r in rows)
