"""Scripted fixtures only: no model quality or real task-solving claim."""
import json
from pathlib import Path
from model_router.classification import OpenAIClassifier
from model_router.core.provider_contracts import ProviderRequest, ProviderFailure
from model_router.core.classifier_contracts import ClassificationFailure
from uuid import uuid4
from model_router.core.provider_contracts import ProviderResult, ProviderUsage
from model_router.execution.provider import MockProvider, request_evidence
from .corpus import canonical_case_input
from .grading import BlindGrader, ProviderSemanticEvaluator


class OfflineProviderClassifier(OpenAIClassifier):
    """Mock classification through the unchanged schema/normalizer with call evidence.

    This lab-only adapter is composed exclusively by compose_offline; it never
    reads credentials or constructs a live provider. The runner wraps its mock
    provider for admission and accounting, as it does all experimental calls.
    """
    def classify(self, request):
        model = self._bundle.catalog['models'][self._config.model_alias]
        invocation = ProviderRequest(task_id=request.task_id,trace_id=request.trace_id,
            invocation_id='classifier-'+uuid4().hex,policy_version=self._bundle.policy['version'],
            catalog_version=self._bundle.catalog['catalog_version'],model_alias=self._config.model_alias,
            provider_model_id=model['provider_model_id'],reasoning_effort=self._config.reasoning_effort,
            input=request.input,instructions=self._config.prompt_text,output_type=self._normalizer._output_type,
            max_output_tokens=self._config.max_output_tokens,timeout_ms=self._config.timeout_ms,purpose='classification')
        outcome = self._provider.execute(invocation)
        if isinstance(outcome,ProviderFailure):
            return ClassificationFailure(task_id=request.task_id,trace_id=request.trace_id,
                classifier_version=self._config.version,prompt_version=self._config.prompt_version,
                schema_version=self._config.schema_version,configuration_hash=self._config.configuration_hash,
                failure_type=outcome.failure_type,cause_code='mock_classifier_failed',provider_result=outcome)
        return self._normalizer.normalize(request,outcome.structured_output,outcome)


def compose_offline(cases, bundle, classifier_config, config, fixture_path):
    """Public scripted outputs are independent fixture evidence, never live answers."""
    fixture = json.loads(Path(fixture_path).read_text())
    # Fixture shape is deliberately simple and fully operator-controlled.
    outputs = fixture['outputs']
    wire = fixture['classification']
    answers = {canonical_case_input(c): outputs[c.case_id] for c in cases if c.case_id in outputs}
    def respond(request):
        usage = ProviderUsage(input_tokens=100,cached_input_tokens=0,cache_write_input_tokens=0,
                              output_tokens=40,reasoning_tokens=0,total_tokens=140)
        values = dict(request_evidence(request,latency_ms=10),response_status='completed',usage=usage)
        if request.purpose == 'classification':
            values['structured_output'] = request.output_type.model_validate(wire)
        elif request.purpose == 'evaluation':
            values['structured_output'] = request.output_type.model_validate({'score':fixture['semantic_score']})
        else:
            if request.input not in answers:
                raise ValueError('offline output is unscripted')
            answer = answers[request.input]
            if not isinstance(answer,str):
                answer = json.dumps(answer,sort_keys=True)
            if request.output_type is not None:
                values['structured_output'] = request.output_type.model_validate_json(answer)
            else:
                values['text'] = answer
        return ProviderResult(**values)
    # No unbounded provider retries. The finite experiment determines consumption.
    from itertools import repeat
    provider = MockProvider(repeat(respond))
    classifier = OfflineProviderClassifier(provider,bundle,classifier_config)
    def evaluator(binding,purpose):
        if binding is None:
            return None
        return ProviderSemanticEvaluator(provider,binding,policy_version=bundle.policy['version'],
            catalog_version=bundle.catalog['catalog_version'],
            provider_model_id=bundle.catalog['models'][binding.model]['provider_model_id'],purpose=purpose)
    grader = BlindGrader(evaluator=evaluator(config.evaluator,'judge'),
                         adjudicator=evaluator(config.adjudicator,'adjudication'),config=config)
    return provider,classifier,grader
