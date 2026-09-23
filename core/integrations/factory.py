"""Fábrica central de integrações."""


def create_integration(db_manager, erp_type=None):
    installation = db_manager.get_installation()
    selected = erp_type or installation["erp_type"]
    if selected == "sysmo":
        from .sysmo import SysmoIntegration
        sysmo = db_manager.get_sysmo_config()
        api = db_manager.get_oriontax_api_config()
        if not sysmo or not api:
            raise RuntimeError("Configure o banco Sysmo e a API OrionTax antes de sincronizar.")
        return SysmoIntegration(sysmo, api, installation["installation_id"])
    raise ValueError("A integração Intersolid continua no fluxo legado durante a migração da versão 2.0.")
