#!/usr/bin/env python3
from __future__ import annotations
import json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.sealed_ruleset import EXPECTED_NAME,EXPECTED_SHA,verify_transport
PROVIDER_TERMS=(('chat'+'gpt').lower(),('open'+'ai').lower())
SKIP={'.git','node_modules','dist','__pycache__','.pytest_cache','.mypy_cache'}
GENOMIC=('.fastq','.fq','.bam','.bai','.cram','.crai','.vcf','.tbi','.fastq.gz','.fq.gz','.vcf.gz')
REQUIRED=(
'normative/sealed/v3.4/MANIFEST.json','manifests/RULESET_V3.4.sha256','template_store/v3.1/MANIFEST.json','template_store/v3.1/inbox/README.md',
'scripts/sealed_ruleset.py','scripts/materialize_ruleset.py','scripts/source_integrity_audit.py','scripts/pre_analysis_master_gate.py','scripts/verify_template_store.py','scripts/verify_supply_chain_lock.py','scripts/generate_all_reports.py',
'workflows/wgs.nf','workflows/array.nf','main.nf','policy_engine/genoma_policy/ruleset.py','policy_engine/genoma_policy/models.py','reporting/engine.py','locks/runtime-lock.json','locks/actions-lock.json',
'.github/workflows/genoma-audit.yml','.github/workflows/genoma-policy-engine.yml','.github/workflows/genoma-production-witness.yml','.github/workflows/genoma-production-ceremony.yml','.github/workflows/materialize-template-pdfs.yml')
def txt(p:Path)->str:return p.read_text(encoding='utf-8')
def validate(root:Path=ROOT)->list[str]:
 e=[]
 for r in REQUIRED:
  if not (root/r).is_file():e.append(f'missing required path: {r}')
 try:
  v=verify_transport(root/'normative'/'sealed'/'v3.4')
  if v.get('raw_sha256')!=EXPECTED_SHA or v.get('section_count')!=263:e.append('v3.4 sealed identity mismatch')
 except Exception as x:e.append(f'v3.4 sealed normative transport invalid: {type(x).__name__}: {x}')
 m=root/'manifests'/'RULESET_V3.4.sha256'
 if m.is_file() and txt(m).strip().split()!=[EXPECTED_SHA,EXPECTED_NAME]:e.append('RULESET_V3.4.sha256 mismatch')
 active=[]
 for p in root.rglob('REGRAS_PROJETO_GENOMA*.txt'):
  if any(x in SKIP for x in p.parts):continue
  try:s=txt(p)
  except UnicodeError:continue
  if re.search(r'^STATUS NORMATIVO:\s*VIGENTE\s*$',s,re.M):active.append(str(p.relative_to(root)))
 if active:e.append(f'active normative plaintext forbidden at rest: {active}')
 tm=root/'template_store'/'v3.1'/'MANIFEST.json'
 if tm.is_file():
  try:
   d=json.loads(txt(tm)); reports=d.get('reports',{}); rs=d.get('ruleset',{})
   if d.get('template_version')!='v3.1' or d.get('status')!='VIGENTE':e.append('template manifest is not v3.1/VIGENTE')
   if set(reports)!={f'{i:02d}' for i in range(1,12)}:e.append('template manifest must define 01..11')
   if rs.get('version')!='v3.4' or rs.get('sha256')!=EXPECTED_SHA:e.append('template suite is not bound to v3.4')
  except json.JSONDecodeError as x:e.append(f'invalid template manifest: {x}')
 rl=root/'locks'/'runtime-lock.json'
 if rl.is_file():
  try:
   d=json.loads(txt(rl))
   if d.get('ruleset_sha256')!=EXPECTED_SHA:e.append('runtime lock is not v3.4')
   if d.get('template_manifest')!='template_store/v3.1/MANIFEST.json':e.append('runtime lock is not template v3.1')
  except json.JSONDecodeError as x:e.append(f'invalid runtime lock: {x}')
 tokens={
  'workflows/wgs.nf':('PRE_ANALYSIS_MASTER_GATE','RULESET_V3.4.sha256','REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt','--strict','ready_for_requested_operation == true'),
  'workflows/array.nf':('ARRAY_PRE_ANALYSIS_MASTER_GATE','RULESET_V3.4.sha256','REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt','--strict','array-consent-provenance'),
  'main.nf':('array_consent_manifest','runtime_gate_manifest','freshness_state_manifest'),
  'reporting/engine.py':('"version": "v3.4"','EXPECTED_TEMPLATE_SUITE = "v3.1"')}
 for r,need in tokens.items():
  p=root/r
  if p.is_file():
   s=txt(p)
   for t in need:
    if t not in s:e.append(f'{r} missing safety token: {t}')
 for p in (root/'.github'/'workflows').glob('*.yml'):
  if '[skip ci]' in txt(p).lower():e.append(f'workflow contains forbidden CI bypass: {p.relative_to(root)}')
 for p in root.rglob('*'):
  if not p.is_file() or any(x in SKIP for x in p.parts):continue
  rel=p.relative_to(root); name=p.name.lower()
  if name.endswith(GENOMIC):e.append(f'genomic/reference payload must not be committed: {rel}')
  try:s=txt(p)
  except (UnicodeDecodeError,OSError):continue
  if any(t in s.lower() for t in PROVIDER_TERMS):e.append(f'provider-specific forbidden term remains: {rel}')
  if p.suffix=='.json':
   try:json.loads(s)
   except json.JSONDecodeError as x:e.append(f'invalid JSON: {rel}: {x}')
 return e
def main()->int:
 e=validate()
 if e:
  for x in e:print(f'FAIL\t{x}')
  return 1
 print('PASS\trepository_contract\tv3.4');print(f'PASS\truleset_sha256\t{EXPECTED_SHA}');print('PASS\ttemplate_contract\tv3.1');print('PASS\tactive_plaintext_rulesets\t0');return 0
if __name__=='__main__':raise SystemExit(main())
