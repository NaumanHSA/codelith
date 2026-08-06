from app.config import get_settings


def select_model(task_type: str) -> str:
    """Return the appropriate model name based on task requirements."""
    settings = get_settings()

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
        return settings.LLM_QUALITY_MODEL
    elif task_type in fast_tasks:
        return settings.LLM_FAST_MODEL
    return settings.LLM_DEFAULT_MODEL
