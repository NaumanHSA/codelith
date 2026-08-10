"""
Quality — findings from the tools that already know, plus what each one touches.

Built. Q1–Q8: run the tools, rank findings by what they touch, measure the surface
nothing tests, audit the manifests offline, derive the layering the codebase
follows, and write tests for the gaps — none of which are executed.

The plan is `.dev/QA_AGENT_PLAN.md`, and the framing that decides its scope is there:
**every linter finds the bug; only Codelith knows what the bug touches.** Reimplementing
ruff and mypy would be a worse version of tools that are deterministic, fast and free.
Running them and explaining their output against the knowledge base is the product.

This is also the first app that will run **its own analysis pass** on top of the base
knowledge base — deeper call edges and symbol-to-test association that no other app
should pay for. Whatever shape that takes, the next app will copy it.
"""

from codelith.apps.qa.api import router
from codelith.apps.qa.service import QAReport, QAService

__all__ = ["QAReport", "QAService", "router"]
