#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.sealed_ruleset import verify_transport
from scripts.source_integrity_audit import audit as source_audit
from scripts.verify_template_store import verify as template_verify
SEALED_DIR=ROOT/'normative'/'sealed'/'v3.4'
def load(path:str|Path)->dict[str,Any]:
 v=json.loads(Path(path).read_text(encoding='utf-8'))
 if not isinstance(v,dict):raise ValueError(f'JSON object required: {path}')
 return v
def evaluate(runtime:dict[str,Any],freshness:dict[str,Any],consent:dict[str,Any])->dict[str,Any]:
 blockers=[];evidence={}
 try:evidence['ruleset_transport']=verify_transport(SEALED_DIR)
 except Exception as x:blockers.append(f'RULESET_TRANSPORT:{type(x).__name__}:{x}')
 source=source_audit(ROOT);evidence['source_integrity']={'operational_status':source.get('operational_status'),'blocking_failures':source.get('blocking_failures',[]),'counts':source.get('counts',{})}
 if source.get('operational_status')!='VERIFICADO':blockers.append('SOURCE_INTEGRITY_AUDIT')
 try:
  templates=template_verify(materialize=False);evidence['template_store']=templates
  if templates.get('operational_status')!='VERIFICADO':blockers.append('TEMPLATE_STORE_GATE')
 except Exception as x:evidence['template_store']={'operational_status':'NÃO DISPONÍVEL','error':f'{type(x).__name__}: {x}'};blockers.append('TEMPLATE_STORE_GATE')
 supply=subprocess.run([sys.executable,str(ROOT/'scripts'/'verify_supply_chain_lock.py')],cwd=ROOT,capture_output=True,text=True,check=False);evidence['supply_chain']={'returncode':supply.returncode,'stdout':supply.stdout[-8000:],'stderr':supply.stderr[-8000:]}
 if supply.returncode!=0:blockers.append('SUPPLY_CHAIN_LOCK')
 if runtime.get('status')!='VERIFICADO' or runtime.get('ready_for_operation') is not True:blockers.append('RUNTIME_RESOURCE_GATE')
 if freshness.get('ready_for_dna') is not True:blockers.append('FRESHNESS_GATE')
 if consent.get('status')!='VERIFICADO' or consent.get('ready_for_first_dna_read') is not True:blockers.append('CONSENT_PROVENANCE_GATE')
 return {'schema':'genoma-pre-analysis-master-gate-v2','gate':'PRE_ANALYSIS_MASTER_GATE','status':'VERIFICADO' if not blockers else 'NÃO DISPONÍVEL','ready_for_first_dna_read':not blockers,'blockers':blockers,'evidence':evidence}
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--runtime-verified',required=True);p.add_argument('--freshness',required=True);p.add_argument('--consent',required=True);p.add_argument('--output',required=True);a=p.parse_args();r=evaluate(load(a.runtime_verified),load(a.freshness),load(a.consent));o=Path(a.output);o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps(r,ensure_ascii=False,indent=2,sort_keys=True));return 0 if r['ready_for_first_dna_read'] else 2
if __name__=='__main__':raise SystemExit(main())
