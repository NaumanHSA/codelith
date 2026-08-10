"""
The legacy single-shot pipeline's agents, and the shared base class.

Documentation's own agents moved to `app/features/documentation/agents/` and are
deliberately *not* re-exported here — this package is part of the base, and the base
importing a feature is the coupling `tests/unit/test_module_isolation.py` exists to
stop. Import them from the feature.
"""

from codelith.agents.architecture import ArchitectureAgent
from codelith.agents.code_understanding import CodeUnderstandingAgent
from codelith.agents.coordinator import CoordinatorAgent
from codelith.agents.planner import PlannerAgent
from codelith.agents.repo_analyzer import RepoAnalyzerAgent
from codelith.agents.strategy import StrategyAgent
from codelith.agents.writer import WriterAgent

__all__ = [
    "CoordinatorAgent",
    "PlannerAgent",
    "RepoAnalyzerAgent",
    "CodeUnderstandingAgent",
    "ArchitectureAgent",
    "StrategyAgent",
    "WriterAgent",
]
