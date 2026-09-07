"""
The studio must not eat the API.

A single-page application needs a catch-all: the browser asks the server for
`/app/projects/1/code`, a route only the browser knows about, and the answer has to be
the application that knows what to do with it. That same catch-all will happily answer
`/api/v1/anything`, and an API client asking for a route that does not exist would get
an HTML page and a 200 instead of a JSON 404 — a failure that looks like success all
the way to whatever tried to parse it.

Registration order is the first defence and an explicit refusal is the second, because
order is easy to change by accident and hard to notice when it is wrong.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from codelith.core.studio import mount_studio


@pytest.fixture
def built(tmp_path):
    """A minimal built studio: a shell, a hashed asset, and nothing else."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>studio</title>", encoding="utf-8")
    (tmp_path / "assets" / "main-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(built, monkeypatch):
    """An app shaped like the real one: a real route, then the studio last."""
    monkeypatch.setattr("codelith.core.studio.studio_dir", lambda: built)

    app = FastAPI()

    @app.get("/api/v1/projects")
    async def projects() -> dict:
        return {"real": True}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    assert mount_studio(app) is True
    return TestClient(app)


class TestItServesTheApplication:
    def test_the_root_is_the_shell(self, client) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "<title>studio</title>" in r.text

    def test_a_client_side_route_survives_a_refresh(self, client) -> None:
        """
        The reason a catch-all exists at all. `/app/projects/1/code` is not a file and
        never will be; the server's job is to hand back the application.
        """
        r = client.get("/app/projects/1/code")
        assert r.status_code == 200
        assert "<title>studio</title>" in r.text

    def test_a_real_file_is_served_as_itself(self, client) -> None:
        assert client.get("/favicon.svg").text == "<svg/>"

    def test_hashed_assets_come_from_the_mount(self, client) -> None:
        r = client.get("/assets/main-abc123.js")
        assert r.status_code == 200 and "console.log" in r.text


class TestItDoesNotEatTheApi:
    def test_a_real_api_route_still_answers(self, client) -> None:
        assert client.get("/api/v1/projects").json() == {"real": True}

    def test_an_unknown_api_route_is_a_json_404_not_a_web_page(self, client) -> None:
        """
        The failure this file exists for. Registration order already keeps the real
        routes safe; this is about the ones that do not exist, where returning the
        shell would hand a client 200 and HTML where it expected a 404.
        """
        r = client.get("/api/v1/does-not-exist")
        assert r.status_code == 404
        assert "<title>" not in r.text

    def test_health_still_answers(self, client) -> None:
        assert client.get("/health").json() == {"status": "ok"}


class TestItRefusesToLeaveItsDirectory:
    @pytest.mark.parametrize(
        "path",
        ["../../../etc/passwd", "..%2f..%2fpyproject.toml", "assets/../../pyproject.toml"],
    )
    def test_traversal_gets_the_shell_not_the_file(self, client, path) -> None:
        """
        Anything that resolves outside the studio directory is not a file being
        served, whatever route was taken to name it. It falls through to the shell,
        which is the same answer any other unknown path gets.
        """
        r = client.get(f"/{path}")
        assert r.status_code in (200, 404)
        assert "pyproject" not in r.text and "root:" not in r.text


class TestWhenNothingWasBuilt:
    def test_mounting_is_a_no_op(self, monkeypatch) -> None:
        """
        The development arrangement: Vite on 5173, the API on 8000, no `dist/`. The
        API must come up exactly as it did before, with no catch-all swallowing
        anything.
        """
        monkeypatch.setattr("codelith.core.studio.studio_dir", lambda: None)
        app = FastAPI()

        @app.get("/api/v1/projects")
        async def projects() -> dict:
            return {"real": True}

        assert mount_studio(app) is False

        client = TestClient(app)
        assert client.get("/api/v1/projects").json() == {"real": True}
        assert client.get("/").status_code == 404
