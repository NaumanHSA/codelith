"""
QA: runs, what they found, and what people decided about it.

A run checks one reading in the areas asked for. Each finding carries a fingerprint
made from the rule, the file and the code itself — not the line number — so the next
run can say which findings are new, which are still open and which were fixed, and a
dismissal survives an edit that moves the line.

What people decide (dismissed, risk accepted) is kept apart from the findings, per
codebase and fingerprint: a finding is found again by every run, a decision is made
once.

The tables live here with every other model; the QA app writes them, and the base
reads them (`knowledge/findings.py`) so Ask and MCP can cite findings without
importing the app.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from codelith.db.base import Base, TimestampMixin
from codelith.db.types import json_column


class QARun(Base, TimestampMixin):
    __tablename__ = "qa_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kb_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The areas asked for: `security`, `leakage`, `errors`, ...
    areas_json: Mapped[list] = mapped_column(json_column(), nullable=False, default=list)
    #: `{"kind": "all"}`, `{"kind": "parts", "parts": [...]}`, `{"kind": "since", "kb_id": n}`.
    scope_json: Mapped[dict] = mapped_column(json_column(), nullable=False, default=dict)
    #: `quick`, `thorough` or `tests`.
    depth: Mapped[str] = mapped_column(String(20), nullable=False, default="quick")
    #: Whether anything was allowed to go online.
    online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: `queued`, `running`, `completed`, `failed`, `cancelled`.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    #: Counts, the checks that ran and the ones that could not, and why.
    summary_json: Mapped[dict] = mapped_column(json_column(), nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QAFinding(Base):
    __tablename__ = "qa_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("qa_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(40), nullable=False)
    rule: Mapped[str] = mapped_column(String(80), nullable=False)
    area: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    #: `confirmed`, `likely` or `suspected`.
    confidence: Mapped[str] = mapped_column(String(10), nullable=False, default="confirmed")
    #: What found it: `rule`, `check`, `tool`, `model`, `test`.
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="rule")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    #: Why it matters.
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: What to do about it.
    fix: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: A unified diff, when the fix is small and local enough to write.
    patch: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The lines it points at, as they were in the reading.
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: What the reading knows about where it is: part, reach, tests, routes, pages.
    impact_json: Mapped[dict] = mapped_column(json_column(), nullable=False, default=dict)
    #: Anything else the check had to say: the matched value's kind, a tool's code.
    evidence_json: Mapped[dict] = mapped_column(json_column(), nullable=False, default=dict)
    #: True when no earlier run of the same areas found it.
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_qa_findings_run_severity", "run_id", "severity"),
        Index("ix_qa_findings_project_fingerprint", "project_id", "fingerprint"),
    )


class QADesignedTest(Base, TimestampMixin):
    """
    A test the model wrote for code no test reached, or to reproduce a suspected
    finding, and what happened when it ran in the sandbox. Kept whole, so it can be
    read, copied and added to the codebase's own tests.
    """

    __tablename__ = "qa_designed_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("qa_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    #: The code it tests.
    target_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_name: Mapped[str] = mapped_column(Text, nullable=False)
    target_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Why this code: `untested` (nothing reached it) or `finding` (to reproduce one).
    reason: Mapped[str] = mapped_column(String(20), nullable=False, default="untested")
    runtime: Mapped[str] = mapped_column(String(20), nullable=False)
    framework: Mapped[str] = mapped_column(String(20), nullable=False)
    #: Where the file went in the copy, relative to the codebase's root.
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: The cases, as the model listed them before writing: name, what it checks, expected.
    cases_json: Mapped[list] = mapped_column(json_column(), nullable=False, default=list)
    #: Each case's outcome in the last run: name, outcome, message.
    results_json: Mapped[list] = mapped_column(json_column(), nullable=False, default=list)
    #: `passed`, `bug` (it fails and the code is at fault), `wrong` (gave up on the test),
    #: `did-not-run`.
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    #: How many times it was written: the first, and each correction.
    tries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Why the verdict, in a sentence or two.
    verdict: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: The end of what the last run printed.
    output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: The finding it raised or reproduced.
    finding_fingerprint: Mapped[str | None] = mapped_column(String(40), nullable=True)


class QAFindingState(Base, TimestampMixin):
    __tablename__ = "qa_finding_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(40), nullable=False)
    #: `dismissed` (not a problem) or `accepted` (a problem we live with).
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (UniqueConstraint("project_id", "fingerprint", name="uq_qa_state_project_fingerprint"),)


__all__ = ["QAFinding", "QAFindingState", "QARun"]
