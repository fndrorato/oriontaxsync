"""Cliente HTTP da VR Integração Fiscal API, sem dependências HTTP externas."""
import http.client
import json
import logging
import time
from typing import Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .oriontax_api_client import OrionTaxApiClient


class VrApiError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class _NetworkError(VrApiError):
    """Falha de transporte (sem resposta HTTP); só GET é repetido."""


class VrApiClient:
    def __init__(self, config: Dict):
        self.base_url = str(config["base_url"]).strip().rstrip("/")
        self.token = config["token"]
        self.timeout = int(config.get("timeout_seconds", 60))
        self.max_retries = int(config.get("max_retries", 3))
        self.page_size = max(1, int(config.get("page_size", 500)))
        self.patch_batch_size = max(1, int(config.get("patch_batch_size", 50)))
        self.logger = logging.getLogger(__name__)
        self._jwt: Optional[str] = None

    # ----- transporte -----

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(seconds)

    def _send(self, method: str, url: str, body, headers: Dict) -> Tuple[int, object]:
        """Executa a requisição; devolve (status, payload) também para 4xx/5xx."""
        encoded = (
            json.dumps(body, ensure_ascii=False, default=OrionTaxApiClient._json_default).encode("utf-8")
            if body is not None else None
        )
        request = Request(url, data=encoded, headers=headers, method=method)
        try:
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    return response.status, self._decode(raw)
            except HTTPError as exc:
                return exc.code, self._decode(exc.read())
        except (OSError, http.client.HTTPException) as exc:
            # URLError, timeout, reset, IncompleteRead, RemoteDisconnected etc.
            raise _NetworkError(f"Falha de comunicação com a API VR: {exc}") from exc

    @staticmethod
    def _decode(raw: bytes):
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except ValueError:
            return text[:1000]

    @staticmethod
    def _build_query(query) -> str:
        pairs = []
        for key, value in (query or {}).items():
            if isinstance(value, bool):
                value = "true" if value else "false"
            pairs.append((key, value))
        return urlencode(pairs)

    def _request(self, method: str, path: str, body=None, query=None, auth: bool = True):
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{self._build_query(query)}"
        # POST/PATCH nunca são repetidos: uma resposta perdida poderia duplicar a gravação.
        allowed_retries = self.max_retries if method == "GET" else 0
        reauthenticated = False
        attempt = 0
        while True:
            headers = {"Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            if auth:
                if not self._jwt:
                    self.authenticate()
                headers["Authorization"] = f"Bearer {self._jwt}"
            try:
                status, payload = self._send(method, url, body, headers)
            except _NetworkError:
                if attempt < allowed_retries:
                    self._sleep(min(2 ** attempt, 8))
                    attempt += 1
                    continue
                raise
            if status == 401 and auth and not reauthenticated:
                # Token expirado: o servidor não processou a requisição, então é seguro repetir.
                reauthenticated = True
                self._jwt = None
                continue
            if status >= 400:
                if (status == 429 or status >= 500) and attempt < allowed_retries:
                    self._sleep(min(2 ** attempt, 8))
                    attempt += 1
                    continue
                raise VrApiError(f"API VR retornou HTTP {status}: {payload}", status)
            return status, payload

    # ----- helpers -----

    @staticmethod
    def _data(payload, key: str, expect=list):
        """Extrai a carga útil do envelope: `key`, senão `retorno`, senão vazio."""
        data = None
        if isinstance(payload, dict):
            data = payload.get(key)
            if data is None:
                data = payload.get("retorno")
        if data is None:
            data = expect()
        if not isinstance(data, expect):
            raise VrApiError(f"Resposta inválida da API VR: campo '{key}' não é {expect.__name__}.")
        return data

    def _get_list(self, path: str, key: str, query=None) -> List[dict]:
        _, payload = self._request("GET", path, query=query)
        return self._data(payload, key)

    # ----- endpoints -----

    def info(self) -> dict:
        _, payload = self._request("GET", "/info", auth=False)
        return payload if isinstance(payload, dict) else {}

    def authenticate(self) -> str:
        _, payload = self._request(
            "POST", "/auth", body={"auth": {"tokenVRMaster": self.token}}, auth=False
        )
        tokens = payload.get("retorno") if isinstance(payload, dict) else None
        if not isinstance(tokens, list) or not tokens or not tokens[0]:
            raise VrApiError("A API VR não devolveu o token de acesso.")
        self._jwt = str(tokens[0])
        return self._jwt

    def list_products(self, cnpj: str, cancel_check: Callable[[], bool] = None) -> List[dict]:
        products: List[dict] = []
        seen = set()
        page = 1
        previous = None
        while True:
            if cancel_check and cancel_check():
                raise VrApiError("Operação cancelada.")
            _, payload = self._request("GET", "/v3/produtos", query={
                "cnpj": cnpj, "usaPaginacao": True,
                "numeroPagina": page, "itensPorPagina": self.page_size,
            })
            items = self._data(payload, "produtos")
            fresh = []
            new_codes = 0
            codeless = 0
            for item in items:
                code = item.get("codigo") if isinstance(item, dict) else None
                if code is None:
                    fresh.append(item)
                    codeless += 1
                elif code not in seen:
                    seen.add(code)
                    fresh.append(item)
                    new_codes += 1
            fingerprint = json.dumps(items, sort_keys=True, default=str)
            # Continua com algum código inédito, ou com itens sem código em página
            # diferente da anterior. Página curta não encerra: o limite de
            # itensPorPagina do servidor é desconhecido. Páginas repetidas
            # (servidor que ignora a paginação) sempre encerram.
            if new_codes == 0 and not (codeless and fingerprint != previous):
                return products
            products.extend(fresh)
            previous = fingerprint
            page += 1

    def list_grupos_economicos(self) -> List[dict]:
        return self._get_list("/gruposeconomicos", "grupoEconomico")

    def list_icms(self, uf: str) -> List[dict]:
        return self._get_list("/icms", "icms", {"uf": uf})

    def list_piscofins(self) -> List[dict]:
        return self._get_list("/piscofins", "pisCofins")

    def list_pautas_fiscais(self, uf: str) -> List[dict]:
        return self._get_list("/pautasfiscais", "pautasFiscais", {"uf": uf})

    def list_classificacoes(self, cnpj: str) -> List[dict]:
        return self._get_list("/classificacaoTributaria", "retorno", {"cnpj": cnpj})

    def patch_integracao_fiscal(self, items: List[dict]) -> List[dict]:
        _, payload = self._request("PATCH", "/v2/integracaofiscal", body=items)
        return self._data(payload, "integracaoFiscal")

    def vincular_classificacao(self, body: dict) -> dict:
        _, payload = self._request("PATCH", "/classificacaoTributaria/vincular", body=body)
        return self._data(payload, "detalhes", expect=dict)
