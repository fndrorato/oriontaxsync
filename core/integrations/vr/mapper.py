"""Conversão de produtos da VR (GET /v3/produtos) para o contrato da API OrionTax."""
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

from core.integrations.sysmo.mapper import REQUIRED_NON_EMPTY_FIELDS

ICMS_SCENARIO = "icmsConsumidorFinal"
_EAN_SIZES = (8, 12, 13, 14)


@dataclass(frozen=True)
class VrStoreContext:
    cnpj: str
    uf: str
    grupo_codigo: int
    grupo_nome: str
    regime: str


def digits(value) -> str:
    return "".join(ch for ch in str(value if value is not None else "") if ch.isdigit())


def build_store_context(cnpj: str, uf: str, grupos: List[dict]) -> VrStoreContext:
    normalized = digits(cnpj).zfill(14)
    for grupo in grupos or []:
        for loja in grupo.get("lojas") or []:
            if digits(loja.get("cnpj")).zfill(14) == normalized:
                return VrStoreContext(
                    cnpj=normalized,
                    uf=str(uf or "").strip().upper(),
                    grupo_codigo=grupo.get("codigo"),
                    grupo_nome=str(grupo.get("nome") or "").strip(),
                    regime=str(grupo.get("regimeTributario") or "").strip(),
                )
    raise ValueError(f"CNPJ {normalized} não encontrado em nenhum grupo econômico da VR")


def regime_block(cadastro: dict, regime: str) -> dict:
    key = "tributacaoLucroReal" if "REAL" in str(regime or "").upper() else "tributacaoLucroPresumido"
    return (cadastro or {}).get(key) or {}


def normalize_ean(value) -> str:
    text = digits(value)
    if not text:
        return ""
    for size in _EAN_SIZES:
        if len(text) <= size:
            return text.zfill(size)
    return text


def parse_percent(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("%").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"Percentual inválido: {value!r}")


def _parse_date(value) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.strptime(text, "%d/%m/%Y").date()


def pick_classificacao(items: List[dict], today: date) -> Optional[dict]:
    if not items:
        return None
    for item in items:
        start = _parse_date(item.get("dataInicioCst"))
        end = _parse_date(item.get("dataFimCst"))
        if (start is None or start <= today) and (end is None or today <= end):
            return item
    return items[0]


def _float(value) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _icms_cst(block: dict) -> Optional[int]:
    cst = digits(block.get("cst"))
    if cst:
        return int(cst)
    csosn = digits(block.get("csosn"))
    return int(csosn) if csosn else None


def find_uf_item(product: dict, uf: str) -> Optional[dict]:
    """Item de `aliquotas[]` da UF informada (comparação sem caixa/espaços)."""
    wanted = str(uf or "").strip().upper()
    return next((a for a in (product or {}).get("aliquotas") or []
                 if str(a.get("uf") or "").strip().upper() == wanted), None)


def find_group_item(product: dict, grupo_nome: str) -> Optional[dict]:
    """Item de `pisCofins[]` do grupo econômico informado (pelo nome, sem caixa/espaços)."""
    wanted = str(grupo_nome or "").strip().lower()
    return next((g for g in (product or {}).get("pisCofins") or []
                 if str(g.get("grupoEconomico") or "").strip().lower() == wanted), None)


def vr_product_to_api(product: dict, ctx: VrStoreContext, today: date) -> dict:
    codigo = str(product.get("codigo") if product.get("codigo") is not None else "").strip()
    label = codigo or "<sem código>"

    uf_item = find_uf_item(product, ctx.uf)
    if uf_item is None:
        raise ValueError(f"Produto {label}: sem alíquotas de ICMS para a UF {ctx.uf}")
    icms = uf_item.get(ICMS_SCENARIO) or {}

    group = find_group_item(product, ctx.grupo_nome)
    if group:
        debito = group.get("debito") or {}
        pis_cst = str(debito["cst"]).zfill(2) if debito.get("cst") not in (None, "") else None
        rates = regime_block(debito, ctx.regime)
        pis_aliquota = _float(rates.get("pis"))
        cofins_aliquota = _float(rates.get("cofins"))
        natureza = group.get("naturezaReceita") or 0
    else:
        pis_cst, pis_aliquota, cofins_aliquota, natureza = None, 0.0, 0.0, 0

    fiscal = product.get("classificacaoFiscal") or {}
    barras = product.get("codigosBarras") or []
    reducao = icms.get("percentualReducao")
    classif = pick_classificacao(product.get("classificacaoTributaria") or [], today)
    red_ibs = parse_percent(classif.get("percentualReducao")) if classif else None

    payload = {
        "sequencial": None,
        "codigo": codigo,
        "codigo_barras": normalize_ean(barras[0]) if barras else "",
        "descricao": str(product.get("descricao") or "").strip(),
        "ncm": digits(fiscal.get("ncm")),
        "cest": digits(fiscal.get("cest")),
        "cfop": None,
        "icms_cst": _icms_cst(icms),
        "icms_aliquota": _float(icms.get("percentual")),
        "percentual_redbcde": _float(reducao),
        "cbenef": str(icms.get("cBenef") or "").strip(),
        "protege": _float(icms.get("percentualFCP")),
        "pis_cst": pis_cst,
        "pis_aliquota": pis_aliquota,
        "cofins_aliquota": cofins_aliquota,
        "natureza_receita": natureza,
        "estado_origem": ctx.uf,
        "estado_destino": ctx.uf,
        "cst_ibs_cbs": classif.get("cst") if classif else None,
        "c_class_trib": classif.get("cClassTrib") if classif else None,
        "aliquota_ibs": None,
        "aliquota_cbs": None,
        "p_red_aliq_ibs": red_ibs,
        "p_red_aliq_cbs": red_ibs,
        "inf_ad_fisco": False,
    }
    missing = [f for f in REQUIRED_NON_EMPTY_FIELDS if payload.get(f) in (None, "")]
    if missing:
        raise ValueError(f"Produto {label}: campos obrigatórios: {', '.join(missing)}")
    return payload
