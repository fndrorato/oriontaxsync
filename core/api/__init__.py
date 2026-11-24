"""Clientes de APIs externas."""

from .oriontax_api_client import OrionTaxApiClient, OrionTaxApiError
from .vr_api_client import VrApiClient, VrApiError

__all__ = ["OrionTaxApiClient", "OrionTaxApiError", "VrApiClient", "VrApiError"]
