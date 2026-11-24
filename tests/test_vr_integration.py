import copy
import tempfile
import unittest
from pathlib import Path

from config.database import DatabaseManager
from core.integrations.factory import create_integration
from core.integrations.profiles import ERP_PROFILES
from core.integrations.vr import VrIntegration
from core.integrations.vr.mapper import vr_product_to_api
from tests.test_vr_correction import CATALOGS
from tests.test_vr_mapper import CTX, TODAY, vr_product

CNPJ = "01234567000195"


def product_without_store_uf():
    product = vr_product()
    product["codigo"] = 99999
    product["aliquotas"] = [a for a in product["aliquotas"] if a["uf"] != "GO"]
    return product


class StubVr:
    patch_batch_size = 2

    def __init__(self):
        self.calls = []
        self.grupos = [{"codigo": 1, "nome": "Lojas Serve Bem", "regimeTributario": "LUCRO REAL",
                        "lojas": [{"cnpj": 1234567000195}]}]
        self.products = []
        self.catalog_ufs = []
        self.patch_calls = []
        self.patch_status = {}
        self.ignore_codes = set()
        self.vincular_calls = []
        self.vincular_detalhes = None
        self.on_patch = None

    def list_grupos_economicos(self):
        self.calls.append("grupos")
        return self.grupos

    def list_products(self, cnpj, cancel_check=None):
        self.calls.append("products")
        return copy.deepcopy(self.products)

    def list_icms(self, uf):
        self.catalog_ufs.append(("icms", uf))
        return CATALOGS.icms

    def list_piscofins(self):
        return CATALOGS.piscofins

    def list_pautas_fiscais(self, uf):
        self.catalog_ufs.append(("pautas", uf))
        return CATALOGS.pautas

    def list_classificacoes(self, cnpj):
        return CATALOGS.classificacoes

    def patch_integracao_fiscal(self, items):
        self.calls.append("patch")
        self.patch_calls.append(items)
        response = []
        for item in items:
            code = item["codigoProduto"]
            if code not in self.ignore_codes:  # simula a gravação para a releitura
                product = next(p for p in self.products if p["codigo"] == code)
                product["classificacaoFiscal"]["ncm"] = item["classificacaoFiscal"]["ncm"]
                uf_item = next(a for a in product["aliquotas"] if a["uf"] == item["estados"][0])
                uf_item["icmsConsumidorFinal"] = dict(item["aliquotas"]["icmsConsumidorFinal"])
            response.append({"codigoProduto": code, "status": self.patch_status.get(code, "SUCESSO"),
                             "info": "processado"})
        if self.on_patch:
            self.on_patch()
        return response

    def vincular_classificacao(self, body):
        self.calls.append("vincular")
        self.vincular_calls.append(body)
        if self.vincular_detalhes is not None:
            return self.vincular_detalhes
        return {"produtosVinculados": [{"codigo": c} for c in body["codigoProdutos"]],
                "totalProdutos": len(body["codigoProdutos"]),
                "produtosNaoVinculados": [], "totalProdutosNaoVinculados": 0,
                "ncmsVinculados": [], "ncmsNaoVinculados": []}


class StubApi:
    batch_size = 2

    def __init__(self):
        self.sent_batches = []
        self.targets = []
        self.receive_calls = 0

    def send_products(self, batch):
        self.sent_batches.append(batch)
        return f"job-{len(self.sent_batches)}"

    def receive_products(self):
        self.receive_calls += 1
        return copy.deepcopy(self.targets)


def store_product(code):
    product = copy.deepcopy(vr_product())
    product["codigo"] = code
    return product


def target_for(code, **changes):
    return {**vr_product_to_api(store_product(code), CTX, TODAY), **changes}


CHANGED = {"icms_cst": 0, "percentual_redbcde": 0}  # CST 20 -> 00, cadastro 8 no catálogo


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

    def _setup_receive(self):
        self.vr.products = [store_product(c) for c in (1, 2, 3, 4)]
        self.api.targets = [target_for(1, **CHANGED), target_for(2, **CHANGED), target_for(3, **CHANGED),
                            target_for(4), {**target_for(4, **CHANGED), "codigo": "77777"}]

    def test_receive_patches_only_changed_products_in_batches(self):
        self._setup_receive()
        progress = []
        result = self.integration.receive(CNPJ, progress.append)
        self.assertEqual([2, 1], [len(b) for b in self.vr.patch_calls])
        self.assertEqual([1, 2, 3], [i["codigoProduto"] for b in self.vr.patch_calls for i in b])
        self.assertEqual(1, result.details["unchanged"])
        self.assertEqual(1, result.details["rejected_count"])
        self.assertIn("77777", result.details["rejected"][0])
        self.assertEqual({"SUCESSO": 3}, result.details["patch_status"])
        self.assertEqual([], result.details["divergences"])
        self.assertTrue(result.success)
        self.assertEqual(3, result.records)
        self.assertEqual("3 produto(s) gravado(s) na VR, 1 sem alteração, 1 rejeitado(s).", result.message)
        self.assertTrue(any("todas as lojas da UF GO" in m and "Lojas Serve Bem" in m for m in progress))
        self.assertTrue(any(m.startswith("⚠ 1 produto(s) rejeitado(s)") for m in progress))
        self.assertTrue(any("Gravando lote 2/2 na VR" in m for m in progress))
        self.assertEqual([("icms", "GO"), ("pautas", "GO")], self.vr.catalog_ufs)

    def test_receive_reads_store_state_before_consuming_oriontax(self):
        self._setup_receive()
        self.integration.store_lookup = lambda cnpj: {"nome": "Loja Centro", "cnpj": cnpj, "uf": ""}
        result = self.integration.receive(CNPJ)
        self.assertFalse(result.success)
        self.assertIn("Informe a UF da loja Loja Centro", result.message)
        self.assertEqual(0, self.api.receive_calls)

    def test_receive_unknown_group_does_not_consume_oriontax(self):
        self._setup_receive()
        self.vr.grupos = [{"codigo": 1, "nome": "X", "regimeTributario": "LUCRO REAL", "lojas": []}]
        result = self.integration.receive(CNPJ)
        self.assertFalse(result.success)
        self.assertIn("grupo econômico", result.message)
        self.assertEqual(0, self.api.receive_calls)

    def test_receive_dry_run_does_not_write(self):
        self._setup_receive()
        self.api.targets[0].update(cst_ibs_cbs="000", c_class_trib="000001")
        self.integration.dry_run = True
        progress = []
        result = self.integration.receive(CNPJ, progress.append)
        self.assertEqual([], self.vr.patch_calls)
        self.assertEqual([], self.vr.vincular_calls)
        self.assertTrue(result.message.startswith("[DRY-RUN]"))
        self.assertEqual("[DRY-RUN] 3 correção(ões) e 1 vínculo(s) montados; nada foi gravado na VR.",
                         result.message)
        self.assertTrue(result.success)
        self.assertTrue(any('"codigoProduto": 1' in m for m in progress))
        self.assertTrue(any('"codigoClassificacaoTributaria": 55' in m for m in progress))

    def test_receive_reports_item_failures_from_patch(self):
        self._setup_receive()
        self.vr.patch_status = {2: "ERRO"}
        self.vr.ignore_codes = {2}
        result = self.integration.receive(CNPJ)
        self.assertFalse(result.success)
        self.assertEqual(1, result.details["patch_status"]["ERRO"])
        self.assertEqual(2, result.details["patch_status"]["SUCESSO"])
        self.assertEqual([2], [i["codigoProduto"] for i in result.details["patch_info"]])
        self.assertEqual([], result.details["divergences"])  # item com erro não é relido
        self.assertTrue(result.message.startswith("2 produto(s) gravado(s) na VR"))

    def test_receive_accepts_ok_status_case_insensitive(self):
        self._setup_receive()
        self.vr.patch_status = {1: "ok", 2: "Produto atualizado com sucesso"}
        result = self.integration.receive(CNPJ)
        self.assertTrue(result.success)
        self.assertEqual([], result.details["patch_info"])

    def test_receive_reports_divergence_on_reread(self):
        self._setup_receive()
        self.vr.ignore_codes = {1}
        result = self.integration.receive(CNPJ)
        self.assertFalse(result.success)
        self.assertEqual(1, len(result.details["divergences"]))
        self.assertIn("1", result.details["divergences"][0])
        self.assertTrue(result.message.endswith(" 1 divergência(s) na releitura."))

    def test_receive_verifies_csosn_when_sent(self):
        self.vr.products = [store_product(1)]
        self.vr.products[0]["aliquotas"][1]["icmsConsumidorFinal"].update(cst="", csosn="102")
        self.api.targets = [target_for(1, icms_cst=500, percentual_redbcde=0)]
        self.vr.list_icms = lambda uf: [{"codigo": 9, "cst": "", "csosn": "500", "percentual": 19,
                                         "percentualReducao": 0, "percentualDiferimento": 0,
                                         "percentualFCP": 2}]
        self.vr.ignore_codes = {1}
        result = self.integration.receive(CNPJ)
        self.assertEqual(1, len(result.details["divergences"]))
        self.assertIn("csosn", result.details["divergences"][0])

    def test_receive_sends_vinculos(self):
        self._setup_receive()
        self.api.targets[3].update(cst_ibs_cbs="000", c_class_trib="000001")  # inalterado no ICMS
        result = self.integration.receive(CNPJ)
        self.assertEqual(55, self.vr.vincular_calls[0]["codigoClassificacaoTributaria"])
        self.assertEqual([4], self.vr.vincular_calls[0]["codigoProdutos"])
        self.assertEqual(["patch", "patch", "vincular"], [c for c in self.vr.calls if c in ("patch", "vincular")])
        self.assertEqual(1, len(result.details["vinculos"]))
        self.assertTrue(result.success)

    def test_receive_counts_products_not_linked_as_failure(self):
        self._setup_receive()
        self.api.targets[3].update(cst_ibs_cbs="000", c_class_trib="000001")
        self.vr.vincular_detalhes = {"produtosVinculados": [], "totalProdutos": 0,
                                     "produtosNaoVinculados": [{"codigo": 4, "motivo": "inativo"}],
                                     "totalProdutosNaoVinculados": 1}
        result = self.integration.receive(CNPJ)
        self.assertFalse(result.success)
        self.assertEqual("inativo", result.details["vinculos"][0]["produtosNaoVinculados"][0]["motivo"])

    def test_receive_rejects_vinculo_without_classificacao(self):
        self._setup_receive()
        self.api.targets[3].update(cst_ibs_cbs="000", c_class_trib="999999")
        result = self.integration.receive(CNPJ)
        self.assertEqual([], self.vr.vincular_calls)
        self.assertEqual(2, result.details["rejected_count"])

    def test_receive_stops_between_batches_when_cancelled(self):
        self._setup_receive()
        self.vr.on_patch = self.integration.cancel
        result = self.integration.receive(CNPJ)
        self.assertEqual(1, len(self.vr.patch_calls))
        self.assertEqual([], self.vr.vincular_calls)
        self.assertFalse(result.success)
        self.assertEqual("Operação cancelada; 1 lote(s) já gravado(s) na VR.", result.message)

    def test_receive_with_nothing_to_write(self):
        self.vr.products = [store_product(4)]
        self.api.targets = [target_for(4)]
        result = self.integration.receive(CNPJ)
        self.assertTrue(result.success)
        self.assertEqual([], self.vr.patch_calls)
        self.assertEqual("0 produto(s) gravado(s) na VR, 1 sem alteração, 0 rejeitado(s).", result.message)

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
