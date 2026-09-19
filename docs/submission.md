# Hack Devengers 2.0 submission

[Hack Devengers 2.0](https://unstop.com/hackathons/hack-devengers-20-devengers-1749441)
— a 24-hour, fully virtual Open Innovation hackathon on Unstop, sponsored
by Lovable. 19 September 10:00 AM – 20 September 10:00 AM 2026. Individual
participation, no fixed problem statement or restricted tech stack: pick a
real problem, build it, ship a GitHub repo that shows the work done in the
window.

## What the hackathon actually requires

Per the official listing's "Submission Round" section:

- **Required:** Project Title, Project Description, GitHub Repository Link
- **Optional:** Live Demo/Deployment Link, PPT
- Submitted through a **Google Form only**, shared on the official
  Devengers WhatsApp channel (opens 1:00 PM on 19 September) — not through
  this repo, and not through Devpost.
- "Your GitHub repository should clearly showcase your project and work
  completed during the hackathon."

No video is required, no fixed rubric or problem statement is published,
and there's no separate blog-post or platform-account requirement (unlike
some other hackathons this project was earlier scoped against — see
"History" below).

## What it does

Kagaz is a pre-submission audit agent for Indian student scheme
paperwork. Give it a scheme notification and a student's document set: it
extracts what the scheme actually requires (documents, format specs,
deadline), verifies the student's documents against that requirement,
cross-checks names and dates across documents, converts documents to the
exact portal-required format, and produces a rejection-risk report. When
it finds something that genuinely needs a human decision — not a routine
naming variance, but a real conflict like a date-of-birth mismatch or an
expiring certificate — it raises a real interrupt and pauses until a
person decides. It never submits anything to any portal; a human always
takes the final downloaded folder from there. A second, real-account flow
(signup/login, real document upload, live model calls, Firestore/Cloud
Storage persistence) is layered on top of the same deterministic core —
see the README's "Two flows, clearly separated" section for what's live
today versus still in progress.

## Who it's for

Office staff at schools, colleges, and coaching centres who process
scheme applications for hundreds of students and don't have time to
re-derive each scheme's format rules by hand, student by student. (The
real-account flow additionally lets an individual student or applicant run
the same audit for themselves.)

## How it works

Built on the Strands Agents SDK. Requirement extraction is four small,
independently-cached model calls (not one large schema — a smaller model
handles four small tasks where it fails one big one). Documents are OCR'd
and read by one Strands agent per document type; photo and signature get
deterministic, non-LLM checks. Cross-checking — name comparison,
date-of-birth comparison, validity-window math — is pure, tested Python
with zero LLM calls; an LLM asked "are these the same person" is
inconsistent across runs, and that inconsistency is unacceptable in a
system whose whole pitch is consistency. Findings in three severity tiers;
only a `blocker` raises Kagaz's signature technical feature, a genuine
Strands human-in-the-loop interrupt that pauses the entire run for one
decision at a time. A separate expiry watcher scans every stored
document's validity date on its own schedule and emails a digest before
anything lapses. Every demo-flow model call is cached record/replay-style,
so the full test suite (and the deployed demo) runs with zero network
access and no API key; the real-account flow forces live calls instead,
deliberately never caching real user documents.

## What's genuinely novel here (for anyone skimming the repo)

- The requirement extractor doesn't have a hardcoded idea of what a
  scheme requires — it reads two structurally different real scheme PDFs
  and produces two genuinely different `Requirement` objects.
- The escalation interrupt is a real Strands interrupt (confirmed against
  strandsagents.com, not approximated with a status flag), verified to
  pause and resume correctly with zero network access.
- The cross-checker's three-tier severity system is a deliberate product
  decision, not just a data model: most naming variance is advisory, not
  blocking, because most naming variance is genuinely fine and treating
  it as an error trains people to ignore warnings.

## Submission checklist (Hack Devengers 2.0)

- [x] Project Title & Description — this README/this doc
- [x] Public GitHub repository, showcasing the work built in the window
      (MIT `LICENSE` at root)
- [ ] Push to a GitHub remote you control and make it public (currently
      local-only in this environment)
- [ ] Submit via the official Google Form once it's shared on the
      Devengers WhatsApp channel (required: title, description, repo link)
- [ ] *(Optional)* Live demo / deployment link — `render.yaml` is ready
      for a one-click Render Blueprint deploy; see the README's
      "Deploying" section
- [ ] *(Optional)* PPT — not drafted

## History (context, not a current requirement)

This project's first phases were originally scoped against a different
event (an AWS-hosted Agents for Humans hackathon, on the Strands Agents
SDK, with its own Devpost-style submission rules — video, AWS Builder ID,
sponsor blog posts). None of that applies to Hack Devengers 2.0's rules
above; the AWS-specific submission scaffolding
(`docs/video-script.md`, `docs/blog-1/2/3-*.md`) is kept in the repo as
supplementary writeups, not because this hackathon requires them. The
technical decisions those docs describe (deterministic core, cost
discipline, the escalation interrupt) are unchanged and still the
substance of what this repo is.

## Roadmap (explicitly out of scope for now)

A job-description-matching extension for placement offices is a natural
next step but is kept off the build list deliberately. It belongs on a
roadmap slide, not in this codebase.
