"""
Documentation — documents written from the knowledge base.

Everything the feature is lives here: its agents, its two workflows (compose and
revise), its services, its Celery tasks and its output formatters.

**It must not import another feature, and the base must not import it.**
`tests/unit/test_module_isolation.py` enforces both.

Two things deliberately stayed outside:

* **ORM models and Pydantic schemas** (`app/models/site.py`, `app/schemas/site.py`).
  The database is one schema with foreign keys across features, SQLAlchemy wants a
  single declarative registry, and Alembic autogenerates from one metadata object.
  Splitting them would be separation in name and coupling in fact.
* **The legacy single-shot pipeline** (`app/workflows/documentation_workflow.py` and
  the agents beside it). It is documentation's by rights, but it is kept working for
  one endpoint and nothing new goes in it — moving it would be churn on code that is
  on its way out.
"""
