from __future__ import annotations

from pathlib import Path

PATH = Path("tests/test_pharmacogenomics.py")
text = PATH.read_text(encoding="utf-8")

old_payload = '''        payload = build_payload(\n            passport_path, matrix_path, policy_evaluation_file(root),\n            consent=consent_for(root, matrix_path),\n        )\n'''
new_payload = '''        from tests.test_policy_evaluation_binding import real_evaluation\n\n        matrix_payload = json.loads(matrix_path.read_text(encoding="utf-8"))\n        policy = policy_evaluation_file(\n            root,\n            real_evaluation(\n                case_id=str(matrix_payload["case_id"]),\n                input_sha256=str(matrix_payload["input_sha256"]),\n            ),\n        )\n        payload = build_payload(\n            passport_path, matrix_path, policy,\n            consent=consent_for(root, matrix_path),\n        )\n'''

old_assertion = '''        self.assertEqual(\n            payload["policy_evaluation"]["source"]["origin"], "policy-engine-output"\n        )\n'''
new_assertion = '''        self.assertEqual(\n            payload["policy_evaluation"]["source"]["status"], "NÃO DISPONÍVEL"\n        )\n        self.assertNotIn("origin", payload["policy_evaluation"]["source"])\n        self.assertIn("schema", payload["policy_evaluation"]["source"]["reason"])\n'''

old_doc = '''        """The CLI forwards the control artifacts unchanged and exits non-zero when release is blocked."""\n'''
new_doc = '''        """The CLI binds the exact control artifacts and exits non-zero when release is blocked."""\n'''

for label, old in (("payload fixture", old_payload), ("CLI assertion", old_assertion), ("CLI docstring", old_doc)):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one {label} occurrence, found {count}")

text = text.replace(old_payload, new_payload, 1)
text = text.replace(old_assertion, new_assertion, 1)
text = text.replace(old_doc, new_doc, 1)
PATH.write_text(text, encoding="utf-8")
print("Applied PR30 final CI fixture repair")
