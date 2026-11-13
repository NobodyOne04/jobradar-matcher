"""Model versions in MLflow (matcher ADR 0004). One registered model, `jobradar-matcher`; each
version's source is its training run's `bundle/` artifacts; alias `champion` is the live one
(jobradar ADR 0010: the backend follows it). The matcher server only downloads versions.
"""

import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

NAME = "jobradar-matcher"
CHAMPION = "champion"


class Unavailable(Exception):
    """The registry cannot be reached right now (retry later)."""


class UnknownVersion(Exception):
    """No such model version."""


class BundleSource(Protocol):
    """Where the server gets bundles from. MLflow in production, a directory in tests."""

    def download(self, version: str, dest: Path) -> None: ...


class MLflowRegistry:
    def __init__(self, tracking_uri: str) -> None:
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")  # quiet library log line
        import mlflow
        from mlflow import MlflowClient

        mlflow.set_tracking_uri(tracking_uri)
        self._mlflow = mlflow
        self.client = MlflowClient(tracking_uri)

    # --- used by the server ---

    def download(self, version: str, dest: Path) -> None:
        """Download a version's bundle into dest (which must not exist yet)."""
        from mlflow.exceptions import MlflowException

        try:
            self.client.get_model_version(NAME, version)
        except MlflowException as e:
            if "RESOURCE_DOES_NOT_EXIST" in str(e.error_code):
                raise UnknownVersion(version) from e
            raise Unavailable(str(e)) from e
        except OSError as e:
            raise Unavailable(str(e)) from e
        tmp = Path(tempfile.mkdtemp(prefix="bundle-"))
        try:
            got = self._mlflow.artifacts.download_artifacts(
                artifact_uri=f"models:/{NAME}/{version}", dst_path=str(tmp)
            )
            shutil.move(got, dest)
        except (MlflowException, OSError) as e:
            raise Unavailable(str(e)) from e
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # --- used by `matcher train`, `promote`, `models` ---

    def register(
        self,
        bundle_dir: Path,
        params: dict[str, str],
        metrics: dict[str, float],
        tags: dict[str, str],
        artifacts: dict[str, Path] | None = None,
    ) -> str:
        """Log a run with the bundle, its eval metrics and extra artifact folders (by artifact
        path), and register it as a new version."""
        from mlflow.exceptions import MlflowException

        self._mlflow.set_experiment(NAME)
        with self._mlflow.start_run() as run:
            self._mlflow.log_params(params)
            if metrics:
                self._mlflow.log_metrics(metrics)
            self._mlflow.set_tags(tags)
            self._mlflow.log_artifacts(str(bundle_dir), "bundle")
            for path, local in (artifacts or {}).items():
                self._mlflow.log_artifacts(str(local), path)
        try:
            self.client.create_registered_model(NAME)
        except MlflowException as e:
            if "RESOURCE_ALREADY_EXISTS" not in str(e.error_code):
                raise
        mv = self.client.create_model_version(
            NAME, source=f"{run.info.artifact_uri}/bundle", run_id=run.info.run_id, tags=tags
        )
        return str(mv.version)

    def champion(self) -> str | None:
        from mlflow.exceptions import MlflowException

        try:
            return str(self.client.get_model_version_by_alias(NAME, CHAMPION).version)
        except MlflowException:
            return None

    def metrics(self, version: str) -> dict[str, float]:
        mv = self.client.get_model_version(NAME, version)
        return dict(self.client.get_run(mv.run_id).data.metrics) if mv.run_id else {}

    def dataset_version(self, version: str) -> str | None:
        mv = self.client.get_model_version(NAME, version)
        return (
            self.client.get_run(mv.run_id).data.tags.get("eval_dataset_version")
            if mv.run_id
            else None
        )

    def promote(self, version: str, reason: str, gate: str) -> None:
        self.client.get_model_version(NAME, version)  # raises if it does not exist
        for key, value in {
            "promoted_reason": reason,
            "promoted_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "gate": gate,
        }.items():
            self.client.set_model_version_tag(NAME, version, key, value)
        self.client.set_registered_model_alias(NAME, CHAMPION, version)

    def versions(self) -> list[dict[str, object]]:
        champion = self.champion()
        out = []
        for mv in self.client.search_model_versions(f"name='{NAME}'"):
            out.append(
                {
                    "version": str(mv.version),
                    "champion": str(mv.version) == champion,
                    "parent": mv.tags.get("parent"),
                    "gate": mv.tags.get("gate"),
                    "promoted_reason": mv.tags.get("promoted_reason"),
                    "created": datetime.fromtimestamp(mv.creation_timestamp / 1000, UTC).isoformat(
                        timespec="seconds"
                    ),
                }
            )
        return sorted(out, key=lambda v: int(str(v["version"])))
