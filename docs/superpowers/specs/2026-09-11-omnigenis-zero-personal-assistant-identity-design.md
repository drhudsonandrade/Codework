# OmniGenis Zero Personal/Assistant Identity Design

**Status:** Approved design, pending implementation plan
**Date:** 2026-09-11
**Baseline main:** `fe0c91c99fe4cd57e14c69cc3b3c58edcb4e8be8`

## 1. Objective

The current tracked repository tree must contain zero plaintext occurrences of the four prohibited identity tokens approved for removal. The rule applies case-insensitively to file contents and tracked path names, including active code, tests, documentation, specifications, plans, evidence, and historical directories.

The repository must remain operational, auditable, provider-neutral, and scientifically unchanged while this cleanup is performed.

## 2. Scope

This design covers the complete tracked Git tree at the current branch tip. No tracked directory is exempt merely because it contains historical, evidence, migration, or audit material.

The migration includes:

- canonical repository identity metadata;
- self-hosted runner names and identity contracts;
- provider account-derived repository and package references;
- required-check metadata stored in governance files;
- historical source-control locators stored in tracked files;
- report/template control markers containing a personal identity fragment;
- optional AI/MCP documentation and attestations that name a specific assistant product;
- tests that currently preserve or assert any prohibited literal;
- new repository-wide enforcement preventing reintroduction.

## 3. Non-goals

This change does not rewrite existing Git object history, old pull-request comments, remote provider databases, or already-published immutable artifacts. Rewriting Git history would invalidate commit SHAs and evidence chains and is not required to achieve a zero-token current tree.

External systems may temporarily retain legacy account-derived names while migration is in progress. Those external values must not be serialized back into tracked repository files. Where external state must be verified, the repository stores stable numeric IDs, digests, provider integration IDs, or cryptographic fingerprints instead of the prohibited plaintext.

No genomic interpretation, clinical rule, scientific threshold, canonical ruleset byte sequence, report taxonomy, variant-calling behavior, or consent policy changes are part of this migration.

## 4. Canonical neutral identity

The product identity remains `OmniGenis`.

Canonical self-hosted runner names become:

- `omnigenis-runner-01`
- `omnigenis-runner-02`

Canonical runner routing remains:

- pool label: `omnigenis-isolated`
- per-runner labels: `omnigenis-01`, `omnigenis-02`

The repository identity contract must no longer persist an account-qualified full repository name. It must use stable neutral fields such as:

- `repository_id: 1212760346`
- `repository_name: OmniGenis`

Provider-qualified repository names are resolved dynamically only at execution time when required.

## 5. Prohibited-token representation

The enforcement mechanism itself must not contain the prohibited plaintext. The repository stores only case-insensitive token fingerprints and expected byte lengths.

Approved fingerprint set:

| Token class | Byte length | SHA-256 of lowercase ASCII token |
| --- | ---: | --- |
| P1 | 8 | `dd052083021cc0cd9c53c4456f395785eea0021d5ea56f5fb3869a6be535786f` |
| P2 | 6 | `0f6360072cf8ed9f46f90ce9d01fae4e42f5e8ff629499d2206c68ed403e2fe7` |
| P3 | 7 | `60965168ce762e949600281ba6d01fee136e5b6e8257b1f216f9025ed324474c` |
| P4 | 6 | `c857d09db23e6822e3600bc06ad8d58f92ed62bc8efd81c753f77048662cb97d` |

These fingerprints are policy data. Tests construct mutation inputs from numeric byte sequences or equivalent non-plaintext fixtures so that test code does not reintroduce a forbidden literal.

## 6. Repository-wide zero-token guard

Create a dedicated fail-closed guard that scans every Git-tracked path and every tracked blob.

The guard operates on raw bytes, not decoded text:

1. enumerate paths with Git, never with ambient filesystem recursion;
2. normalize ASCII uppercase bytes to lowercase for matching only;
3. scan path bytes and blob bytes using sliding windows for every configured token length;
4. hash each candidate window with SHA-256;
5. compare with the fingerprint set;
6. fail with path, byte offset, and token class only, never echoing the prohibited plaintext;
7. reject unreadable tracked blobs or Git enumeration failures instead of silently skipping them.

Because matching is byte-based, binary tracked files are covered without requiring UTF-8 decoding. There are no historical-directory exemptions.

The guard becomes part of `scripts/validate_repo.py` and mandatory CI validation.

## 7. Provider namespace decoupling

Tracked files must not persist a personal provider namespace.

Repository references should prefer stable identifiers:

- repository numeric ID;
- pull-request number;
- workflow run ID;
- job ID;
- artifact ID;
- commit SHA;
- package name plus immutable digest.

Where a workflow must construct a provider-qualified name, it uses runtime context variables supplied by the provider. The resulting qualified value is not committed as repository data.

Historical clickable URLs that would violate the zero-token rule are replaced by structured provenance records containing the stable IDs needed to reconstruct or query the event externally.

## 8. Package and container provenance

Versioned evidence must store package identity in owner-neutral form, for example:

- registry: `ghcr.io`
- package: `omnigenis-genome`
- digest: immutable SHA-256
- repository ID
- workflow run/job/artifact identifiers

Workflows may assemble a fully qualified image path dynamically from runtime repository-owner context. Tests validate the neutral package and digest contract rather than a hard-coded personal namespace.

## 9. Required-check and governance metadata

Provider-generated required-check names that embed account identity must not be committed verbatim.

For external checks, tracked governance data should bind to stable properties where available:

- integration ID;
- provider-neutral check family;
- cryptographic fingerprint of the live context when an exact context comparison is still required.

If a ruleset materializer needs the exact live context string, it must obtain it from authenticated provider state at application/verification time and must not persist that string into the tracked tree.

Live GitHub rulesets remain protected and semantically equivalent unless a separate approved migration is required to remove an external provider account name from live state.

## 10. Report and template control markers

Any report/template marker containing a personal identity fragment is replaced with the already canonical neutral control namespace:

- canonical control marker: `GENOMA-RULESET-v3.4`
- generic prefix: `GENOMA-RULESET-v`

Tests must preserve version exactness and reject malformed variants without storing the retired plaintext marker.

This marker migration must not change the canonical v3.4 ruleset bytes or the normative manifest identity.

## 11. Provider-neutral AI/MCP terminology

Tracked repository documentation and code must describe interfaces by capability rather than by assistant product name.

Use neutral terms according to context:

- `AI client`
- `MCP client`
- `interactive AI workspace`
- `project instructions`
- `secure MCP tunnel`
- `optional natural-language interface`

Attestation locators become provider-neutral, for example `project-instructions://GENOMA/instructions`.

No deterministic core behavior may depend on a named assistant vendor or product.

## 12. Historical and evidence migration

Historical tracked files are included in the purge. Their factual provenance is preserved by replacing identity-bearing locators with structured IDs and immutable digests.

A migrated historical record must continue to state what was executed, when, under which commit/run/job/artifact identifiers, and with which outcome. It must not fabricate a new historical URL or claim that a provider namespace was different at execution time.

When exact historical reconstruction depends on an external URL that cannot be stored under this policy, the record states that the external locator was intentionally de-identified and provides the stable IDs instead.

## 13. Runner migration

The current dual-label state remains the safety anchor until a protected-main canary has succeeded using `omnigenis-isolated`.

After the canary:

1. keep both runners online while removing retired pool/per-runner labels in a controlled sequence;
2. rerun the Runtime/Resource Gate before any re-registration;
3. leave runner 02 serving traffic while runner 01 is drained and re-registered as `omnigenis-runner-01`;
4. verify runner 01 online and execute a controlled canary;
5. only then drain and re-register runner 02 as `omnigenis-runner-02`;
6. verify both online and execute a final pool canary.

No operation may unregister or stop both runners simultaneously.

## 14. Migration sequencing

Implementation should be separated into governed stages:

### Stage A — Guard and neutral contracts

Add the fingerprint-based zero-token guard and convert canonical identity contracts to owner-neutral fields and neutral future runner names.

### Stage B — Current-tree purge

Remove all prohibited plaintext from active code, tests, docs, plans, specs, evidence, and tracked history. Replace owner-qualified provenance with stable IDs/digests and provider-specific assistant terminology with capability-based language.

### Stage C — External contract adaptation

Adapt governance validation, required-check verification, package evidence, and runtime materialization so external account-derived values are resolved dynamically or verified by fingerprint/ID without being committed.

### Stage D — Zero-token seal

Run the repository-wide guard over every tracked path/blob and require zero matches. Run a separate filename/path scan and the full project validation suite. Record exact-head evidence without embedding prohibited plaintext.

### Stage E — Runner external rename

After the protected-main canary and a fresh Runtime/Resource Gate, perform rolling runner re-registration to the canonical neutral names. This is an external operational action and must preserve at least one working runner at all times.

## 15. Testing requirements

The implementation must include:

- RED tests proving each fingerprint class is detected in content and filenames without plaintext fixtures;
- tests proving mixed-case occurrences are detected;
- tests proving binary blobs are scanned;
- tests proving historical directories are not exempt;
- tests proving tracked-file enumeration is authoritative and untracked files do not change the official result;
- tests proving duplicate/overlapping fingerprints cannot create an ambiguous PASS;
- tests for owner-neutral repository/package evidence;
- tests for provider-neutral project-instruction attestation semantics;
- tests for the neutral report control marker;
- mutation tests proving a prohibited token reintroduced anywhere blocks `validate_repo.py`;
- full repository regression and all existing scientific/normative integrity gates.

## 16. Definition of done

The migration is complete only when all of the following are true:

1. every Git-tracked path name has zero prohibited-token matches;
2. every Git-tracked blob has zero prohibited-token matches;
3. the zero-token guard is part of the official repository validator;
4. canonical runner names are neutral and contain no personal identity;
5. tracked repository/package provenance uses IDs, digests, neutral names, or runtime resolution;
6. tracked governance files contain no account-derived prohibited identity;
7. tracked historical/evidence files satisfy the same zero-token rule;
8. report/template control markers use the neutral canonical namespace;
9. assistant-product-specific terminology is absent from tracked files;
10. full tests, supply-chain checks, language guards, scientific boundaries, and rulesets are green;
11. a negative mutation proves the guard fails closed;
12. post-merge operational evidence confirms runner continuity before any legacy external identity is retired.

## 17. Rollback and safety

Repository cleanup is performed in a dedicated branch and PR. No automatic merge is allowed.

External runner changes remain staged and reversible until the protected-main canary is verified. The repository does not remove live rollback labels or re-register both runners together.

If removal of a tracked identity-bearing locator would destroy evidence that cannot be reconstructed from stable IDs/digests, implementation must stop and surface that specific case rather than silently deleting provenance.

## 18. Final invariant

The current tracked OmniGenis tree contains no personal or assistant-brand identity plaintext. External provider state is referenced only through neutral runtime resolution, stable IDs, or cryptographic fingerprints, and the repository continuously enforces that invariant fail-closed.
