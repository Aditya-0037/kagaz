# Architecture

Kagaz's central argument is visible in this one diagram: **most of the
pipeline is deterministic Python, not an LLM**. Purple boxes are the only
places a model is actually called. Everything green is pure, tested
Python — name/DOB comparison, validity-window math, OCR, image checks,
packaging, the expiry watcher. The one red box is the escalation
interrupt: a genuine pause for a human decision, never approximated with a
status flag.

![Kagaz architecture](architecture.png)

(Source: [`architecture.mmd`](architecture.mmd) — regenerate the PNG with
`npx @mermaid-js/mermaid-cli -i docs/architecture.mmd -o docs/architecture.png -b white -w 1600`.)

```mermaid
flowchart TB
    subgraph INPUT["Input tiers"]
        direction LR
        PDF["Scheme PDF<br/>(pdfplumber)"]
        TEXT["Pasted text"]
        MANUAL["Manual dict"]:::det
    end

    subgraph EXTRACT["Requirement Extractor — 4 decomposed calls"]
        direction LR
        C1["checklist"]:::llm
        C2["fields"]:::llm
        C3["format specs"]:::llm
        C4["deadline"]:::llm
    end

    MERGE["merge → Requirement"]:::det
    DEADLINE["apply_deadline()"]:::det

    PDF --> EXTRACT
    TEXT --> EXTRACT
    C1 & C2 & C3 & C4 --> MERGE
    MANUAL -.->|"skips extraction entirely"| DEADLINE
    MERGE --> DEADLINE

    subgraph VERIFY["Verifier fan-out — parallel, dispatch is deterministic Python"]
        direction LR
        OCR["OCR (rapidocr)"]:::det
        V1["5 certificate-style<br/>verifier agents"]:::llm
        IMG["photo / signature<br/>image_checks"]:::det
        OCR --> V1
    end
    DEADLINE --> VERIFY

    CROSS["cross_checker<br/>name / DOB / validity rules<br/>zero LLM calls"]:::det
    VERIFY --> CROSS

    ESCALATE["escalation interrupt<br/>real Strands interrupt,<br/>one Finding at a time"]:::human
    CROSS -->|"Finding.needs_human"| ESCALATE
    CROSS --> PACKAGE
    ESCALATE --> PACKAGE

    PACKAGE["packager<br/>documents/ · values.csv ·<br/>audit_report.pdf · checklist.md"]:::det

    subgraph WATCHER["Expiry watcher — separate track, its own schedule"]
        direction LR
        SCAN["scan valid_until"]:::det
        DIGEST["render one digest"]:::det
        EMAIL["send: file / SES"]:::det
        SCAN --> DIGEST --> EMAIL
    end

    subgraph LEGEND["Legend"]
        direction LR
        L1["LLM call"]:::llm
        L2["deterministic Python"]:::det
        L3["human-in-the-loop"]:::human
    end

    classDef llm fill:#ede9fe,stroke:#7c3aed,color:#3b0764,stroke-width:2px
    classDef det fill:#dcfce7,stroke:#15803d,color:#052e16,stroke-width:2px
    classDef human fill:#fee2e2,stroke:#b91c1c,color:#450a0a,stroke-width:2px
```

## Reading the diagram

- **Input tiers** (top): a scheme notification arrives as a PDF (primary),
  pasted text (secondary), or — skipping extraction entirely — a manual
  dict a human already filled in. No URL fetching, no scraping.
- **Requirement Extractor**: four small, independently-cached model calls
  (checklist / fields / format specs / deadline) instead of one big
  schema — an 8B local model handles one small task reliably where it
  fails a large one (see `docs/blog-2-cost-discipline.md`). Merged
  deterministically in Python; nothing here is guessed — unresolved items
  land in `Requirement.unresolved`.
- **`apply_deadline()`**: copies the scheme deadline onto every
  `RequiredDoc` that actually expires (certificates, not marksheets or
  passbooks). This exists because the extractor deliberately never
  invents a per-document validity policy — see `agents/coordinator.py`'s
  docstring for the bug that fix guards against.
- **Verifier fan-out**: OCR is deterministic (rapidocr); reading fields off
  that OCR text is genuinely an LLM's job (five small agents, one per
  document type), but *which* verifier runs for *which* document is
  decided by Python, not a model — this is the Workflow multi-agent
  pattern (see `docs/sdk-notes.md`), not Graph or Swarm. Photo/signature
  never touch an LLM at all.
- **`cross_checker`**: the differentiating component, and it makes zero
  LLM calls. Name comparison, DOB comparison, and validity-window math are
  tested Python functions with a fixed rule table — an LLM asked "are
  these the same person" is inconsistent across runs, which is fatal in a
  live demo (see `docs/blog-1-deterministic-core.md`).
- **Escalation interrupt**: the one red box, and the only place a real
  pause happens. When a `Finding.needs_human` is `True`, the coordinator
  raises a genuine Strands interrupt — one Finding at a time, never
  batched — and waits for a human's accept/override/defer before
  continuing (see `docs/blog-3-escalation.md`).
- **Packager**: builds the deliverable folder and stops. Kagaz never
  submits anything to any portal; a human takes the folder from here.
- **Expiry watcher**: a separate track entirely — it doesn't run as part
  of an audit, it runs on its own schedule, scanning every stored
  document's `valid_until` and emailing one digest when something crosses
  a 60/30/7-day-out or expiry-day threshold.
