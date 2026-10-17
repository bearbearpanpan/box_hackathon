# Reality Check

> Sales promises. Ops delivers. Reality Check makes sure they're the same number.

An AWS Bedrock + Box agent that reads a draft contract, finds comparable past
deals in document history, and flags when the promised timeline doesn't match
what similar deals *actually* took.

**The gap it closes:** The ERP has dates. It doesn't know the delay was a PDU
shortage, a permit in that metro, or a supplier that always slips in Q4. That's
in the documents — and that's what the agent reads.

## How it works

1. **Read** — Box AI pulls project size, promised vs actual date, delay reason,
   supplier, and location from each document and saves it as Box metadata.
2. **Check** — The draft's promises (quantity, timeline, location) are extracted;
   code finds similar past deals and compares promised vs actual days.
3. **Report** — A Box AI write-up with a risk level, cited reasons, and a safer
   suggested timeline, saved as a PDF in Box with a review task for the deal desk.

## The three rules

See [`RULES.md`](./RULES.md) for the full spec. In one line each:

- **Similarity** — same metro *or* same supplier, size within ±40%; rank by
  supplier, region, quarter, size; take the top 3.
- **Safer timeline** — median of the top-3's *actual* days (not a mean), floored
  at what sales promised; worst case shown alongside.
- **Risk** — 🔴 RED when the promise beats *every* comparable deal's actual
  delivery.

## Demo

Upload the draft (`docs/draft/DRAFT-01-contract.md`) live. ~30 seconds later:

> 🔴 **RED — "60 days promised, history says 95."**
> Comparables: CR-02 (actual 95), CR-05 (actual 110), CR-01 (actual 88).
> Cited reasons: Meridian PDU shortage, Q4 freight + Ashburn permit backlog,
> a prior 60→95 slip that triggered an SLA credit.
> Suggested safer timeline: **95 days**; worst case **110**.

## Dataset

13 seed documents live under [`docs/`](./docs/). See
[`docs/dataset-overview.md`](./docs/dataset-overview.md) for the full map and the
planted "Meridian always slips in Q4" pattern the agent is meant to discover.
