"""Orquestra a integração VR (API HTTP) com a API OrionTax."""
import os
from datetime import date
from typing import Callable, Optional

from core.api import OrionTaxApiClient
from core.api.vr_api_client import VrApiClient
from core.integrations.base import IntegrationAdapter, SyncResult
from core.integrations.lock import SyncLockRegistry

from .mapper import build_store_context, digits, vr_product_to_api


def format_cnpj(cnpj: str) -> str:
    d = digits(cnpj).zfill(14)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


class VrIntegration(IntegrationAdapter):
    erp_type = "vr"

    def __init__(self, vr_config: dict, api_config: dict, installation_id: str,
                 store_lookup: Callable[[str], Optional[dict]]):
        self.vr = VrApiClient(vr_config)
        self.api = OrionTaxApiClient(api_config)
        self.installation_id = installation_id
        self.store_lookup = store_lookup
        self.dry_run = os.environ.get("ORIONTAX_DRY_RUN") == "1"
        self._cancelled = False

    @staticmethod
    def _progress(callback, message):
        if callback:
            callback(message)

    def _store_uf(self, cnpj: str) -> str:
        cliente = self.store_lookup(cnpj)
        uf = ((cliente or {}).get("uf") or "").strip()
        if not uf:
            nome = (cliente or {}).get("nome") or format_cnpj(cnpj)
            raise ValueError(f"Informe a UF da loja {nome} no cadastro de clientes.")
        return uf

    def send(self, cnpj: str, progress_callback=None) -> SyncResult:
        with SyncLockRegistry.acquire(self.installation_id):
            try:
                uf = self._store_uf(cnpj)
                self._progress(progress_callback, "Conectando à API VR...")
                grupos = self.vr.list_grupos_economicos()
                ctx = build_store_context(cnpj, uf, grupos)
            except ValueError as exc:
                return SyncResult(False, str(exc))
            self._progress(
                progress_callback,
                f"Grupo econômico: {ctx.grupo_nome} (regime {ctx.regime}); UF da loja: {ctx.uf}.",
            )
            raw = self.vr.list_products(ctx.cnpj, lambda: self._cancelled)
            self._progress(progress_callback, f"{len(raw)} produto(s) lido(s) da VR.")
            products = []
            rejected = []
            today = date.today()
            for item in raw:
                try:
                    products.append(vr_product_to_api(item, ctx, today))
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
            total = (len(products) + batch_size - 1) // batch_size
            for offset in range(0, len(products), batch_size):
                batch = products[offset:offset + batch_size]
                number = offset // batch_size + 1
                self._progress(progress_callback, f"Enviando lote {number}/{total} ({len(batch)} produtos)...")
                jobs.append(self.api.send_products(batch))
            message = f"{len(products)} produto(s) aceito(s) pela API em {len(jobs)} lote(s)."
            if rejected:
                message += f" {len(rejected)} produto(s) não enviado(s) por dados obrigatórios ausentes."
            return SyncResult(
                True, message, len(products), jobs,
                details={"rejected_count": len(rejected), "rejected": rejected[:100]},
            )

    def receive(self, cnpj: str, progress_callback=None) -> SyncResult:
        raise NotImplementedError("Recebimento VR será implementado na Task 6.")

    def cancel(self):
        self._cancelled = True
