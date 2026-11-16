import unittest
from gost_ref.rsl import search_instructions, record_url, record_id_from_url, parse_record_html


class RSLTests(unittest.TestCase):
    def test_search_fields(self):
        q = search_instructions(title="Первые русские города Сибири", author="Кочедамов")
        self.assertIn('title:"Первые русские города Сибири"', q["query"])
        self.assertIn('author:"Кочедамов"', q["query"])
        self.assertFalse(q["verified"])

    def test_empty_query(self):
        with self.assertRaises(ValueError):
            search_instructions()

    def test_record_id(self):
        url = record_url("01004095555")
        self.assertEqual(record_id_from_url(url), "01004095555")

    def test_untrusted_url(self):
        for url in ("https://evil.test/ru/record/01004095555",
                    "http://search.rsl.ru/ru/record/01004095555",
                    "https://search.rsl.ru/ru/record/01004095555?x=1"):
            with self.assertRaises(ValueError):
                record_id_from_url(url)

    def test_parse_fixture(self):
        html = "<html><body><h2>Описание</h2><div>Заглавие</div><div>Словарь Академии Российской</div><div>Выходные данные</div><div>Санкт-Петербург, 1789</div></body></html>"
        record = parse_record_html(record_url("01004095555"), html)
        self.assertEqual(record["fields"]["title"], "Словарь Академии Российской")
        self.assertFalse(record["verified"])


if __name__ == "__main__":
    unittest.main()
