"""
QA's mechanical fixes (`apps/qa/fixes.py`), its two write-ups (`apps/qa/report.py`),
and the CI gate of `codelith qa`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from codelith.apps.qa import fixes, report
from codelith.cli.commands import cmd_qa, gate
from codelith.cli.render import Output
from codelith.models.qa import QAFinding, QARun


class TestFixes:
    @pytest.mark.parametrize(
        ("rule", "line", "fixed"),
        [
            ("py.bare-except", "    except:", "    except Exception:"),
            ("py.is-literal", 'if kind is "admin" or n is not 0:', 'if kind == "admin" or n != 0:'),
            ("py.debug-on", "app.run(debug=True)", "app.run(debug=False)"),
            ("py.debug-on", "DEBUG = True", "DEBUG = False"),
            ("py.tls-off", "requests.get(url, verify=False)", "requests.get(url, verify=True)"),
            ("py.unsafe-deserialization", "data = yaml.load(fh)", "data = yaml.safe_load(fh)"),
            ("py.weak-hash", "h = hashlib.md5(raw).hexdigest()", "h = hashlib.sha256(raw).hexdigest()"),
            ("py.no-timeout", 'r = requests.get(f"{base}/x", headers=h)', 'r = requests.get(f"{base}/x", headers=h, timeout=30)'),
            ("py.no-timeout", "r = httpx.post(url)", "r = httpx.post(url, timeout=30)"),
            ("ts.tls-off", "  rejectUnauthorized: false,", "  rejectUnauthorized: true,"),
            ("go.tls-off", "TLSClientConfig: &tls.Config{InsecureSkipVerify: true},", "TLSClientConfig: &tls.Config{InsecureSkipVerify: false},"),
        ],
    )
    def test_each_rewrite(self, rule, line, fixed) -> None:
        assert fixes.FIXES[rule](line) == fixed

    @pytest.mark.parametrize(
        ("rule", "line"),
        [
            ("py.unsafe-deserialization", "data = pickle.loads(raw)"),
            ("py.unsafe-deserialization", "yaml.load(fh, Loader=yaml.SafeLoader)"),
            ("py.no-timeout", "r = requests.get(url, timeout=5)"),
            ("py.no-timeout", "r = requests.get("),
            ("py.is-literal", "if x is None:"),
        ],
    )
    def test_no_patch_where_the_line_does_not_settle_it(self, rule, line) -> None:
        assert fixes.FIXES[rule](line) is None

    def test_a_patch_has_real_line_numbers_and_applies_back(self) -> None:
        lines = [f"line {i}" for i in range(1, 21)]
        lines[11] = "    except:"
        patch = fixes.patch_for("py.bare-except", "app/io.py", lines, 12)
        assert patch.startswith("--- a/app/io.py\n+++ b/app/io.py\n@@ -9,7 +9,7 @@")
        text = "\n".join(lines) + "\n"
        fixed = fixes.apply(text, patch)
        assert fixed.splitlines()[11] == "    except Exception:" and fixed.endswith("\n")
        assert fixes.apply(text.replace("line 10", "line ten"), patch) is None, "no fuzz: the context must match"

    def test_the_dependency_bump_now_has_real_line_numbers(self) -> None:
        from codelith.apps.qa.checks.online import _bump

        text = "\n".join(["flask>=2.0", "jinja2==2.10", "requests"]) + "\n"
        patch = _bump(text, 2, "jinja2", "3.1.4", "PyPI", "requirements.txt")
        assert "@@ -1,3 +1,3 @@" in patch and "+jinja2>=3.1.4" in patch
        assert fixes.apply(text, patch).splitlines()[1] == "jinja2>=3.1.4"


def _run() -> QARun:
    return QARun(
        id=7, project_id=1, areas_json=["security", "errors"], depth="quick", scope_json={"kind": "all"},
        summary_json={"commit": "abcdef1234", "scope": "the whole codebase", "notes": ["A note."]},
        finished_at=datetime(2026, 11, 12, tzinfo=UTC),
    )


def _finding(fid, rule, severity, title, path="app/a.py", line=3, patch=None, area="security", evidence=None) -> QAFinding:
    return QAFinding(
        id=fid, run_id=7, project_id=1, fingerprint=f"fp{fid}", rule=rule, area=area, severity=severity,
        confidence="confirmed", source="rule", title=title, message="Why.", fix="Do the thing.", path=path,
        line=line, patch=patch, evidence_json=evidence or {},
    )


FINDINGS = [
    _finding(1, "security.route-unguarded", "high", "Open route"),
    _finding(2, "py.tls-off", "high", "TLS off", patch="--- a/app/a.py\n+++ b/app/a.py\n@@ -3 +3 @@\n-x\n+y\n",
             evidence={"verified": "The tests ran again.", "fix_note": "Mind this."}),
    _finding(3, "breaks.install-fails", "critical", "Install fails", path="pyproject.toml", line=None),
    _finding(4, "py.bare-except", "low", "Bare except", area="errors"),
]


class TestReports:
    def test_the_fix_plan_is_by_severity_then_quickest_first(self) -> None:
        text = report.markdown(_run(), FINDINGS, "shop")
        assert text.startswith("# QA fix plan — shop\n")
        assert "**4 open**: 1 critical, 2 high, 1 low." in text
        assert text.index("## Critical (1)") < text.index("## High (2)") < text.index("## Low (1)")
        high = text[text.index("## High"): text.index("## Low")]
        assert high.index("TLS off") < high.index("Open route"), "the one with a patch is quicker"
        assert "- [ ] **TLS off** — `app/a.py:3` · small · confirmed" in text
        assert "  - Checked: The tests ran again." in text and "  - Note: Mind this." in text
        assert "  ```diff\n  --- a/app/a.py" in text
        assert "**Install fails** — `pyproject.toml` · large" in text
        assert "- A note." in text

    def test_sarif(self) -> None:
        doc = report.sarif(_run(), FINDINGS)
        assert doc["version"] == "2.1.0"
        run = doc["runs"][0]
        assert run["tool"]["driver"]["name"] == "Codelith QA"
        assert [r["ruleId"] for r in run["results"]] == ["breaks.install-fails", "security.route-unguarded", "py.tls-off", "py.bare-except"]
        first, tls = run["results"][0], run["results"][2]
        assert first["level"] == "error" and "region" not in first["locations"][0]["physicalLocation"]
        assert tls["locations"][0]["physicalLocation"] == {
            "artifactLocation": {"uri": "app/a.py", "uriBaseId": "%SRCROOT%"}, "region": {"startLine": 3}
        }
        assert tls["partialFingerprints"] == {"codelithFingerprint/v1": "fp2"}
        assert run["tool"]["driver"]["rules"][tls["ruleIndex"]]["id"] == "py.tls-off"
        assert run["versionControlProvenance"] == [{"revisionId": "abcdef1234"}]
        json.dumps(doc)


class TestTheGate:
    def test_counts_at_or_above(self) -> None:
        counts = {"critical": 0, "high": 2, "medium": 5, "low": 1}
        assert gate(counts, "critical") == 0
        assert gate(counts, "high") == 2
        assert gate(counts, "medium") == 7
        assert gate(counts, "never") == 0

    def test_the_command_fails_a_ci_step_and_writes_sarif(self, tmp_path, monkeypatch, capsys) -> None:
        import codelith.cli.commands as commands

        calls: list[tuple] = []

        class Api:
            def projects(self):
                return []

            def qa_catalog(self, pid):
                return {"areas": [{"id": "security"}, {"id": "errors"}]}

            def qa_start(self, pid, body):
                calls.append(("start", body))
                return {"id": 9, "status": "queued"}

            def qa_run(self, pid, rid):
                return {"id": 9, "status": "completed", "summary": {"open": 3, "files": 4, "by_severity": {"high": 1, "low": 2}}}

            def qa_report(self, pid, rid, fmt):
                calls.append(("report", fmt))
                return '{"version": "2.1.0"}'

        monkeypatch.setattr(commands, "ApiClient", Api)
        monkeypatch.setattr(commands, "_find_project", lambda api, ref: {"id": 1, "name": "shop"})
        monkeypatch.setattr(commands.time, "sleep", lambda s: None)
        sarif = tmp_path / "qa.sarif"
        args = SimpleNamespace(project="shop", target=".", areas="security", depth="quick", online=False,
                               fail_on="high", sarif=str(sarif), markdown=None)
        assert cmd_qa(args, Output(True)) == 1
        assert calls[0] == ("start", {"areas": ["security"], "depth": "quick", "online": False, "scope": {"kind": "all"}})
        assert ("report", "sarif") in calls and json.loads(sarif.read_text())["version"] == "2.1.0"
        assert json.loads(capsys.readouterr().out)["failing"] == 1
        args.fail_on = "critical"
        assert cmd_qa(args, Output(True)) == 0
