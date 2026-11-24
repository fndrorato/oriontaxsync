"""Orquestra a integração VR (API HTTP) com a API OrionTax."""
import json
import os
from datetime import date
from typing import Callable, Dict, List, Optional

from core.api import OrionTaxApiClient
from core.api.vr_api_client import VrApiClient, VrApiError
from core.integrations.base import IntegrationAdapter, SyncResult
from core.integrations.lock import SyncLockRegistry

from .correction import CorrectionRejected, VrCatalogs, build_correction, build_vinculos
from .mapper import ICMS_SCENARIO, build_store_context, digits, find_uf_item, parse_percent, vr_product_to_api

_DETAILS_LIMIT = 100
_TOL = 0.001


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

    @classmethod
    def _warn_rejections(cls, callback, rejected: List[str], continuing: int):
        """Aviso de rejeições locais: contagem, as 20 primeiras e o restante resumido."""
        if not rejected:
            return
        cls._progress(
            callback,
            f"⚠ {len(rejected)} produto(s) rejeitado(s) localmente; "
            f"{continuing} produto(s) válido(s) continuarão."
        )
        for error in rejected[:20]:
            cls._progress(callback, f"⚠ {error}")
        if len(rejected) > 20:
            cls._progress(callback, f"⚠ ... e mais {len(rejected) - 20} rejeição(ões).")

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
            self._warn_rejections(progress_callback, rejected, len(products))
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
        with SyncLockRegistry.acquire(self.installation_id):
            # Tudo o que pode falhar na VR roda antes do GET da OrionTax, que muda o estado dos itens.
            try:
                uf = self._store_uf(cnpj)
                self._progress(progress_callback, "Conectando à API VR...")
                ctx = build_store_context(cnpj, uf, self.vr.list_grupos_economicos())
            except ValueError as exc:
                return SyncResult(False, str(exc))
            self._progress(
                progress_callback,
                f"Grupo econômico: {ctx.grupo_nome} (regime {ctx.regime}); UF da loja: {ctx.uf}.",
            )
            self._progress(progress_callback, "Lendo cadastros fiscais e produtos da VR...")
            catalogs = VrCatalogs(
                icms=self.vr.list_icms(ctx.uf),
                piscofins=self.vr.list_piscofins(),
                pautas=self.vr.list_pautas_fiscais(ctx.uf),
                classificacoes=self.vr.list_classificacoes(ctx.cnpj),
            )
            current_by_code = self._index_products(self.vr.list_products(ctx.cnpj, lambda: self._cancelled))

            self._progress(progress_callback, "Recebendo fotografia tributada da API OrionTax...")
            targets = self.api.receive_products()
            self._progress(progress_callback, f"{len(targets)} produto(s) recebido(s); montando correções...")

            items, pairs, rejected = [], [], []
            unchanged = 0
            for target in targets:
                code = str(target.get("codigo") if target.get("codigo") is not None else "").strip()
                current = current_by_code.get(str(int(code)) if code.isdigit() else code)
                try:
                    item = build_correction(current, target, ctx, catalogs)
                except CorrectionRejected as exc:
                    rejected.append(str(exc))
                    continue
                pairs.append((current, target))
                if item is None:
                    unchanged += 1
                else:
                    items.append(item)
            try:
                vinculos, vinculo_rejected = build_vinculos(pairs, ctx, catalogs, date.today())
            except ValueError as exc:
                return SyncResult(False, f"Classificação tributária inválida na VR: {exc}",
                                  details=self._receive_details(rejected, unchanged))
            rejected.extend(vinculo_rejected)
            self._warn_rejections(progress_callback, rejected, len(pairs))
            self._progress(progress_callback,
                           f"⚠ A correção vale para todas as lojas da UF {ctx.uf} e do grupo {ctx.grupo_nome}.")

            if self.dry_run:
                for item in items[:3]:
                    self._progress(progress_callback, f"[DRY-RUN] PATCH /v2/integracaofiscal: "
                                                      f"{json.dumps(item, ensure_ascii=False)}")
                if vinculos:
                    self._progress(progress_callback, f"[DRY-RUN] PATCH /classificacaoTributaria/vincular: "
                                                      f"{json.dumps(vinculos[0], ensure_ascii=False)}")
                return SyncResult(
                    True,
                    f"[DRY-RUN] {len(items)} correção(ões) e {len(vinculos)} vínculo(s) montados; "
                    f"nada foi gravado na VR.",
                    len(items), details=self._receive_details(rejected, unchanged),
                )
            return self._write_corrections(ctx, items, vinculos, rejected, unchanged, progress_callback)

    @staticmethod
    def _index_products(products: List[dict]) -> Dict[str, dict]:
        indexed = {}
        for product in products or []:
            code = str(product.get("codigo") if product.get("codigo") is not None else "").strip()
            if code:
                indexed[str(int(code)) if code.isdigit() else code] = product
        return indexed

    @staticmethod
    def _receive_details(rejected, unchanged, patch_status=None, patch_info=None,
                         vinculos=None, divergences=None) -> dict:
        return {
            "rejected_count": len(rejected),
            "rejected": rejected[:_DETAILS_LIMIT],
            "unchanged": unchanged,
            "patch_status": patch_status or {},
            "patch_info": (patch_info or [])[:_DETAILS_LIMIT],
            "vinculos": vinculos or [],
            "divergences": (divergences or [])[:_DETAILS_LIMIT],
        }

    @staticmethod
    def _is_success(status) -> bool:
        text = str(status or "").strip().upper()
        return "SUCESSO" in text or text == "OK"

    def _write_corrections(self, ctx, items, vinculos, rejected, unchanged, progress_callback) -> SyncResult:
        patch_status: Dict[str, int] = {}
        patch_info: List[dict] = []
        written: List[dict] = []
        failures = 0
        batch_size = self.vr.patch_batch_size
        total = (len(items) + batch_size - 1) // batch_size
        done = 0
        for offset in range(0, len(items), batch_size):
            batch = items[offset:offset + batch_size]
            number = offset // batch_size + 1
            if self._cancelled:
                return self._cancelled_result(done, written, rejected, unchanged, patch_status, patch_info)
            self._progress(progress_callback, f"Gravando lote {number}/{total} na VR...")
            try:
                response = self.vr.patch_integracao_fiscal(batch)
            except VrApiError as exc:
                return SyncResult(False, f"Erro ao gravar o lote {number}/{total} na VR: {exc}; "
                                         f"{done} lote(s) já gravado(s) na VR.", len(written),
                                  details=self._receive_details(rejected, unchanged, patch_status, patch_info))
            done += 1
            by_code = {}
            for result in response or []:
                if isinstance(result, dict) and digits(result.get("codigoProduto")):
                    by_code[int(digits(result.get("codigoProduto")))] = result
            for item in batch:
                result = by_code.get(item["codigoProduto"],
                                     {"codigoProduto": item["codigoProduto"], "status": "SEM RETORNO",
                                      "info": "Produto ausente no retorno da VR"})
                status = str(result.get("status") or "").strip() or "SEM STATUS"
                patch_status[status] = patch_status.get(status, 0) + 1
                if self._is_success(status):
                    written.append(item)
                else:
                    failures += 1
                    patch_info.append(result)

        if self._cancelled:
            return self._cancelled_result(done, written, rejected, unchanged, patch_status, patch_info)
        vinculo_details = []
        for body in vinculos:
            self._progress(progress_callback, f"Vinculando classificação tributária "
                                              f"{body['codigoClassificacaoTributaria']} na VR...")
            try:
                detalhes = self.vr.vincular_classificacao(body)
            except VrApiError as exc:
                failures += len(body.get("codigoProdutos") or [])
                vinculo_details.append({"codigoClassificacaoTributaria": body["codigoClassificacaoTributaria"],
                                        "erro": str(exc)})
                continue
            vinculo_details.append(detalhes)
            failures += len(detalhes.get("produtosNaoVinculados") or [])
            failures += len(detalhes.get("ncmsNaoVinculados") or [])

        divergences = []
        if written:
            self._progress(progress_callback, "Relendo produtos na VR para conferência...")
            reread = self._index_products(self.vr.list_products(ctx.cnpj))
            divergences = [d for d in (self._divergence(item, reread, ctx.uf) for item in written) if d]

        message = (f"{len(written)} produto(s) gravado(s) na VR, {unchanged} sem alteração, "
                   f"{len(rejected)} rejeitado(s).")
        if divergences:
            message += f" {len(divergences)} divergência(s) na releitura."
        return SyncResult(
            failures + len(divergences) == 0, message, len(written),
            details=self._receive_details(rejected, unchanged, patch_status, patch_info,
                                          vinculo_details, divergences),
        )

    def _cancelled_result(self, done, written, rejected, unchanged, patch_status, patch_info) -> SyncResult:
        return SyncResult(False, f"Operação cancelada; {done} lote(s) já gravado(s) na VR.", len(written),
                          details=self._receive_details(rejected, unchanged, patch_status, patch_info))

    @staticmethod
    def _divergence(item: dict, reread: Dict[str, dict], uf: str) -> Optional[str]:
        code = item["codigoProduto"]
        product = reread.get(str(code))
        if product is None:
            return f"Produto {code}: não encontrado na releitura"
        sent = item["aliquotas"][ICMS_SCENARIO]
        read = (find_uf_item(product, uf) or {}).get(ICMS_SCENARIO) or {}
        diffs = []

        def check(field, expected, got, same):
            if not same:
                diffs.append(f"{field} enviado {expected!r}, lido {got!r}")

        sent_ncm = item["classificacaoFiscal"]["ncm"]
        read_ncm = (product.get("classificacaoFiscal") or {}).get("ncm")
        check("NCM", sent_ncm, read_ncm, digits(sent_ncm) == digits(read_ncm))
        field = "cst" if digits(sent.get("cst")) else "csosn"
        check(field, sent.get(field), read.get(field), _same_code(sent.get(field), read.get(field)))
        check("percentual", sent.get("percentual"), read.get("percentual"),
              _same_percent(sent.get("percentual"), read.get("percentual")))
        return f"Produto {code}: " + "; ".join(diffs) if diffs else None

    def cancel(self):
        self._cancelled = True


def _same_code(a, b) -> bool:
    da, db = digits(a), digits(b)
    return (int(da) if da else None) == (int(db) if db else None)


def _same_percent(a, b) -> bool:
    try:
        pa, pb = parse_percent(a), parse_percent(b)
    except ValueError:
        return False
    return pa is not None and pb is not None and abs(pa - pb) <= _TOL
