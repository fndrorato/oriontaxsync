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

    def test_missing_natureza_receita_keeps_current(self):
        prod = vr_product()
        prod["pisCofins"][1]["naturezaReceita"] = 101
        for empty in (None, ""):
            target = vr_product_to_api(prod, CTX, TODAY) | {"natureza_receita": empty}
            self.assertIsNone(build_correction(prod, target, CTX, CATALOGS))
            changed = target | {"icms_cst": 0, "percentual_redbcde": 0}
            saida = build_correction(prod, changed, CTX, CATALOGS)["pisCofins"]["pisCofinsSaida"]
            self.assertEqual(101, saida["naturezaReceita"])
            new_rates = target | {"pis_cst": "04", "pis_aliquota": 0, "cofins_aliquota": 0}
            saida = build_correction(prod, new_rates, CTX, CATALOGS)["pisCofins"]["pisCofinsSaida"]
            self.assertEqual((4, 101), (saida["idPisCofins"], saida["naturezaReceita"]))

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

    def test_pauta_with_mva_requires_unique_value_type(self):
        target = vr_product_to_api(with_pauta(), CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
        with self.assertRaisesRegex(CorrectionRejected, "Produto 86922: pauta fiscal sem tipoValor único .*19019000"):
            build_correction(with_pauta(), target, CTX, CATALOGS)
        conflicting = replace(CATALOGS, pautas=[{"ncm": "19019000", "tipoValor": "Percentual"},
                                                {"ncm": "1901.90.00", "tipoValor": "Absoluto"}])
        with self.assertRaisesRegex(CorrectionRejected, "tipoValor único"):
            build_correction(with_pauta(), target, CTX, conflicting)
        agreeing = replace(CATALOGS, pautas=[{"ncm": "19019000", "tipoValor": "Absoluto"},
                                             {"ncm": "1901.90.00", "tipoValor": "Absoluto"}])
        self.assertIs(False, build_correction(with_pauta(), target, CTX, agreeing)["pautaFiscal"]["valorPercentual"])

    def test_pauta_without_mva_defaults_value_type_to_false(self):
        prod = with_pauta()
        prod["aliquotas"][1]["pautaFiscal"].update(mva=0, mvaAjustada=0)
        target = vr_product_to_api(prod, CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
        self.assertIs(False, build_correction(prod, target, CTX, CATALOGS)["pautaFiscal"]["valorPercentual"])

    def test_icms_match_uses_aplica_reducao_fcp(self):
        base = {"cst": "00", "csosn": "", "percentual": 19, "percentualReducao": 0,
                "percentualDiferimento": 0, "percentualFCP": 2}
        catalogs = replace(CATALOGS, icms=[{**base, "codigo": 20, "aplicaReducaoFCP": False},
                                           {**base, "codigo": 21, "aplicaReducaoFCP": True}])
        prod = vr_product()
        prod["aliquotas"][1]["icmsConsumidorFinal"]["aplicaReducaoFCP"] = True
        target = vr_product_to_api(prod, CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
        cf = build_correction(prod, target, CTX, catalogs)["aliquotas"]["icmsConsumidorFinal"]
        self.assertEqual((21, True), (cf["idAliquota"], cf["aplicaReducaoFCP"]))

    def test_ambiguous_icms_cadastro(self):
        base = {"cst": "00", "csosn": "", "percentual": 19, "percentualReducao": 0,
                "percentualDiferimento": 0, "percentualFCP": 2}
        ambiguous = replace(CATALOGS, icms=[CATALOGS.icms[0], {**base, "codigo": 30, "aliquotaIcmsMonofasico": 0},
                                            {**base, "codigo": 31, "aliquotaIcmsMonofasico": 1.5}])
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
        with self.assertRaisesRegex(CorrectionRejected, "Produto 86922: cadastro de ICMS ambíguo em /icms"):
            build_correction(vr_product(), target, CTX, ambiguous)
        # cenário não alvo (icmsDebito 00/19%/FCP 2) ambíguo: só valores, sem idAliquota
        prod = vr_product()
        prod["aliquotas"][1]["icmsDebito"]["percentualFCP"] = 2
        target = vr_product_to_api(prod, CTX, TODAY) | {"ncm": "19019010"}
        item = build_correction(prod, target, CTX, ambiguous)
        self.assertNotIn("idAliquota", item["aliquotas"]["icmsDebito"])
        self.assertEqual(7, item["aliquotas"]["icmsConsumidorFinal"]["idAliquota"])
        self.assertIsNone(resolve_icms_id(base, ambiguous.icms))
        identical = replace(CATALOGS, icms=[{**base, "codigo": 30}, {**base, "codigo": 31}])
        self.assertEqual(30, resolve_icms_id(base, identical.icms))
        none_vs_zero = [{**base, "codigo": 30, "percentualDesonerado": None},
                        {**base, "codigo": 31, "percentualDesonerado": 0.0004}]
        self.assertEqual(30, resolve_icms_id(base, none_vs_zero))
        motivo = [{**base, "codigo": 30, "motivoDesoneracao": ""},
                  {**base, "codigo": 31, "motivoDesoneracao": "Outros"}]
        self.assertIsNone(resolve_icms_id(base, motivo))

    def test_duplicated_icms_cadastros_with_other_names_use_first(self):
        base = {"cst": "00", "csosn": "", "percentual": 19, "percentualReducao": 0,
                "percentualDiferimento": 0, "percentualFCP": 2}
        catalogs = replace(CATALOGS, icms=[{**base, "codigo": 40, "descricao": "19% FCP", "mensagem": "a"},
                                           {**base, "codigo": 41, "descricao": "ICMS 19 GO", "status": "ATIVO"}])
        target = vr_product_to_api(vr_product(), CTX, TODAY) | {"icms_cst": 0, "percentual_redbcde": 0}
        cf = build_correction(vr_product(), target, CTX, catalogs)["aliquotas"]["icmsConsumidorFinal"]
        self.assertEqual(40, cf["idAliquota"])


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

    def test_build_vinculos_rejects_only_product_with_malformed_date(self):
        t = lambda code: {"codigo": str(code), "cst_ibs_cbs": "000", "c_class_trib": "1"}
        bad = {**vr_product(), "codigo": 86923}
        bad["classificacaoTributaria"] = [{"cst": "200", "cClassTrib": "200003", "dataInicioCst": "2026-01-01"}]
        bodies, rejected = build_vinculos([(vr_product(), t(86922)), (bad, t(86923))], CTX, CATALOGS, TODAY)
        self.assertEqual([86922], bodies[0]["codigoProdutos"])
        self.assertEqual(1, len(rejected))
        self.assertTrue(rejected[0].startswith("Produto 86923: "), rejected[0])

    def test_build_vinculos_rejects_catalog_classification_without_codigo(self):
        catalogs = replace(CATALOGS, classificacoes=[{"cst": "000", "cClassTrib": "000001"}])
        t = {"codigo": "86922", "cst_ibs_cbs": "000", "c_class_trib": "1"}
        bodies, rejected = build_vinculos([(vr_product(), t)], CTX, catalogs, TODAY)
        self.assertEqual([], bodies)
        self.assertEqual(1, len(rejected))
        self.assertTrue(rejected[0].startswith("Produto 86922: "), rejected[0])


if __name__ == "__main__":
    unittest.main()
