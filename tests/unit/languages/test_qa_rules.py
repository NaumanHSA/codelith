"""
QA's rules per language: each one fires on the pattern it is for, and stays quiet on
the near miss that real code is full of.
"""

from __future__ import annotations

import textwrap

import pytest

from codelith.languages import registry


def rules(path: str, source: str) -> list[str]:
    return [i.rule for i in registry.for_path(path).inspect(path, textwrap.dedent(source))]


def one(path: str, source: str, rule: str):
    found = [i for i in registry.for_path(path).inspect(path, textwrap.dedent(source)) if i.rule == rule]
    assert len(found) == 1, found
    return found[0]


class TestPythonErrors:
    def test_a_dropped_exception(self) -> None:
        issue = one("app/x.py", "try:\n    go()\nexcept Exception:\n    pass\n", "py.swallowed-exception")
        assert (issue.area, issue.severity, issue.line) == ("errors", "medium", 3)

    @pytest.mark.parametrize(
        "body",
        [
            "    logger.exception('failed')\n",
            "    raise\n",
            "    return default_value()\n",
            "    errors.append(exc)\n",
            "    pass  # best effort: the cache is optional\n",
        ],
    )
    def test_handled_or_explained_is_not(self, body: str) -> None:
        assert "py.swallowed-exception" not in rules("app/x.py", "try:\n    go()\nexcept Exception as exc:\n" + body)

    def test_a_specific_exception_ignored_on_purpose_is_not(self) -> None:
        assert rules("app/x.py", "try:\n    go()\nexcept KeyError:\n    pass\n") == []

    def test_bare_except(self) -> None:
        assert rules("app/x.py", "try:\n    go()\nexcept:\n    handle()\n") == ["py.bare-except"]

    def test_raise_without_cause_but_not_for_http_errors(self) -> None:
        src = "try:\n    go()\nexcept ValueError as e:\n    raise RuntimeError('x')\n"
        assert rules("app/x.py", src) == ["py.raise-without-cause"]
        http = "try:\n    go()\nexcept ValueError as e:\n    raise HTTPException(404)\n"
        assert rules("app/x.py", http) == []

    def test_requests_without_timeout(self) -> None:
        assert rules("app/x.py", "import requests\nrequests.get(url)\n") == ["py.no-timeout"]
        assert rules("app/x.py", "import requests\nrequests.get(url, timeout=5)\n") == []


class TestPythonSecurity:
    def test_eval_of_a_value_not_a_literal(self) -> None:
        assert rules("app/x.py", "eval(user_input)\n") == ["py.eval"]
        assert rules("app/x.py", "eval('1 + 1')\n") == []

    def test_shell_true_with_a_built_command(self) -> None:
        assert rules("app/x.py", "import subprocess\nsubprocess.run(f'git log {ref}', shell=True)\n") == ["py.shell-injection"]
        assert rules("app/x.py", "import subprocess\nsubprocess.run(['git', 'log', ref])\n") == []

    def test_sql_built_from_values(self) -> None:
        assert rules("app/x.py", "cur.execute(f'SELECT * FROM users WHERE id = {uid}')\n") == ["py.sql-built"]
        assert rules("app/x.py", "q = 'DELETE FROM t WHERE id = %s' % uid\ncur.execute(q)\n") == ["py.sql-built"]
        assert rules("app/x.py", "cur.execute('SELECT * FROM users WHERE id = ?', (uid,))\n") == []

    def test_schema_statements_are_a_softer_warning(self) -> None:
        issue = one("app/x.py", "db.execute(f'ALTER TABLE {t} ADD COLUMN {c}')\n", "py.sql-built")
        assert (issue.severity, issue.confidence) == ("medium", "likely")

    def test_unsafe_loading(self) -> None:
        assert rules("app/x.py", "import pickle\npickle.loads(blob)\n") == ["py.unsafe-deserialization"]
        assert rules("app/x.py", "import yaml\nyaml.load(text)\n") == ["py.unsafe-deserialization"]
        assert rules("app/x.py", "import yaml\nyaml.load(text, Loader=yaml.SafeLoader)\nyaml.safe_load(text)\n") == []

    def test_tls_and_jwt_checks_turned_off(self) -> None:
        assert rules("app/x.py", "requests.get(u, verify=False, timeout=3)\n") == ["py.tls-off"]
        src = "jwt.decode(token, options={'verify_signature': False})\n"
        assert rules("app/x.py", src) == ["py.jwt-unverified"]

    def test_cors_open_with_credentials_is_high(self) -> None:
        src = "app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True)\n"
        assert one("app/x.py", src, "py.cors-any-origin").severity == "high"
        assert one("app/x.py", "app.add_middleware(CORSMiddleware, allow_origins=['*'])\n", "py.cors-any-origin").severity == "low"

    def test_random_for_a_token_but_not_for_a_shuffle(self) -> None:
        assert rules("app/x.py", "import random\nreset_token = random.choice(chars)\n") == ["py.insecure-random"]
        assert rules("app/x.py", "import random\nsample = random.choice(items)\n") == []

    def test_md5_of_a_password_but_not_of_a_cache_key(self) -> None:
        assert rules("app/x.py", "hashlib.md5(password.encode())\n") == ["py.weak-hash"]
        assert rules("app/x.py", "hashlib.md5(cache_key.encode())\n") == []


class TestPythonLeaksBreaksAndPerformance:
    def test_a_secret_in_a_log_but_not_a_token_count(self) -> None:
        assert rules("app/x.py", "logger.info('key %s', api_key)\n") == ["py.secret-in-log"]
        assert rules("app/x.py", "logger.info('used %s', max_tokens)\nlogger.info('has key', ok=bool(api_key))\n") == []

    def test_exception_text_to_the_client_only_when_caught_broadly(self) -> None:
        broad = "try:\n    go()\nexcept Exception as e:\n    raise HTTPException(500, detail=str(e))\n"
        assert "py.error-to-client" in rules("app/x.py", broad)
        domain = "try:\n    go()\nexcept NotFoundError as e:\n    raise HTTPException(404, detail=str(e)) from e\n"
        assert rules("app/x.py", domain) == []

    def test_mutable_default(self) -> None:
        assert rules("app/x.py", "def f(items=[]):\n    return items\n") == ["py.mutable-default"]
        assert rules("app/x.py", "def f(items=None):\n    return items or []\n") == []

    def test_is_with_a_literal(self) -> None:
        assert rules("app/x.py", "if name is 'admin':\n    pass\n") == ["py.is-literal"]
        assert rules("app/x.py", "if name is None:\n    pass\n") == []

    def test_blocking_call_in_async_code_only(self) -> None:
        assert rules("app/x.py", "import time\nasync def h():\n    time.sleep(1)\n") == ["py.blocking-in-async"]
        assert rules("app/x.py", "import time\ndef h():\n    time.sleep(1)\n") == []
        nested = "import time\nasync def h():\n    def later():\n        time.sleep(1)\n    return later\n"
        assert rules("app/x.py", nested) == []


class TestPythonTests:
    def test_only_test_rules_apply_to_a_test_file(self) -> None:
        src = "def test_it():\n    eval(x)\n    try:\n        go()\n    except Exception:\n        pass\n"
        assert rules("tests/test_x.py", src) == ["py.test-asserts-nothing"]

    def test_a_test_with_an_assertion_or_raises(self) -> None:
        assert rules("tests/test_x.py", "def test_a():\n    assert f() == 1\n") == []
        assert rules("tests/test_x.py", "def test_b():\n    with pytest.raises(ValueError):\n        f()\n") == []


class TestPatterns:
    def test_typescript(self) -> None:
        assert rules("src/a.ts", "try { go() } catch (e) {}\n") == ["ts.empty-catch"]
        assert rules("src/a.ts", "try { go() } catch { /* the store may be off */ }\n") == []
        assert rules("src/a.ts", "const r = await db.query(`SELECT * FROM t WHERE id = ${id}`)\n") == ["ts.sql-built"]
        assert rules("src/a.ts", "// eval(code)\nconst x = 1\n") == []
        assert rules("src/a.ts", "https.request({ rejectUnauthorized: false })\n") == ["ts.tls-off"]

    def test_go(self) -> None:
        assert rules("a.go", 'rows, err := db.Query(fmt.Sprintf("SELECT * FROM t WHERE id=%s", id))\n') == ["go.sql-built"]
        assert rules("a.go", "cfg := &tls.Config{InsecureSkipVerify: true}\n") == ["go.tls-off"]
        assert rules("a.go", "    _ = os.Remove(path)\n") == ["go.ignored-error"]

    def test_java(self) -> None:
        assert rules("A.java", "try { go(); } catch (Exception e) {}\n") == ["java.empty-catch"]
        assert rules("A.java", 'stmt.executeQuery("SELECT * FROM t WHERE id = " + id);\n') == ["java.sql-built"]
        assert rules("A.java", "e.printStackTrace();\n") == ["java.print-stack-trace"]

    def test_every_language_with_rules_says_so(self) -> None:
        for path in ("a.py", "a.ts", "a.js", "a.go", "A.java"):
            assert registry.for_path(path).has_rules
