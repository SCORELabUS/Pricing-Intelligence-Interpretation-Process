from __future__ import annotations

import json

import httpx
import pytest
import respx

from pricing_mcp.cache import MemoryCache
from pricing_mcp.clients.amint import AMintClient
from pricing_mcp.config import get_settings
from pricing_mcp.workflows.pricing import PricingWorkflow

AMINT_URL = "http://amint.test"
PRICING_URL = "https://example.com/pricing"
YAML = "saasName: Example\n"


@pytest.fixture(autouse=True)
def base_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMINT_BASE_URL", AMINT_URL)
    monkeypatch.setenv("ANALYSIS_BASE_URL", "http://analysis.test")
    for name in ("AMINT_LLM_MODEL", "AMINT_LLM_BETTER_MODEL", "AMINT_LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_workflow(cache: MemoryCache | None = None) -> tuple[PricingWorkflow, AMintClient]:
    get_settings.cache_clear()
    amint = AMintClient()
    workflow = PricingWorkflow(amint_client=amint, analysis_client=None, cache=cache or MemoryCache())  # type: ignore[arg-type]
    return workflow, amint


def mock_amint(router: respx.MockRouter) -> respx.Route:
    transform = router.post(f"{AMINT_URL}/api/v1/transform").mock(
        return_value=httpx.Response(200, json={"task_id": "t1"})
    )
    router.get(f"{AMINT_URL}/api/v1/transform/status/t1").mock(
        return_value=httpx.Response(200, text=YAML, headers={"content-type": "application/x-yaml"})
    )
    return transform


@respx.mock
async def test_defaults_send_the_same_llm_configuration_as_before():
    transform = mock_amint(respx.mock)
    workflow, amint = make_workflow()

    assert await workflow.ensure_pricing_yaml(PRICING_URL) == YAML
    await amint.aclose()

    payload = json.loads(transform.calls.last.request.content)
    assert payload["model"] == "gpt-5.2"
    assert payload["better_model"] == "gpt-5.2"
    assert payload["base_url"] == "https://api.openai.com/v1"
    assert payload["url"] == PRICING_URL


@respx.mock
async def test_sends_llm_configuration_from_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AMINT_LLM_MODEL", "qwen3:32b")
    monkeypatch.setenv("AMINT_LLM_BETTER_MODEL", "qwen3:235b")
    monkeypatch.setenv("AMINT_LLM_BASE_URL", "http://host.docker.internal:11434/v1")
    transform = mock_amint(respx.mock)
    workflow, amint = make_workflow()

    await workflow.ensure_pricing_yaml(PRICING_URL)
    await amint.aclose()

    payload = json.loads(transform.calls.last.request.content)
    assert payload["model"] == "qwen3:32b"
    assert payload["better_model"] == "qwen3:235b"
    assert payload["base_url"] == "http://host.docker.internal:11434/v1"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("AMINT_LLM_MODEL", "qwen3:32b"),
        ("AMINT_LLM_BETTER_MODEL", "qwen3:235b"),
        ("AMINT_LLM_BASE_URL", "http://host.docker.internal:11434/v1"),
    ],
)
async def test_cache_key_changes_with_llm_configuration(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
):
    default_workflow, default_amint = make_workflow()
    default_key = default_workflow._pricing_cache_key(PRICING_URL)
    await default_amint.aclose()

    monkeypatch.setenv(variable, value)
    changed_workflow, changed_amint = make_workflow()
    changed_key = changed_workflow._pricing_cache_key(PRICING_URL)
    await changed_amint.aclose()

    assert changed_key != default_key
    assert PRICING_URL in changed_key


@respx.mock
async def test_changing_the_model_does_not_reuse_cached_yaml(monkeypatch: pytest.MonkeyPatch):
    transform = mock_amint(respx.mock)
    cache = MemoryCache()

    first, first_amint = make_workflow(cache)
    await first.ensure_pricing_yaml(PRICING_URL)
    await first.ensure_pricing_yaml(PRICING_URL)
    await first_amint.aclose()
    assert transform.call_count == 1

    monkeypatch.setenv("AMINT_LLM_MODEL", "qwen3:32b")
    second, second_amint = make_workflow(cache)
    await second.ensure_pricing_yaml(PRICING_URL)
    await second_amint.aclose()
    assert transform.call_count == 2
