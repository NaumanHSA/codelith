"""
Prompts for the tests QA designs (`apps/qa/designed.py`).

The model writes a test file for one function — one nothing tests, or one a reviewer
suspects — listing its cases before the code. The file runs in the sandbox with no
network. When it fails, a second call decides whose fault that is: the code's (a
finding, with the output as evidence) or the test's (corrected and run again, twice
at most). When unsure, it is the test's: a designed test proves a bug only when the
expectation is plainly what the code promised.
"""

from __future__ import annotations

from codelith.llm.prompts.base import PromptTemplate

TEST_DESIGN = PromptTemplate(
    system=(
        "You design and write tests for code you did not write, the way a careful QA engineer does: "
        "you test what the code promises — by its name, signature, docstring, types and how it is "
        "used — and you look for the input that breaks it.\n\n"
        "The tests are ${language} for ${framework}. They will run:\n"
        "- with no network, no database server and no other service: replace anything outside the "
        "process (HTTP, databases, queues, the clock, randomness, files outside a temporary "
        "directory, environment variables) with fakes or mocks;\n"
        "- using only the test framework, the standard library and these packages the project "
        "declares: ${packages};\n"
        "- from the file ${test_path}. ${import_hint}\n\n"
        "Cover the normal case, the edges (empty, zero, missing, very large, the boundary of every "
        "condition in the code) and the failure paths (what it should raise or return). Each test "
        "checks one thing, says in its name what that is, and asserts something. Between 3 and 8 "
        "tests. Do not test private helpers through anything but the function named. Do not change "
        "or copy the code under test.\n${focus}\n${style}\n\n"
        "Return ONLY a JSON object, no prose and no markdown fences:\n"
        '{"cases": [{"name": "<the test\'s name>", "checks": "<what it checks>", '
        '"expect": "<what should happen>"}], "code": "<the whole test file>"}'
    ),
    user=(
        "Test `${function}` in ${path} (lines ${start}–${end}).\n${context}\n\n"
        "The file, each line numbered:\n${code}"
    ),
)

TEST_VERDICT = PromptTemplate(
    system=(
        "A test written for code it did not come with has failed. Decide whose fault that is.\n"
        "- bug: the code does the wrong thing. The test expects what the function plainly promises "
        "— by its name, signature, docstring and how it is used — and the code fails it, or it "
        "crashes on input its signature accepts.\n"
        "- wrong_test: the test is at fault. It expects something the code never promised, imports "
        "or calls it wrongly, sets it up wrongly, or depends on something that is not there (a "
        "network, a file, a service, a setting, a package).\n"
        "When you are not sure, it is wrong_test.\n\n"
        "Return ONLY a JSON object, no prose and no markdown fences:\n"
        '{"verdict": "bug|wrong_test", "why": "<what fails and why, two sentences at most>", '
        '"severity": "high|medium|low", "line": <for a bug: the line of the code at fault>, '
        '"fix": "<for a bug: what to change in the code>", '
        '"code": "<for wrong_test: the whole corrected test file>"}'
    ),
    user=(
        "The code under test, `${function}` in ${path}, each line numbered:\n${code}\n\n"
        "The test file (${test_path}):\n${test}\n\n"
        "What the run printed:\n${output}"
    ),
)

__all__ = ["TEST_DESIGN", "TEST_VERDICT"]
