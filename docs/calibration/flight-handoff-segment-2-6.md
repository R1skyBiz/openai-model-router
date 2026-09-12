# Calibration flight handoff — Segment 2.6

Implemented a local-only ChatGPT export intake and owner-review workflow. **No
actual private export was accessed.** The frozen corpus remains **44 cases,
35 conservative work-product groups, a 25-group gap to 60**, with existing
statuses and canary configuration unchanged. No model/API calls, paid execution,
canary enablement or remote push occurred.

## Starting state and scope

Verified before edits: `main` at
`f7ba8c78ab45eec84c79aa2704317563ac90162e`, seven commits ahead of the local
`origin/main` tracking ref, with no tracked/staged changes. The only untracked
files were `docs/calibration-canary-readiness-v1.md` and
`docs/calibration-provenance-tranche-v1.md`; both are preserved byte-for-byte and
remain untracked. Remote state was not queried.

Read the Segment 1/2 handoffs, owner review packet, source gap plan, prior private
intake guide, calibration contracts/authoring/loader/privacy code, and ADR 0017.
[ADR 0018](../decisions/0018-private-export-intake-boundary.md) records the new
private authoring boundary. Production routing, policy, provider behavior and
experiment admission remain unchanged.

## Architecture and changed files

| File | Change |
| --- | --- |
| `src/model_router/calibration/export_safety.py` | Git/worktree boundary discovery, descriptor-based external file checks, bounded ZIP/directory/JSON reading, strict JSON parsing, private staged output and cleanup. |
| `src/model_router/calibration/export_sanitize.py` | Deterministic pattern redaction, literal private denylists, keyed opaque references and residual-pattern scans. |
| `src/model_router/calibration/chatgpt_export.py` | Branch reconstruction, conversation grouping, owner-review drafts, external provenance/review bundle, cross-corpus duplicate screen, validation and explicit pinned promotion. |
| `src/model_router/calibration/cli.py` | `export-intake` subcommands and fixed, content-free rejection codes. |
| `tests/test_calibration_export_intake.py` | 83 synthetic workflow, security and promotion tests. |
| `tests/test_calibration_privacy.py` | Extend actual wheel/sdist sentinel exclusion checks and ignore/container checks to likely export-intake locations. |
| `.gitignore`, `.dockerignore` | Focused defense-in-depth entries for likely private intake directories and root conversation JSON. |
| `docs/calibration/private-source-intake-guide.md` | Executable workflow, output contract, owner decisions, promotion format, limits and recovery. |
| `docs/decisions/0018-private-export-intake-boundary.md` | Explicit offline intake and human promotion boundary. |
| `docs/calibration/flight-handoff-segment-2-6.md` | This completion and verification record. |

Commands are `model-router calibrate export-intake preflight`, `inventory`,
`extract`, `bundle`, `validate`, `duplicates` and `promote`. `extract` deliberately
produces the same full review bundle as `bundle`. Inventory writes nothing;
preflight does not parse raw message content. All extraction output remains
unaccepted. Promotion is a separate explicit operation requiring one exact
owner-edited case and approval record per selected survivor; the existing full
corpus loader validates the new version before the directory is published.

Parent links reconstruct all bounded branches deterministically, retaining edited
alternatives within one provisional conversation group. Cycles, missing parents
and unsupported graphs are not flattened into invented chronology. Repeated raw
records are reported, not counted as additions. Each branch's last supported
non-greeting/non-thanks user request can produce a draft with earlier turns as
context. Historical final assistant responses remain in the review transcript,
not grading truth. Tools, hidden/nonfinal channels, omitted content, attachments,
unknown current branches and incomplete messages require explicit review.

The review bundle includes candidate JSONL, schema-compatible case-draft JSONL,
private provenance manifest, ordinal source mapping, review/skipped/redaction
reports, grouping suggestions, duplicate findings and sanitization validation.
Default comparisons cover sample/seed/pilot/tranche v1/v2 when available; missing
corpora are disclosed. Explicit `--against` inputs replace defaults and must pass
manifest validation. No duplicate finding deletes or promotes a candidate.

## Security controls and limitations

Raw records, keys, denylists and outputs must be outside worktrees. Git boundary
discovery fails closed, strips Git environment overrides and includes linked
worktrees and Git administrative storage. Symlink components, multiply linked
raw files, nonregular input and untrusted writable ancestors are refused. Output
parents must be private/current-user-owned; new directories/files use 0700/0600.

ZIP central-directory allocation is bounded before `ZipFile` construction. Member
names/types/compression, traversal, symlinks, devices, encryption, duplicate names,
multipart/ZIP64 directory metadata, sizes and ratios are checked. Only conversation
JSON is read; no raw extraction or attachment copies are created. Output is
sanitized in memory and staged privately, with failure cleanup and validation
before publication. Fixed errors contain no raw data, supplied titles or paths.

HMAC references hide source identities; original conversation JSON and canonical
record hashes pin source evidence. All transformations are deterministic for the
same input, key, denylist and comparison set. Removed values never enter reports;
only categories/counts are recorded. Phone/email/address, credential/token,
account/project, UUID, SSN, IP, local-path and configured entity patterns are
covered. All network URLs are removed conservatively, including secret queries.
The guide enumerates exact bounds and unsupported formats.

Known limits: compatibility is tested on synthetic export shapes only; actual
export variability may need an explicitly scoped follow-up. Attachments are
metadata-only, semantic work-product independence cannot be established, and
multi-turn drafts need task-window/leakage/consequence/tool review. Greetings and
closing thanks are handled only by a narrow English heuristic. Redaction can miss
obfuscated/international/unlabeled data and remove necessary technical context.
No candidate is certified publication-safe. Private source bytes are not retained
in temporary files, but secure memory erasure, swap/core dumps, malicious same-user
processes, ACL/cloud-sharing policy and fabricated owner attestations are outside
the threat model. Forced termination can leave a private sanitized staging folder.

Promotion pins the source candidate and full approved-case hash, reviewer/date,
selected branch, grouping and seven explicit owner attestations. It requires
actual deterministic rules or a semantic rubric, removes no old status, and writes
a new external corpus with full case hashes and approval provenance. The software
validates the attestation structure/pins, not the truth of human judgment.

## Validation and preservation evidence

Final targeted test run: **83 passed**. Complete relevant regression: **189 passed**
(the 11 calibration test files plus the source authentication identity regression),
with two existing dependency deprecation warnings. The suite blocks socket access
and live credentials by default; new tests additionally block model construction,
provider execution and shell execution of supplied content. Export inputs and
comparison fixtures in the new tests are purpose-built synthetic data.

Coverage includes ZIP/directory/direct JSON/wrapped JSON, branched and edited
conversations, continued work products, incomplete messages, missing/malformed
fields, empty/greeting-only records, unsupported content, attachments, sensitive
patterns/denylists, deterministic output, duplicates and comparison missingness,
repository/linked-worktree/symlink/hardlink/FIFO refusal, ZIP traversal/types/size
and central-directory bounds, cleanup, suppressed error content, no dispatch,
bundle tampering, residual redaction checks and successful/rejected promotion.
Actual wheel and source archive builds exclude synthetic private sentinels,
including the new likely intake locations and root `conversations.json`.

The old Python 3.12 interpreter path no longer contained a complete standard
library; the current project environment lacked pytest. Offline cache-only setup
attempts could not satisfy all cached wheels. No dependency was downloaded and
no packaging/source change was made to conceal this. Tests used bundled Python
3.12.14 plus the retained compatible dependency directory, through `uv --offline`:

```sh
env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=src:/private/tmp/model-router-pilot-pg-venv/lib/python3.12/site-packages \
  UV_CACHE_DIR="$PWD/.calibration/segment-1-build-cache" \
  uv run --offline --no-project \
  /path/to/python3 \
  -m pytest tests/test_calibration_export_intake.py \
  --basetemp=/private/tmp/model-router-segment-2-6/targeted-final \
  -o cache_dir=/private/tmp/model-router-segment-2-6/pytest-cache

# Full relevant regression; run after targeted success.
env PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=src:/private/tmp/model-router-pilot-pg-venv/lib/python3.12/site-packages \
  UV_CACHE_DIR="$PWD/.calibration/segment-1-build-cache" \
  uv run --offline --no-project \
  /path/to/python3 \
  -m pytest tests/test_calibration_*.py \
  tests/test_phase6_auth.py::test_server_owned_identity_defeats_query_header_and_environment_spoofing \
  --basetemp=/private/tmp/model-router-segment-2-6/regression-final \
  -o cache_dir=/private/tmp/model-router-segment-2-6/pytest-cache
```

A pre-edit SHA-256 inventory covered 420 pre-existing tracked/private files,
including the two untracked reports. Exactly five pre-existing tracked files are
intentionally edited; the other **415 remain byte-identical**, including every
inventoried private corpus, status/source record, policy/model configuration and
canary artifact. The v2 loader independently confirms 44 pinned cases and 35
work-product IDs. The disabled canary still has `live_enabled: false`.

Private-path Git tracking queries are empty; ignore probes identify the expected
protections. Staged whitespace and the exact 11-file commit allowlist are checked.
Only code, synthetic tests, documentation and ignore rules enter the local commit.
These checks establish this change's scope/current index; they do not certify
absence from all historical Git objects. Test logs and the preservation inventory
are outside the checkout under `/private/tmp/model-router-segment-2-6/`.

## Exact next command when the owner supplies the export path

After preparing the external batch/key/optional denylist as documented in the
[guide](private-source-intake-guide.md), define this retained-machine helper:

```sh
calibrate_local() {
  env PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=src:/private/tmp/model-router-pilot-pg-venv/lib/python3.12/site-packages \
    UV_CACHE_DIR=.uv-cache \
    uv run --offline --no-project \
    /path/to/python3 \
    -c 'import sys; from model_router.calibration.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
}
PRIVATE_SOURCE='/absolute/external/path/provided-by-owner/export.zip'
PRIVATE_BATCH="$HOME/ModelRouterPrivate/source-intake/batch-001"
calibrate_local export-intake preflight "$PRIVATE_SOURCE" \
  --output "$PRIVATE_BATCH/review-v1"
calibrate_local export-intake inventory "$PRIVATE_SOURCE" \
  --key-file "$PRIVATE_BATCH/source-key.bin" --denylist "$PRIVATE_BATCH/denylist.json"
calibrate_local export-intake bundle "$PRIVATE_SOURCE" \
  --output "$PRIVATE_BATCH/review-v1" \
  --key-file "$PRIVATE_BATCH/source-key.bin" --denylist "$PRIVATE_BATCH/denylist.json"
```

Omit `--denylist` consistently if the owner supplies none. Expected output is the
new external `$HOME/ModelRouterPrivate/source-intake/batch-001/review-v1/` directory
with the ten files listed in the guide. Nothing is automatically imported into
`calibration/internal/`. The exact owner-authorized export path/scope, private
storage policy, denylist, branch/task-window choices, origin/privacy decisions,
work-product merges/splits, independent grading and promotion approvals remain
required. No owner approval or additional qualifying work product was invented.

This segment creates one focused local commit with the verified starting HEAD as
parent. Resolve its ID using `git log -1 --format=%H --
docs/calibration/flight-handoff-segment-2-6.md`; a commit cannot contain its own
hash. No push is performed.
