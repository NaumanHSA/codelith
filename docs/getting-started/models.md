# Models

Codelith calls a model. It does not ship one, and it does not care whose it is, as long
as the endpoint speaks the OpenAI API.

## Three tiers

| Tier | Used for | A reasonable local choice |
|---|---|---|
| **quality** | writing, review, validation, architecture, planning | a 7-14B instruct model |
| **fast** | classification, extraction, diagrams, summarising | a 1-3B instruct model |
| **embedding** | indexing and retrieval | any embedding model |

Which tier handles which task is decided in `codelith/llm/router.py`, by task type,
never by the caller. `write`, `review`, `validate`, `architecture` and `plan` go to
quality; `classify`, `extract`, `diagram` and `summarize` go to fast. Anything
unrecognised goes to quality, because being slow is a better failure than being wrong.

## Configuring them

In the studio under **Settings → Models**, or in `.env`:

```bash
MODEL_QUALITY_PROVIDER=local          # local | openai
MODEL_QUALITY=qwen/qwen3.5-9b
MODEL_QUALITY_BASE_URL=http://localhost:1234/v1
MODEL_QUALITY_CONTEXT_WINDOW=21000
# ...and the same four for MODEL_FAST_* and MODEL_EMBEDDING_*
```

The settings page wins over `.env` once anything has been configured there. An install
that has never opened it behaves exactly as its `.env` says.

!!! note "The provider decides one thing only"
    Whether `OPENAI_API_KEY` is sent. `openai` sends it; `local` does not.

    That split exists because of a real failure: a key posted to LM Studio, which
    answered — as whatever model it happened to have loaded. The form now shows only
    the fields a provider can use, so a field that cannot be set cannot be set wrong.

## Mixing them

The tiers are independent. Running quality on a hosted model and fast and embedding
locally is a common and sensible arrangement: the cheap, frequent calls stay on your
machine, and the one that has to write well goes somewhere stronger.

Nothing about the design assumes they share a provider.

## There is no embedding width setting

The width of an embedding is a property of the model, not a thing to configure.
Codelith measures it on the first call and records it on the knowledge base along with
the model's name.

Open a knowledge base with a different embedding model and it **refuses to read it**
and tells you to re-analyse, rather than silently comparing vectors that do not mean
the same thing.

??? note "Why this is a refusal and not a warning"
    `VECTOR_DIMENSIONS` used to be a setting, and the operator was expected to keep it
    in step with whichever model they had loaded. It also, by then, did nothing: the
    column is a blob with no declared width, so nothing checked it and nothing could.

    What actually happened on a mismatch was `ValueError: setting an array element with
    a sequence` out of numpy, at search time, from a stack nobody would connect to a
    model they changed last week.

    The comparison is on the model *name* as well as the width, because two models can
    share a width and still disagree completely about what a vector means: same shape,
    meaningless answers, and nothing anywhere to say so.

Any embedding model works. You never have to tell it a number.

## Checking before it fails deep

```bash
codelith doctor
```

It checks the things that fail late and confusingly, in the order they break: no server
at all, then no credentials, then a model endpoint that is not there, then the embedding
width — which does not fail at startup, but deep inside ingestion when the first vector
is written.

The studio's model form has the same check per endpoint: **Test connection** before
save, because the useful moment to find out an endpoint is unreachable is while the
form is still open. It reports the model that actually answered, which is how you catch
a local server quietly serving something other than what you asked for.

## Running models in Docker

You do not. The model runs on your machine and the container reaches out to it — see
[Install](install.md#docker) for the one address that changes.
