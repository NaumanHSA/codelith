"""
Vocabulary of the Knowledge Base.

These describe *product* concepts (a route, an entrypoint, a deployment narrative)
rather than *language* concepts (a class, a method) — those live in
`app.languages.taxonomy`. Keeping the two apart is what lets a Go or TypeScript
provider populate the same knowledge base as Python.

All values are persisted, so add members freely but never rename one.
"""

from __future__ import annotations

from enum import StrEnum


class KBStatus(StrEnum):
    """Lifecycle of a knowledge base build."""

    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    #: Built, but some stage failed — usable for composition with a warning.
    DEGRADED = "degraded"
    FAILED = "failed"
    #: Superseded by a newer build for the same project.
    STALE = "stale"

    @property
    def is_usable(self) -> bool:
        return self in (KBStatus.READY, KBStatus.DEGRADED)

    @property
    def can_serve_features(self) -> bool:
        """
        Whether a feature may run against this build.

        Wider than `is_usable` by one status, deliberately. A `STALE` build has been
        superseded by a newer one for the same project — the code has moved on, and
        what it holds is a true account of an older commit. Refusing to answer from it
        would mean the studio goes dark the moment somebody pushes, which is worse
        than answering from a KB whose age the reader can see.

        Three services had each written this triple out by hand, and one of them had
        drifted to `is_usable` and quietly refused stale builds. This is the one
        definition.
        """
        return self in (KBStatus.READY, KBStatus.DEGRADED, KBStatus.STALE)

    @property
    def is_terminal(self) -> bool:
        return self in (KBStatus.READY, KBStatus.DEGRADED, KBStatus.FAILED, KBStatus.STALE)


class EntityKind(StrEnum):
    """
    A discrete, factual thing found in a codebase.

    Deliberately language-neutral: an HTTP route is a route whether it came from a
    FastAPI decorator, an Express call, or a Spring annotation.
    """

    ROUTE = "route"
    ENTRYPOINT = "entrypoint"
    SERVICE = "service"
    DEPENDENCY = "dependency"
    ENV_VAR = "env_var"
    CONFIG_FILE = "config_file"
    DATASTORE = "datastore"
    EXTERNAL_API = "external_api"
    CLI_COMMAND = "cli_command"
    SCHEDULED_TASK = "scheduled_task"
    EVENT = "event"
    INFRA_RESOURCE = "infra_resource"
    TEST_SUITE = "test_suite"


class NarrativeTopic(StrEnum):
    """
    Cross-cutting prose generated once per knowledge base and reused by every
    document type. These are doc-type-independent on purpose.
    """

    OVERVIEW = "overview"
    ARCHITECTURE = "architecture"
    REQUEST_LIFECYCLE = "request_lifecycle"
    DATA_MODEL = "data_model"
    AUTH = "auth"
    CONFIGURATION = "configuration"
    DEPLOYMENT = "deployment"
    TESTING = "testing"
    ERROR_HANDLING = "error_handling"
    INTEGRATIONS = "integrations"
    # The ten above assume a request/response service. These cover the shapes that
    # assumption misses — CLIs, libraries, frontends, pipelines and frameworks.
    CONCURRENCY = "concurrency"
    EXTENSIBILITY = "extensibility"
    CLI_USAGE = "cli_usage"
    OBSERVABILITY = "observability"
    BUILD_AND_RELEASE = "build_and_release"
    STATE_MANAGEMENT = "state_management"
    PERFORMANCE = "performance"


class ModuleRole(StrEnum):
    """
    What a module is *for*, inferred during analysis. Drives section planning — an
    API reference cares about `api` and `schema` modules, a deployment guide about
    `infra`.
    """

    API = "api"
    SERVICE = "service"
    DATA_ACCESS = "data_access"
    MODEL = "model"
    SCHEMA = "schema"
    WORKER = "worker"
    UI = "ui"
    CLI = "cli"
    CONFIG = "config"
    INFRA = "infra"
    TEST = "test"
    UTILITY = "utility"
    UNKNOWN = "unknown"


class PageStatus(StrEnum):
    """
    Lifecycle of one page of a documentation site.

    A site is grown a section at a time, so most pages spend most of their life
    `planned`: known to the map, listed in the nav, not yet written. Nothing here
    ever deletes — a page that analysis stops proposing becomes `orphaned` rather
    than vanishing, because its slug is a URL somebody may have bookmarked.
    """

    #: In the map, not yet written. The nav shows it greyed with a Generate action.
    PLANNED = "planned"
    GENERATING = "generating"
    READY = "ready"
    #: Written, but the code it was written from has moved on.
    STALE = "stale"
    #: No longer proposed by analysis. Kept, and readable, but off the live nav.
    ORPHANED = "orphaned"
    FAILED = "failed"

    @property
    def has_content(self) -> bool:
        """Whether a reader can open this page and find prose."""
        return self in (PageStatus.READY, PageStatus.STALE, PageStatus.ORPHANED)


#: Job kinds — analysis builds the KB, composition consumes it.
class JobType(StrEnum):
    ANALYSIS = "analysis"
    COMPOSITION = "composition"
    #: A targeted edit to prose that already exists: one heading of a page, or a
    #: whole page, rewritten against instructions the user gave. Distinct from
    #: composition because it neither plans nor chooses what to write — the subject
    #: is already decided and the existing text is an input, not something to replace
    #: unseen.
    REVISION = "revision"


__all__ = [
    "KBStatus",
    "EntityKind",
    "NarrativeTopic",
    "ModuleRole",
    "PageStatus",
    "JobType",
]
