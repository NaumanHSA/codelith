"""
Quality — findings from the tools that already know, plus what each one touches.

Not built. The package exists so the app is registered, renders as planned in the
studio, and the isolation rules apply to it from the first line rather than being
retrofitted.

The plan is `.dev/QA_AGENT_PLAN.md`, and the framing that decides its scope is there:
**every linter finds the bug; only Codelith knows what the bug touches.** Reimplementing
ruff and mypy would be a worse version of tools that are deterministic, fast and free.
Running them and explaining their output against the knowledge base is the product.

This is also the first app that will run **its own analysis pass** on top of the base
knowledge base — deeper call edges and symbol-to-test association that no other app
should pay for. Whatever shape that takes, the next app will copy it.
"""
