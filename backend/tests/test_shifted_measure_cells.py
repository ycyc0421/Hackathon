"""Explicit unit ownership across adjacent model cells; no model or file mocks."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline.paddle_vl_reader import adapt_output, locate_fields
from app.pipeline.rows import parse_line_items

HEADER = ['NO.', 'ITEM NO.', 'DESCRIPTION', 'QTY', 'PACKAGES', 'G.W.']
def result(cells, headers=HEADER):
    grid = '<table>' + ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>'
                              for row in [headers, ['1', 'SKU-815', 'CERAMIC PLATE', *cells]]) + '</table>'
    output = {'res': {'parsing_res_list': [
        {'block_label': 'text', 'block_content': 'PACKING LIST\nDocument No.: PL-815\nTOTAL PACKAGES: 17 CTNS\nTOTAL G.W.: 93.25 KGS', 'block_bbox': [0, 0, 200, 100]},
        {'block_label': 'table', 'block_content': grid, 'block_bbox': [0, 100, 300, 250]}]}}
    before = copy.deepcopy(output)
    adapted = adapt_output(output)
    assert adapted.ok, adapted.error_message
    parsed = parse_line_items(adapted.text, page=1)
    assert output == before and adapted.model_outputs == [before]
    locate_fields([], parsed.line_items, adapted.source_blocks)
    return parsed, {f['field_key']: f for f in parsed.line_items[0]['fields']}, before

class ShiftedMeasureTests(unittest.TestCase):
    def test_complete_unit_chain_restores_values_and_source(self):
        parsed, fields, original = result(['735', 'PCS 17', 'CTNS 93.25'])
        self.assertFalse(parsed.suspected)
        for key, value, unit, raw in [('quantity',735,'PCS','735 PCS'),
                                     ('packages',17,'CARTON','17 CTNS'),
                                     ('gross_weight',93.25,'KGS','93.25')]:
            field = fields[key]
            self.assertEqual((field['normalized_value'], field['unit'], field['status']), (value,unit,'EXTRACTED'))
            self.assertEqual(field['raw_value'], raw)
            self.assertIn('PCS 17   CTNS 93.25', field['raw_text'])
            self.assertEqual((field['page'],field['bbox'],field['bbox_unit']), (1,[0.,100.,300.,150.],'PX'))
        self.assertIn('<td>735</td><td>PCS 17</td><td>CTNS 93.25</td>', original['res']['parsing_res_list'][1]['block_content'])

    def test_existing_unit_aliases_and_numbers_keep_their_meaning(self):
        for cells, values, carton in [
            (['1,735','pieces 27','cartons 193.25'],[1735,27,193.25],'CARTON'),
            (['835','UNIT 37','CTN 293,25'],[835,37,293.25],'CARTON'),
            (['935','个 47','箱 393.25'],[935,47,393.25],'CARTON'),
        ]:
            with self.subTest(cells=cells):
                _, fields, _ = result(cells)
                self.assertEqual([fields[k]['normalized_value'] for k in ('quantity','packages','gross_weight')],values)
                self.assertEqual(fields['packages']['unit'],carton)

    def test_valid_and_untyped_cells_stay_unchanged(self):
        for cells, carton in [(['735 PCS','17 CTNS','93.25'],'CARTON'),
                              (['735','17','93.25'],None),
                              (['735 PCS','17 PKGS','93.25'],None)]:
            with self.subTest(cells=cells):
                _, fields, _ = result(cells)
                self.assertEqual([fields[k]['raw_value'] for k in ('quantity','packages','gross_weight')],cells)
                self.assertEqual(fields['packages']['unit'],carton)

    def test_incomplete_unknown_or_extra_tokens_are_not_repaired(self):
        for cells in [
            ['735 PCS','PCS 17','CTNS 93.25'],
            ['735','SETS 17','CTNS 93.25'],
            ['735','PCS 17','PALLETS 93.25'],
            ['735','PCS 17 extra','CTNS 93.25'],
            ['735','PCS 17','CTNS 93.25 KGS'],
            ['735','PCS 17','CTNS 93.25 50'],
            ['735','PCS 17','93.25'],
            ['735','\ue000','CTNS 93.25'],
            ['735','PCS 17','\ue000'],
            ['735','PCS 1,2,3','CTNS 93.25'],
        ]:
            with self.subTest(cells=cells):
                _, fields, _ = result(cells)
                self.assertTrue(any(fields[k]['status'] in ('NORMALIZE_FAILED','MISSING_IN_DOC') for k in ('packages','gross_weight')))
                for key, original in zip(('quantity','packages','gross_weight'), cells):
                    self.assertEqual(fields[key]['raw_value'],None if original=='\ue000' else original)

    def test_different_header_order_does_not_move_units(self):
        _, fields, _ = result(['735','PCS 17','CTNS 93.25'], HEADER[:-2] + ['G.W.','PACKAGES'])
        self.assertEqual(fields['gross_weight']['raw_value'],'PCS 17')
        self.assertEqual(fields['packages']['raw_value'],'CTNS 93.25')
        self.assertEqual(fields['gross_weight']['status'],'NORMALIZE_FAILED')

if __name__ == '__main__': unittest.main()
