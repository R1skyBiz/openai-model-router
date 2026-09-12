# Private source intake guide — Segment 2.6

The local `model-router calibrate export-intake` workflow converts a supplied
ChatGPT export into **private, unaccepted owner-review proposals**. Segment 2.6
implements and tests the adapter using synthetic records only. It accesses no
actual private export and leaves the 44-case/35-group corpus, statuses and disabled
canary unchanged. No paid calls or remote push are part of this workflow.

The implementation is under [ADR 0018](../decisions/0018-private-export-intake-boundary.md).
[Owner review](owner-review-packet-v1.md) and the [source gap plan](source-gap-plan-v1.md)
still govern acceptance. Automated redaction does not establish publication safety,
historical authenticity, task success, fair grading or semantic independence.

## Runtime and private workspace

Run from this repository using a prepared Python 3.12+ environment with its
existing dependencies and `uv`. An installed checkout exposes `model-router`.
The following helper also works with a prepared interpreter without installing
or modifying the project. Set `INTAKE_PYTHON` to that interpreter first:

```sh
calibrate() {
  env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src UV_CACHE_DIR=.uv-cache \
    uv run --offline --no-project "$INTAKE_PYTHON" \
    -c 'import sys; from model_router.calibration.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
}
calibrate export-intake --help
```

For this retained machine, the earlier `/private/tmp/model-router-pilot-pg-venv/bin/python`
is incomplete. Segment 2.6 tests instead used the bundled Python 3.12.14 interpreter
with that environment's retained dependency directory; see the exact test command
in the [handoff](flight-handoff-segment-2-6.md). Do not change packaging to mask a
local interpreter or editable-install problem.

Once the owner supplies an authorized source path, prepare an **external** private
workspace. These are future commands, not a claim that a real export exists:

```sh
umask 077
PRIVATE_BATCH="$HOME/ModelRouterPrivate/source-intake/batch-001"
mkdir -p "$PRIVATE_BATCH"
chmod 700 "$PRIVATE_BATCH"
# Generate once; retain the same key for stable references across exports.
# The exclusive create refuses to replace an existing key.
"$INTAKE_PYTHON" - "$PRIVATE_BATCH/source-key.bin" <<'PY'
import os, secrets, sys
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'wb') as stream:
    stream.write(secrets.token_bytes(32))
PY
```

Keep raw sources in their existing external location. Use absolute paths with no
symlink components; on macOS use `/private/tmp` rather than the `/tmp` symlink.
The output parent must already exist, belong to the current user, and have no
permissions for other users (0700). Output directories/files are 0700/0600.
Non-sticky group/world-writable ancestors are refused. Shared sticky system temp
ancestors are allowed; a private directory beneath them is still required.
Confirm actual backup/sharing policy: directory names and Unix modes do not
establish that a synced or backed-up location is private.

Create an optional UTF-8 private denylist at `$PRIVATE_BATCH/denylist.json` with
only these keys (values below are synthetic examples):

```json
{"personal_names":["Synthetic Person"],"organizations":["Example [Lab]"],"other":[]}
```

Terms are literal, case-insensitive strings with word boundaries, not executable
regex. Longest terms are replaced first. Identical matched terms receive stable
keyed aliases; removed values and alias dictionaries are never written. Keep the
key and denylist private; use the same files during extraction, validation and
promotion. The validator refuses a mismatched policy. No denylist is inferred
from unrelated private files.

## Formats and exact commands

Supported input is a direct UTF-8 conversation JSON file, an extracted directory
containing exactly one `conversations.json` at any depth, or a ZIP containing
exactly one such member. The JSON root may be a conversation list or an object
with a `conversations` list. Each usable conversation needs a parent-linked
`mapping` and at least one complete user/assistant text span. Field variability,
missing timestamps/current pointers and unsupported message content are handled
with explicit flags/counts. The adapter does not read chat HTML, download assets,
or convert PDF, audio, images, CAD or attachments to text.

```sh
PRIVATE_SOURCE='/absolute/external/path/provided-by-owner/export.zip'
REVIEW="$PRIVATE_BATCH/review-v1"

# Path/type/output-parent checks only; does not parse or read raw message content.
calibrate export-intake preflight "$PRIVATE_SOURCE" --output "$REVIEW"

# Parse and inspect in memory; print aggregate counts; write nothing.
calibrate export-intake inventory "$PRIVATE_SOURCE" \
  --key-file "$PRIVATE_BATCH/source-key.bin" --denylist "$PRIVATE_BATCH/denylist.json"

# Extract, sanitize, suggest grouping/grading, compare duplicates and write a bundle.
calibrate export-intake bundle "$PRIVATE_SOURCE" --output "$REVIEW" \
  --key-file "$PRIVATE_BATCH/source-key.bin" --denylist "$PRIVATE_BATCH/denylist.json"

# Recheck file/candidate/draft hashes and residual sensitive patterns, read-only.
calibrate export-intake validate "$REVIEW" \
  --key-file "$PRIVATE_BATCH/source-key.bin" --denylist "$PRIVATE_BATCH/denylist.json"

# Re-run comparisons into a NEW external report directory.
calibrate export-intake duplicates "$REVIEW" --output "$PRIVATE_BATCH/duplicate-review-v1" \
  --key-file "$PRIVATE_BATCH/source-key.bin" --denylist "$PRIVATE_BATCH/denylist.json"
```

`extract` is an alias for the full `bundle` operation so extraction cannot lose
its review/provenance sidecars. Omit `--denylist` everywhere if none was supplied.
The default output is `$HOME/ModelRouterPrivate/source-intake/review-v1`, with an
existing private parent required. Explicit per-batch output paths are preferable.
Existing destinations are refused, including empty directories. `--repository`
defaults to the current checkout; Git boundary discovery must succeed. There is
no override to allow raw sources or export outputs in a worktree.

Comparison defaults are the public sample, seed, reviewed pilot, tranche v1 and
tranche v2 at their documented repository paths. Missing defaults are explicitly
listed in `review-report.json`; a fresh clone cannot compare absent private
corpora. Repeat `--against /absolute/path/to/sanitized-corpus.jsonl` to supply an
explicit comparison set **instead of** defaults. Every supplied corpus must pass
the existing adjacent-manifest loader; invalid explicit comparisons fail the
operation. Never supply raw export files to `--against` or `calibrate import`.

## Expected external outputs

| File | Meaning |
| --- | --- |
| `candidates.jsonl` | Versioned proposal records: sanitized branch transcripts, opaque conversation/work-product IDs, source-record hashes, timestamps, attachment types, suggestions and required-review flags. Status is always `needs_owner_review`. |
| `case-drafts.jsonl` | Individual branch drafts compatible with `CalibrationCase`, human-review-only grading, `restricted` privacy and `unreviewed-export-draft` tags. Not a frozen corpus; no adjacent corpus manifest is generated. |
| `provenance-manifest.json` | Pipeline version, original conversation JSON byte hash, keyed policy references, candidate/draft hashes and all other bundle file hashes. No raw path or title. |
| `candidate-mapping.json` | External-only mapping to zero-based conversation-list positions and sorted raw mapping-key positions, opaque message/parent references and original canonical-record hashes. |
| `review-report.json` | Counts, comparison coverage/missingness, universal owner-review requirements; zero accepted cases and zero human decisions. |
| `skipped-records.json` | Opaque references/record indices and fixed reasons for unusable or repeated records. Unsupported parts/roles/attachments have aggregate counts in the review report. |
| `redaction-summary.json` | Category counts only, never removed values. |
| `grouping-suggestions.json` | Retain all branches of a conversation together, pending broader owner merge/split decisions. |
| `duplicates.json` | Exact canonical input and near-duplicate findings, including opaque comparison-case references. |
| `sanitization-validation.json` | Residual-pattern results with `publication_safe: false` and mandatory owner review. |

IDs use a private HMAC key. Conversation IDs are stable across exports when the
export supplies an unchanged conversation identifier. Without one, the fallback
is the canonical record hash and changes when the record changes. Candidate IDs
also pin the specific record revision. Titles are parsed into keyed references,
never published as text. Raw node IDs/paths are not emitted; use the external
ordinal mapping and original record to resolve a message privately. The original
byte pin covers `conversations.json`, not the ZIP container or attachments.
Record hashes use sorted-key compact UTF-8 JSON plus one newline.

A draft uses the branch's **last supported user request** as `task` (excluding
standalone English greetings/thanks by a narrow heuristic), preceding
supported turns as role-labeled `context_text`, and no final historical assistant
answer in generation input. All branches remain in one provisional work-product
group. This mechanical window may contain prior-answer leakage, unresolved tool
references or depend on another chat. The owner must author the correct complete
task window and assess dependencies; the draft is not an independently validated
case. Token/output bounds and consequence in the draft are authoring defaults,
not measurements or a consequence classification.

The exact-duplicate screen uses `canonical_case_input_sha256`. The near screen
uses lowercase task/context `re.findall(r'\w+', text)` token sets, excludes
formatting instructions and reports Jaccard scores at least 0.35. It compares
within the batch and against supplied corpora, retaining every draft. Duplicate
raw records are reported/skipped as repeat source evidence. Findings can be
reproduced by input order and hashes; comparison references hash the corpus ordinal
and case ID. They are triage evidence, never an independence certificate. Several
conversations may continue one investigation; different branches or formulations
must not automatically add work-product counts.

## Owner review and explicit later promotion

Compare each proposal privately with its original. Verify permission, origin,
sanitization, attachments and missing context; preserve units, measurements,
topology, temporal relationships, task intent, consequence and tool requirements.
Review every branch and select the relevant task window. Merge continuing
investigations; split only with evidence of independent deliverables. Defer cases
whose necessary technical context cannot survive sanitization. Establish grading
truth independently of historical assistant prose. Semantic criteria require
must-pass/omission/partial/contradiction anchors and human adjudication; executed
tool/CAD/code work still requires a suitable separately authorized harness.

Create `$PRIVATE_BATCH/approved-cases.jsonl` containing **only individually reviewed
survivors**, edited from the case drafts and validated against `calibrate schema`.
Remove `unreviewed-export-draft`, replace draft notes/defaults, supply independent
deterministic rules or an adjudicated semantic rubric, and retain private privacy
classification. Human-review-only placeholder grading cannot be promoted.
Do not edit the original review bundle: its pins must remain reproducible.

Create `$PRIVATE_BATCH/approvals.json`, an array with one decision per approved
case. The example is structural; replace each placeholder with inspected values.
Do not copy `true` attestations unless the owner has actually completed them:

```json
[{
  "case_id":"CASE_ID",
  "candidate_id":"CANDIDATE_ID",
  "candidate_sha256":"FROM_PROVENANCE_MANIFEST",
  "approved_case_sha256":"FULL_APPROVED_CASE_HASH",
  "branch_ref":"SELECTED_BRANCH_REF",
  "work_product_id":"OWNER_ADJUDICATED_GROUP_ID",
  "decision":"approve",
  "reviewer_ref":"opaque-owner-reference",
  "review_date":"2026-09-11",
  "privacy_reviewed":true,
  "origin_verified":true,
  "self_contained":true,
  "grouping_reviewed":true,
  "grading_reviewed":true,
  "independent_truth_verified":true,
  "consequence_tools_reviewed":true
}]
```

Compute each full approved-case hash with the existing schema/hash functions,
locally in the prepared environment. This command prints only IDs and hashes:

```sh
"$INTAKE_PYTHON" - "$PRIVATE_BATCH/approved-cases.jsonl" <<'PY'
import sys
from model_router.calibration.intake import read_cases
from model_router.calibration.corpus import case_content_sha256
for case in read_cases(sys.argv[1]):
    print(case.case_id, case_content_sha256(case))
PY

calibrate export-intake promote "$REVIEW" \
  --key-file "$PRIVATE_BATCH/source-key.bin" --denylist "$PRIVATE_BATCH/denylist.json" \
  --approved-cases "$PRIVATE_BATCH/approved-cases.jsonl" \
  --approvals "$PRIVATE_BATCH/approvals.json" \
  --version owner-reviewed-export-v1 --output "$PRIVATE_BATCH/promoted-v1"
calibrate validate "$PRIVATE_BATCH/promoted-v1/corpus.jsonl"
```

For an uninstalled checkout, prefix the hash command with `PYTHONPATH=src` or use
the same prepared dependency environment as the helper. Keep reviewer identity
opaque and all approval notes private. Every approval pins both the exact source
candidate and the full owner-edited case; editing either requires a new review.
The command adds immutable source/approval provenance, writes `corpus.jsonl`, its
adjacent full-hash manifest and `approvals.json`, and runs the existing loader
before publishing the new directory. Duplicate inputs, conflicting rubric
identities, missing/stale attestations and unreviewed placeholder grading fail.

Promotion creates a **new external version**. It does not merge with or mutate
the current corpus/status ledger, enable a canary or start evaluation. A future
explicitly approved corpus version may use the already-existing `calibrate import`
tooling for reviewed sanitized survivors at a new ignored destination; never use
that generic authoring command to bypass export review requirements.

## Threat model, bounds and recovery

The OS, current account and installed local code/Git are trusted. Input JSON, ZIP
metadata, messages and attachments are untrusted. The adapter rejects paths in
known linked worktrees and Git administrative directories, other detected Git
worktrees, symlink components, multiply linked raw files and nonregular inputs.
It opens raw files through directory descriptors with `O_NOFOLLOW`, and refuses
unsafe ZIP names, symlink/device/FIFO members, encryption, unsupported compression,
duplicate names, multipart/ZIP64 directory metadata and unreasonable expansion.
Archive content is never extracted or executed. Only local Git metadata commands
run; no network or provider interface is invoked.

Fixed limits: 256 MiB ZIP file; 64 MiB conversation JSON; 512 MiB total advertised
ZIP expansion; compression ratio at most 200; 10,000 archive/directory entries or
conversation records; 8 MiB ZIP central directory; 10,000 nodes/conversation;
128 leaves; 2,048 nodes/branch; 100,000 node×leaf product; 16 MiB retained transcript
characters; two million duplicate-comparison upper bound. Output files are at
most 64 MiB each and 128 MiB combined. JSON duplicate keys, non-finite numbers,
cycles, dangling parents and unbounded graphs are rejected or explicitly skipped.
These bounds intentionally decline very large/unusual exports instead of silently
truncating a task. Parser compatibility has been tested on synthetic exports only.

Redaction covers common email/phone/street-address patterns, credentials, bearer
and provider tokens, private key blocks, account/project IDs, UUIDs, SSNs, IPs,
local paths and configured entities. All HTTP/HTTPS/FTP URLs are redacted,
including credentials/query parameters, because even secret-free paths may be
private. This can remove technical references: owners must repair safely or defer.
International addresses/names, compact phone numbers, encoded/obfuscated secrets,
unlabeled identifiers and proprietary facts can escape detection. Redaction can
also match benign technical data. Every proposal therefore requires owner privacy
and technical-fidelity review; zero matches is never publication clearance.

No raw temporary extraction exists to clean up. Sanitized output is staged under
the external private parent, then renamed after validation; normal failures clean
the staging directory and leave no final output. A forced termination or power
loss can leave a mode-0700 `.intake-stage-*` containing sanitized private material;
inspect/remove only that abandoned directory locally, then retry with a new output.
Secure memory erasure, swap/core-dump protection, ACL/cloud-sharing audits,
malicious same-user processes and authenticity of owner attestations are outside
this tool's guarantees. File hashes detect mutation, not a malicious owner who
rewrites both data and hashes. No publication or historical-Git absence claim follows.

CLI failures print fixed reason codes, never raw exception text, filenames or
message excerpts. For `external_path_required`, choose an external non-symlink
path; for `private_parent_required`, prepare the private parent; for
`one_conversations_file_required`, select one specific extracted conversation file;
for size/graph limits, retain the original and create an owner-scoped external
subset without splitting an investigation. For malformed JSON, repair a separate
external copy and retain both hashes; do not paste raw errors or records into a
Git issue. For hash/policy mismatches, restore the pinned bundle/key/denylist or
create a new bundle and repeat review. Never weaken safety checks to force intake.

## Proving source files remain untracked

During actual intake, boundary refusal keeps raw input and output outside Git.
The ignore entries for `.calibration/`, private calibration trees, `private-intake/`,
`chatgpt-exports/`, `source-intake/` and root `conversations.json` are defense in
depth. Ignore rules cannot remove already-tracked or force-added files.

```sh
git status --short --branch
git ls-files calibration/internal calibration/private calibration/sensitive calibration/restricted .calibration private-intake chatgpt-exports source-intake conversations.json
git check-ignore private-intake/probe.json chatgpt-exports/probe.zip source-intake/probe.json conversations.json
git diff --cached --name-only
git diff --cached --check
git show --name-status --format=fuller HEAD
```

The private-path tracking query must be empty. Inspect the entire proposed patch
against the explicit code/test/documentation allowlist; never stage an external
bundle or force-add source records. Preserve byte hashes of the frozen corpus,
decisions, canary configuration and pre-existing reports before/after intake.
The Segment 2.6 handoff records these checks and synthetic package-exclusion tests.
They establish current index/change scope, not absence from all Git history, backups
or unreachable objects. No actual source record was accessed in Segment 2.6.
