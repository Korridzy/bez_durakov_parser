"""Durable chat and background run HTTP surface."""
import asyncio
from typing import Any
from weakref import WeakValueDictionary

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from api_errors import ApiError
from chat_store import ChatBusy as StoreChatBusy, ChatNotFound, RequestConflict
from runs import (ChatBusy, InvalidRequest, ModelUnavailable, Overloaded, RunNotFound,
                  ToolServiceUnavailable)

router = APIRouter(prefix="/api")
_submission_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


class ChatCreate(BaseModel):
    title: str | None = None


class ChatRename(BaseModel):
    title: str


class SendMessage(BaseModel):
    request_id: str
    message: str


class CancelRun(BaseModel):
    request_id: str


def _public_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    if run["response"] is None:
        return run
    return {**run, "response": {**run["response"], "data": None}}


def _invalid(message: str) -> ApiError:
    return ApiError(422, "invalid_request", message)


def _title(value: str) -> str:
    title = " ".join(value.split())
    if not 1 <= len(title) <= 80:
        raise _invalid("Название должно содержать от 1 до 80 символов")
    return title


async def _existing_chat(chat_id: str):
    import main
    chat = await main.chat_store.get_chat(chat_id)
    if chat is None:
        raise ApiError(404, "not_found", "Чат не найден")
    return chat


@router.post("/chats", status_code=201)
async def create_chat(body: ChatCreate):
    import main
    return await main.chat_store.create_chat(_title(body.title) if body.title is not None else None)


@router.get("/chats")
async def list_chats(q: str | None = None, limit: int = Query(50, ge=1, le=100),
                     cursor: str | None = None):
    import main
    try:
        items, next_cursor = await main.chat_store.list_chats(q, limit, cursor)
    except ValueError as error:
        raise _invalid("Неверный курсор списка чатов") from error
    return {"items": items, "next_cursor": next_cursor}


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: str):
    import main
    chat = await _existing_chat(chat_id)
    return {"chat": chat, "messages": await main.chat_store.list_messages(chat_id),
            "reports": await main.chat_store.list_reports(chat_id),
            "active_run": _public_run(await main.chat_store.active_run(chat_id)),
            "last_run": _public_run(await main.chat_store.last_run(chat_id))}


@router.patch("/chats/{chat_id}")
async def rename_chat(chat_id: str, body: ChatRename):
    import main
    try:
        return await main.chat_store.rename_chat(chat_id, _title(body.title))
    except ChatNotFound as error:
        raise ApiError(404, "not_found", "Чат не найден") from error


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(chat_id: str):
    import main
    async with main.admission_lock:
        if main.pinned.get(chat_id, 0):
            raise ApiError(409, "chat_busy", "Чат занят, дождитесь ответа")
        try:
            await main.chat_store.delete_chat(chat_id)
        except ChatNotFound as error:
            raise ApiError(404, "not_found", "Чат не найден") from error
        except StoreChatBusy as error:
            raise ApiError(409, "chat_busy", "Чат занят, дождитесь ответа") from error
        await main.checkpoint_saver.adelete_thread(chat_id)
        await main.sessions.drop(chat_id)


@router.post("/chats/{chat_id}/messages", status_code=202)
async def send_message(chat_id: str, body: SendMessage, response: Response):
    import main
    if not body.message.strip():
        raise _invalid("Сообщение не должно быть пустым")
    try:
        # Serialize only submissions sharing an id; creation versus reuse is
        # decided by the registry's store transaction, not an earlier route read.
        lock = _submission_locks.setdefault(body.request_id, asyncio.Lock())
        async with lock:
            submitted = await main.registry.submit(chat_id, body.request_id, body.message)
    except InvalidRequest as error:
        raise _invalid("Неверный request_id") from error
    except ChatNotFound as error:
        raise ApiError(404, "not_found", "Чат не найден") from error
    except RequestConflict as error:
        raise ApiError(409, "request_conflict", "Идентификатор запроса уже использован") from error
    except ChatBusy as error:
        raise ApiError(409, "chat_busy", "Чат занят, дождитесь ответа") from error
    except Overloaded as error:
        raise ApiError(503, "overloaded", "Сервер перегружен, повторите позже") from error
    except ToolServiceUnavailable as error:
        raise ApiError(503, "tool_service_unavailable", "Сервис инструментов недоступен") from error
    except ModelUnavailable as error:
        raise ApiError(503, "llm_proxy_unavailable", main.MODEL_UNAVAILABLE_MESSAGE) from error
    if not submitted.created:
        response.status_code = 200
    return _public_run(submitted.run)


@router.get("/chats/{chat_id}/status")
async def chat_status(chat_id: str):
    import main
    await _existing_chat(chat_id)
    return {"active_run": _public_run(await main.chat_store.active_run(chat_id)),
            "last_run": _public_run(await main.chat_store.last_run(chat_id))}


@router.post("/chats/{chat_id}/cancel", status_code=202)
async def cancel_run(chat_id: str, body: CancelRun, response: Response):
    import main
    try:
        run = await main.registry.cancel(chat_id, body.request_id)
    except RunNotFound as error:
        raise ApiError(404, "not_found", "Запрос не найден") from error
    if run["state"] not in ("running", "cancelling"):
        response.status_code = 200
    return _public_run(run)


@router.get("/runs/{request_id}")
async def get_run(request_id: str):
    import main
    run = await main.chat_store.get_run(request_id)
    if run is None:
        raise ApiError(404, "not_found", "Запрос не найден")
    return _public_run(run)
