"""Free authenticated preview using the shared client; no provider call."""
import asyncio
import json

from model_router.client import RouterClient, ClientConfig, Request, Classification


async def preview(base_url: str, token: str) -> dict:
    request = Request(task_id="sample-preview-1", trace_id="sample-preview-trace-1",
        input="Convert these labels to lowercase.", consequence="low",
        requirements=("text_input", "text_output"),
        context={"input_tokens": 100, "expected_output_tokens": 50})
    classification = Classification(task_family="transform", confidence=1.0,
        provenance="application-supplied", components={
            "reasoning_depth": 0, "step_dependency": 0, "context_synthesis": 0,
            "technical_precision": 0, "ambiguity": 0, "tool_orchestration": 0,
            "reliability_requirement": 0})
    async with RouterClient(ClientConfig(base_url=base_url, token=token)) as client:
        return (await client.route_preview(request, classification)).model_dump(mode="json")


if __name__ == "__main__":
    config = ClientConfig.from_env()
    print(json.dumps(asyncio.run(preview(config.base_url, config.token.get_secret_value())), indent=2))
