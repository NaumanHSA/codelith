"""
Tour — a guided walk through a codebase for someone new to it.

An app in the strict sense: it reads the knowledge base (the map, its columns, the
flows, the narratives, the reach of each file) and analysis does not know it exists.
"""

from codelith.apps.tour.api import router
from codelith.apps.tour.service import Stop, Tour, TourFile, TourService

__all__ = ["Stop", "Tour", "TourFile", "TourService", "router"]
