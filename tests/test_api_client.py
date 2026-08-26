import unittest

from core.api.oriontax_api_client import OrionTaxApiClient, OrionTaxApiError


class FakeApi(OrionTaxApiClient):
    def __init__(self, responses):
        super().__init__({"base_url": "https://api.test", "token": "secret", "page_size": 2})
        self.responses = iter(responses)

    def _request(self, method, path, body=None, query=None):
        return next(self.responses)


class ApiClientTests(unittest.TestCase):
    def test_send_requires_job_id(self):
        api = FakeApi([(201, {"job_id": "job-1"})])
        self.assertEqual("job-1", api.send_products([{"codigo": "1"}]))
        with self.assertRaises(ValueError):
            api.send_products([])

    def test_receive_all_pages_and_deduplicates(self):
        api = FakeApi([
            (200, {"page": 1, "total_pages": 2, "results": [{"codigo": "1"}, {"codigo": "2"}]}),
            (200, {"page": 2, "total_pages": 2, "results": [{"codigo": "2", "ncm": "new"}]}),
        ])
        result = api.receive_products()
        self.assertEqual(2, len(result))
        self.assertEqual("new", next(x for x in result if x["codigo"] == "2")["ncm"])

    def test_receive_rejects_product_without_code(self):
        api = FakeApi([(200, {"page": 1, "total_pages": 1, "results": [{}]})])
        with self.assertRaises(OrionTaxApiError):
            api.receive_products()


if __name__ == "__main__":
    unittest.main()
