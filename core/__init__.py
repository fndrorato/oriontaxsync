"""Módulo Core - Lógica de negócio.

Os imports são carregados sob demanda para que componentes independentes (por
exemplo, updater e mapeadores) não exijam drivers de banco ou APScheduler.
"""

__all__ = ['Scheduler', 'OracleClient', 'OrionTaxClient']


def __getattr__(name):
    if name == 'Scheduler':
        from .scheduler import Scheduler
        return Scheduler
    if name == 'OracleClient':
        from .oracle_client import OracleClient
        return OracleClient
    if name == 'OrionTaxClient':
        from .oriontax_client import OrionTaxClient
        return OrionTaxClient
    raise AttributeError(name)
