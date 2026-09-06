"""Select required evidence/checks without executing any validators."""

from model_router.core.contracts import (
    EnvironmentSnapshot, Request, ValidationLevel, ValidationRequirements,
)


def determine_validation(request: Request, environment: EnvironmentSnapshot, bundle) -> ValidationRequirements:
    config = bundle.validation
    consequence = config["consequence_defaults"][request.consequence]
    levels = tuple(ValidationLevel)
    requested = [ValidationLevel(config["default_profile"]), ValidationLevel(consequence["profile"])]
    requested.extend(value for value in (request.requested_validation, environment.requested_validation)
                     if value is not None)
    level = max(requested, key=levels.index)
    profiles, checks, evaluators, validators, blockers = [], [], [], [], []

    def visit(name):
        if name in profiles:
            return
        profile = config["profiles"][name]
        if profile.get("base_profile"):
            visit(profile["base_profile"])
        if profile.get("required_semantic_profile"):
            visit(profile["required_semantic_profile"])
        profiles.append(name)
        checks.extend(profile.get("checks_when_applicable", ()))
        mock = environment.synthetic and environment.validation.get(name) == "configured_mock"
        if profile.get("evaluator_ref"):
            ref = profile["evaluator_ref"]
            evaluators.append(ref)
            binding = config["evaluators"][ref]
            if not mock and not binding["enabled"]:
                blockers.append("evaluator_unconfigured")
        if profile["kind"] == "application_domain":
            if profile.get("validator_ref"):
                validators.append(profile["validator_ref"])
            elif not mock:
                blockers.append("domain_validator_unconfigured")

    # V3 is not defined as a superset of V2; retain all independently required
    # profiles when callers strengthen the selected profile.
    for name in dict.fromkeys(requested):
        visit(name)
    if consequence["approval_gate"] and not request.approval_evidence:
        blockers.append("approval_missing")
    if ("domain_clearance_required" in consequence["execution_restrictions"]
            and not request.domain_clearance_evidence):
        blockers.append("domain_clearance_missing")
    return ValidationRequirements(
        level=level, profiles=tuple(profiles), checks=tuple(dict.fromkeys(checks)),
        evaluator_refs=tuple(dict.fromkeys(evaluators)), validator_refs=tuple(dict.fromkeys(validators)),
        blockers=tuple(dict.fromkeys(blockers)), evaluator_required=bool(evaluators),
        approval_required=consequence["approval_gate"], evidence=consequence["evidence"],
        execution_restrictions=consequence["execution_restrictions"],
    )
