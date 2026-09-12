# ADR 0018: Private, offline ChatGPT export intake

Status: Accepted for explicitly authorized Calibration Segment 2.6.

Extend the authoring boundary in ADR 0017 with a local export adapter in
`model_router.calibration`. This authorizes no production routing, provider,
policy, telemetry, corpus-status or canary change. No private export is accessed
while implementing this segment; tests use purpose-built synthetic records.

Raw ZIP/directory/JSON sources, private key/denylist, review bundles and promoted
versions must be external to Git worktrees. Repository discovery must succeed.
Use bounded, read-only file descriptors without following symlinks, inspect ZIP
metadata before reading only conversation JSON, and never extract attachments.
Treat all export content as inert data. No network, model, API or tool execution
is part of this adapter; local Git commands establish repository boundaries only.

Retain parent-linked branches, including edited alternatives, within a provisional
conversation work-product group. Last-user-request drafts retain prior context;
final historical assistant responses stay in review transcripts and are never
invented grading truth. Missing context, multimodal/tool content, cross-chat
relationships, consequence and provenance require explicit owner adjudication.
Do not claim work-product independence from branch or conversation counts.

Use a private HMAC key for stable opaque identifiers. Retain original JSON byte
and canonical-record hashes, derivative hashes and external ordinal mappings.
Apply deterministic pattern/denylist redaction, retain only category counts,
and require human privacy review even when residual-pattern checks pass.
Version this transformation independently of routing policy. No automatically
sanitized artifact is certified publication-safe.

Candidate extraction never writes an accepted corpus. A separate promotion
operation requires an individually approved case hash and source-candidate hash,
selected branch, reviewer/date, grouping and explicit privacy, origin, grading,
independent-truth, consequence/tool and self-containment attestations. Promotion
creates a fresh external version, validates it with the existing corpus loader
before publication, and retains full case hashes and approval provenance. It
does not append to or rewrite frozen corpora, change old decisions, or authorize
execution. Generic authoring commands remain available; owners must not use them
to bypass this review gate for export derivatives.
