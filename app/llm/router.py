from app.config import get_settings


def select_model(task_type: str) -> str:
    """Return the appropriate model name based on task requirements."""
    settings = get_settings()

    quality_tasks = {"write", "review", "validate", "architecture"}
    fast_tasks = {"plan", "classify", "extract", "diagram", "summarize"}

    if task_type in quality_tasks:
        return settings.LLM_QUALITY_MODEL
    elif task_type in fast_tasks:
        return settings.LLM_FAST_MODEL
    return settings.LLM_DEFAULT_MODEL
