import importlib
import sys
import unittest
from asyncio import Event, create_task, sleep

sys.path.insert(0, "/")

net_guard = importlib.import_module("test_net_guard")


def setUpModule() -> None:
    net_guard.install()


def _tool_call(call_id: str) -> dict[str, object]:
    return {
        "name": "get_all_teams",
        "args": {},
        "id": call_id,
        "type": "tool_call",
    }


class _ScriptedFailure(RuntimeError):
    pass


class _SaverUnavailable(RuntimeError):
    pass


class _ScriptedModel:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses

    def bind_tools(self, tools, *, parallel_tool_calls):
        return self

    async def ainvoke(self, messages):
        if not self.responses:
            raise AssertionError("Scripted model exhausted")
        return self.responses.pop(0)


class _TimeoutAfterStepModel:
    def __init__(self, step: object) -> None:
        self.step = step
        self.calls = 0
        self.second_call_started = Event()

    def bind_tools(self, tools, *, parallel_tool_calls):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return self.step
        self.second_call_started.set()
        await sleep(3600)
        raise AssertionError("Unreachable after timeout")


class _TimeoutBeforeStepModel:
    def bind_tools(self, tools, *, parallel_tool_calls):
        return self

    async def ainvoke(self, messages):
        await sleep(3600)
        raise AssertionError("Unreachable after timeout")


class _FailureAfterStepModel:
    def __init__(self, step: object) -> None:
        self.step = step
        self.calls = 0

    def bind_tools(self, tools, *, parallel_tool_calls):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return self.step
        raise _ScriptedFailure("model exploded")


class _RepeatingModel:
    def __init__(self, step_factory) -> None:
        self.step_factory = step_factory

    def bind_tools(self, tools, *, parallel_tool_calls):
        return self

    async def ainvoke(self, messages):
        return self.step_factory()


class _BrokenSaver:
    async def aget_tuple(self, config):
        raise _SaverUnavailable("checkpoint lookup failed")


class _RuntimeImports:
    @classmethod
    def setUpClass(cls) -> None:
        cls.memory = importlib.import_module("langgraph.checkpoint.memory")
        cls.messages = importlib.import_module("langchain_core.messages")
        cls.report_agents = importlib.import_module("agents.report_runtime")
        cls.support = importlib.import_module("test_agent_support")

    def make_agent(self, model, *, timeout: float = 60):
        saver = self.memory.InMemorySaver()
        service = self.support.StubService()
        service.results["get_all_teams"] = []
        return (
            self.report_agents.ReportAgentSystem(
                service=service,
                model_client=model,
                checkpointer=saver,
                timeout_seconds=timeout,
            ),
            saver,
        )

    def reasoning_step(self, reasoning: str):
        return self.messages.AIMessage(
            content="",
            additional_kwargs={"reasoning_content": reasoning},
            tool_calls=[_tool_call("teams")],
        )


class TestReasoningPropagation(_RuntimeImports, unittest.IsolatedAsyncioTestCase):
    async def test_success_carries_current_turn_reasoning(self) -> None:
        # Given a reasoning-bearing tool step followed by a final answer.
        model = _ScriptedModel(
            [self.reasoning_step("Step 1"), self.messages.AIMessage(content="Ready")]
        )
        system, _saver = self.make_agent(model)

        # When the agent completes its turn.
        response = await system.process_user_request("Show teams", "reasoning-success")

        # Then the report response exposes the current-turn reasoning.
        self.assertTrue(response["success"])
        self.assertEqual("Step 1", response["reasoning"])

    async def test_success_has_none_reasoning_when_model_omits_it(self) -> None:
        # Given a plain final answer without reasoning metadata.
        system, _saver = self.make_agent(
            _ScriptedModel([self.messages.AIMessage(content="Ready")])
        )

        # When the agent completes its turn.
        response = await system.process_user_request("Show teams", "plain-success")

        # Then the required response key is explicitly null.
        self.assertIn("reasoning", response)
        self.assertIsNone(response["reasoning"])

    async def test_success_normalizes_block_list_final_answer(self) -> None:
        # Given a final answer represented as provider content blocks.
        system, _saver = self.make_agent(
            _ScriptedModel(
                [
                    self.messages.AIMessage(
                        content=[
                            {"type": "text", "text": "A"},
                            {"type": "text", "text": "B"},
                        ]
                    )
                ]
            )
        )

        # When the agent completes its turn.
        response = await system.process_user_request("Show teams", "block-answer")

        # Then only text blocks reach the string response boundary.
        self.assertEqual("A\n\nB", response["message"])



class TestFailurePartialReasoning(_RuntimeImports, unittest.IsolatedAsyncioTestCase):
    async def test_timeout_after_completed_step_recovers_reasoning(self) -> None:
        # Given a completed reasoning-bearing tool step and a blocked next model call.
        model = _TimeoutAfterStepModel(self.reasoning_step("Saved step"))
        system, _saver = self.make_agent(model, timeout=1)

        # When the agent times out during its next step.
        request = create_task(
            system.process_user_request("Show teams", "timeout-after-step")
        )
        await model.second_call_started.wait()
        response = await request

        # Then the latest completed checkpoint supplies partial reasoning.
        self.assertEqual("timeout", response["error"])
        self.assertEqual("Saved step", response["reasoning"])

    async def test_timeout_before_completed_step_has_no_reasoning(self) -> None:
        # Given a model that blocks before producing a checkpointable response.
        system, _saver = self.make_agent(_TimeoutBeforeStepModel(), timeout=0.01)

        # When the initial agent call times out.
        response = await system.process_user_request("Show teams", "timeout-before-step")

        # Then no mid-step thought is fabricated.
        self.assertEqual("timeout", response["error"])
        self.assertIsNone(response["reasoning"])

    async def test_recursion_limit_recovers_reasoning(self) -> None:
        # Given a model that repeatedly emits a reasoning-bearing tool call.
        system, _saver = self.make_agent(
            _RepeatingModel(lambda: self.reasoning_step("Loop reasoning"))
        )

        # When LangGraph reaches its recursion limit.
        response = await system.process_user_request("Show teams", "recursion")

        # Then the controlled failure carries best-effort partial reasoning.
        self.assertEqual("recursion_limit", response["error"])
        self.assertIn("Loop reasoning", response["reasoning"])

    async def test_agent_exception_preserves_error_and_recovers_reasoning(self) -> None:
        # Given a completed reasoning-bearing tool step followed by a model exception.
        system, _saver = self.make_agent(
            _FailureAfterStepModel(self.reasoning_step("Before failure"))
        )

        # When the second model call raises.
        response = await system.process_user_request("Show teams", "model-error")

        # Then the original error and checkpointed partial reasoning both survive.
        self.assertEqual("model exploded", response["error"])
        self.assertEqual("Before failure", response["reasoning"])

    async def test_broken_saver_does_not_mask_original_agent_error(self) -> None:
        # Given an agent failure after a saved step but a broken recovery lookup.
        system, _saver = self.make_agent(
            _FailureAfterStepModel(self.reasoning_step("Unrecoverable step"))
        )
        system._saver = _BrokenSaver()

        # When recovery itself cannot read the checkpoint.
        response = await system.process_user_request("Show teams", "broken-saver")

        # Then the original controlled failure remains intact without reasoning.
        self.assertEqual("model exploded", response["error"])
        self.assertIsNone(response["reasoning"])


if __name__ == "__main__":
    unittest.main()
