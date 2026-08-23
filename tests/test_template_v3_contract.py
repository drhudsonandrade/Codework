import os
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULESET = {
    'status': 'VIGENTE',
    'version': 'v3.4',
    'effective_date': '17/08/2026',
    'sha256': 'ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580',
}


class TemplateV3ContractTest(unittest.TestCase):
    def test_manifest_is_complete_for_all_eleven_reference_models(self):
        from reporting.template_v3 import load_reference_manifest
        m = load_reference_manifest()
        self.assertEqual(set(m['reports']), {f'{i:02d}' for i in range(1,12)})
        expected_pages={'01':10,'02':10,'03':10,'04':10,'05':11,'06':9,'07':9,'08':9,'09':9,'10':1,'11':12}
        self.assertEqual({rid:int(x['page_count']) for rid,x in m['reports'].items()}, expected_pages)
        for meta in m['reports'].values():
            self.assertRegex(meta['sha256'], r'^[0-9a-f]{64}$')
        self.assertRegex(m['external_coordinate_manifest']['sha256'], r'^[0-9a-f]{64}$')
        self.assertRegex(m['external_coordinate_detail']['sha256'], r'^[0-9a-f]{64}$')

    def test_missing_or_wrong_template_pack_fails_closed(self):
        from reporting.template_v3 import TemplateV3Error, verify_template_pack
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(TemplateV3Error):
                verify_template_pack(Path(td))

    def test_historical_template_ruleset_labels_are_generically_migrated_to_current_identity(self):
        from reporting.template_v3 import CURRENT_RULESET_TEMPLATE_LABEL, _system_value_for_source

        self.assertEqual(CURRENT_RULESET_TEMPLATE_LABEL, 'GENOMA--RULESET-v3.4')
        systems = {'OTHER': 'value'}
        self.assertEqual(
            _system_value_for_source('GENOMA-HUDSON-RULESET-v2.8', systems),
            CURRENT_RULESET_TEMPLATE_LABEL,
        )
        self.assertEqual(_system_value_for_source('OTHER', systems), 'value')
        self.assertIsNone(_system_value_for_source('UNKNOWN', systems))

    @unittest.skipUnless(os.environ.get('GENOMA_REPORT_TEMPLATE_DIR'), 'external v3 template pack not mounted')
    def test_external_template_pack_verifies_and_report10_strict_docx_is_editable(self):
        from reporting.engine import render_document
        from reporting.editorial_v3 import write_editorial_bundle
        from reporting.template_v3 import load_reference_manifest, verify_template_pack
        template_dir=Path(os.environ['GENOMA_REPORT_TEMPLATE_DIR'])
        verification=verify_template_pack(template_dir)
        self.assertEqual(verification['verified_reports'],11)
        detailed=load_reference_manifest(template_dir/'GENOMA_V3_TEMPLATE_MANIFEST.json')
        meta=detailed['reports']['10']
        fields={item['field_id']:'NÃO DISP.' for item in meta['fields'] if not item.get('guidance_only')}
        data={
            'case_id':'CASE-TEMPLATE-10',
            'summary':'fixture',
            'ruleset':dict(RULESET),
            'publication_gate':{'passed':True,'consent_verified':True,'qc_verified':True,'evidence_verified':True,'placeholders_resolved':True},
            'policy_evaluation':{'ready_for_requested_operation':True,'planes':{'policy_control':{'state':'PASS'},'scientific_data':{'state':'PASS'},'evidence':{'state':'PASS'},'audit':{'state':'PASS'}},'gates':[{'gate':'FINAL_AUDIT_GATE','state':'PASS','blocking':True}]},
            'post_deployment_status':'PENDENTE','sections':{},'findings':[],'execution_manifest':{'status':'VERIFICADO'},'sources':['fixture'],'limitations':'fixture',
            'editorial_mode':'template-v3','template_fields_complete':True,'template_fields':fields,
        }
        rendered=render_document('10',data,mode='FINAL')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            paths=write_editorial_bundle(rendered, root, stem='10')
            self.assertTrue(paths['pdf'].is_file()); self.assertTrue(paths['docx'].is_file())
            with zipfile.ZipFile(paths['docx']) as zf:
                xml=zf.read('word/document.xml').decode('utf-8')
                self.assertIn('GENOMA_FIELD_', xml)
                self.assertIn('svgBlip', xml)


if __name__ == '__main__':
    unittest.main()
