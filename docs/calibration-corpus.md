# Calibration corpus and evidence privacy

Calibration Lab corpora use UTF-8 JSON Lines and a byte-pinning manifest beside the
corpus. For `corpus-v1.jsonl`, the required manifest is
`corpus-v1.manifest.json`. The manifest records schema version, corpus version,
SHA-256 of the exact JSONL bytes, case count, highest privacy classification, and a
description. It may carry a full-case SHA-256 map; loading validates an authored map
or populates it when omitted so each run pins every replayed case. Loading fails
closed on a malformed line, hash/count/version/privacy
mismatch, unsafe or duplicate case ID, or duplicate canonical generation input.

Every case separates generation input from evaluation annotation. The canonical
generation input contains only `task`, `instructions`, `context_text`, and the output
contract. Classification and generation must never receive `task_family_hint`,
source kind, privacy, tags, notes, reference metadata, deterministic expectations,
or semantic rubrics. A separate comparison hash covers the canonical input plus
requirements, consequence, context bounds, deadline, and tool policy. Strategy runs
on the same case must record that comparison hash so fairness is auditable.

Privacy classifications are `public`, `internal`, `sensitive`, and `restricted`, in
increasing order. A manifest's classification must equal its most restrictive case.
Only reviewed public samples belong in `calibration/sample/`. Local corpora belong in
the ignored classification directory that matches their handling requirements.
Generated outputs and run stores belong in `calibration/generated/` or
`calibration/runs/`; the CLI's default local store is `.calibration/runs/`. These
locations are ignored and excluded from wheel, source archive, and Docker contexts.
The committed sample is solely a harness fixture. It is not representative
evidence and must not support routing-policy conclusions. Its fictional scenarios
all use low execution consequence so the Phase 1 V0-only offline path can exercise
them; dedicated tests cover rejection of envelopes that require stronger production
validation.

Sample JSON output contracts use the provider-supported strict subset: every object
declares `properties`, requires every declared property, and sets
`additionalProperties` to false; every array declares an item schema. This avoids a
provider silently tightening the contract and keeps deterministic grading comparable.

`CalibrationStore` keeps each run in an exclusive directory named by a portable run
ID. It writes and fsyncs the manifest before work begins, appends a narrow metadata
journal for dispatch intent and outcomes, and creates the final snapshot exactly
once. Reruns use new IDs. A completed directory cannot accept more events or another
snapshot. SHA-256 sidecars detect modification of both the manifest and final
snapshot. No-follow opens and real-directory checks reject symlink substitution;
an exclusive journal lock serializes append and finish across processes. Stored
manifests retain corpus/policy hashes, versions, strategy/config
snapshots, model and price metadata, timestamps, and software provenance. Rubric
prose and reference facts are replaced by a hash plus rubric ID/version. Pydantic's
excluded task and output fields remain absent, and open-ended metadata keys that
could contain content or credentials are replaced by hashes.

The journal accepts only identifiers, state, cost, latency, and provenance fields.
It rejects arbitrary error text, prompts, outputs, rubrics, references, and unknown
keys. Failure reasons must be stable codes rather than exception messages. This
allows started and uncertain paid actions to survive a crash without creating a
second raw-content store.

Human adjudication sometimes requires the candidate output that safe run evidence
deliberately omits. When experiment configuration explicitly enables review capture,
the runner may call `save_review_output` before finishing the run. This creates a
mode-0600 file under the run's ignored `review_outputs/` directory. Its relative
reference contains the candidate ID and output SHA-256; the payload and checksum
repeat and verify that association. Secret-shaped outputs are rejected. The normal
run snapshot stores only the relative reference, and retrieval requires an explicit
run-and-candidate lookup. Review output capture remains off by default.
