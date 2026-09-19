# Video script (draft) — 5 minutes

Shot list with narration. Timings are targets, not contracts — adjust in
the edit. Screen recordings should all be the actual running app (replay
mode is fine and is in fact the honest thing to show — it's what a judge
watching post-hoc would run too).

---

## 0:00–0:35 — The rejection letter (problem, cold open)

**Visual:** A close-up of a (synthetic, clearly-labeled) scheme rejection
notice. Slow zoom on the reason line: something bland and bureaucratic —
"Application rejected: documents do not meet prescribed requirements."

**Narration:**
> "This is what a rejected scholarship application looks like. It doesn't
> say why. The student doesn't find out until the window has already
> closed. And most of the time, it's not about merit — it's a certificate
> that expired eleven days too early, or a date of birth entered two
> different ways on two different documents. Nobody catches it on a skim.
> That's the problem Kagaz solves."

---

## 0:35–1:10 — The office's actual workload

**Visual:** A wide shot or mockup of a stack of paper folders, or a
spreadsheet with a long list of student names and application statuses.

**Narration:**
> "A school or coaching centre's office handles this for hundreds of
> students, for every scheme that opens each year. They don't have time to
> re-read each scheme's fine print by hand for every applicant. Kagaz
> does that reading for them."

---

## 1:10–1:35 — Who it's for, what it is

**Visual:** README or a simple title card.

**Narration:**
> "Kagaz is a pre-submission audit agent, built on the Strands Agents SDK.
> Give it a scheme notification and a student's documents. It works out
> what the scheme actually requires, checks the documents against it, and
> tells you exactly what would get this application rejected — before a
> portal does. It never submits anything. A human always presses submit."

---

## 1:35–2:30 — The three-student run

**Visual:** Screen recording: the web UI's index page, picking a student
and scheme, watching the progress screen.

**Narration:**
> "Three synthetic students, each testing something different. Priya's
> documents are all genuinely valid — her photo is just the wrong size,
> which the formatter fixes automatically. Run her, and Kagaz finds
> nothing wrong."

**Visual:** Results screen for priya_nair — "0 findings."

---

## 2:30–3:15 — The name-variance advisory (the judgment moment)

**Visual:** Results screen for aditya_sharma, showing the two
`likely_fine` findings.

**Narration:**
> "Aditya's name is spelled three different ways across his documents —
> 'Aditya Kumar Sharma' on his marksheet, 'Aditya Sharma' on his bank
> passbook, 'A. K. Sharma' on his domicile certificate. A naive system
> would flag all three as errors. Kagaz recognizes an omitted middle name
> and an abbreviated initial for what they actually are — normal, not a
> red flag — and says so, instead of blocking on something that isn't
> actually wrong."

---

## 3:15–3:50 — The two blockers nobody would catch

**Visual:** Results screen for mohammed_irfan (post-decision), zoomed on
the two findings: DOB mismatch and the expiring income certificate.

**Narration:**
> "Mohammed's case is the opposite: two real problems, both invisible to a
> human skimming. His date of birth is entered as 05/06/2007 on one
> document and 06/05/2007 on another — day and month transposed, which
> looks fine at a glance either way. And his income certificate expires
> eleven days before the scheme's deadline. Both would silently sink this
> application. Kagaz catches both."

---

## 3:50–4:20 — The escalation screen, live

**Visual:** Screen recording of the actual escalation screen appearing,
paused, waiting; click "Override," watch it resume and pause again on the
second finding.

**Narration:**
> "When Kagaz finds something that genuinely needs a human's judgment, it
> doesn't guess and it doesn't auto-correct — it pauses. This is a real
> interrupt, not a status flag: the entire pipeline stops here until a
> person decides. One finding at a time, never batched. Every decision is
> logged — who decided what, on what evidence."

---

## 4:20–4:40 — The expiry email arriving unprompted

**Visual:** Terminal or file browser showing `scripts/run_watcher.py
--as-of 2026-09-12` running, then the digest file opening.

**Narration:**
> "Separately, Kagaz watches every stored document's expiry date in the
> background. Seven days before Mohammed's income certificate expires, it
> emails the office — before anyone has to think to check."

---

## 4:40–5:00 — The downloaded folder (close)

**Visual:** The download button, the unzipped folder: `documents/`,
`values.csv`, `audit_report.pdf`, `checklist.md`.

**Narration:**
> "At the end, Kagaz hands back a folder: reformatted documents, a
> values sheet ready to copy into the portal, a full audit report, a
> checklist. Nothing gets submitted automatically. A human takes it from
> here — with everything they need to actually get it right the first
> time."

**End card:** Kagaz. Built on Strands Agents. All data synthetic.
