"""Conversões entre o schema Sysmo e o contrato da API OrionTax V2."""
from decimal import Decimal, InvalidOperation


REQUIRED_API_FIELDS = (
    "codigo", "descricao", "ncm", "cfop", "icms_cst", "icms_aliquota",
    "pis_cst", "pis_aliquota", "cofins_aliquota",
)


def _number(value, default=0):
    if value in (None, ""):
        return default
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Valor numérico inválido: {value!r}")


def sysmo_row_to_api(row: dict) -> dict:
    integral = _number(row.get("vl_aliquota_integral_icms"))
    final = _number(row.get("vl_aliquota_final_icms"))
    reduction = round((1 - final / integral) * 100, 2) if integral else 0.0
    payload = {
        "codigo": str(row.get("cd_produto", "")).strip(),
        "codigo_barras": str(row.get("tx_codigobarras") or "").strip(),
        "descricao": str(row.get("tx_descricaoproduto") or "").strip(),
        "ncm": str(row.get("tx_ncm") or "").strip(),
        "cest": str(row.get("tx_cest") or "").strip(),
        "cfop": row.get("nr_cfop"),
        "icms_cst": row.get("nr_cst_icms"),
        "icms_aliquota": integral,
        "percentual_redbcde": reduction,
        "cbenef": str(row.get("tx_cbenef") or "").strip(),
        "protege": _number(row.get("vl_aliquota_fcp")),
        "pis_cst": row.get("nr_cst_pis"),
        "pis_aliquota": _number(row.get("vl_aliquota_pis")),
        "cofins_aliquota": _number(row.get("vl_aliquota_cofins")),
        "natureza_receita": row.get("nr_naturezareceita") or 0,
        "cst_ibs_cbs": row.get("cst_ibs_cbs"),
        "c_class_trib": row.get("c_class_trib"),
        "aliquota_ibs": row.get("aliquota_ibs"),
        "aliquota_cbs": row.get("aliquota_cbs"),
        "p_red_aliq_ibs": row.get("p_red_aliq_ibs"),
        "p_red_aliq_cbs": row.get("p_red_aliq_cbs"),
        "inf_ad_fisco": bool(row.get("inf_ad_fisco", False)),
    }
    missing = [field for field in REQUIRED_API_FIELDS if payload.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Produto {payload['codigo'] or '<sem código>'}: campos obrigatórios: {', '.join(missing)}")
    return payload


def api_product_to_sysmo(product: dict) -> tuple:
    return (
        product.get("sequencial") or 0,
        str(product.get("codigo", "")).strip(),
        str(product.get("codigo_barras") or "").strip(),
        str(product.get("descricao") or "").strip(),
        str(product.get("ncm") or "").strip(),
        str(product.get("cest") or "").strip(),
        product.get("cfop"), product.get("icms_cst"), product.get("icms_aliquota"),
        product.get("icms_aliquota_reduzida"), product.get("protege"),
        str(product.get("cbenef") or ""), product.get("pis_cst"),
        product.get("pis_aliquota"), product.get("pis_cst"), product.get("cofins_aliquota"),
        product.get("natureza_receita") or 0, product.get("estado_origem") or "",
        product.get("estado_destino") or "", "S",
    )
