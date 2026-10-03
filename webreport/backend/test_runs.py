"""Lifecycle tests for durable background chat turns."""
import asyncio
import json
import os
import random
import string
import subprocess
import threading
import sys
import tempfile
import unittest
from datetime import date, datetime, time
from decimal import Decimal
from fastapi.encoders import jsonable_encoder
from pathlib import Path
from unittest.mock import AsyncMock, patch
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
                  Overloaded, ChatBusy, RequestConflict, derive_report_title)
import report_title
from report_title_work import ParseWork


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
        submitted = await self.registry.submit(chat or self.chat, request or uuid4().hex, message)
        return submitted.run

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

    async def test_submit_result_distinguishes_creation_from_identical_retry(self):
        request_id = uuid4().hex
        first = await self.registry.submit(self.chat, request_id, 'Question')
        self.assertTrue(first.created)
        self.assertEqual(first.run['state'], 'running')
        duplicate = await self.registry.submit(self.chat, request_id, 'Question')
        self.assertFalse(duplicate.created)
        self.assertEqual(duplicate.run, first.run)
        await self.finish(request_id)

    async def test_concurrent_direct_submit_reports_only_one_created(self):
        request_id = uuid4().hex
        entered, checked_twice, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_create = self.store.create_run
        original_get = self.store.get_request
        checks = 0

        async def paused_create(*args, **kwargs):
            if args[1] == request_id:
                entered.set()
                await release.wait()
            return await original_create(*args, **kwargs)

        async def observed_get(run_id):
            nonlocal checks
            result = await original_get(run_id)
            if run_id == request_id and result is None:
                checks += 1
                if checks == 2:
                    checked_twice.set()
            return result

        self.store.create_run = paused_create
        self.store.get_request = observed_get
        try:
            first = asyncio.create_task(self.registry.submit(self.chat, request_id, 'Question'))
            await asyncio.wait_for(entered.wait(), 5)
            second = asyncio.create_task(self.registry.submit(self.chat, request_id, 'Question'))
            await asyncio.wait_for(checked_twice.wait(), 5)
            release.set()
            outcomes = await asyncio.wait_for(asyncio.gather(first, second), 5)
            self.assertEqual([outcome.created for outcome in outcomes], [True, False])
            self.assertEqual(outcomes[0].run['request_id'], outcomes[1].run['request_id'])
        finally:
            release.set()
            self.store.create_run = original_create
            self.store.get_request = original_get
        await self.finish(request_id)
        self.assertEqual(len(self.archive.begins), 1)
        self.assertEqual(self.pinned, {})

    async def test_submit_after_clear_creates_again(self):
        request_id = uuid4().hex
        first = await self.registry.submit(self.chat, request_id, 'Question')
        self.assertTrue(first.created)
        await self.finish(request_id)
        await self.store.clear_chat(self.chat)
        new = await self.registry.submit(self.chat, request_id, 'Question')
        self.assertTrue(new.created)
        self.assertEqual(new.run['state'], 'running')
        await self.finish(request_id)

    async def test_report_retained(self):
        self.agent.result = success('# Report', [], [{'n': 1}], reasoning='thinking', report_handle={'tool': 'read_rows', 'args': {'limit': 1}})
        run = await self.submit()
        done = await self.finish(run['request_id'])
        card = done['response']['report']
        self.assertEqual(card['title'], 'Report')
        self.assertEqual((await self.store.get_report(card['id']))['data'], [{'n': 1}])
        self.assertEqual((await self.store.list_messages(self.chat))[-1]['reasoning'], 'thinking')

    async def test_report_titles_strip_markdown(self):
        cases = [
            ('```csv\nкоманда,очки\nА,10\n```', 'Вопрос', 'команда,очки'),
            ('~~~csv\nкоманда,очки\n~~~', 'Вопрос', 'команда,очки'),
            ('| --- | :---: |\n| | |\n| **Команда** | `Очки` |',
             'Вопрос', 'Команда Очки'),
            ('---\n***\n___\n# Итоги сезона', 'Вопрос', 'Итоги сезона'),
            ('> ## **Итоги** _сезона_', 'Вопрос', 'Итоги сезона'),
            ('## Итоги сезона ##', 'Вопрос', 'Итоги сезона'),
            ('- *Итоги* **сезона**', 'Вопрос', 'Итоги сезона'),
            ('- [x] **Итоги сезона**', 'Вопрос', 'Итоги сезона'),
            ('1. Итоги `сезона`', 'Вопрос', 'Итоги сезона'),
            ('2) ~~Итоги~~ __сезона__', 'Вопрос', 'Итоги сезона'),
            ('[Итоги](https://example.org) ![сезона](image.png)',
             'Вопрос', 'Итоги сезона'),
            ('<h2>Итоги <em>сезона</em></h2>', 'Вопрос', 'Итоги сезона'),
            ('##\n> - ** **\nИтоги сезона', 'Вопрос', 'Итоги сезона'),
            ('```csv\n```\n~~~\n~~~', 'Покажи итоги', 'Покажи итоги'),
            ('| --- | --- |\n| | |\n---', 'Покажи итоги', 'Покажи итоги'),
            ('\n \t\n', 'Покажи итоги', 'Покажи итоги'),
            ('**\n__\n<em></em>', 'Покажи итоги', 'Покажи итоги'),
            ('<b>Итоги &amp; очки</b>', 'Вопрос', 'Итоги & очки'),
            ('**' + 'Я' * 121 + '**', 'Вопрос', 'Я' * 120),
            ('```\n```', 'Ж' * 121, 'Ж' * 120),
            ('Итоги team_name: -5, 2 * 3', 'Вопрос', 'Итоги team_name: -5, 2 * 3'),
        ]
        for answer, question, expected in cases:
            with self.subTest(answer=answer):
                agent = FakeAgent()
                agent.result = success(answer, [], [{'n': 1}], reasoning='thinking',
                                       report_handle={'tool': 'read_rows', 'args': {}})
                self.agent = agent
                run = await self.submit(message=question)
                done = await self.finish(run['request_id'])
                self.assertEqual(done['state'], 'succeeded', done)
                response = done['response']
                assert response is not None
                card = response['report']
                self.assertEqual(card['title'], expected)
                report = await self.store.get_report(card['id'])
                assert report is not None
                self.assertEqual(report['title'], expected)
                self.assertEqual(report['question'], question)
                self.assertEqual(report['data'], [{'n': 1}])
                self.assertEqual((await self.store.list_messages(self.chat))[-1]['content'], answer)

    async def test_report_titles_reviewer_matrix(self):
        # Exact 55-input oracle attached to the todo-25 gate review.
        q = 'Покажи итоги'
        cases = [
            ('f3-csv', '```csv\nкоманда,очки\nА,10\n```', q, 'команда,очки'),
            ('fence-table', '```csv\n| a | b |\n|---|---|\n|1|2|\n```', q, 'a b'),
            ('tilde-fence', '~~~csv\nкоманда,очки\n~~~', q, 'команда,очки'),
            ('fence-only', '```csv\n```\n~~~\n~~~', q, q),
            ('table-first', '| a | b |\n|---|---|\n|1|2|', q, 'a b'),
            ('separator-first', '|---|:---:|\n| | |\n| a | b |', q, 'a b'),
            ('setext', 'Итоги\n=====\nbody', q, 'Итоги'),
            ('setext-dashes', 'Итоги\n-----\nbody', q, 'Итоги'),
            ('atx-h1', '# Итоги', q, 'Итоги'),
            ('atx-h2', '## Итоги ##', q, 'Итоги'),
            ('atx-h3', '### Итоги', q, 'Итоги'),
            ('blockquote', '> Итоги', q, 'Итоги'),
            ('dash-list', '- Итоги', q, 'Итоги'),
            ('star-list', '* Итоги', q, 'Итоги'),
            ('plus-list', '+ Итоги', q, 'Итоги'),
            ('number-list', '1. Итоги', q, 'Итоги'),
            ('number-paren', '2) Итоги', q, 'Итоги'),
            ('checkbox-x', '- [x] Итоги', q, 'Итоги'),
            ('checkbox-blank', '- [ ] Итоги', q, 'Итоги'),
            ('bold', '**Итоги**', q, 'Итоги'),
            ('italic', '*Итоги* _сезона_', q, 'Итоги сезона'),
            ('strike', '~~Итоги~~', q, 'Итоги'),
            ('inline-code', '`Итоги`', q, 'Итоги'),
            ('link', '[Итоги](https://example.org)', q, 'Итоги'),
            ('image', '![Итоги](image.png)', q, 'Итоги'),
            ('autolink-alone', '<https://example.org/results>', q, 'https://example.org/results'),
            ('autolink-in-text', 'Результаты <https://example.org/results>', q,
             'Результаты https://example.org/results'),
            ('email-autolink', '<analyst@example.org>', q, 'analyst@example.org'),
            ('html-tags', '<h2>Итоги <em>сезона</em></h2>', q, 'Итоги сезона'),
            ('html-entities', '<b>Итоги &amp; очки &#x1F600;</b>', q, 'Итоги & очки 😀'),
            ('rules', '---\n***\n___\nИтоги', q, 'Итоги'),
            ('emoji-leading', '😀 **Итоги**', q, '😀 Итоги'),
            ('cyrillic-combining', '## И\u0306тоги е\u0301жегодно', q, 'И\u0306тоги е\u0301жегодно'),
            ('long-codepoints', '😀' * 121, q, '😀' * 120),
            ('combining-boundary', 'а' * 119 + 'е\u0301', q, 'а' * 119 + 'е'),
            ('whitespace', '\n \t\n', q, q),
            ('empty', '', q, q),
            ('none', None, q, None),
            ('all-scaffolding', '```\n```\n|---|---|\n| | |\n---\n#\n>\n**\n<em></em>', q, q),
            ('fallback-empty', '```\n```', '', ''),
            ('fallback-long', '```\n```', 'Я' * 121, 'Я' * 120),
            ('nested-markers', '**# x**', q, 'x'),
            ('nested-emphasis', '***Итоги***', q, 'Итоги'),
            ('underscores', 'snake_case team_name', q, 'snake_case team_name'),
            ('math', '2*3*4', q, '2*3*4'),
            ('link-parentheses', '[Итоги](https://example.org/a_(b))', q, 'Итоги'),
            ('bare-url-parentheses', 'https://example.org/a_(b)', q, 'https://example.org/a_(b)'),
            ('escaped-markers', r'\*Итоги\*', q, '*Итоги*'),
            ('inline-triple-backticks', '```Итоги```', q, 'Итоги'),
            ('mixed-inline-emphasis', '**Итоги _сезона_**', q, 'Итоги сезона'),
            ('empty-checkbox', '- [x]\nИтоги', q, 'Итоги'),
            ('encoded-html-text', '&lt;b&gt;Итоги&lt;/b&gt;', q, '<b>Итоги</b>'),
            ('code-with-literal-stars', '`*Итоги*`', q, '*Итоги*'),
            ('fenced-code-literal-heading', '```text\n# literal heading\n```', q, '# literal heading'),
            ('setext-only', '===\n', q, q),
        ]
        for label, answer, question, expected in cases:
            with self.subTest(case=label):
                if answer is None:
                    # The review identifies nullable answers as outside the str contract.
                    self.assertRaises(AttributeError, derive_report_title, answer, question)
                    continue
                agent = FakeAgent()
                agent.result = success(answer, [], [{'n': 1}], reasoning='thinking',
                                       report_handle={'tool': 'read_rows', 'args': {}})
                self.agent = agent
                run = await self.submit(message=question)
                done = await self.finish(run['request_id'])
                self.assertEqual(done['state'], 'succeeded', done)
                response = done['response']
                assert response is not None
                card = response['report']
                self.assertEqual(card['title'], expected)
                report = await self.store.get_report(card['id'])
                assert report is not None
                self.assertEqual(report['title'], expected)
                self.assertEqual(report['question'], question)
                self.assertEqual(report['data'], [{'n': 1}])
                self.assertEqual((await self.store.list_messages(self.chat))[-1]['content'], answer)

    async def test_report_titles_round_two_matrix(self):
        cases = [
            ('reference-full', '[Итоги][1]\n\n[1]: https://example.org/results', 'Итоги'),
            ('reference-collapsed', '[Итоги][]\n\n[Итоги]: https://example.org', 'Итоги'),
            ('reference-shortcut', '[Итоги]\n\n[Итоги]: https://example.org/results', 'Итоги'),
            ('reference-missing', '[x][1]', '[x][1]'),
            ('collapsed-missing', '[x][]', '[x][]'),
            ('shortcut-missing', '[x]', '[x]'),
            ('definition-only', '[x]: https://example.org', 'Покажи итоги'),
            ('definition-first', '[x]: https://example.org\n\n[x]', 'x'),
            ('reference-normalized', '[Итоги][A B]\n\n[a   b]: https://example.org', 'Итоги'),
            ('shared-strong', '**Итоги *сезона***', 'Итоги сезона'),
            ('shared-star-three', '***x***', 'x'),
            ('shared-strong-inner', '**a *b***', 'a b'),
            ('shared-emphasis-inner', '*a **b***', 'a b'),
            ('nested-underscore-emphasis', '__Итоги _сезона_ клуба__', 'Итоги сезона клуба'),
            ('link-inside-heading', '## [**Итоги**](https://example.org/a_(b)) ##', 'Итоги'),
            ('footnote', 'Итоги[^1]\n\n[^1]: Источник', 'Итоги'),
            ('footnote-definition-only', '[^1]: Источник', 'Покажи итоги'),
            ('html-comment-single-line', '<!-- hidden -->\n# Видимый', 'Видимый'),
            ('html-comment-multiline', '<!--\nnot visible\n-->\n# Итоги', 'Итоги'),
            ('html-declaration', '<!DOCTYPE html>\n# Итоги', 'Итоги'),
            ('html-cdata', '<![CDATA[\nnot visible\n]]>\n# Итоги', 'Итоги'),
            ('html-processing', '<?instruction\nnot visible\n?>\n# Итоги', 'Итоги'),
            ('html-script', '<script>\nnot visible\n</script>\n# Итоги', 'Итоги'),
            ('html-style', '<style>\nnot visible\n</style>\n# Итоги', 'Итоги'),
            ('html-type-six', '<div>\nnot visible\n</div>\n\n# Итоги', 'Итоги'),
            ('html-type-seven', '<custom-tag>\nnot visible\n</custom-tag>\n\n# Итоги', 'Итоги'),
            ('html-closing-start', '</div>\nnot visible\n\n# Итоги', 'Итоги'),
            ('html-empty-block', '<div></div>\nnot visible\n\n# Итоги', 'Итоги'),
            ('footnote-continuation', '[^1]: source\n    hidden\n\n# Итоги', 'Итоги'),
            ('definition-cannot-interrupt', '[x]\n[x]: url', '[x]'),
            ('html-no-blank', '<div>\n# not visible\n</div>\n# still hidden', 'Покажи итоги'),
            ('unclosed-comment', '<!--\n# not visible', 'Покажи итоги'),
            ('setext-after-paragraph', 'Первый абзац\n\nИтоги\n=====', 'Первый абзац'),
            ('table-escaped-pipe', '| a\\|b | c |\n|---|---|', 'a|b c'),
            ('task-list-link', '- [ ] [Итоги](https://example.org/a_(b))', 'Итоги'),
            ('front-matter', '---\ntitle: **Служебное**\n---\n# Итоги', 'title: Служебное'),
            ('math-escapes', r'Итоги \(2*3*4\)', 'Итоги (2*3*4)'),
            ('crlf', ' \r\n### Итоги\r\nДалее', 'Итоги'),
            ('unicode-line-separators', '\u0085\u2028## Итоги\u2028Далее', 'Итоги'),
            ('zero-width-prefix', '\u200b# Итоги', '\u200b# Итоги'),
            ('rtl-mark', '\u200f**مرحبا**', '\u200fمرحبا'),
            ('very-long-single-token', 'Слово' * 100000, 'Слово' * 24),
            ('ten-thousand-lines', '<!-- hidden -->\n' * 10000 + '## Итоги', 'Итоги'),
            ('fifty-thousand-stars', '*' * 50000, 'Покажи итоги'),
            ('twenty-thousand-open-brackets', '[' * 20000, '[' * 120),
            ('null-bytes', '\x00## Итоги\x00', '\x00## Итоги\x00'),
            ('linked-image', '[![Logo](logo.png)](https://example.org/results)', 'Logo'),
            ('nested-underscore-and-intraword', '**snake_case _и_ words__with__underscores**',
             'snake_case и words__with__underscores'),
        ]
        for label, answer, expected in cases:
            with self.subTest(case=label):
                agent = FakeAgent()
                agent.result = success(answer, [], [{'n': 1}], reasoning='thinking',
                                       report_handle={'tool': 'read_rows', 'args': {}})
                self.agent = agent
                run = await self.submit(message='Покажи итоги')
                self.agent.release.set()
                # Runtime-cost sanity only: ten times the reviewer's 28.7-second probe.
                done = await asyncio.wait_for(self.registry.wait(run['request_id']), 300)
                self.assertEqual(done['state'], 'succeeded', done)
                response = done['response']
                assert response is not None
                self.assertEqual(response['report']['title'], expected)
                report = await self.store.get_report(response['report']['id'])
                assert report is not None
                self.assertEqual(report['title'], expected)
                self.assertEqual((await self.store.list_messages(self.chat))[-1]['content'], answer)

    async def test_report_titles_round_three_matrix(self):
        cases = [
            ('late-251', '<!-- hidden -->\n' * 251 + '# Итоги', 'Итоги'),
            ('late-10000', '<!-- hidden -->\n' * 10000 + '# Итоги', 'Итоги'),
            ('blank-comment-5000', '\n<!-- hidden -->\n' * 2500 + '# Итоги', 'Итоги'),
            ('long-bold', '**' + 'a' * 2100 + '**', 'a' * 120),
            ('long-code', '`' + 'x' * 2100 + '`', 'x' * 120),
            ('long-triple-code', '```' + 'x' * 2100 + '```', 'x' * 120),
            ('long-reference', '[' + 'a' * 2100 + '][x]\n\n[x]: url', 'a' * 120),
            ('large-bold', '**' + 'a' * 149996 + '**', 'a' * 120),
            ('cyrillic-bold', '**' + 'я' * 2100 + '**', 'я' * 120),
            ('cyrillic-code', '`' + 'ю' * 2100 + '`', 'ю' * 120),
            ('cyrillic-large-bold', '**' + 'я' * 149996 + '**', 'я' * 120),
            ('later-long-bold', '<!-- hidden -->\n' * 10000 + '**' + 'я' * 2100 + '**',
             'я' * 120),
        ]
        for label, answer, expected in cases:
            with self.subTest(case=label):
                agent = FakeAgent()
                agent.result = success(answer, [], [{'n': 1}], reasoning='thinking',
                                       report_handle={'tool': 'read_rows', 'args': {}})
                self.agent = agent
                run = await self.submit(message='Покажи итоги')
                self.agent.release.set()
                done = await asyncio.wait_for(self.registry.wait(run['request_id']), 600)
                self.assertEqual(done['state'], 'succeeded', done)
                response = done['response']
                assert response is not None
                self.assertEqual(response['report']['title'], expected)
                report = await self.store.get_report(response['report']['id'])
                assert report is not None
                self.assertEqual(report['title'], expected)
                self.assertEqual((await self.store.list_messages(self.chat))[-1]['content'], answer)

    def test_report_title_safety_fallback_boundaries(self):
        wrappers = [
            ('bold', '**', '**'), ('italic', '*', '*'),
            ('strong-emphasis', '***', '***'), ('code', '`', '`'),
            ('link', '[', '](https://example.org)'),
            ('mixed', '**[`', '`](https://example.org)**'),
        ]
        for net in (200000, 1000000):
            for delta in (-1, 0, 1, 2):
                for label, opening, closing in wrappers:
                    length = net + delta
                    answer = opening + 'a' * (length - len(opening) - len(closing)) + closing
                    with self.subTest(kind=label, net=net, delta=delta):
                        self.assertEqual(derive_report_title(answer, 'Q'),
                                         'Q' if length > 200000 else 'a' * 120)
        for answer in ('**' + 'a' * 199997 + '**', '`' + 'x' * 199999 + '`',
                       '**' + 'a' * 1000000 + '**'):
            with self.subTest(reviewer_length=len(answer)):
                self.assertEqual(derive_report_title(answer, 'Q'), 'Q')

    def test_report_title_escaped_backtick_runs(self):
        cases = [
            (r'\`', '`'), (r'\\`', '\\`'), (r'\`\`', '``'),
            (r'\``foo`', '`foo'), (r'\```foo``', '`foo'),
            (r'\``Итоги`', '`Итоги'),
            ('` a `b', 'ab'), ('a` b `', 'ab'), ('`` a`b ``c', 'a`bc'),
        ]
        for width in range(1, 6):
            ticks = '`' * width
            cases.extend([
                ('\\' + '`' + ticks + 'foo' + ticks, '`foo'),
                ('\\\\' + ticks + 'foo' + ticks, '\\foo'),
                (ticks + 'foo\\' + ticks, 'foo\\'),
                (ticks + 'foo' + ticks + '\\', 'foo\\'),
                ('\\' + ticks + 'foo' + ticks, ticks + 'foo' + ticks),
            ])
        for answer, expected in cases:
            with self.subTest(answer=answer):
                self.assertEqual(derive_report_title(answer, 'Q'), expected)

    def test_report_title_oracle_hostile_edges(self):
        for repeats in (128, 256, 512):
            with self.subTest(alternations=repeats):
                self.assertEqual(derive_report_title('*_*_*_' * repeats, 'Q'), '_*' * 60)
        for repeats in (31, 32, 33):
            with self.subTest(destination_depth=repeats - 1):
                self.assertEqual(derive_report_title('[a](' * repeats + ')' * repeats +
                                                     ' "unterminated', 'Q'), 'a "unterminated')
        for repeats in (5000, 10000, 20000):
            with self.subTest(destination_depth=repeats - 1):
                self.assertEqual(derive_report_title('[a](' * repeats + ')' * repeats +
                                                     ' "unterminated', 'Q'), '[a](' * 30)

    def test_report_title_inline_token_boundaries(self):
        cases = [
            ("<https://example.org/o'neil>", "https://example.org/o'neil"),
            ("<o'neil@example.org>", "o'neil@example.org"),
            ("&unknown **Итоги** &amp; очки", "&unknown Итоги & очки"),
            ("&notanentity; **Итоги**", "&notanentity; Итоги"),
            ("&#" + "9" * 5000 + ";", "&#" + "9" * 118),
            ("&#12345678;", "&#12345678;"),
            ("[**Итоги**](https://example.org/a_(b_(c)))", "Итоги"),
            ("``Итоги `сезона` ``", "Итоги `сезона`"),
            ("````Итоги````", "Итоги"),
            (r"[Итоги](https://example.org/a_\(b\))", "Итоги"),
            (r"\# Итоги \_сезона\_", "# Итоги _сезона_"),
            ('<span title="x > y">**Итоги**</span>', "Итоги"),
            ("`<b>*Итоги*</b>`", "<b>*Итоги*</b>"),
            ("<https://example.org/a_(b)>", "https://example.org/a_(b)"),
            ("~~~text\n# literal\n~~~~", "# literal"),
        ]
        for answer, expected in cases:
            with self.subTest(answer=answer):
                self.assertEqual(derive_report_title(answer, "Вопрос"), expected)

    def test_report_title_parser_input_bounds(self):
        for answer, inline_input, expected in [
            ('[' * 20000, '[' * 20000, '[' * 120),
            ('# ' + 'a' * 7000, 'a' * 7000, 'a' * 120),
            ('**' + 'a' * 2100 + '**', '**' + 'a' * 2100 + '**', 'a' * 120),
            ('**' + 'a' * 199996 + '**', '**' + 'a' * 199996 + '**', 'a' * 120),
        ]:
            with self.subTest(answer_length=len(answer)):
                with patch.object(report_title, '_parse_answer', wraps=report_title._parse_answer) as blocks:
                    with patch.object(report_title, 'inline_text', wraps=report_title.inline_text) as inlines:
                        title = derive_report_title(answer, 'Question')
                self.assertEqual(blocks.call_args.args[0], answer)
                self.assertEqual(inlines.call_args.args[0], inline_input)
                self.assertTrue(all(len(call.args[0]) <= 200000 for call in inlines.call_args_list))
                self.assertEqual(title, expected)
        with patch.object(report_title, 'inline_text', wraps=report_title.inline_text) as inlines:
            self.assertEqual(derive_report_title('a' * 200100, 'Question'), 'a' * 120)
        self.assertEqual(inlines.call_count, 0)
        answer = '<!-- hidden -->\n' * 62500 + '# outside'
        with patch.object(report_title, '_parse_answer', wraps=report_title._parse_answer) as blocks:
            self.assertEqual(derive_report_title(answer, 'Question'), 'Question')
        self.assertEqual(blocks.call_args.args[0], '<!-- hidden -->\n' * 62500)

    def test_report_title_linear_operations(self):
        families = [
            ('brackets', '[', '', '[' * 120),
            ('stars', '*', '', 'Question'),
            ('underscores', '_', '', 'Question'),
            ('backticks', '`', '', 'Question'),
            ('angles', '<', '', '<' * 120),
            ('images', '![', '', '![' * 60),
            ('destinations', '[a](', '', '[a](' * 30),
            ('quotes', '> ', 'Title', 'Title'),
            ('lists', '- ', 'Title', 'Title'),
            ('unmatched-emphasis', '**a ', '', ('**a ' * 30).rstrip()),
            ('malformed-tags', '<a x="', '', ('<a x="' * 20)),
        ]
        for label, fragment, suffix, expected in families:
            counts = []
            for size in (5000, 20000):
                answer = fragment * size + suffix
                work = ParseWork()
                title = derive_report_title(answer, 'Question', work)
                with self.subTest(family=label, size=size):
                    self.assertEqual(title, expected)
                    self.assertLessEqual(work.total, 64 * len(answer))
                    self.assertGreaterEqual(work.total, len(answer))
                    self.assertLessEqual(len(title), 120)
                    self.assertEqual(title, title.strip())
                counts.append(work.total)
                print('TITLE_OPERATIONS ' + json.dumps({
                    'family': label, 'size': size, 'length': len(answer),
                    'characters': work.characters, 'tokens': work.tokens,
                    'delimiters': work.delimiters, 'count': work.total,
                }))
            with self.subTest(family=label, scaling=True):
                self.assertGreaterEqual(counts[1] / counts[0], 3.8)
                self.assertLessEqual(counts[1] / counts[0], 4.2)
        counts = []
        for size in (5000, 20000):
            pieces, width, length = ['x '], 1, 2
            while length + width + 2 <= size:
                pieces.append('`' * width + 'x ')
                length += width + 2
                width += 1
            answer = ''.join(pieces) + 'x' * (size - length)
            work = ParseWork()
            self.assertEqual(derive_report_title(answer, 'Question', work), answer[:120].rstrip())
            self.assertLessEqual(work.total, 64 * len(answer))
            counts.append(work.total)
            print('TITLE_OPERATIONS ' + json.dumps({
                'family': 'distinct-backtick-runs', 'size': size, 'length': len(answer),
                'characters': work.characters, 'tokens': work.tokens,
                'delimiters': work.delimiters, 'count': work.total,
            }))
        self.assertGreaterEqual(counts[1] / counts[0], 3.8)
        self.assertLessEqual(counts[1] / counts[0], 4.2)

    def test_report_title_stops_block_selection_and_emission(self):
        work = ParseWork()
        self.assertEqual(derive_report_title('**' + 'a' * 149996 + '**\n' +
                                            'ignored\n' * 10000, 'Question', work), 'a' * 120)
        self.assertEqual(work.lines, 1)
        self.assertEqual(work.emitted, 120)
        self.assertGreater(work.characters, 150000)

    def test_report_title_pathological_inputs(self):
        cases = [
            ('[' * 20000, '[' * 120),
            ('[' * 40000, '[' * 120),
            ('*' * 50000, 'Question'),
            ('Слово' * 100000, 'Слово' * 24),
            ('<!-- hidden -->\n' * 10000 + '# visible', 'visible'),
        ]
        code = (
            'import json, sys\n'
            'from report_title import derive_report_title\n'
            'answers = json.load(sys.stdin)\n'
            'print(json.dumps([derive_report_title(answer, "Question") for answer in answers]))\n'
        )
        # Only a subprocess hang guard, not a wall-clock performance assertion.
        result = subprocess.run(
            [sys.executable, '-c', code], input=json.dumps([answer for answer, _ in cases]),
            capture_output=True, text=True, check=True, timeout=600)
        self.assertEqual(json.loads(result.stdout), [expected for _, expected in cases])

    def test_report_title_generated_inputs(self):
        rng = random.Random(25)
        alphabet = string.printable + string.punctuation * 4
        for case in range(512):
            answer = ''.join(rng.choices(alphabet, k=rng.randrange(513)))
            question = ''.join(rng.choices(alphabet, k=rng.randrange(257)))
            for text in (answer, ''):
                with self.subTest(case=case, answer=text, question=question):
                    title = derive_report_title(text, question)
                    self.assertIsInstance(title, str)
                    self.assertLessEqual(len(title), 120)
                    self.assertEqual(title, title.strip())

    async def test_report_retains_mysql_scalar_rows(self):
        rows = [{'day': date(2026, 10, 1), 'moment': datetime(2026, 10, 1, 12, 30),
                 'clock': time(12, 30), 'amount': Decimal('1234.5678'),
                 'count': Decimal('100000'), 'id': uuid4(), 'label': b'rows'}]
        agent = FakeAgent()
        agent.result = success('Report', [], rows, reasoning=None,
                               report_handle={'tool': 'read_rows', 'args': {}})
        self.agent = agent
        run = await self.submit()
        done = await self.finish(run['request_id'])
        self.assertEqual(done['state'], 'succeeded', done)
        response = done['response']
        assert response is not None
        self.assertEqual(response['data'], jsonable_encoder(rows))
        report = await self.store.get_report(response['report']['id'])
        assert report is not None
        self.assertEqual(report['data'], jsonable_encoder(rows))

    async def test_report_retains_reviewer_date_key_repro(self):
        rows = [{date(2026, 10, 1): Decimal("1.25")}]
        agent = FakeAgent()
        agent.result = success("Report", [], rows, reasoning=None,
                               report_handle={"tool": "read_rows", "args": {}})
        self.agent = agent
        run = await self.submit()
        done = await self.finish(run["request_id"])
        self.assertEqual(done["state"], "succeeded", done)
        response = done["response"]
        assert response is not None
        report = await self.store.get_report(response["report"]["id"])
        assert report is not None
        self.assertEqual(response["data"], jsonable_encoder(rows))
        self.assertEqual(report["data"], jsonable_encoder(rows))

    async def test_collision_repro_fails_without_retaining_report(self):
        rows = [{date(2026, 10, 1): object(), "2026-10-01": 1}]
        agent = FakeAgent()
        agent.result = success("Report", [], rows, reasoning=None,
                               report_handle={"tool": "read_rows", "args": {}})
        self.agent = agent
        run = await self.submit()
        done = await self.finish(run["request_id"])
        self.assertEqual(done["state"], "failed", done)
        error = done["error"]
        assert error is not None
        self.assertEqual(error["code"], "internal:TypeError")
        self.assertIsNone(done["response"])
        self.assertEqual(await self.store.list_reports(self.chat), [])

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
