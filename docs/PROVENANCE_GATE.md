# PROVENANCE_GATE — every printed value is bound to an artifact

## The hole this closes

`scripts/generate_report.py` described its input as *"structured, already-curated JSON"*.
That was accurate, and it was the largest remaining weakness in the system: the four-plane
audit, the publication gates, the sealed templates and the pixel QA all protect **how a
report is rendered**, while its **scientific content** arrived through a file somebody
typed.

Nothing downstream could distinguish a genotype that was measured from one that was written.
Ruleset section 6 (NO FALSE CERTAINTY) and section 8 (CAPABILITY HONESTY) were therefore
enforced by operator discipline rather than by the pipeline — exactly the arrangement the
rest of the project refuses to rely on.

## The two-stage binding

Neither stage can be satisfied by writing prose.

### Stage 1 — compile time, artifacts on disk

`reporting/provenance.py::PayloadCompiler.derive()` takes a **locator**, not a value:

```python
compiler.derive(
    "summary",
    artifact="completeness-matrix",
    locator="totals",
    status="VERIFICADO",
    basis="totais calculados a partir da matriz de completude",
    kind="computed",
    transform=lambda t: f"{t['interpretable']} de {t['targets']} alvos ...",
)
```

The compiler reads the locator out of the registered artifact and renders whatever is
there. A locator the artifact does not contain raises `ProvenanceError`. There is no
`value=` parameter for a derived field, so inventing a genotype is not a discouraged
practice — it is unrepresentable.

### Stage 2 — render time, artifacts may be gone

`provenance_blockers()` runs inside `reporting.engine._publication_blockers`, where the
pipeline outputs are no longer available. What it can still prove, and what defeats a
hand-edited payload, is that:

- every printed field carries an anchor at all (`provenance:unanchored:<field>`);
- the text about to be printed still equals the anchored `observed_value`
  (`provenance:mismatch:<field>`);
- the anchor block still hashes to its own digest (`provenance:sha256`);
- the declared status does not exceed the weakest anchor (`provenance:status_above_floor`);
- the floor and status distribution match the anchors they summarise
  (`provenance:floor_mismatch`, `provenance:distribution_mismatch`).

## Why there is no bypass flag

A QA fixture has to render a FINAL document in order to measure its layout. The obvious
shortcut — a `skip_provenance` flag, or exempting payloads that declare themselves
non-clinical — would reopen the hole one indirection further away, since anything could then
call itself QA.

Instead, a payload that is not derived from real artifacts is compiled with **`fixture`
anchors**, which are structurally forbidden from carrying any status above `NÃO DISPONÍVEL`.
Such a payload renders normally, and its own status floor reports `NÃO DISPONÍVEL` on the
page. The weak case is made to *say* it is weak rather than made impossible.

`reporting/provenance.py::fixture_payload()` is the canonical constructor; both QA scripts
and the engine tests use it.

## Anchor kinds

| kind | may claim | used for |
|---|---|---|
| `observation` | up to EXECUTADO | a genotype or record read from array/VCF output |
| `qc_metric` | up to EXECUTADO | a measured QC value (call rate, conflict rate) |
| `evidence_retrieval` | up to EXECUTADO | a verified external-provider retrieval |
| `computed` | up to EXECUTADO | a deterministic function of the above |
| `normative` | up to VERIFICADO | ruleset identity and run context |
| `case_control` | up to VERIFICADO | case/artifact identifiers, not measurements |
| `fixture` | **NÃO DISPONÍVEL only** | layout QA, tests, non-measurement scaffolding |

## Status floor vs. distribution

`operational_status` is the **weakest** anchor in the report — deliberately conservative, so
a report can never read stronger than its weakest supported statement. Because one honestly
absent section would otherwise make a mostly-verified report indistinguishable from an empty
one, `provenance.status_distribution` reports the full breakdown alongside it. Both are
recomputed by the gate rather than trusted.

## Negative controls

These are the negative controls that exist, by file and test name. The list is deliberately
exhaustive: an earlier version of this section named `tests/test_report_provenance.py` and
`tests/test_genome_completeness.py::CompletenessReportTest`, **neither of which exists in this
repository**, and enumerated ten controls of which several had no test at all. A citation that
cannot be opened is worse than no citation, because it reads as coverage.

`tests/test_reporting_provenance_regressions.py::ReportingProvenanceRegressionTest`:

- `test_extra_cannot_replace_the_compiled_report_identity` — `extra` cannot overwrite the
  compiled identity;
- `test_post_compile_publication_gate_edit_is_detected` — a value edited after compilation;
- `test_removed_section_is_detected_from_its_remaining_anchor` — a section removed while its
  anchor remains;
- `test_removed_finding_uncertainties_is_detected` — a finding's uncertainties removed;
- `test_extra_cannot_supply_any_block_compile_derives_from_artifacts` — every name in
  `DERIVED_BLOCKS`, one subtest each;
- `test_the_derived_block_guard_is_reached_and_not_shadowed_by_the_anchor_guard` — that the
  derived-block guard is the one refusing `publication_gate`, since `policy_evaluation` is
  also an anchored field and would hide its deletion;
- `test_a_derived_block_is_refused_even_beside_acceptable_keys` — buried in a valid `extra`;
- `test_the_reserved_verdict_artifacts_cannot_be_registered` — `register()` on
  `policy-evaluation` and `post-deployment-witness`;
- `test_free_text_cannot_be_introduced_through_a_derived_kind` and
  `test_derive_refuses_a_kind_that_is_not_derived` — both directions of the kind boundary;
- `test_a_restated_floor_or_distribution_is_recomputed_and_refused` — a block that reassures
  about itself;
- `test_a_status_declared_above_the_floor_is_refused` — each of the four statuses above
  NÃO DISPONÍVEL.

Plus the accepting cases beside them (`test_extra_that_touches_no_reserved_name_still_works`,
`test_an_ordinary_artifact_still_registers`), so the refusals are distinctions rather than a
blanket no.

`tests/test_execution_manifest_anchoring.py` covers the `execution_manifest[...]` namespace:
every key anchored, a mutated value, a removed key, an unanchored key added, and the whole
block replaced through `extra`.

`tests/test_rendered_text_matches_the_document.py` covers the rendering itself: that an
anchor's `observed_value` and the text `reporting.engine._safe` prints agree character for
character, end to end through `render_document`.

The last three controls in the first list were added when this section was corrected. Until
then it stated — accurately at the time — that free text through a derived kind, a restated
floor or distribution, and a status above the floor had no negative control. The code paths
existed and nothing pinned them.

**Reproducing this list, rather than trusting it.** Every name above is a test method, so the
claim is checkable in one command:

```bash
python3 -m unittest discover -s tests -p 'test_reporting_provenance_regressions.py' -v
python3 -m unittest discover -s tests -p 'test_execution_manifest_anchoring.py' -v
python3 -m unittest discover -s tests -p 'test_rendered_text_matches_the_document.py' -v
```

To find a claim of coverage that has gone stale — the failure this section was written
after, when it named `tests/test_report_provenance.py`, which does not exist:

```bash
grep -o 'tests/test_[a-z0-9_]*\.py' docs/PROVENANCE_GATE.md | sort -u | while read -r f; do
  test -e "$f" || echo "MISSING: $f"
done
```

That command currently prints exactly two lines, and both are correct:

```text
MISSING: tests/test_genome_completeness.py
MISSING: tests/test_report_provenance.py
```

Those are the two phantom citations named in the paragraph above *as* nonexistent. Any third
line is a real stale citation. To check the method names instead of the files:

```bash
python3 - <<'PY'
import pathlib, re, subprocess
doc = pathlib.Path("docs/PROVENANCE_GATE.md").read_text(encoding="utf-8")
cited = set(re.findall(r"`(test_[a-z0-9_]+)`", doc))
grep = subprocess.run(["grep", "-rho", "def test_[a-z0-9_]*", "tests/"],
                      capture_output=True, text=True).stdout
defined = {line.split()[1] for line in grep.splitlines()}
print(sorted(cited - defined) or "every cited test method exists")
PY
```

There is no coverage report committed to this repository, so "covered" here means "a named
test asserts it", verifiable by running the commands above — not a measured coverage
percentage.
