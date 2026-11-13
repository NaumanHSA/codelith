"""
QA rules as patterns, for the languages read without a syntax tree.

TypeScript, JavaScript, Go and Java are parsed by patterns elsewhere in their
providers too, so their rules are patterns here: each anchored on something specific
enough to mean what it says (`InsecureSkipVerify: true`, a SQL keyword inside a
template literal with `${`), never on a bare word. Comments are blanked before
matching, keeping every line where it was, so a commented-out `eval(` is not a finding
and line numbers stay true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from codelith.languages.base import FlowFacts, Guards, Issue, Sink

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
#: A line comment, but not `://` inside a URL.
_LINE_COMMENT = re.compile(r"(?<![:\"'`\\])//[^\n]*")


@dataclass(frozen=True, slots=True)
class PatternRule:
    rule: str
    area: str
    severity: str
    pattern: re.Pattern
    title: str
    message: str
    fix: str
    confidence: str = "confirmed"
    #: Applies to test files too (rules about tests).
    in_tests: bool = False
    #: Applies only to test files.
    only_tests: bool = False
    #: Matched with the comments in place: a `catch` holding only a comment explains
    #: itself, which is what the rule asks for.
    keep_comments: bool = False


#: Short names where a rule's title says more than its group should.
_SHORT: dict[str, str] = {
    "ts.empty-catch": "Errors caught and dropped",
    "ts.swallowed-promise": "Promise failures dropped",
    "ts.eval": "Code run from a string",
    "ts.inner-html": "HTML written from values",
    "ts.dangerously-set-html": "Raw HTML rendered by React",
    "ts.shell-injection": "Shell commands built from values",
    "ts.sql-built": "SQL built from values",
    "ts.tls-off": "Certificate checks turned off",
    "ts.secret-in-log": "Secrets written to the console",
    "ts.token-in-local-storage": "Credentials kept in localStorage",
    "go.sql-built": "SQL built from values",
    "go.tls-off": "Certificate checks turned off",
    "go.shell-injection": "Shell commands built from values",
    "go.ignored-error": "Errors thrown away",
    "go.no-timeout": "HTTP clients with no timeout",
    "java.empty-catch": "Exceptions caught and dropped",
    "java.print-stack-trace": "Stack traces printed and dropped",
    "java.sql-built": "SQL built from values",
    "java.shell-injection": "Commands built from values",
    "java.trust-all": "Certificates trusted without checking",
    "java.unsafe-deserialization": "Unsafe deserialisation",
}


def labels(rules: tuple[PatternRule, ...]) -> dict[str, str]:
    return {r.rule: _SHORT.get(r.rule, r.title) for r in rules}


def blank_comments(source: str) -> str:
    """The source with comments replaced by spaces, newlines kept."""

    def keep_lines(match: re.Match) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return _LINE_COMMENT.sub(keep_lines, _BLOCK_COMMENT.sub(keep_lines, source))


def scan(source: str, rules: tuple[PatternRule, ...], is_test: bool) -> list[Issue]:
    blanked = blank_comments(source)
    out: list[Issue] = []
    seen: set[tuple[str, int]] = set()
    for rule in rules:
        if (is_test and not (rule.in_tests or rule.only_tests)) or (rule.only_tests and not is_test):
            continue
        text = source if rule.keep_comments else blanked
        for match in rule.pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            if (rule.rule, line) in seen:
                continue
            seen.add((rule.rule, line))
            out.append(
                Issue(
                    rule=rule.rule,
                    area=rule.area,
                    severity=rule.severity,
                    line=line,
                    end_line=text.count("\n", 0, match.end()) + 1,
                    title=rule.title,
                    message=rule.message,
                    fix=rule.fix,
                    confidence=rule.confidence,
                )
            )
    return out


_SQL = r"(?:select\s[^`]*\sfrom|insert\s+into|update\s+\w+\s+set|delete\s+from)"
_SECRET_WORD = r"(?:password|passwd|secret|apiKey|api_key|accessToken|access_token|authToken|auth_token|refreshToken|privateKey|bearer)"

# -- TypeScript and JavaScript ---------------------------------------------------------

TYPESCRIPT: tuple[PatternRule, ...] = (
    PatternRule(
        "ts.empty-catch",
        "errors",
        "medium",
        re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}"),
        "An error is caught and dropped",
        "An empty `catch` hides every failure in its `try`: when it goes wrong, nothing says so and the code "
        "carries on as if it had worked.",
        "Log it, rethrow it, or catch only what you mean to ignore and say why in a comment.",
        keep_comments=True,
    ),
    PatternRule(
        "ts.swallowed-promise",
        "errors",
        "low",
        re.compile(r"\.catch\(\s*(?:\(\s*\w*\s*\)|\w+)\s*=>\s*(?:\{\s*\}|null|undefined|void 0)\s*\)"),
        "A promise's failure is dropped",
        "`.catch(() => {})` turns every rejection into silence, network errors included.",
        "Handle the failure, or at least log it.",
    ),
    PatternRule(
        "ts.eval",
        "security",
        "high",
        re.compile(r"(?<![\w.])(?:eval\s*\(|new\s+Function\s*\()"),
        "Code is built from a string and run",
        "Whatever reaches `eval` or `new Function` runs with the page's or the process's permissions.",
        "Parse the data (`JSON.parse`) or look the operation up in a map of allowed ones.",
    ),
    PatternRule(
        "ts.inner-html",
        "security",
        "medium",
        re.compile(r"\.(?:innerHTML|outerHTML)\s*=(?!=)(?!\s*(['\"`])\s*\1)"),
        "HTML is written from a value",
        "If any part of the value comes from a user or a server response, its `<script>` and `onerror=` run on "
        "the page: cross-site scripting.",
        "Set `textContent`, or sanitise the HTML first (DOMPurify).",
        "likely",
    ),
    PatternRule(
        "ts.dangerously-set-html",
        "security",
        "low",
        re.compile(r"dangerouslySetInnerHTML\s*=\s*\{\{\s*__html\s*:\s*(?!['\"`])"),
        "React renders raw HTML from a value",
        "React escapes everything except this. Whatever the value holds runs on the page.",
        "Make sure the HTML is sanitised or comes from a trusted renderer, and say where in a comment.",
        "likely",
    ),
    PatternRule(
        "ts.shell-injection",
        "security",
        "high",
        re.compile(r"\b(?:exec|execSync|spawnSync|spawn)\s*\(\s*(?:`[^`]*\$\{|['\"][^'\"]*['\"]\s*\+)"),
        "A shell command is built from values",
        "A value containing `;` or `&&` runs a second command of its own.",
        "Use `execFile` or `spawn` with the arguments as an array, without `shell: true`.",
    ),
    PatternRule(
        "ts.sql-built",
        "security",
        "high",
        re.compile(r"\.(?:query|execute|raw|\$queryRawUnsafe|\$executeRawUnsafe)\s*\(\s*`[^`]*" + _SQL + r"[^`]*\$\{", re.IGNORECASE),
        "SQL is built from values",
        "A value placed in the query text becomes part of the query: a quote in it ends the string and what "
        "follows runs as SQL.",
        "Pass values as parameters (`query('... WHERE id = $1', [id])`), or use the tagged-template form your "
        "driver escapes.",
    ),
    PatternRule(
        "ts.tls-off",
        "security",
        "high",
        re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED['\"]?\s*\]?\s*=\s*['\"]?0"),
        "Certificate checking is turned off",
        "Anyone between this code and the server can read and change the traffic, credentials included.",
        "Leave verification on; pass the private CA (`ca:`) if that is why it was turned off.",
    ),
    PatternRule(
        "ts.secret-in-log",
        "leakage",
        "medium",
        re.compile(r"console\.(?:log|info|debug|warn|error)\([^)\n]*\b" + _SECRET_WORD + r"\b", re.IGNORECASE),
        "A credential is written to the console",
        "Console output ends up in logs and in browser devtools, read by people who should not hold it.",
        "Log that it was present, never the value.",
        "likely",
    ),
    PatternRule(
        "ts.token-in-local-storage",
        "leakage",
        "low",
        re.compile(r"localStorage\.setItem\(\s*['\"`][^'\"`]*(?:token|jwt|auth|session)", re.IGNORECASE),
        "A credential is kept in localStorage",
        "Any script that runs on the page can read localStorage, so one cross-site scripting bug hands over the "
        "session.",
        "Prefer an httpOnly cookie; if a token must live in the page, keep it short-lived.",
        "likely",
    ),
)

# -- Go ------------------------------------------------------------------------------

GO: tuple[PatternRule, ...] = (
    PatternRule(
        "go.sql-built",
        "security",
        "high",
        re.compile(r"\.(?:Query|QueryRow|Exec|QueryContext|QueryRowContext|ExecContext)\(\s*(?:ctx\s*,\s*)?(?:fmt\.Sprintf\(|\"[^\"]*\"\s*\+)"),
        "SQL is built from values",
        "A value formatted into the query text becomes part of it: a quote in it ends the string and what "
        "follows runs as SQL.",
        "Pass values as arguments: `db.Query(\"... WHERE id = $1\", id)`.",
    ),
    PatternRule(
        "go.tls-off",
        "security",
        "high",
        re.compile(r"InsecureSkipVerify\s*:\s*true"),
        "Certificate checking is turned off",
        "Anyone between this code and the server can read and change the traffic.",
        "Leave verification on; add the private CA to `RootCAs` if that is why it was turned off.",
    ),
    PatternRule(
        "go.shell-injection",
        "security",
        "high",
        re.compile(r"exec\.Command(?:Context)?\(\s*(?:ctx\s*,\s*)?\"(?:sh|bash|cmd|/bin/sh|/bin/bash)\"\s*,\s*\"(?:-c|/c)\"\s*,\s*[^\"\s)]"),
        "A shell command is built from values",
        "Through `sh -c`, a value containing `;` or `&&` runs a second command of its own.",
        "Call the program directly with its arguments: `exec.Command(\"git\", \"log\", ref)`.",
    ),
    PatternRule(
        "go.ignored-error",
        "errors",
        "low",
        re.compile(r"^\s*(?:_\s*=|\w+\s*,\s*_\s*:?=)\s*[\w.]+\([^\n]*\)\s*$", re.MULTILINE),
        "A returned error may be thrown away",
        "Assigning a call's result to `_` drops the error it returns, and the code carries on as if it worked.",
        "Check it: `if err != nil { return err }`, or say in a comment why it cannot fail.",
        "likely",
    ),
    PatternRule(
        "go.no-timeout",
        "errors",
        "medium",
        re.compile(r"\bhttp\.(?:Get|Post|PostForm|Head)\(|http\.DefaultClient\b"),
        "The default HTTP client has no timeout",
        "`http.Get` and `http.DefaultClient` wait forever on a server that stops answering.",
        "Use a client with a timeout: `&http.Client{Timeout: 10 * time.Second}`.",
    ),
)

# -- Java ----------------------------------------------------------------------------

JAVA: tuple[PatternRule, ...] = (
    PatternRule(
        "java.empty-catch",
        "errors",
        "medium",
        re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*\}"),
        "An exception is caught and dropped",
        "An empty `catch` hides every failure in its `try`, and the code carries on as if it had worked.",
        "Log it, rethrow it wrapped, or catch only what you mean to ignore and say why.",
        keep_comments=True,
    ),
    PatternRule(
        "java.print-stack-trace",
        "errors",
        "low",
        re.compile(r"\.printStackTrace\(\s*\)"),
        "An exception is printed to stderr and dropped",
        "`printStackTrace` writes past the logging setup, so the error is not where anyone looks.",
        "Log it with the logger (`log.error(\"...\", e)`), or rethrow it.",
    ),
    PatternRule(
        "java.sql-built",
        "security",
        "high",
        re.compile(r"(?:executeQuery|executeUpdate|execute|prepareStatement|createQuery|createNativeQuery)\(\s*\"[^\"]*" + _SQL.replace("[^`]", "[^\"]") + r"[^\"]*\"\s*\+", re.IGNORECASE),
        "SQL is built from values",
        "A value concatenated into the query becomes part of it: a quote in it ends the string and what follows "
        "runs as SQL.",
        "Use a `PreparedStatement` with `?` placeholders, or named parameters in JPA.",
    ),
    PatternRule(
        "java.shell-injection",
        "security",
        "high",
        re.compile(r"Runtime\.getRuntime\(\)\.exec\([^;\n]*\+"),
        "A command is built from values",
        "A value concatenated into the command can add arguments, or a command of its own through a shell.",
        "Use `ProcessBuilder` with the arguments as a list.",
    ),
    PatternRule(
        "java.trust-all",
        "security",
        "high",
        re.compile(
            r"ALLOW_ALL_HOSTNAME_VERIFIER|NoopHostnameVerifier|setHostnameVerifier\(\s*\(\s*\w+\s*,\s*\w+\s*\)\s*->\s*true"
            r"|checkServerTrusted\([^)]*\)\s*(?:throws\s+[\w.]+\s*)?\{\s*\}"
        ),
        "Certificates or hostnames are trusted without checking",
        "Anyone between this code and the server can present any certificate and read the traffic.",
        "Remove the trust-all manager; add the private CA to a trust store if that is why it was there.",
    ),
    PatternRule(
        "java.unsafe-deserialization",
        "security",
        "medium",
        re.compile(r"new\s+ObjectInputStream\("),
        "Java serialisation reads objects from a stream",
        "Deserialising untrusted bytes can run code through gadget classes on the classpath.",
        "Read a data format (JSON) instead, or filter the classes allowed (`ObjectInputFilter`).",
        "likely",
    ),
)


# -- Following a request, by pattern ---------------------------------------------------
#
# Without a syntax tree, a guard is found where it is written once for many routes (a
# router's or the app's middleware, a security configuration, a guard annotation), and a
# sink where a request's own value is handed straight to it on one line. The enclosing
# function is left for QA to find from the reading's symbols.

_AUTH_WORD = r"(?:auth|jwt|passport|session|requireUser|requireAuth|isAuthenticated|ensureAuth|verifyToken|protect|guard|login)"

_GUARDS: dict[str, tuple[tuple[str, re.Pattern], ...]] = {
    "typescript": (
        ("app", re.compile(r"\bapp\.use\(\s*[^)\n]*" + _AUTH_WORD, re.IGNORECASE)),
        ("router", re.compile(r"\b(\w+)\.use\(\s*[^)\n]*" + _AUTH_WORD, re.IGNORECASE)),
        ("file", re.compile(r"@UseGuards\(")),
    ),
    "go": (
        ("app", re.compile(r"\.Use\(\s*[\w.]*" + _AUTH_WORD, re.IGNORECASE)),
    ),
    "java": (
        ("app", re.compile(r"SecurityFilterChain|@EnableWebSecurity|\.authenticated\(\)")),
        (
            "handler",
            re.compile(
                r"@(?:PreAuthorize|Secured|RolesAllowed)\((?:[^()]|\([^()]*\))*\)\s*"
                r"(?:@\w+(?:\((?:[^()]|\([^()]*\))*\))?\s*)*(?:public|protected|private)?\s*[\w<>\[\], ?]+?\s+(\w+)\s*\("
            ),
        ),
    ),
}

_SINKS: dict[str, tuple[tuple[str, re.Pattern], ...]] = {
    "typescript": (
        ("file", re.compile(r"\bfs(?:\.promises)?\.(?:readFile|readFileSync|createReadStream|unlink|unlinkSync|rm|rmSync)\(\s*(?:req|request)\.")),
        ("file", re.compile(r"\bres\.(?:sendFile|download)\(\s*(?:req|request)\.")),
        ("url", re.compile(r"\b(?:fetch|axios(?:\.(?:get|post|put|request))?|got)\(\s*(?:req|request)\.(?:query|body|params)")),
        ("shell", re.compile(r"\b(?:exec|execSync)\(\s*`[^`]*\$\{\s*(?:req|request)\.")),
        ("sql", re.compile(r"\.(?:query|execute|raw)\(\s*`[^`]*\$\{\s*(?:req|request)\.")),
    ),
    "go": (
        ("file", re.compile(r"\bos\.(?:Open|ReadFile|Remove|RemoveAll)\(\s*r\.(?:URL|FormValue|PathValue)")),
        ("url", re.compile(r"\bhttp\.(?:Get|Post)\(\s*r\.(?:URL|FormValue|PathValue)")),
    ),
    "java": (),
}


def flow_facts(source: str, language: str) -> FlowFacts:
    text = blank_comments(source)
    guards = Guards()
    for scope, pattern in _GUARDS.get(language, ()):
        for match in pattern.finditer(text):
            evidence = match.group(0).strip()[:120]
            if scope == "app":
                guards.app = guards.app or evidence
            elif scope == "router" and match.group(1) not in ("app",):
                guards.routers[match.group(1)] = evidence
            elif scope == "file":
                guards.routers["*"] = evidence
            elif scope == "handler":
                guards.handlers[match.group(1)] = evidence.split("\n", 1)[0]
    sinks = [
        Sink(kind=kind, line=text.count("\n", 0, m.start()) + 1, function="", params=["request"], call=m.group(0).strip()[:80])
        for kind, pattern in _SINKS.get(language, ())
        for m in pattern.finditer(text)
    ]
    return FlowFacts(guards=guards, sinks=sinks)


__all__ = ["GO", "JAVA", "TYPESCRIPT", "PatternRule", "blank_comments", "flow_facts", "labels", "scan"]
