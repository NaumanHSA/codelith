from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import FastAPI, Response

job_total = Counter("docany_jobs_total", "Total documentation jobs", ["status"])
job_duration = Histogram("docany_job_duration_seconds", "Job duration in seconds")
llm_tokens_total = Counter("docany_llm_tokens_total", "Total LLM tokens used", ["model", "direction"])
agent_errors_total = Counter("docany_agent_errors_total", "Agent errors", ["agent"])


def register_metrics_endpoint(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
