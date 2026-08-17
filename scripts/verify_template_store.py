#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,shutil,tempfile,zipfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]; STORE=ROOT/'template_store'/'v3.1'; MANIFEST=STORE/'MANIFEST.json'; MATERIALIZED=STORE/'materialized'; INBOX_ZIP=STORE/'inbox'/'GENOMA_REPORT_TEMPLATES_v3.1_DETERMINISTIC.zip'
EXPECTED_ZIP_SHA='9ea777466fd9f8823c67f862e73d11bca5bf13c58765da4ef4d9bd4d08bb7776'; FORBIDDEN=(('chat'+'gpt').lower(),('open'+'ai').lower())
def sha256_bytes(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def pdf_text(data:bytes)->str:
 from io import BytesIO
 from pypdf import PdfReader
 return '\n'.join((p.extract_text() or '') for p in PdfReader(BytesIO(data)).pages)
def verify_pdf(rid:str,spec:dict,data:bytes)->None:
 if not data.startswith(b'%PDF-'):raise ValueError(f'report {rid} is not a PDF')
 if len(data)!=spec['size_bytes'] or sha256_bytes(data)!=spec['sha256']:raise ValueError(f'report {rid} byte identity mismatch')
 if any(t in pdf_text(data).lower() for t in FORBIDDEN):raise ValueError(f'report {rid} contains forbidden provider-specific text')
def verify_materialized(reports:dict)->tuple[bool,list[str]]:
 missing=[]
 for rid,spec in reports.items():
  p=MATERIALIZED/spec['filename']
  if not p.is_file():missing.append(spec['filename']);continue
  verify_pdf(rid,spec,p.read_bytes())
 return not missing,missing
def verify_zip(reports:dict)->dict[str,bytes]:
 data=INBOX_ZIP.read_bytes()
 if sha256_bytes(data)!=EXPECTED_ZIP_SHA:raise ValueError('v3.1 transport ZIP SHA-256 mismatch')
 expected={s['filename'] for s in reports.values()}; extracted={}
 with zipfile.ZipFile(INBOX_ZIP) as z:
  infos=[i for i in z.infolist() if not i.is_dir()]
  if len(infos)!=11 or {i.filename for i in infos}!=expected:raise ValueError('v3.1 ZIP member set mismatch')
  for i in infos:
   p=PurePosixPath(i.filename)
   if p.is_absolute() or '..' in p.parts or len(p.parts)!=1:raise ValueError('unsafe ZIP path')
  for rid,spec in reports.items():
   blob=z.read(spec['filename']);verify_pdf(rid,spec,blob);extracted[spec['filename']]=blob
 return extracted
def verify(*,materialize:bool=False)->dict:
 m=json.loads(MANIFEST.read_text(encoding='utf-8')); reports=m.get('reports',{}); rs=m.get('ruleset',{})
 if set(reports)!={f'{i:02d}' for i in range(1,12)}:raise ValueError('template store must define exactly reports 01..11')
 if m.get('template_version')!='v3.1' or rs.get('version')!='v3.4' or rs.get('formal_date')!='17/08/2026':raise ValueError('template/ruleset compatibility mismatch')
 ready,missing=verify_materialized(reports);source='materialized';runtime_extractable=False
 if not ready:
  if not INBOX_ZIP.is_file():return {'schema':'genoma-template-store-verification-v3','operational_status':'NÃO DISPONÍVEL','reports':11,'missing_binaries':missing,'required_transport':str(INBOX_ZIP),'required_transport_sha256':EXPECTED_ZIP_SHA}
  extracted=verify_zip(reports);ready=True;missing=[];runtime_extractable=True;source='verified-immutable-runtime-extractable-zip'
  if materialize:
   with tempfile.TemporaryDirectory() as td:
    staging=Path(td)/'materialized';staging.mkdir()
    for name,blob in extracted.items():(staging/name).write_bytes(blob)
    if MATERIALIZED.exists():shutil.rmtree(MATERIALIZED)
    shutil.copytree(staging,MATERIALIZED)
   ready,missing=verify_materialized(reports);runtime_extractable=False;source='materialized-from-verified-zip'
 return {'schema':'genoma-template-store-verification-v3','operational_status':'VERIFICADO' if ready else 'NÃO DISPONÍVEL','binary_source':'RUNTIME_EXTRACTABLE' if runtime_extractable else 'MATERIALIZED','reports':11,'source':source,'missing_binaries':missing,'zip_sha256':EXPECTED_ZIP_SHA if runtime_extractable else None}
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--materialize',action='store_true');a=p.parse_args()
 try:r=verify(materialize=a.materialize)
 except Exception as exc:print(f'NÃO DISPONÍVEL: {type(exc).__name__}: {exc}');return 2
 print(json.dumps(r,ensure_ascii=False,indent=2,sort_keys=True));return 0 if r['operational_status']=='VERIFICADO' else 2
if __name__=='__main__':raise SystemExit(main())
