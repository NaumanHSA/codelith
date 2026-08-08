"""
The contract every language provider satisfies, as data.

Adding language three should not re-litigate language two. TypeScript surfaced the
real shape of the interface — locals are not symbols, export is the visibility
boundary, a resolver must never invent a file — and this freezes it before Go and
Java arrive to bend it again.

Each language contributes one `ConformanceCase`: a small repository written in that
language, plus what a correct provider must find in it. The assertions live once, in
`test_conformance.py`, and run identically against every case. A provider that needs
the suite changed to pass has found a genuine gap in the contract — or is wrong, and
those two outcomes should be argued about explicitly rather than papered over.

The fixtures deliberately include the things that broke previous providers:
a declaration inside a comment, a declaration inside a string, a local binding, and
an import of something that is not in the repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ConformanceCase:
    """One language's fixture repository and what must be found in it."""

    language: str
    #: `relative path -> source`. Must contain at least two files that import each other.
    files: dict[str, str]

    #: The file the assertions are mostly about.
    main_path: str
    #: Declarations that must be found in `main_path`, by name.
    expect_symbols: frozenset[str]
    #: Names that must NOT be found: locals, and anything written in a comment or a
    #: string literal. Every provider so far has failed at least one of these.
    reject_symbols: frozenset[str]

    #: Exported/public declarations in `main_path`.
    expect_public: frozenset[str] = frozenset()
    #: Declarations that exist but are not part of the module's surface.
    expect_non_public: frozenset[str] = frozenset()

    #: `main_path` imports this repository file. The resolver must find it.
    expect_import_target: str = ""
    #: A third-party import in `main_path`, and the package it belongs to.
    expect_external_package: str = ""

    #: A path that is a test, and one that is not.
    test_path: str = ""
    non_test_path: str = ""
    #: A path that is a way into the system, and one that merely looks like one.
    entrypoint_path: str = ""
    non_entrypoint_path: str = ""

    #: Manifest filename and a dependency that must be parsed out of it.
    manifest_path: str = ""
    manifest_source: str = ""
    expect_dependency: str = ""

    #: An environment variable read by `main_path`, and one named only in a comment.
    expect_env_var: str = ""
    reject_env_var: str = ""

    #: Symbols that must carry a parent (methods on a class/struct/receiver).
    expect_parented: dict[str, str] = field(default_factory=dict)


# ── Python ────────────────────────────────────────────────────────────────────

PYTHON = ConformanceCase(
    language="python",
    files={
        "pkg/__init__.py": "",
        "pkg/helpers.py": '''
def shared_helper():
    """Something another module imports."""
    return 1
''',
        "pkg/service.py": '''
"""A service. Mentions os.getenv("GHOST_VAR") in prose, which is not a read."""
import os
import json

from pkg.helpers import shared_helper

# def commented_out_function(): pass

TEMPLATE = "class StringClass: pass"


class UserService:
    """Public surface."""

    def fetch(self, key):
        local_binding = shared_helper()
        return local_binding

    def _internal(self):
        return os.getenv("DATABASE_URL")


def _private_helper():
    return 2
''',
    },
    main_path="pkg/service.py",
    expect_symbols=frozenset({"UserService", "fetch", "_internal", "_private_helper", "TEMPLATE"}),
    reject_symbols=frozenset({"commented_out_function", "StringClass"}),
    expect_public=frozenset({"UserService", "fetch", "TEMPLATE"}),
    expect_non_public=frozenset({"_internal", "_private_helper"}),
    expect_import_target="pkg/helpers.py",
    expect_external_package="",  # json/os are stdlib, correctly not dependencies
    test_path="tests/test_service.py",
    non_test_path="pkg/service.py",
    entrypoint_path="main.py",
    non_entrypoint_path="pkg/service.py",
    manifest_path="requirements.txt",
    manifest_source="fastapi==0.110.0\nuvicorn\n",
    expect_dependency="fastapi",
    expect_env_var="DATABASE_URL",
    reject_env_var="GHOST_VAR",
    expect_parented={"fetch": "UserService"},
)

# ── TypeScript ────────────────────────────────────────────────────────────────

TYPESCRIPT = ConformanceCase(
    language="typescript",
    files={
        "src/helpers.ts": "export function sharedHelper() { return 1 }\n",
        "src/service.ts": """\
import { useState } from 'react'
import { sharedHelper } from './helpers'

// export function commentedOutFunction() {}

const TEMPLATE = `export class StringClass {}`

export interface UserShape {
  id: number
}

export class UserService {
  private token = ''

  fetch(key: string) {
    const localBinding = sharedHelper()
    return localBinding
  }
}

function notExported() {
  return import.meta.env.DATABASE_URL
}
// also mentions import.meta.env.GHOST_VAR in a comment
""",
    },
    main_path="src/service.ts",
    expect_symbols=frozenset({"UserService", "UserShape", "fetch", "notExported", "TEMPLATE"}),
    reject_symbols=frozenset({"commentedOutFunction", "StringClass", "localBinding"}),
    expect_public=frozenset({"UserService", "UserShape"}),
    expect_non_public=frozenset({"notExported", "TEMPLATE"}),
    expect_import_target="src/helpers.ts",
    expect_external_package="react",
    test_path="src/service.test.ts",
    non_test_path="src/service.ts",
    entrypoint_path="src/main.ts",
    non_entrypoint_path="src/app/components/deeply/nested/index.ts",
    manifest_path="package.json",
    manifest_source='{"dependencies": {"react": "^19.0.0"}}',
    expect_dependency="react",
    expect_env_var="DATABASE_URL",
    reject_env_var="GHOST_VAR",
    expect_parented={"fetch": "UserService"},
)

# ── Go ────────────────────────────────────────────────────────────────────────

GO = ConformanceCase(
    language="go",
    files={
        "go.mod": "module github.com/acme/widget\n\ngo 1.22\n",
        "internal/helpers/helpers.go": """\
package helpers

func SharedHelper() int {
	return 1
}
""",
        "internal/service/service.go": """\
package service

import (
	"os"

	"github.com/acme/widget/internal/helpers"
	"github.com/gin-gonic/gin"
)

// func CommentedOutFunction() {}

const Template = "type StringStruct struct{}"

type UserService struct {
	token string
}

type UserShape interface {
	ID() int
}

func (s *UserService) Fetch(key string) int {
	localBinding := helpers.SharedHelper()
	return localBinding
}

func notExported() string {
	return os.Getenv("DATABASE_URL")
}

// also mentions os.Getenv("GHOST_VAR") in a comment
""",
    },
    main_path="internal/service/service.go",
    expect_symbols=frozenset({"UserService", "UserShape", "Fetch", "notExported", "Template"}),
    reject_symbols=frozenset({"CommentedOutFunction", "StringStruct", "localBinding"}),
    expect_public=frozenset({"UserService", "UserShape", "Fetch", "Template"}),
    expect_non_public=frozenset({"notExported"}),
    expect_import_target="internal/helpers/helpers.go",
    expect_external_package="github.com/gin-gonic/gin",
    test_path="internal/service/service_test.go",
    non_test_path="internal/service/service.go",
    entrypoint_path="cmd/widget/main.go",
    non_entrypoint_path="internal/service/service.go",
    manifest_path="go.mod",
    manifest_source="module github.com/acme/widget\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n)\n",
    expect_dependency="github.com/gin-gonic/gin",
    expect_env_var="DATABASE_URL",
    reject_env_var="GHOST_VAR",
    expect_parented={"Fetch": "UserService"},
)

# ── Java ──────────────────────────────────────────────────────────────────────

JAVA = ConformanceCase(
    language="java",
    files={
        "src/main/java/com/acme/helpers/Helpers.java": """\
package com.acme.helpers;

public class Helpers {
    public static int sharedHelper() {
        return 1;
    }
}
""",
        "src/main/java/com/acme/service/UserService.java": """\
package com.acme.service;

import com.acme.helpers.Helpers;
import org.springframework.stereotype.Service;

// public class CommentedOutClass {}

@Service
public class UserService {
    private String token;

    public static final String TEMPLATE = "class StringClass {}";

    public int fetch(String key) {
        int localBinding = Helpers.sharedHelper();
        return localBinding;
    }

    private String internal() {
        return System.getenv("DATABASE_URL");
    }
}

// also mentions System.getenv("GHOST_VAR") in a comment
""",
    },
    main_path="src/main/java/com/acme/service/UserService.java",
    expect_symbols=frozenset({"UserService", "fetch", "internal", "TEMPLATE"}),
    reject_symbols=frozenset({"CommentedOutClass", "StringClass", "localBinding"}),
    expect_public=frozenset({"UserService", "fetch", "TEMPLATE"}),
    expect_non_public=frozenset({"internal"}),
    expect_import_target="src/main/java/com/acme/helpers/Helpers.java",
    expect_external_package="org.springframework",
    test_path="src/test/java/com/acme/service/UserServiceTest.java",
    non_test_path="src/main/java/com/acme/service/UserService.java",
    entrypoint_path="src/main/java/com/acme/Application.java",
    non_entrypoint_path="src/main/java/com/acme/service/UserService.java",
    manifest_path="pom.xml",
    manifest_source="""\
<project>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
</project>
""",
    expect_dependency="org.springframework.boot:spring-boot-starter-web",
    expect_env_var="DATABASE_URL",
    reject_env_var="GHOST_VAR",
    expect_parented={"fetch": "UserService"},
)


ALL_CASES: tuple[ConformanceCase, ...] = (PYTHON, TYPESCRIPT, GO, JAVA)

__all__ = ["ConformanceCase", "ALL_CASES", "PYTHON", "TYPESCRIPT", "GO", "JAVA"]
