import unittest
from unittest.mock import patch
from gost_ref.discovery import reconcile, discover


class DiscoveryTests(unittest.TestCase):
    def test_same_edition_merges_with_provenance(self):
        fields = {"title": "Книга", "year": "1978", "publisher": "Наука", "isbn": "123"}
        groups = reconcile([{"source": "A", "fields": fields}, {"source": "B", "fields": dict(fields)}])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["provenance"]["title"]), 2)

    def test_different_years_not_merged(self):
        base = {"title": "Книга", "publisher": "Наука", "isbn": "123"}
        groups = reconcile([{"fields": {**base, "year": "1978"}},
                            {"fields": {**base, "year": "1980"}}])
        self.assertEqual(len(groups), 2)

    def test_missing_details_not_assumed_same(self):
        self.assertEqual(len(reconcile([
            {"fields": {"title": "Книга", "year": "1978"}},
            {"fields": {"title": "Книга", "year": "1978", "publisher": "Наука"}}
        ])), 2)

    @patch("gost_ref.lookup.by_crossref_title", side_effect=RuntimeError("offline"))
    @patch("gost_ref.lookup.by_openalex")
    def test_provider_failure_isolated(self, openalex, crossref):
        openalex.return_value = {"source": "OpenAlex", "fields": {"title": "Книга"}}
        result = discover("Книга")
        self.assertEqual(result["raw_count"], 1)
        self.assertIn("crossref", result["provider_errors"])
        self.assertEqual(result["manual_checks"][0]["provider"], "РГБ")
        self.assertFalse(result["groups"][0]["verified"])


if __name__ == "__main__":
    unittest.main()
