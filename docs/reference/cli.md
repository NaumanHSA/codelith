# CLI

```
codelith [--json] <command>
```

!!! note "The CLI is a client"
    It talks to a running Codelith server over HTTP. Start one first — see
    [Install](../getting-started/install.md). The address comes from
    `CODELITH_API_URL`, defaulting to `http://localhost:8000`.

`--json` prints one JSON document to stdout and nothing else, for scripting.

## `codelith login`

Signs in and remembers the token, so the other commands do not ask again.

## `codelith analyse <target>`

Reads a codebase into a knowledge base. Aliased `analyze`.

```bash
codelith analyse .                                        # a folder
codelith analyse https://github.com/NaumanHSA/watchtower.git
codelith analyse github.com/owner/repo                    # scheme optional
```

Anything that exists on disk is treated as local, checked first — a directory called
`gitlab.com` is a directory. Otherwise it is parsed as a GitHub, GitLab or Bitbucket
URL.

Follows the job and narrates each stage as it changes, using the stage names the
pipeline actually reports rather than a list kept in the CLI. `--no-wait` starts it and
returns.

Running it again on the same folder or URL reads the same codebase again — it does not
create a second one. A second reading keeps everything that did not change since the
first (search vectors, module summaries, narratives, and while the structure is the same
the architecture), so after a small commit it takes a fraction of the time, and it ends
by saying what it kept. If the code has not moved at all, there is nothing to read and it
says so. `--from-scratch` reads everything again, which is worth it after changing models.

## `codelith watch [path]`

Reads a local repository again after every commit, for as long as it runs:

```bash
codelith watch            # the repository you are in
codelith watch ../api --interval 10
```

It checks `HEAD` every few seconds (`--interval`, default 5). A new commit starts a
reading of the changes; commits made while one is running cost one more reading when it
finishes, not one each. Ctrl+C stops it.

## `codelith hook install | uninstall [path]`

The same without a process left running: a git `post-commit` hook that starts a reading
of the changes after each commit, in the background, so a commit never waits on it.

```bash
codelith hook install
codelith hook uninstall
```

It honours `core.hooksPath`, and it never overwrites a hook it did not write: if you
already have a `post-commit` hook it prints the one line to add to it instead.

The studio has a third way for a folder on the machine running Codelith: **Read every
commit** on the codebase page, where the server does the checking.

## `codelith review [path]`

Checks the change in a checkout against what Codelith knows about the codebase, before
it is merged:

```bash
codelith review                   # uncommitted changes, against the commit the knowledge was read at
codelith review --against main    # against another branch or commit
codelith review --head feature    # a branch, not the working copy
```

It finds the codebase by the folder, or by the checkout's `origin` — so a clone of a
repository read from GitHub is that codebase. The report says what the change touches,
what could break, which tests to run and which written pages to check, what it adds or
removes, and whether it breaks the codebase's shape; it is kept on the codebase's
**Review** page in the studio.

Exits with `1` when there is something under *Stop and look*, so it can run before a
push or in a local CI step.

## `codelith qa [path]`

Runs QA on the codebase's latest reading, waits for it, and fails a CI step on what it
finds:

```bash
codelith qa                                  # every area, quick: rules and checks, no model
codelith qa --areas security,leakage --fail-on medium
codelith qa --depth tests --sarif qa.sarif   # the sandbox too; SARIF for GitHub code scanning
codelith qa --markdown fix-plan.md --fail-on never
```

Exits `1` when anything at `--fail-on` (default `high`) or worse is open. Findings
dismissed or accepted in the studio do not count, so a decision made once holds in CI.
`--online` lets the dependency check ask OSV.dev and the registries. A run that fails or is
cancelled is an error; Ctrl-C cancels the run.

## `codelith agents-md [path]`

Writes the instruction file coding agents read first, from the reading:

```bash
codelith agents-md                     # print it
codelith agents-md --write             # put it in AGENTS.md at the repository's root
codelith agents-md --write --format claude   # CLAUDE.md instead
```

What the codebase is, how it is laid out and which way imports should run, how to run
it, how routes, commands, settings, models and tests are added here, the files where an
edit hurts most, and how to use Codelith's tools while working. Every sentence comes from
the reading; no model writes it.

`--write` replaces only the section between `<!-- codelith:begin -->` and
`<!-- codelith:end -->`, so whatever is written by hand around it stays. Run it again
after a reading to bring it up to date. `--project` names the codebase when the folder is
not itself one.

## `codelith ask "<question>"`

A question, answered from the analysis, with citations checked against retrieved
evidence.

## `codelith status`

What has been analysed: each codebase, its commit, and whether its knowledge base is
ready.

## `codelith doctor`

Checks the things that fail late and confusingly, in the order they break: no server,
then no credentials, then a model endpoint that is not there, then the embedding width —
which does not fail at startup at all, but deep inside ingestion when the first vector
is written.

Run it before a long analysis rather than after.

## `codelith studio`

Opens the studio in a browser, and warns first if the API is not answering — a studio
that loads but cannot sign you in is a confusing thing to be handed.

## `codelith mcp`

Serves the knowledge base over [MCP](../mcp.md) on stdin and stdout. Prints no banner,
because a stray line on stdout is a parse error on the client.

## Exit codes

`0` on success. `1` on a failure the command can describe — an analysis that ended in
`failed`, an unreachable API, a doctor check that did not pass.
