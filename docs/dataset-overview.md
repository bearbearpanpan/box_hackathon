# Seed Dataset — Overview & Planted Patterns

15 documents designed so the demo produces a crisp, defensible result.

## The draft under test
- **Draft contract:** 1,200 kW rack deal, US-East (Ashburn), supplier **Meridian Power**, signed **Q4**, promises **60 days**.

## Planted pattern: "Meridian always slips in Q4"
Across the closeout reports, Meridian Power deals signed in Q4 slip hard (PDU shortages, holiday freight). This is the pattern the agent should "discover" and cite — it's the literal example in the pitch.

## How the top-3 comparison resolves (per RULES.md)
Comparison set for the draft (same supplier Meridian OR same region Ashburn, size within ±40% of 1200kW = 720–1680kW):

| Doc | Size kW | Region | Supplier | Signed Q | Promised | Actual | Why it ranks |
|-----|---------|--------|----------|----------|----------|--------|--------------|
| CR-02 | 1000 | US-East (Ashburn) | Meridian Power | Q4 | 60 | **95** | supplier+region+Q4+size → top |
| CR-05 | 1400 | US-East (Ashburn) | Meridian Power | Q4 | 75 | **110** | supplier+region+Q4 |
| CR-01 | 1100 | US-East (Ashburn) | Meridian Power | Q2 | 70 | **88** | supplier+region |

→ actuals = **88, 95, 110** → min=88 > 60 promised → **🔴 RED**, p50 = **95** → headline **"60 promised, history says 95."**

## The other closeouts (context / near-misses, shouldn't crowd the top 3)
- CR-03: 1250kW, US-West (Hillsboro), Vortex Grid, Q1 — different metro+supplier → gated OUT.
- CR-04: 900kW, US-East (Ashburn), Apex Cooling, Q3 — region match, on-time-ish (contrast case).
- CR-06: 2000kW, EU-West (Dublin), Meridian Power, Q4 — supplier match but size out of ±40% band → gated OUT (shows the size gate working).

## Full doc list (15)
1–6. Closeout reports CR-01…CR-06
7–9. Supplier quotes/delay notices: SQ-01 (Meridian quote), DN-01 (Meridian Q4 delay notice), SQ-02 (Apex quote)
10–11. Lessons-learned: LL-01 (Q4 freight), LL-02 (PDU supply chain)
12. SLA credit memo: SLA-01 (Meridian missed Ashburn SLA)
13. The draft contract: DRAFT-01
