# Approved Archive Solution Guide
Document ID: B1 | Owner: Archive Storage Product Team (Priya Raman) | Last updated: October 1, 2026 | Status: Approved for customer use
Fictional demo data. Not actual AWS product documentation or commitments.
## Purpose
This guide lists what the field team may promise today for the Archive Storage service. Anything not listed here must be confirmed with the product owner before it appears in a customer agreement.
## Supported capabilities
- Encryption at rest: supported for Standard and Archive tiers in all commercial Regions, including US-West (Oregon), using service-managed or customer-managed keys.
- Encryption in transit: TLS 1.2 or higher on all endpoints.
- Object versioning and object lock (compliance mode): supported for Standard and Archive tiers.
- Bulk import from exported files: supported through the Archive Transfer Tool for CSV manifests and ZIP batches up to 5 TB per batch.
- Lifecycle rules to move objects from Standard to Archive tier after a configurable number of days.
## Not supported or not approved
- Smart Archive Search is not a supported capability. See the Archive Product Roadmap (B2).
## Performance benchmark
Validated configuration: Archive tier, US-West (Oregon), 500-800 TB archive, objects 1-50 MB, 64 parallel readers.
- Sustained read throughput: 5 GB/s (validated September 2026).
- Peak burst read throughput: 7 GB/s for up to 10 minutes. Burst figures must not be promised as sustained.
- First-byte retrieval latency for Archive tier: 3-5 hours (standard retrieval), 1-5 minutes (expedited).
- Throughput above 5 GB/s sustained has not been benchmarked and requires a performance engineering review.
## Limits
- Maximum object size: 5 TB.
- Maximum Archive Transfer Tool batch: 5 TB.
