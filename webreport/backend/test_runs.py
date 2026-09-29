"""Lifecycle tests for durable background chat turns."""
import asyncio
import os
import threading
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import structlog
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from agent.graph import arun, build_graph
from test_agent_graph import ScriptedModel
from langchain_core.tools import tool

from chat_store import ChatStore
from session_store import SessionIndex
from agents.report_support import success
from runs import (RunRegistry, RunNotFound, InvalidRequest, ModelUnavailable,
                  Overloaded, ChatBusy, RequestConflict)


class FakeAgent:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.history = []
        self.result = success('Answer', [], None, reasoning='reason')
        self.error = None
        self.head = []

    async def process_user_request(self, message, session_id, history=()):
        self.history.append(list(history))
        self.started.set()
        await self.release.wait()
        if self.error:
            raise self.error
        return self.result

    async def head_messages(self, session_id):
        return self.head


class FakeArchive:
    def __init__(self):
        self.begins = []
        self.completions = []

    async def begin(self, **kwargs):
        self.begins.append(kwargs)
        return len(self.begins)

    async def complete(self, row_id, result):
        self.completions.append((row_id, result))


class RunTests(unittest.IsolatedAsyncioTestCase):
    AGENT_MODEL = 'test-model'
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ChatStore(Path(self.temp.name) / 'chats.db')
        await self.store.setup()
        self.agent = FakeAgent()
        self.archive = FakeArchive()
        self.sessions = SessionIndex(max_size=4)
        self.pinned = {}
        self._admission_lock = asyncio.Lock()
        self.saver = AsyncMock()
        self.registry = RunRegistry(self.store, runtime=lambda: self)
        self.chat = (await self.store.create_chat())['id']

    async def asyncTearDown(self):
        await self.registry.shutdown()
        await self.store.close()
        self.temp.cleanup()

    @property
    def agent_system(self):
        return self.agent

    @property
    def checkpoint_saver(self):
        return self.saver

    @property
    def admission_lock(self):
        return self._admission_lock

    async def submit(self, chat=None, request=None, message='Question'):
        return await self.registry.submit(chat or self.chat, request or uuid4().hex, message)

    async def finish(self, request):
        self.agent.release.set()
        return await asyncio.wait_for(self.registry.wait(request), 5)

    async def test_submit_and_success(self):
        run = await self.submit()
        self.assertEqual(run['state'], 'running')
        self.assertEqual([m['role'] for m in await self.store.list_messages(self.chat)], ['user'])
        done = await self.finish(run['request_id'])
        self.assertEqual(done['state'], 'succeeded')
        self.assertEqual(done['response']['message'], 'Answer')
        self.assertEqual([m['role'] for m in await self.store.list_messages(self.chat)], ['user', 'assistant'])
        self.assertEqual(self.pinned, {})

    async def test_report_retained(self):
        self.agent.result = success('# Report', [], [{'n': 1}], reasoning='thinking', report_handle={'tool': 'read_rows', 'args': {'limit': 1}})
        run = await self.submit()
        done = await self.finish(run['request_id'])
        card = done['response']['report']
        self.assertEqual(card['title'], 'Report')
        self.assertEqual((await self.store.get_report(card['id']))['data'], [{'n': 1}])
        self.assertEqual((await self.store.list_messages(self.chat))[-1]['reasoning'], 'thinking')

    async def test_cancel_wait_and_idempotence(self):
        run = await self.submit()
        await asyncio.wait_for(self.agent.started.wait(), 5)
        first = await self.registry.cancel(self.chat, run['request_id'])
        second = await self.registry.cancel(self.chat, run['request_id'])
        self.assertEqual(first['state'], second['state'])
        done = await asyncio.wait_for(self.registry.wait(run['request_id']), 5)
        self.assertEqual(done['state'], 'cancelled')
        self.assertEqual([m['content'] for m in await self.store.list_messages(self.chat) if m['role'] == 'assistant'], ['Запрос отменён'])
        self.assertEqual(self.archive.completions[0][1]['error'], 'cancelled')
        self.assertEqual(self.pinned, {})

    async def test_cancel_before_first_step(self):
        run = await self.submit()
        await self.registry.cancel(self.chat, run['request_id'])
        self.assertEqual((await asyncio.wait_for(self.registry.wait(run['request_id']), 5))['state'], 'cancelled')
        self.assertEqual(self.pinned, {})

    async def test_terminal_cancel_and_unknown(self):
        run = await self.submit()
        done = await self.finish(run['request_id'])
        self.assertEqual(await self.registry.cancel(self.chat, run['request_id']), done)
        with self.assertRaises(RunNotFound):
            await self.registry.cancel(self.chat, uuid4().hex)

    async def test_caller_cancel_does_not_cancel_run(self):
        run = await self.submit()
        waiter = asyncio.create_task(self.registry.wait(run['request_id']))
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertEqual((await self.finish(run['request_id']))['state'], 'succeeded')

    async def test_conflicts(self):
        run = await self.submit()
        self.assertEqual(await self.submit(request=run['request_id']), run)
        with self.assertRaises(RequestConflict):
            await self.submit(request=run['request_id'], message='Other')
        other = (await self.store.create_chat())['id']
        with self.assertRaises(RequestConflict):
            await self.submit(chat=other, request=run['request_id'])
        with self.assertRaises(ChatBusy):
            await self.submit()
        await self.finish(run['request_id'])

    async def test_invalid_and_unavailable_without_writes(self):
        with self.assertRaises(InvalidRequest):
            await self.submit(request='abc')
        self.agent = None
        with self.assertRaises(ModelUnavailable):
            await self.submit()
        self.assertEqual(await self.store.list_messages(self.chat), [])
        self.assertEqual(self.archive.begins, [])

    async def test_overloaded_without_writes(self):
        self.sessions = SessionIndex(max_size=1)
        run = await self.submit()
        other = (await self.store.create_chat())['id']
        with self.assertRaises(Overloaded):
            await self.submit(chat=other)
        self.assertEqual(await self.store.list_messages(other), [])
        await self.finish(run['request_id'])

    async def test_archive_correlation(self):
        with structlog.contextvars.bound_contextvars(request_id='bound-http', trace_id='bound-trace'):
            run = await self.submit()
        await self.finish(run['request_id'])
        self.assertEqual((self.archive.begins[0]['request_id'], self.archive.begins[0]['trace_id']), ('bound-http', 'bound-trace'))
        self.assertNotEqual(self.archive.begins[0]['request_id'], run['request_id'])

    async def test_internal_error(self):
        self.agent.error = ValueError('broken')
        run = await self.submit()
        done = await self.finish(run['request_id'])
        self.assertEqual(done['error']['code'], 'internal:ValueError')
        self.assertEqual(len(await self.store.list_messages(self.chat)), 2)

    async def test_reseed_and_repair(self):
        first = await self.submit()
        await self.finish(first['request_id'])
        self.agent.release.clear()
        self.agent.started.clear()
        self.sessions = SessionIndex(ttl=0)
        self.agent.head = [AIMessage(content='', tool_calls=[{'name': 'read_rows', 'args': {}, 'id': 'dangling'}])]
        second = await self.submit(message='Next')
        await asyncio.wait_for(self.agent.started.wait(), 5)
        history = self.agent.history[-1]
        self.assertEqual([type(m) for m in history], [HumanMessage, AIMessage, ToolMessage])
        self.assertEqual(history[-1].tool_call_id, 'dangling')
        await self.finish(second['request_id'])

    async def test_submit_cancel_during_atomic_write_keeps_chat_available(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.store._get_run

        async def paused(*args):
            entered.set()
            await release.wait()
            return await original(*args)

        self.store._get_run = paused
        request = uuid4().hex
        submitting = asyncio.create_task(self.submit(request=request))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            submitting.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(submitting, 5)
        finally:
            release.set()
            self.store._get_run = original
        row = await self.store.get_run(request)
        self.assertTrue(row is None or row['state'] not in ('running', 'cancelling'))
        if row is not None:
            self.assertEqual((await self.store.list_messages(self.chat))[0]['content'], 'Question')
        self.assertEqual(self.pinned, {})
        next_run = await self.submit(message='Next question')
        self.assertEqual((await self.finish(next_run['request_id']))['state'], 'succeeded')

    async def test_cancel_between_run_and_user_write_does_not_orphan(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.store.append_message

        async def paused(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        self.store.append_message = paused
        request = uuid4().hex
        submitting = asyncio.create_task(self.submit(request=request))
        signal = asyncio.create_task(entered.wait())
        try:
            done, pending = await asyncio.wait(
                {submitting, signal}, return_when=asyncio.FIRST_COMPLETED, timeout=5,
            )
            for task in pending:
                if task is signal:
                    task.cancel()
            self.assertTrue(done)
            if entered.is_set():
                submitting.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(submitting, 5)
            else:
                await submitting
        finally:
            release.set()
            self.store.append_message = original
        row = await self.store.get_run(request)
        self.assertTrue(row is None or row['state'] not in ('running', 'cancelling')
                        or request in self.registry.tasks)
        if request in self.registry.tasks:
            await self.finish(request)
        self.assertEqual(self.pinned, {})
        next_run = await self.submit(message='Next question')
        self.assertEqual((await self.finish(next_run['request_id']))['state'], 'succeeded')

    async def test_submit_cancel_before_atomic_write_keeps_chat_available(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.store.create_run

        async def paused(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        self.store.create_run = paused
        request = uuid4().hex
        submitting = asyncio.create_task(self.submit(request=request))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            submitting.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(submitting, 5)
        finally:
            release.set()
            self.store.create_run = original
        row = await self.store.get_run(request)
        self.assertTrue(row is None or row['state'] not in ('running', 'cancelling'))
        if row is not None:
            self.assertEqual((await self.store.list_messages(self.chat))[0]['content'], 'Question')
        self.assertEqual(self.pinned, {})
        next_run = await self.submit(message='Next question')
        self.assertEqual((await self.finish(next_run['request_id']))['state'], 'succeeded')

    async def test_cancel_after_commit_before_registration_stops_run(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.store.create_run
        request = uuid4().hex

        async def committed_then_paused(*args, **kwargs):
            run = await original(*args, **kwargs)
            if args[1] == request:
                entered.set()
                await release.wait()
            return run

        self.store.create_run = committed_then_paused
        submission = asyncio.create_task(self.submit(request=request))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            self.assertIn(request, self.registry.tasks)
            pending_wait = asyncio.create_task(self.registry.wait(request))
            cancelled = await asyncio.wait_for(self.registry.cancel(self.chat, request), 5)
            self.assertEqual(cancelled['state'], 'cancelling')
            release.set()
            await asyncio.wait_for(submission, 5)
            done = await asyncio.wait_for(pending_wait, 5)
            self.assertEqual(done['state'], 'cancelled')
            self.assertIsNone(done['response'])
            self.assertEqual([m['content'] for m in await self.store.list_messages(self.chat)
                              if m['role'] == 'assistant'], ['Запрос отменён'])
            self.assertEqual(self.agent.history, [])
            self.assertEqual(self.pinned, {})
            # The task can be cancelled before its first statement: in that case
            # there is no archive row to complete.
            self.assertEqual(len(self.archive.completions), len(self.archive.begins))
        finally:
            release.set()
            self.store.create_run = original

    async def test_second_submit_cannot_replace_pending_cancel_handle(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.store.create_run
        request = uuid4().hex

        async def committed_then_paused(*args, **kwargs):
            run = await original(*args, **kwargs)
            if args[1] == request:
                entered.set()
                await release.wait()
            return run

        self.store.create_run = committed_then_paused
        submission = asyncio.create_task(self.submit(request=request))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            first_handle = self.registry.tasks.get(request)
            self.assertIsNotNone(first_handle)
            with self.assertRaises(ChatBusy):
                await self.submit(message='Second')
            duplicate = asyncio.create_task(self.submit(request=request))
            self.assertIs(self.registry.tasks.get(request), first_handle)
            await self.registry.cancel(self.chat, request)
            release.set()
            await asyncio.wait_for(submission, 5)
            self.assertEqual((await asyncio.wait_for(duplicate, 5))['request_id'], request)
            self.assertEqual((await asyncio.wait_for(self.registry.wait(request), 5))['state'], 'cancelled')
            self.assertEqual(self.pinned, {})
        finally:
            release.set()
            self.store.create_run = original

    async def test_cancel_foreign_active_row_without_handle(self):
        request = uuid4().hex
        await self.store.create_run(self.chat, request, 'Unfinished', 'older-boot',
                                    with_user_message=True)
        self.assertNotIn(request, self.registry.tasks)
        done = await asyncio.wait_for(self.registry.cancel(self.chat, request), 5)
        self.assertEqual(done['state'], 'interrupted')
        self.assertEqual((await asyncio.wait_for(self.registry.wait(request), 5))['state'], 'interrupted')
        self.assertEqual([m['content'] for m in await self.store.list_messages(self.chat)
                          if m['role'] == 'assistant'], ['Ответ прерван перезапуском сервера'])
        self.assertEqual((await self.registry.cancel(self.chat, request))['state'], 'interrupted')
        next_run = await self.submit(message='Next')
        self.assertEqual((await self.finish(next_run['request_id']))['state'], 'succeeded')

    async def test_finalise_write_failure_uses_terminal_fallback_and_completes_archive(self):
        run = await self.submit()
        await asyncio.wait_for(self.agent.started.wait(), 5)
        original = self.store.finish_run

        async def broken_finish(*args, **kwargs):
            raise OSError('controlled write failure')

        self.store.finish_run = broken_finish
        try:
            await self.registry.cancel(self.chat, run['request_id'])
            done = await asyncio.wait_for(self.registry.wait(run['request_id']), 5)
        finally:
            self.store.finish_run = original
        self.assertEqual(done['state'], 'failed')
        self.assertEqual(done['error']['code'], 'internal:finalise')
        self.assertEqual(len(self.archive.completions), 1)
        self.assertEqual(self.pinned, {})

    async def test_cancel_during_publication_joins_commit(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.store.publish_result

        async def blocked(*args, **kwargs):
            # Holding the SQLite transaction while cancellation arrives exercises
            # the store's terminal-state arbiter rather than a timing delay.
            async with self.store._transaction():
                entered.set()
                await release.wait()
            return await original(*args, **kwargs)

        self.agent.result = success('Report', [], [{'x': 1}], reasoning=None,
                                    report_handle={'tool': 'read_rows', 'args': {}})
        self.store.publish_result = blocked
        run = await self.submit()
        self.agent.release.set()
        await asyncio.wait_for(entered.wait(), 5)
        self.registry.tasks[run['request_id']].task.cancel()
        release.set()
        done = await asyncio.wait_for(self.registry.wait(run['request_id']), 5)
        self.assertEqual(done['state'], 'succeeded')
        self.assertEqual(len(await self.store.list_reports(self.chat)), 1)
        self.assertEqual(len([m for m in await self.store.list_messages(self.chat) if m['role'] == 'assistant']), 1)

    async def test_cancel_before_publication_has_no_report(self):
        self.agent.result = success('Report', [], [{'x': 1}], reasoning=None,
                                    report_handle={'tool': 'read_rows', 'args': {}})
        run = await self.submit()
        await asyncio.wait_for(self.agent.started.wait(), 5)
        await self.registry.cancel(self.chat, run['request_id'])
        self.agent.release.set()
        self.assertEqual((await asyncio.wait_for(self.registry.wait(run['request_id']), 5))['state'], 'cancelled')
        self.assertEqual(await self.store.list_reports(self.chat), [])

    async def test_reseed_is_bounded_to_last_twenty_pairs(self):
        for index in range(21):
            request = uuid4().hex
            await self.store.create_run(self.chat, request, f'Question {index}', self.registry.boot_id)
            await self.store.append_message(self.chat, request, 'user', f'Question {index}', None, None, None)
            await self.store.publish_result(request,
                                            assistant={'content': f'Answer {index}'},
                                            report=None, response={'success': True}, state='succeeded')
        history = await self.registry._history(self.chat, False, self.agent)
        self.assertEqual(len(history), 40)
        self.assertEqual(history[0].content, 'Question 1')
        self.assertEqual(history[-1].content, 'Answer 20')

    async def test_live_session_has_no_reseed(self):
        first = await self.submit()
        await self.finish(first['request_id'])
        self.agent.started.clear()
        second = await self.submit(message='Next')
        await asyncio.wait_for(self.agent.started.wait(), 5)
        self.assertEqual(self.agent.history[-1], [])
        await self.finish(second['request_id'])

    async def test_cancel_blocking_tool_then_resend_repairs_every_call(self):
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        @tool
        def gated(value: int) -> str:
            """A synchronous tool that holds the checkpoint at the tools node."""
            loop.call_soon_threadsafe(started.set)
            if not release.wait(5):
                raise TimeoutError('tool gate was never released')
            return str(value)

        saver = InMemorySaver()
        model = ScriptedModel([
            AIMessage(content='', tool_calls=[
                {'name': 'gated', 'args': {'value': 1}, 'id': 'dangling-1'},
                {'name': 'gated', 'args': {'value': 2}, 'id': 'dangling-2'},
            ]),
            AIMessage(content='Fresh answer'),
        ])
        graph = build_graph(model, [gated], saver, 'System')
        histories = []

        class GraphAgent:
            async def head_messages(self, session_id):
                checkpoint = await saver.aget_tuple({'configurable': {'thread_id': session_id}})
                return list(checkpoint.checkpoint['channel_values'].get('messages', ())) if checkpoint else []

            async def process_user_request(self, message, session_id, history=()):
                histories.append(list(history))
                result = await arun(graph, message, session_id, history=history)
                return success(result['messages'][-1].content, [], None, reasoning=None)

        self.agent = GraphAgent()
        try:
            first = await self.submit(message='Stale question')
            await asyncio.wait_for(started.wait(), 5)
            await self.registry.cancel(self.chat, first['request_id'])
            self.assertEqual((await asyncio.wait_for(self.registry.wait(first['request_id']), 5))['state'], 'cancelled')
            self.assertEqual(model.invocation_count, 1)
            second = await self.submit(message='New question')
            done = await asyncio.wait_for(self.registry.wait(second['request_id']), 5)
            self.assertEqual(done['state'], 'succeeded')
            self.assertEqual(done['response']['message'], 'Fresh answer')
            self.assertEqual(model.invocation_count, 2)
            self.assertEqual({m.tool_call_id for m in histories[-1] if isinstance(m, ToolMessage)},
                             {'dangling-1', 'dangling-2'})
            self.assertTrue(all(m.content == 'Запрос отменён' for m in histories[-1]))
            self.assertIsInstance(model.requests[1][-1], HumanMessage)
            self.assertEqual(model.requests[1][-1].content, 'New question')
        finally:
            release.set()

    async def test_scripted_graph_receives_repaired_input(self):
        # Use the real compiled graph, not a fake arun: the new input must be
        # the last human turn seen by its scripted model.
        model = ScriptedModel([AIMessage(content='Fresh answer')])
        graph = build_graph(model, [], InMemorySaver(), 'System')
        previous = AIMessage(content='', tool_calls=[{'name': 'read_rows', 'args': {}, 'id': 'stale'}])
        self.agent.head = [previous]
        history = await self.registry._history(self.chat, True, self.agent)
        self.assertEqual([m.tool_call_id for m in history], ['stale'])
        output = await asyncio.wait_for(arun(graph, 'New question', self.chat, history=history), 5)
        self.assertEqual(output['messages'][-1].content, 'Fresh answer')
        self.assertEqual(model.invocation_count, 1)
        self.assertIsInstance(model.requests[0][-1], HumanMessage)
        self.assertEqual(model.requests[0][-1].content, 'New question')

    async def test_sweep(self):
        old = await self.store.create_run(self.chat, uuid4().hex, 'Old', 'foreign-boot')
        await self.store.append_message(self.chat, old['request_id'], 'user', 'Old', None, None, None)
        await self.registry.sweep_on_startup()
        self.assertEqual((await self.store.get_run(old['request_id']))['state'], 'interrupted')
        self.assertEqual((await self.store.list_messages(self.chat))[-1]['content'], 'Ответ прерван перезапуском сервера')

    async def test_shutdown_archive_completes_before_store_closes(self):
        completed = asyncio.Event()
        original = self.archive.complete

        async def checked(row_id, result):
            self.assertIsNotNone(self.store.connection)
            await original(row_id, result)
            completed.set()

        self.archive.complete = checked
        run = await self.submit()
        await asyncio.wait_for(self.agent.started.wait(), 5)
        await asyncio.wait_for(self.registry.shutdown(), 5)
        self.assertTrue(completed.is_set())
        self.assertEqual((await self.store.get_run(run['request_id']))['state'], 'interrupted')

    async def test_startup_sweep_in_fresh_process(self):
        # The application startup hook is wired in todo 9. Exercise the registry's
        # recovery seam in a fresh process against the same persisted SQLite file.
        old = await self.store.create_run(self.chat, uuid4().hex, 'Old', 'foreign-boot')
        await self.store.append_message(self.chat, old['request_id'], 'user', 'Old', None, None, None)
        source = '''import asyncio, os
from chat_store import ChatStore
from runs import RunRegistry
async def probe():
    store = ChatStore(os.environ["BD_CHATS_DB_PATH"])
    await store.setup()
    registry = RunRegistry(store, runtime=lambda: None, boot_id="new-boot")
    await registry.sweep_on_startup()
    run = await store.get_run(os.environ["PROBE_REQUEST_ID"])
    assert run["state"] == "interrupted", run
    assert (await store.list_messages(run["chat_id"]))[-1]["content"] == "Ответ прерван перезапуском сервера"
    await store.close()
    print("recovered foreign-boot run")
asyncio.run(probe())'''
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-c', source,
            env={**os.environ, 'BD_CHATS_DB_PATH': str(self.store.path),
                 'PROBE_REQUEST_ID': old['request_id']},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(process.communicate(), 5)
        self.assertEqual(process.returncode, 0, err.decode())
        self.assertIn('recovered foreign-boot run', out.decode())

    async def test_shutdown(self):
        run = await self.submit()
        await asyncio.wait_for(self.agent.started.wait(), 5)
        await asyncio.wait_for(self.registry.shutdown(), 5)
        self.assertEqual((await self.store.get_run(run['request_id']))['state'], 'interrupted')
        self.assertEqual(self.pinned, {})
        self.assertEqual(len(self.archive.completions), 1)


if __name__ == '__main__':
    unittest.main()
