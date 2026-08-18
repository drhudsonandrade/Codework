# GENOMA v3.0 Sealed Template Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the exact 48 sealed Base64 transport parts declared by the immutable GENOMA v3.0 template-store manifest and prove round-trip identity of all 11 historical PDF models.

**Architecture:** Treat `template_store/v3.0/MANIFEST.json` as the immutable byte-identity contract. Acquire only the exact pinned v3.0 PDF bytes or the exact approved one-shot ZIP, build/recover the already-declared tar.xz/Base64 transport, validate every aggregate and part checksum, then commit only `tplpart-000` through `tplpart-047` after strict verification succeeds.

**Tech Stack:** Python 3, hashlib, base64, tarfile/lzma, PyMuPDF for page-count verification where required, Git/GitHub, pytest.

**Spec:** `docs/superpowers/specs/2026-08-17-template-store-v3-sealed-parts-design.md`

## Global Constraints

- Repository must remain private.
- `template_store/v3.0/MANIFEST.json` identity values are immutable.
- `reporting/reference_v3_manifest.json` identity values are immutable.
- Input PDFs must be the exact 11 v3.0 files already pinned by SHA-256, byte size and page count.
- v3.1 PDFs, corrected PDFs, regenerated PDFs and visually equivalent PDFs are forbidden substitutes.
- The 13-part normative ruleset transport must not be modified.
- Current ruleset v3.4, prompt v1.2 and reporting content/layout are out of scope.
- Binary transport status remains `NÃO DISPONÍVEL` until all 48 parts and strict round-trip verification pass.
- Broader `POST-DEPLOYMENT PASS` is not implied by this task.

---

### Task 1: Prove Exact Source Availability

**Files:**
- Read: `template_store/v3.0/MANIFEST.json`
- Read: `reporting/reference_v3_manifest.json`
- Read: `template_store/v3.0/inbox/README.md`
- Read: `.github/workflows/materialize-template-pdfs.yml`
- No repository file changes in this task.

**Interfaces:**
- Consumes: immutable report identities and optional one-shot transport identity.
- Produces: a verified local source directory containing all 11 exact PDF bytes, or a fail-closed `NÃO DISPONÍVEL` result.

- [ ] **Step 1: Check the active runtime for all 11 exact v3.0 source filenames**

Run:
```bash
python3 - <<'PY'
import json
from pathlib import Path
m=json.loads(Path('template_store/v3.0/MANIFEST.json').read_text())
for k in sorted(m['reports']):
    print(m['reports'][k]['filename'])
PY
```
Expected: the 11 immutable v3.0 filenames are listed.

- [ ] **Step 2: Verify every candidate source before packaging**

Run against the source directory:
```bash
python3 - <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path('SOURCE_V3')
m=json.loads(Path('template_store/v3.0/MANIFEST.json').read_text())
for k in sorted(m['reports']):
    s=m['reports'][k]; p=root/s['filename']
    if not p.is_file(): raise SystemExit(f'NÃO DISPONÍVEL: {p}')
    b=p.read_bytes(); h=hashlib.sha256(b).hexdigest()
    if len(b)!=s['size_bytes'] or h!=s['sha256'] or not b.startswith(b'%PDF-'):
        raise SystemExit(f'INTEGRITY FAIL: {p.name}')
print('SOURCE IDENTITY: VERIFICADO')
PY
```
Expected: `SOURCE IDENTITY: VERIFICADO`. Any missing byte source stops implementation without substitution.

- [ ] **Step 3: If using the historical one-shot ZIP, verify its exact identity before extraction**

Run:
```bash
printf '%s  %s\n' \
  '2350111fa0dc26dd23515e0e3550748592c62147f480c11e09b12bca3557020b' \
  'GENOMA_REPORT_TEMPLATES_v3.0_DETERMINISTIC.zip' | sha256sum --check --strict
```
Expected: `OK`; otherwise do not use the ZIP.

### Task 2: Reproduce the Declared Aggregate Transport

**Files:**
- Read: `template_store/v3.0/MANIFEST.json`
- Temporary only: `GENOMA_V3_TEMPLATE_PACK.tar.xz`
- Temporary only: Base64 aggregate payload.

**Interfaces:**
- Consumes: exact verified v3.0 source directory from Task 1.
- Produces: archive bytes with size `1726200` and SHA-256 `3717f35b6eb0b82fc24f275cb216595c9d3281dc96558103ae791bc9bcf7174a`, plus Base64 payload of exactly `2301600` bytes.

- [ ] **Step 1: Build or recover the deterministic tar.xz using the established manifest contract**

The implementation must use the same file order and normalized tar metadata that produced the pinned archive identity. It must never change the manifest to fit a newly generated archive.

- [ ] **Step 2: Verify aggregate archive byte identity**

Run:
```bash
printf '%s  %s\n' \
  '3717f35b6eb0b82fc24f275cb216595c9d3281dc96558103ae791bc9bcf7174a' \
  'GENOMA_V3_TEMPLATE_PACK.tar.xz' | sha256sum --check --strict
[ "$(wc -c < GENOMA_V3_TEMPLATE_PACK.tar.xz)" -eq 1726200 ]
```
Expected: hash `OK` and zero exit status.

- [ ] **Step 3: Base64-encode without line wrapping and verify payload length**

Run:
```bash
base64 -w0 GENOMA_V3_TEMPLATE_PACK.tar.xz > GENOMA_V3_TEMPLATE_PACK.tar.xz.b64
[ "$(wc -c < GENOMA_V3_TEMPLATE_PACK.tar.xz.b64)" -eq 2301600 ]
```
Expected: zero exit status.

### Task 3: Generate and Validate the 48 Manifest Parts

**Files:**
- Create: `template_store/v3.0/sealed/parts/tplpart-000`
- Create: `template_store/v3.0/sealed/parts/tplpart-001`
- Create: `template_store/v3.0/sealed/parts/tplpart-002`
- Create: `template_store/v3.0/sealed/parts/tplpart-003`
- Create: `template_store/v3.0/sealed/parts/tplpart-004`
- Create: `template_store/v3.0/sealed/parts/tplpart-005`
- Create: `template_store/v3.0/sealed/parts/tplpart-006`
- Create: `template_store/v3.0/sealed/parts/tplpart-007`
- Create: `template_store/v3.0/sealed/parts/tplpart-008`
- Create: `template_store/v3.0/sealed/parts/tplpart-009`
- Create: `template_store/v3.0/sealed/parts/tplpart-010`
- Create: `template_store/v3.0/sealed/parts/tplpart-011`
- Create: `template_store/v3.0/sealed/parts/tplpart-012`
- Create: `template_store/v3.0/sealed/parts/tplpart-013`
- Create: `template_store/v3.0/sealed/parts/tplpart-014`
- Create: `template_store/v3.0/sealed/parts/tplpart-015`
- Create: `template_store/v3.0/sealed/parts/tplpart-016`
- Create: `template_store/v3.0/sealed/parts/tplpart-017`
- Create: `template_store/v3.0/sealed/parts/tplpart-018`
- Create: `template_store/v3.0/sealed/parts/tplpart-019`
- Create: `template_store/v3.0/sealed/parts/tplpart-020`
- Create: `template_store/v3.0/sealed/parts/tplpart-021`
- Create: `template_store/v3.0/sealed/parts/tplpart-022`
- Create: `template_store/v3.0/sealed/parts/tplpart-023`
- Create: `template_store/v3.0/sealed/parts/tplpart-024`
- Create: `template_store/v3.0/sealed/parts/tplpart-025`
- Create: `template_store/v3.0/sealed/parts/tplpart-026`
- Create: `template_store/v3.0/sealed/parts/tplpart-027`
- Create: `template_store/v3.0/sealed/parts/tplpart-028`
- Create: `template_store/v3.0/sealed/parts/tplpart-029`
- Create: `template_store/v3.0/sealed/parts/tplpart-030`
- Create: `template_store/v3.0/sealed/parts/tplpart-031`
- Create: `template_store/v3.0/sealed/parts/tplpart-032`
- Create: `template_store/v3.0/sealed/parts/tplpart-033`
- Create: `template_store/v3.0/sealed/parts/tplpart-034`
- Create: `template_store/v3.0/sealed/parts/tplpart-035`
- Create: `template_store/v3.0/sealed/parts/tplpart-036`
- Create: `template_store/v3.0/sealed/parts/tplpart-037`
- Create: `template_store/v3.0/sealed/parts/tplpart-038`
- Create: `template_store/v3.0/sealed/parts/tplpart-039`
- Create: `template_store/v3.0/sealed/parts/tplpart-040`
- Create: `template_store/v3.0/sealed/parts/tplpart-041`
- Create: `template_store/v3.0/sealed/parts/tplpart-042`
- Create: `template_store/v3.0/sealed/parts/tplpart-043`
- Create: `template_store/v3.0/sealed/parts/tplpart-044`
- Create: `template_store/v3.0/sealed/parts/tplpart-045`
- Create: `template_store/v3.0/sealed/parts/tplpart-046`
- Create: `template_store/v3.0/sealed/parts/tplpart-047`

**Interfaces:**
- Consumes: exact Base64 payload from Task 2 and manifest part table.
- Produces: 48 ASCII chunk files whose names, byte sizes and SHA-256 values exactly match the immutable manifest.

- [ ] **Step 1: Split by manifest-declared part sizes, not by an inferred constant**

Use a script that iterates `manifest['parts']`, slices exactly `size_bytes` bytes for each part, writes the named chunk and fails if any payload bytes remain or are missing.

- [ ] **Step 2: Verify all 48 parts against the manifest**

Run:
```bash
python3 scripts/verify_template_store.py --root template_store/v3.0 --no-materialize
```
Expected: strict successful verification with operational status `VERIFICADO`.

- [ ] **Step 3: Verify exact file count and naming**

Run:
```bash
test "$(find template_store/v3.0/sealed/parts -maxdepth 1 -type f -name 'tplpart-*' | wc -l)" -eq 48
```
Expected: zero exit status.

### Task 4: Round-Trip and Regression Verification

**Files:**
- Read: `scripts/verify_template_store.py`
- Read: `tests/test_template_store.py`
- Read: `tests/test_template_v3_contract.py`
- Read: `tests/test_repo_contract.py`
- No identity-manifest changes.

**Interfaces:**
- Consumes: committed-candidate 48 parts.
- Produces: evidence that the reconstructed archive and all 11 PDFs match immutable identities and that unrelated contracts remain intact.

- [ ] **Step 1: Run strict binary transport verification with materialization into a temporary directory**

Run:
```bash
python3 scripts/verify_template_store.py --root template_store/v3.0 --materialize-to /tmp/genoma-v3-materialized
```
Expected: `VERIFICADO` and 11 reconstructed PDFs.

- [ ] **Step 2: Run focused tests**

Run:
```bash
pytest -q tests/test_template_store.py tests/test_template_v3_contract.py tests/test_repo_contract.py
```
Expected: all tests pass.

- [ ] **Step 3: Confirm the normative 13-part transport is unchanged**

Run:
```bash
git diff main...HEAD -- normative/sealed
```
Expected: empty diff.

- [ ] **Step 4: Confirm no immutable manifest identities changed**

Run:
```bash
git diff main...HEAD -- template_store/v3.0/MANIFEST.json reporting/reference_v3_manifest.json
```
Expected: empty diff.

### Task 5: Commit and Review the Sealed Transport

**Files:**
- Add only: `template_store/v3.0/sealed/parts/tplpart-000` through `tplpart-047`
- Keep: approved spec and implementation plan documentation.

**Interfaces:**
- Consumes: fully verified files from Tasks 1–4.
- Produces: reviewable feature branch with immutable v3.0 binary transport completed.

- [ ] **Step 1: Inspect the exact change set**

Run:
```bash
git status --short
git diff --stat main...HEAD
```
Expected: the 48 sealed parts plus approved planning documentation; no unrelated system files.

- [ ] **Step 2: Commit the 48 verified parts**

Run:
```bash
git add template_store/v3.0/sealed/parts/tplpart-*
git commit -m 'data: add exact sealed GENOMA v3.0 template transport'
```
Expected: commit succeeds.

- [ ] **Step 3: Re-run strict verification on the committed tree**

Run:
```bash
python3 scripts/verify_template_store.py --root template_store/v3.0 --no-materialize
pytest -q tests/test_template_store.py tests/test_template_v3_contract.py tests/test_repo_contract.py
```
Expected: all checks pass.

- [ ] **Step 4: Open or update the pull request only after verification evidence is available**

PR description must state that the task completes the existing v3.0 sealed binary transport, does not alter current v3.4/v3.1 assets, does not change the 13-part ruleset transport, and does not imply broader POST-DEPLOYMENT PASS.
