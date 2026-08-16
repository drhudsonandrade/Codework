import json
import tempfile
import unittest
from pathlib import Path

from scripts.runtime_stack import MANAGED_RUNTIME_PACKAGES


class PromotionGateTest(unittest.TestCase):
    def _write(self, path: Path, payload):
        path.write_text(json.dumps(payload), encoding='utf-8')
        return path

    def _inventory(self):
        return [{'name': name, 'version': '1.0'} for name in MANAGED_RUNTIME_PACKAGES]

    def test_promotion_requires_functional_and_orchestration_canaries(self):
        from scripts.promote_latest_candidate import promote
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            functional = self._write(root/'functional.json', {
                'status': 'PASS',
                'editorial_runtime': {'status': 'PASS'},
            })
            orchestration = self._write(root/'orchestration.json', {'status': 'PASS'})
            inventory = self._write(root/'inventory.json', self._inventory())
            state = promote(functional, orchestration, inventory)
            self.assertEqual(state['candidate_canaries']['functional']['status'], 'PASS')
            self.assertEqual(state['candidate_canaries']['orchestration']['status'], 'PASS')
            self.assertTrue(all(x['promotion_status'] == 'VERIFICADO' for x in state['components']))

    def test_promotion_refuses_failed_orchestration_canary(self):
        from scripts.promote_latest_candidate import promote
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            functional=self._write(root/'functional.json', {'status':'PASS','editorial_runtime':{'status':'PASS'}})
            orchestration=self._write(root/'orchestration.json', {'status':'FAIL'})
            inventory=self._write(root/'inventory.json', self._inventory())
            with self.assertRaisesRegex(RuntimeError, 'orchestration canary'):
                promote(functional, orchestration, inventory)

    def test_promotion_refuses_functional_canary_without_editorial_runtime_pass(self):
        from scripts.promote_latest_candidate import promote
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            functional=self._write(root/'functional.json', {'status':'PASS'})
            orchestration=self._write(root/'orchestration.json', {'status':'PASS'})
            inventory=self._write(root/'inventory.json', self._inventory())
            with self.assertRaisesRegex(RuntimeError, 'editorial runtime'):
                promote(functional, orchestration, inventory)


if __name__ == '__main__':
    unittest.main()
