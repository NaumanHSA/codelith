"""
The legacy single-shot pipeline's agents, and the shared base class.

Documentation's own agents moved to `app/features/documentation/agents/` and are
deliberately *not* re-exported here — this package is part of the base, and the base
importing a feature is the coupling `tests/unit/test_module_isolation.py` exists to
stop. Import them from the feature.
"""

from app.agents.architecture import ArchitectureAgent
from app.agents.code_understanding import CodeUnderstandingAgent
from app.agents.coordinator import CoordinatorAgent
from app.agents.planner import PlannerAgent
from app.agents.repo_analyzer import RepoAnalyzerAgent
from app.agents.strategy import StrategyAgent
from app.agents.writer import WriterAgent

__all__ = [
    "CoordinatorAgent",
    "PlannerAgent",
    "RepoAnalyzerAgent",
    "CodeUnderstandingAgent",
    "ArchitectureAgent",
    "StrategyAgent",
    "WriterAgent",
]
