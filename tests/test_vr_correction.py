import unittest
from dataclasses import replace

from core.integrations.vr.correction import (
    CorrectionRejected, VrCatalogs, build_correction, build_vinculos,
    format_cest, format_ncm, resolve_icms_id, resolve_piscofins_id,
)
from core.integrations.vr.mapper import vr_product_to_api
from tests.test_vr_mapper import CTX, TODAY, vr_product

CATALOGS = VrCatalogs(
    icms=[{"codigo": 7, "cst": "20", "csosn": "", "percentual": 19, "percentualReducao": 26.32,
           "percentualDiferimento": 0, "percentualFCP": 2},
          {"codigo": 8, "cst": "00", "csosn": "", "percentual": 19, "percentualReducao": 0,
           "percentualDiferimento": 0, "percentualFCP": 2}],
    piscofins=[{"codigo": 3, "cst": 1, "tipoOperacao": "SAIDA",
                "tributacaoLucroReal": {"pis": 1.65, "cofins": 7.6}},
               {"codigo": 4, "cst": 4, "tipoOperacao": "SAIDA",
                "tributacaoLucroReal": {"pis": 0, "cofins": 0}}],
    pautas=[],
    classificacoes=[{"codigo": 55, "cst": "000", "cClassTrib": "000001"}],
)


def with_pauta():
    prod = vr_product()
    prod["aliquotas"][1]["pautaFiscal"] = {
        "mva": 30, "mvaAjustada": 35, "percentualProdepe": 0, "recolheIcmsAntecipadamente": False,
        "icmsDebito": {"cst": "00", "csosn": "", "percentual": 19, "percentualReducao": 0,
                       "percentualDiferimento": 0, "percentualFCP": 2},
        "icmsCredito": {"cst": "00", "percentual": 12},
    }
    return prod


class BuildCorrectionTests(unittest.TestCase):
    def test_unchanged_target_returns_none(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY)
        self.assertIsNone(build_correction(vr_product(), target, CTX, CATALOGS))

    def test_overlays_consumer_icms_and_resolves_id(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
        item = build_correction(vr_product(), target, CTX, CATALOGS)
        cf = item["aliquotas"]["icmsConsumidorFinal"]
        self.assertEqual(("00", 19.0, 0, 8), (cf["cst"], cf["percentual"], cf["percentualReducao"], cf["idAliquota"]))
        self.assertEqual(("00", 19), (item["aliquotas"]["icmsDebito"]["cst"], item["aliquotas"]["icmsDebito"]["percentual"]))  # cenário não alvo preservado
        self.assertEqual((86922, ["GO"], [1]), (item["codigoProduto"], item["estados"], item["gruposEconomicos"]))
        self.assertEqual("1901.90.00", item["classificacaoFiscal"]["ncm"])
        self.assertEqual("17.004.00", item["classificacaoFiscal"]["cest"])
        self.assertNotIn("regraFiscal", item)

    def test_keeps_other_fields_of_consumer_scenario_and_full_pis_cofins(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
        item = build_correction(vr_product(), target, CTX, CATALOGS)
        cf = item["aliquotas"]["icmsConsumidorFinal"]
        self.assertEqual((2.0, "GO821001", ""), (cf["percentualFCP"], cf["cBenef"], cf["csosn"]))
        self.assertEqual(0, item["classificacaoFiscal"]["exTIPI"])
        saida = item["pisCofins"]["pisCofinsSaida"]
        self.assertEqual((3, 1, 1.65, 7.6, 0), (saida["idPisCofins"], saida["cst"], saida["pis"],
                                                saida["cofins"], saida["naturezaReceita"]))
        entrada = item["pisCofins"]["pisCofinsEntrada"]
        self.assertEqual((9, 50, 1.65, 7.6, 0), (entrada["idPisCofins"], entrada["cst"], entrada["pis"],
                                                 entrada["cofins"], entrada["percentualReducao"]))
        self.assertNotIn("icmsCredito", item["aliquotas"])  # cenário ausente no atual não é inventado
        self.assertNotIn("pautaFiscal", item)

    def test_derives_reduction_from_reduced_rate_when_absent(self):
        target = {**vr_product_to_api(vr_product(), CTX, TODAY), "icms_aliquota_reduzida": 14.0}
        target.pop("percentual_redbcde")
        # 1 - 14/19 = 26.32%
        self.assertIsNone(build_correction(vr_product(), target, CTX, CATALOGS))

    def test_reduction_is_zero_without_reduced_rate(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": 0}
        target.pop("percentual_redbcde")
        cf = build_correction(vr_product(), target, CTX, CATALOGS)["aliquotas"]["icmsConsumidorFinal"]
        self.assertEqual((0, 8), (cf["percentualReducao"], cf["idAliquota"]))

    def test_rejects_when_no_compatible_icms_cadastro(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_aliquota": 17.0}
        with self.assertRaisesRegex(CorrectionRejected, "Produto 86922: sem cadastro de ICMS"):
            build_correction(vr_product(), target, CTX, CATALOGS)

    def test_rejects_target_without_icms_cst(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": None}
        with self.assertRaisesRegex(CorrectionRejected, "Produto 86922: .*CST"):
            build_correction(vr_product(), target, CTX, CATALOGS)

    def test_resolves_new_pis_cofins_saida_and_keeps_entrada(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"pis_cst": "04", "pis_aliquota": 0, "cofins_aliquota": 0}
        item = build_correction(vr_product(), target, CTX, CATALOGS)
        self.assertEqual((4, 4), (item["pisCofins"]["pisCofinsSaida"]["idPisCofins"], item["pisCofins"]["pisCofinsSaida"]["cst"]))
        self.assertEqual(9, item["pisCofins"]["pisCofinsEntrada"]["idPisCofins"])

    def test_rejects_pis_cofins_without_cadastro(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"pis_cst": "06", "pis_aliquota": 0, "cofins_aliquota": 0}
        with self.assertRaisesRegex(CorrectionRejected, "Produto 86922: .*PIS/COFINS"):
            build_correction(vr_product(), target, CTX, CATALOGS)

    def test_null_pis_cst_keeps_current_saida(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"pis_cst": None, "pis_aliquota": 0,
                                                               "cofins_aliquota": 0, "icms_cst": 0,
                                                               "percentual_redbcde": 0}
        saida = build_correction(vr_product(), target, CTX, CATALOGS)["pisCofins"]["pisCofinsSaida"]
        self.assertEqual((3, 1, 1.65, 7.6), (saida["idPisCofins"], saida["cst"], saida["pis"], saida["cofins"]))

    def test_null_pis_cst_alone_is_unchanged(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"pis_cst": None}
        self.assertIsNone(build_correction(vr_product(), target, CTX, CATALOGS))

    def test_rejects_product_missing_in_store(self):
        with self.assertRaisesRegex(CorrectionRejected, "não encontrado"):
            build_correction(None, {"codigo": "1", "ncm": "19019000"}, CTX, CATALOGS)

    def test_rejects_non_numeric_code(self):
        with self.assertRaisesRegex(CorrectionRejected, "não numérico"):
            build_correction(vr_product(), {"codigo": "ABC", "ncm": "19019000"}, CTX, CATALOGS)

    def test_rejects_code_mismatch(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"codigo": "1"}
        with self.assertRaises(CorrectionRejected):
            build_correction(vr_product(), target, CTX, CATALOGS)

    def test_rejects_invalid_ncm(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"ncm": "1901"}
        with self.assertRaises(CorrectionRejected):
            build_correction(vr_product(), target, CTX, CATALOGS)

    def test_rejects_without_store_uf_or_group(self):
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
        no_uf = vr_product()
        no_uf["aliquotas"] = no_uf["aliquotas"][:1]
        with self.assertRaisesRegex(CorrectionRejected, "Produto 86922: .*UF GO"):
            build_correction(no_uf, target, CTX, CATALOGS)
        no_group = vr_product()
        no_group["pisCofins"] = no_group["pisCofins"][:1]
        with self.assertRaisesRegex(CorrectionRejected, "Produto 86922: .*Lojas Serve Bem"):
            build_correction(no_group, target, CTX, CATALOGS)

    def test_csosn_target_goes_to_csosn_field(self):
        catalogs = replace(CATALOGS, icms=CATALOGS.icms + [{"codigo": 11, "cst": "", "csosn": "102", "percentual": 19,
                                                             "percentualReducao": 26.32, "percentualDiferimento": 0, "percentualFCP": 2}])
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": 102}
        cf = build_correction(vr_product(), target, CTX, catalogs)["aliquotas"]["icmsConsumidorFinal"]
        self.assertEqual(("", "102", 11), (cf["cst"], cf["csosn"], cf["idAliquota"]))

    def test_pauta_fiscal_keeps_values_resolves_icms_and_value_type(self):
        catalogs = replace(CATALOGS, pautas=[{"ncm": "1901.90.00", "tipoValor": "Percentual"}])
        target = vr_product_to_api(with_pauta(), CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
        pauta = build_correction(with_pauta(), target, CTX, catalogs)["pautaFiscal"]
        self.assertEqual((30, 35, True, False), (pauta["mva"], pauta["mvaAjustada"], pauta["valorPercentual"],
                                                 pauta["recolheIcmsAntecipadamente"]))
        self.assertNotIn("idPauta", pauta)
        self.assertEqual(8, pauta["icmsDebito"]["idAliquota"])
        self.assertNotIn("idAliquota", pauta["icmsCredito"])  # sem cadastro: só valores
        self.assertEqual(("00", 12), (pauta["icmsCredito"]["cst"], pauta["icmsCredito"]["percentual"]))
        pauta2 = build_correction(with_pauta(), target, CTX, CATALOGS)["pautaFiscal"]
        self.assertIs(False, pauta2["valorPercentual"])


class HelperTests(unittest.TestCase):
    def test_format_ncm_and_cest(self):
        self.assertEqual("1901.90.00", format_ncm("19019000"))
        self.assertEqual("1901.90.00", format_ncm("1901.90.00"))
        with self.assertRaises(CorrectionRejected):
            format_ncm("1901")
        with self.assertRaises(CorrectionRejected):
            format_ncm(None)
        self.assertEqual("17.004.00", format_cest("1700400"))
        self.assertEqual("", format_cest(""))
        self.assertEqual("", format_cest(None))
        with self.assertRaises(CorrectionRejected):
            format_cest("170")

    def test_resolve_icms_id_tolerance_and_empty_values(self):
        values = {"cst": "20", "csosn": None, "percentual": 19.0004, "percentualReducao": 26.32,
                  "percentualDiferimento": None, "percentualFCP": "2"}
        self.assertEqual(7, resolve_icms_id(values, CATALOGS.icms))
        self.assertIsNone(resolve_icms_id(values | {"percentual": 19.01}, CATALOGS.icms))
        self.assertIsNone(resolve_icms_id(values, []))

    def test_resolve_piscofins_id_only_saida(self):
        catalog = [{"codigo": 1, "cst": 1, "tipoOperacao": "ENTRADA",
                    "tributacaoLucroReal": {"pis": 1.65, "cofins": 7.6}}] + CATALOGS.piscofins
        self.assertEqual(3, resolve_piscofins_id(1, 1.65, 7.6, "LUCRO REAL", catalog))
        self.assertIsNone(resolve_piscofins_id(1, 1.65, 7.6, "LUCRO PRESUMIDO", catalog))
        debito = [{"codigo": 5, "cst": 1, "tipoOperacao": "Débito",
                   "tributacaoLucroPresumido": {"pis": 0.65, "cofins": 3}}]
        self.assertEqual(5, resolve_piscofins_id(1, 0.65, 3, "LUCRO PRESUMIDO", debito))


class BuildVinculosTests(unittest.TestCase):
    def test_build_vinculos_groups_by_classification(self):
        t = lambda code: {"codigo": str(code), "cst_ibs_cbs": "000", "c_class_trib": "1"}
        p1, p2 = vr_product(), {**vr_product(), "codigo": 86923}
        bodies, rejected = build_vinculos([(p1, t(86922)), (p2, t(86923))], CTX, CATALOGS, TODAY)
        self.assertEqual([{"codigoClassificacaoTributaria": 55, "codigoProdutos": [86922, 86923],
                           "cnpj": 1234567000195, "observacao": "OrionTax Sync"}], bodies)
        self.assertEqual([], rejected)

    def test_build_vinculos_skips_unchanged_and_reports_unknown(self):
        same = {"codigo": "86922", "cst_ibs_cbs": "200", "c_class_trib": "200003"}
        unknown = {"codigo": "86922", "cst_ibs_cbs": "410", "c_class_trib": "410999"}
        self.assertEqual(([], []), build_vinculos([(vr_product(), same)], CTX, CATALOGS, TODAY))
        bodies, rejected = build_vinculos([(vr_product(), unknown)], CTX, CATALOGS, TODAY)
        self.assertEqual([], bodies); self.assertIn("410999", rejected[0])

    def test_build_vinculos_skips_targets_without_classification(self):
        partial = {"codigo": "86922", "cst_ibs_cbs": "000", "c_class_trib": None}
        self.assertEqual(([], []), build_vinculos([(vr_product(), partial)], CTX, CATALOGS, TODAY))


if __name__ == "__main__":
    unittest.main()
