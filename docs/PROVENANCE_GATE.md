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

`tests/test_report_provenance.py` is written entirely as negative controls — each test
proves a specific way of stating something the data does not support is now refused:

- a locator absent from the artifact;
- an out-of-range index;
- an unregistered artifact;
- free text submitted through a derived kind;
- a fixture anchor claiming any measured status;
- a value edited after compilation;
- an injected section or finding;
- an anchor block edited to match a tampered value;
- a restated floor or distribution;
- a status declared above the floor.

`tests/test_genome_completeness.py::CompletenessReportTest` adds the end-to-end case: a
hand-edited headline count on report 09 is refused at render time.
