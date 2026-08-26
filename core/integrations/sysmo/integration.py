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
                products = []
                rejected = []
                for row in rows:
                    try:
                        products.append(sysmo_row_to_api(row))
                    except ValueError as exc:
                        rejected.append(str(exc))
                if rejected:
                    self._progress(
                        progress_callback,
                        f"⚠ {len(rejected)} produto(s) rejeitado(s) localmente; "
                        f"{len(products)} produto(s) válido(s) continuarão."
                    )
                    for error in rejected[:20]:
                        self._progress(progress_callback, f"⚠ {error}")
                    if len(rejected) > 20:
                        self._progress(progress_callback, f"⚠ ... e mais {len(rejected) - 20} rejeição(ões).")
                if not products:
                    return SyncResult(
                        False, "Nenhum produto válido para envio.", 0,
                        details={"rejected_count": len(rejected), "rejected": rejected[:100]},
                    )
                batch_size = self.api.batch_size
                jobs = []
                for offset in range(0, len(products), batch_size):
                    batch = products[offset:offset + batch_size]
                    number = offset // batch_size + 1
                    total = (len(products) + batch_size - 1) // batch_size
                    self._progress(progress_callback, f"Enviando lote {number}/{total} ({len(batch)} produtos)...")
                    jobs.append(self.api.send_products(batch))
                message = f"{len(products)} produto(s) aceito(s) pela API em {len(jobs)} lote(s)."
                if rejected:
                    message += f" {len(rejected)} produto(s) não enviado(s) por dados obrigatórios ausentes."
                return SyncResult(
                    True, message, len(products), jobs,
                    details={"rejected_count": len(rejected), "rejected": rejected[:100]},
                )
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
