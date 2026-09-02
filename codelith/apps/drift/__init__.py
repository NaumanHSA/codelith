"""
Drift — what changed between two readings, and what it makes wrong.

An app in the strict sense: it reads the knowledge base and adds something of its
own, and analysis does not know it exists.
"""

from codelith.apps.drift.api import router
from codelith.apps.drift.service import DriftReport, DriftService

__all__ = ["DriftService", "DriftReport", "router"]
