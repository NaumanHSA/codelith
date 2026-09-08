# Install

Three ways in. Docker is the one to pick if you just want to see it work.

## Docker

One container: the API, the studio it serves, and the database. The image builds the
studio, serves it from the same origin, creates the database and seeds an account.

```bash
git clone https://github.com/NaumanHSA/codelith.git
cd codelith
docker compose up --build -d
```

Open **<http://localhost:8000>** and sign in with `admin@codelith.dev` / `admin1234`.

`make docker` does the same and prints the address. `make docker-down` stops it; the
knowledge bases live in a named volume and survive.

!!! warning "Your model stays on your machine, and that needs one setting"
    A container's `localhost` is the container. A model server running on your host is
    not reachable at the address that works everywhere else.

    Compose maps `host.docker.internal` for exactly this. Point the tiers at
    `http://host.docker.internal:1234/v1` rather than `http://localhost:1234/v1`.

    You do not have to remember that: the studio detects it is containerised, changes
    the placeholder, warns if you type `localhost`, and offers a button that rewrites
    it for you.

## From source

Needs Python 3.11+ and, for the studio, Node ≥ 20.19.

```bash
git clone https://github.com/NaumanHSA/codelith.git
cd codelith
pip install -e ".[dev]"

python scripts/seed_dev.py     # the first account
make dev                       # API on :8000

# a second terminal
cd ui && pnpm install && pnpm dev    # studio on :5173
```

`.env` is optional. Every setting has a working default and
[`.env.example`](../reference/configuration.md) documents them. The database is a file
under `~/.codelith` (or `CODELITH_HOME`), created on first run, so there is no migrate
step for a fresh install and no separate one for an upgrade.

!!! note "Reload is off by default on Windows"
    WatchFiles prints "Reloading…", the replacement worker never starts, and the
    previous one keeps serving while staying bound to the port. Set `RELOAD=1` to opt
    in, or restart by hand.

## From the command line

The CLI is a **client**. It talks to a running Codelith server, so start one of the
above first.

```bash
codelith login                          # remembers the token
codelith analyse .                      # or a GitHub URL, or a folder
codelith ask "how does auth work?"
codelith status                         # what has been analysed
codelith doctor                         # check the config before it fails deep
codelith mcp                            # serve the knowledge base over MCP
```

See the [CLI reference](../reference/cli.md).

## PyPI

Not published yet. The release workflow is built and wired to trusted publishing;
firing it is a maintainer decision, and this page will say so when it happens rather
than before.

## What gets created

Nothing outside your home directory.

| Path | What it is |
|---|---|
| `~/.codelith/codelith.db` | The database. Every knowledge base, project, job and document |
| `~/.codelith/storage/` | Generated documents and exports |
| `./repos/` | Clones, while a job is reading them. Removed when the job ends |
| `./runs/{job_id}/` | Per-job traces and artefacts, if tracing is on |

Override the first two with `CODELITH_HOME`, or individually with `DATABASE_URL` and
`STORAGE_DIR`.
