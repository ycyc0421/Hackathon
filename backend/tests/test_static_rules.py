import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline import rules
from tools.crawl_rule_sources import OfficialRedirectHandler, fetch_source


class StaticRulesTests(unittest.TestCase):
    def support_case(self, country="US", hs="69111000"):
        return (
            {"destination_country": country},
            [{"file_id": "f1", "file_name": "invoice.pdf", "doc_type": "COMMERCIAL_INVOICE", "process_status": "EXTRACTED"}],
            [{"file_id": "f1", "fields": [{"field_key": "hs_code", "status": "EXTRACTED", "normalized_value": hs}]}],
        )

    def test_broad_demo_rules_inactive(self):
        for country in ("DE", "NL", "FR", "GB", "US"):
            self.assertEqual(rules.country_rules(country)["required_documents"], [])
            self.assertIsNone(rules.match_hs_rule(country, "69010000"))
            self.assertIsNone(rules.match_hs_rule(country, "85010000"))
            self.assertEqual(rules.match_hs_rule(country, "69111000")["review_status"], "APPLICABILITY_REVIEW_REQUIRED")
            self.assertEqual(rules.match_certificate_rules(country, "69111000")[0]["review_status"], "APPLICABILITY_REVIEW_REQUIRED")
        self.assertFalse(rules.ruleset_verified())

    def test_source_in_risk_and_certificate_prompt(self):
        risks=rules.evaluate_risks({"destination_country":"US"}, [{"file_id":"f1","file_name":"x","doc_type":"COMMERCIAL_INVOICE","process_status":"EXTRACTED"}], [{"file_id":"f1","fields":[{"field_key":"hs_code","status":"EXTRACTED","normalized_value":"69111000"}]}])
        self.assertEqual([risk["type"] for risk in risks],["OTHER","HS_CLASSIFICATION"])
        self.assertIn("www.fda.gov",risks[0]["rule_source"])
        self.assertIn("未经核实",risks[0]["title"])
        self.assertEqual(risks[0]["rule_id"],"US-CERAMICS-6911-SUPPORT-DOCS")

    def test_unparsed_file_prevents_missing_certificate_conclusion(self):
        risks=rules.evaluate_risks({"destination_country":"DE"}, [
            {"file_id":"f1","file_name":"invoice.pdf","doc_type":"COMMERCIAL_INVOICE","process_status":"EXTRACTED"},
            {"file_id":"f2","file_name":"support.pdf","doc_type":None,"process_status":"FAILED"},
        ], [{"file_id":"f1","fields":[{"field_key":"hs_code","status":"EXTRACTED","normalized_value":"69120000"}]}])
        self.assertEqual(risks[0]["type"],"OTHER")
        self.assertEqual(risks[0]["rule_id"],"DE-CERAMICS-6912-SUPPORT-DOCS")
        self.assertIn("无法确认",risks[0]["title"])
        self.assertEqual(risks[1]["type"],"HS_CLASSIFICATION")

    def test_crawler_rejects_untrusted_sources_and_redirects(self):
        with self.assertRaises(ValueError):
            fetch_source({"source_id":"x","url":"https://example.com"},Path("unused"))
        with self.assertRaises(ValueError):
            OfficialRedirectHandler().redirect_request(None,None,302,"",{},"http://www.fda.gov/x")

    def test_support_documents_require_review_without_missing_conclusion(self):
        for country in ("DE", "NL", "FR", "GB", "US"):
            for hs in ("69111000", "69120000"):
                for with_support in (False, True):
                    with self.subTest(country=country, hs=hs, with_support=with_support):
                        task_input, documents, extractions = self.support_case(country, hs)
                        if with_support:
                            documents.append({"file_id": "f2", "file_name": "测试报告.pdf", "doc_type": "OTHER", "process_status": "EXTRACTED"})
                        risk = rules.evaluate_risks(task_input, documents, extractions)[0]
                        self.assertEqual(risk["type"], "OTHER")
                        self.assertIn("待人工核对", risk["title"])
                        self.assertIn("尚不支持自动确认", risk["detail"])
                        self.assertNotIn("可能缺少", risk["title"])
                        self.assertNotIn("未在已解析文件中识别到", risk["detail"])
                        self.assertNotIn("???", risk["title"] + risk["detail"])

    def test_all_non_extracted_files_keep_uncertainty_and_source(self):
        for status in ("FAILED", "UNSUPPORTED", "UPLOADED", "PARSING"):
            with self.subTest(status=status):
                task_input, documents, extractions = self.support_case()
                documents.append({"file_id": "f2", "file_name": "support.pdf", "doc_type": "OTHER", "process_status": status})
                risk = rules.evaluate_risks(task_input, documents, extractions)[0]
                self.assertEqual(risk["type"], "OTHER")
                self.assertIn("无法确认", risk["title"])
                self.assertEqual(risk["rule_id"], "US-CERAMICS-6911-SUPPORT-DOCS")
                self.assertIn("www.fda.gov", risk["rule_source"])
                self.assertEqual(set(risk["related_file_ids"]), {"f1", "f2"})

    def test_repeated_evidence_is_deduplicated_without_losing_files(self):
        task_input, documents, extractions = self.support_case()
        documents.append({**documents[0], "file_id": "f2", "file_name": "packing.pdf"})
        extractions.append({**deepcopy(extractions[0]), "file_id": "f2"})
        risks = rules.evaluate_risks(task_input, documents, extractions)
        support = [risk for risk in risks if risk.get("rule_id", "") and risk["rule_id"].endswith("SUPPORT-DOCS")]
        self.assertEqual(len(support), 1)
        self.assertEqual(set(support[0]["related_file_ids"]), {"f1", "f2"})

    def test_item_support_prompts_keep_scope_and_skip_repeated_header(self):
        task_input, documents, extractions = self.support_case()
        field = deepcopy(extractions[0]["fields"][0])
        extractions[0]["line_items"] = [{"item_no": number, "fields": [deepcopy(field)]} for number in (1, 2)]
        items = [{"item_id": "item" + str(number), "label": "商品" + str(number), "members": [{"file_id": "f1", "item_no": number}]} for number in (1, 2)]
        risks = rules.evaluate_risks(task_input, documents, extractions, items)
        support = [risk for risk in risks if (risk.get("rule_id") or "").endswith("SUPPORT-DOCS")]
        self.assertEqual([risk["related_item_ids"] for risk in support], [["item1"], ["item2"]])

    def test_unaligned_rows_are_not_merged_by_hs_code(self):
        task_input, documents, extractions = self.support_case()
        field = extractions[0]["fields"].pop()
        extractions[0]["line_items"] = [{"item_no": number, "fields": [deepcopy(field)]} for number in (1, 2)]
        support = [risk for risk in rules.evaluate_risks(task_input, documents, extractions) if (risk.get("rule_id") or "").endswith("SUPPORT-DOCS")]
        self.assertEqual(len(support), 2)
        self.assertIn("第 1 行", support[0]["detail"])
        self.assertIn("第 2 行", support[1]["detail"])

    def test_support_prompt_sources_remain_linked_in_report(self):
        from app.report_content import content
        task_input, documents, extractions = self.support_case()
        documents.append({"file_id": "f2", "file_name": "support.pdf", "doc_type": "OTHER", "process_status": "FAILED"})
        task = {
            "task_id": "tsk_20261014_review", "status": "PARTIAL",
            "created_at": "2026-10-14T00:00:00+08:00", "finished_at": "2026-10-14T00:00:01+08:00",
            "input": task_input, "summary": {}, "documents": documents, "extractions": extractions,
            "items": [], "comparisons": [], "errors": [],
            "risks": rules.evaluate_risks(task_input, documents, extractions),
        }
        report = content(task, [])
        prompt = report["risks"][0]
        self.assertEqual(prompt["type"], "OTHER")
        self.assertEqual(prompt["rule_context"]["verification_status"], "UNVERIFIED")
        self.assertEqual(prompt["rule_context"]["source_ids"], ["FDA-CPG-545450"])
        self.assertIn("FDA-CPG-545450", {source["source_id"] for source in report["provenance"]["sources"]})


if __name__ == '__main__':
    unittest.main()
