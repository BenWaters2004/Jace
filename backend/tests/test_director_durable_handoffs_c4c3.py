"""C4C.3: offline SQLite tests; no user database, network or providers touched."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select, create_engine
from sqlalchemy.orm import sessionmaker

class _AsyncSessionAdapter:
    """Run Jace's ORM operations on a disposable synchronous SQLite database.

    This verifies atomic ORM behaviour without network or aiosqlite dependency;
    Jace's production async engine is separately covered by integration tests.
    """
    def __init__(self, sync_factory):
        self._session = sync_factory()
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        self._session.close()
    async def get(self, *args, **kwargs):
        return self._session.get(*args, **kwargs)
    async def execute(self, *args, **kwargs):
        return self._session.execute(*args, **kwargs)
    async def commit(self):
        self._session.commit()
    async def flush(self):
        self._session.flush()
    async def rollback(self):
        self._session.rollback()
    def add(self, value):
        self._session.add(value)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jace.agents import durable_handoffs as service
from jace.agents.models import AgentTask, AgentTaskEvent, DirectorHandoffReceipt
from jace.db.models import Base, Conversation, Message


class DurableHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="jace_c4c3_test_")
        db = Path(self.tmp.name) / "test.db"
        self.engine = create_engine(f"sqlite:///{db.as_posix()}")
        Base.metadata.create_all(self.engine)
        native_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.factory = lambda: _AsyncSessionAdapter(native_factory)
        self.override = patch.object(service, "SessionLocal", self.factory)
        self.override.start()
        self.conversation_id = "33333333-3333-4333-8333-333333333333"
        async with self.factory() as session:
            session.add(Conversation(id=self.conversation_id, title="Demo", model="openai:example", system_prompt=""))
            await session.commit()

    async def asyncTearDown(self):
        self.override.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    async def _task(self, task_id, used="[]", status="failed"):
        async with self.factory() as session:
            session.add(AgentTask(id=task_id, agent_id="code", title="test", instruction="test", status=status,
                                  used_tools_json=used))
            await session.commit()

    async def _event(self, task_id, kind):
        async with self.factory() as session:
            session.add(AgentTaskEvent(task_id=task_id, event_type=kind, message="test"))
            await session.commit()

    async def test_atomic_message_and_receipt(self):
        row = await service.save_handoff_once(workflow_id="workflow-1",conversation_id=self.conversation_id,
                                               objective="Review my code",result="Result",review_metadata={"status":"completed_excerpt_review"})
        self.assertTrue(row.created)
        async with self.factory() as session:
            receipt = await session.get(DirectorHandoffReceipt,"workflow-1")
            self.assertEqual(receipt.handoff_message_id,row.message_id)
            self.assertEqual(receipt.result_sha256,hashlib.sha256(b"Result").hexdigest())
            m = await session.get(Message,row.message_id)
            self.assertIn("Review my code",m.content)

    async def test_same_workflow_returns_existing_message(self):
        kwargs=dict(workflow_id="workflow-2",conversation_id=self.conversation_id,objective="A job",result="Result")
        a=await service.save_handoff_once(**kwargs)
        b=await service.save_handoff_once(**{**kwargs,"result":"Different text"})
        self.assertTrue(a.created)
        self.assertFalse(b.created)
        self.assertEqual(a.message_id,b.message_id)
        async with self.factory() as session:
            results=await session.execute(select(Message).where(Message.model=="agent:director"))
            self.assertEqual(len(results.scalars().all()),1)

    async def test_existing_receipt_recovery(self):
        row=await service.save_handoff_once(workflow_id="workflow-3",conversation_id=self.conversation_id,
                                             objective="Research this",result="Result")
        recovered=await service.existing_receipt("workflow-3")
        self.assertEqual(row.message_id,recovered.message_id)
        self.assertFalse(recovered.created)

    async def test_missing_conversation_records_receipt_without_message(self):
        row=await service.save_handoff_once(workflow_id="workflow-4",conversation_id="not-found",objective="Result",result="Nothing")
        self.assertEqual(row.status,"no_conversation")
        self.assertIsNone(row.message_id)
        self.assertFalse((await service.existing_receipt("workflow-4")).created)

    async def test_review_metadata_whitelist(self):
        metadata={"status":"completed_excerpt_review","source_count":3,"prompt":"PRIVATE","secret":"abc","model_calls":2,"external_fact_verification":False}
        row=await service.save_handoff_once(workflow_id="workflow-5",conversation_id=self.conversation_id,
                                             objective="Review",result="Okay",review_metadata=metadata)
        async with self.factory() as session:
            stored=await session.get(DirectorHandoffReceipt,"workflow-5")
            data=json.loads(stored.review_metadata_json)
            self.assertNotIn("prompt",data)
            self.assertNotIn("secret",data)
            self.assertEqual(data["source_count"],3)
            self.assertIs(data["external_fact_verification"],False)

    async def test_missing_receipt_is_none(self):
        self.assertIsNone(await service.existing_receipt("not-created"))

    async def test_retry_allowed_before_any_tool(self):
        await self._task("task-1")
        await self._event("task-1","queued")
        self.assertTrue(await service.failed_task_is_retry_safe("task-1"))

    async def test_retry_blocked_after_tool_attempt_event(self):
        await self._task("task-2")
        await self._event("task-2","tool_requested")
        self.assertFalse(await service.failed_task_is_retry_safe("task-2"))

    async def test_retry_blocked_after_approval_event(self):
        await self._task("task-3")
        await self._event("task-3","approval_required")
        self.assertFalse(await service.failed_task_is_retry_safe("task-3"))

    async def test_retry_blocked_after_used_tools_without_events(self):
        await self._task("task-4",used='["send_email"]')
        self.assertFalse(await service.failed_task_is_retry_safe("task-4"))

    async def test_retry_blocked_for_invalid_metadata(self):
        await self._task("task-5",used="not JSON")
        self.assertFalse(await service.failed_task_is_retry_safe("task-5"))

    async def test_retry_never_allowed_for_completed_task(self):
        await self._task("task-6",status="completed")
        self.assertFalse(await service.failed_task_is_retry_safe("task-6"))

    async def test_bad_workflow_id_rejected(self):
        with self.assertRaises(ValueError):
            await service.save_handoff_once(workflow_id="",conversation_id=self.conversation_id,objective="Objective",result="Result")

    def test_status_cannot_store_arbitrary_text(self):
        result=service.clean_review_metadata({"status":"incomplete\nsecret-key","some_key":"don't persist"})
        self.assertEqual(result["status"],"unknown")
        self.assertNotIn("some_key",result)

    def test_negative_cost_counter_is_discarded(self):
        result=service.clean_review_metadata({"model_calls":-7,"source_count":True})
        self.assertNotIn("model_calls",result)
        self.assertNotIn("source_count",result)

if __name__ == "__main__":
    unittest.main()
