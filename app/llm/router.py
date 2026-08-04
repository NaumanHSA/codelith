from app.config import get_settings


def select_model(task_type: str) -> str:
    """Return the appropriate model name based on task requirements."""
    settings = get_settings()

    # `plan` is quality work despite producing short output: it fixes the document's
    # structure *and* the `key_files` every section's retrieval is anchored on.
    # Measured on a 1.2b model it returned architecture-shaped sections for an API doc
    # and zero key_files, which silently degrades the whole composition.
    quality_tasks = {"write", "review", "validate", "architecture", "plan"}
    fast_tasks = {"classify", "extract", "diagram", "summarize"}

    if task_type in quality_tasks:
        return settings.LLM_QUALITY_MODEL
    elif task_type in fast_tasks:
        return settings.LLM_FAST_MODEL
    return settings.LLM_DEFAULT_MODEL
