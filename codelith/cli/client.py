"""
Talking to a Codelith server, and remembering how.

The CLI is a client, not a second implementation. Everything it does goes through
the same HTTP API the studio uses, so there is exactly one place where a project is
created, an analysis is started, or a question is answered. A CLI that reached into
the database directly would be a second copy of the service layer, and the two would
drift the first time either changed.

That does mean a server has to be running. `codelith doctor` says so plainly when it
is not, and Phase 2 of the roadmap removes the requirement for the single-machine
case by running the same services in-process.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_API = "http://localhost:8000"

#: Where the token lives between invocations. Under the user's home rather than the
#: project, because one machine talks to one server and a credential checked into a
#: repository is a credential leaked.
CONFIG_DIR = Path(os.environ.get("CODELITH_HOME") or (Path.home() / ".codelith"))
CREDENTIALS = CONFIG_DIR / "credentials.json"


class CliError(Exception):
    """Anything the user should read as a sentence rather than a traceback."""


@dataclass
class Credentials:
    api_url: str
    token: str | None = None

    @classmethod
    def load(cls) -> Credentials:
        """
        Environment first, then the file, then the default.

        `CODELITH_TOKEN` exists so CI and scripts never have to run `login` — and so
        nothing has to write a secret to disk on a shared machine.
        """
        api = os.environ.get("CODELITH_API_URL")
        token = os.environ.get("CODELITH_TOKEN")

        stored: dict[str, Any] = {}
        if CREDENTIALS.exists():
            try:
                stored = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # A corrupt credentials file must not stop `doctor` from running and
                # explaining itself — that is the command you reach for when this
                # happens.
                stored = {}

        return cls(
            api_url=(api or stored.get("api_url") or DEFAULT_API).rstrip("/"),
            token=token or stored.get("token"),
        )

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CREDENTIALS.write_text(
            json.dumps({"api_url": self.api_url, "token": self.token}, indent=2),
            encoding="utf-8",
        )
        # Best effort: POSIX honours it, Windows ignores it, and neither should stop
        # a login from succeeding.
        try:
            CREDENTIALS.chmod(0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass


class ApiClient:
    """A thin, synchronous wrapper. The CLI is one request at a time by nature."""

    def __init__(self, creds: Credentials | None = None, timeout: float = 30.0) -> None:
        self.creds = creds or Credentials.load()
        self._timeout = timeout

    # ── plumbing ──────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.creds.token:
            h["Authorization"] = f"Bearer {self.creds.token}"
        return h

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict | None = None,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self.creds.api_url}/api/v1{path}"
        try:
            r = httpx.request(
                method,
                url,
                json=json_body,
                params=params,
                headers=self._headers(),
                timeout=timeout or self._timeout,
            )
        except httpx.ConnectError as exc:
            raise CliError(
                f"No Codelith server at {self.creds.api_url}.\n"
                "Start one with `make dev`, or point somewhere else with "
                "CODELITH_API_URL. `codelith doctor` checks the rest."
            ) from exc
        except httpx.TimeoutException as exc:
            raise CliError(f"{self.creds.api_url} did not answer in time.") from exc

        if r.status_code == 401:
            raise CliError("Not signed in, or the token has expired. Run `codelith login`.")
        if r.status_code >= 400:
            raise CliError(f"{method} {path} failed ({r.status_code}): {_detail(r)}")
        if not r.content:
            return None
        return r.json()

    def stream_sse(self, path: str, json_body: Any, timeout: float = 600.0):
        """
        Yield decoded `data:` payloads from a server-sent-event response.

        The answer stream is the only place the CLI needs this, and it is worth doing
        properly: printing tokens as they arrive is most of why a local model feels
        usable at all.
        """
        url = f"{self.creds.api_url}/api/v1{path}"
        try:
            with httpx.stream(
                "POST", url, json=json_body, headers=self._headers(), timeout=timeout
            ) as r:
                if r.status_code >= 400:
                    r.read()
                    raise CliError(f"POST {path} failed ({r.status_code}): {_detail(r)}")
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        try:
                            yield json.loads(line[6:])
                        except ValueError:
                            continue
        except httpx.ConnectError as exc:
            raise CliError(f"No Codelith server at {self.creds.api_url}.") from exc

    # ── the calls the commands need ───────────────────────────────────────────

    def login(self, email: str, password: str) -> str:
        data = self.request(
            "POST", "/auth/login", json_body={"email": email, "password": password}
        )
        return data["access_token"]

    def me(self) -> dict:
        return self.request("GET", "/auth/me")

    def projects(self) -> list[dict]:
        return self.request("GET", "/projects", params={"limit": 100})

    def project(self, project_id: int) -> dict:
        return self.request("GET", f"/projects/{project_id}")

    def create_with_source(
        self, name: str, source_type: str, url_or_path: str, branch: str | None
    ) -> dict:
        return self.request(
            "POST",
            "/projects/with-source",
            json_body={
                "name": name,
                "source_type": source_type,
                "url_or_path": url_or_path,
                "branch": branch,
            },
            # A probe clones or walks the source before answering, which is not fast.
            timeout=180.0,
        )

    def analyse(self, project_id: int) -> dict:
        return self.request("POST", f"/projects/{project_id}/analyze", json_body={})

    def job(self, job_id: int) -> dict:
        return self.request("GET", f"/jobs/{job_id}")

    def knowledge_base(self, project_id: int) -> dict:
        return self.request("GET", f"/projects/{project_id}/knowledge-base")

    def ask(self, project_id: int, question: str):
        yield from self.stream_sse(
            f"/projects/{project_id}/chat/stream", {"question": question}
        )

    def health(self) -> dict:
        r = httpx.get(f"{self.creds.api_url}/health", timeout=self._timeout)
        r.raise_for_status()
        return r.json()


def _detail(r: httpx.Response) -> str:
    """The server's own words when it has any, the status line when it does not."""
    try:
        body = r.json()
    except ValueError:
        return (r.text or "").strip()[:300] or r.reason_phrase
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list):  # FastAPI validation errors
        return "; ".join(str(d.get("msg", d)) for d in detail)
    return str(detail or body)[:300]
