"""Metadados de apresentação e capacidades por ERP."""

ERP_PROFILES = {
    "intersolid": {
        "name": "Intersolid",
        "erp_connection": "BD Intersolid",
        "oriontax_connection": "OrionTax (PostgreSQL)",
        "send_label": "📤 Enviar Dados para OrionTax",
        "receive_label": "📥 Buscar Dados da OrionTax",
        "show_tmp_cleanup": True,
    },
    "sysmo": {
        "name": "Sysmo",
        "erp_connection": "Banco Sysmo (PostgreSQL)",
        "oriontax_connection": "API OrionTax",
        "send_label": "📤 Enviar Produtos para Análise",
        "receive_label": "📥 Receber Produtos Tributados",
        "show_tmp_cleanup": False,
    },
}


def get_erp_profile(erp_type: str):
    return ERP_PROFILES.get(erp_type, ERP_PROFILES["intersolid"])
