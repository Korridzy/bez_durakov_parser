"""Per-request progress, shared by the graph and the local job API."""

from contextvars import ContextVar
import asyncio

from langchain_core.callbacks import AsyncCallbackHandler

progress_sink = ContextVar("workspace_progress_sink", default=None)


def emit(event):
    sink = progress_sink.get()
    if sink:
        sink(event)


class ProgressCallback(AsyncCallbackHandler):
    async def on_retry(self, retry_state, **kwargs):
        emit(
            {
                "type": "status",
                "text": "Провайдер не ответил. Повторная попытка подключения…",
            }
        )


class RetryingModelClient:
    """Retry transient provider failures with a visible event for every attempt."""

    def __init__(self, client, retries):
        self._client = client
        self._retries = min(max(retries, 0), 4)

    def bind_tools(self, tools, *, parallel_tool_calls):
        bound = self._client.bind_tools(tools, parallel_tool_calls=parallel_tool_calls)
        retries = self._retries

        class Bound:
            async def ainvoke(self, messages):
                for attempt in range(retries + 1):
                    try:
                        return await bound.ainvoke(messages)
                    except Exception as error:
                        status = getattr(error, "status_code", None)
                        transient = status in {408, 429, 500, 502, 503, 504} or any(
                            name in type(error).__name__
                            for name in ("Timeout", "Connection", "RateLimit")
                        )
                        if not transient or attempt == retries:
                            raise
                        emit(
                            {
                                "type": "status",
                                "text": f"Модель временно недоступна. Переподключение {attempt + 1} из {retries}…",
                            }
                        )
                        await asyncio.sleep(min(2**attempt, 8))

        return Bound()
