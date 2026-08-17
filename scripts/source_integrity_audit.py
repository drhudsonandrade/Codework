#!/usr/bin/env python3
from __future__ import annotations
import argparse, ast, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.sealed_ruleset import decode_verified_payload
SKIP_PARTS={'.git','node_modules','dist','__pycache__','.pytest_cache','.mypy_cache'}
CODE_SUFFIXES={'.py','.ts','.js','.mjs','.cjs','.sh','.bash','.nf'}
PROVIDER_TERMS=(('chat'+'gpt').lower(),('open'+'ai').lower())
RISK_PATTERNS={'python_eval':re.compile(r'\beval\s*\('),'python_exec':re.compile(r'\bexec\s*\('),'os_system':re.compile(r'\bos\.system\s*\('),'subprocess_shell_true':re.compile(r'\bshell\s*=\s*True\b'),'pickle_loads':re.compile(r'\bpickle\.loads?\s*\('),'unsafe_yaml_load':re.compile(r'\byaml\.load\s*\(')}
ACTION_REF=re.compile(r'^\s*-?\s*uses:\s*([^\s#]+)'); PINNED_ACTION=re.compile(r'^[^@\s]+@[0-9a-f]{40}$')
SEALED_DIR=ROOT/'normative'/'sealed'/'v3.4'
def sha256_bytes(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def hits(text:str,path:str)->list[dict]:
 out=[]
 for term in PROVIDER_TERMS:
  for n,line in enumerate(text.splitlines(),1):
   if term in line.lower(): out.append({'path':path,'line':n})
 return out
def pdf_text(path:Path)->str:
 from pypdf import PdfReader
 return '\n'.join((p.extract_text() or '') for p in PdfReader(str(path)).pages)
def audit(root:Path=ROOT)->dict:
 files=text_files=binary_files=text_lines=0; provider_hits=[]; risky=[]; parse_errors=[]; unpinned=[]; hashes=[]; binary_errors=[]
 for path in sorted(root.rglob('*')):
  if not path.is_file() or any(x in SKIP_PARTS for x in path.parts): continue
  rel=str(path.relative_to(root)); data=path.read_bytes(); files+=1; hashes.append({'path':rel,'sha256':sha256_bytes(data),'size_bytes':len(data)})
  try:text=data.decode('utf-8')
  except UnicodeDecodeError:
   binary_files+=1
   if path.suffix.lower()=='.pdf':
    try: provider_hits.extend(hits(pdf_text(path),rel+'::pdf-text'))
    except Exception as exc: binary_errors.append({'path':rel,'error':f'{type(exc).__name__}: {exc}'})
   continue
  text_files+=1; lines=text.splitlines(); text_lines+=len(lines); provider_hits.extend(hits(text,rel))
  if path.suffix in CODE_SUFFIXES:
   for name,pat in RISK_PATTERNS.items():
    for n,line in enumerate(lines,1):
     if pat.search(line): risky.append({'path':rel,'line':n,'pattern':name})
  if path.suffix=='.py':
   try: ast.parse(text,filename=rel)
   except SyntaxError as exc: parse_errors.append({'path':rel,'line':exc.lineno,'error':exc.msg})
  if rel.startswith('.github/workflows/') and path.suffix in {'.yml','.yaml'}:
   for n,line in enumerate(lines,1):
    m=ACTION_REF.match(line)
    if m and not m.group(1).startswith('./') and not PINNED_ACTION.fullmatch(m.group(1)): unpinned.append({'path':rel,'line':n,'ref':m.group(1)})
 try:
  raw,evidence=decode_verified_payload(SEALED_DIR); provider_hits.extend(hits(raw.decode('utf-8'),'normative/sealed/v3.4::decoded-canonical')); decoded={'status':'VERIFICADO','sha256':evidence['raw_sha256'],'section_count':evidence['section_count']}
 except Exception as exc:
  decoded={'status':'NÃO DISPONÍVEL','error':f'{type(exc).__name__}: {exc}'}; binary_errors.append({'path':'normative/sealed/v3.4','error':decoded['error']})
 blocking=[]
 if provider_hits:blocking.append('PROVIDER_NEUTRALITY')
 if risky:blocking.append('DANGEROUS_CODE_PATTERN')
 if parse_errors:blocking.append('PYTHON_PARSE')
 if unpinned:blocking.append('ACTION_IMMUTABILITY')
 if binary_errors:blocking.append('BINARY_CONTENT_AUDIT')
 return {'schema':'genoma-source-integrity-audit-v2','created_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'operational_status':'VERIFICADO' if not blocking else 'NÃO DISPONÍVEL','root':str(root),'counts':{'files':files,'text_files':text_files,'binary_files':binary_files,'text_lines':text_lines},'decoded_ruleset':decoded,'provider_hits':provider_hits,'risky_code_hits':risky,'python_parse_errors':parse_errors,'unpinned_actions':unpinned,'binary_audit_errors':binary_errors,'blocking_failures':blocking,'file_hashes':hashes}
def main()->int:
 p=argparse.ArgumentParser(); p.add_argument('--output'); a=p.parse_args(); r=audit(); payload=json.dumps(r,ensure_ascii=False,indent=2,sort_keys=True)+'\n'
 if a.output:Path(a.output).write_text(payload,encoding='utf-8')
 print(payload,end=''); return 0 if r['operational_status']=='VERIFICADO' else 2
if __name__=='__main__':raise SystemExit(main())
