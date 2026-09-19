# Agents for Humans: cost discipline as a design constraint, not an afterthought

Kagaz was built with no cloud credentials at all for most of its
development, on a laptop, against a local 8B model. That constraint could
have been a handicap. Instead it produced two of the design's better
ideas: a record/replay cache that makes the whole test suite free to run,
and a decomposition of the requirement extractor that turned out to
matter for correctness, not just for cost — and both of those ideas are
exactly why later swapping the underlying provider (first evaluated
against AWS Bedrock, ultimately migrated to Google Cloud Vertex AI) was a
config change, not a rewrite.

## One factory, one cache

Nothing in Kagaz instantiates a model directly. Every agent asks
`model_provider.get_model()` for one, and which provider that returns —
`vertex` (the default), `ollama`, eventually `anthropic` — is controlled
entirely by an environment variable. Swapping providers is a one-line
change in deployment config; no agent code has to know or care.

Every one of those models' calls is then routed through
`llm_cache.cached_call`, keyed on `(provider, model, prompt, inputs)`.
Three modes:

- `replay` (the default, and what `pytest`/CI always use) — served
  entirely from a recorded fixture. A cache miss doesn't fall back to the
  network; it raises `LLMCacheMiss`, naming the exact key that's missing,
  so a developer can go record it on purpose.
- `record` — calls the real model and overwrites the cached entry.
- `live` — calls the real model and never touches the cache, for ad hoc
  manual testing.

The consequence: **the entire test suite — 177 tests, covering everything
from name comparison to OCR to the escalation interrupt to the full
coordinator pipeline — runs with no API key, no Ollama install, and no
network access at all**, verifiable with one flag:
`KAGAZ_OLLAMA_HOST=http://127.0.0.1:1 pytest`. That's not a testing nicety.
It's what made it possible to develop against a model that occasionally
had to be unreachable (a laptop closing its lid, a demo machine with no
internet) without the test suite going down with it, and it's what makes
this repository usable by anyone who clones it, with zero setup cost
before they see it work.

## Why one big extraction call doesn't work on an 8B model

The requirement extractor's job sounds like a single task: read a scheme
notification PDF, return a structured `Requirement` — document checklist,
field list, format specs, deadline, all at once. The first version tried
exactly that, one call, one large schema.

An 8B local model handles that unreliably. Not because it can't read the
document, but because holding four different sub-tasks in mind
simultaneously while also conforming to one large nested JSON schema is a
harder joint task than any one of those sub-tasks alone. The fix was to
decompose it into four small, independent calls — checklist, fields,
format specs, deadline — each with its own tiny Pydantic schema, merged
deterministically in Python afterward. Each of those four calls is a task
an 8B model is actually good at.

This wasn't just a cost optimization. It caught a real mistake.

## The Photograph that the checklist call missed

Scheme A's notification mentions seven required documents. Five of them —
income certificate, caste certificate, domicile certificate, marksheet,
bank passbook — are named directly in a checklist paragraph on page one.
The other two — a photograph and a specimen signature — are mentioned in
that same paragraph, but the model's checklist call, run against the real
document text, came back with only the first five. It simply didn't pick
up "Photograph" and "Specimen Signature" from the prose.

Separately, the *format-specs* call — a different one of the four decomposed
calls, reading the same document, looking specifically for a table of
size/dimension/format rules — correctly found both "Photograph" and
"Specimen Signature" in the page-3 annexure table, with exact numbers
(50KB, 276×354px for the photo).

Because these are two independently recorded, independently inspectable
calls rather than one blended extraction, this discrepancy was visible:
the format-specs fixture had two documents the checklist fixture didn't.
That's the whole point of decomposing the task — not just that a smaller
task is easier for a small model, but that a smaller task is a smaller,
checkable unit when it's wrong. A single monolithic extraction call would
have just silently returned five documents, and nothing would have looked
unusual about the output; there would have been no format-specs call to
disagree with it.

The fixture was corrected by hand (restoring "Photograph" and "Specimen
Signature" to the checklist), and that correction is now the recorded,
version-controlled ground truth every test runs against — not something
the live model has to get right again on every run. Which is really the
same idea as the cache, one level up: an 8B model is a genuinely useful
tool for turning prose into structure, and it does not have to be
infallible to be useful, as long as its mistakes are small, checkable, and
fixed once instead of live every time.
