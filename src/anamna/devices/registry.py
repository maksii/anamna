from __future__ import annotations

from .apple_health import AppleHealthAdapter
from .kardia import KardiaAdapter
from .structured import GarminAdapter, OuraAdapter


ADAPTERS = {
    adapter.key: adapter
    for adapter in (AppleHealthAdapter(), OuraAdapter(), GarminAdapter(), KardiaAdapter())
}


def get_adapter(key: str):
    try:
        return ADAPTERS[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported device vendor: {key}") from exc
