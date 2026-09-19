# Agents for Humans: the interrupt as product design, not just plumbing

It would have been easy to build Kagaz's "ask a human" feature as a status
flag: a `needs_review: bool` column, a dashboard that lists rows where
it's `True`, and a person who checks the dashboard when they get a chance.
That's what most systems do, and it's why most "human in the loop" agent
demos aren't actually about the human — the loop happens somewhere else,
later, disconnected from the moment the agent noticed a problem.

Kagaz doesn't do that. When a finding needs a human, the coordinator
raises a real Strands interrupt — the SDK's actual pause/resume
mechanism — and the run genuinely stops there. Not "gets marked for
review." Stops. The next line of code doesn't execute until a person
supplies an `accept`, `override`, or `defer`, and it resolves one finding
at a time, never batched, because a queue of five things to review at once
is not the same product experience as being shown one thing at a time and
asked to actually look at it.

## Why three tiers, and why only one of them pauses anything

Every comparison Kagaz makes lands in one of three severities:
`likely_fine`, `worth_knowing`, or `blocker`. Only `blocker` sets
`needs_human=True`. The other two are visible in the report, but the
pipeline doesn't stop for them.

That's a deliberate asymmetry, and it's the actual point. "Aditya Kumar
Sharma" on a marksheet versus "Aditya Sharma" on a bank passbook is a
genuinely ambiguous situation — dropping a middle name is completely
normal, most portals accept it, some might not, and there is no universal
right answer Kagaz can compute. Treating it as a `blocker` would mean
every application with a common, harmless naming inconsistency stops and
demands a decision from an office worker who already knows it's fine. That
doesn't build trust in the tool; it teaches people to click through
warnings without reading them, which is worse than not warning at all.

Treating it as `likely_fine` — visible, explained, not blocking — respects
that the office worker's judgment is the actual authority here, not
Kagaz's. Kagaz's job in that case is to make the comparison legible ("here
are the two names, here's why they probably match"), not to adjudicate it.
A date of birth that reads as `05/06/2007` on one document and
`06/05/2007` on another is a different situation: there is no benign
explanation for two different documents disagreeing about someone's actual
birth date, so it earns the interrupt.

## Nothing is auto-corrected, on purpose

Kagaz never rewrites a name, never picks the "more likely" date of birth,
never silently accepts a document past its window because the gap looks
small. Every finding is advice with evidence attached; the coordinator
decides what to do about `blocker`s by asking, and does nothing at all
about `likely_fine`/`worth_knowing` beyond reporting them. This is a
narrower claim than it might sound: it's not that Kagaz is cautious in
general, it's that *the one thing it is confident about is what it found,
not what should be done about it.* Those are different kinds of
correctness, and conflating them is how a tool ends up making a decision
nobody asked it to make.

## What this means for building agents meant to assist, not override

The distinction that matters is between an agent that *decides* and an
agent that *prepares a decision*. The second kind is more useful in
exactly the domains where being wrong is expensive and where the person
who'd catch the mistake is available and willing — an office worker who
already knows this student, already has a phone number to call and
confirm a middle name. Kagaz's escalation interrupt is built the way it is
because that person's judgment isn't a fallback for when the agent runs
out of confidence; it's the actual authority the whole system is designed
to serve, one finding at a time, with everything they need to answer
already in front of them.
