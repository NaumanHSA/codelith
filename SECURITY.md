# Security Policy

## Reporting a vulnerability

**Do not open a public issue.** Email **naumanhsa965@gmail.com** with:

- what the problem is, and what an attacker gets from it
- the steps to reproduce it
- the version or commit you found it on

You will get an acknowledgement within 72 hours and an assessment within a week. If a
fix is warranted, you will be credited in the release notes unless you would rather not
be.

## Supported versions

Codelith is pre-1.0. Fixes go to `main` and the next release; there are no maintained
release branches yet.

## What Codelith touches

Worth stating plainly, because it shapes what a vulnerability here would mean.

**It runs on your machine and reads your code.** It clones repositories you point it
at, parses them, and stores what it learned in SQLite under `~/.codelith`. The clone is
discarded when analysis finishes; the extracted chunks are the copy that remains.

**It talks to a model endpoint you configure.** That may be a local server or a hosted
provider. Source excerpts are sent to whichever you chose — that is how analysis works —
so a hosted provider means your code reaches that provider. Nothing else leaves the
machine: no telemetry, no fonts from a CDN, no phone-home.

**Stored credentials.** Provider API keys entered in the studio are encrypted at rest
with Fernet. The key is derived from your instance secret; anyone with read access to
both the database file and the secret can recover them.

**Published documentation sites are unauthenticated by design.** A publish produces a
capability URL containing a 128-bit random slug, so a site is reachable by anyone with
the link and not guessable without it. That is the intended sharing model — treat the
link as the secret. Take a site down from the Published page when you are done with it.

**The MCP server is read-only.** Nothing in `codelith/mcp/` writes, and it reaches no
network beyond the databases Codelith already talks to.

## Out of scope

- Findings that require an attacker to already have filesystem access to `~/.codelith`
  or to the machine running the studio.
- The content of a model's output. Codelith checks citations against what was actually
  retrieved, but a model writing something wrong is a quality problem, not a
  vulnerability.
- Vulnerabilities in a model provider you configured.
