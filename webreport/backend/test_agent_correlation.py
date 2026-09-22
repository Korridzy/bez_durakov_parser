"""Tests for per-call model correlation and LiteLLM logger adoption."""

import asyncio
import importlib
import io
import json
import os
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast
from unittest.mock import AsyncMock, patch

import structlog

from bd_shared import logging_setup
from bd_shared.config import ENVIRONMENT

correlation = importlib.import_module("agent.correlation")
CorrelatedModelClient = correlation.CorrelatedModelClient

MODEL = "litellm_proxy/gpt-4o"
TRACE_ID = "0123456789abcdef0123456789abcdef"
BACKEND_ROOT = Path(__file__).resolve().parent


class StubMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class StubResponse(StubMessage):
    tool_calls: list[object] = []


class BoundInvoker(Protocol):
    async def ainvoke(self, messages: Sequence[StubMessage]) -> StubResponse: ...


class StubTool:
    name = "stub_tool"
    description = "A tool used only by the correlation tests."


class RecordingBoundModel:
    def __init__(self, response: StubResponse) -> None:
        self.response = response
        self.requests: list[tuple[Sequence[StubMessage], dict[str, object]]] = []

    async def ainvoke(
        self,
        messages: Sequence[StubMessage],
        **kwargs: object,
    ) -> StubResponse:
        self.requests.append((messages, dict(kwargs)))
        return self.response


class NoKwargsBoundModel:
    """A legacy test double whose invocation contract accepts no kwargs."""

    def __init__(self, response: StubResponse) -> None:
        self.response = response
        self.requests: list[Sequence[StubMessage]] = []

    async def ainvoke(self, messages: Sequence[StubMessage]) -> StubResponse:
        self.requests.append(messages)
        return self.response


class RaisingBoundModel:
    async def ainvoke(
        self,
        messages: Sequence[StubMessage],
        **kwargs: object,
    ) -> StubResponse:
        del messages, kwargs
        raise RuntimeError("scripted model failure")


class RecordingClient:
    def __init__(self, bound: BoundInvoker) -> None:
        self.bound = bound
        self.bound_tools: list[object] = []
        self.parallel_tool_calls: bool | None = None

    def bind_tools(
        self,
        tools: Sequence[object],
        *,
        parallel_tool_calls: bool,
    ) -> BoundInvoker:
        self.bound_tools = list(tools)
        self.parallel_tool_calls = parallel_tool_calls
        return self.bound


class InterleavingBoundModel:
    def __init__(
        self,
        entered: dict[str, asyncio.Event],
        release: asyncio.Event,
    ) -> None:
        self.entered = entered
        self.release = release
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.response = StubResponse("ok")

    async def ainvoke(
        self,
        messages: Sequence[StubMessage],
        **kwargs: object,
    ) -> StubResponse:
        task_name = messages[0].content
        self.entered[task_name].set()
        await self.release.wait()
        self.requests.append((task_name, dict(kwargs)))
        return self.response


class CorrelatedModelClientTests(unittest.IsolatedAsyncioTestCase):
    stream: io.StringIO | None = None

    def setUp(self) -> None:
        logging_setup._reset_for_tests()
        stream = io.StringIO()
        self.stream = stream
        logging_setup.configure_logging(
            "test-agent-correlation",
            log_format="json",
            stream=stream,
        )

    def tearDown(self) -> None:
        logging_setup._reset_for_tests()
        self.stream = None

    def records(self) -> list[dict[str, object]]:
        assert self.stream is not None
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    @staticmethod
    def wrap(bound: BoundInvoker) -> tuple[RecordingClient, BoundInvoker]:
        client = RecordingClient(bound)
        wrapped = CorrelatedModelClient(client, model=MODEL, role="agent")
        return client, cast(
            BoundInvoker,
            wrapped.bind_tools([StubTool()], parallel_tool_calls=False),
        )

    async def test_correlation_contract_reaches_exact_kwargs(self):
        response = StubResponse("ok")
        recorder = RecordingBoundModel(response)
        client, bound = self.wrap(recorder)
        messages = [StubMessage("hello")]

        with (
            patch.object(
                correlation.secrets,
                "token_hex",
                return_value="fedcba9876543210",
            ),
            structlog.contextvars.bound_contextvars(
                request_id="r1",
                trace_id=TRACE_ID,
                session_id="s1",
            ),
        ):
            returned = await bound.ainvoke(messages)

        self.assertEqual(len(client.bound_tools), 1)
        self.assertIsInstance(client.bound_tools[0], StubTool)
        self.assertIs(client.parallel_tool_calls, False)
        self.assertIs(returned, response)
        self.assertIs(recorder.requests[0][0], messages)
        kwargs = recorder.requests[0][1]
        self.assertEqual(
            kwargs,
            {
                "extra_body": {
                    "metadata": {
                        "request_id": "r1",
                        "session_id": "s1",
                        "trace_metadata": {"request_id": "r1"},
                        "generation_name": "agent",
                        "tags": ["webreport", ENVIRONMENT],
                    }
                },
                "extra_headers": {
                    "X-Request-ID": "r1",
                    "traceparent": f"00-{TRACE_ID}-fedcba9876543210-01",
                },
            },
        )
        extra_headers = cast(dict[str, str], kwargs["extra_headers"])
        traceparent = extra_headers["traceparent"]
        self.assertRegex(
            traceparent,
            r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$",
        )
        self.assertEqual(traceparent.split("-")[1], TRACE_ID)
        self.assertNotIn("user", kwargs)
        extra_body = cast(dict[str, object], kwargs["extra_body"])
        metadata = cast(dict[str, object], extra_body["metadata"])
        self.assertTrue(
            {"trace_id", "existing_trace_id", "generation_id"}.isdisjoint(
                metadata
            )
        )

    async def test_two_calls_in_one_context_get_distinct_span_ids(self):
        recorder = RecordingBoundModel(StubResponse("ok"))
        _, bound = self.wrap(recorder)

        with (
            patch.object(
                correlation.secrets,
                "token_hex",
                side_effect=["1" * 16, "2" * 16],
            ),
            structlog.contextvars.bound_contextvars(
                request_id="r1",
                trace_id=TRACE_ID,
            ),
        ):
            await bound.ainvoke([StubMessage("first")])
            await bound.ainvoke([StubMessage("second")])

        traceparents = [
            cast(dict[str, str], request[1]["extra_headers"])["traceparent"]
            for request in recorder.requests
        ]
        self.assertEqual(
            traceparents,
            [
                f"00-{TRACE_ID}-{'1' * 16}-01",
                f"00-{TRACE_ID}-{'2' * 16}-01",
            ],
        )
        self.assertNotEqual(traceparents[0], traceparents[1])

    async def test_user_id_adds_trace_user_id_metadata(self):
        recorder = RecordingBoundModel(StubResponse("ok"))
        _, bound = self.wrap(recorder)

        with structlog.contextvars.bound_contextvars(user_id="u1"):
            await bound.ainvoke([StubMessage("hello")])

        self.assertEqual(
            recorder.requests[0][1],
            {
                "extra_body": {
                    "metadata": {
                        "generation_name": "agent",
                        "tags": ["webreport", ENVIRONMENT],
                        "trace_user_id": "u1",
                    }
                }
            },
        )

    async def test_request_id_alone_builds_metadata_and_header(self):
        recorder = RecordingBoundModel(StubResponse("ok"))
        _, bound = self.wrap(recorder)

        with structlog.contextvars.bound_contextvars(request_id="r1"):
            await bound.ainvoke([StubMessage("hello")])

        self.assertEqual(
            recorder.requests[0][1],
            {
                "extra_body": {
                    "metadata": {
                        "request_id": "r1",
                        "trace_metadata": {"request_id": "r1"},
                        "generation_name": "agent",
                        "tags": ["webreport", ENVIRONMENT],
                    }
                },
                "extra_headers": {"X-Request-ID": "r1"},
            },
        )

    async def test_session_id_alone_has_metadata_without_headers(self):
        recorder = RecordingBoundModel(StubResponse("ok"))
        _, bound = self.wrap(recorder)

        with structlog.contextvars.bound_contextvars(session_id="s1"):
            await bound.ainvoke([StubMessage("hello")])

        self.assertEqual(
            recorder.requests[0][1],
            {
                "extra_body": {
                    "metadata": {
                        "session_id": "s1",
                        "generation_name": "agent",
                        "tags": ["webreport", ENVIRONMENT],
                    }
                }
            },
        )
        self.assertNotIn("extra_headers", recorder.requests[0][1])

    async def test_no_context_records_an_empty_kwargs_mapping(self):
        recorder = RecordingBoundModel(StubResponse("ok"))
        _, bound = self.wrap(recorder)

        await bound.ainvoke([StubMessage("hello")])

        self.assertEqual(recorder.requests[0][1], {})

    async def test_no_context_passes_no_kwargs_to_a_no_kwargs_stub(self):
        response = StubResponse("ok")
        recorder = NoKwargsBoundModel(response)
        _, bound = self.wrap(recorder)
        messages = [StubMessage("hello")]

        returned = await bound.ainvoke(messages)

        self.assertIs(returned, response)
        self.assertEqual(recorder.requests, [messages])

    async def test_success_emits_a_correlated_structured_record(self):
        recorder = RecordingBoundModel(StubResponse("ok"))
        _, bound = self.wrap(recorder)

        with structlog.contextvars.bound_contextvars(request_id="r1"):
            await bound.ainvoke([StubMessage("hello")])

        [record] = [item for item in self.records() if item["event"] == "llm_call"]
        self.assertEqual(record["model"], MODEL)
        self.assertEqual(record["role"], "agent")
        self.assertIsInstance(record["duration_ms"], (int, float))
        self.assertEqual(record["request_id"], "r1")
        self.assertNotIn("messages", record)
        self.assertNotIn("prompt", record)
        self.assertNotIn("response", record)

    async def test_failure_emits_exception_record_and_still_propagates(self):
        _, bound = self.wrap(RaisingBoundModel())

        with (
            structlog.contextvars.bound_contextvars(request_id="r1"),
            self.assertRaises(RuntimeError),
        ):
            await bound.ainvoke([StubMessage("hello")])

        [record] = [
            item for item in self.records() if item["event"] == "llm_call_failed"
        ]
        self.assertEqual(record["level"], "error")
        self.assertEqual(record["model"], MODEL)
        self.assertEqual(record["role"], "agent")
        self.assertIsInstance(record["duration_ms"], (int, float))
        self.assertEqual(record["request_id"], "r1")
        self.assertIn("exception", record)

    async def test_concurrent_calls_keep_their_own_context(self):
        entered = {"a": asyncio.Event(), "b": asyncio.Event()}
        release = asyncio.Event()
        recorder = InterleavingBoundModel(entered, release)
        _, bound = self.wrap(recorder)

        async def invoke(
            name: str,
            request_id: str,
            trace_id: str,
            session_id: str,
        ) -> object:
            with structlog.contextvars.bound_contextvars(
                request_id=request_id,
                trace_id=trace_id,
                session_id=session_id,
            ):
                return await bound.ainvoke([StubMessage(name)])

        def span_for_context(nbytes: int) -> str:
            self.assertEqual(nbytes, 8)
            request_id = structlog.contextvars.get_contextvars()["request_id"]
            return {"request-a": "1" * 16, "request-b": "2" * 16}[
                request_id
            ]

        with patch.object(
            correlation.secrets,
            "token_hex",
            side_effect=span_for_context,
        ):
            tasks = [
                asyncio.create_task(
                    invoke("a", "request-a", "a" * 32, "session-a")
                ),
                asyncio.create_task(
                    invoke("b", "request-b", "b" * 32, "session-b")
                ),
            ]
            try:
                await asyncio.wait_for(
                    asyncio.gather(entered["a"].wait(), entered["b"].wait()),
                    5,
                )
                release.set()
                await asyncio.wait_for(asyncio.gather(*tasks), 5)
            finally:
                release.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        recorded = dict(recorder.requests)
        self.assertEqual(
            recorded["a"],
            {
                "extra_body": {
                    "metadata": {
                        "request_id": "request-a",
                        "session_id": "session-a",
                        "trace_metadata": {"request_id": "request-a"},
                        "generation_name": "agent",
                        "tags": ["webreport", ENVIRONMENT],
                    }
                },
                "extra_headers": {
                    "X-Request-ID": "request-a",
                    "traceparent": f"00-{'a' * 32}-{'1' * 16}-01",
                },
            },
        )
        self.assertEqual(
            recorded["b"],
            {
                "extra_body": {
                    "metadata": {
                        "request_id": "request-b",
                        "session_id": "session-b",
                        "trace_metadata": {"request_id": "request-b"},
                        "generation_name": "agent",
                        "tags": ["webreport", ENVIRONMENT],
                    }
                },
                "extra_headers": {
                    "X-Request-ID": "request-b",
                    "traceparent": f"00-{'b' * 32}-{'2' * 16}-01",
                },
            },
        )

    async def test_real_chat_litellm_forwards_kwargs_to_sdk_boundary(self):
        chat_models = importlib.import_module("langchain_litellm")
        messages = importlib.import_module("langchain_core.messages")
        pydantic = importlib.import_module("pydantic")
        trivial_tool = pydantic.create_model("TrivialTool", value=(str, ...))
        trivial_tool.__doc__ = "Echo one value for the SDK-boundary test."
        completion = AsyncMock(
            return_value={
                "id": "x",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                        "index": 0,
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
                "model": "gpt-4o",
            }
        )
        with patch.dict(os.environ, {"LITELLM_LOCAL_MODEL_COST_MAP": "True"}):
            client = chat_models.ChatLiteLLM(
                model=MODEL,
                api_base="http://litellm:4000",
                api_key="sk-noop",
            )
            wrapped = CorrelatedModelClient(
                client,
                model=MODEL,
                role="agent",
            )
            bound = wrapped.bind_tools([trivial_tool], parallel_tool_calls=False)
            with (
                patch.object(client.client, "acompletion", completion),
                patch.object(
                    correlation.secrets,
                    "token_hex",
                    return_value="fedcba9876543210",
                ),
                structlog.contextvars.bound_contextvars(
                    request_id="r1",
                    trace_id=TRACE_ID,
                    session_id="s1",
                ),
            ):
                response = await bound.ainvoke(
                    [messages.HumanMessage(content="hello")]
                )

        self.assertEqual(response.content, "hi")
        completion.assert_awaited_once()
        await_args = completion.await_args
        self.assertIsNotNone(await_args)
        assert await_args is not None
        sdk_kwargs = await_args.kwargs
        self.assertEqual(
            sdk_kwargs["extra_body"],
            {
                "metadata": {
                    "request_id": "r1",
                    "session_id": "s1",
                    "trace_metadata": {"request_id": "r1"},
                    "generation_name": "agent",
                    "tags": ["webreport", ENVIRONMENT],
                }
            },
        )
        self.assertEqual(
            sdk_kwargs["extra_headers"],
            {
                "X-Request-ID": "r1",
                "traceparent": f"00-{TRACE_ID}-fedcba9876543210-01",
            },
        )
        self.assertNotIn("user", sdk_kwargs)


class FactoryLoggerAdoptionTests(unittest.TestCase):
    def run_factory_probe(self, factory_name: str) -> subprocess.CompletedProcess[str]:
        source = f"""
import logging
import litellm
logger = logging.getLogger("LiteLLM")
before = len(logger.handlers)
assert before > 0, before
from agents.report_runtime import {factory_name}
{factory_name}()
assert logger.handlers == [], logger.handlers
assert logger.propagate is True
print(f"factory={factory_name} before={{before}} after={{len(logger.handlers)}} propagate={{logger.propagate}}")
"""
        environment = {
            **os.environ,
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "PYTHONPATH": "/",
        }
        return subprocess.run(
            [sys.executable, "-c", source],
            cwd=BACKEND_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_agent_factory_adopts_litellm_logger(self):
        completed = self.run_factory_probe("_new_model_client")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("after=0 propagate=True", completed.stdout)

    def test_gate_factory_adopts_litellm_logger(self):
        completed = self.run_factory_probe("_new_gate_model_client")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("after=0 propagate=True", completed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
