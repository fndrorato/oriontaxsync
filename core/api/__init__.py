"""Clientes de APIs externas."""

from .oriontax_api_client import OrionTaxApiClient, OrionTaxApiError

__all__ = ["OrionTaxApiClient", "OrionTaxApiError"]
