"""Declarative, fail-closed UiPath platform provisioning."""

from .manifest import DEFAULT_MANIFEST_PATH, PlatformManifest, load_manifest

__all__ = ["DEFAULT_MANIFEST_PATH", "PlatformManifest", "load_manifest"]
