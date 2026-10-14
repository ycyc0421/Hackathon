"""Unaligned rows must survive public projection without becoming ticket fields."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.frontend_view import to_frontend_task


class EvidenceTests(unittest.TestCase):
    def test_unaligned_row_retains_line_and_null_owner(self):
        task = {'items': [], 'extractions': [{'file_id': 'f1', 'fields': [
            {'field_key': 'quantity', 'normalized_value': 30}], 'line_items': [
            {'item_no': 2, 'fields': [{'field_key': 'quantity', 'raw_text': 'SKU-A 10 PCS',
             'raw_value': '10 PCS', 'normalized_value': 10, 'page': 1}]}]}],
            'summary': {'field_count': 1}}
        original = copy.deepcopy(task)
        public = to_frontend_task(task)
        self.assertEqual(task, original)
        fields = public['extractions'][0]['fields']
        self.assertEqual(len(fields), 2)
        self.assertIsNone(fields[1]['item_id'])
        self.assertEqual(fields[1]['line_no'], 2)
        self.assertEqual(fields[1]['raw_text'], 'SKU-A 10 PCS')
        self.assertEqual(fields[1]['page'], 1)
        self.assertEqual(public['summary']['field_count'], 2)
        self.assertNotIn('line_no', fields[0])


if __name__ == '__main__':
    unittest.main()
