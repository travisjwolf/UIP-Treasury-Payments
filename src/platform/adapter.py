"""Explicit adapters between logical Alpha contracts and Data Fabric fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .manifest import PlatformManifest


_DATA_FABRIC_SYSTEM_FIELDS = {
    "createdby",
    "createtime",
    "id",
    "updatedby",
    "updatetime",
}


class RecordAdapterError(ValueError):
    """Raised when a record falls outside the declared schema mapping."""


def logical_to_physical(
    manifest: PlatformManifest,
    contract: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    entity = manifest.entity_for_contract(contract)
    mapping = {field.logical_name: field.physical_name for field in entity.fields}
    unknown = set(record) - mapping.keys()
    if unknown:
        raise RecordAdapterError(
            f"unknown logical field(s) for {contract}: {sorted(unknown)}"
        )
    return {mapping[name]: value for name, value in record.items()}


def physical_to_logical(
    manifest: PlatformManifest,
    contract: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    entity = manifest.entity_for_contract(contract)
    mapping = {field.physical_name: field.logical_name for field in entity.fields}
    unknown = {
        name
        for name in record
        if name not in mapping and name.lower() not in _DATA_FABRIC_SYSTEM_FIELDS
    }
    if unknown:
        raise RecordAdapterError(
            f"unknown physical field(s) for {contract}: {sorted(unknown)}"
        )
    return {mapping[name]: value for name, value in record.items() if name in mapping}
