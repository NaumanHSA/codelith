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
