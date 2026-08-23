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

## What the ceremony certifies, and how you can tell

`genoma-production-ceremony.yml` and `genoma-production-witness.yml` used to do one thing:
`docker build`, `docker run` on the GitHub runner, and smoke `http://127.0.0.1:8787`. That
is a real live HTTP execution against a real container — and it is an **ephemeral CI
container** that ceases to exist when the job ends. The witness recorded the fixed string
*"live HTTP execution against a real container instance"* whichever address had been
dialled, so nothing downstream could tell that run from one against a laboratory's server.

Both workflows now take a `base_url` input:

| `base_url` | what happens | what it certifies |
|---|---|---|
| empty | builds the image for this commit and runs it hardened on the runner | that container, for the life of the job |
| set | provisions nothing, smokes the service already at that URL | that deployment |

The distinction is **measured, not declared**. `reporting/deployment_target.py` parses the
URL the smoke is about to dial, resolves it, and classifies the addresses as `loopback`,
`private-network`, `public-host` or `unresolved`. A `--deployment-kind deployed-host` flag
would have been one more self-declared field feeding the gate that reads it; a loopback run
records loopback whatever its operator intended, and a name resolving to several addresses
takes the weakest class, because which one was reached is not recorded.

That target travels the whole way:

- into the smoke's `classification` and `limitations`, replacing the fixed string;
- into `witness.json`, which the workflow refuses to write without one;
- into `witness_verdict`, which returns PENDENTE for a witness that does not say what it
  certified, and **recomputes the class from the addresses the witness itself records** — so
  editing `"network_class": "public-host"` into a loopback witness does not survive a read;
- onto the report's identity header, which now prints
  `POST-DEPLOYMENT: PASS — verificado contra serviço local ou contêiner efêmero, não um host
  implantado (http://127.0.0.1:8787)` instead of the bare word;
- through `provenance_blockers`, which re-runs the same recomputation on the compiled
  payload, so the printed clause cannot be improved by hand-editing.

`require_deployed_host: true` on the ceremony fails the run unless the measured class is
reachable beyond the runner — for when the run is *meant* to certify a deployment.

### The bootstrap is established in the same run, against the same target

Both workflows passed `deploy/attestations/bootstrap-project-v3.4.json` to the smoke. That
file is the honest PROPOSTO stub with all eight checks `false`, so the ceremony could only
ever fail. Worse, the fix of committing a VERIFICADO one would be an inherited PASS —
exactly what section 259 forbids. The workflows now run `verify_bootstrap_live.py` against
`$GENOMA_BASE_URL` first and feed the smoke *that* attestation, and the smoke refuses an
attestation whose `deployment.base_url` is not the URL it is dialling:

```
bootstrap_blockers: ["bootstrap was verified against 'https://genoma.example.org',
                     and this smoke is running against 'http://127.0.0.1:8787':
                     different deployments"]
```

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
  --bootstrap-attestation evidence/bootstrap-live-attestation.json \
  --deployment-id prod-2026-08-19 \
  --output evidence/live-smoke.json
```

The smoke's `--bootstrap-attestation` must be the one `--attestation-out` just wrote for the
same URL; the committed `deploy/attestations/bootstrap-project-v3.4.json` is the PROPOSTO
stub and will correctly fail the run.

Both exit non-zero when the deployment does not earn the verdict.
