"""Declarative, fail-closed UiPath platform provisioning."""

from .adapter import RecordAdapterError, logical_to_physical, physical_to_logical
from .manifest import DEFAULT_MANIFEST_PATH, PlatformManifest, load_manifest

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "PlatformManifest",
    "RecordAdapterError",
    "load_manifest",
    "logical_to_physical",
    "physical_to_logical",
]
