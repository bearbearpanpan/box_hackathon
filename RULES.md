# Reality Check — Decision Rules

The three rules that turn "it depends" into a crisp "60 promised, history says 95."
Everything else (Box wiring, PDF, review task) is plumbing. These three decide the demo.

---

## Metadata schema (what Box AI extracts per doc)

Every document gets these fields written back as Box metadata:

| Field              | Type   | Example            | Notes                                      |
|--------------------|--------|--------------------|--------------------------------------------|
| `doc_type`         | enum   | `closeout_report`  | closeout_report / supplier_quote / delay_notice / lessons_learned / sla_credit / draft_contract |
| `project_size_kw`  | number | `1200`             | Rack deal size in kW (our "how big" axis)  |
| `region`           | string | `US-East (Ashburn)`| Metro/region (our "where" axis)            |
| `supplier`         | string | `Meridian Power`   | Primary equipment/power supplier           |
| `promised_days`    | number | `60`               | Promised lead time at contract signing     |
| `actual_days`      | number | `95`               | Actual delivery time (closeouts only)      |
| `delay_reason`     | string | `PDU shortage`     | Short cause tag                            |
| `signed_quarter`   | enum   | `Q4`               | Quarter the deal was signed                |

---

## RULE 1 — Similarity (what makes a past deal "comparable")

A past closeout is **comparable** to the draft if it clears a gate, then it's ranked.

**Gate (must pass all):**
- Same `region` **OR** same `supplier` (at least one must match — a deal in a different metro with a different supplier tells us nothing).
- `project_size_kw` within **±40%** of the draft (same rough size class).

**Ranking (among those that pass the gate), score each candidate — higher is more similar:**
```
score =  3 * (supplier matches)        # exact supplier match is the strongest signal
       + 2 * (region matches)
       + 1 * (same signed_quarter)     # captures the "always slips in Q4" pattern
       + size_closeness                # 1 - |size_draft - size_cand| / size_draft, clamped to [0,1]
```
Take the **top 3** by score as the comparison set. If fewer than 3 pass the gate, use what passes and flag "thin history" in the report.

One sentence for a judge:
> "Similar means same metro or same supplier, within 40% on size — then we rank by supplier, region, quarter, and size, and compare against the three closest past deals."

---

## RULE 2 — Suggested safer timeline

Don't average. A mean of 6 deals is mushy and a judge will push on it. Use the comparison set (top-3):

```
suggested_days = max( p50(actual_days of comparison set),
                      promised_days_of_draft )
```
- Use the **median (p50)** of the comparison set's *actual* days — robust to one outlier.
- Never suggest a timeline **shorter** than what sales already promised (that would be absurd).
- Report also shows the **worst actual** in the set as the "if the Q4/supplier pattern repeats" number.

One sentence for a judge:
> "The safer date is the median of what those three comparable deals actually took — and we show the worst case alongside it."

---

## RULE 3 — Risk level

Compare the draft's `promised_days` against the comparison set's actual delivery:

| Level     | Condition                                              | Meaning                                   |
|-----------|--------------------------------------------------------|-------------------------------------------|
| 🟢 GREEN  | `promised_days >= p50(actual)`                         | Promise is at or above typical reality    |
| 🟡 AMBER  | `min(actual) <= promised_days < p50(actual)`           | Promise beats typical but some deals hit it |
| 🔴 RED    | `promised_days < min(actual)`                          | No comparable deal ever delivered this fast |

**Demo target:** the draft promises 60 days; the three comparable deals actually took 88, 95, 110 → min actual = 88 > 60 → **RED**, p50 = 95 → headline "60 promised, history says 95."

One sentence for a judge:
> "Red means no comparable deal in our history ever delivered that fast. This one's red."
