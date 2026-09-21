"""Offline contract test for LiteLLM proxy correlation exported to Langfuse."""

import asyncio
import json
import os
import unittest

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import litellm  # noqa: E402
from litellm.integrations.langfuse.langfuse_otel import (  # noqa: E402
    LangfuseOtelLogger,
)
from litellm.integrations.opentelemetry import OpenTelemetryConfig  # noqa: E402
from litellm.litellm_core_utils.logging_worker import (  # noqa: E402
    GLOBAL_LOGGING_WORKER,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode  # noqa: E402


TRACE_ID = "0123456789abcdef0123456789abcdef"
REQUEST_ID = "proxy-contract-request"
SESSION_ID = "proxy-contract-session"
USER_ID = "proxy-contract-user"
SUCCESS_SPAN_IDS = ("1111111111111111", "2222222222222222")
FAILURE_SPAN_ID = "3333333333333333"


def _metadata(generation_name: str) -> dict[str, object]:
    return {
        "request_id": REQUEST_ID,
        "session_id": SESSION_ID,
        "trace_user_id": USER_ID,
        "trace_metadata": {"request_id": REQUEST_ID},
        "generation_name": generation_name,
        "tags": ["webreport", "development"],
    }


def _proxy_request(span_id: str) -> dict[str, dict[str, str]]:
    return {
        "headers": {
            "traceparent": f"00-{TRACE_ID}-{span_id}-01",
            "x-request-id": REQUEST_ID,
        }
    }


async def _drain_logging_tasks() -> None:
    current = asyncio.current_task()
    worker = GLOBAL_LOGGING_WORKER._worker_task
    tasks = tuple(
        task
        for task in asyncio.all_tasks()
        if task is not current and task is not worker
    )
    _ = await asyncio.gather(*tasks, return_exceptions=True)
    await GLOBAL_LOGGING_WORKER.flush()
    await GLOBAL_LOGGING_WORKER.stop()


class LangfuseProxyContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_logger_exports_correlated_success_and_failure_spans(self) -> None:
        exporter = InMemorySpanExporter()
        logger = LangfuseOtelLogger(
            config=OpenTelemetryConfig(
                exporter=exporter,
                skip_set_global=True,
            ),
            callback_name="langfuse_otel",
        )
        original_callbacks = litellm.callbacks
        litellm.callbacks = [logger]

        try:
            for span_id in SUCCESS_SPAN_IDS:
                response = await litellm.acompletion(
                    model="openai/gpt-4o",
                    messages=[{"role": "user", "content": "hello"}],
                    mock_response="ok",
                    api_key="sk-test",
                    metadata=_metadata("agent"),
                    proxy_server_request=_proxy_request(span_id),
                )
                self.assertEqual(response.choices[0].message.content, "ok")

            await _drain_logging_tasks()

            with self.assertRaises(litellm.InternalServerError):
                await litellm.acompletion(
                    model="openai/gpt-4o",
                    messages=[{"role": "user", "content": "fail"}],
                    mock_response=Exception("boom"),
                    num_retries=0,
                    api_key="sk-test",
                    metadata=_metadata("scope_gate"),
                    proxy_server_request=_proxy_request(FAILURE_SPAN_ID),
                )

            await _drain_logging_tasks()
            logger._tracer_provider.force_flush()

            spans = exporter.get_finished_spans()
            self.assertTrue(
                any(
                    span.attributes.get("session.id") == SESSION_ID
                    for span in spans
                ),
                "callback did not map session.id",
            )
            generation_spans = [
                span
                for span in spans
                if span.attributes.get("langfuse.observation.type") == "generation"
            ]
            self.assertEqual(len(generation_spans), 3)

            for span in generation_spans:
                self.assertEqual(f"{span.context.trace_id:032x}", TRACE_ID)
                self.assertEqual(span.attributes.get("user.id"), USER_ID)
                self.assertIsNotNone(span.end_time)
                self.assertGreater(span.end_time, span.start_time)
                self.assertIn("llm.provider", span.attributes)

            success_spans = [
                span
                for span in generation_spans
                if span.attributes.get("langfuse.generation.name") == "agent"
            ]
            self.assertEqual(len(success_spans), 2)
            self.assertCountEqual(
                [f"{span.parent.span_id:016x}" for span in success_spans],
                SUCCESS_SPAN_IDS,
            )
            for span in success_spans:
                attributes = span.attributes
                self.assertEqual(attributes.get("session.id"), SESSION_ID)
                self.assertEqual(
                    attributes.get("langfuse.generation.name"), "agent"
                )
                self.assertIn(
                    "webreport", json.loads(attributes["langfuse.trace.tags"])
                )
                self.assertEqual(
                    json.loads(attributes["langfuse.trace.metadata"])["request_id"],
                    REQUEST_ID,
                )
                for name in (
                    "llm.model_name",
                    "llm.token_count.prompt",
                    "llm.token_count.completion",
                    "langfuse.observation.input",
                    "langfuse.observation.output",
                ):
                    self.assertIn(name, attributes)
                self.assertTrue(
                    "llm.cost.total" in attributes
                    or "llm.response.cost" in attributes
                )

            [failure_span] = [
                span
                for span in generation_spans
                if span.attributes.get("langfuse.generation.name") == "scope_gate"
            ]
            self.assertEqual(failure_span.status.status_code, StatusCode.ERROR)
            self.assertEqual(
                failure_span.attributes.get("error.type"), "InternalServerError"
            )
            self.assertEqual(
                f"{failure_span.parent.span_id:016x}",
                FAILURE_SPAN_ID,
            )
            self.assertIn("litellm.trace_id", failure_span.attributes)

            for span in spans:
                for value in span.attributes.values():
                    self.assertNotIn("sk-test", str(value))
        finally:
            litellm.callbacks = original_callbacks
            await GLOBAL_LOGGING_WORKER.stop()
            logger._tracer_provider.force_flush()
            logger._tracer_provider.shutdown()


if __name__ == "__main__":
    _ = unittest.main()
