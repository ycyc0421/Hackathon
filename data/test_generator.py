"""Independent literal golden assertions and output regression checks."""
import json
import unittest
from pathlib import Path
from generator import build_cases, expected_comparison, field, write_cases


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.cases = {c['case_id']: c for c in build_cases(42)}

    def status(self, case, identity, key):
        return next(c for c in self.cases[case]['expected']['comparisons']
                    if c['item_id'] == identity and c['field_key'] == key)

    def test_literal_golden(self):
        # These expectations are hand-written, not computed by the oracle.
        golden = [
            ('normal_multi', 'item_001', 'quantity', 'MATCH'),
            ('one_item_conflict_multi', 'item_001', 'quantity', 'CONFLICT'),
            ('one_item_conflict_multi', 'item_002', 'quantity', 'MATCH'),
            ('different_order_multi', 'item_002', 'gross_weight', 'MATCH'),
            ('missing_hs_single', 'item_001', 'hs_code', 'MISSING_IN_SOME'),
            ('all_missing_single', 'item_001', 'hs_code', 'MISSING_IN_SOME'),
            ('unrecognized_single', 'item_001', 'description', 'UNRECOGNIZED'),
            ('partial_unrecognized_single', 'item_001', 'description', 'NOT_CHECKED'),
            ('low_confidence_single', 'item_001', 'description', 'MATCH'),
            ('bill_weight_conflict', None, 'gross_weight', 'CONFLICT'),
        ]
        for name, identity, key, expected in golden:
            with self.subTest(case=name, key=key):
                self.assertEqual(self.status(name, identity, key)['status'], expected)
        self.assertIn('All applicable', self.status('all_missing_single', 'item_001', 'hs_code')['note'])
        self.assertIn('UNRECOGNIZED', self.status('partial_unrecognized_single', 'item_001', 'description')['note'])
        for name in ('low_confidence_single', 'partial_unrecognized_single', 'all_missing_single'):
            self.assertTrue(self.cases[name]['expected']['risks'])

    def test_numeric_equality_and_boolean_distinction(self):
        def compare(a, b):
            docs = [dict(file_id=str(i), fields=[field('gross_weight', v, 'KGS')])
                    for i, v in enumerate((a, b))]
            return expected_comparison(docs)[0]['status']
        self.assertEqual(compare(2400, 2400.0), 'MATCH')
        self.assertEqual(compare(True, 1), 'CONFLICT')
        self.assertEqual(compare(2400, 2401), 'CONFLICT')

    def test_row_scope_and_not_applicable(self):
        for case in self.cases.values():
            for doc in case['documents']:
                rows = {}
                for f in doc['fields']:
                    if f['item_id'] is not None:
                        rows.setdefault(f['item_id'], set()).add(f['line_no'])
                    else:
                        self.assertIsNone(f['line_no'])
                self.assertTrue(all(len(nums) == 1 for nums in rows.values()))
        normal = self.cases['normal_single']
        bill = normal['documents'][2]
        self.assertTrue(all(f['status'] == 'NOT_IN_DOC' for f in bill['fields']
                            if f['field_key'] in {'quantity', 'hs_code'}))
        self.assertFalse(normal['expected']['risks'])

    def test_bytes_determinism_and_preservation(self):
        root = Path('data/.test_generator_output')
        root.mkdir(parents=True, exist_ok=True)
        for old in root.glob('*.json'):
            old.unlink()
        extra = root / 'user.json'
        extra.write_bytes(b'{"keep":true}')
        write_cases(root, 42)
        before = {p.name: p.read_bytes() for p in root.glob('*.json')}
        write_cases(root, 42)
        self.assertEqual(before, {p.name: p.read_bytes() for p in root.glob('*.json')})
        self.assertEqual(extra.read_bytes(), b'{"keep":true}')
        for name, raw in before.items():
            if name != 'user.json':
                self.assertNotIn(b'\r\n', raw)
        write_cases(root, 43)
        self.assertNotEqual(before['normal_multi.json'], (root/'normal_multi.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
