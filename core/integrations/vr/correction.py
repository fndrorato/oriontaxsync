"""Montagem das correções fiscais (OrionTax → PATCH /v2/integracaofiscal e /classificacaoTributaria/vincular).

Funções puras, sem I/O. Na dúvida, rejeitar: um item errado grava tributação errada em todas as
lojas da UF/grupo. O item sai sempre completo, porque campos omitidos no PATCH podem ser zerados.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from core.integrations.vr.mapper import (
    ICMS_SCENARIO, VrStoreContext, digits, find_group_item, find_uf_item,
    parse_percent, pick_classificacao, regime_block,
)

ICMS_SCENARIOS = ("icmsDebito", "icmsCredito", "icmsDebitoInterestadual",
                  "icmsCreditoInterestadual", "icmsConsumidorFinal", "icmsBeneficioGoias")
PAUTA_ICMS = ("icmsDebito", "icmsCredito", "icmsInterestadual")
_ICMS_KEYS = ("cst", "csosn", "percentual", "percentualReducao", "percentualDiferimento",
              "percentualFCP", "aplicaReducaoFCP", "cBenef")
_ICMS_MATCH_CODES = ("cst", "csosn")
_ICMS_MATCH_NUMBERS = ("percentual", "percentualReducao", "percentualDiferimento", "percentualFCP")
_ICMS_IMPOSED_NUMBERS = ("aliquotaIcmsMonofasico", "percentualDesonerado", "percentualIcmsConsumidor")
_PAUTA_KEYS = ("mva", "mvaAjustada", "percentualProdepe", "recolheIcmsAntecipadamente")
_TOL = 0.001
OBSERVACAO = "OrionTax Sync"


class CorrectionRejected(ValueError):
    """Correção recusada. Mensagem: "Produto <codigo>: <motivo>" (sem código, só o motivo)."""

    def __init__(self, motivo: str, codigo=None):
        self.motivo = motivo
        self.codigo = codigo
        super().__init__(f"Produto {codigo}: {motivo}" if codigo not in (None, "") else motivo)


@dataclass
class VrCatalogs:
    icms: List[dict] = field(default_factory=list)
    piscofins: List[dict] = field(default_factory=list)
    pautas: List[dict] = field(default_factory=list)
    classificacoes: List[dict] = field(default_factory=list)


def _num(value) -> float:
    try:
        number = parse_percent(value)
    except ValueError as exc:
        raise CorrectionRejected(str(exc))
    return 0.0 if number is None else number


def _code(value) -> str:
    text = digits(value)
    return str(int(text)) if text else ""


def _same_num(a, b) -> bool:
    return abs(_num(a) - _num(b)) <= _TOL


def format_ncm(value) -> str:
    text = digits(value)
    if len(text) != 8:
        raise CorrectionRejected(f"NCM inválido ({value!r}): precisa ter 8 dígitos")
    return f"{text[:4]}.{text[4:6]}.{text[6:]}"


def format_cest(value) -> str:
    text = digits(value)
    if not text:
        return ""
    if len(text) != 7:
        raise CorrectionRejected(f"CEST inválido ({value!r}): precisa ter 7 dígitos")
    return f"{text[:2]}.{text[2:5]}.{text[5:]}"


def _icms_matches(values: dict, catalog: List[dict]) -> List[dict]:
    """Cadastros ativos com mesmos códigos, percentuais e (quando os dois têm) aplicaReducaoFCP."""
    found = []
    for cadastro in catalog or []:
        if str(cadastro.get("status") or "").strip().upper() == "INATIVO":
            continue
        if not all(_code(values.get(k)) == _code(cadastro.get(k)) for k in _ICMS_MATCH_CODES):
            continue
        if not all(_same_num(values.get(k), cadastro.get(k)) for k in _ICMS_MATCH_NUMBERS):
            continue
        if values.get("aplicaReducaoFCP") is not None and cadastro.get("aplicaReducaoFCP") is not None \
                and bool(values["aplicaReducaoFCP"]) != bool(cadastro["aplicaReducaoFCP"]):
            continue
        found.append(cadastro)
    return found


def _same_imposed(a: dict, b: dict) -> bool:
    """Campos fiscais que o cadastro impõe ao produto via idAliquota (nome, mensagem e status não contam)."""
    return (bool(a.get("aplicaReducaoFCP")) == bool(b.get("aplicaReducaoFCP"))
            and all(_same_num(a.get(k), b.get(k)) for k in _ICMS_IMPOSED_NUMBERS)
            and str(a.get("motivoDesoneracao") or "").strip() == str(b.get("motivoDesoneracao") or "").strip())


def _resolve_icms(values: dict, catalog: List[dict]) -> Tuple[Optional[dict], bool]:
    """(cadastro, ambíguo). Vários candidatos: ambíguo se diferem num campo fiscal que o cadastro impõe."""
    found = _icms_matches(values, catalog)
    if not found:
        return None, False
    if any(not _same_imposed(c, found[0]) for c in found[1:]):
        return None, True
    return found[0], False


def resolve_icms_id(values: dict, catalog: List[dict]) -> Optional[int]:
    """`codigo` do cadastro compatível; None se não houver ou se for ambíguo."""
    cadastro, _ = _resolve_icms(values, catalog)
    return cadastro.get("codigo") if cadastro else None


def _is_saida(cadastro: dict) -> bool:
    tipo = str(cadastro.get("tipoOperacao") or "").strip().upper()
    return tipo.startswith("S") or "DEB" in tipo or "DÉB" in tipo


def _find_piscofins(cst: int, pis, cofins, regime: str, catalog: List[dict]) -> Optional[dict]:
    for cadastro in catalog or []:
        if not _is_saida(cadastro) or _code(cadastro.get("cst")) != _code(cst):
            continue
        rates = regime_block(cadastro, regime)
        if rates and _same_num(rates.get("pis"), pis) and _same_num(rates.get("cofins"), cofins):
            return cadastro
    return None


def resolve_piscofins_id(cst: int, pis: float, cofins: float, regime: str,
                         catalog: List[dict]) -> Optional[int]:
    cadastro = _find_piscofins(cst, pis, cofins, regime, catalog)
    return cadastro.get("codigo") if cadastro else None


def _icms_block(source: dict, catalog: List[dict], required: bool = False) -> dict:
    block = {k: source[k] for k in _ICMS_KEYS if k in source}
    block.setdefault("cst", "")
    block.setdefault("csosn", "")
    block.setdefault("cBenef", "")
    for key in _ICMS_MATCH_NUMBERS:
        block[key] = _num(block.get(key))
    cadastro, ambiguous = _resolve_icms(block, catalog)
    if required and ambiguous:
        code = block["cst"] or block["csosn"]
        raise CorrectionRejected(f"cadastro de ICMS ambíguo em /icms (CST {code}, {block['percentual']:g}%): "
                                 f"mais de um cadastro compatível e diferentes entre si; ajuste no VRMaster")
    if required and cadastro is None:
        code = block["cst"] or block["csosn"]
        raise CorrectionRejected(f"sem cadastro de ICMS compatível em /icms "
                                 f"(CST {code}, {block['percentual']:g}%); crie no VRMaster")
    if cadastro is not None:
        block["idAliquota"] = cadastro.get("codigo")
        if cadastro.get("aliquotaIcmsMonofasico") is not None:
            block["aliquotaMonofasico"] = cadastro["aliquotaIcmsMonofasico"]
    return block


def _target_consumer_icms(current: dict, target: dict) -> dict:
    """Valores de icmsConsumidorFinal do alvo, sobre os campos atuais que o alvo não informa."""
    code = digits(target.get("icms_cst"))
    if not code:
        raise CorrectionRejected("CST/CSOSN de ICMS ausente no alvo")
    aliquota = _num(target.get("icms_aliquota"))
    if target.get("percentual_redbcde") is not None:
        reducao = _num(target["percentual_redbcde"])
    else:
        reduzida = _num(target.get("icms_aliquota_reduzida"))
        reducao = round((1 - reduzida / aliquota) * 100, 2) if aliquota > 0 and reduzida > 0 else 0
    values = {k: current[k] for k in _ICMS_KEYS if k in current}
    if int(code) >= 100:
        values.update(cst="", csosn=str(int(code)))
    else:
        values.update(cst=str(int(code)).zfill(2), csosn="")
    values.update(percentual=aliquota, percentualReducao=reducao,
                  percentualFCP=_num(target.get("protege")),
                  cBenef=str(target.get("cbenef") or "").strip())
    return values


def _same_icms(a: dict, b: dict) -> bool:
    return (_code(a.get("cst")) == _code(b.get("cst")) and _code(a.get("csosn")) == _code(b.get("csosn"))
            and all(_same_num(a.get(k), b.get(k)) for k in ("percentual", "percentualReducao", "percentualFCP"))
            and str(a.get("cBenef") or "").strip() == str(b.get("cBenef") or "").strip())


def _piscofins_block(cadastro: dict, regime: str, natureza, codigo=None) -> dict:
    rates = regime_block(cadastro, regime)
    return {
        "idPisCofins": cadastro.get("codigo") if codigo is None else codigo,
        "cst": int(_code(cadastro.get("cst")) or 0),
        "pis": _num(rates.get("pis")),
        "cofins": _num(rates.get("cofins")),
        "csa": rates.get("csa") or 0,
        "percentualReducao": _num(rates.get("reducao")),
        "naturezaReceita": natureza or 0,
        "tipoCreditoTributado": cadastro.get("tipoCreditoTributado") or 0,
        "tipoCreditoNaoTributado": cadastro.get("tipoCreditoNaoTributado") or 0,
    }


def _target_saida(group: dict, target: dict, ctx: VrStoreContext, catalogs: VrCatalogs) -> dict:
    debito = group.get("debito") or {}
    current = _piscofins_block(debito, ctx.regime, group.get("naturezaReceita"))
    if target.get("pis_cst") in (None, ""):
        return current
    cst = int(_code(target["pis_cst"]) or 0)
    pis, cofins = _num(target.get("pis_aliquota")), _num(target.get("cofins_aliquota"))
    natureza = target.get("natureza_receita")
    if natureza in (None, ""):  # alvo sem natureza: mantém a atual da VR
        natureza = current["naturezaReceita"]
    if debito.get("codigo") is not None and cst == current["cst"] and \
            _same_num(pis, current["pis"]) and _same_num(cofins, current["cofins"]):
        return {**current, "naturezaReceita": natureza}
    cadastro = _find_piscofins(cst, pis, cofins, ctx.regime, catalogs.piscofins)
    if cadastro is None:
        raise CorrectionRejected(f"sem cadastro de PIS/COFINS de saída compatível em /piscofins "
                                 f"(CST {cst}, PIS {pis:g}%, COFINS {cofins:g}%); crie no VRMaster")
    return {**_piscofins_block(cadastro, ctx.regime, natureza), "pis": pis, "cofins": cofins}


def _same_saida(a: dict, b: dict) -> bool:
    return (a["cst"] == b["cst"] and _same_num(a["pis"], b["pis"]) and _same_num(a["cofins"], b["cofins"])
            and _same_num(a["naturezaReceita"], b["naturezaReceita"]))


def _pauta(current_pauta: dict, ncm, catalogs: VrCatalogs) -> dict:
    pauta = {k: current_pauta[k] for k in _PAUTA_KEYS if k in current_pauta}
    tipos = {str(p.get("tipoValor") or "").strip()
             for p in catalogs.pautas or [] if digits(p.get("ncm")) == digits(ncm)}
    if len(tipos) == 1 and "" not in tipos:
        pauta["valorPercentual"] = tipos.pop() == "Percentual"
    elif _num(current_pauta.get("mva")) == 0 and _num(current_pauta.get("mvaAjustada")) == 0:
        pauta["valorPercentual"] = False  # sem MVA, o tipo de valor não altera o cálculo
    else:
        raise CorrectionRejected(f"pauta fiscal sem tipoValor único em /pautasfiscais para o NCM {digits(ncm)}")
    for key in PAUTA_ICMS:
        if current_pauta.get(key):
            pauta[key] = _icms_block(current_pauta[key], catalogs.icms)
    return pauta


def build_correction(current: Optional[dict], target: dict, ctx: VrStoreContext,
                     catalogs: VrCatalogs) -> Optional[dict]:
    label = str(target.get("codigo") if target.get("codigo") is not None else "").strip() or "<sem código>"
    try:
        return _build_correction(current, target, ctx, catalogs, label)
    except CorrectionRejected as exc:
        if exc.codigo is not None:
            raise
        raise CorrectionRejected(exc.motivo, label) from None


def _build_correction(current, target, ctx, catalogs, label) -> Optional[dict]:
    if current is None:
        raise CorrectionRejected("não encontrado ou inativo na loja VR")
    if not label.isdigit():
        raise CorrectionRejected("código não numérico")
    if digits(current.get("codigo")) == "" or int(label) != int(digits(current.get("codigo"))):
        raise CorrectionRejected(f"código diferente do produto lido na VR ({current.get('codigo')!r})")
    uf_item = find_uf_item(current, ctx.uf)
    if uf_item is None:
        raise CorrectionRejected(f"sem alíquotas de ICMS para a UF {ctx.uf} na VR")
    group = find_group_item(current, ctx.grupo_nome)
    if group is None:
        raise CorrectionRejected(f"sem PIS/COFINS do grupo econômico {ctx.grupo_nome} na VR")
    if not group.get("credito") or not group.get("debito"):
        raise CorrectionRejected(f"PIS/COFINS do grupo {ctx.grupo_nome} sem cadastro de entrada ou saída")

    fiscal = current.get("classificacaoFiscal") or {}
    current_cf = uf_item.get(ICMS_SCENARIO) or {}
    target_cf = _target_consumer_icms(current_cf, target)
    saida = _target_saida(group, target, ctx, catalogs)
    current_saida = _piscofins_block(group["debito"], ctx.regime, group.get("naturezaReceita"))
    if (digits(target.get("ncm")) == digits(fiscal.get("ncm"))
            and digits(target.get("cest")) == digits(fiscal.get("cest"))
            and _same_icms(target_cf, current_cf) and _same_saida(saida, current_saida)):
        return None

    aliquotas: Dict[str, dict] = {}
    for scenario in ICMS_SCENARIOS:
        if scenario == ICMS_SCENARIO:
            aliquotas[scenario] = _icms_block(target_cf, catalogs.icms, required=True)
        elif uf_item.get(scenario):
            aliquotas[scenario] = _icms_block(uf_item[scenario], catalogs.icms)

    item = {
        "codigoProduto": int(digits(current["codigo"])),
        "estados": [ctx.uf],
        "gruposEconomicos": [ctx.grupo_codigo],
        "classificacaoFiscal": {"ncm": format_ncm(target.get("ncm")),
                                "cest": format_cest(target.get("cest")),
                                "exTIPI": fiscal.get("exTIPI") or 0},
        "aliquotas": aliquotas,
        "pisCofins": {
            "pisCofinsEntrada": _piscofins_block(group["credito"], ctx.regime, group.get("naturezaReceita")),
            "pisCofinsSaida": saida,
        },
    }
    if uf_item.get("pautaFiscal"):
        item["pautaFiscal"] = _pauta(uf_item["pautaFiscal"], fiscal.get("ncm"), catalogs)
    return item


def _vinculo_for(current: dict, target: dict, catalogs: VrCatalogs,
                 today: date) -> Optional[Tuple[int, int]]:
    """(código da classificação, código do produto); None se não há o que vincular.

    Levanta CorrectionRejected (mensagem "Produto <codigo>: ...") para rejeitar o produto.
    """
    if target.get("cst_ibs_cbs") in (None, "") or target.get("c_class_trib") in (None, ""):
        return None
    cst = str(target["cst_ibs_cbs"]).strip().zfill(3)
    cclass = str(target["c_class_trib"]).strip().zfill(6)
    atual = pick_classificacao(current.get("classificacaoTributaria") or [], today) or {}
    if (str(atual.get("cst") or "").strip().zfill(3) == cst
            and str(atual.get("cClassTrib") or "").strip().zfill(6) == cclass):
        return None
    if not digits(current.get("codigo")):
        raise CorrectionRejected("código não numérico", repr(current.get("codigo")))
    codigo_produto = int(digits(current.get("codigo")))
    match = next((c for c in catalogs.classificacoes or []
                  if str(c.get("cst") or "").strip().zfill(3) == cst
                  and str(c.get("cClassTrib") or "").strip().zfill(6) == cclass), None)
    if match is None:
        raise CorrectionRejected(f"sem classificação tributária CST {cst} / cClassTrib {cclass} no VRMaster "
                                 f"(a API não cria classificações); crie no VRMaster", codigo_produto)
    if match.get("codigo") in (None, ""):
        raise CorrectionRejected(f"classificação tributária CST {cst} / cClassTrib {cclass} sem código "
                                 f"em /classificacaoTributaria; confira no VRMaster", codigo_produto)
    return match.get("codigo"), codigo_produto


def build_vinculos(pairs: List[Tuple[dict, dict]], ctx: VrStoreContext, catalogs: VrCatalogs,
                   today: date) -> Tuple[List[dict], List[str]]:
    grouped: Dict[int, List[int]] = {}
    rejected: List[str] = []
    for current, target in pairs:
        if current is None or not target:
            continue
        try:
            found = _vinculo_for(current, target, catalogs, today)
        except CorrectionRejected as exc:
            rejected.append(str(exc))
            continue
        except ValueError as exc:  # um produto com dado ruim não derruba os demais
            label = digits(current.get("codigo")) or current.get("codigo")
            rejected.append(f"Produto {label}: classificação tributária inválida na VR ({exc})")
            continue
        if found is None:
            continue
        codigo_classificacao, codigo_produto = found
        produtos = grouped.setdefault(codigo_classificacao, [])
        if codigo_produto not in produtos:
            produtos.append(codigo_produto)
    bodies = [{"codigoClassificacaoTributaria": codigo, "codigoProdutos": produtos,
               "cnpj": int(digits(ctx.cnpj)), "observacao": OBSERVACAO}
              for codigo, produtos in grouped.items()]
    return bodies, rejected
