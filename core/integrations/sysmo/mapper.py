"""Conversões entre o schema Sysmo e o contrato da API OrionTax V2."""
from decimal import Decimal, InvalidOperation


# A API exige a presença das chaves fiscais, mas a implementação real aceita
# valores nulos (confirmado em homologação). Código, descrição e NCM continuam
# validados localmente porque identificam o produto e são indispensáveis para
# uma mensagem de erro útil. As demais chaves sempre são incluídas no payload.
REQUIRED_NON_EMPTY_FIELDS = ("codigo", "descricao", "ncm")


def _number(value, default=0):
    if value in (None, ""):
        return default
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Valor numérico inválido: {value!r}")


def _code(value, width=None):
    """Normaliza códigos vindos do PostgreSQL sem produzir textos como 1.0."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.zfill(width) if width and text.isdigit() else text


def sysmo_row_to_api(row: dict) -> dict:
    integral = _number(row.get("vl_aliquota_integral_icms"))
    final = _number(row.get("vl_aliquota_final_icms"))
    reduction = round((1 - final / integral) * 100, 2) if integral else 0.0
    pis_cst = _code(row.get("nr_cst_pis"), 2)
    if not pis_cst:
        # O domínio OrionTax usa um único CST para PIS/COFINS. Algumas bases
        # Sysmo preenchem somente nr_cst_cofins.
        pis_cst = _code(row.get("nr_cst_cofins"), 2)
    payload = {
        "codigo": str(row.get("cd_produto", "")).strip(),
        "codigo_barras": str(row.get("tx_codigobarras") or "").strip(),
        "descricao": str(row.get("tx_descricaoproduto") or "").strip(),
        "ncm": str(row.get("tx_ncm") or "").strip(),
        "cest": str(row.get("tx_cest") or "").strip(),
        "cfop": _code(row.get("nr_cfop")),
        "icms_cst": row.get("nr_cst_icms"),
        "icms_aliquota": integral,
        "percentual_redbcde": reduction,
        "cbenef": str(row.get("tx_cbenef") or "").strip(),
        "protege": _number(row.get("vl_aliquota_fcp")),
        "pis_cst": pis_cst,
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
    missing = [field for field in REQUIRED_NON_EMPTY_FIELDS if payload.get(field) in (None, "")]
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
