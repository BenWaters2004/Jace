"""C5B.1 offline receipt tests. No external model, network or user DB calls."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jace.model_gateway import receipts as r


ROUTE = SimpleNamespace(provider="openai", model="test-only", route_id="openai:test-only")
PRIVACY = SimpleNamespace(classification="public", mode="protected_cloud", action="allow")


class ReceiptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.saved = []
        async def capture(record):
            self.saved.append(record)
            return True
        self.capture_patch = patch.object(r, "persist_receipt", new=capture)
        self.capture_patch.start()

    def tearDown(self):
        self.capture_patch.stop()

    async def test_stream_per_adapter_attempt(self):
        async def stream():
            yield {"message": {"content": "private output"}, "done": False}
            yield {"done": True, "prompt_eval_count": 23, "eval_count": 5}
        with patch.object(r.settings, "cloud_pricing_json", '{"openai:test-only":{"input_per_million":1,"output_per_million":3}}'):
            data = [x async for x in r.traced_stream(route=ROUTE, capability="conversation.fast",
                       operation="stream_chat", privacy=PRIVACY,
                       requested_route="anthropic:requested", stream=stream())]
        self.assertEqual(len(data), 2)
        self.assertEqual(len(self.saved), 1)
        row = self.saved[0]
        self.assertEqual((row.provider_id, row.model, row.status), ("openai", "test-only", "success"))
        self.assertTrue(row.route_changed)
        self.assertEqual((row.input_tokens, row.output_tokens), (23, 5))
        self.assertAlmostEqual(row.estimated_cost_usd, 0.000038)
        self.assertEqual(row.privacy_classification, "public")
        self.assertIsNone(row.provider_request_id)
        self.assertNotIn("private output", str(row.__dict__))

    async def test_incomplete_stream_not_success(self):
        async def stream():
            yield {"done": False, "message": {"content": "partial"}}
        [x async for x in r.traced_stream(route=ROUTE, capability="reasoning.high", operation="stream_chat",
              privacy=PRIVACY, requested_route=None, stream=stream())]
        self.assertEqual(self.saved[0].status, "incomplete")
        self.assertIsNone(self.saved[0].estimated_cost_usd)

    async def test_stream_failed_sanitized(self):
        async def stream():
            raise RuntimeError("DO_NOT_LOG_THIS_SECRET")
            yield {}
        with self.assertRaises(RuntimeError):
            [x async for x in r.traced_stream(route=ROUTE, capability="reasoning.high", operation="stream_chat",
                  privacy=PRIVACY, requested_route=None, stream=stream())]
        self.assertEqual(self.saved[0].status, "error")
        self.assertEqual(self.saved[0].error_category, "RuntimeError")
        self.assertNotIn("DO_NOT_LOG_THIS_SECRET", str(self.saved[0].__dict__))

    async def test_cancelled_stream(self):
        async def stream():
            yield {"done": False, "message": {"content": "first"}}
            await asyncio.sleep(30)
        it = r.traced_stream(route=ROUTE, capability="conversation.fast", operation="stream_chat",
                             privacy=PRIVACY, requested_route=None, stream=stream())
        await anext(it)
        await it.aclose()
        self.assertEqual(self.saved[0].status, "cancelled")

    async def test_structured_no_tokens_invented(self):
        async def call():
            return {"value": "dummy"}
        result = await r.traced_call(route=ROUTE, capability="memory.extract", operation="structured_chat",
                                     privacy=PRIVACY, requested_route=None, invoke=call)
        self.assertEqual(result["value"], "dummy")
        row = self.saved[0]
        self.assertIsNone(row.input_tokens)
        self.assertIsNone(row.estimated_cost_usd)
        self.assertEqual(row.usage_source, "unavailable")

    async def test_embedding_error(self):
        async def call():
            raise LookupError("NOT_TO_BE_STORED")
        with self.assertRaises(LookupError):
            await r.traced_call(route=ROUTE, capability="embedding", operation="embedding",
                                privacy=PRIVACY, requested_route=None, invoke=call)
        self.assertEqual(self.saved[0].status, "error")
        self.assertEqual(self.saved[0].error_category, "LookupError")
        self.assertNotIn("NOT_TO_BE_STORED", str(self.saved[0].__dict__))

    async def test_unpriced_usage_stays_unknown(self):
        async def stream():
            yield {"done": True, "prompt_eval_count": 10, "eval_count": 20}
        with patch.object(r.settings, "cloud_pricing_json", "{}"):
            [x async for x in r.traced_stream(route=ROUTE, capability="conversation.fast",
                  operation="stream_chat", privacy=PRIVACY, requested_route=None, stream=stream())]
        self.assertIsNone(self.saved[0].estimated_cost_usd)
        self.assertEqual(self.saved[0].usage_source, "provider_terminal")

    async def test_unknown_usage_zeros_are_not_estimated(self):
        async def stream():
            yield {"done": True, "prompt_eval_count": 0, "eval_count": 0}
        [x async for x in r.traced_stream(route=ROUTE, capability="conversation.fast",
             operation="stream_chat", privacy=PRIVACY, requested_route=None, stream=stream())]
        self.assertIsNone(self.saved[0].input_tokens)

    @unittest.skipUnless(importlib.util.find_spec("aiosqlite"), "aiosqlite not installed")
    async def test_real_disposable_sqlite_persistence(self):
        self.capture_patch.stop()
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(lambda conn: r.ModelInvocationReceipt.__table__.create(conn))
            factory = async_sessionmaker(engine, expire_on_commit=False)
            with patch("jace.database.SessionLocal", factory):
                async def call(): return "done"
                await r.traced_call(route=ROUTE, capability="reasoning.high",
                    operation="structured_chat", privacy=PRIVACY,
                    requested_route=None, invoke=call)
                async with factory() as session:
                    rows = (await session.execute(select(r.ModelInvocationReceipt))).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "success")
        finally:
            await engine.dispose()
            self.capture_patch.start()


if __name__ == "__main__":
    unittest.main()
