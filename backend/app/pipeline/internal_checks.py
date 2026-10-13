"""Document arithmetic checks, separate from cross-document comparisons."""
from decimal import Decimal


def check_rows(extractions: list[dict]) -> list[dict]:
    warnings = []
    for extraction in extractions:
        for row in extraction.get('line_items', []):
            fields = {field['field_key']: field for field in row['fields']}
            def number(key):
                field = fields.get(key, {})
                value = field.get('normalized_value')
                return (Decimal(str(value)) if isinstance(value, (int, float))
                        and field.get('status') in {'EXTRACTED', 'LOW_CONFIDENCE'} else None)
            net, gross = number('net_weight'), number('gross_weight')
            qty, price, amount = number('quantity'), number('unit_price'), number('amount')
            findings = []
            if net is not None and gross is not None and gross < net:
                findings.append(('GROSS_BELOW_NET', f'毛重 {gross} 小于净重 {net}。'))
            if qty is not None and price is not None and amount is not None:
                price_unit = fields['unit_price'].get('unit')
                amount_unit = fields['amount'].get('unit')
                if price_unit and price_unit == amount_unit and abs(qty * price - amount) > Decimal('0.01'):
                    findings.append(('LINE_AMOUNT_MISMATCH',
                                     f'数量 {qty} × 单价 {price} = {qty * price}，与行金额 {amount} 不一致（{amount_unit}）。'))
            for code, detail in findings:
                warnings.append({'code': code, 'level': 'WARNING',
                                 'file_ids': [extraction['file_id']],
                                 'message': f"文件 {extraction['file_id']} 第 {row['item_no']} 行：{detail} 请核对原件及折扣、费用约定。"})
    return warnings
