import unittest
from datetime import date

from core.integrations.vr.mapper import (
    VrStoreContext, build_store_context, normalize_ean, parse_percent,
    pick_classificacao, regime_block, vr_product_to_api,
)

CTX = VrStoreContext("01234567000195", "GO", 1, "Lojas Serve Bem", "LUCRO REAL")
TODAY = date(2026, 11, 24)


def vr_product():
    return {
        "codigo": 86922,
        "descricao": " Desinfetante ",
        "codigosBarras": [789123456789],
        "classificacaoFiscal": {"ncm": "1901.90.00", "cest": "17.004.00", "exTIPI": 0},
        "aliquotas": [
            {"uf": "SP",
             "icmsConsumidorFinal": {"cst": "00", "csosn": "", "percentual": 18,
                                     "percentualReducao": 0, "percentualFCP": 0, "cBenef": ""},
             "icmsDebito": {"cst": "00", "percentual": 18}},
            {"uf": "GO",
             "icmsConsumidorFinal": {"cst": "20", "csosn": "", "percentual": 19,
                                     "percentualReducao": 26.32, "percentualFCP": 2,
                                     "cBenef": "GO821001"},
             "icmsDebito": {"cst": "00", "percentual": 19}},
        ],
        "pisCofins": [
            {"grupoEconomico": "Outro", "naturezaReceita": 5,
             "debito": {"codigo": 4, "cst": 4,
                        "tributacaoLucroReal": {"pis": 0, "cofins": 0},
                        "tributacaoLucroPresumido": {"pis": 0, "cofins": 0}},
             "credito": {"codigo": 8, "cst": 70,
                         "tributacaoLucroReal": {"pis": 0, "cofins": 0, "reducao": 0}}},
            {"grupoEconomico": "Lojas Serve Bem", "naturezaReceita": 0,
             "debito": {"codigo": 3, "cst": 1,
                        "tributacaoLucroReal": {"pis": 1.65, "cofins": 7.6},
                        "tributacaoLucroPresumido": {"pis": 0.65, "cofins": 3}},
             "credito": {"codigo": 9, "cst": 50,
                         "tributacaoLucroReal": {"pis": 1.65, "cofins": 7.6, "reducao": 0}}},
        ],
        "classificacaoTributaria": [
            {"cst": "000", "cClassTrib": "000001", "percentualReducao": "0%",
             "dataInicioCst": "01/01/2025", "dataFimCst": "31/12/2025"},
            {"cst": "200", "cClassTrib": "200003", "percentualReducao": "60%",
             "dataInicioCst": "01/01/2026", "dataFimCst": ""},
        ],
    }


class VrMapperTests(unittest.TestCase):
    def test_store_context_matches_cnpj_with_leading_zero(self):
        grupos = [{"codigo": 7, "nome": "Lojas Serve Bem", "regimeTributario": "LUCRO REAL",
                   "lojas": [{"cnpj": 1234567000195}]}]
        ctx = build_store_context("01.234.567/0001-95", "go", grupos)
        self.assertEqual(("01234567000195", "GO", 7, "LUCRO REAL"),
                         (ctx.cnpj, ctx.uf, ctx.grupo_codigo, ctx.regime))

    def test_store_context_rejects_unknown_cnpj(self):
        with self.assertRaisesRegex(ValueError, "grupo econômico"):
            build_store_context("11111111000111", "GO", [{"codigo": 1, "nome": "X", "lojas": []}])

    def test_maps_identification_and_classification(self):
        p = vr_product_to_api(vr_product(), CTX, TODAY)
        self.assertEqual("86922", p["codigo"])
        self.assertEqual("Desinfetante", p["descricao"])
        self.assertEqual("789123456789", p["codigo_barras"])  # 12 dígitos já é tamanho válido (UPC-A)
        self.assertEqual("19019000", p["ncm"])
        self.assertEqual("1700400", p["cest"])
        self.assertIsNone(p["cfop"])
        self.assertIsNone(p["sequencial"])
        self.assertEqual(("GO", "GO"), (p["estado_origem"], p["estado_destino"]))

    def test_maps_icms_from_consumer_scenario_of_store_uf(self):
        p = vr_product_to_api(vr_product(), CTX, TODAY)
        self.assertEqual((20, 19.0, 26.32, 2.0, "GO821001"),
                         (p["icms_cst"], p["icms_aliquota"], p["percentual_redbcde"],
                          p["protege"], p["cbenef"]))

    def test_uses_csosn_when_cst_is_empty(self):
        prod = vr_product()
        prod["aliquotas"][1]["icmsConsumidorFinal"].update(cst="", csosn="102")
        self.assertEqual(102, vr_product_to_api(prod, CTX, TODAY)["icms_cst"])

    def test_rejects_product_without_store_uf(self):
        prod = vr_product()
        prod["aliquotas"] = prod["aliquotas"][:1]
        with self.assertRaisesRegex(ValueError, "Produto 86922: .*UF GO"):
            vr_product_to_api(prod, CTX, TODAY)

    def test_maps_pis_cofins_of_store_group_and_regime(self):
        p = vr_product_to_api(vr_product(), CTX, TODAY)
        self.assertEqual(("01", 1.65, 7.6, 0),
                         (p["pis_cst"], p["pis_aliquota"], p["cofins_aliquota"], p["natureza_receita"]))
        presumido = VrStoreContext(CTX.cnpj, "GO", 1, "Lojas Serve Bem", "LUCRO PRESUMIDO")
        self.assertEqual(0.65, vr_product_to_api(vr_product(), presumido, TODAY)["pis_aliquota"])

    def test_missing_group_pis_sends_nulls(self):
        prod = vr_product()
        prod["pisCofins"] = []
        p = vr_product_to_api(prod, CTX, TODAY)
        self.assertIsNone(p["pis_cst"])
        self.assertEqual(0.0, p["pis_aliquota"])
        self.assertEqual(0, p["natureza_receita"])

    def test_maps_current_ibs_cbs_classification(self):
        p = vr_product_to_api(vr_product(), CTX, TODAY)
        self.assertEqual(("200", "200003", 60.0, 60.0),
                         (p["cst_ibs_cbs"], p["c_class_trib"], p["p_red_aliq_ibs"], p["p_red_aliq_cbs"]))
        self.assertIsNone(p["aliquota_ibs"])
        self.assertIsNone(p["aliquota_cbs"])
        self.assertIs(False, p["inf_ad_fisco"])

    def test_normalize_ean_and_parse_percent(self):
        self.assertEqual("00001234", normalize_ean(1234))
        self.assertEqual("7891234567895", normalize_ean(7891234567895))
        self.assertEqual("078912345678", normalize_ean(78912345678))
        self.assertEqual("", normalize_ean(None))
        self.assertEqual(12.5, parse_percent("12,5%"))
        self.assertEqual(60.0, parse_percent("60%"))
        self.assertIsNone(parse_percent(""))
        self.assertEqual(3.0, parse_percent(3))

    def test_rejects_missing_ncm(self):
        prod = vr_product()
        prod["classificacaoFiscal"]["ncm"] = ""
        with self.assertRaisesRegex(ValueError, "ncm"):
            vr_product_to_api(prod, CTX, TODAY)

    def test_pick_classificacao_by_date(self):
        items = vr_product()["classificacaoTributaria"]
        self.assertEqual("200", pick_classificacao(items, TODAY)["cst"])
        self.assertEqual("000", pick_classificacao(items, date(2025, 6, 1))["cst"])
        self.assertEqual("000", pick_classificacao(items, date(2024, 1, 1))["cst"])
        self.assertIsNone(pick_classificacao([], TODAY))

    def test_regime_block(self):
        d = {"tributacaoLucroReal": {"pis": 1}, "tributacaoLucroPresumido": {"pis": 2}}
        self.assertEqual({"pis": 1}, regime_block(d, "LUCRO REAL"))
        self.assertEqual({"pis": 2}, regime_block(d, "LUCRO PRESUMIDO"))
        self.assertEqual({}, regime_block({}, "LUCRO REAL"))


if __name__ == "__main__":
    unittest.main()
