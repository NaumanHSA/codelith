"""
Modules, as something to browse rather than count.

The codebase page has shown a radar of role *counts* since it was built: five
numbers standing in for twenty modules, each of which has a written summary that
cost a call to produce and has never been on screen.

Everything here is stored verbatim by analysis, so unlike the architecture map
almost none of it needs defending. The two judgements are that test modules are
included (591 lines of tests is a fact about a project, not noise to filter at the
source) and that a module carries its file list, because a module a reader cannot
open is another summary they have to take on trust.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModuleOut(BaseModel):
    #: Stable key: repo-relative, POSIX separators.
    path: str
    #: What a person calls it, e.g. "src.session".
    name: str
    #: Provider-decided: package, file, and so on.
    kind: str = ""
    #: Inferred during analysis: service, api, utility, config, test.
    role: str = ""
    language: str = ""
    file_count: int = 0
    loc: int = 0
    is_test: bool = False
    #: The prose written for this module. Empty for test modules, which are
    #: deliberately not summarised.
    summary: str = ""
    #: Repo-relative paths. These open in the code viewer, which is the point.
    files: list[str] = Field(default_factory=list)
    symbols: int = 0


class ModulesOut(BaseModel):
    available: bool = False
    commit_sha: str | None = None
    modules: list[ModuleOut] = Field(default_factory=list)
    #: Counted rather than hidden. A module with no summary is one the reader
    #: should know was not written about.
    without_summary: int = 0
    total_loc: int = 0


__all__ = ["ModuleOut", "ModulesOut"]
