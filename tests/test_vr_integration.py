import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config.database import DatabaseManager
from core.integrations.factory import create_integration
from core.integrations.profiles import ERP_PROFILES
from core.integrations.vr import VrIntegration
from core.api.vr_api_client import VrApiError
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
        self.reread_error = None

    def list_grupos_economicos(self):
        self.calls.append("grupos")
        return self.grupos

    def list_products(self, cnpj, cancel_check=None):
        self.calls.append("products")
        if self.reread_error is not None and "patch" in self.calls:
            raise self.reread_error
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
        self.vr = StubVr()
        self.api = StubApi()
        self.integration = self._make()
        products = []
        for code in (1, 2, 3):
            p = copy.deepcopy(vr_product())
            p["codigo"] = code
            products.append(p)
        self.vr.products = products + [product_without_store_uf()]

    def _make(self, write_enabled=True, env=None, **kwargs):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            for key in ("ORIONTAX_DRY_RUN", "ORIONTAX_VR_ONLY"):
                if key not in (env or {}):
                    os.environ.pop(key, None)
            integration = VrIntegration(
                {"base_url": "http://x", "token": "t", "write_enabled": write_enabled},
                {"base_url": "https://api.example.com", "token": "t"},
                "inst-1",
                lambda cnpj: {"nome": "Loja", "cnpj": cnpj, "uf": "GO"},
                **kwargs,
            )
        integration.vr = self.vr
        integration.api = self.api
        return integration

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
        self.assertIn("⚠ ICMS e PIS/COFINS valem para todas as lojas da UF GO e do grupo Lojas Serve Bem "
                      "(1 loja(s) no grupo); NCM e CEST valem para todas as lojas.", progress)
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
        self.assertEqual("[DRY-RUN] 3 correção(ões) e 1 vínculo(s) montados; nada foi gravado na VR. "
                         "Atenção: a fotografia da OrionTax foi consumida; peça o reenvio antes da gravação real.",
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

    def test_receive_reread_error_keeps_write_record(self):
        self._setup_receive()
        self.vr.reread_error = VrApiError("timeout")
        result = self.integration.receive(CNPJ)
        self.assertFalse(result.success)
        self.assertEqual(3, result.records)
        self.assertEqual({"SUCESSO": 3}, result.details["patch_status"])
        self.assertEqual("3 produto(s) gravado(s) na VR, 1 sem alteração, 1 rejeitado(s). "
                         "Não foi possível reler os produtos para conferência: timeout.", result.message)

    def test_receive_message_and_progress_show_patch_failures(self):
        self._setup_receive()
        self.vr.patch_status = {2: "ERRO"}
        self.vr.ignore_codes = {2}
        progress = []
        result = self.integration.receive(CNPJ, progress.append)
        self.assertIn(" 1 falha(s) na gravação.", result.message)
        self.assertIn("⚠ Produto 2: ERRO – processado", progress)

    def test_receive_summarizes_more_than_20_patch_failures(self):
        self.vr.products = [store_product(c) for c in range(1, 23)]
        self.api.targets = [target_for(c, **CHANGED) for c in range(1, 23)]
        self.vr.patch_status = {c: "ERRO" for c in range(1, 23)}
        progress = []
        result = self.integration.receive(CNPJ, progress.append)
        self.assertIn(" 22 falha(s) na gravação.", result.message)
        self.assertEqual(20, len([m for m in progress if m.startswith("⚠ Produto ")]))
        self.assertIn("⚠ ... e mais 2 falha(s).", progress)

    def test_receive_progress_shows_vinculo_failures_and_divergences(self):
        self._setup_receive()
        self.api.targets[3].update(cst_ibs_cbs="000", c_class_trib="000001")
        self.vr.vincular_detalhes = {"produtosNaoVinculados": [{"codigo": 4, "motivo": "inativo"}],
                                     "ncmsNaoVinculados": [{"ncm": "1234", "motivo": "NCM em formato inválido"}]}
        self.vr.ignore_codes = {1}
        progress = []
        result = self.integration.receive(CNPJ, progress.append)
        self.assertIn(" 2 falha(s) na gravação.", result.message)
        self.assertIn(" 1 divergência(s) na releitura.", result.message)
        self.assertIn("⚠ Vínculo 55: produto 4 não vinculado (inativo)", progress)
        self.assertIn("⚠ Vínculo 55: NCM 1234 não vinculado (NCM em formato inválido)", progress)
        self.assertTrue(any(m.startswith("⚠ Produto 1: cst enviado") for m in progress))

    def test_receive_vincular_error_counts_as_failure(self):
        self._setup_receive()
        self.api.targets[3].update(cst_ibs_cbs="000", c_class_trib="000001")

        def boom(body):
            raise VrApiError("HTTP 500")
        self.vr.vincular_classificacao = boom
        progress = []
        result = self.integration.receive(CNPJ, progress.append)
        self.assertFalse(result.success)
        self.assertIn(" 1 falha(s) na gravação.", result.message)
        self.assertIn("⚠ Vínculo 55: HTTP 500", progress)

    # ----- trava de gravação, allowlist, fotografia, multi-UF -----

    GATE_OFF = ("Gravação na VR desabilitada. Homologue com ORIONTAX_DRY_RUN=1 e habilite em "
                "Configurar API VR.")

    def test_receive_gate_off_does_not_consume_oriontax(self):
        self._setup_receive()
        with tempfile.TemporaryDirectory() as temp:
            integration = self._make(write_enabled=False, snapshot_dir=Path(temp) / "vr_snapshots")
            result = integration.receive(CNPJ)
            self.assertFalse(Path(temp, "vr_snapshots").exists())
        self.assertFalse(result.success)
        self.assertEqual(self.GATE_OFF, result.message)
        self.assertEqual(0, self.api.receive_calls)
        self.assertEqual([], self.vr.patch_calls)

    def test_receive_gate_off_allows_dry_run(self):
        self._setup_receive()
        integration = self._make(write_enabled=False, env={"ORIONTAX_DRY_RUN": "1"})
        result = integration.receive(CNPJ)
        self.assertTrue(result.success)
        self.assertTrue(result.message.startswith("[DRY-RUN]"))
        self.assertEqual(1, self.api.receive_calls)
        self.assertEqual([], self.vr.patch_calls)

    def test_receive_gate_on_writes(self):
        self._setup_receive()
        result = self._make(write_enabled=True).receive(CNPJ)
        self.assertTrue(result.success)
        self.assertEqual(1, self.api.receive_calls)
        self.assertEqual([1, 2, 3], [i["codigoProduto"] for b in self.vr.patch_calls for i in b])

    def test_receive_allowlist_writes_only_listed_codes(self):
        self._setup_receive()
        for t in self.api.targets[:3]:
            t.update(cst_ibs_cbs="000", c_class_trib="000001")
        integration = self._make(env={"ORIONTAX_VR_ONLY": " 2, 0003 "})
        progress = []
        result = integration.receive(CNPJ, progress.append)
        self.assertEqual([2, 3], [i["codigoProduto"] for b in self.vr.patch_calls for i in b])
        self.assertEqual([[2, 3]], [c["codigoProdutos"] for c in self.vr.vincular_calls])
        self.assertEqual(3, result.details["skipped_allowlist"])
        self.assertIn("⚠ ORIONTAX_VR_ONLY ativo: 3 produto(s) fora da lista não serão gravados.", progress)
        self.assertEqual(0, result.details["rejected_count"])
        self.assertTrue(result.success)

    def test_receive_without_allowlist_reports_zero_skipped(self):
        self._setup_receive()
        progress = []
        result = self.integration.receive(CNPJ, progress.append)
        self.assertEqual(0, result.details["skipped_allowlist"])
        self.assertFalse(any("ORIONTAX_VR_ONLY" in m for m in progress))

    def test_receive_malformed_classification_date_rejects_only_that_product(self):
        self._setup_receive()
        for t in self.api.targets[:3]:
            t.update(cst_ibs_cbs="000", c_class_trib="000001")
        self.vr.products[1]["classificacaoTributaria"][0]["dataInicioCst"] = "31/02/2025"
        result = self.integration.receive(CNPJ)
        self.assertEqual([[1, 3]], [c["codigoProdutos"] for c in self.vr.vincular_calls])
        self.assertTrue(any(r.startswith("Produto 2: ") for r in result.details["rejected"]))
        self.assertIn(1, [i["codigoProduto"] for b in self.vr.patch_calls for i in b])
        self.assertIn(3, [i["codigoProduto"] for b in self.vr.patch_calls for i in b])

    def test_receive_catalog_classification_without_codigo_is_rejected(self):
        self._setup_receive()
        self.api.targets[3].update(cst_ibs_cbs="000", c_class_trib="000001")
        self.vr.list_classificacoes = lambda cnpj: [{"cst": "000", "cClassTrib": "000001"}]
        result = self.integration.receive(CNPJ)
        self.assertEqual([], self.vr.vincular_calls)
        self.assertTrue(any(r.startswith("Produto 4: ") for r in result.details["rejected"]))
        self.assertEqual(3, len([i for b in self.vr.patch_calls for i in b]))

    def test_receive_generic_value_error_in_correction_rejects_only_that_product(self):
        self._setup_receive()
        from core.integrations.vr import integration as module
        real = module.build_correction

        def flaky(current, target, ctx, catalogs):
            if str(target.get("codigo")) == "2":
                raise ValueError("valor estranho")
            return real(current, target, ctx, catalogs)
        with mock.patch.object(module, "build_correction", flaky):
            result = self.integration.receive(CNPJ)
        self.assertIn("Produto 2: valor estranho", result.details["rejected"])
        self.assertEqual([1, 3], [i["codigoProduto"] for b in self.vr.patch_calls for i in b])

    def test_receive_saves_oriontax_snapshot(self):
        self._setup_receive()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "vr_snapshots"
            integration = self._make(snapshot_dir=folder)
            progress = []
            integration.receive(CNPJ, progress.append)
            files = list(folder.glob(f"receive-*-{CNPJ}.json"))
            self.assertEqual(1, len(files))
            self.assertRegex(files[0].name, r"^receive-\d{8}-\d{6}-" + CNPJ + r"\.json$")
            self.assertEqual(self.api.targets, json.loads(files[0].read_text(encoding="utf-8")))
            self.assertIn(f"Fotografia OrionTax salva em {files[0]}", progress)

    def test_receive_snapshot_failure_only_warns(self):
        self._setup_receive()
        with tempfile.TemporaryDirectory() as temp:
            blocker = Path(temp) / "arquivo"
            blocker.write_text("x")
            integration = self._make(snapshot_dir=blocker / "vr_snapshots")
            progress = []
            result = integration.receive(CNPJ, progress.append)
        self.assertTrue(result.success)
        self.assertTrue(any(m.startswith("⚠ Não foi possível salvar a fotografia OrionTax") for m in progress))
        self.assertEqual(3, len([i for b in self.vr.patch_calls for i in b]))

    def test_receive_warns_about_active_stores_in_other_ufs(self):
        self._setup_receive()
        integration = self._make(active_ufs=lambda: {"GO", "SP", None, ""})
        progress = []
        integration.receive(CNPJ, progress.append)
        self.assertIn("⚠ Há lojas ativas em mais de uma UF (GO, SP); apenas a UF GO desta loja será "
                      "corrigida nesta execução.", progress)

    def test_receive_single_uf_has_no_multi_uf_warning(self):
        self._setup_receive()
        progress = []
        self._make(active_ufs=lambda: {"GO"}).receive(CNPJ, progress.append)
        self.assertFalse(any("mais de uma UF" in m for m in progress))

    def test_receive_patch_error_says_batch_state_unknown(self):
        self._setup_receive()
        calls = []

        def boom(items):
            calls.append(items)
            if len(calls) == 2:
                raise VrApiError("HTTP 500")
            return [{"codigoProduto": i["codigoProduto"], "status": "SUCESSO"} for i in items]
        self.vr.patch_integracao_fiscal = boom
        result = self.integration.receive(CNPJ)
        self.assertFalse(result.success)
        self.assertEqual("Erro ao gravar o lote 2/2 na VR: HTTP 500; 1 lote(s) já gravado(s) na VR, "
                         "lote 2 com estado desconhecido (confira no VRMaster).", result.message)

    def test_receive_unsupported_regime_does_not_consume_oriontax(self):
        self._setup_receive()
        self.vr.grupos[0]["regimeTributario"] = "SIMPLES NACIONAL"
        result = self.integration.receive(CNPJ)
        self.assertFalse(result.success)
        self.assertIn("não suportado pela integração VR", result.message)
        self.assertEqual(0, self.api.receive_calls)

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
                integration = create_integration(db, "vr")
                self.assertIsInstance(integration, VrIntegration)
                self.assertFalse(integration.write_enabled)
                self.assertEqual(Path(temp) / "vr_snapshots", Path(integration.snapshot_dir))
                db.create_cliente("Loja GO", "01234567000195", "GO")
                db.create_cliente("Loja SP", "22881305000192", "SP")
                db.create_cliente("Loja sem UF", "11222333000181")
                self.assertEqual({"GO", "SP"}, integration.active_ufs())
                db.save_vr_config("http://10.0.0.5:9025", "tok", write_enabled=True)
                self.assertTrue(create_integration(db, "vr").write_enabled)
            finally:
                db.disconnect()

    def test_scheduler_routes_vr_through_integration(self):
        from core.integrations.base import SyncResult
        from core.scheduler import Scheduler

        with tempfile.TemporaryDirectory() as temp:
            db = DatabaseManager(Path(temp) / "t.db")
            try:
                db.set_erp_type("vr")
                db.save_vr_config("http://10.0.0.5:9025", "tok")
                db.save_oriontax_api_config("https://api.example.com", "tok")
                fake = mock.Mock()
                fake.send.return_value = SyncResult(True, "ok", 3)
                scheduler = Scheduler(db)
                with mock.patch("core.integrations.create_integration", return_value=fake) as factory:
                    scheduler._execute_sync_for_client(
                        "ENVIAR", db.get_vr_config(), db.get_oriontax_api_config(),
                        CNPJ, "Loja", "vr")
                factory.assert_called_once_with(db, "vr")
                fake.send.assert_called_once()
                logs = db.get_logs_recentes(5)
                self.assertEqual("SUCESSO", logs[0]["status"])
                self.assertEqual(3, logs[0]["registros_processados"])
            finally:
                db.disconnect()


if __name__ == "__main__":
    unittest.main()
