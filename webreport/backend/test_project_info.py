"""Offline project-document persistence and real graph/tool round-trip checks."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from connectors.http import ConnectorError
from workspace.project_info import (
    INFO_TEMPLATE,
    build_project_tools,
    project_context,
    project_info,
    save_project_info,
    with_update_notice,
)
from workspace.store import WorkspaceStore


class ProjectInfoTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "workspace.json"
        self.store = WorkspaceStore(self.path)
        self.project = self.store.add("projects", {"name": "Synthetic project"})
        self.chat = self.store.add(
            "chats", {"project_id": self.project["id"], "project_interview": True}
        )
        self.job = self.store.add(
            "jobs", {"chat_id": self.chat["id"], "status": "running"}
        )
        self.tools = {
            t.name: t
            for t in build_project_tools(
                self.store, self.project["id"], self.chat["id"], self.job["id"]
            )
        }

    def tearDown(self):
        self.directory.cleanup()

    def test_empty_template_and_restart_preserve_document_and_revision(self):
        empty = save_project_info(
            self.store, self.project["id"], INFO_TEMPLATE, 0, "user"
        )
        self.assertEqual(empty["content"], "")
        self.assertEqual(empty["revision"], 0)
        saved = save_project_info(
            self.store, self.project["id"], "## Цели\nУдержание", 0, "user"
        )
        restored = WorkspaceStore(self.path)
        self.assertEqual(
            project_info(restored.get("projects", self.project["id"])), saved
        )
        with self.assertRaises(ConnectorError):
            save_project_info(restored, self.project["id"], "Stale edit", 0, "user")
        self.assertEqual(
            project_info(restored.get("projects", self.project["id"])), saved
        )

    def test_concurrent_writers_cannot_silently_overwrite(self):
        def write(content):
            try:
                return save_project_info(
                    self.store, self.project["id"], content, 0, "agent"
                )
            except ConnectorError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["First fact", "Second fact"]))
        self.assertEqual(results.count(409), 1)
        self.assertEqual(
            project_info(self.store.get("projects", self.project["id"]))["revision"], 1
        )

    def test_tools_are_scoped_idempotent_and_reject_stale_or_cancelled_updates(self):
        other = self.store.add("projects", {"name": "Other project"})
        update = self.tools["update_project_info"]
        args = {
            "content": "## Что за проект\nОнлайн-игра.",
            "revision": 0,
            "summary": "Добавил описание игры.",
        }
        self.assertEqual(update.invoke(args)["status"], "saved")
        self.assertEqual(update.invoke({**args, "revision": 1})["status"], "unchanged")
        self.assertEqual(
            update.invoke({**args, "content": "Stale"})["status"], "conflict"
        )
        self.assertEqual(
            project_info(self.store.get("projects", other["id"]))["revision"], 0
        )
        notices = self.store.get("jobs", self.job["id"])["events"]
        self.assertEqual(len(notices), 1)
        notice = with_update_notice("Ответ", {"events": notices})
        self.assertIn("[информацию о проекте](#project-info)", notice)
        self.tools["finish_project_interview"].invoke({})
        self.assertFalse(self.store.get("chats", self.chat["id"])["project_interview"])
        self.store.update("jobs", self.job["id"], status="cancelled")
        self.assertEqual(
            update.invoke({**args, "revision": 1, "content": "Too late"})["status"],
            "conflict",
        )
        self.assertEqual(
            self.tools["read_project_info"].invoke({})["content"], args["content"]
        )

    def test_update_notices_do_not_turn_summaries_into_links(self):
        text = with_update_notice(
            "Ответ",
            {
                "events": [
                    {
                        "type": "project_info_updated",
                        "text": "[ссылка](https://example.com)",
                    }
                ]
            },
        )
        self.assertIn(r"\[ссылка\]", text)
        self.assertEqual(text.count("](#project-info)"), 1)


class ProjectGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_updates_document_and_next_turn_gets_manual_edits(self):
        from langchain_core.messages import AIMessage
        from langgraph.checkpoint.memory import InMemorySaver
        from agents.report_runtime import ReportAgentSystem

        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory) / "workspace.json")
            project = store.add("projects", {"name": "Synthetic"})
            chat = store.add(
                "chats", {"project_id": project["id"], "project_interview": True}
            )
            job = store.add("jobs", {"chat_id": chat["id"], "status": "running"})
            info_tools = build_project_tools(
                store, project["id"], chat["id"], job["id"]
            )
            calls = []

            class Model:
                def bind_tools(self, tools, *, parallel_tool_calls):
                    self.names = {t.name for t in tools}
                    return self

                async def ainvoke(self, messages):
                    calls.append(list(messages))
                    if len(calls) == 1:
                        return AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "update_project_info",
                                    "id": "save-context",
                                    "type": "tool_call",
                                    "args": {
                                        "content": INFO_TEMPLATE.replace(
                                            "## Что за проект\n",
                                            "## Что за проект\nОнлайн-игра.\n",
                                        ),
                                        "revision": 0,
                                        "summary": "Добавил описание игры.",
                                    },
                                }
                            ],
                        )
                    if len(calls) == 2:
                        result = json.loads(messages[-1].content)
                        assert result["status"] == "saved"
                        assert "handle" not in result
                        return AIMessage(content="Кто ваши игроки?")
                    assert "Ручная правка" in messages[0].content
                    assert "No project interview is active" in messages[0].content
                    return AIMessage(content="Перехожу к вашему вопросу.")

            model, saver = Model(), InMemorySaver()
            system = ReportAgentSystem(
                SimpleNamespace(),
                model_client=model,
                checkpointer=saver,
                context=project_context(project, True),
                extra_tools=info_tools,
            )
            result = await system.process_user_request(
                "Это онлайн-игра", "project-chat"
            )
            self.assertTrue(result["success"], result)
            self.assertEqual(
                store.get("projects", project["id"])["info"]["revision"], 1
            )
            save_project_info(store, project["id"], "Ручная правка", 1, "user")
            system = ReportAgentSystem(
                SimpleNamespace(),
                model_client=model,
                checkpointer=saver,
                context=project_context(store.get("projects", project["id"]), False),
                extra_tools=info_tools,
            )
            result = await system.process_user_request(
                "Теперь к вопросам", "project-chat"
            )
            self.assertTrue(result["success"], result)
            self.assertEqual(len(store.get("jobs", job["id"])["events"]), 1)


if __name__ == "__main__":
    unittest.main()
