"""Orquestra a integração VR (API HTTP) com a API OrionTax."""
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from core.api import OrionTaxApiClient
from core.api.vr_api_client import VrApiClient, VrApiError
from core.integrations.base import IntegrationAdapter, SyncResult
from core.integrations.lock import SyncLockRegistry

from .correction import CorrectionRejected, VrCatalogs, build_correction, build_vinculos
from .mapper import ICMS_SCENARIO, build_store_context, digits, find_uf_item, parse_percent, vr_product_to_api

_DETAILS_LIMIT = 100
_TOL = 0.001
GATE_OFF_MESSAGE = ("Gravação na VR desabilitada. Homologue com ORIONTAX_DRY_RUN=1 e habilite em "
                    "Configurar API VR.")


def format_cnpj(cnpj: str) -> str:
    d = digits(cnpj).zfill(14)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


class VrIntegration(IntegrationAdapter):
    erp_type = "vr"

    def __init__(self, vr_config: dict, api_config: dict, installation_id: str,
                 store_lookup: Callable[[str], Optional[dict]],
                 snapshot_dir=None, active_ufs: Optional[Callable[[], Set[str]]] = None):
        self.vr = VrApiClient(vr_config)
        self.api = OrionTaxApiClient(api_config)
        self.installation_id = installation_id
        self.store_lookup = store_lookup
        self.snapshot_dir = snapshot_dir
        self.active_ufs = active_ufs
        self.write_enabled = bool(vr_config.get("write_enabled"))
        self.dry_run = os.environ.get("ORIONTAX_DRY_RUN") == "1"
        self.only_codes = self._parse_allowlist(os.environ.get("ORIONTAX_VR_ONLY"))
        self._cancelled = False

    @staticmethod
    def _normalize_code(code) -> str:
        text = str(code if code is not None else "").strip()
        return str(int(text)) if text.isdigit() else text

    @classmethod
    def _parse_allowlist(cls, raw) -> Optional[Set[str]]:
        """Códigos de ORIONTAX_VR_ONLY (separados por vírgula); None quando não definido."""
        codes = {cls._normalize_code(c) for c in str(raw or "").split(",")} - {""}
        return codes or None

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
        cls._warn_lines(callback, rejected, "rejeição(ões)")

    @classmethod
    def _warn_lines(cls, callback, lines: List[str], noun: str, limit: int = 20):
        """Emite as primeiras `limit` linhas com ⚠ e resume o restante."""
        for line in lines[:limit]:
            cls._progress(callback, f"⚠ {line}")
        if len(lines) > limit:
            cls._progress(callback, f"⚠ ... e mais {len(lines) - limit} {noun}.")

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
            # Sem a trava liberada, nem chega a consumir a fotografia da OrionTax.
            if not self.write_enabled and not self.dry_run:
                return SyncResult(False, GATE_OFF_MESSAGE)
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
            self._warn_multi_uf(progress_callback, ctx.uf)
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
            # Daqui em diante a fotografia já foi consumida: nenhum produto ruim pode descartar o lote.
            self._save_snapshot(targets, ctx.cnpj, progress_callback)
            self._progress(progress_callback, f"{len(targets)} produto(s) recebido(s); montando correções...")

            items, pairs, rejected = [], [], []
            unchanged = 0
            skipped = 0
            for target in targets:
                if not isinstance(target, dict):
                    rejected.append("Produto <sem código>: item inválido na fotografia da OrionTax")
                    continue
                code = self._normalize_code(target.get("codigo"))
                if self.only_codes is not None and code not in self.only_codes:
                    skipped += 1
                    continue
                current = current_by_code.get(code)
                try:
                    item = build_correction(current, target, ctx, catalogs)
                except CorrectionRejected as exc:
                    rejected.append(str(exc))
                    continue
                except ValueError as exc:
                    rejected.append(f"Produto {code or '<sem código>'}: {exc}")
                    continue
                pairs.append((current, target))
                if item is None:
                    unchanged += 1
                else:
                    items.append(item)
            if self.only_codes is not None:
                self._progress(progress_callback, f"⚠ ORIONTAX_VR_ONLY ativo: {skipped} produto(s) fora da "
                                                  f"lista não serão gravados.")
            vinculos, vinculo_rejected = build_vinculos(pairs, ctx, catalogs, date.today())
            rejected.extend(vinculo_rejected)
            self._warn_rejections(progress_callback, rejected, len(pairs))
            self._progress(progress_callback,
                           f"⚠ ICMS e PIS/COFINS valem para todas as lojas da UF {ctx.uf} e do grupo "
                           f"{ctx.grupo_nome} ({ctx.lojas_no_grupo} loja(s) no grupo); "
                           f"NCM e CEST valem para todas as lojas.")

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
                    f"nada foi gravado na VR. Atenção: a fotografia da OrionTax foi consumida; "
                    f"peça o reenvio antes da gravação real.",
                    len(items), details=self._receive_details(rejected, unchanged, skipped=skipped),
                )
            return self._write_corrections(ctx, items, vinculos, rejected, unchanged, progress_callback,
                                           skipped)

    def _warn_multi_uf(self, callback, uf: str):
        if self.active_ufs is None:
            return
        ufs = sorted({str(u).strip().upper() for u in (self.active_ufs() or []) if u and str(u).strip()})
        if len(ufs) > 1:
            self._progress(callback, f"⚠ Há lojas ativas em mais de uma UF ({', '.join(ufs)}); "
                                     f"apenas a UF {uf} desta loja será corrigida nesta execução.")

    def _save_snapshot(self, targets, cnpj: str, callback):
        """Guarda a fotografia recebida da OrionTax; falha aqui só gera aviso."""
        if self.snapshot_dir is None:
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = Path(self.snapshot_dir) / f"receive-{stamp}-{cnpj}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(targets, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except (OSError, TypeError, ValueError) as exc:
            self._progress(callback, f"⚠ Não foi possível salvar a fotografia OrionTax em {path}: {exc}")
            return
        self._progress(callback, f"Fotografia OrionTax salva em {path}")

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
                         vinculos=None, divergences=None, skipped=0) -> dict:
        return {
            "skipped_allowlist": skipped,
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

    def _write_corrections(self, ctx, items, vinculos, rejected, unchanged, progress_callback,
                           skipped=0) -> SyncResult:
        patch_status: Dict[str, int] = {}
        patch_info: List[dict] = []
        written: List[dict] = []
        batch_size = self.vr.patch_batch_size
        total = (len(items) + batch_size - 1) // batch_size
        done = 0

        def partial(message):
            self._warn_patch_failures(progress_callback, patch_info)
            return SyncResult(False, message, len(written),
                              details=self._receive_details(rejected, unchanged, patch_status, patch_info,
                                                            skipped=skipped))

        for offset in range(0, len(items), batch_size):
            batch = items[offset:offset + batch_size]
            number = offset // batch_size + 1
            if self._cancelled:
                return partial(self._cancel_message(done))
            self._progress(progress_callback, f"Gravando lote {number}/{total} na VR...")
            try:
                response = self.vr.patch_integracao_fiscal(batch)
            except VrApiError as exc:
                return partial(f"Erro ao gravar o lote {number}/{total} na VR: {exc}; "
                               f"{done} lote(s) já gravado(s) na VR, lote {number} com estado "
                               f"desconhecido (confira no VRMaster).")
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
                    patch_info.append({**result, "status": status})
        self._warn_patch_failures(progress_callback, patch_info)
        if self._cancelled:
            return partial(self._cancel_message(done))

        vinculo_details, vinculo_failures, vinculo_lines = self._send_vinculos(vinculos, progress_callback)
        self._warn_lines(progress_callback, vinculo_lines, "falha(s) de vínculo")
        failures = len(patch_info) + vinculo_failures

        divergences = []
        reread_error = None
        if written:
            self._progress(progress_callback, "Relendo produtos na VR para conferência...")
            try:
                reread = self._index_products(self.vr.list_products(ctx.cnpj))
            except VrApiError as exc:
                reread_error = exc
            else:
                divergences = [d for d in (self._divergence(item, reread, ctx.uf) for item in written) if d]
                self._warn_lines(progress_callback, divergences, "divergência(s)")

        message = (f"{len(written)} produto(s) gravado(s) na VR, {unchanged} sem alteração, "
                   f"{len(rejected)} rejeitado(s).")
        if failures:
            message += f" {failures} falha(s) na gravação."
        if divergences:
            message += f" {len(divergences)} divergência(s) na releitura."
        if reread_error is not None:
            message += f" Não foi possível reler os produtos para conferência: {reread_error}."
        return SyncResult(
            failures + len(divergences) == 0 and reread_error is None, message, len(written),
            details=self._receive_details(rejected, unchanged, patch_status, patch_info,
                                          vinculo_details, divergences, skipped),
        )

    @classmethod
    def _warn_patch_failures(cls, callback, patch_info: List[dict]):
        lines = []
        for r in patch_info:
            line = f"Produto {r.get('codigoProduto')}: {r.get('status')}"
            info = str(r.get("info") or "").strip()
            lines.append(f"{line} – {info}" if info else line)
        cls._warn_lines(callback, lines, "falha(s)")

    def _send_vinculos(self, vinculos, progress_callback):
        """(detalhes de cada vínculo, quantidade de falhas, linhas de aviso)."""
        details, lines = [], []
        failures = 0
        for body in vinculos:
            codigo = body["codigoClassificacaoTributaria"]
            self._progress(progress_callback, f"Vinculando classificação tributária {codigo} na VR...")
            try:
                detalhes = self.vr.vincular_classificacao(body)
            except VrApiError as exc:
                failures += len(body.get("codigoProdutos") or [])
                details.append({"codigoClassificacaoTributaria": codigo, "erro": str(exc)})
                lines.append(f"Vínculo {codigo}: {exc}")
                continue
            details.append(detalhes)
            for produto in detalhes.get("produtosNaoVinculados") or []:
                failures += 1
                lines.append(f"Vínculo {codigo}: produto {produto.get('codigo')} não vinculado "
                             f"({produto.get('motivo') or 'sem motivo'})")
            for ncm in detalhes.get("ncmsNaoVinculados") or []:
                failures += 1
                lines.append(f"Vínculo {codigo}: NCM {ncm.get('ncm')} não vinculado "
                             f"({ncm.get('motivo') or 'sem motivo'})")
        return details, failures, lines

    @staticmethod
    def _cancel_message(done: int) -> str:
        return f"Operação cancelada; {done} lote(s) já gravado(s) na VR."

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
