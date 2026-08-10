"""
Ask the code — questions answered from the knowledge base, with checked citations.

Everything this feature is lives in this package: the answer path, thread storage, and
its routes. It reads the knowledge base and writes only its own tables.

**It must not import another feature, and the knowledge base must not import it.**
`tests/unit/test_module_isolation.py` enforces both. The rule is what keeps the base
from becoming shaped like whichever feature was written most recently — which is the
thing this whole restructure exists to prevent.

ORM models stay in `app/models/`. The database is one schema with foreign keys across
features (`chat_threads.project_id`), SQLAlchemy wants a single declarative registry,
and Alembic autogenerates from one metadata object. Splitting the models would be
separation in name and coupling in fact.
"""

from codelith.apps.ask.api import router, threads_router
from codelith.apps.ask.service import AskService
from codelith.apps.ask.threads import ChatService

__all__ = ["AskService", "ChatService", "router", "threads_router"]
