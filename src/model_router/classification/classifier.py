"""Structured task classification without routing decisions."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, create_model, model_validator
import yaml

from model_router.core.classifier_contracts import ClassificationFailure, ClassificationResult
from model_router.core.configuration import PolicyBundle
from model_router.core.contracts import Classification, ConfigurationError, Effort, FailureType, Name, Record, Request
from model_router.core.provider_contracts import ModelProvider, ProviderFailure, ProviderRequest, ProviderResult


_COMPONENT_FIELDS = (
    "reasoning_depth", "step_dependency", "context_synthesis", "technical_precision",
    "ambiguity", "tool_orchestration", "reliability_requirement",
)
_WIRE_FIELDS = frozenset({"task_family", "task_subclass", "components", "confidence", "flags"})


class ClassifierConfig(Record):
    """Validated settings plus immutable provenance material."""

    schema_version: Name
    version: Name
    prompt_version: Name
    status: Literal["draft", "active", "retired"]
    model_alias: Name
    reasoning_effort: Effort
    max_output_tokens: Annotated[StrictInt, Field(gt=0)]
    timeout_ms: Annotated[StrictInt, Field(gt=0)]
    live_enabled: StrictBool
    prompt_path: Name
    prompt_text: StrictStr = Field(exclude=True, repr=False)
    prompt_hash: Name
    schema_hash: Name
    configuration_hash: Name
    bundle_hash: Name

    @model_validator(mode="after")
    def prompt_is_not_blank(self):
        if not self.prompt_text.strip():
            raise ValueError("classifier prompt must not be blank")
        return self


class _ClassifierFile(Record):
    schema_version: Name
    version: Name
    prompt_version: Name
    status: Literal["draft", "active", "retired"]
    model_alias: Name
    reasoning_effort: Effort
    max_output_tokens: Annotated[StrictInt, Field(gt=0)]
    timeout_ms: Annotated[StrictInt, Field(gt=0)]
    live_enabled: StrictBool
    prompt_path: Name


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found an unhashable key", key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found duplicate key", key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _flag_vocabulary(bundle: PolicyBundle) -> tuple[str, ...]:
    flags = {
        flag
        for section in ("task_family_floors", "modifiers")
        for rule in bundle.policy[section]
        for flag in rule["match"]["flags_all"]
    }
    return tuple(sorted(flags))


def build_output_type(bundle: PolicyBundle) -> type[BaseModel]:
    """Build the strict Structured Outputs model from the pinned policy."""

    configured = bundle.policy["complexity"]["components"]
    if set(configured) != set(_COMPONENT_FIELDS):
        raise ConfigurationError("classifier component vocabulary does not match Phase 1")
    component_fields: dict[str, tuple[Any, Any]] = {}
    for name in _COMPONENT_FIELDS:
        bounds = configured[name]
        component_fields[name] = (
            Annotated[StrictInt, Field(ge=bounds["min"], le=bounds["max"])], ...,
        )
    components_type = create_model(
        "TaskComplexityComponentsV1",
        __config__=ConfigDict(extra="forbid", frozen=True, strict=True),
        **component_fields,
    )
    flags_type = create_model(
        "TaskPolicyFlagsV1",
        __config__=ConfigDict(extra="forbid", frozen=True, strict=True),
        **{name: (StrictBool, ...) for name in _flag_vocabulary(bundle)},
    )
    families = tuple(bundle.policy["task_families"])
    if not families:
        raise ConfigurationError("classifier task-family vocabulary must not be empty")
    family_type = Literal.__getitem__(families)
    return create_model(
        "TaskPropertiesV1",
        __config__=ConfigDict(extra="forbid", frozen=True, strict=True),
        task_family=(family_type, ...),
        task_subclass=(type(None), ...),
        components=(components_type, ...),
        confidence=(Annotated[float, Field(strict=True, ge=0, le=1)], ...),
        flags=(flags_type, ...),
    )


def _schema_hash(output_type: type[BaseModel]) -> str:
    return _canonical_hash(output_type.model_json_schema())


def load_classifier_config(path: str | Path, bundle: PolicyBundle) -> ClassifierConfig:
    """Load classifier settings and bind them to prompt, schema, and policy."""

    config_path = Path(path)
    if config_path.is_dir():
        config_path = config_path / "classifier.yaml"
    try:
        with config_path.open("r", encoding="utf-8") as stream:
            raw = yaml.load(stream, Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError):
        raise ConfigurationError("cannot load classifier configuration") from None
    if not isinstance(raw, dict):
        raise ConfigurationError("classifier configuration must contain a mapping")
    try:
        parsed = _ClassifierFile.model_validate(raw)
    except ValidationError:
        raise ConfigurationError("invalid classifier configuration") from None

    prompt_path = (config_path.parent / parsed.prompt_path).resolve()
    config_directory = config_path.parent.resolve()
    if prompt_path != config_directory and config_directory not in prompt_path.parents:
        raise ConfigurationError("classifier prompt_path must remain inside the configuration directory")
    try:
        prompt_text = prompt_path.read_text(encoding="utf-8")
    except OSError:
        raise ConfigurationError("cannot load classifier prompt") from None
    if not prompt_text.strip():
        raise ConfigurationError("classifier prompt must not be blank")

    model = bundle.catalog["models"].get(parsed.model_alias)
    if model is None:
        raise ConfigurationError("classifier references an unknown model alias")
    if not model["availability"]["configured_enabled"]:
        raise ConfigurationError("classifier model is not enabled in the catalog")
    if parsed.reasoning_effort.value not in model["reasoning_efforts"]:
        raise ConfigurationError("classifier reasoning effort is unsupported by its model")
    capabilities = model["capabilities"]
    if capabilities["text_input"] is not True or capabilities["structured_outputs"] is not True:
        raise ConfigurationError("classifier model lacks verified required capabilities")
    if parsed.max_output_tokens > model["max_output_tokens"]:
        raise ConfigurationError("classifier output limit exceeds the model catalog limit")

    output_type = build_output_type(bundle)
    prompt_hash = sha256(prompt_text.encode("utf-8")).hexdigest()
    schema_hash = _schema_hash(output_type)
    config_payload = parsed.model_dump(mode="json")
    config_hash = _canonical_hash({
        "config": config_payload,
        "prompt_sha256": prompt_hash,
        "schema_sha256": schema_hash,
        "policy_bundle_sha256": bundle.content_hash,
    })
    return ClassifierConfig(
        **config_payload, prompt_text=prompt_text, prompt_hash=prompt_hash,
        schema_hash=schema_hash, configuration_hash=config_hash, bundle_hash=bundle.content_hash,
    )


def _check_binding(bundle: PolicyBundle, config: ClassifierConfig) -> None:
    if config.bundle_hash != bundle.content_hash:
        raise ConfigurationError("classifier configuration is bound to a different policy bundle")
    schema_hash = _schema_hash(build_output_type(bundle))
    prompt_hash = sha256(config.prompt_text.encode("utf-8")).hexdigest()
    config_payload = {
        name: config.model_dump(mode="json")[name]
        for name in _ClassifierFile.model_fields
    }
    configuration_hash = _canonical_hash({
        "config": config_payload,
        "prompt_sha256": prompt_hash,
        "schema_sha256": schema_hash,
        "policy_bundle_sha256": bundle.content_hash,
    })
    if config.schema_hash != schema_hash or config.prompt_hash != prompt_hash:
        raise ConfigurationError("classifier prompt or schema provenance is invalid")
    if config.configuration_hash != configuration_hash:
        raise ConfigurationError("classifier configuration provenance is invalid")


def _provenance(config: ClassifierConfig, bundle: PolicyBundle) -> str:
    return (
        f"{config.version};prompt={config.prompt_version}@sha256:{config.prompt_hash};"
        f"schema={config.schema_version}@sha256:{config.schema_hash};"
        f"config=sha256:{config.configuration_hash};policy=sha256:{bundle.content_hash}"
    )


def _validation_diagnostics(exc: ValidationError) -> tuple[str, ...]:
    """Return bounded schema labels and never rejected values or field names."""

    safe: list[str] = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        location = error.get("loc", ())
        first = location[0] if location else None
        label = str(first) if first in _WIRE_FIELDS else "unknown_field"
        if label not in safe:
            safe.append(label)
    return tuple(safe) or ("structured_output",)


def _failure(
    request: Request,
    config: ClassifierConfig,
    failure_type: FailureType,
    cause_code: str,
    *,
    diagnostic_fields: tuple[str, ...] = (),
    provider_result: ProviderResult | ProviderFailure | None = None,
) -> ClassificationFailure:
    return ClassificationFailure(
        task_id=request.task_id, trace_id=request.trace_id,
        classifier_version=config.version, prompt_version=config.prompt_version,
        schema_version=config.schema_version, configuration_hash=config.configuration_hash,
        failure_type=failure_type, cause_code=cause_code,
        diagnostic_fields=diagnostic_fields, provider_result=provider_result,
    )


class _Normalizer:
    def __init__(self, bundle: PolicyBundle, config: ClassifierConfig):
        _check_binding(bundle, config)
        self._bundle = bundle
        self._config = config
        self._output_type = build_output_type(bundle)

    def normalize(
        self,
        request: Request,
        output: Mapping[str, Any] | BaseModel,
        provider_result: ProviderResult | None = None,
    ) -> ClassificationResult | ClassificationFailure:
        try:
            payload = output.model_dump(mode="python") if isinstance(output, BaseModel) else output
            wire = self._output_type.model_validate(payload)
        except ValidationError as exc:
            return _failure(
                request, self._config, FailureType.MALFORMED_OUTPUT,
                "CLASSIFIER_OUTPUT_SCHEMA_INVALID",
                diagnostic_fields=_validation_diagnostics(exc), provider_result=provider_result,
            )
        classification = Classification(
            task_family=wire.task_family, task_subclass=wire.task_subclass,
            components=wire.components.model_dump(mode="python"), confidence=wire.confidence,
            flags=wire.flags.model_dump(mode="python"),
            provenance=_provenance(self._config, self._bundle),
        )
        return ClassificationResult(
            classification=classification, classifier_version=self._config.version,
            prompt_version=self._config.prompt_version, schema_version=self._config.schema_version,
            configuration_hash=self._config.configuration_hash, provider_result=provider_result,
        )


class OpenAIClassifier:
    """One-invocation classifier using the provider port and Pydantic output."""

    def __init__(self, provider: ModelProvider, bundle: PolicyBundle, config: ClassifierConfig):
        self._provider = provider
        self._bundle = bundle
        self._config = config
        self._normalizer = _Normalizer(bundle, config)

    def classify(self, request: Request) -> ClassificationResult | ClassificationFailure:
        if not self._config.live_enabled:
            return _failure(
                request, self._config, FailureType.CAPABILITY_FAILURE,
                "CLASSIFIER_LIVE_DISABLED", diagnostic_fields=("live_enabled",),
            )
        model = self._bundle.catalog["models"][self._config.model_alias]
        provider_request = ProviderRequest(
            task_id=request.task_id, trace_id=request.trace_id,
            invocation_id=f"classifier:{uuid4().hex}",
            policy_version=self._bundle.policy["version"],
            catalog_version=self._bundle.catalog["catalog_version"],
            model_alias=self._config.model_alias, provider_model_id=model["provider_model_id"],
            reasoning_effort=self._config.reasoning_effort, input=request.input,
            instructions=self._config.prompt_text, output_type=self._normalizer._output_type,
            max_output_tokens=self._config.max_output_tokens, timeout_ms=self._config.timeout_ms,
            purpose="classification", truncation="disabled",
        )
        outcome = self._provider.execute(provider_request)
        if isinstance(outcome, ProviderFailure):
            return _failure(
                request, self._config, outcome.failure_type, outcome.cause_code,
                diagnostic_fields=outcome.diagnostic_fields, provider_result=outcome,
            )
        if outcome.response_status != "completed":
            return _failure(
                request, self._config, FailureType.MALFORMED_OUTPUT,
                "CLASSIFIER_PROVIDER_INCOMPLETE", diagnostic_fields=("response_status",),
                provider_result=outcome,
            )
        if outcome.refused:
            return _failure(
                request, self._config, FailureType.MALFORMED_OUTPUT,
                "CLASSIFIER_PROVIDER_REFUSAL", diagnostic_fields=("refused",),
                provider_result=outcome,
            )
        if outcome.structured_output is None:
            return _failure(
                request, self._config, FailureType.MALFORMED_OUTPUT,
                "CLASSIFIER_OUTPUT_MISSING", diagnostic_fields=("structured_output",),
                provider_result=outcome,
            )
        return self._normalizer.normalize(request, outcome.structured_output, outcome)


class MockClassifier:
    """Deterministic classifier with keyed or sequential scripted outputs."""

    def __init__(
        self,
        outputs: Mapping[str, Mapping[str, Any] | BaseModel] | Iterable[Mapping[str, Any] | BaseModel],
        bundle: PolicyBundle,
        config: ClassifierConfig,
    ):
        self._normalizer = _Normalizer(bundle, config)
        self._config = config
        self._calls = 0
        if isinstance(outputs, Mapping) and not _WIRE_FIELDS.issubset(outputs):
            self._keyed = dict(outputs)
            self._outputs: deque[Mapping[str, Any] | BaseModel] | None = None
        else:
            self._keyed = None
            self._outputs = deque((outputs,)) if isinstance(outputs, Mapping) else deque(outputs)

    @property
    def call_count(self) -> int:
        return self._calls

    def classify(self, request: Request) -> ClassificationResult | ClassificationFailure:
        self._calls += 1
        if self._keyed is not None:
            if request.input not in self._keyed:
                return _failure(
                    request, self._config, FailureType.MALFORMED_OUTPUT,
                    "CLASSIFIER_INPUT_UNSCRIPTED", diagnostic_fields=("input",),
                )
            output = self._keyed[request.input]
        else:
            assert self._outputs is not None
            if not self._outputs:
                return _failure(
                    request, self._config, FailureType.MALFORMED_OUTPUT,
                    "CLASSIFIER_SCRIPT_EXHAUSTED",
                )
            output = self._outputs.popleft()
        return self._normalizer.normalize(request, output)


__all__ = [
    "ClassifierConfig", "MockClassifier", "OpenAIClassifier",
    "build_output_type", "load_classifier_config",
]
