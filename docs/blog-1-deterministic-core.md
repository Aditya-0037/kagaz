# Agents for Humans: the case for a deterministic core

Kagaz is an agent built on the Strands Agents SDK, and about half of this
post is going to be about the parts of it that are deliberately *not*
agentic at all.

## The question that's tempting to just ask a model

The obvious way to build the part of Kagaz that compares a name on one
document against a name on another is to ask an LLM: "are these the same
person?" It's a reasonable-sounding shortcut, and an 8B model will answer
it, most of the time, in a way that sounds right.

The problem is what "most of the time" means in practice. Ask the same
model the same question — "Aditya Kumar Sharma" vs. "A. K. Sharma," same
tokens, one abbreviated — on two different runs, and there's no guarantee
you get the same answer twice. Sampling temperature, an unlucky token, a
slightly different prompt template version: any of it can flip "same
person, abbreviated" into "these may be different people." Nothing about
the input changed. Only the model's mood did.

That's not a tolerable failure mode for a system whose entire pitch is
"catch the thing a human would miss." If the answer can flip between two
identical runs, you don't have a rule, you have a coin flip with
vocabulary. And in a live demo, in front of judges, a coin flip that
lands wrong once is the only thing anyone remembers.

## So the comparison isn't a prompt

`tools/name_match.py` and `tools/dates.py` are plain Python. No model
call, no `Agent()`, no prompt. Every input produces the same output every
time, on any machine, forever — which is also, not coincidentally, the
property that makes them unit-testable in the normal software-engineering
sense rather than the "run it 20 times and eyeball the pass rate" sense
LLM behavior usually requires.

The rule table (spec-derived, and directly mirrored in
`tests/test_name_match.py`'s 30 cases):

| Situation | Example | Verdict |
|---|---|---|
| Identical tokens | "Aditya Kumar Sharma" = "Aditya Kumar Sharma" | match (no finding) |
| Strict subset | "Aditya Kumar Sharma" vs "Aditya Kumar" | `likely_fine` |
| Initial expands to a token | "A. K. Sharma" vs "Aditya Kumar Sharma" | `likely_fine` |
| Glued initials (OCR/real-world) | "A.K. Sharma" vs "A. K. Sharma" | `likely_fine` |
| Same tokens, different order | "Sharma Aditya Kumar" vs "Aditya Kumar Sharma" | `likely_fine` |
| Transliteration, edit distance ≤2 | "Aditya" vs "Aaditya" | `worth_knowing` |
| Same-position token, genuinely different | "...Sharma" vs "...Verma" | `blocker` |
| Disjoint token sets | "Priya Ramesh Nair" vs "Fatima Ayesha Khan" | `blocker` |

And for dates: `tools/dates.py`'s `compare_dob` parses both raw strings
under the DD/MM/YYYY convention and flags a `blocker` the moment they
resolve to different calendar dates — which is exactly what catches
`05/06/2007` vs. `06/05/2007`: two different real dates that *look* like
they could be the same typo from a distance. `check_validity` compares a
document's expiry against the scheme deadline with three fixed windows
(already expired / expires before the deadline / expires within 60 days
after) — again, no model, just a `datetime` subtraction.

Every one of these rules is deterministic in the literal sense: give it
the same two strings a thousand times, get the same verdict a thousand
times. That's the property an LLM comparison cannot offer, no matter how
good the prompt.

## Where the LLM actually earns its place

This isn't an argument against using models — Kagaz calls one constantly.
Reading a scheme notification's prose to figure out what documents it
requires, or reading OCR'd certificate text to extract a name and a date,
are genuinely open-ended language tasks; there's no fixed rule table for
"what does this paragraph mean." That's exactly where an LLM belongs, and
exactly where Kagaz uses one (see
[`docs/blog-2-cost-discipline.md`](blog-2-cost-discipline.md) for how that
part is kept honest and cheap).

The line Kagaz draws is specific: **extraction is a model's job; judgment
against a fixed rule is not.** Once the OCR text has become a `name`
string and a `dob` string, comparing two of them is arithmetic with extra
steps, and arithmetic doesn't need an opinion.

## Why this matters more than it sounds like it should

A hackathon demo runs once, in front of an audience, and has to be right
that one time. A deployed system runs thousands of times, unattended, and
has to be right *every* time, consistently, in a way an office worker can
learn to trust. Both of those are actually the same requirement:
determinism where determinism is available. The interesting, hard part of
Kagaz — deciding whether "A. K. Sharma" is the same person as "Aditya
Kumar Sharma" — turned out to be the part that most needed to *not* be
agentic. The agent's job was reading the paragraph that made the rule
table possible in the first place.
