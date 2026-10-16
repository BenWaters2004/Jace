"""C4C.3B offline tests: disposable SQLite, no provider or live database calls."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jace.agents.models import AgentTask, AgentTaskEvent, DirectorWorkflowCheckpoint
from jace.agents import workflow_checkpoints as w
from jace.db.models import Base


class _AsyncAdapter:
    def __init__(self, factory): self.session = factory()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.session.close()
    async def get(self, *args): return self.session.get(*args)
    async def execute(self, *args): return self.session.execute(*args)
    async def commit(self): self.session.commit()
    async def rollback(self): self.session.rollback()
    def add(self, x): self.session.add(x)


class WorkflowCheckpoints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="jace_c4c3b_offline_")
        db = Path(self.directory.name) / "fixture.db"
        self.engine = create_engine(f"sqlite:///{db.as_posix()}")
        Base.metadata.create_all(self.engine)
        factory = sessionmaker(self.engine, expire_on_commit=False)
        self.session_factory = lambda: _AsyncAdapter(factory)
        self.patch = patch.object(w, 'SessionLocal', self.session_factory)
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()
        self.engine.dispose()
        self.directory.cleanup()

    async def create(self, workflow="wf1", **kwargs):
        defaults = dict(workflow_id=workflow, conversation_id="test-conversation", objective="Inspect code",
                        plan={"summary":"explain", "steps":[{"id":"code","agent_id":"code"}]},
                        model="openai:test", temperature=0.3, reasoning_mode="balanced")
        defaults.update(kwargs)
        return await w.save_plan(**defaults)

    async def test_plan_is_persisted(self):
        row=await self.create()
        self.assertEqual(row.stage,"planned")
        self.assertEqual((await w.load_checkpoint('wf1')).plan["summary"],"explain")

    async def test_repeated_plan_does_not_overwrite(self):
        await self.create()
        row=await self.create(objective="Different task",model="anthropic:different")
        self.assertEqual(row.objective,"Inspect code")
        self.assertEqual(row.model,"openai:test")

    async def test_stages_in_order(self):
        await self.create()
        a=await w.save_stage('wf1','synthesized', synthesis='Original answer')
        self.assertEqual(a.synthesis,'Original answer')
        b=await w.save_stage('wf1','reviewed', final_result='Reviewed result',
                             review_metadata={'status':'completed', 'source_count':2, 'prompt':'private'})
        self.assertEqual(b.review_metadata['source_count'],2)
        self.assertNotIn('prompt', b.review_metadata)
        c=await w.save_stage('wf1','completed')
        self.assertEqual(c.stage,'completed')
        self.assertEqual(await w.incomplete_checkpoints(),[])

    async def test_review_requires_synthesis(self):
        await self.create()
        with self.assertRaises(ValueError): await w.save_stage('wf1','reviewed',final_result='No synthesis')

    async def test_save_stage_rejects_empty_text(self):
        await self.create()
        with self.assertRaises(ValueError): await w.save_stage('wf1','synthesized',synthesis='  ')

    async def test_complete_before_review_rejected(self):
        await self.create()
        with self.assertRaises(ValueError): await w.save_stage('wf1','completed')

    async def test_saved_stage_never_replaced(self):
        await self.create()
        await w.save_stage('wf1','synthesized', synthesis='First result')
        row=await w.save_stage('wf1','synthesized',synthesis='Attempted replacement')
        self.assertEqual(row.synthesis,'First result')

    async def test_incomplete_plan_is_discoverable_before_tasks(self):
        await self.create('wf0')
        self.assertEqual([r.workflow_id for r in await w.incomplete_checkpoints()],['wf0'])

    async def test_invalid_temperature_fails_closed(self):
        with self.assertRaises(ValueError): await self.create(temperature=float('nan'))

    async def test_invalid_mode_fails_closed(self):
        with self.assertRaises(ValueError): await self.create(reasoning_mode='unsupported')

    async def test_oversized_model_stage_rejected(self):
        await self.create()
        with self.assertRaises(ValueError): await w.save_stage('wf1','synthesized',synthesis='x'*(w.MAX_RESULT+1))

    async def test_unrecorded_job_is_not_falsely_recovered(self):
        self.assertIsNone(await w.load_checkpoint('not-here'))

    async def _task(self, name, used='[]', status='running', event=None):
        async with self.session_factory() as db:
            db.add(AgentTask(id=name,agent_id='code',title='example',instruction='example',status=status,used_tools_json=used))
            if event: db.add(AgentTaskEvent(task_id=name,event_type=event,message='example'))
            await db.commit()

    async def test_recovery_blocks_nonterminal_tool_history(self):
        await self._task('task1',event='tool_completed')
        self.assertTrue(await w.existing_task_requires_manual_review('task1'))

    async def test_recovery_blocks_nonterminal_used_tools(self):
        await self._task('task2',used='["send_email"]')
        self.assertTrue(await w.existing_task_requires_manual_review('task2'))

    async def test_recovery_blocks_approval_event(self):
        await self._task('task3',event='approval_required')
        self.assertTrue(await w.existing_task_requires_manual_review('task3'))

    async def test_recovery_allows_tool_free_nonterminal(self):
        await self._task('task4',event='thinking')
        self.assertFalse(await w.existing_task_requires_manual_review('task4'))

    async def test_completed_task_skips_quarantine(self):
        await self._task('task5',used='["read_workspace_file"]',status='completed')
        self.assertFalse(await w.existing_task_requires_manual_review('task5'))

    async def test_corrupted_checkpoint_skipped_from_resume(self):
        await self.create()
        async with self.session_factory() as db:
            row=await db.get(DirectorWorkflowCheckpoint,'wf1')
            row.plan_json='{broken'
            await db.commit()
        self.assertEqual(await w.incomplete_checkpoints(),[])


if __name__ == '__main__': unittest.main()
