"""Model versions as the server sees them (matcher ADR 0004): downloaded once into a cache
directory that survives restarts, verified, kept in memory. Versions never change in MLflow,
so a cached copy is never stale, and cached versions keep working while MLflow is down.
"""

import shutil
import threading
from pathlib import Path

from matcher import bundle
from matcher.registry import BundleSource, Unavailable, UnknownVersion

__all__ = ["ModelStore", "Unavailable", "UnknownVersion"]


class ModelStore:
    def __init__(self, source: BundleSource | None, cache_dir: Path) -> None:
        self.source = source
        self.cache_dir = cache_dir
        self._loaded: dict[str, bundle.Bundle] = {}
        self._lock = threading.Lock()  # one download per version at a time

    def get(self, version: str) -> bundle.Bundle:
        """The verified bundle of a version. UnknownVersion or BundleError: the request is
        wrong (422). Unavailable: try again later (503)."""
        if not version.isdigit():
            raise UnknownVersion(version)
        if version in self._loaded:
            return self._loaded[version]
        with self._lock:
            if version in self._loaded:
                return self._loaded[version]
            path = self.cache_dir / version
            if not path.is_dir():
                if self.source is None:
                    raise Unavailable("no model registry configured and version not cached")
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                partial = self.cache_dir / f".{version}.partial"
                shutil.rmtree(partial, ignore_errors=True)
                self.source.download(version, partial)
                partial.rename(path)  # appears complete or not at all
            try:
                loaded = bundle.load(path)
            except bundle.BundleError:
                shutil.rmtree(path, ignore_errors=True)  # a bad copy is fetched again next time
                raise
            self._loaded[version] = loaded
            return loaded

    def listing(self) -> list[dict[str, object]]:
        """Versions in memory and in the cache directory, with their manifests."""
        cached = (
            sorted((p.name for p in self.cache_dir.glob("[0-9]*") if p.is_dir()), key=int)
            if self.cache_dir.is_dir()
            else []
        )
        return [
            {
                "version": v,
                "loaded": v in self._loaded,
                "manifest": bundle.manifest_dict(self.cache_dir / v),
            }
            for v in cached
        ]
