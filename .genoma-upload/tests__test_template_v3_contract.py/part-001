import os
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TemplateV3ContractTest(unittest.TestCase):
    def test_manifest_is_complete_for_all_eleven_reference_models(self):
        from reporting.template_v3 import load_reference_manifest
        m = load_reference_manifest()
        self.assertEqual(set(m['reports']), {f'{i:02d}' for i in range(1,12)})
        expected_pages={'01':10,'02':10,'03':10,'04':10,'05':11,'06':9,'07':9,'08':9,'09':9,'10':1,'11':12}
        self.assertEqual({rid:int(x['page_count']) for rid,x in m['reports'].items()}, expected_pages)
        for rid, meta in m['reports'].items():
            self.assertRegex(meta['sha256'], r'^[0-9a-f]{64}$')
            self.assertGreater(len(meta.get('fields', [])), 0)

    def test_missing_or_wrong_template_pack_fails_closed(self):
        from reporting.template_v3 import TemplateV3Error, verify_template_pack
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(TemplateV3Error):
                verify_template_pack(Path(td))

    @unittest.skipUnless(os.environ.get('GENOMA_REPORT_TEMPLATE_DIR'), 'external v3 template pack not mounted')
    def test_external_template_pack_verifies_and_report10_strict_docx_is_editable(self):
        from reporting.engine import render_document
        from reporting.template_v3 import load_reference_manifest, render_docx_from_template, render_pdf_from_template, verify_template_pack
        template_dir=Path(os.environ['GENOMA_REPORT_TEMPLATE_DIR'])
        verification=verify_template_pack(template_dir)
        self.assertEqual(verification['verified_reports'],11)
        manifest=load_reference_manifest(); meta=manifest['reports']['10']
        fields={item['field_id']:'NÃO DISP.' for item in meta['fields'] if not item.get('guidance_only')}
        data={
            'case_id':'CASE-TEMPLATE-10',
            'summary':'fixture',
            'ruleset':{'status':'VIGENTE','version':'v3.3','effective_date':'14/08/2026'},
            'publication_gate':{'passed':True,'consent_verified':True,'qc_verified':True,'evidence_verified':True,'placeholders_resolved':True},
            'policy_evaluation':{'ready_for_requested_operation':True,'planes':{'policy_control':{'state':'PASS'},'scientific_data':{'state':'PASS'},'evidence':{'state':'PASS'},'audit':{'state':'PASS'}},'gates':[{'gate':'FINAL_AUDIT_GATE','state':'PASS','blocking':True}]},
            'post_deployment_status':'PASS','sections':{},'findings':[],'execution_manifest':{'status':'VERIFICADO'},'sources':['fixture'],'limitations':'fixture',
            'editorial_mode':'template-v3','template_fields_complete':True,'template_fields':fields,
        }
        rendered=render_document('10',data,mode='FINAL')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); pdf=root/'10.pdf'; docx=root/'10.docx'
            pr=render_pdf_from_template(rendered,pdf,template_dir,strict=True)
            dr=render_docx_from_template(rendered,docx,template_dir,strict=True)
            self.assertEqual(pr['page_count'],1); self.assertEqual(pr['unresolved_fields'],[])
            self.assertEqual(dr['unresolved_fields'],[]); self.assertTrue(dr['editable_dynamic_fields'])
            with zipfile.ZipFile(docx) as zf:
                xml=zf.read('word/document.xml').decode('utf-8')
                self.assertIn('GENOMA_FIELD_', xml)
                self.assertIn('svgBlip', xml)


if __name__ == '__main__':
    unittest.main()
