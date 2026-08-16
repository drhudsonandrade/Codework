-- OPTIONAL Evidence Plane projection. The deterministic core never requires this schema.
create schema if not exists genoma_evidence;

create table if not exists genoma_evidence.runs (
  run_id text primary key,
  ruleset_sha256 text not null,
  commit_sha text,
  created_at timestamptz not null default now(),
  evidence_bundle_sha256 text not null,
  payload jsonb not null
);

create table if not exists genoma_evidence.attestations (
  attestation_id text primary key,
  run_id text not null references genoma_evidence.runs(run_id) on delete restrict,
  rule_id text not null,
  rule_sha256 text not null,
  status text not null check (status in ('EXECUTADO','VERIFICADO','INFERIDO','PROPOSTO','NÃO DISPONÍVEL')),
  decision text not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

-- Keep internal by default: no anon/authenticated grants are issued here.
revoke all on schema genoma_evidence from anon, authenticated;
revoke all on all tables in schema genoma_evidence from anon, authenticated;

-- Append-only guard. Updates/deletes require an explicit administrative migration.
create or replace function genoma_evidence.reject_mutation()
returns trigger language plpgsql as $$
begin
  raise exception 'GENOMA evidence projection is append-only; rebuild projection instead of mutating history';
end;
$$;

drop trigger if exists runs_append_only on genoma_evidence.runs;
create trigger runs_append_only before update or delete on genoma_evidence.runs
for each row execute function genoma_evidence.reject_mutation();

drop trigger if exists attestations_append_only on genoma_evidence.attestations;
create trigger attestations_append_only before update or delete on genoma_evidence.attestations
for each row execute function genoma_evidence.reject_mutation();
