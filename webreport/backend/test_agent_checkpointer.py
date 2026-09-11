import asyncio
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/")


class TestCheckpointerCases(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkpoint = importlib.import_module("langgraph.checkpoint.sqlite.aio")
        cls.config = importlib.import_module("bd_shared.config")
        cls.graph_module = importlib.import_module("agent.graph")
        cls.registry_module = importlib.import_module("agent.registry")
        cls.tools_module = importlib.import_module("agent.tools")
        cls.messages = importlib.import_module("langchain_core.messages")
        cls.graph_cases = importlib.import_module("test_agent_graph")
        cls.support = importlib.import_module("test_agent_support")
        cls.knowledge_module = importlib.import_module("agent.knowledge")
        cls.runtime = importlib.import_module("agents.report_runtime")

    def _build_graph(self, saver, model, knowledge=None):
        service = self.support.StubService()
        registry = self.registry_module.ToolRegistry(service)
        tools = self.tools_module.build_tools(registry, self.config, knowledge=knowledge)
        graph = self.graph_module.build_graph(
            model, tools, saver, "Test system prompt for checkpointer tests."
        )
        return service, graph

    async def test_checkpoint_round_trip_preserves_history(self):
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            model = self.graph_cases.ScriptedModel(
                [
                    self.messages.AIMessage(
                        content="",
                        tool_calls=[
                            self.graph_cases.tool_call("get_all_teams", {}, "turn-1-tool")
                        ],
                    ),
                    self.messages.AIMessage(content="Первый ответ."),
                    self.messages.AIMessage(
                        content="",
                        tool_calls=[
                            self.graph_cases.tool_call("get_all_teams", {}, "turn-2-tool")
                        ],
                    ),
                    self.messages.AIMessage(content="Второй ответ."),
                ]
            )
            service, graph = self._build_graph(saver, model)
            service.results["get_all_teams"] = []

            first = await self.graph_module.arun(graph, "Покажи команды", "t1")
            first_tuple = await saver.aget_tuple({"configurable": {"thread_id": "t1"}})
            self.assertIsNotNone(first_tuple)
            assert first_tuple is not None
            first_messages = first_tuple.checkpoint["channel_values"]["messages"]

            second = await self.graph_module.arun(graph, "Ещё раз", "t1")
            second_tuple = await saver.aget_tuple({"configurable": {"thread_id": "t1"}})
            self.assertIsNotNone(second_tuple)
            assert second_tuple is not None
            second_messages = second_tuple.checkpoint["channel_values"]["messages"]

            self.assertEqual(first["messages"][-1].content, "Первый ответ.")
            self.assertEqual(second["messages"][-1].content, "Второй ответ.")
            self.assertEqual(
                [message.content for message in second_messages if message.type == "human"],
                ["Покажи команды", "Ещё раз"],
            )
            self.assertEqual(second_messages[-1].content, "Второй ответ.")
            self.assertGreater(len(second_messages), len(first_messages))

    def _knowledge_fixture(self, body="DOCUMENT-BODY-SENTINEL-65"):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name)
        (path / "manifest.toml").write_text(
            'dataset = "fixture"\npersona = "Fixture analyst."\n', encoding="utf-8"
        )
        text = f"# Rules\n\nFixture summary.\n\n{body}\n"
        (path / "rules.md").write_text(text, encoding="utf-8")
        return path, text, self._load_knowledge(path)

    def _load_knowledge(self, path):
        return self.knowledge_module.load_knowledge(
            path,
            "fixture",
            self.knowledge_module.KnowledgeLimits(80, 200, 2000, 50, 65536, 131072),
        )

    def _read_response(self, call_id="knowledge-1"):
        return self.messages.AIMessage(
            content="",
            tool_calls=[
                self.graph_cases.tool_call("read_knowledge", {"topic": "rules"}, call_id)
            ],
            additional_kwargs={"reasoning_content": "REASONING-SENTINEL-65"},
        )

    async def _head(self, saver, thread="knowledge"):
        checkpoint = await saver.aget_tuple({"configurable": {"thread_id": thread}})
        self.assertIsNotNone(checkpoint)
        return checkpoint.checkpoint["channel_values"]

    def _assert_no_document(self, messages, text):
        self.assertFalse(
            any(text in str(message.content) for message in messages),
            "The next turn must not carry the knowledge document body",
        )

    def _assert_pairs(self, messages):
        calls = [
            call["id"]
            for message in messages
            if isinstance(message, self.messages.AIMessage)
            for call in message.tool_calls
        ]
        results = [
            message.tool_call_id
            for message in messages
            if isinstance(message, self.messages.ToolMessage)
        ]
        self.assertCountEqual(calls, results)
        self.assertEqual(len(results), len(set(results)))

    async def test_next_turn_does_not_carry_knowledge_document(self):
        _, text, knowledge = self._knowledge_fixture()
        model = self.graph_cases.ScriptedModel([
            self._read_response(),
            self.messages.AIMessage(content="ANSWER-ONE"),
            self.messages.AIMessage(content="ANSWER-TWO"),
        ])
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            _, graph = self._build_graph(saver, model, knowledge)
            first = await self.graph_module.arun(graph, "QUESTION-ONE", "knowledge")
            self.assertIn(text, [message.content for message in model.requests[1]])
            self.assertEqual(first["knowledge_bytes_consumed"], len(text.encode("utf-8")))
            second = await self.graph_module.arun(graph, "QUESTION-TWO", "knowledge")
            self.assertEqual(second["knowledge_bytes_consumed"], 0)
            self._assert_no_document(model.requests[-1], text)
            head = await self._head(saver)
            self._assert_no_document(head["messages"], text)
            self.assertEqual(
                [m.content for m in head["messages"] if m.type == "human"],
                ["QUESTION-ONE", "QUESTION-TWO"],
            )
            self.assertEqual(
                [m.content for m in head["messages"] if m.type == "ai" and not m.tool_calls],
                ["ANSWER-ONE", "ANSWER-TWO"],
            )

    async def test_knowledge_compaction_preserves_message_identity_and_pairs(self):
        _, text, knowledge = self._knowledge_fixture()
        response = self._read_response()
        response.tool_calls.append(self.graph_cases.tool_call("get_all_teams", {}, "data-1"))
        model = self.graph_cases.ScriptedModel([
            response, self.messages.AIMessage(content="ANSWER-ONE")
        ])
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            service, graph = self._build_graph(saver, model, knowledge)
            service.results["get_all_teams"] = []
            await self.graph_module.arun(graph, "QUESTION-ONE", "knowledge")
            original = [m for m in model.requests[1] if m.type != "system"]
            head = (await self._head(saver))["messages"]
            self._assert_pairs(head)
            self.assertEqual([m.id for m in head[:-1]], [m.id for m in original])
            for before, after in zip(original, head, strict=False):
                if before.type == "tool" and before.tool_call_id == "knowledge-1":
                    self.assertEqual(before.content, text)
                    self.assertEqual(after.id, before.id)
                    self.assertEqual(after.tool_call_id, before.tool_call_id)
                    self.assertNotEqual(after.content, before.content)
                    self.assertIn("rules", after.content)
                else:
                    self.assertEqual(after.model_dump(), before.model_dump())

    async def test_baseline_bounded_tool_rounds_still_complete(self):
        _, text, knowledge = self._knowledge_fixture()
        # Baseline that already succeeds without compaction; see decisions.md scope ruling.
        successful_rounds = self.config.AGENT_RECURSION_LIMIT - 1
        responses = [self._read_response()]
        responses.extend(
            self.messages.AIMessage(content="", tool_calls=[
                self.graph_cases.tool_call("get_all_teams", {}, f"data-{index}")
            ]) for index in range(successful_rounds - 1)
        )
        responses.append(self.messages.AIMessage(content="BOUNDARY-ANSWER"))
        model = self.graph_cases.ScriptedModel(responses)
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            service, graph = self._build_graph(saver, model, knowledge)
            service.results["get_all_teams"] = []
            result = await self.graph_module.arun(graph, "Use all rounds", "knowledge")
            self.assertEqual(result["messages"][-1].content, "BOUNDARY-ANSWER")
            # Pin the same baseline before and after compaction: R tool rounds, R+1 calls.
            self.assertEqual(model.invocation_count, successful_rounds + 1)
            self.assertEqual(len(service.calls), successful_rounds - 1)
            self.assertEqual(sum(m.type == "tool" for m in result["messages"]), successful_rounds)
            self.assertEqual(result["knowledge_bytes_consumed"], len(text.encode("utf-8")))
            self._assert_pairs(result["messages"])
            print(
                f"bounded baseline: model_invocations={model.invocation_count} "
                f"tool_executions={successful_rounds} data_calls={len(service.calls)}"
            )

    async def _recover_failed_turn(self, failure_mode):
        _, text, knowledge = self._knowledge_fixture()
        model_started = asyncio.Event()

        def repeat(invocation):
            if failure_mode == "model_exception":
                raise RuntimeError("MODEL-FAILURE-SENTINEL-65")
            return self.messages.AIMessage(content="", tool_calls=[
                self.graph_cases.tool_call("get_all_teams", {}, f"data-{invocation}")
            ])

        model = self.graph_cases.ScriptedModel([self._read_response()], repeat_factory=repeat)
        original_invoke = model.ainvoke

        async def block_after_read(messages):
            if model.invocation_count == 1:
                # Record the exact provider request before signalling cancellation readiness.
                model.requests.append(messages)
                model.invocation_count += 1
                model_started.set()
                await asyncio.Future()
            return await original_invoke(messages)

        async def timeout_after_model_started(awaitable, timeout):
            # Simulate the runtime deadline, but only after the real tools node committed.
            task = asyncio.create_task(awaitable)
            try:
                await asyncio.wait_for(model_started.wait(), timeout=5)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=5)
            raise TimeoutError

        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            service = self.support.StubService()
            service.results["get_all_teams"] = []
            agent = self.runtime.ReportAgentSystem(
                service=service, model_client=model, checkpointer=saver,
                knowledge=knowledge,
            )
            if failure_mode == "timeout":
                with patch.object(model, "ainvoke", side_effect=block_after_read), patch.object(
                    self.runtime, "wait_for", side_effect=timeout_after_model_started
                ):
                    result = await agent.process_user_request("Read then fail", "knowledge")
            elif failure_mode == "model_exception":
                with self.assertLogs("agents.report_runtime", level="ERROR"):
                    result = await agent.process_user_request("Read then fail", "knowledge")
            else:
                result = await agent.process_user_request("Read then fail", "knowledge")
            expected = {
                "recursion": "recursion_limit",
                "model_exception": "MODEL-FAILURE-SENTINEL-65",
                "timeout": "timeout",
            }
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], expected[failure_mode])
            self.assertIn(text, [m.content for m in model.requests[1]])
            head = await self._head(saver)
            self.assertIn(text, [m.content for m in head["messages"]])
            if failure_mode == "recursion":
                self.assertEqual(model.invocation_count, self.config.AGENT_RECURSION_LIMIT + 1)
                self.assertEqual(len(service.calls), self.config.AGENT_RECURSION_LIMIT - 1)
                self.assertEqual(
                    sum(m.type == "tool" for m in head["messages"]),
                    self.config.AGENT_RECURSION_LIMIT,
                )
            # Restart the graph from the failed checkpoint, not from a clean conversation.
            if failure_mode == "model_exception":
                failing = self.graph_cases.ScriptedModel([], repeat_factory=repeat)
                _, graph = self._build_graph(saver, failing, knowledge)
                with self.assertRaisesRegex(RuntimeError, "MODEL-FAILURE-SENTINEL-65"):
                    await self.graph_module.arun(graph, "Fail again", "knowledge")
                self._assert_no_document(failing.requests[0], text)
                # No completed model update means the resumable head may still contain it.
                self.assertIn(text, [m.content for m in (await self._head(saver))["messages"]])
            recovery = self.graph_cases.ScriptedModel([
                self._read_response("fresh-read"), self.messages.AIMessage(content="RECOVERED")
            ])
            _, graph = self._build_graph(saver, recovery, knowledge)
            recovered = await self.graph_module.arun(graph, "Read again", "knowledge")
            self._assert_no_document(recovery.requests[0], text)
            fresh = [m for m in recovery.requests[1] if m.type == "tool"][-1]
            self.assertEqual(fresh.content, text)
            self.assertEqual(recovered["knowledge_bytes_consumed"], len(text.encode("utf-8")))
            self._assert_no_document((await self._head(saver))["messages"], text)
            print(f"{failure_mode}: next-turn request and completed head omit document")

    async def test_next_turn_after_recursion_error_does_not_carry_document(self):
        await self._recover_failed_turn("recursion")

    async def test_next_turn_after_model_exception_does_not_carry_document(self):
        await self._recover_failed_turn("model_exception")

    async def test_next_turn_after_timeout_does_not_carry_document(self):
        await self._recover_failed_turn("timeout")

    async def test_restart_reads_changed_document_not_checkpoint_copy(self):
        path, old_text, knowledge = self._knowledge_fixture()
        database = str(path / "checkpoints.sqlite")
        first_model = self.graph_cases.ScriptedModel([
            self._read_response(), self.messages.AIMessage(content="OLD-ANSWER")
        ])
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(database) as saver:
            _, graph = self._build_graph(saver, first_model, knowledge)
            await self.graph_module.arun(graph, "Old question", "knowledge")
        new_text = old_text.replace("DOCUMENT-BODY-SENTINEL-65", "NEW-DOCUMENT-SENTINEL-65")
        (path / "rules.md").write_text(new_text, encoding="utf-8")
        reloaded = self._load_knowledge(path)
        model = self.graph_cases.ScriptedModel([
            self._read_response("new-read"), self.messages.AIMessage(content="NEW-ANSWER")
        ])
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(database) as saver:
            _, graph = self._build_graph(saver, model, reloaded)
            await self.graph_module.arun(graph, "New question", "knowledge")
            self._assert_no_document(model.requests[0], old_text)
            self.assertIn(new_text, [m.content for m in model.requests[1]])
            self._assert_no_document(model.requests[1], old_text)
            head = (await self._head(saver))["messages"]
            self._assert_pairs(head)
            self.assertIn("Old question", [m.content for m in head])
            self.assertIn("OLD-ANSWER", [m.content for m in head])

    async def test_three_large_reads_keep_head_and_next_request_small(self):
        prefix = "# Rules\n\nFixture summary.\n\n"
        _, text, knowledge = self._knowledge_fixture("Z" * (60 * 1024 - len(prefix) - 1))
        self.assertEqual(len(text.encode("utf-8")), 60 * 1024)
        responses = []
        for turn in range(3):
            responses.extend([
                self._read_response(f"large-{turn}"),
                self.messages.AIMessage(content=f"ANSWER-{turn}"),
            ])
        responses.append(self.messages.AIMessage(content="FOLLOW-UP"))
        model = self.graph_cases.ScriptedModel(responses)

        def serialized_size(messages):
            return len(json.dumps(self.messages.messages_to_dict(messages)).encode("utf-8"))

        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            _, graph = self._build_graph(saver, model, knowledge)
            head_sizes = []
            request_sizes = []
            for turn in range(4):
                first_call = len(model.requests)
                await self.graph_module.arun(graph, f"QUESTION-{turn}", "knowledge")
                if turn:
                    outbound = model.requests[first_call]
                    self._assert_no_document(outbound, text)
                    request_sizes.append(serialized_size(outbound))
                    print(
                        f"read_turn={turn} document_bytes={len(text.encode('utf-8'))} "
                        f"head_messages_bytes={head_sizes[-1]} "
                        f"next_first_request_bytes={request_sizes[-1]}"
                    )
                if turn < 3:
                    self.assertIn(text, [m.content for m in model.requests[-1]])
                    head_sizes.append(serialized_size((await self._head(saver))["messages"]))
            self.assertTrue(all(size < 30 * 1024 for size in head_sizes + request_sizes))
            self.assertLess(max(head_sizes) - min(head_sizes), 10 * 1024)
            self.assertLess(max(request_sizes) - min(request_sizes), 10 * 1024)

    async def test_delete_thread_on_missing_thread_needs_setup(self):
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            await saver.setup()
            await saver.adelete_thread("never-existed")


class TestPromptCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.knowledge_module = importlib.import_module("agent.knowledge")

    def _knowledge_limits(self):
        return self.knowledge_module.KnowledgeLimits(
            max_title_chars=80,
            max_summary_chars=200,
            max_persona_chars=2000,
            max_topics=50,
            max_doc_bytes=65536,
            max_bytes_per_turn=131072,
        )

    def test_system_prompt_without_knowledge_is_byte_exact(self):
        expected_prompt = (
            "You are a data analyst for the connected database. Answer in the language of the user's question.\n\n"
            "- Get data ONLY through the tools.\n"
            "- The tools return a summary, not the rows themselves. If you need rows, call read_rows.\n"
            "- Row budgets are bounded per call and per request. "
            "When a budget is exhausted, answer with what you have.\n"
            "- Once you have received data, call mark_report(handle).\n"
            "- If there is nothing, say so plainly and do not mark a report.\n"
            "- Do not invent numbers or names."
        )
        actual_prompt = self.knowledge_module.compose_system_prompt(None)

        self.assertEqual(expected_prompt.encode("utf-8"), actual_prompt.encode("utf-8"))
        for fragment in ("read_rows", "mark_report"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, actual_prompt)
        self.assertNotIn("256", actual_prompt)
        self.assertNotIn("1024", actual_prompt)

    def test_system_prompt_with_knowledge_is_byte_exact(self):
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\nSome summary paragraph text.\n",
                encoding="utf-8",
            )
            knowledge = self.knowledge_module.load_knowledge(
                folder_path,
                "some_db",
                limits,
            )
            expected_prompt = (
                "Some text.\n\n"
                "- Get data ONLY through the tools.\n"
                "- The tools return a summary, not the rows themselves. If you need rows, call read_rows.\n"
                "- Row budgets are bounded per call and per request. "
                "When a budget is exhausted, answer with what you have.\n"
                "- Once you have received data, call mark_report(handle).\n"
                "- If there is nothing, say so plainly and do not mark a report.\n"
                "- Do not invent numbers or names.\n"
                "- Before answering a question covered by a listed topic, "
                "call read_knowledge with that topic id.\n\n"
                "## Knowledge topics\n\n"
                "rules: Rules. Some summary paragraph text."
            )

            actual_prompt = self.knowledge_module.compose_system_prompt(knowledge)

            self.assertEqual(expected_prompt.encode("utf-8"), actual_prompt.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
