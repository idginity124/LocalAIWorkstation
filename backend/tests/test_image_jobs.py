import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from backend.app.comfy import ComfyManager, ImageCancelled
from backend.app.image_jobs import ImageJobs, ImageRequest
from backend.app.storage import open_database
from backend.app.jobs import JobRepository


class FakeComfy:
    def __init__(self):
        self.release = threading.Event()
        self.calls = 0
    _decode_image = staticmethod(ComfyManager._decode_image)
    def status(self):
        return {"generation_available": True, "edit": {"available": True}}
    def execute(self, mode, payload, cancel, *, job_id=None):
        self.calls += 1
        while not self.release.wait(.01):
            if cancel.is_set():
                raise ImageCancelled("İptal edildi")
        return {"filename": "test.png", "url": "/api/v1/image/output/test.png"}


class ImageJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "jobs.sqlite3"
        self.comfy = FakeComfy()
        self.jobs = ImageJobs(self.path, self.comfy)
    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()
    def request(self, key="test"):
        return ImageRequest(prompt="A red apple", idempotency_key=key)
    def finish(self, job):
        for _ in range(200):
            current = self.jobs.get(job["id"])
            if current["status"] in {"COMPLETED", "FAILED", "INTERRUPTED"}:
                return current
            time.sleep(.01)
        self.fail("Job did not finish")
    def test_same_request_is_not_submitted_twice_and_result_survives_restart(self):
        job = self.jobs.submit(self.request())
        self.assertEqual(job["id"], self.jobs.submit(self.request())["id"])
        with self.assertRaises(RuntimeError):
            self.jobs.submit(self.request("second"))
        self.comfy.release.set()
        self.assertEqual(self.finish(job)["status"], "COMPLETED")
        self.jobs.close()
        self.jobs = ImageJobs(self.path, self.comfy)
        self.assertEqual(self.jobs.list()[0]["result"]["filename"], "test.png")
        self.assertEqual(self.comfy.calls, 1)
    def test_cancellation_is_persistent_and_does_not_repeat_work(self):
        job = self.jobs.submit(self.request())
        self.jobs.cancel(job["id"])
        self.assertEqual(self.finish(job)["status"], "INTERRUPTED")
        self.assertEqual(self.jobs.submit(self.request())["status"], "INTERRUPTED")
    def test_restart_marks_orphaned_jobs_without_resubmitting(self):
        db = open_database(self.path)
        job, _ = JobRepository(db).enqueue("image", {"prompt": "test"}, "orphan")
        db.close()
        self.jobs.close()
        self.jobs = ImageJobs(self.path, self.comfy)
        self.assertEqual(self.jobs.get(job.id)["status"], "RECOVERY_REQUIRED")
        self.assertEqual(self.comfy.calls, 0)
    def test_invalid_input_and_idempotency_collision_are_rejected(self):
        with self.assertRaises(ValueError):
            ImageRequest(prompt=" ", idempotency_key="bad")
        with self.assertRaises(ValueError):
            ImageRequest(prompt="test", width=513, idempotency_key="bad")
        with self.assertRaises(ValueError):
            ImageRequest(prompt="test", cfg=float("nan"), idempotency_key="bad")
        with self.assertRaises(ValueError):
            self.jobs.submit(ImageRequest(prompt="test", mode="edit", idempotency_key="bad"))
        self.jobs.submit(self.request())
        with self.assertRaises(ValueError):
            self.jobs.submit(ImageRequest(prompt="different", idempotency_key="test"))
    def test_unmanaged_service_cannot_execute_or_receive_interrupt(self):
        manager = ComfyManager(Path(self.temp.name), Path(self.temp.name) / "output")
        manager.is_running = Mock(return_value=True)
        manager._post = Mock()
        with self.assertRaises(RuntimeError):
            manager.execute("generate", {"prompt": "test"}, threading.Event())
        manager._abort_workflow("foreign")
        manager._post.assert_not_called()

class ImageRegressionTests(unittest.TestCase):
    def setUp(self):
        from contextlib import closing
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.sqlite3'
        self.manager=FakeComfy()
        self.jobs=ImageJobs(self.path,self.manager)
        self.addCleanup(self.jobs.close)

    def test_cancel_cannot_be_overwritten_by_a_late_success(self):
        entered,release=threading.Event(),threading.Event()
        def execute(mode,payload,cancel,*,job_id=None):
            entered.set();release.wait(2)
            return {'filename':'late.png'}
        self.manager.execute=execute
        job=self.jobs.submit(ImageRequest(prompt='Question',idempotency_key='race'))
        try:
            self.assertTrue(entered.wait(1))
            self.jobs.cancel(job['id'])
        finally:release.set()
        for _ in range(100):
            if not self.jobs.active:break
            time.sleep(.005)
        self.assertEqual(self.jobs.get(job['id'])['status'],'INTERRUPTED')

    def test_uncertain_service_is_persisted_as_recovery_required(self):
        from backend.app.comfy import ImageRecoveryRequired
        self.manager.execute=Mock(side_effect=ImageRecoveryRequired('Cannot verify stop'))
        job=self.jobs.submit(ImageRequest(prompt='Question',idempotency_key='recovery'))
        for _ in range(100):
            if not self.jobs.active:break
            time.sleep(.005)
        self.assertEqual(self.jobs.get(job['id'])['status'],'RECOVERY_REQUIRED')

    def test_cursor_pagination_and_search_reach_jobs_older_than_fifty(self):
        from contextlib import closing
        with closing(open_database(self.path)) as db:
            for index in range(73):
                JobRepository(db).enqueue('image',{'mode':'generate','prompt':f'ЗАПРОС {index}'},f'page-{index}')
        first=self.jobs.page(limit=50)
        self.assertEqual(len(first['jobs']),50)
        with closing(open_database(self.path)) as db:JobRepository(db).enqueue('image',{'prompt':'New insert'},'new')
        second=self.jobs.page(limit=50,before=first['next_cursor'])
        self.assertEqual(len(second['jobs']),23)
        self.assertIsNone(second['next_cursor'])
        self.assertFalse({j['id'] for j in first['jobs']} & {j['id'] for j in second['jobs']})
        found=self.jobs.page(search='запрос 0')
        self.assertEqual(len(found['jobs']),1)
        self.assertEqual(found['jobs'][0]['prompt'],'ЗАПРОС 0')

class InpaintJobRoutingTests(unittest.TestCase):
    setUp = ImageJobTests.setUp
    tearDown = ImageJobTests.tearDown
    finish = ImageJobTests.finish
    def masked_request(self, engine='lama', key='inpaint'):
        import base64, io
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(32,32),'white').save(out,format='PNG')
        raw=base64.b64encode(out.getvalue()).decode()
        return ImageRequest(mode='edit',prompt='remove',init_image=raw,edit_mask=raw,engine=engine,idempotency_key=key)

    def test_selected_engine_reaches_execution_and_changes_identity(self):
        from unittest.mock import Mock
        self.comfy.inpaint_status=Mock(return_value={'lama':{'available':True}})
        self.comfy.execute=Mock(wraps=self.comfy.execute)
        job=self.jobs.submit(self.masked_request())
        self.assertEqual(job['id'],self.jobs.submit(self.masked_request())['id'])
        with self.assertRaises(ValueError):self.jobs.submit(self.masked_request('sdxl'))
        self.comfy.release.set();self.assertEqual(self.finish(job)['status'],'COMPLETED')
        self.assertEqual(self.comfy.execute.call_args.args[1]['engine'],'lama')

    def test_generation_and_unmasked_requests_cannot_use_inpaint_engine(self):
        for request in (ImageRequest(prompt='remove',engine='lama',idempotency_key='bad'),
                        ImageRequest(mode='edit',prompt='remove',init_image='bad',engine='sdxl',idempotency_key='bad')):
            with self.assertRaises(ValueError):self.jobs.submit(request)
        self.assertEqual(self.comfy.calls,0)

    def test_missing_engine_assets_do_not_start_a_job(self):
        from unittest.mock import Mock
        self.comfy.inpaint_status=Mock(return_value={'lama':{'available':False}})
        with self.assertRaises(RuntimeError):self.jobs.submit(self.masked_request())
        self.assertEqual(self.comfy.calls,0)
