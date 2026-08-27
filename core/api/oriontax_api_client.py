"""Cliente HTTP da API OrionTax V2, sem dependências HTTP externas."""
import json
import logging
import socket
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class OrionTaxApiError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class OrionTaxApiClient:
    def __init__(self, config: Dict):
        self.base_url = self.normalize_base_url(config["base_url"])
        self.token = config["token"]
        self.timeout = int(config.get("timeout_seconds", 60))
        self.max_retries = int(config.get("max_retries", 3))
        self.batch_size = max(1, int(config.get("batch_size", 500)))
        self.page_size = min(500, max(1, int(config.get("page_size", 500))))
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def normalize_base_url(url: str) -> str:
        """Aceita tanto a raiz do site quanto uma URL terminada em /api/v1|v2."""
        parts = urlsplit(str(url).strip().rstrip("/"))
        path = parts.path.rstrip("/")
        for suffix in ("/api/v2", "/api/v1", "/api"):
            if path.lower().endswith(suffix):
                path = path[:-len(suffix)]
                break
        return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")

    @staticmethod
    def _json_default(value):
        """Converte tipos nativos de drivers de banco para tipos JSON."""
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError(f"Decimal não finito não pode ser enviado em JSON: {value}")
            return int(value) if value == value.to_integral_value() else float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    def _request(self, method: str, path: str, body=None, query=None):
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query)}"
        encoded = (
            json.dumps(body, ensure_ascii=False, default=self._json_default).encode("utf-8")
            if body is not None else None
        )
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if encoded is not None:
            headers["Content-Type"] = "application/json"

        # POST não é repetido automaticamente: a API atual não oferece chave
        # idempotente e uma resposta perdida poderia duplicar o job.
        allowed_retries = self.max_retries if method == "GET" else 0
        for attempt in range(allowed_retries + 1):
            try:
                request = Request(url, data=encoded, headers=headers, method=method)
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    return response.status, json.loads(raw.decode("utf-8")) if raw else None
            except HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                retryable = exc.code == 429 or exc.code >= 500
                if retryable and attempt < allowed_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                try:
                    detail = json.loads(raw)
                except ValueError:
                    detail = raw[:1000]
                raise OrionTaxApiError(
                    f"API OrionTax retornou HTTP {exc.code}: {detail}", exc.code, retryable
                ) from exc
            except (URLError, socket.timeout, TimeoutError) as exc:
                if attempt < allowed_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise OrionTaxApiError(f"Falha de comunicação com a API OrionTax: {exc}", retryable=True) from exc

    def send_products(self, products: List[Dict]) -> str:
        if not isinstance(products, list) or not products:
            raise ValueError("O lote de produtos deve ser uma lista não vazia.")
        status, payload = self._request("POST", "/api/v2/enviar/", body=products)
        if status != 201 or not isinstance(payload, dict) or not payload.get("job_id"):
            raise OrionTaxApiError("Resposta inválida ao enviar produtos para a API OrionTax.", status)
        return str(payload["job_id"])

    def receive_products(self) -> List[Dict]:
        products = []
        page = 1
        while True:
            status, payload = self._request(
                "GET", "/api/v2/receber/", query={"page": page, "page_size": self.page_size}
            )
            if status != 200 or not isinstance(payload, dict):
                raise OrionTaxApiError("Resposta paginada inválida da API OrionTax.", status)
            results = payload.get("results")
            if not isinstance(results, list):
                raise OrionTaxApiError("Campo 'results' ausente ou inválido na API OrionTax.", status)
            products.extend(results)
            total_pages = int(payload.get("total_pages", 1))
            if page >= total_pages:
                break
            page += 1

        # O endpoint pode reenviar estados 2/3; a última ocorrência do código vence.
        deduplicated = {}
        for product in products:
            code = str(product.get("codigo", "")).strip()
            if not code:
                raise OrionTaxApiError("API retornou produto sem código.")
            deduplicated[code] = product
        return list(deduplicated.values())
