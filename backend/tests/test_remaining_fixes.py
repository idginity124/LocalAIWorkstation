from contextlib import closing
import hashlib
import io
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from backend.app.filesystem import atomic_write, FileConflict, is_sensitive_path
from backend.app.projects import ProjectService
from backend.app.settings import SettingsService, DEFAULTS
from backend.app.storage import open_database
from backend.app.resources import GpuResourceManager
from backend.app.llm import LocalLlmManager, GemmaUnavailable
from backend.app.audio_jobs import AudioJobs, AudioRequest
from backend.app.documents import build_xlsx
from backend.tests.test_audio_jobs import FakeRunner


class RemainingFixTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.root=self.base/'project';self.root.mkdir()
        self.db=open_database(self.base/'state.sqlite3');self.addCleanup(self.db.close)
        self.projects=ProjectService(self.db);self.project=self.projects.register(str(self.root))

    def test_sensitive_credentials_are_blocked_for_read_and_write(self):
        for name in ('.codex/auth.json','config/credentials.json','config/secrets.yaml','.env.staging','.ssh/config'):
            with self.subTest(name=name):
                self.assertTrue(is_sensitive_path(Path(name)))
                with self.assertRaises(PermissionError):atomic_write(self.root,name,b'not a secret',approved=True)
                with self.assertRaises(PermissionError):self.projects.read_file(self.project['id'],name)

    def test_executable_permissions_survive_replacement(self):
        path=self.root/'run.sh';path.write_text('old');path.chmod(0o755)
        proposal=self.projects.propose(self.project['id'],'run.sh','new')
        self.projects.apply(proposal['id'],approved=True,overwrite_approved=True)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o755)

    def test_external_edit_at_the_commit_point_is_restored_and_proposal_is_stale(self):
        from backend.app import filesystem
        path=self.root/'main.py';path.write_text('old')
        proposal=self.projects.propose(self.project['id'],'main.py','proposal')
        exchange=filesystem._exchange
        calls=0
        def concurrent(fd,first,second):
            nonlocal calls
            calls+=1
            if calls==1:path.write_text('external edit')
            return exchange(fd,first,second)
        with patch.object(filesystem,'_exchange',side_effect=concurrent):
            with self.assertRaises(FileConflict):self.projects.apply(proposal['id'],approved=True,overwrite_approved=True)
        self.assertEqual(path.read_text(),'external edit')
        self.assertEqual(self.db.execute('SELECT status FROM edit_proposals WHERE id=?',(proposal['id'],)).fetchone()[0],'STALE')
        self.assertEqual(len(list(self.root.glob('.ai-workstation-conflict-*'))),1)

    def test_new_file_is_not_overwritten_if_it_appears_during_commit(self):
        original_link=os.link
        def appeared(*args,**kwargs):
            (self.root/'new.txt').write_text('external')
            return original_link(*args,**kwargs)
        with patch('backend.app.filesystem.os.link',side_effect=appeared):
            with self.assertRaises(FileConflict):atomic_write(self.root,'new.txt',b'proposal',approved=True)
        self.assertEqual((self.root/'new.txt').read_text(),'external')

    def test_invalid_settings_and_corrupt_rows_do_not_crash_api_services(self):
        settings=SettingsService(self.db)
        for key,value in [('theme',[]),('theme',{}),('telemetry_refresh_seconds',[]),('telemetry_refresh_seconds',5.0)]:
            with self.subTest(value=value),self.assertRaises(ValueError):settings.update(key,value)
        self.db.execute("INSERT INTO settings(key,value_json) VALUES('theme','{')")
        self.db.execute("INSERT INTO settings(key,value_json) VALUES('telemetry_refresh_seconds','0')")
        self.assertEqual(settings.get_all(),DEFAULTS)
        self.assertEqual(settings.update('theme','light')['theme'],'light')

    def test_target_preflight_failure_preserves_the_loaded_model(self):
        manager=LocalLlmManager(Mock(),self.base)
        target=manager.server('qwen3.5-9b-q8_0')
        current=Mock();current.status.return_value={'managed':True,'active_request':False}
        manager._servers={'gemma-4-12b':current,'qwen3.5-9b-q8_0':target}
        with self.assertRaises(GemmaUnavailable):manager.start('qwen3.5-9b-q8_0')
        current.stop.assert_not_called()

    def test_load_failure_attempts_to_restore_previous_model(self):
        manager=LocalLlmManager(Mock(),self.base)
        current=Mock();current.status.return_value={'managed':True,'active_request':False}
        target=Mock();target.start.side_effect=GemmaUnavailable('load failed')
        manager._servers={'gemma-4-12b':current,'qwen3.5-9b-q8_0':target}
        with self.assertRaises(GemmaUnavailable):manager.start('qwen3.5-9b-q8_0')
        current.stop.assert_called_once();current.start.assert_called_once()

    def test_recovery_state_and_reason_survive_another_acquire(self):
        import asyncio
        from backend.tests.test_resources import FixedObservation, observation
        manager=GpuResourceManager(FixedObservation(observation(0)))
        asyncio.run(manager.acquire('owner',100))
        manager.require_recovery('verify cleanup first')
        with self.assertRaisesRegex(RuntimeError,'verify cleanup first'):asyncio.run(manager.acquire('new',100))
        self.assertEqual(manager.state,'RECOVERY_REQUIRED')

    def test_plain_formula_like_text_remains_text_but_explicit_formulas_work(self):
        from openpyxl import load_workbook
        artifact=build_xlsx({'sheets':[{'name':'S','cells':{'A1':'=SIN(1)','A2':{'formula':'=SUM(1,2)'}}}]})
        workbook=load_workbook(io.BytesIO(artifact.content),data_only=False)
        try:
            self.assertEqual(workbook['S']['A1'].data_type,'s')
            self.assertEqual(workbook['S']['A1'].value,'=SIN(1)')
            self.assertEqual(workbook['S']['A2'].data_type,'f')
        finally:workbook.close()


class AudioLifecycleFixTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.runner=FakeRunner(self.base/'audio')
        self.jobs=AudioJobs(self.base/'db.sqlite3',self.runner);self.addCleanup(self.jobs.close)

    def test_cancel_wins_over_a_late_success(self):
        entered,release=threading.Event(),threading.Event()
        def run(*args):entered.set();release.wait(2);return {'filename':'late.wav'}
        self.runner.run=run
        job=self.jobs.submit(AudioRequest(text='test',idempotency_key='late'))
        try:
            self.assertTrue(entered.wait(1));self.jobs.cancel(job['id'])
        finally:release.set()
        for _ in range(100):
            if self.jobs.active_job_id is None:break
            time.sleep(.005)
        self.assertEqual(self.jobs.get(job['id'])['status'],'INTERRUPTED')

    def test_rejected_upload_is_removed_but_claimed_upload_is_not(self):
        identifier=self.jobs.begin_upload()
        path=self.runner.reference_path(identifier);path.write_bytes(b'fixture')
        self.jobs.finish_upload(identifier,completed=True)
        self.runner.ready=False
        with self.assertRaises(RuntimeError):self.jobs.submit(AudioRequest(text='test',mode='clone',reference_id=identifier,idempotency_key='rejected'))
        self.assertFalse(path.exists())
        self.runner.ready=True
        path.write_bytes(b'fixture')
        accepted=self.jobs.submit(AudioRequest(text='test',mode='clone',reference_id=identifier,idempotency_key='accepted'))
        self.jobs.discard_reference(identifier)
        self.assertTrue(path.exists())
        self.jobs.cancel(accepted['id'])

    def test_failed_and_expired_uploads_are_cleaned_and_quota_is_bounded(self):
        identifier=self.jobs.begin_upload();path=self.runner.reference_path(identifier)
        path.with_name(path.name+'.part').write_bytes(b'partial')
        self.jobs.finish_upload(identifier,completed=False)
        self.assertFalse(path.with_name(path.name+'.part').exists())
        path.write_bytes(b'old');os.utime(path,(0,0))
        new=self.jobs.begin_upload();self.assertFalse(path.exists())
        self.jobs.finish_upload(new,completed=False)
        for _ in range(8):self.jobs.begin_upload()
        with self.assertRaises(RuntimeError):self.jobs.begin_upload()

    def test_audio_history_reaches_older_records(self):
        from backend.app.jobs import JobRepository
        with closing(open_database(self.jobs.path)) as db:
            for index in range(60):JobRepository(db).enqueue('audio',{'text':str(index)},f'audio-{index}')
        first=self.jobs.page();second=self.jobs.page(before=first['next_cursor'])
        self.assertEqual(len(first['jobs']),50);self.assertEqual(len(second['jobs']),10)
        self.assertIsNone(second['next_cursor'])
