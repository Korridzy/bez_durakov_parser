"""Retained report endpoints; Update replays the stored tool handle without a model."""

import asyncio
import importlib
import logging
from weakref import WeakValueDictionary

from fastapi import APIRouter, Response

from bd_shared.config import AGENT_TIMEOUT_SECONDS
from api_errors import ApiError
from chat_store import ReportNotFound
from timestamps import utc_now

router = APIRouter()
logger = logging.getLogger(__name__)
_update_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def _runtime():
    # Resolve mutable runtime globals per request, including test-installed stores.
    return importlib.import_module("main")


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Не найдено")


def _report_busy() -> ApiError:
    return ApiError(409, "report_busy", "Отчёт занят, повторите позже")


@router.get("/api/chats/{chat_id}/reports")
async def chat_reports(chat_id: str):
    store = _runtime().chat_store
    if await store.get_chat(chat_id) is None:
        raise _not_found()
    return await store.list_reports(chat_id)


@router.get("/api/reports/{report_id}")
async def get_report(report_id: str):
    report = await _runtime().chat_store.get_report(report_id)
    if report is None:
        raise _not_found()
    return report


@router.put("/api/reports/{report_id}/saved")
async def save_report(report_id: str):
    try:
        return await _runtime().chat_store.set_saved(report_id, True)
    except ReportNotFound as error:
        raise _not_found() from error


@router.delete("/api/reports/{report_id}/saved", status_code=204)
async def unsave_report(report_id: str):
    try:
        await _runtime().chat_store.set_saved(report_id, False)
    except ReportNotFound as error:
        raise _not_found() from error
    return Response(status_code=204)


@router.get("/api/saved-reports")
async def saved_reports():
    return await _runtime().chat_store.list_saved_reports()


@router.post("/api/reports/{report_id}/update")
async def update_report(report_id: str):
    runtime = _runtime()
    store = runtime.chat_store
    report = await store.get_report(report_id)
    if report is None:
        raise _not_found()
    chat_id = report["chat_id"]
    if chat_id is not None and await runtime.registry.store.active_run(chat_id) is not None:
        raise _report_busy()

    # A lock is never waited on: a second request sees busy immediately. The weak
    # map releases inactive locks without accumulating one per report forever.
    lock = _update_locks.setdefault(report_id, asyncio.Lock())
    if lock.locked():
        raise _report_busy()
    async with lock:
        if runtime.tool_service is None:
            raise ApiError(503, "tool_service_unavailable", "Сервис данных недоступен")
        try:
            data = await asyncio.wait_for(
                runtime.tool_registry.execute_response(report["tool"], report["args"]),
                AGENT_TIMEOUT_SECONDS,
            )
            generated_at = utc_now()
            updated = await store.replace_report_data(
                report_id, data, generated_at, expected_version=report["version"]
            )
        except Exception as error:
            logger.warning("Report update failed: report_id=%s exception=%s", report_id, type(error).__name__)
            raise ApiError(
                502, "update_failed", f"Не удалось обновить отчёт ({type(error).__name__})",
                body_extra={"report": report},
            ) from error
        if updated is None:
            if await store.get_report(report_id) is None:
                raise _not_found()
            raise _report_busy()
        return updated
