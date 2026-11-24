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
    if selected == "vr":
        from .vr import VrIntegration
        vr = db_manager.get_vr_config()
        api = db_manager.get_oriontax_api_config()
        if not vr or not api:
            raise RuntimeError("Configure a API VR e a API OrionTax antes de sincronizar.")
        from pathlib import Path

        def active_ufs():
            return {c.get("uf") for c in db_manager.get_all_clientes_threadsafe() if c.get("uf")}

        return VrIntegration(vr, api, installation["installation_id"],
                             store_lookup=db_manager.get_cliente_by_cnpj_threadsafe,
                             snapshot_dir=Path(db_manager.db_path).parent / "vr_snapshots",
                             active_ufs=active_ufs)
    raise ValueError("A integração Intersolid continua no fluxo legado durante a migração da versão 2.0.")
