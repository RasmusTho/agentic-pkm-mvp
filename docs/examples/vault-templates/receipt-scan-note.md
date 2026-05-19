---
artifact_class: scan_or_receipt_note
artifact_type: receipt         # receipt | warranty | manual | contract | scan
lifecycle: durable             # durable | archived
work_relation: remember
area: "{{area}}"
project: "{{project}}"        # omit if not project-specific

provenance:
  source_kind: own_scan        # own_scan | own_photo
  source_file: "{{/path/to/original/scan.pdf}}"
  original_captured_at: "{{date}}"

# Fields below are AI-extracted and non-authoritative.
# The scan/PDF file is the authoritative record for any financial, warranty, or legal purpose.
extracted:
  vendor: "{{vendor name}}"              # [AI-suggested, non-authoritative]
  date: "{{purchase date}}"             # [AI-suggested, non-authoritative]
  amount: "{{amount and currency}}"     # [AI-suggested, non-authoritative]
  warranty_until: "{{date or N/A}}"     # [AI-suggested, non-authoritative]
  serial_number: "{{serial or N/A}}"    # [AI-suggested, non-authoritative]

authority:
  human_authored: true
  ai_generated_fields:
    - extracted.vendor
    - extracted.date
    - extracted.amount
    - extracted.warranty_until
    - extracted.serial_number
  source_authoritative: false    # the scan/PDF file holds source authority; this note does not
  ai_summary_authoritative: false
  requires_review: true

privacy: private                 # private | review-required
review_state: unreviewed         # unreviewed | reviewed

created: "{{date}}"
updated: "{{date}}"
---

## Notes

{{Human-written context: what this receipt/document is for, which project or purchase it relates to.}}

## Related

- [[{{Project or area link}}]]

---

_The original scan file at `source_file` is the authoritative record.
AI-extracted fields above are for convenience lookup only — not for legal, financial, or warranty
disputes. For legal or financial matters, refer to the original scan or physical document._
