import unittest

from core.integrations.sysmo.mapper import api_product_to_sysmo, sysmo_row_to_api


class SysmoMapperTests(unittest.TestCase):
    def valid_row(self):
        return {
            "cd_produto": " 001 ", "tx_codigobarras": "0789", "tx_descricaoproduto": " Produto ",
            "tx_ncm": "01012100", "tx_cest": None, "nr_cfop": 5102, "nr_cst_icms": 0,
            "vl_aliquota_integral_icms": 18, "vl_aliquota_final_icms": 12.6,
            "vl_aliquota_fcp": 2, "tx_cbenef": None, "nr_cst_pis": "01",
            "vl_aliquota_pis": 1.65, "vl_aliquota_cofins": 7.6, "nr_naturezareceita": 101,
        }

    def test_maps_and_preserves_text_codes(self):
        payload = sysmo_row_to_api(self.valid_row())
        self.assertEqual("001", payload["codigo"])
        self.assertEqual("0789", payload["codigo_barras"])
        self.assertEqual("01012100", payload["ncm"])
        self.assertEqual(30.0, payload["percentual_redbcde"])
        self.assertIs(payload["inf_ad_fisco"], False)

    def test_rejects_missing_required_field(self):
        row = self.valid_row(); row["tx_descricaoproduto"] = None
        with self.assertRaisesRegex(ValueError, "descricao"):
            sysmo_row_to_api(row)

    def test_maps_api_product_to_target_tuple(self):
        row = api_product_to_sysmo({"codigo": "1", "descricao": "P", "pis_cst": "01"})
        self.assertEqual("1", row[1])
        self.assertEqual("01", row[12])
        self.assertEqual("01", row[14])
        self.assertEqual("S", row[-1])


if __name__ == "__main__":
    unittest.main()
