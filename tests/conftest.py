"""
Shared test configuration.

Deliberately free of database setup: unit tests must run with no infrastructure, as
`make test-unit` advertises. Anything needing Postgres lives in
`tests/integration/conftest.py`.

Event-loop scoping is configured in `pyproject.toml`
(`asyncio_default_*_loop_scope`); pytest-asyncio 1.x no longer supports overriding
the `event_loop` fixture here.
"""
