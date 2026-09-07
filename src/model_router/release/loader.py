"""Side-effect-free loader for separately versioned release manifests."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError
import yaml

from model_router.classification.classifier import ClassifierConfig, load_classifier_config
from model_router.core.configuration import PolicyBundle, load_bundle
from model_router.core.contracts import ConfigurationError, thaw

from .schema import LiveEvidenceDocument, ReleaseConfig


class ReleaseConfigurationError(ConfigurationError):
    """Release manifest or one of its immutable references is invalid."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value) if value.__class__.__name__ == "Decimal" else value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _read_yaml(path: Path) -> Mapping[str, Any]:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except OSError as exc:
        raise ReleaseConfigurationError(f"cannot read release file {path}") from exc
    except yaml.YAMLError as exc:
        raise ReleaseConfigurationError(f"cannot parse release file {path}") from exc
    if not isinstance(value, dict):
        raise ReleaseConfigurationError(f"release file {path} must contain a mapping")
    return value


def _file_digest(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ReleaseConfigurationError(f"cannot read immutable reference {path}: {exc}") from exc


def _validation_fields(exc: ValidationError) -> str:
    fields = sorted(
        {
            ".".join(str(part) for part in error.get("loc", ())) or "document"
            for error in exc.errors(
                include_url=False, include_context=False, include_input=False
            )
        }
    )
    return ", ".join(fields[:16])


@dataclass(frozen=True, slots=True)
class LoadedRelease:
    source: Path
    config: ReleaseConfig
    policy_bundle: PolicyBundle
    release_sha256: str
    live_evidence: LiveEvidenceDocument | None
    classifier_config: ClassifierConfig | None

    @property
    def canonical_manifest(self) -> Mapping[str, Any]:
        return _manifest(self.config)


def _manifest(config):
    value = thaw(config.model_dump(mode="python", exclude_none=False))
    # Preserve hashes and activation receipts for historical manifests.
    if "classify_route" not in config.operations.model_fields_set:
        value["operations"].pop("classify_route")
    if "max_preview_records" not in config.limits.model_fields_set:
        value["limits"].pop("max_preview_records")
    return value


def _policy_versions(bundle: PolicyBundle) -> dict[str, str]:
    return {
        "policy": str(bundle.policy["version"]),
        "catalog": str(bundle.catalog["catalog_version"]),
        "budgets": str(bundle.budgets["version"]),
        "validation": str(bundle.validation["version"]),
    }


def load_release(path: str | Path) -> LoadedRelease:
    """Load every referenced snapshot without authorizing any operation."""

    source = Path(path).expanduser().resolve()
    values = _read_yaml(source)
    try:
        config = ReleaseConfig.model_validate(values)
    except ValidationError as exc:
        raise ReleaseConfigurationError(
            f"invalid release manifest fields: {_validation_fields(exc)}"
        ) from exc
    except (ValueError, TypeError) as exc:
        raise ReleaseConfigurationError("invalid release manifest") from exc

    policy_directory = (source.parent / config.policy.directory).resolve()
    try:
        policy_bundle = load_bundle(policy_directory)
    except ConfigurationError as exc:
        raise ReleaseConfigurationError(f"invalid referenced policy bundle: {exc}") from exc
    if policy_bundle.content_hash != config.policy.content_sha256:
        raise ReleaseConfigurationError("referenced policy content hash does not match manifest")
    if _policy_versions(policy_bundle) != config.policy.versions.model_dump(mode="python"):
        raise ReleaseConfigurationError("referenced policy versions do not match manifest")

    live_evidence = None
    if config.live.evidence is not None:
        reference = config.live.evidence
        evidence_path = (source.parent / reference.path).resolve()
        if _file_digest(evidence_path) != reference.sha256:
            raise ReleaseConfigurationError("live evidence file hash does not match manifest")
        try:
            live_evidence = LiveEvidenceDocument.model_validate(_read_yaml(evidence_path))
        except ValidationError as exc:
            raise ReleaseConfigurationError(
                f"invalid live evidence fields: {_validation_fields(exc)}"
            ) from exc
        except (ValueError, TypeError) as exc:
            raise ReleaseConfigurationError("invalid live evidence") from exc
        if live_evidence.evidence_id != reference.version:
            raise ReleaseConfigurationError("live evidence version does not match manifest")

    classifier_config = None
    if config.live.classifier_config is not None:
        reference = config.live.classifier_config
        classifier_path = (source.parent / reference.path).resolve()
        try:
            classifier_config = load_classifier_config(classifier_path, policy_bundle)
        except ConfigurationError as exc:
            raise ReleaseConfigurationError(f"invalid classifier config: {exc}") from exc
        if classifier_config.configuration_hash != reference.sha256:
            raise ReleaseConfigurationError("classifier configuration hash does not match manifest")
        if classifier_config.version != reference.version:
            raise ReleaseConfigurationError("classifier config version does not match manifest")

    release_hash = sha256(_canonical_bytes(_manifest(config))).hexdigest()
    return LoadedRelease(
        source=source,
        config=config,
        policy_bundle=policy_bundle,
        release_sha256=release_hash,
        live_evidence=live_evidence,
        classifier_config=classifier_config,
    )


__all__ = ["LoadedRelease", "ReleaseConfigurationError", "load_release"]
