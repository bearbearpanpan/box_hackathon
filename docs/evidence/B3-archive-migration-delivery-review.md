# Archive Migration Delivery Review
Document ID: B3 | Owner: Migration Delivery Office (Maria Chen) | Last updated: September 30, 2026 | Status: Approved closeout summary
Fictional demo data. Not actual AWS customer projects.
## Scope
Closeout results for completed archive migrations of 400-800 TB into the Archive tier over the last 12 months.
## Delivery outcomes
- MIG-2025-114, Contoso Records, 520 TB: promised 45 days, actual 61 days. Slip cause: customer-side export throughput.
- MIG-2026-019, Fabrikam Health, 610 TB: promised 40 days, actual 72 days. Slip cause: data validation and re-export of corrupt batches.
- MIG-2026-042, Tailspin Media, 480 TB: promised 50 days, actual 58 days. Slip cause: change-freeze window at customer.
- MIG-2026-077, Wingtip Legal, 700 TB: promised 45 days, actual 69 days. Slip cause: Archive Transfer Tool batch limits and re-queuing.
## Summary
- Comparable migrations took 58-72 days (median 65 days).
- No archive migration above 400 TB has completed in under 58 days.
- Most common causes: customer-side export speed, batch re-processing, and change freezes.
## Recommendation
For archives of 400-800 TB, commit to no less than 75 days from signature, or stage the migration with a first milestone at 30 days.
