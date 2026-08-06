from app.llm.providers import FAST, QUALITY, ModelSpec, spec_for_tier


def select_tier(task_type: str) -> str:
    """Return the tier a task type belongs to."""
    # `plan` is quality work despite producing short output: it fixes the document's
    # structure *and* the `key_files` every section's retrieval is anchored on.
    # Measured on a 1.2b model it returned architecture-shaped sections for an API doc
    # and zero key_files, which silently degrades the whole composition.
    # `select` — choosing which narratives a codebase warrants — is judgement, not
    # classification. Measured on job 3 the fast tier proposed nothing usable at all,
    # leaving the deterministic floor to do the whole job. Same lesson as `plan`.
    # `diagram` joined them after job 6: on the fast tier the model reproduced the
    # worked example's *names* (LoginPage, Customer, P1) instead of its syntax, twice,
    # and emitted `class Diagram` with a space in the keyword. Both diagrams were
    # correctly rejected and the document shipped with none. Drawing a grounded diagram
    # is judgement, not formatting.
    quality_tasks = {"write", "review", "validate", "architecture", "plan", "select", "diagram"}
    fast_tasks = {"classify", "extract", "summarize"}

    if task_type in quality_tasks:
        return QUALITY
    if task_type in fast_tasks:
        return FAST
    # Anything unclassified degrades in cost, not in output.
    return QUALITY


def select_spec(task_type: str) -> ModelSpec:
    """
    The endpoint this task should be sent to — provider, model, URL and key.

    Callers take a whole spec rather than a model name because the two tiers may sit
    on different providers, and a name alone no longer says where to send the request.
    """
    return spec_for_tier(select_tier(task_type))


def select_model(task_type: str) -> str:
    """The model name for a task type. Prefer `select_spec` where the endpoint matters."""
    return select_spec(task_type).model


__all__ = ["select_tier", "select_spec", "select_model"]
