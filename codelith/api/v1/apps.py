"""
The catalogue of what Codelith can do, independent of any one codebase.

`GET /projects/{id}/apps` answers "what can *this* project do", which needs a
knowledge base to judge. The dashboard asks a different question — "what does this
product do at all" — before any project is chosen, and answering it by hardcoding a
list in the studio would mean two places to update and one of them silently wrong.

Route templates come back with `{id}` unsubstituted. The studio fills it in once it
knows which codebase the reader meant, which is the whole difficulty the dashboard
has: a feature needs a project and the dashboard has none selected.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from codelith.dependencies import CurrentUser
from codelith.apps import APPS

router = APIRouter(prefix="/apps", tags=["Apps"])


class AppCatalogItem(BaseModel):
    id: str
    label: str
    blurb: str
    needs: list[str]
    #: Contains `{id}` — a project id, which the caller substitutes.
    route_template: str
    built: bool


@router.get("", response_model=list[AppCatalogItem])
async def list_apps(user: CurrentUser) -> list[AppCatalogItem]:
    """Every app, built or planned, with no project in the picture."""
    return [
        AppCatalogItem(
            id=f.id,
            label=f.label,
            blurb=f.blurb,
            needs=list(f.needs),
            route_template=f.route,
            built=f.built,
        )
        for f in APPS
    ]
