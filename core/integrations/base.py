"""Contratos compartilhados pelas integrações ERP."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


ProgressCallback = Optional[Callable[[str], None]]


@dataclass
class SyncResult:
    success: bool
    message: str
    records: int = 0
    accepted_jobs: List[str] = field(default_factory=list)
    details: Dict = field(default_factory=dict)


class IntegrationAdapter(ABC):
    erp_type = "unknown"

    @abstractmethod
    def send(self, cnpj: str, progress_callback: ProgressCallback = None) -> SyncResult:
        """Envia dados do ERP para a OrionTax."""

    @abstractmethod
    def receive(self, cnpj: str, progress_callback: ProgressCallback = None) -> SyncResult:
        """Recebe dados da OrionTax e grava no ERP."""

    def cancel(self):
        """Solicita cancelamento da operação, quando suportado."""

