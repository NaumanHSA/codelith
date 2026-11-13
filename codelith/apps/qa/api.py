"""QA over HTTP: what can be checked, runs, findings, and decisions about them."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import PurePosixPath

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from codelith.apps.qa import sandbox
from codelith.apps.qa.areas import AREAS, DEPTHS
from codelith.apps.qa.checks import CHECKS
from codelith.apps.qa.rules import label as rule_label
from codelith.apps.qa.service import QAService, steps_for
from codelith.core.exceptions import ValidationError
from codelith.dependencies import CurrentUser, DbSession
from codelith.models.qa import QADesignedTest, QAFinding, QAFindingState, QARun
from codelith.services.project_service import ProjectService

router = APIRouter(prefix="/projects/{project_id}/qa", tags=["QA"])


class AreaOut(BaseModel):
    id: str
    label: str
    blurb: str
    looks_for: list[str]
    icon: str


class DepthOut(BaseModel):
    id: str
    label: str
    blurb: str
    available: bool
    why_not: str = ""


class CatalogOut(BaseModel):
    areas: list[AreaOut]
    depths: list[DepthOut]
    #: Whether any check may go online yet (the dependency audit, Q3).
    online_available: bool = False


class StartIn(BaseModel):
    areas: list[str]
    depth: str = "quick"
    scope: dict = Field(default_factory=lambda: {"kind": "all"})
    online: bool = False


class RunOut(BaseModel):
    id: int
    status: str
    areas: list[str]
    depth: str
    scope: dict
    online: bool
    kb_id: int | None
    job_id: int | None
    summary: dict
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    #: The job steps a run of these areas reports, in order, and where each stands.
    stages: list[str] = Field(default_factory=list)
    steps: list[dict] = Field(default_factory=list)


class FindingOut(BaseModel):
    id: int
    fingerprint: str
    rule: str
    #: The rule's short name, the same for every finding of it: what the page groups by.
    group: str = ""
    area: str
    severity: str
    confidence: str
    source: str
    title: str
    message: str
    fix: str
    patch: str | None = None
    path: str | None = None
    line: int | None = None
    end_line: int | None = None
    snippet: str = ""
    impact: dict = Field(default_factory=dict)
    is_new: bool = False
    #: `open`, `dismissed` or `accepted`, from what people decided.
    status: str = "open"
    reason: str = ""
    #: When the sandbox ran: what happened to the tests with the patch applied.
    verified: str | None = None
    #: What the patch changes beyond the line, when there is something to say.
    fix_note: str | None = None


class DesignedOut(BaseModel):
    id: int
    target_path: str
    target_name: str
    target_line: int | None
    #: `untested` or `finding`.
    reason: str
    runtime: str
    framework: str
    file_path: str
    code: str
    cases: list[dict]
    results: list[dict]
    #: `passed`, `bug`, `wrong`, `did-not-run`.
    outcome: str
    tries: int
    verdict: str
    output: str
    finding_fingerprint: str | None


def _designed_out(d: QADesignedTest) -> DesignedOut:
    return DesignedOut(
        id=d.id,
        target_path=d.target_path,
        target_name=d.target_name,
        target_line=d.target_line,
        reason=d.reason,
        runtime=d.runtime,
        framework=d.framework,
        file_path=d.file_path,
        code=d.code,
        cases=list(d.cases_json or []),
        results=list(d.results_json or []),
        outcome=d.outcome,
        tries=d.tries,
        verdict=d.verdict,
        output=d.output,
        finding_fingerprint=d.finding_fingerprint,
    )


class FindingDetailOut(FindingOut):
    #: `[line, text]` around the finding, as the reading kept the file; secrets masked.
    context: list[tuple[int, str]] = Field(default_factory=list)
    #: The designed test that raised or reproduced it.
    designed_test: DesignedOut | None = None


class StateIn(BaseModel):
    status: str
    reason: str = ""


def _run_out(run: QARun, steps: list[dict] | None = None) -> RunOut:
    return RunOut(
        id=run.id,
        status=run.status,
        areas=list(run.areas_json or []),
        depth=run.depth,
        scope=run.scope_json or {},
        online=run.online,
        kb_id=run.kb_id,
        job_id=run.job_id,
        summary=run.summary_json or {},
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
        stages=steps_for(list(run.areas_json or []), run.online, run.depth),
        steps=steps or [],
    )


def _finding_out(f: QAFinding, state: QAFindingState | None, cls=FindingOut, **extra) -> FindingOut:
    evidence = f.evidence_json or {}
    return cls(
        id=f.id,
        fingerprint=f.fingerprint,
        rule=f.rule,
        group=rule_label(f.rule),
        area=f.area,
        severity=f.severity,
        confidence=f.confidence,
        source=f.source,
        title=f.title,
        message=f.message,
        fix=f.fix,
        patch=f.patch,
        path=f.path,
        line=f.line,
        end_line=f.end_line,
        snippet=f.snippet,
        impact={
            **(f.impact_json or {}),
            **{k: evidence[k] for k in ("read_in", "entries", "params", "route") if k in evidence},
        },
        is_new=f.is_new,
        verified=evidence.get("verified"),
        fix_note=evidence.get("fix_note"),
        status=state.status if state else "open",
        reason=state.reason if state else "",
        **extra,
    )


@router.get("/catalog", response_model=CatalogOut)
async def catalog(project_id: int, db: DbSession, user: CurrentUser) -> CatalogOut:
    """What a run can look at, and how deep it can go."""
    await ProjectService(db).get(project_id, user)
    covered = {a for c in CHECKS for a in c.areas}
    return CatalogOut(
        areas=[
            AreaOut(id=a.id, label=a.label, blurb=a.blurb, looks_for=list(a.looks_for), icon=a.icon)
            for a in AREAS
            if a.id in covered
        ],
        depths=[DepthOut(id=d.id, label=d.label, blurb=d.blurb, available=d.available, why_not=d.why_not) for d in DEPTHS],
        online_available=True,
    )


class SandboxOut(BaseModel):
    ready: bool
    #: Why not, in a sentence; empty when ready.
    reason: str = ""


@router.get("/sandbox", response_model=SandboxOut)
async def sandbox_status(project_id: int, db: DbSession, user: CurrentUser) -> SandboxOut:
    """Whether Docker answers, for the run dialog to say before a run rather than after."""
    await ProjectService(db).get(project_id, user)
    why = await sandbox.docker_ready(sandbox.Runner())
    return SandboxOut(ready=why is None, reason=why or "")


@router.post("/runs", response_model=RunOut, status_code=202)
async def start(project_id: int, body: StartIn, db: DbSession, user: CurrentUser) -> RunOut:
    """Start a run against the newest reading. It runs on the worker; poll the run."""
    await ProjectService(db).get(project_id, user)
    run = await QAService(db).start(
        project_id, user, areas=body.areas, depth=body.depth, scope=body.scope, online=body.online
    )
    return _run_out(run)


@router.get("/runs", response_model=list[RunOut])
async def runs(project_id: int, db: DbSession, user: CurrentUser) -> list[RunOut]:
    """Every run, newest first."""
    await ProjectService(db).get(project_id, user)
    return [_run_out(r) for r in await QAService(db).runs(project_id)]


@router.get("/runs/{run_id}", response_model=RunOut)
async def run(project_id: int, run_id: int, db: DbSession, user: CurrentUser) -> RunOut:
    await ProjectService(db).get(project_id, user)
    service = QAService(db)
    found = await service.get_run(project_id, run_id)
    return _run_out(found, await service.steps(found))


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel(project_id: int, run_id: int, db: DbSession, user: CurrentUser) -> RunOut:
    await ProjectService(db).get(project_id, user)
    return _run_out(await QAService(db).cancel(project_id, run_id, user))


@router.get("/runs/{run_id}/findings", response_model=list[FindingOut])
async def findings(project_id: int, run_id: int, db: DbSession, user: CurrentUser) -> list[FindingOut]:
    """Everything a run found, most severe first, each with what people decided about it."""
    await ProjectService(db).get(project_id, user)
    service = QAService(db)
    states = await service.states(project_id)
    return [_finding_out(f, states.get(f.fingerprint)) for f in await service.findings(project_id, run_id)]


@router.get("/findings/{finding_id}", response_model=FindingDetailOut)
async def finding(project_id: int, finding_id: int, db: DbSession, user: CurrentUser) -> FindingDetailOut:
    """One finding with the code around it."""
    await ProjectService(db).get(project_id, user)
    service = QAService(db)
    found, context = await service.finding(project_id, finding_id)
    states = await service.states(project_id)
    test = await service.designed_for(found)
    return _finding_out(
        found, states.get(found.fingerprint), FindingDetailOut, context=context,
        designed_test=_designed_out(test) if test is not None else None,
    )


@router.get("/runs/{run_id}/report")
async def report(
    project_id: int,
    run_id: int,
    db: DbSession,
    user: CurrentUser,
    format: str = "markdown",
    include: str = "open",
) -> Response:
    """
    The run written out: `markdown` (a fix plan, most severe and quickest first) or
    `sarif` (SARIF 2.1.0, for GitHub code scanning). Open findings only, unless
    `include=all`.
    """
    import json

    from codelith.apps.qa import report as qa_report
    from codelith.models.project import Project

    if format not in ("markdown", "sarif"):
        raise ValidationError("format is markdown or sarif.")
    await ProjectService(db).get(project_id, user)
    service = QAService(db)
    run = await service.get_run(project_id, run_id)
    states = await service.states(project_id)
    rows = [
        f for f in await service.findings(project_id, run_id)
        if include == "all" or states.get(f.fingerprint) is None or states[f.fingerprint].status == "open"
    ]
    project = await db.get(Project, project_id)
    if format == "sarif":
        body = json.dumps(qa_report.sarif(run, rows), indent=2)
        media, name = "application/sarif+json", f"qa-run-{run_id}.sarif"
    else:
        body = qa_report.markdown(run, rows, project.name if project else "this codebase")
        media, name = "text/markdown; charset=utf-8", f"qa-run-{run_id}-fix-plan.md"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/runs/{run_id}/designed", response_model=list[DesignedOut])
async def designed(project_id: int, run_id: int, db: DbSession, user: CurrentUser) -> list[DesignedOut]:
    """The tests the run designed, passing or not, each with its cases and what happened."""
    await ProjectService(db).get(project_id, user)
    return [_designed_out(d) for d in await QAService(db).designed(project_id, run_id)]


_OUTCOME_WORDS = {
    "passed": "passes",
    "bug": "fails, and the code was judged at fault",
    "wrong": "given up on: judged a wrong test after two corrections",
    "did-not-run": "not run",
}


@router.get("/runs/{run_id}/designed/archive")
async def designed_archive(project_id: int, run_id: int, db: DbSession, user: CurrentUser) -> Response:
    """
    The designed tests that are worth keeping — the passing ones and the ones that found
    a bug — at the paths they ran from, with a README saying what each one is.
    """
    await ProjectService(db).get(project_id, user)
    tests = [d for d in await QAService(db).designed(project_id, run_id) if d.outcome in ("passed", "bug") and d.code]
    buffer = io.BytesIO()
    readme = [f"# Tests designed by QA run #{run_id}", ""]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for d in tests:
            archive.writestr(d.file_path, d.code)
            readme.append(f"- `{d.file_path}` tests `{d.target_name}` in `{d.target_path}`: {_OUTCOME_WORDS[d.outcome]}.")
            if d.outcome == "bug" and d.verdict:
                readme.append(f"  {d.verdict}")
        if not tests:
            readme.append("No designed test passed or found a bug, so there is nothing here to keep.")
        readme += ["", "Written by a model and run once in a clean container. Read each before adding it."]
        archive.writestr("README-codelith-qa.md", "\n".join(readme) + "\n")
    name = f"qa-run-{run_id}-designed-tests.zip"
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{PurePosixPath(name).name}"'},
    )


@router.put("/findings/{fingerprint}/state", response_model=FindingOut | None)
async def set_state(project_id: int, fingerprint: str, body: StateIn, db: DbSession, user: CurrentUser):
    """Dismiss a finding (not a problem), accept its risk, or open it again. Kept across runs."""
    await ProjectService(db).get(project_id, user)
    await QAService(db).set_state(project_id, fingerprint, body.status, body.reason.strip(), user)
    return None
