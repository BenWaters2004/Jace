"""C4C.3C safety regressions using disposable SQLite; no real tool/provider calls."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jace.agents.models import AgentTask, AgentTaskEvent
from jace.agents import recovery_policy as rp
from jace.agents import service as svc
from jace.db.models import Base, ToolAuditLog


class Adapter:
    def __init__(self, db): self.db=db
    async def __aenter__(self): return self
    async def __aexit__(self, *_): self.db.close()
    async def execute(self, *args): return self.db.execute(*args)
    async def scalar(self, *args): return self.db.scalar(*args)
    async def get(self, *args): return self.db.get(*args)
    async def commit(self): self.db.commit()
    async def rollback(self): self.db.rollback()
    async def refresh(self, obj): self.db.refresh(obj)
    async def flush(self): self.db.flush()
    def add(self, obj): self.db.add(obj)


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='jace_c4c3c_')
        dbpath=Path(self.tmp.name)/'safe_recovery.db'
        self.engine=create_engine(f'sqlite:///{dbpath.as_posix()}')
        Base.metadata.create_all(self.engine)
        factory=sessionmaker(self.engine,expire_on_commit=False)
        self.open=lambda: Adapter(factory())
        self.config_patch=patch.object(svc,'settings',SimpleNamespace(agent_safe_recovery_enabled=True))
        self.config_patch.start()
    async def asyncTearDown(self):
        self.config_patch.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    async def task(self, id, *, status='running', event=None, used='[]', audit=False, metadata='{}'):
        async with self.open() as s:
            s.add(AgentTask(id=id,agent_id='code',title='Unit test',instruction='Unit test',
                status=status,used_tools_json=used,metadata_json=metadata))
            if event: s.add(AgentTaskEvent(task_id=id,event_type=event,message='Recorded before tool execution'))
            if audit: s.add(ToolAuditLog(tool_name='run_device_command',permission_mode='agent:'+id,
                status='approved',arguments_json='{}'))
            await s.commit()

    async def recover(self):
        async with self.open() as s:
            tasks=await svc.recover_incomplete_tasks(s)
            return [x.id for x in tasks]

    async def read(self,id):
        async with self.open() as s: return await s.get(AgentTask,id)

    async def test_tool_started_fences_replay(self):
        await self.task('t1',event='tool_started')
        self.assertEqual(await self.recover(),[])
        t=await self.read('t1')
        self.assertEqual(t.status,'failed')
        self.assertTrue(json.loads(t.metadata_json)['recovery_quarantined'])
        self.assertNotIn('run_device_command',t.error)

    async def test_tool_completed_also_fences(self):
        await self.task('t2',status='thinking',event='tool_completed')
        self.assertEqual(await self.recover(),[])
        self.assertEqual((await self.read('t2')).status,'failed')

    async def test_approval_fences(self):
        await self.task('t3',status='waiting_permission',event='approval_required')
        self.assertEqual(await self.recover(),[])
        t=await self.read('t3')
        self.assertEqual(t.status,'failed')
        self.assertIn('MANUAL REVIEW',t.error)

    async def test_audit_only_fences(self):
        await self.task('t4',event='thinking',audit=True)
        self.assertEqual(await self.recover(),[])
        self.assertEqual((await self.read('t4')).status,'failed')

    async def test_used_tools_fences(self):
        await self.task('t5',used='["read_web_page"]')
        self.assertEqual(await self.recover(),[])

    async def test_corrupt_used_tools_fences(self):
        await self.task('t6',used='{oops')
        self.assertEqual(await self.recover(),[])

    async def test_corrupt_metadata_fences(self):
        await self.task('t7',metadata='[broken')
        self.assertEqual(await self.recover(),[])

    async def test_tool_free_restarts(self):
        await self.task('t8',event='thinking')
        self.assertEqual(await self.recover(),['t8'])
        self.assertEqual((await self.read('t8')).status,'queued')

    async def test_cancel_request_wins(self):
        await self.task('t9',event='tool_started')
        async with self.open() as s:
            t=await s.get(AgentTask,'t9');t.cancel_requested=True;await s.commit()
        self.assertEqual(await self.recover(),[])
        self.assertEqual((await self.read('t9')).status,'cancelled')

    async def test_queued_task_with_old_tool_is_fenced(self):
        await self.task('t10',status='queued',event='tool_started')
        self.assertEqual(await self.recover(),[])
        self.assertEqual((await self.read('t10')).status,'failed')

    async def test_previously_completed_not_recovered(self):
        await self.task('t11',status='completed',event='tool_started')
        self.assertEqual(await self.recover(),[])
        self.assertEqual((await self.read('t11')).status,'completed')

    async def test_worker_exit_after_tool_fences(self):
        await self.task('t12',event='tool_started')
        async with self.open() as s:
            t=await s.get(AgentTask,'t12')
            out=await svc.recover_task_after_worker_crash(s,t,worker_id='worker-1',error='exception')
            self.assertEqual(out.status,'failed')
            self.assertEqual(json.loads(out.metadata_json)['recovery_quarantine_reason'],'worker_exit')

    async def test_worker_exit_without_tools_requeues(self):
        await self.task('t13',event='thinking')
        async with self.open() as s:
            t=await s.get(AgentTask,'t13')
            out=await svc.recover_task_after_worker_crash(s,t,worker_id='worker-2',error='exception')
            self.assertEqual(out.status,'queued')

    async def test_quarantined_retry_blocked(self):
        await self.task('t14',event='approval_required')
        await self.recover()
        async with self.open() as s:
            t=await s.get(AgentTask,'t14')
            with self.assertRaisesRegex(ValueError,'cannot be retried'):
                await svc.prepare_retry(s,t)

    async def test_no_outbound_calls_when_disabled(self):
        await self.task('t15',event='tool_started')
        with patch.object(svc,'settings',SimpleNamespace(agent_safe_recovery_enabled=False)):
            self.assertEqual(await self.recover(),['t15'])
        self.assertEqual((await self.read('t15')).status,'queued')

    async def test_quarantine_event_has_no_arguments(self):
        await self.task('t16',event='tool_started')
        await self.recover()
        async with self.open() as s:
            rows=(await s.execute(select(AgentTaskEvent).where(AgentTaskEvent.task_id=='t16',AgentTaskEvent.event_type=='recovery_quarantined'))).scalars().all()
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads(rows[0].data_json),{'reason':'core_restart'})


if __name__ == '__main__': unittest.main()
