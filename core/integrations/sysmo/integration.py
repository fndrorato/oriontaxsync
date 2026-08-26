"""Orquestra a integração Sysmo PostgreSQL com a API OrionTax."""
from core.api import OrionTaxApiClient
from core.integrations.base import IntegrationAdapter, SyncResult
from core.integrations.lock import SyncLockRegistry

from .mapper import sysmo_row_to_api
from .repository import SysmoRepository


class SysmoIntegration(IntegrationAdapter):
    erp_type = "sysmo"

    def __init__(self, sysmo_config: dict, api_config: dict, installation_id: str):
        self.repository = SysmoRepository(sysmo_config)
        self.api = OrionTaxApiClient(api_config)
        self.installation_id = installation_id

    @staticmethod
    def _progress(callback, message):
        if callback:
            callback(message)

    def send(self, cnpj: str, progress_callback=None) -> SyncResult:
        with SyncLockRegistry.acquire(self.installation_id):
            try:
                self._progress(progress_callback, "Conectando ao PostgreSQL da Sysmo...")
                rows = self.repository.read_products()
                self._progress(progress_callback, f"{len(rows)} produto(s) lido(s) da Sysmo.")
                products = [sysmo_row_to_api(row) for row in rows]
                batch_size = self.api.batch_size
                jobs = []
                for offset in range(0, len(products), batch_size):
                    batch = products[offset:offset + batch_size]
                    number = offset // batch_size + 1
                    total = (len(products) + batch_size - 1) // batch_size
                    self._progress(progress_callback, f"Enviando lote {number}/{total} ({len(batch)} produtos)...")
                    jobs.append(self.api.send_products(batch))
                return SyncResult(True, f"{len(products)} produto(s) aceito(s) pela API em {len(jobs)} lote(s).", len(products), jobs)
            finally:
                self.repository.close()

    def receive(self, cnpj: str, progress_callback=None) -> SyncResult:
        with SyncLockRegistry.acquire(self.installation_id):
            try:
                self._progress(progress_callback, "Recebendo fotografia tributada da API OrionTax...")
                products = self.api.receive_products()
                self._progress(progress_callback, f"{len(products)} produto(s) recebidos; validando destino Sysmo...")
                count = self.repository.replace_received_products(products)
                return SyncResult(True, f"{count} produto(s) gravado(s) na Sysmo.", count)
            finally:
                self.repository.close()

    def cancel(self):
        self.repository.cancel()
