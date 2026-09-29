"""Background chat runs, with a durable completion barrier and late-bound runtime."""
import asyncio
from dataclasses import dataclass, field
import logging
import re
from uuid import uuid4

import structlog
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.report_support import failure
from chat_store import ChatNotFound, RunConflict, RequestConflict, RequestExists
from request_context import derive_trace_id, new_request_id

logger = logging.getLogger(__name__)
RESEED_MAX_PAIRS = 20
SHUTDOWN_GRACE_SECONDS = 15
REQUEST_ID = re.compile(r'^[0-9a-f]{32}$')
CANCEL_MARKER = 'Запрос отменён'
INTERRUPT_MARKER = 'Ответ прерван перезапуском сервера'


class InvalidRequest(ValueError):
    pass


class ModelUnavailable(RuntimeError):
    pass


class ToolServiceUnavailable(RuntimeError):
    pass


class Overloaded(RuntimeError):
    pass


class ChatBusy(RuntimeError):
    pass


class RunNotFound(LookupError):
    pass


@dataclass
class RunHandle:
    request_id: str
    chat_id: str
    task: asyncio.Task | None = None
    cancel_requested: bool = False
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    finalised: bool = False
    archive_row_id: int | None = None
    archive_completed: bool = False
    result: dict | None = None
    cancel_result: dict | None = None


class RunRegistry:
    def __init__(self, store, *, runtime, boot_id: str | None = None):
        self.store = store
        self.runtime = runtime
        self.boot_id = boot_id or uuid4().hex
        self.tasks: dict[str, RunHandle] = {}
        self.interrupted = False
        self._cancel_lock = asyncio.Lock()

    async def submit(self, chat_id: str, request_id: str, message: str):
        if not REQUEST_ID.fullmatch(request_id):
            raise InvalidRequest(request_id)
        if await self.store.get_chat(chat_id) is None:
            raise ChatNotFound(chat_id)
        rt = self.runtime()
        if getattr(rt, 'tool_service', True) is None:
            raise ToolServiceUnavailable()
        system = rt.agent_system
        if system is None and hasattr(rt, '_recover_agent_system'):
            system = await rt._recover_agent_system()
        if system is None or rt.checkpoint_saver is None:
            raise ModelUnavailable()
        pinned_added = False
        handle = None
        owns_handle = False
        registered = False
        try:
            async with rt.admission_lock:
                was_live = await rt.sessions.is_live(chat_id)
                for expired_id in await rt.sessions.expired_ids():
                    if rt.pinned.get(expired_id, 0) > 0:
                        continue
                    await rt.checkpoint_saver.adelete_thread(expired_id)
                    await rt.sessions.drop(expired_id)
                rt.pinned[chat_id] = rt.pinned.get(chat_id, 0) + 1
                pinned_added = True
                if not await rt.sessions.is_live(chat_id) and len(rt.sessions) >= rt.sessions.max_size:
                    victim = await rt.sessions.lru_victim(rt.pinned)
                    if victim is None:
                        raise Overloaded('Сервер перегружен, повторите позже')
                    await rt.checkpoint_saver.adelete_thread(victim)
                    await rt.sessions.drop(victim)
                await rt.sessions.touch(chat_id)
            # Register before the write can commit: cancel and wait can now find
            # this turn even while SQLite is committing or the caller is paused.
            existing = self.tasks.get(request_id)
            if existing is not None:
                await existing.ready.wait()
            handle = RunHandle(request_id, chat_id)
            owns_handle = self.tasks.setdefault(request_id, handle) is handle
            # Shield the whole write, not merely its commit: caller cancellation
            # joins the transaction before compensating a committed turn.
            write = asyncio.create_task(self.store.create_run(
                chat_id, request_id, message, self.boot_id, with_user_message=True,
            ))
            created = False
            try:
                try:
                    run = await asyncio.shield(write)
                except asyncio.CancelledError:
                    try:
                        await write
                    except Exception:
                        logger.exception('Cancelled submit transaction rolled back')
                    else:
                        created = True
                    raise
                except RunConflict as exc:
                    raise ChatBusy(chat_id) from exc
                except RequestExists as exc:
                    return exc.run
                created = True
                if not owns_handle:
                    raise RuntimeError('Run id is already owned by another submission')
                task = asyncio.create_task(self._execute(handle, message, was_live, system))
                handle.task = task
                task.add_done_callback(lambda _: asyncio.ensure_future(self._finalise(handle)))
                registered = True
                if handle.cancel_requested or self.interrupted:
                    task.cancel()
                handle.ready.set()
                pinned_added = False
                return run
            finally:
                if created and not registered:
                    await self.store.finish_run(request_id, 'cancelled', None, None)
                    await self.store.append_message(chat_id, request_id, 'assistant',
                                                    CANCEL_MARKER, None, 'cancelled', None)
        finally:
            if pinned_added:
                self._unpin(rt, chat_id)
            if owns_handle and not registered:
                assert handle is not None
                self.tasks.pop(request_id, None)
                handle.ready.set()
                handle.done.set()

    @staticmethod
    def _unpin(rt, chat_id):
        remaining = rt.pinned[chat_id] - 1
        if remaining:
            rt.pinned[chat_id] = remaining
        else:
            del rt.pinned[chat_id]

    async def _history(self, chat_id, was_live, system):
        history = []
        if not was_live:
            messages = await self.store.list_messages(chat_id)
            questions = {m['request_id']: m['content'] for m in messages if m['role'] == 'user'}
            pairs = [(questions[m['request_id']], m['content']) for m in messages
                     if m['role'] == 'assistant' and m['state'] == 'succeeded'
                     and m['request_id'] in questions]
            for question, answer in pairs[-RESEED_MAX_PAIRS:]:
                history.extend((HumanMessage(content=question), AIMessage(content=answer)))
        head = await system.head_messages(chat_id)
        if head and isinstance(head[-1], AIMessage):
            answered = {m.tool_call_id for m in head if isinstance(m, ToolMessage)}
            for call in head[-1].tool_calls:
                if call['id'] not in answered:
                    history.append(ToolMessage(content=CANCEL_MARKER, tool_call_id=call['id']))
        return history

    async def _execute(self, handle, message, was_live, system):
        try:
            rt = self.runtime()
            structlog.contextvars.bind_contextvars(session_id=handle.chat_id, run_id=handle.request_id)
            context = structlog.contextvars.get_contextvars()
            http_id = str(context.get('request_id') or new_request_id())
            trace_id = str(context.get('trace_id') or derive_trace_id(http_id))
            handle.archive_row_id = await rt.archive.begin(
                request_id=http_id, trace_id=trace_id, session_id=handle.chat_id,
                user_id=None, model=rt.AGENT_MODEL, user_message=message,
            )
            history = await self._history(handle.chat_id, was_live, system)
            result = await system.process_user_request(message, session_id=handle.chat_id, history=history)
            handle.result = result
            response = {
                'success': result['success'], 'session_id': handle.chat_id,
                'data': result.get('data'), 'query_info': result['query_info'],
                'message': result['message'], 'timestamp': result['timestamp'],
                'error': result.get('error'), 'reasoning': result.get('reasoning'),
                'scope_verdict': result.get('verdict'), 'report': None,
            }
            report = None
            marked = result.get('report_handle') if result['success'] else None
            if marked is not None:
                title = next((line.lstrip(' #*->\t').strip() for line in result['message'].splitlines()
                              if line.lstrip(' #*->\t').strip()), message)
                report = {
                    'id': uuid4().hex, 'title': title[:120], 'question': message,
                    'tool': marked['tool'], 'args': marked['args'], 'data': result.get('data'),
                    'generated_at': result['timestamp'],
                }
            pub = asyncio.ensure_future(self.store.publish_result(
                handle.request_id, assistant={'content': result['message'], 'reasoning': result.get('reasoning')},
                report=report, response=response,
                state='succeeded' if result['success'] else 'failed',
            ))
            try:
                await asyncio.shield(pub)
            except asyncio.CancelledError:
                await pub
                raise
        except asyncio.CancelledError:
            handle.cancel_result = failure(CANCEL_MARKER, 'cancelled')
            raise
        except Exception as error:
            handle.result = failure('Внутренняя ошибка', f'internal:{type(error).__name__}')
            await self.store.finish_run(handle.request_id, 'failed', None,
                                        (f'internal:{type(error).__name__}', 'Внутренняя ошибка'))
            await self.store.append_message(handle.chat_id, handle.request_id, 'assistant',
                                            'Внутренняя ошибка', None, 'failed', None)
            logger.exception('Background run failed')

    async def _finalise(self, handle):
        if handle.finalised:
            return
        handle.finalised = True
        run = None
        finalise_error = False
        try:
            try:
                run = await self.store.get_run(handle.request_id)
                if run is not None and run['state'] in ('running', 'cancelling'):
                    state = 'interrupted' if self.interrupted else 'cancelled'
                    marker = INTERRUPT_MARKER if self.interrupted else CANCEL_MARKER
                    try:
                        await self.store.finish_run(handle.request_id, state, None, None)
                    except Exception:
                        logger.exception('Normal terminal write failed; using minimal terminal write')
                        await self.store.force_fail_run(handle.request_id)
                        state, marker = 'failed', 'Внутренняя ошибка'
                        finalise_error = True
                    await self.store.append_message(handle.chat_id, handle.request_id,
                                                    'assistant', marker, None, state, None)
            except Exception:
                logger.exception('Run terminal persistence failed')
                finalise_error = True
                try:
                    await self.store.force_fail_run(handle.request_id)
                except Exception:
                    logger.exception('Minimal terminal write also failed')
            if handle.archive_row_id is not None and not handle.archive_completed:
                result = (failure('Внутренняя ошибка', 'internal:finalise') if finalise_error
                          else handle.result if run is not None and run['state'] in ('succeeded', 'failed')
                          else failure(INTERRUPT_MARKER, 'interrupted') if self.interrupted
                          else handle.cancel_result or failure(CANCEL_MARKER, 'cancelled'))
                try:
                    await self.runtime().archive.complete(handle.archive_row_id, result)
                    handle.archive_completed = True
                except Exception:
                    logger.exception('Archive completion failed during finalisation')
        finally:
            self._unpin(self.runtime(), handle.chat_id)
            self.tasks.pop(handle.request_id, None)
            handle.done.set()

    async def cancel(self, chat_id, request_id):
        async with self._cancel_lock:
            run = await self.store.get_run(request_id)
            if run is None or run['chat_id'] != chat_id:
                raise RunNotFound(request_id)
            if run['state'] not in ('running', 'cancelling'):
                return run
            handle = self.tasks.get(request_id)
            if handle is None:
                # A row from an earlier registry boot has no task to cancel.
                await self.store.finish_run(request_id, 'interrupted', None, None)
                await self.store.append_message(chat_id, request_id, 'assistant',
                                                INTERRUPT_MARKER, None, 'interrupted', None)
                return await self.store.get_run(request_id)
            if run['state'] == 'cancelling':
                return run
            await self.store.set_run_state(request_id, 'cancelling')
            handle.cancel_requested = True
            if handle.task is not None:
                handle.task.cancel()
            return await self.store.get_run(request_id)

    async def wait(self, request_id):
        handle = self.tasks.get(request_id)
        if handle is not None:
            await handle.done.wait()
        run = await self.store.get_run(request_id)
        if run is None:
            raise RunNotFound(request_id)
        if run['state'] in ('running', 'cancelling'):
            raise RuntimeError('Run finalisation did not persist a terminal state')
        return run

    async def sweep_on_startup(self):
        for run in await self.store.sweep_interrupted(self.boot_id):
            await self.store.append_message(run['chat_id'], run['request_id'],
                                            'assistant', INTERRUPT_MARKER, None, 'interrupted', None)

    async def shutdown(self):
        self.interrupted = True
        handles = list(self.tasks.values())
        for handle in handles:
            run = await self.store.get_run(handle.request_id)
            if handle.task is None:
                handle.cancel_requested = True
            elif run is not None and run['state'] != 'cancelling':
                handle.task.cancel()
        if handles:
            try:
                await asyncio.wait_for(asyncio.gather(*(h.done.wait() for h in handles)),
                                       SHUTDOWN_GRACE_SECONDS)
            except TimeoutError:
                logger.error('Run shutdown grace expired')
