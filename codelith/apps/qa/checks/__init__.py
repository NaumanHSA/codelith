"""Every check a run can do, in the order it does them."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from codelith.apps.qa.checks import (
    code,
    dependencies,
    deploy,
    environment,
    flows,
    online,
    review,
    sandbox,
    secrets,
    untested,
)
from codelith.apps.qa.context import RunContext
from codelith.apps.qa.findings import Finding


@dataclass(frozen=True, slots=True)
class Check:
    id: str
    title: str
    areas: frozenset[str]
    run: Callable[[RunContext], Awaitable[list[Finding]]]
    #: Asks outside services: runs only when the run is allowed online.
    online: bool = False
    #: The shallowest depth it runs at: `quick`, `thorough` or `tests`.
    depth: str = "quick"

    @property
    def step(self) -> str:
        """The job step this check reports as."""
        return f"qa_{self.id}"


CHECKS: tuple[Check, ...] = (
    Check("code", code.TITLE, code.AREAS, code.run),
    Check("flows", flows.TITLE, flows.AREAS, flows.run),
    Check("secrets", secrets.TITLE, secrets.AREAS, secrets.run),
    Check("deploy", deploy.TITLE, deploy.AREAS, deploy.run),
    Check("environment", environment.TITLE, environment.AREAS, environment.run),
    Check("dependencies", dependencies.TITLE, dependencies.AREAS, dependencies.run),
    Check("online", online.TITLE, online.AREAS, online.run, online=True),
    Check("untested", untested.TITLE, untested.AREAS, untested.run),
    Check("review", review.TITLE, review.AREAS, review.run, depth="thorough"),
    Check("sandbox", sandbox.TITLE, sandbox.AREAS, sandbox.run, depth="tests"),
)

#: Each depth includes the ones before it.
DEPTH_ORDER = {"quick": 0, "thorough": 1, "tests": 2}


def runs_at(check: Check, depth: str, online: bool) -> bool:
    return DEPTH_ORDER.get(depth, 0) >= DEPTH_ORDER.get(check.depth, 0) and (online or not check.online)


__all__ = ["CHECKS", "DEPTH_ORDER", "Check", "runs_at"]
