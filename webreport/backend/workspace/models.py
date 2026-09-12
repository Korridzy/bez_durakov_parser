"""Model connections over ChatLiteLLM, preserving the existing reasoning filter."""

import re

from agent.reasoning import OutboundReasoningFilter
from connectors.http import ConnectorError, public_url, request_json

MODEL_PROVIDERS = [
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1"},
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
    },
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1"},
    {
        "id": "google",
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
    },
    {"id": "custom", "name": "Совместимый API", "base_url": ""},
]


def connection_base(provider, base_url=""):
    entry = next((p for p in MODEL_PROVIDERS if p["id"] == provider), None)
    if entry is None:
        raise ConnectorError("Выберите поставщика модели.")
    return public_url(base_url) if provider == "custom" else entry["base_url"]


def discover_models(provider, token, base_url=""):
    if not token.strip():
        raise ConnectorError("Введите API-ключ.")
    base = connection_base(provider, base_url)
    data = request_json(
        "GET", base + "/models", headers={"Authorization": "Bearer " + token}
    )
    models = []
    for entry in data.get("data", []):
        name = entry.get("id", "")
        # The graph requires function calling; audio, image, embeddings and Anthropic
        # thinking-block transports do not satisfy its text/reasoning contract.
        if not name or any(
            part in name.lower()
            for part in (
                "embedding",
                "whisper",
                "tts",
                "image",
                "dall-e",
                "moderation",
                "realtime",
                "audio",
                "claude",
                "anthropic",
            )
        ):
            continue
        if provider == "openai" and not re.match(r"^(gpt-|o[134])", name):
            continue
        models.append({"id": name, "name": entry.get("name", name)})
    return sorted(models, key=lambda m: m["id"], reverse=True)[:300]


def reasoning_options(model_id):
    name = model_id.lower().split("/")[-1]
    if re.match(r"^(gpt-5|gpt-6|o[134])", name):
        return ["auto", "low", "medium", "high"]
    return ["auto"]


def make_client(model, credentials, effort="auto"):
    from langchain_litellm import ChatLiteLLM
    from bd_shared import config
    from workspace.progress import ProgressCallback, RetryingModelClient

    if effort not in reasoning_options(model["model_id"]):
        raise ConnectorError("Эта модель не поддерживает выбранное усилие рассуждений.")
    if model["id"] == "system":
        model_name = "litellm_proxy/" + config.AGENT_MODEL
        base, key = config.LITELLM_BASE_URL, "sk-noop"
    else:
        base = connection_base(model["provider"], credentials.get("base_url", ""))
        key = credentials["token"]
        # LiteLLM maps Responses-only OpenAI models onto the common message contract.
        prefix = (
            "openai/responses/"
            if model["provider"] == "openai"
            and re.match(r"^gpt-[56]", model["model_id"])
            else "openai/"
        )
        model_name = prefix + model["model_id"]
    kwargs = {"num_retries": 0}
    if effort != "auto":
        kwargs["reasoning_effort"] = effort
    return RetryingModelClient(
        OutboundReasoningFilter(
            ChatLiteLLM(
                model=model_name,
                api_base=base,
                api_key=key,
                request_timeout=config.LLM_REQUEST_TIMEOUT_SECONDS,
                model_kwargs=kwargs,
                callbacks=[ProgressCallback()],
            )
        ),
        config.LLM_MAX_RETRIES,
    )
