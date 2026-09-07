# Contributing to Codelith

Thanks for being here. This file is short on ceremony and long on the things that
will actually get a patch rejected, because those are the ones you cannot guess.

## Getting it running

```bash
git clone https://github.com/NaumanHSA/codelith.git
cd codelith
pip install -e ".[dev]"

make dev                             # API on :8000. Nothing to start first.
cd ui && pnpm install && pnpm dev     # studio on :5173 — needs Node >= 20.19
```

There is no database to provision and no migrate step. SQLite lives in a file under
`~/.codelith` (or `CODELITH_HOME`) and is created on first run. `.env` is optional —
every setting has a working default and `.env.example` documents them.

You will need a model to run an analysis. `codelith doctor` tells you what it can and
cannot reach, which is faster than reading the config.

```bash
make test          # the whole suite, ~40 seconds, starts nothing
make lint          # ruff
make typecheck     # mypy
cd ui && pnpm build  # typecheck + the two render checks + the bundle
```

## The rules that are actually enforced

These are not style preferences. Each one has a test or a reviewer behind it, and each
exists because breaking it caused a real problem.

**The base may not import an app, and apps may not import each other.**
`tests/unit/test_module_isolation.py` fails if they do. Known exceptions live in
`KNOWN_LEAKS` with a reason attached, and that list is only allowed to shrink. An app
is defined by *what it reads from the knowledge base*; if you find yourself editing an
analysis agent to add an app, stop — the app is asking for something the knowledge base
should hold for everyone.

**No language-specific code outside `codelith/languages/`.** Python's `ast`, file
extensions, framework idioms: all of it lives behind `LanguageProvider`. Agents and the
knowledge base speak the neutral vocabulary in `languages/taxonomy.py` and
`knowledge/constants.py`. Adding a language must mean adding one provider, not touching
agents or schema.

**All database access goes through `codelith/db/repositories/`.** Never query
SQLAlchemy directly from a route or a service.

**Business logic lives in `codelith/services/`.** Routes validate input, call a
service, and return a schema. Nothing else.

**Configuration is `pydantic-settings` in `codelith/config.py`.** No hardcoded values
anywhere.

**LLM calls go through `codelith.llm.client`.** Never instantiate `openai.AsyncOpenAI`
directly. Resolve the endpoint with `codelith.llm.router.select_spec(task_type)` and
pass the resulting `ModelSpec` — a bare model name is not enough now that the tiers can
sit on different providers. Which tier a task gets is decided by task type in
`llm/router.py`, not by the caller.

**Long-running work stays cancellable.** Never swallow `JobCancelled` in a broad
`except Exception`, and never retry it.

**A concurrent phase must not share one `AsyncSession`.** Fetch what you need before
`asyncio.gather`, and avoid `return_exceptions=True` unless you log the exception.

### In the studio (`ui/`)

**No hardcoded colours.** Tokens live in `ui/src/styles/theme.css` and are surfaced as
Tailwind utilities (`bg-panel`, `text-ink-dim`, `border-rule`, `text-hot-ink`). Never
`bg-white` or `text-slate-600`. The categorical hues used by the knowledge graph
(`--cat-1` … `--cat-6`) are validated for colour-vision deficiency; do not add a
seventh without re-running that check.

**Nothing loads from a CDN at runtime.** Fonts are bundled in `ui/src/assets/fonts`.
The product's claim is that nothing leaves the machine, and a webfont request is a
request.

**IDs from the API are integers.** Type them as `number`.

**All HTTP goes through `ui/src/app/lib/api.ts`** — it attaches the JWT, refreshes once
on 401, retries, and only then bounces to sign-in.

## Tests

New behaviour needs a test. Two things we care about more than coverage:

- **Test the real thing, not a copy of it.** If a test has to reassemble the logic to
  exercise it, extract the logic into a function both call. A test that re-implements
  what it checks keeps passing after the code stops working.
- **Say what the test is holding.** A docstring naming the failure it prevents is worth
  more than the assertion; the assertion says what, the docstring says why anyone
  should keep it.

## Commits and pull requests

- Conventional-ish prefixes (`feat:`, `fix:`, `chore:`, `docs:`, `test:`).
- Say **why**, not just what. The diff already says what.
- One concern per pull request.
- `make test`, `make lint` and `pnpm build` all pass before you open it.

## Reporting things

- **Bugs and features**: [issues](https://github.com/NaumanHSA/codelith/issues).
- **Security**: do not open an issue. See [SECURITY.md](SECURITY.md).

## Licence

By contributing you agree that your contributions are licensed under
[Apache-2.0](LICENSE), the same terms as the project.
