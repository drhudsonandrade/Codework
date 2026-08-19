# Automating POST-DEPLOYMENT without letting the system certify itself

## What the human was doing

`deploy/attestations/bootstrap-project-v3.4.json` shipped with all eight checks `false` and
this method: *"requires direct inspection of the live project instructions after the v3.4
BOOTSTRAP CURTO is installed"*. A person was expected to open the deployed configuration,
satisfy themselves that eight properties held, and flip the flags by hand.

That step was the last thing keeping POST-DEPLOYMENT permanently `PENDENTE`. It was also
the **weakest** link in the chain, because reading a configuration establishes what a
deployment is *configured* to do, not what it *does*. A stale config, a partially-applied
deploy, or an override elsewhere all read fine.

## What replaced it

`scripts/verify_bootstrap_live.py` decides each of the eight properties by **sending the
deployment a request whose response differs depending on whether the property holds**.

| check | probe |
|---|---|
| `consult_ruleset_before_relevant_genetic_analysis` | an analysis-relevant manifest must be evaluated through gates including RULESET_GATE, with the governing version reported |
| `require_status_vigente` / `require_version_v3_4` / `require_effective_date_2026_08_17` | `GET /v1/ruleset` must report the identity `normative` declares |
| `fail_closed_on_missing_or_conflicting_ruleset` | a manifest naming `v0.0` must be objected to **by RULESET_GATE** |
| `runtime_resource_gate_before_real_calling` | `requires_real_calling` without a runtime gate must be blocked **by the runtime gate** |
| `operational_status_contract_present` | a `qc.status` outside the §261 vocabulary must be refused, **and a valid one accepted** |
| `post_deployment_requires_live_15_of_15_zero_critical` | a `post_deployment` block claiming 0/15 must not be granted PASS |

This is strictly stronger evidence than inspection: it tests the running system.

## What stops it from being self-certification

- **No offline mode.** An empty base URL raises; an unreachable endpoint yields
  `NÃO DISPONÍVEL` with every check false. There is no "assume PASS".
- **Every probe is falsifiable.** `tests/test_bootstrap_live.py` stands up deployments that
  violate each property one at a time and requires the probe to catch each one. A probe
  that cannot fail is not evidence.
- **Specificity.** Two probes originally accepted any `ready == False`, which would credit a
  deployment that waved real calling through but tripped over unrelated missing consent.
  Each now requires *its own* gate to object.
- **Paired control.** The §261 probe checks that an invalid status is refused **and** that a
  valid one is accepted — otherwise a deployment that refused every manifest would satisfy
  it while enforcing nothing.
- **Recomputable.** Every raw response is hashed into the evidence, and the attestation
  carries an `evidence_sha256`.
- **No inheritance.** The attestation names `base_url`, `deployment_id` and `revision`, so a
  PASS cannot carry over to a later deploy — §259.

## What automation cannot supply

**Authorisation.** That *this* endpoint is the one the operator meant to certify is not a
fact any probe can establish. `--deployment-id` and `--revision` are therefore required and
recorded: the machine proves the behaviour, the caller names the target.

## The chain, verified end to end

Against the real policy engine (`python3 -m genoma_policy serve`):

```
verify_bootstrap_live.py   -> status VERIFICADO (8/8 checks)
run_live_post_deployment_smoke.py
                           -> bootstrap_verified: true, bootstrap_blockers: []
                           -> live smoke 15/15, critical_failures 0
                           -> post_deployment_status: PASS
```

and the negative control, the same attestation with its status downgraded:

```
                           -> bootstrap_verified: false
                           -> bootstrap_blockers: ["bootstrap status is 'PROPOSTO', not VERIFICADO"]
                           -> post_deployment_status: FAIL
```

The attestation is load-bearing, not decorative.

## Two probe defects the real server exposed

Both were found by running against the actual policy engine rather than only the fake:

1. **HTTP 200 was required.** The real engine answers an incomplete analysis manifest with
   **422**, which is the fail-closed behaviour this project wants — so correct refusal was
   being scored as a probe failure. The HTTP status is now recorded but excluded from the
   verdict.
2. **The §261 probe searched for keywords.** It looked for `EXECUTADO`/`VERIFICADO` in the
   response body, which tests nothing: a deployment ignoring the contract entirely passes as
   long as some unrelated field contains one of the words. It now submits an invalid status
   and requires the refusal, with the valid-status control alongside.

## Running it

```bash
python3 scripts/verify_bootstrap_live.py \
  --base-url https://your-deployment \
  --deployment-id prod-2026-08-19 \
  --revision "$(git rev-parse --short HEAD)" \
  --output evidence/bootstrap-live.json \
  --attestation-out deploy/attestations/bootstrap-project-v3.4.json

python3 scripts/run_live_post_deployment_smoke.py \
  --base-url https://your-deployment \
  --bootstrap-attestation deploy/attestations/bootstrap-project-v3.4.json \
  --deployment-id prod-2026-08-19 \
  --output evidence/live-smoke.json
```

Both exit non-zero when the deployment does not earn the verdict.
