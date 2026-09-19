"""Tests for request correlation and structured HTTP request logging."""

import asyncio
import io
import json
import re
import unittest

import fastapi
import httpx
import structlog
from fastapi.testclient import TestClient

from bd_shared import logging_setup
from request_context import RequestCorrelationMiddleware

GENERATED_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")


class RequestCorrelationMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        logging_setup._reset_for_tests()
        self.log_stream = io.StringIO()
        logging_setup.configure_logging(
            "test-backend", log_format="json", stream=self.log_stream
        )
        self.entered = {"a": asyncio.Event(), "b": asyncio.Event()}
        self.release = asyncio.Event()

        api = fastapi.FastAPI()

        @api.get("/ping")
        async def ping() -> dict[str, bool]:
            return {"ok": True}

        @api.get("/boom")
        async def boom() -> None:
            raise RuntimeError("boom")

        @api.get("/items/{item_id}")
        async def item(item_id: str) -> dict[str, str]:
            return {"item_id": item_id}

        @api.get("/log")
        async def log_inside() -> dict[str, bool]:
            structlog.get_logger("t").info("inside")
            return {"ok": True}

        @api.get("/wait/{name}")
        async def wait_inside(name: str) -> dict[str, str]:
            self.entered[name].set()
            await self.release.wait()
            structlog.get_logger("t").info("inside", name=name)
            return {"name": name}

        self.wrapped = RequestCorrelationMiddleware(api)

    def tearDown(self) -> None:
        logging_setup._reset_for_tests()

    def records(self, event: str | None = None) -> list[dict[str, object]]:
        records = [
            json.loads(line)
            for line in self.log_stream.getvalue().splitlines()
            if line
        ]
        if event is None:
            return records
        return [record for record in records if record.get("event") == event]

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | list[tuple[bytes, bytes]] | None = None,
        raise_server_exceptions: bool = False,
    ) -> httpx.Response:
        with TestClient(
            self.wrapped, raise_server_exceptions=raise_server_exceptions
        ) as client:
            return client.request(method, path, headers=headers)

    def assert_invalid_id_is_replaced(
        self, headers: list[tuple[bytes, bytes]]
    ) -> None:
        response = self.request("GET", "/ping", headers=headers)

        request_id = response.headers["x-request-id"]
        self.assertRegex(request_id, GENERATED_REQUEST_ID)
        [request_record] = self.records("http_request")
        self.assertEqual(request_record["request_id"], request_id)

    def test_missing_header_generates_id_and_logs_request_fields(self) -> None:
        response = self.request("GET", "/ping")

        request_id = response.headers["x-request-id"]
        self.assertRegex(request_id, GENERATED_REQUEST_ID)
        [request_record] = self.records("http_request")
        self.assertEqual(request_record["request_id"], request_id)
        self.assertEqual(request_record["method"], "GET")
        self.assertEqual(request_record["route"], "/ping")
        self.assertEqual(request_record["status"], 200)
        self.assertIn(type(request_record["duration_ms"]), (int, float))

    def test_valid_header_is_echoed_and_bound_to_endpoint_log(self) -> None:
        response = self.request(
            "GET", "/log", headers={"X-Request-ID": "abc.DEF-123_x"}
        )

        self.assertEqual(response.headers["x-request-id"], "abc.DEF-123_x")
        [inside_record] = self.records("inside")
        self.assertEqual(inside_record["request_id"], "abc.DEF-123_x")

    def test_empty_header_is_replaced(self) -> None:
        self.assert_invalid_id_is_replaced([(b"x-request-id", b"")])

    def test_oversized_header_is_replaced(self) -> None:
        self.assert_invalid_id_is_replaced([(b"x-request-id", b"a" * 129)])

    def test_header_with_space_is_replaced(self) -> None:
        self.assert_invalid_id_is_replaced([(b"x-request-id", b"a b")])

    def test_non_ascii_header_is_replaced(self) -> None:
        self.assert_invalid_id_is_replaced(
            [(b"x-request-id", "ю".encode("utf-8"))]
        )

    def test_duplicated_header_is_replaced(self) -> None:
        self.assert_invalid_id_is_replaced(
            [(b"x-request-id", b"first"), (b"X-Request-ID", b"second")]
        )

    def test_route_template_is_logged_instead_of_raw_path(self) -> None:
        response = self.request("GET", "/items/42")

        self.assertEqual(response.status_code, 200)
        [request_record] = self.records("http_request")
        self.assertEqual(request_record["route"], "/items/{item_id}")

    def test_unmatched_route_logs_raw_path_and_404(self) -> None:
        response = self.request("GET", "/nonexistent")

        self.assertEqual(response.status_code, 404)
        [request_record] = self.records("http_request")
        self.assertEqual(request_record["route"], "/nonexistent")
        self.assertEqual(request_record["status"], 404)

    def test_exception_response_has_id_and_error_record(self) -> None:
        response = self.request(
            "GET", "/boom", headers={"X-Request-ID": "boom-id"}
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["x-request-id"], "boom-id")
        [request_record] = self.records("http_request")
        self.assertEqual(request_record["level"], "error")
        self.assertEqual(request_record["status"], 500)
        self.assertIn("exception", request_record)

    def test_exception_still_propagates_when_client_requests_it(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "boom"):
            self.request("GET", "/boom", raise_server_exceptions=True)

    def test_head_request_is_logged(self) -> None:
        response = self.request("HEAD", "/ping")

        [request_record] = self.records("http_request")
        self.assertEqual(request_record["method"], "HEAD")
        self.assertEqual(request_record["status"], response.status_code)

    def test_options_request_is_logged(self) -> None:
        response = self.request("OPTIONS", "/ping")

        [request_record] = self.records("http_request")
        self.assertEqual(request_record["method"], "OPTIONS")
        self.assertEqual(request_record["status"], response.status_code)

    async def test_lifespan_scope_passes_through_without_binding(self) -> None:
        calls: list[dict[str, object]] = []
        seen_context: list[dict[str, object]] = []

        async def app(scope, receive, send) -> None:
            del receive, send
            calls.append(scope)
            seen_context.append(structlog.contextvars.get_contextvars())

        middleware = RequestCorrelationMiddleware(app)
        scope = {"type": "lifespan"}
        structlog.contextvars.bind_contextvars(request_id="outer")

        async def receive() -> dict[str, str]:
            return {"type": "lifespan.startup"}

        async def send(message: dict[str, object]) -> None:
            del message

        await middleware(scope, receive, send)

        self.assertEqual(calls, [scope])
        self.assertEqual(seen_context, [{"request_id": "outer"}])
        self.assertEqual(self.records("http_request"), [])

    async def test_contextvars_are_cleared_after_async_transport_request(
        self,
    ) -> None:
        transport = httpx.ASGITransport(app=self.wrapped)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://t"
        ) as client:
            response = await client.get("/ping")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(structlog.contextvars.get_contextvars(), {})

    async def test_concurrent_requests_keep_request_ids_isolated(self) -> None:
        transport = httpx.ASGITransport(app=self.wrapped)
        tasks: list[asyncio.Task[httpx.Response]] = []
        async with httpx.AsyncClient(
            transport=transport, base_url="http://t"
        ) as client:
            tasks = [
                asyncio.create_task(
                    client.get("/wait/a", headers={"X-Request-ID": "aaaa"})
                ),
                asyncio.create_task(
                    client.get("/wait/b", headers={"X-Request-ID": "bbbb"})
                ),
            ]
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        self.entered["a"].wait(), self.entered["b"].wait()
                    ),
                    5,
                )
                self.release.set()
                responses = await asyncio.wait_for(asyncio.gather(*tasks), 5)
            finally:
                self.release.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual([response.status_code for response in responses], [200, 200])
        inside_records = {
            record["name"]: record for record in self.records("inside")
        }
        self.assertEqual(inside_records["a"]["request_id"], "aaaa")
        self.assertEqual(inside_records["b"]["request_id"], "bbbb")
        request_records = self.records("http_request")
        self.assertEqual(
            {record["request_id"] for record in request_records},
            {"aaaa", "bbbb"},
        )
        self.assertEqual(
            {record["route"] for record in request_records}, {"/wait/{name}"}
        )


if __name__ == "__main__":
    unittest.main()
