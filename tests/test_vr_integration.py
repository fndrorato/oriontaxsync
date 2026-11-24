import copy
import tempfile
import unittest
from pathlib import Path

from config.database import DatabaseManager
from core.integrations.factory import create_integration
from core.integrations.profiles import ERP_PROFILES
from core.integrations.vr import VrIntegration
from tests.test_vr_mapper import vr_product

CNPJ = "01234567000195"


def product_without_store_uf():
    product = vr_product()
    product["codigo"] = 99999
    product["aliquotas"] = [a for a in product["aliquotas"] if a["uf"] != "GO"]
    return product


class StubVr:
    def __init__(self):
        self.calls = []
        self.grupos = [{"codigo": 1, "nome": "Lojas Serve Bem", "regimeTributario": "LUCRO REAL",
                        "lojas": [{"cnpj": 1234567000195}]}]
        self.products = []

    def list_grupos_economicos(self):
        self.calls.append("grupos")
        return self.grupos

    def list_products(self, cnpj, cancel_check=None):
        self.calls.append("products")
        return self.products


class StubApi:
    batch_size = 2

    def __init__(self):
        self.sent_batches = []

    def send_products(self, batch):
        self.sent_batches.append(batch)
        return f"job-{len(self.sent_batches)}"


class VrIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.integration = VrIntegration(
            {"base_url": "http://x", "token": "t"},
            {"base_url": "https://api.example.com", "token": "t"},
            "inst-1",
            lambda cnpj: {"nome": "Loja", "cnpj": cnpj, "uf": "GO"},
        )
        self.vr = StubVr()
        self.api = StubApi()
        self.integration.vr = self.vr
        self.integration.api = self.api
        products = []
        for code in (1, 2, 3):
            p = copy.deepcopy(vr_product())
            p["codigo"] = code
            products.append(p)
        self.vr.products = products + [product_without_store_uf()]

    def test_send_maps_batches_and_reports_rejections(self):
        progress = []
        result = self.integration.send(CNPJ, progress.append)
        self.assertTrue(result.success)
        self.assertEqual(3, result.records)
        self.assertEqual(["job-1", "job-2"], result.accepted_jobs)
        self.assertEqual(1, result.details["rejected_count"])
        self.assertTrue(any("UF GO" in m for m in progress))

    def test_send_fails_when_cnpj_not_in_any_group(self):
        self.vr.grupos = [{"codigo": 1, "nome": "X", "regimeTributario": "LUCRO REAL", "lojas": []}]
        result = self.integration.send(CNPJ)
        self.assertFalse(result.success)
        self.assertIn("grupo econômico", result.message)
        self.assertEqual([], self.api.sent_batches)

    def test_send_stops_when_store_has_no_uf(self):
        self.integration.store_lookup = lambda cnpj: {"nome": "Loja Centro", "cnpj": cnpj, "uf": None}
        result = self.integration.send(CNPJ)
        self.assertFalse(result.success)
        self.assertIn("Informe a UF da loja Loja Centro", result.message)
        self.assertEqual([], self.vr.calls)

    def test_missing_client_uses_formatted_cnpj(self):
        self.integration.store_lookup = lambda cnpj: None
        result = self.integration.send(CNPJ)
        self.assertIn("01.234.567/0001-95", result.message)

    def test_send_with_no_valid_products_does_not_call_api(self):
        self.vr.products = [product_without_store_uf()]
        result = self.integration.send(CNPJ)
        self.assertFalse(result.success)
        self.assertEqual("Nenhum produto válido para envio.", result.message)
        self.assertEqual([], self.api.sent_batches)

    def test_cancel_sets_flag(self):
        self.integration.cancel()
        self.assertTrue(self.integration._cancelled)

    def test_profile(self):
        self.assertEqual("VR", ERP_PROFILES["vr"]["name"])

    def test_factory_creates_vr_integration(self):
        with tempfile.TemporaryDirectory() as temp:
            db = DatabaseManager(Path(temp) / "t.db")
            try:
                with self.assertRaises(RuntimeError):
                    create_integration(db, "vr")
                db.set_erp_type("vr")
                db.save_vr_config("http://10.0.0.5:9025", "tok")
                db.save_oriontax_api_config("https://api.example.com", "tok")
                self.assertIsInstance(create_integration(db, "vr"), VrIntegration)
            finally:
                db.disconnect()


if __name__ == "__main__":
    unittest.main()
