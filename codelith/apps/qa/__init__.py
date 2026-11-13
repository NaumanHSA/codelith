"""
QA — what a QA engineer does, starting from what Codelith already knows about the code.

A run checks one reading in the areas asked for (security, data leakage, error
handling, things that will break, performance, configuration and deployment, tests),
through the files that reading kept. Each finding points at an exact line, says how
sure it is, what it touches (part, reach, routes, tests, pages) and how to fix it, and
is recognised again by the next run through its fingerprint.

An app in the strict sense: it reads the knowledge base and the base never imports it.
Its tables live in `models/qa.py`; the base reads findings through
`knowledge/findings.py`.
"""

from codelith.apps.qa.api import router
from codelith.apps.qa.service import QAService

__all__ = ["QAService", "router"]
