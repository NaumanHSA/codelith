from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "insecure-dev-secret"
    APP_DEBUG: bool = True
    SQLALCHEMY_ECHO: bool = False
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # JWT
    JWT_SECRET_KEY: str = "insecure-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # PostgreSQL
    DATABASE_URL: str = "postgresql+asyncpg://docuser:docpassword@localhost:5432/documentanything"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── LLM: one provider per tier ────────────────────────────────────────────
    # There are two tiers, and `app/llm/router.py` picks between them by task type,
    # never the caller. Each tier chooses its own provider independently, so the
    # common setup — a cheap local model summarising 45 modules while a hosted one
    # writes the prose — needs no code change, only these two values.
    #
    #   local  — any OpenAI-compatible endpoint: LM Studio, Ollama, vLLM, llama.cpp.
    #            Needs a base URL, a model name and the context length it is served
    #            with. The API key is ignored.
    #   openai — needs an API key and a model name. The base URL and context window
    #            have working defaults.
    LLM_QUALITY_PROVIDER: str = "local"
    LLM_FAST_PROVIDER: str = "local"

    # Local endpoint, shared by whichever tiers are set to `local`.
    LLM_LOCAL_BASE_URL: str = "http://localhost:1234/v1"
    LLM_LOCAL_QUALITY_MODEL: str = "local-model"
    LLM_LOCAL_FAST_MODEL: str = "local-model"
    # The context length the model is actually *served* with, which is a property of
    # how it was loaded, not of the model. Set it too high and requests 400 late in a
    # long job; too low and context is trimmed that would have fitted.
    LLM_LOCAL_CONTEXT_WINDOW: int = 21000
    # Ignored by local endpoints, which authenticate nothing. Present because the
    # OpenAI SDK requires a non-empty string.
    LLM_LOCAL_API_KEY: str = "not-needed"

    # OpenAI, or anything speaking its API at another base URL (Azure, a gateway).
    OPENAI_API_KEY: str = ""
    OPENAI_QUALITY_MODEL: str = "gpt-4o-mini"
    OPENAI_FAST_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_CONTEXT_WINDOW: int = 128_000

    LLM_MAX_TOKENS: int = 8192
    LLM_TEMPERATURE: float = 0.2
    # Stream completions so a cancelled job can abandon generation mid-flight rather
    # than waiting for the model to finish. Disable only to debug the transport.
    LLM_STREAMING: bool = True

    # ── Embeddings ────────────────────────────────────────────────────────────
    # Deliberately its own provider rather than following the quality tier. The
    # embedding model's output size is baked into `code_chunks.embedding` by the
    # migrations (`VECTOR_DIMENSIONS`), so switching it means a migration that
    # TRUNCATEs the table and a full re-ingest of every project. Moving the writing
    # model to OpenAI must not drag the embedder along with it.
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_MODEL: str = "text-embedding-ada-002"
    # Texts per embeddings request. Batching is what keeps ingestion off a
    # one-request-per-chunk path; lower it if the endpoint rejects large batches.
    EMBEDDING_BATCH_SIZE: int = 64

    # pgvector — must match your embedding model's output size (common: 1536, 1024, 768, 384)
    VECTOR_DIMENSIONS: int = 1536

    # ── Analysis (Phase 1: build the knowledge base) ──────────────────────────
    # Modules sent to the summarizer, largest first. Bounds cost on big repos.
    ANALYSIS_MAX_SUMMARISED_MODULES: int = 40
    # Source characters shown to the summarizer per module.
    ANALYSIS_MODULE_CONTEXT_CHARS: int = 6000
    # Ceiling on narratives written per knowledge base. The floor of evidence-justified
    # topics comes first, then whatever the selection call adds, up to this many. Each
    # is a quality-tier call, so this is the cost control for the stage.
    ANALYSIS_MAX_NARRATIVES: int = 12
    # Concurrent LLM calls in the summarizer and narrative writer. Narratives are the
    # binding constraint: 5 topics at 4-way concurrency is two serial batches. Tune to
    # what the endpoint sustains — too high and requests queue inside LM Studio.
    ANALYSIS_SUMMARY_CONCURRENCY: int = 6

    # ── Documentation site (the map analysis proposes) ────────────────────────
    # Ceiling on the site map `site_planner` may propose. Slugs are permanent and
    # every page is a future generation run, so an over-eager map is expensive in
    # both directions: 30 pages at one quality call per heading is roughly an hour.
    # The cap bounds the proposal; SITE_MAX_PAGES_PER_JOB will bound what one
    # composition job writes.
    SITE_MAX_PAGES: int = 30
    SITE_MAX_SECTIONS: int = 8
    # How many pages one composition job may write. Each page is a planning call
    # plus a quality-tier call per heading, so a whole 30-page site in one job is
    # roughly an hour — that has to be a deliberate choice, made a section at a
    # time, not something a stray request can trigger.
    SITE_MAX_PAGES_PER_JOB: int = 8
    # Headings planned within one page. A page is a page because it is readable in
    # one sitting; more than this and it wanted to be two pages.
    #
    # Left at 6 deliberately. C1 proposed cutting it to 4 and then measured every page
    # already planning exactly 4 against this cap — it is not the binding constraint,
    # and lowering it would only bite on the pages that legitimately want more.
    SITE_MAX_HEADINGS_PER_PAGE: int = 6
    # Words one heading should aim for, carried into the writer's prompt.
    #
    # This is the lever page length actually responds to. C1 measured 594 words per
    # heading against 555 before the anti-duplication fix — a number that had never
    # moved, and that multiplied by the heading count is the whole of page length.
    # 350 puts a 4-heading page near 1,400 words rather than 2,400.
    SITE_WORDS_PER_HEADING: int = 350
    # `###` levels the writer may add inside one heading. C1 found 75 subheadings
    # across four pages that nothing asked for — roughly 19 per page under 4 planned
    # headings. A word budget answered by fragmenting into more sub-structure has not
    # been obeyed, so the budget and this cap have to travel together.
    SITE_MAX_SUBHEADINGS_PER_SECTION: int = 3

    # ── Composition (Phase 2: write docs from the knowledge base) ─────────────
    # Token ceiling for one section's retrieved context bundle.
    COMPOSITION_SECTION_TOKEN_BUDGET: int = 6000
    # Concurrent section-writing LLM calls.
    COMPOSITION_SECTION_CONCURRENCY: int = 4

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4jpassword"

    # MinIO / S3
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "documentanything"
    S3_REGION: str = "us-east-1"

    # OAuth2 (Phase 4)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # Observability
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"

    # Ingestion scratch dir (legacy — new jobs use sandbox)
    REPO_SCRATCH_DIR: str = "/tmp/repos"

    # Per-job sandbox
    JOB_SANDBOX_BASE_DIR: str = "/tmp/jobs"

    # ── Diagrams ──────────────────────────────────────────────────────────────
    # Off by default. The stage works — job 11 produced two grounded, rendered
    # diagrams — but it costs a quality-tier call per diagram plus a browser render,
    # and it is the least load-bearing thing composition does. Turn it on with
    # DIAGRAMS_ENABLED=true; everything behind this flag (derivation, grounding
    # checks, Mermaid validation, PNG rendering) stays in place and tested.
    DIAGRAMS_ENABLED: bool = False
    # Mermaid source only becomes a picture if the reader can render it, and neither
    # the studio's markdown pipeline nor a DOCX export can. Diagrams are rendered to
    # PNG locally via `node_modules/.bin/mmdc` (installed by the root package.json)
    # and embedded in the document; the Mermaid source is kept alongside them.
    DIAGRAM_RENDER_PNG: bool = True
    # Empty means: use the local install, else `mmdc` on PATH.
    MERMAID_CLI_PATH: str = ""
    DIAGRAM_RENDER_TIMEOUT_SECONDS: int = 60
    # Ceiling on one embedded image. Data URIs are copied with the document, so an
    # enormous render is dropped in favour of publishing the source.
    DIAGRAM_MAX_PNG_BYTES: int = 1_500_000

    # ── Step artifacts ────────────────────────────────────────────────────────
    # What each agent actually produced — architecture map, section plan, strategy,
    # narratives, the context a section was written from — dumped verbatim to
    # ./runs/{job_id}/artifacts/. The tracer records that a stage ran; this records
    # what it made. Set ARTIFACTS_ENABLED=false to switch the whole thing off.
    ARTIFACTS_ENABLED: bool = True
    # Inputs (prompt payloads, retrieved context, inventories) are far larger than
    # the outputs they produce, so they are gated separately.
    ARTIFACTS_INCLUDE_INPUTS: bool = True
    # Per-file ceiling. 0 disables truncation.
    ARTIFACTS_MAX_CHARS: int = 400_000

    # Tracing
    TRACING_ENABLED: bool = True
    TRACING_LOG_STEPS: bool = True
    TRACING_SAVE_JSON: bool = True
    TRACING_SAVE_MARKDOWN: bool = True
    TRACING_MAX_OUTPUT_PREVIEW_CHARS: int = 4000
    TRACING_INDENT_SPACES: int = 4
    TRACING_SHOW_INPUTS: bool = False
    TRACING_SHOW_OUTPUTS: bool = True
    TRACING_MAX_PREVIEW_CHARS: int = 300

    # ReAct agents
    REACT_MAX_ITERATIONS: int = 20
    REACT_SECTION_MAX_ITERATIONS: int = 8  # tool rounds for one writer section
    REACT_CONTEXT_WINDOW_LIMIT: int = 14000   # single-shot _call_llm trim target
    REACT_CONTEXT_WINDOW_MAX: int = 8000

    # ReAct context compaction (intelligent LLM summarisation)
    # (The model's real context window is a property of the endpoint, not a global —
    #  see LLM_LOCAL_CONTEXT_WINDOW / OPENAI_CONTEXT_WINDOW, resolved per tier by
    #  `app/llm/providers.py`.)
    REACT_TOOL_RESULT_MAX_CHARS: int = 4000    # cap one tool result (~1k tokens)
    REACT_COMPACT_THRESHOLD_TOKENS: int = 9000 # compact conversation when it grows past this
    REACT_COMPACT_KEEP_LAST: int = 8           # verbatim recent messages kept after a summary

    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}")
        return v

    @field_validator("LLM_QUALITY_PROVIDER", "LLM_FAST_PROVIDER", "EMBEDDING_PROVIDER")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """
        Fail at startup rather than at the first LLM call.

        A typo here otherwise surfaces as a connection error deep inside a job, after
        a repository has already been cloned and embedded.
        """
        provider = (v or "").strip().lower()
        allowed = {"local", "openai"}
        if provider not in allowed:
            raise ValueError(f"provider must be one of {sorted(allowed)}, got {v!r}")
        return provider

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
