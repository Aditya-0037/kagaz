# Setting up Google Cloud Vertex AI

Kagaz's default provider is Vertex AI (Gemini), selected via
`KAGAZ_MODEL_PROVIDER=vertex` (the default — see `model_provider.py`).
`ollama` remains fully wired as an offline, credential-free dev fallback.
Every model call goes through one factory (`model_provider.get_model()`)
and one cache (`llm_cache.cached_call`), so this is a config exercise, not
a code change — follow these steps in order. Written to be runnable by
someone who has never touched this repo before.

## 1. Enable the Vertex AI API

1. Pick (or create) a Google Cloud project. This project uses
   `kagaz-509105`.
2. Enable the Vertex AI API for it:
   ```bash
   gcloud config set project kagaz-509105
   gcloud services enable aiplatform.googleapis.com
   ```
3. Confirm the model named by `KAGAZ_VERTEX_MODEL_ID` (default:
   `gemini-2.5-flash` — check `model_provider.py`'s
   `DEFAULT_VERTEX_MODEL_ID` for the current value) is available in your
   chosen region. `us-central1` (the default `GOOGLE_CLOUD_LOCATION`) has
   broad Gemini model availability; check the
   [Vertex AI model garden](https://console.cloud.google.com/vertex-ai/model-garden)
   if you pick a different region.

## 2. Authenticate with Application Default Credentials

No API keys in code, no service account JSON committed. Authenticate as
yourself:

```bash
gcloud auth login                          # if you haven't already
gcloud auth application-default login
```

This opens a browser for sign-in and writes credentials to the standard
ADC location (`~/.config/gcloud/application_default_credentials.json`, or
the Windows equivalent under `%APPDATA%\gcloud\`). `google-genai` (the
client underneath Strands' `GeminiModel`) picks these up automatically —
nothing in this repo reads or stores them itself.

This step is **interactive by nature** (a browser OAuth consent screen)
and cannot be scripted or automated around — including by an AI agent
working in this repo. If you're asking something to do this setup for
you, this is the one step you have to do by hand.

For a deployed service (not a developer's machine), use a service
account with the `roles/aiplatform.user` role and workload identity /
attached service account credentials instead of a personal ADC login —
still no JSON key committed to the repo.

## 3. Set the environment variables

```bash
export KAGAZ_MODEL_PROVIDER=vertex
export GOOGLE_CLOUD_PROJECT=kagaz-509105
export GOOGLE_CLOUD_LOCATION=us-central1        # region with model access
export KAGAZ_VERTEX_MODEL_ID=gemini-2.5-flash   # or whatever you confirmed in step 1
```

`GOOGLE_CLOUD_PROJECT` being set is also what un-skips
`tests/test_model_provider.py::test_vertex_provider_constructs_without_network`.

## 4. Smoke-test the provider alone, before touching fixtures

```bash
python -c "
from model_provider import get_model
from strands import Agent
agent = Agent(model=get_model('vertex'))
print(agent('Say hello in five words.'))
"
```

This should return a real response with no exception. If it fails, fix
project/region/auth/model-access before going further — don't re-record
fixtures against a broken provider.

**Also smoke-test `structured_output_model=` specifically** before
re-recording anything — this is the one piece of the migration that
couldn't be confirmed from documentation alone (see `docs/sdk-notes.md`'s
2026-09-19 entry: a real, still-open upstream issue,
[strands-agents/sdk-python#1121](https://github.com/strands-agents/sdk-python/issues/1121),
reports `structured_output_model=` failing on `GeminiModel` with a
`tools[0].tool_type` proto error — though the reporter's repro combined it
with ~20 other tools, a heavier setup than Kagaz's plain calls):

```bash
python -c "
from pydantic import BaseModel, Field
from strands import Agent
from model_provider import get_model

class Simple(BaseModel):
    color: str = Field(description='the favorite color mentioned')

agent = Agent(model=get_model('vertex'))
result = agent('My favorite color is teal.', structured_output_model=Simple)
print(result.structured_output)
"
```

If this raises the `tools[0].tool_type` error (or
`StructuredOutputException`), **stop** — do not proceed to step 5. That
means Kagaz's requirement extractor and verifiers, which depend entirely
on `structured_output_model=`, cannot run against Vertex as currently
built, and the fallback is routing through LiteLLM instead of
`GeminiModel` directly (a larger change than this doc covers — update
`model_provider.py`'s vertex branch to construct a LiteLLM-backed model
pointed at Vertex, and update this doc's step 4 example accordingly).

## 5. Re-record every cached fixture

Every `fixtures/llm_cache/*.json` entry and `fixtures/ocr_cache/*.json`
entry (if `KAGAZ_OCR_BACKEND=vision` is also switched on) is keyed on
`(provider, model, prompt, inputs)`, so switching providers means nothing
is cached yet under `vertex` — re-record from scratch:

```bash
python scripts/record_fixtures.py
```

(`KAGAZ_MODEL_PROVIDER=vertex` is the script's own default now — see its
module docstring. Pass `KAGAZ_MODEL_PROVIDER=ollama` explicitly instead if
you want to record against the local fallback.)

**Inspect the output by hand before committing it**, the same way the
original Ollama recordings were checked in phase 4/5c — a bigger model is
generally more reliable, not infallible. Compare against the existing
Ollama-recorded `Requirement`/`ExtractedDocument` values; anything that
changed either reveals an Ollama-era mistake (good, fix the old fixture's
expectations) or a Vertex-era mistake (fix that entry by hand, same as the
Ollama `Photograph`/`Specimen Signature` correction in phase 4).

Delete the stale `ollama`-provider entries in `fixtures/llm_cache/` and
`fixtures/ocr_cache/` only *after* the new `vertex` entries are recorded,
inspected, and green — never before, so there's always a working set of
fixtures to fall back to if something goes wrong mid-migration.

## 6. Verify

```bash
KAGAZ_LLM_MODE=replay KAGAZ_MODEL_PROVIDER=vertex pytest
KAGAZ_LLM_MODE=replay KAGAZ_MODEL_PROVIDER=vertex KAGAZ_OLLAMA_HOST=http://127.0.0.1:1 pytest
```

Both must be fully green. The second run proves the suite still doesn't
depend on Ollama being reachable once Vertex fixtures exist.

## 7. Flip the default and redeploy

`render.yaml` already defaults `KAGAZ_MODEL_PROVIDER=vertex`. Add
`GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` and however this deploy's
credentials reach Render (a service account with workload identity, or —
less ideally — a service account key stored as a Render secret, never
committed to the repo). Push; Render redeploys the blueprint
automatically. If `KAGAZ_LLM_MODE` also flips from `replay` to `live` (a
real deployment against Vertex, not just replaying fixtures under a new
provider label), the "running in replay mode" banner in
`web/templates/base.html` correctly stops rendering on its own — it's
driven by `KAGAZ_LLM_MODE` at request time, nothing to edit by hand.

Nothing in application code changes for this switch — if you find yourself
editing `agents/*.py` or `tools/*.py` to make Vertex work, something has
gone wrong with the factory boundary; fix `model_provider.py` instead.

## Multimodal / vision OCR

Once Vertex is verified working, `tools/ocr.py`'s `vision` backend
(`KAGAZ_OCR_BACKEND=vision`, the default when `KAGAZ_MODEL_PROVIDER=vertex`)
reads document images directly through Gemini instead of rapidocr — see
that module's docstring for how it's selected and cached.

## 8. Real-user accounts: Firestore + Cloud Storage

The synthetic demo (`/`, `/run/*`) needs none of this — it's in-memory and
pre-seeded. The real-user flow (`/signup`, `/login`, `/app/*`) persists
accounts and runs in Firestore and stores uploaded documents in Cloud
Storage, authenticated via the *same* ADC set up in step 2 — no separate
credentials.

```bash
gcloud services enable firestore.googleapis.com --project=kagaz-509105
gcloud firestore databases create --project=kagaz-509105 \
    --location=us-central1 --type=firestore-native

gcloud storage buckets create gs://kagaz-509105-uploads \
    --project=kagaz-509105 --location=us-central1 \
    --uniform-bucket-level-access
```

(`storage.googleapis.com` is usually already enabled alongside Vertex; if
not, `gcloud services enable storage.googleapis.com` too.) No extra IAM
grant is needed beyond what step 2's ADC principal already has if that
principal is a project owner/editor; otherwise grant `roles/datastore.user`
and `roles/storage.objectAdmin` on the bucket.

`db.py`'s `list_runs_for_user` runs a composite query (`user_id ==` +
`order_by created_at`), which Firestore requires a composite index for.
Create it once:

```bash
gcloud firestore indexes composite create --project=kagaz-509105 \
    --collection-group=runs --database="(default)" \
    --field-config=field-path=user_id,order=ascending \
    --field-config=field-path=created_at,order=descending
```

(Index builds take a few minutes; `gcloud firestore indexes composite list
--project=kagaz-509105` shows build status.) If you skip this, the first
call to `db.list_runs_for_user` fails with `FailedPrecondition: The query
requires an index` and the error message itself contains a console link to
create it interactively instead.

Set `KAGAZ_GCS_BUCKET` if the bucket name isn't
`{GOOGLE_CLOUD_PROJECT}-uploads` (`blob_storage.py`'s default), and
`KAGAZ_SESSION_SECRET` to a real random value in production (`api/main.py`
refuses to start without it when `KAGAZ_ENV=production`; a fixed insecure
default is used otherwise, for local dev only).

Tests in `tests/test_auth.py`'s `TestWebFlow` class (and later phases'
Firestore/GCS-backed tests) run against this real project — no emulator is
wired up — and are skipped automatically when `GOOGLE_CLOUD_PROJECT` isn't
set, same pattern as `test_model_provider.py`'s live-provider test.
