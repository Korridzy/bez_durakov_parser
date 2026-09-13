"""Model connections over ChatLiteLLM, preserving the existing reasoning filter."""

import re
from datetime import date, datetime, timezone

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

# WebReport's shortlist, reviewed 2026-09-13 against
# https://developers.openai.com/api/docs/models . /models has no recommendation
# field. Exact IDs are intersected with the provider's live catalog below; never
# infer a recommendation for a dated snapshot or a similarly named custom model.
MODEL_RECOMMENDATIONS = {
    "openai": {
        "gpt-5.6-terra": ("GPT-5.6 Terra", "Баланс качества и стоимости"),
        "gpt-6-astra": ("GPT-6 Astra", "Для самых сложных задач"),
        "gpt-5.6-luna": ("GPT-5.6 Luna", "Быстрые и недорогие ответы"),
        "gpt-5.6-sol": ("GPT-5.6 Sol", "Для сложной профессиональной работы"),
    },
}


def connection_base(provider, base_url=""):
    entry = next((p for p in MODEL_PROVIDERS if p["id"] == provider), None)
    if entry is None:
        raise ConnectorError("Выберите поставщика модели.")
    return public_url(base_url) if provider == "custom" else entry["base_url"]


def normalize_model_key(raw):
    """Reject obvious paste mistakes, without guessing provider key schemas.

    OpenAI documents an opaque string, not a fixed key length or prefix:
    https://developers.openai.com/api/reference/overview#authentication
    Keep these messages in sync with frontend-web/src/model-key.ts.
    """
    token = raw.strip()
    if not token:
        raise ConnectorError("Введите API-ключ.")
    if re.match(r"^(?:authorization\s*:|bearer\s)", token, re.IGNORECASE):
        raise ConnectorError("Вставьте только ключ, без Authorization и Bearer.")
    if re.search(r"\s", token):
        raise ConnectorError(
            "В ключе есть пробелы или переносы строк. Скопируйте его заново."
        )
    if re.search(r"[^\x21-\x7e]", token):
        raise ConnectorError(
            "В ключе есть посторонние или невидимые символы. Скопируйте его заново."
        )
    return token


def discover_models(provider, token, base_url=""):
    token = normalize_model_key(token)
    base = connection_base(provider, base_url)
    data = request_json(
        "GET", base + "/models", headers={"Authorization": "Bearer " + token}
    )
    recommendations = MODEL_RECOMMENDATIONS.get(provider, {})
    ranks = {name: rank for rank, name in enumerate(recommendations)}
    models = {}
    for entry in data.get("data", []):
        name = entry.get("id", "")
        # This is a coarse exclusion filter, not a runtime compatibility probe.
        # The graph requires text output, function calling and reasoning round-trip.
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
                "transcrib",
                "transcription",
                "gpt-live",
                "claude",
                "anthropic",
            )
        ):
            continue
        if provider == "openai" and not re.match(r"^(gpt-|o[134])", name):
            continue
        shutdown = None
        if provider == "openai" and entry.get("shutdown_date"):
            try:
                shutdown = date.fromisoformat(entry["shutdown_date"])
            except (TypeError, ValueError):
                pass
        if shutdown and shutdown <= datetime.now(timezone.utc).date():
            continue
        model = {"id": name, "name": entry.get("name") or name}
        if shutdown:
            model["shutdown_date"] = shutdown.isoformat()
        elif name in recommendations:
            model["name"], model["recommendation"] = recommendations[name]
        models[name] = model
    return sorted(
        models.values(),
        key=lambda m: (
            ranks[m["id"]] if "recommendation" in m else len(ranks),
            m["id"],
        ),
    )


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
