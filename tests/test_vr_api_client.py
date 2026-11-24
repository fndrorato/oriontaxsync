import http.client
import unittest
from unittest import mock

from core.api import vr_api_client

from core.api.vr_api_client import VrApiClient, VrApiError, _NetworkError


class FakeVr(VrApiClient):
    """Substitui o transporte de baixo nível; _request real cuida de auth/401/retry."""

    def __init__(self, responses, **config):
        base = {"base_url": "http://vr.test:9025", "token": "tok"}
        base.update(config)
        super().__init__(base)
        self.responses = iter(responses)
        self.calls = []
        self.sleeps = []

    def _send(self, method, url, body, headers):
        self.calls.append((method, url[len(self.base_url):], body, headers))
        return next(self.responses)

    def _sleep(self, seconds):
        self.sleeps.append(seconds)


class VrApiClientTests(unittest.TestCase):
    def test_authenticates_and_sends_bearer(self):
        api = FakeVr([(200, {"retorno": ["jwt1"]}), (200, {"produtos": []})])
        api.list_products("22881305000192")
        self.assertEqual(("POST", "/auth"), api.calls[0][:2])
        self.assertEqual({"auth": {"tokenVRMaster": "tok"}}, api.calls[0][2])
        self.assertEqual("Bearer jwt1", api.calls[1][3]["Authorization"])

    def test_reads_all_pages_until_empty_page(self):
        page = lambda codes: (200, {"produtos": [{"codigo": c} for c in codes]})
        api = FakeVr([(200, {"retorno": ["jwt"]}), page([1, 2]), page([3]), page([])], page_size=2)
        self.assertEqual([1, 2, 3], [p["codigo"] for p in api.list_products("1")])
        self.assertIn("numeroPagina=2", api.calls[2][1])
        self.assertIn("usaPaginacao=true", api.calls[2][1])
        self.assertIn("itensPorPagina=2", api.calls[2][1])

    def test_short_page_does_not_stop_reading(self):
        page = lambda codes: (200, {"produtos": [{"codigo": c} for c in codes]})
        api = FakeVr([(200, {"retorno": ["jwt"]}), page([1, 2]), page([3]), page([])], page_size=500)
        self.assertEqual([1, 2, 3], [p["codigo"] for p in api.list_products("1")])

    def test_codeless_items_continue_when_page_differs(self):
        page = lambda tags: (200, {"produtos": [{"x": t} for t in tags]})
        api = FakeVr([(200, {"retorno": ["jwt"]}), page("ab"), page("cd"), page("")], page_size=2)
        self.assertEqual(4, len(api.list_products("1")))

    def test_repeated_codeless_page_stops(self):
        same = (200, {"produtos": [{"x": 1}, {"x": 2}]})
        api = FakeVr([(200, {"retorno": ["jwt"]}), same, same, same], page_size=2)
        self.assertEqual(2, len(api.list_products("1")))
        self.assertEqual(3, len(api.calls))

    def test_stops_when_server_ignores_pagination(self):
        full = (200, {"produtos": [{"codigo": 1}, {"codigo": 2}]})
        api = FakeVr([(200, {"retorno": ["jwt"]}), full, full, full], page_size=2)
        self.assertEqual([1, 2], [p["codigo"] for p in api.list_products("1")])
        self.assertEqual(3, len(api.calls))

    def test_accepts_retorno_envelope(self):
        api = FakeVr([(200, {"retorno": ["jwt"]}), (200, {"retorno": [{"codigo": 9}]}),
                      (200, {"retorno": []})])
        self.assertEqual([{"codigo": 9}], api.list_products("1"))

    def test_cancel_check_stops_between_pages(self):
        full = (200, {"produtos": [{"codigo": 1}, {"codigo": 2}]})
        api = FakeVr([(200, {"retorno": ["jwt"]}), full, full], page_size=2)
        with self.assertRaisesRegex(VrApiError, "cancelada"):
            api.list_products("1", cancel_check=lambda: len(api.calls) >= 2)

    def test_reauthenticates_once_on_401(self):
        api = FakeVr([(200, {"retorno": ["old"]}), (401, None),
                      (200, {"retorno": ["new"]}), (200, {"produtos": []})])
        api.list_products("1")
        self.assertEqual("Bearer new", api.calls[-1][3]["Authorization"])

    def test_second_401_raises(self):
        api = FakeVr([(200, {"retorno": ["a"]}), (401, None), (200, {"retorno": ["b"]}), (401, None)])
        with self.assertRaisesRegex(VrApiError, "401"):
            api.list_grupos_economicos()

    def test_patch_is_not_retried_on_500(self):
        api = FakeVr([(200, {"retorno": ["jwt"]}), (500, {"info": "erro"})])
        with self.assertRaises(VrApiError):
            api.patch_integracao_fiscal([{"codigoProduto": 1}])
        self.assertEqual(2, len(api.calls))

    def test_json_error_detail_is_truncated(self):
        detail = {"info": "x" * 5000}
        api = FakeVr([(200, {"retorno": ["jwt"]}), (400, detail)])
        with self.assertRaises(VrApiError) as cm:
            api.patch_integracao_fiscal([{"codigoProduto": 1}])
        prefix = "API VR retornou HTTP 400: "
        self.assertTrue(str(cm.exception).startswith(prefix + '{"info": "xxx'))
        self.assertEqual(len(prefix) + 1000, len(str(cm.exception)))

    def test_patch_returns_item_results(self):
        api = FakeVr([(200, {"retorno": ["jwt"]}),
                      (200, {"integracaoFiscal": [{"codigoProduto": 1, "status": "OK", "info": "x"}]})])
        self.assertEqual("OK", api.patch_integracao_fiscal([{"codigoProduto": 1}])[0]["status"])
        self.assertEqual(("PATCH", "/v2/integracaofiscal"), api.calls[1][:2])

    def test_get_retries_on_5xx_with_backoff(self):
        api = FakeVr([(200, {"retorno": ["jwt"]}), (503, None), (429, None),
                      (200, {"pisCofins": [{"codigo": 1}]})])
        self.assertEqual([{"codigo": 1}], api.list_piscofins())
        self.assertEqual([1, 2], api.sleeps)

    def test_get_gives_up_after_max_retries(self):
        api = FakeVr([(200, {"retorno": ["jwt"]})] + [(500, {"info": "x"})] * 4, max_retries=2)
        with self.assertRaisesRegex(VrApiError, "500"):
            api.list_piscofins()
        self.assertEqual(4, len(api.calls))

    def test_get_retries_on_network_error_then_succeeds(self):
        class Flaky(FakeVr):
            def _send(self, *args):
                if not self.calls or self.calls[-1][0] == "POST":
                    if len(self.calls) == 1:
                        self.calls.append(("GET", "", None, {}))
                        raise _NetworkError("reset")
                return super()._send(*args)
        api = Flaky([(200, {"retorno": ["jwt"]}), (200, {"pisCofins": [{"codigo": 1}]})])
        self.assertEqual([{"codigo": 1}], api.list_piscofins())
        self.assertEqual([1], api.sleeps)

    def test_patch_network_error_is_not_retried(self):
        class Down(FakeVr):
            def _send(self, method, url, body, headers):
                if method == "PATCH":
                    self.calls.append((method, url, body, headers))
                    raise _NetworkError("reset")
                return super()._send(method, url, body, headers)
        api = Down([(200, {"retorno": ["jwt"]})])
        with self.assertRaises(VrApiError):
            api.patch_integracao_fiscal([{"codigoProduto": 1}])
        self.assertEqual(2, len(api.calls))
        self.assertEqual([], api.sleeps)

    def test_send_wraps_read_phase_errors(self):
        api = VrApiClient({"base_url": "http://vr.test", "token": "t"})
        for error in (ConnectionResetError("reset"), http.client.IncompleteRead(b"x"),
                      http.client.RemoteDisconnected("closed")):
            response = mock.MagicMock()
            response.__enter__.return_value.read.side_effect = error
            with mock.patch.object(vr_api_client, "urlopen", return_value=response):
                with self.assertRaises(_NetworkError):
                    api._send("GET", "http://vr.test/x", None, {})

    def test_info_does_not_authenticate(self):
        api = FakeVr([(200, {"servico": "vr"})])
        self.assertEqual({"servico": "vr"}, api.info())
        self.assertEqual([("GET", "/info")], [c[:2] for c in api.calls])
        self.assertNotIn("Authorization", api.calls[0][3])

    def test_lookup_endpoints_use_query_and_keys(self):
        api = FakeVr([(200, {"retorno": ["jwt"]}),
                      (200, {"icms": [{"codigo": 1}]}),
                      (200, {"pautasFiscais": [{"codigo": 2}]}),
                      (200, {"retorno": [{"codigo": 3}]}),
                      (200, {"grupoEconomico": [{"codigo": 4}]})])
        self.assertEqual([{"codigo": 1}], api.list_icms("SP"))
        self.assertEqual([{"codigo": 2}], api.list_pautas_fiscais("SP"))
        self.assertEqual([{"codigo": 3}], api.list_classificacoes("22881305000192"))
        self.assertEqual([{"codigo": 4}], api.list_grupos_economicos())
        self.assertEqual("/icms?uf=SP", api.calls[1][1])
        self.assertEqual("/pautasfiscais?uf=SP", api.calls[2][1])
        self.assertEqual("/classificacaoTributaria?cnpj=22881305000192", api.calls[3][1])

    def test_vincular_returns_detalhes(self):
        api = FakeVr([(200, {"retorno": ["jwt"]}), (200, {"detalhes": {"totalProdutos": 1}})])
        self.assertEqual({"totalProdutos": 1}, api.vincular_classificacao({"cnpj": "1"}))
        self.assertEqual(("PATCH", "/classificacaoTributaria/vincular"), api.calls[1][:2])

    def test_non_list_payload_raises(self):
        api = FakeVr([(200, {"retorno": ["jwt"]}), (200, {"icms": "x"})])
        with self.assertRaises(VrApiError):
            api.list_icms("SP")

    def test_auth_without_token_in_response_raises(self):
        api = FakeVr([(200, {"retorno": []})])
        with self.assertRaises(VrApiError):
            api.authenticate()


if __name__ == "__main__":
    unittest.main()
