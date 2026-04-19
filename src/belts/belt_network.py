"""Compatibility shim.

The original Python-recursive ``BeltNetwork`` has been replaced by the
vectorised ``BeltNetworkSoA`` in :mod:`src.belts.network_soa`. This module
re-exports it under the old name so existing imports keep working.
"""

from __future__ import annotations

from .network_soa import BeltNetworkSoA as BeltNetwork

__all__ = ["BeltNetwork"]
