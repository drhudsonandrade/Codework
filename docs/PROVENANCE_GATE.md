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
- `test_removed_finding_uncertainties_is_detected` — a finding's uncertainties removed.

`tests/test_execution_manifest_anchoring.py` covers the `execution_manifest[...]` namespace:
every key anchored, a mutated value, a removed key, an unanchored key added, and the whole
block replaced through `extra`.

**Not covered by a test in this repository**, and stated here rather than implied: free text
submitted through a derived kind, a restated floor or distribution, and a status declared
above the floor. The code paths exist in `reporting/provenance.py`; what does not exist is a
negative control pinning them, and this section will say so until one does.
