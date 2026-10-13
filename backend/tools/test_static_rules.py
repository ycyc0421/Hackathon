import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline import rules
from crawl_rule_sources import OfficialRedirectHandler, fetch_source


class StaticRulesTests(unittest.TestCase):
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
        self.assertEqual([risk["type"] for risk in risks],["MISSING_CERTIFICATE","HS_CLASSIFICATION"])
        self.assertIn("www.fda.gov",risks[0]["rule_source"])
        self.assertIn("未经核实",risks[0]["title"])
        self.assertEqual(risks[0]["rule_id"],"US-CERAMICS-6911-SUPPORT-DOCS")

    def test_unparsed_file_prevents_missing_certificate_conclusion(self):
        risks=rules.evaluate_risks({"destination_country":"DE"}, [
            {"file_id":"f1","file_name":"invoice.pdf","doc_type":"COMMERCIAL_INVOICE","process_status":"EXTRACTED"},
            {"file_id":"f2","file_name":"support.pdf","doc_type":None,"process_status":"FAILED"},
        ], [{"file_id":"f1","fields":[{"field_key":"hs_code","status":"EXTRACTED","normalized_value":"69120000"}]}])
        self.assertEqual(risks[0]["type"],"OTHER")
        self.assertIsNone(risks[0]["rule_id"])
        self.assertIn("无法确认",risks[0]["title"])
        self.assertEqual(risks[1]["type"],"HS_CLASSIFICATION")

    def test_crawler_rejects_untrusted_sources_and_redirects(self):
        with self.assertRaises(ValueError):
            fetch_source({"source_id":"x","url":"https://example.com"},Path("unused"))
        with self.assertRaises(ValueError):
            OfficialRedirectHandler().redirect_request(None,None,302,"",{},"http://www.fda.gov/x")


if __name__ == '__main__':
    unittest.main()
