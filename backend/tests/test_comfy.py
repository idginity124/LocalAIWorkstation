import base64
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from uuid import UUID, uuid4
from PIL import Image

from backend.app.comfy import ComfyManager, ImageCancelled, ImageRecoveryRequired
from backend.app.image_files import inspect_image


def image_bytes(size=(32,24), format='PNG'):
    stream = io.BytesIO()
    Image.new('RGBA' if format != 'JPEG' else 'RGB', size, (10,20,30,40) if format != 'JPEG' else (10,20,30)).save(stream,format=format)
    return stream.getvalue()


class ComfyBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.manager=ComfyManager(self.root/'comfy',self.root/'output')
        self.manager.process=Mock()
        self.manager.process.poll.return_value=None
        self.manager.is_running=Mock(return_value=True)
        self.manager.edit_status=Mock(return_value={'ready':True})
        self.manager._edit_clip=Mock(return_value=Path('clip.safetensors'))

    def output(self,name='image.png',size=(80,120)):
        path=self.manager.output_dir/name
        path.write_bytes(image_bytes(size))
        return [{'filename':name,'subfolder':'LocalAIWorkstation','type':'output'}],1.25

    def test_edit_preserves_input_and_cleans_temporary_copy_with_actual_output_dimensions(self):
        raw=image_bytes((90,60),'WEBP')
        def generate(workflow):
            self.assertEqual(workflow['5']['inputs']['megapixels'], 1.0)
            path=self.manager.comfy_root/'input'/workflow['4']['inputs']['image']
            self.assertEqual(path.read_bytes(),raw)
            return self.output()
        with patch.object(self.manager,'_run_workflow',side_effect=generate):
            result=self.manager.edit('Edit',base64.b64encode(raw).decode())
        self.assertEqual((result['width'],result['height']),(80,120))
        self.assertEqual(result['path'],str((self.manager.output_dir/'image.png').resolve()))
        self.assertEqual(list((self.manager.comfy_root/'input').iterdir()),[])
        self.assertEqual(self.manager.list_gallery()[0]['mode'],'edit')

    def test_input_is_cleaned_after_generation_failure_and_cancellation(self):
        for error in (RuntimeError('fixture failure'),ImageCancelled('cancelled')):
            with self.subTest(error=error),patch.object(self.manager,'_run_workflow',side_effect=error):
                with self.assertRaises(type(error)):
                    self.manager.edit('Edit',base64.b64encode(image_bytes()).decode())
            self.assertEqual(list((self.manager.comfy_root/'input').iterdir()),[])

    def test_img2img_reference_is_also_removed(self):
        with patch.object(self.manager,'_run_workflow',return_value=self.output()):
            result=self.manager.generate('Generate',init_image=base64.b64encode(image_bytes()).decode())
        self.assertEqual(result['mode'],'img2img')
        self.assertEqual(list((self.manager.comfy_root/'input').iterdir()),[])

    def test_missing_corrupt_or_outside_output_cannot_be_marked_successful(self):
        for image in ({'filename':'missing.png'},{'filename':'../../escape.png'},{'filename':'invalid.png'},{'filename':'image.png','subfolder':'other'},{'filename':'link.png'}):
            with self.subTest(image=image):
                (self.manager.output_dir/'invalid.png').write_bytes(b'not an image')
                self.output()
                link=self.manager.output_dir/'link.png'
                if not link.is_symlink():link.symlink_to(self.manager.output_dir/'image.png')
                with patch.object(self.manager,'_run_workflow',return_value=([image],0)):
                    with self.assertRaises(ValueError):self.manager.generate('Generate')

    def test_gallery_survives_bad_metadata_broken_links_and_bad_images(self):
        self.output()
        meta=self.manager.output_dir/'image.png.meta.json'
        (self.manager.output_dir/'broken.png').symlink_to(self.root/'missing')
        (self.manager.output_dir/'bad.png').write_bytes(b'broken')
        for value in ('[]','null','{','{"prompt":23,"width":1024,"height":1024,"seed":"not a number"}', json.dumps({'seed':10**400})):
            with self.subTest(value=value):
                meta.write_text(value)
                gallery=self.manager.list_gallery()
                self.assertEqual(len(gallery),1)
                self.assertEqual((gallery[0]['width'],gallery[0]['height']),(80,120))
                self.assertEqual(gallery[0]['prompt'],'')
                self.assertNotIn('seed',gallery[0])

    def test_symlink_metadata_is_not_read(self):
        self.output()
        outside=self.root/'private.json';outside.write_text('{"prompt":"secret"}')
        (self.manager.output_dir/'image.png.meta.json').symlink_to(outside)
        self.assertEqual(self.manager.list_gallery()[0]['prompt'],'')

    def test_image_signature_alone_and_truncated_image_are_rejected(self):
        for raw in (b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff',image_bytes()[:40],b''):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                self.manager._decode_image(base64.b64encode(raw).decode())
        for format in ('PNG','JPEG','WEBP'):
            raw=image_bytes(format=format)
            self.assertEqual(self.manager._decode_image(base64.b64encode(raw).decode()),raw)

    def test_pixel_limit_is_checked_before_decoding(self):
        image=Mock(size=(10000,10000),format='PNG')
        image.__enter__=Mock(return_value=image);image.__exit__=Mock(return_value=False)
        with patch('backend.app.image_files.Image.open',return_value=image):
            with self.assertRaisesRegex(ValueError,'16 megapiksel'):inspect_image(b'fixture')
        image.verify.assert_not_called();image.load.assert_not_called()

    def test_prompt_id_is_known_before_sending_and_matches_persistent_job_id(self):
        identifier=str(uuid4())
        self.manager._prompt_id=identifier
        def request(path,body=None,**kwargs):
            if path=='/prompt':
                self.assertEqual(body['prompt_id'],identifier)
                self.assertEqual(self.manager._prompt_id,identifier)
                UUID(body['prompt_id'])
                return {'prompt_id':identifier}
            if path=='/history/'+identifier:
                return {identifier:{'status':{'status_str':'success'},'outputs':{'save':{'images':[{'filename':'image.png'}]}}}}
            self.fail('Unexpected request: '+path)
        with patch.object(self.manager,'_request_json',side_effect=request):
            images,_=self.manager._run_workflow({})
        self.assertEqual(images[0]['filename'],'image.png')

    def test_lost_acknowledgement_stops_owned_service_without_resubmitting(self):
        for error in (TimeoutError('ack lost'),ValueError('broken ack')):
            with self.subTest(error=error),patch.object(self.manager,'_request_json',side_effect=error) as request,patch.object(self.manager,'_stop_process') as stop:
                with self.assertRaisesRegex(RuntimeError,'doğrulanamadı'):self.manager._run_workflow({})
                request.assert_called_once();stop.assert_called_once()
                self.assertIsNotNone(self.manager._prompt_id)

    def test_unverified_stop_requires_recovery_and_preserves_reference_until_safe(self):
        with patch.object(self.manager,'_request_json',side_effect=TimeoutError('ack lost')),patch.object(self.manager,'_stop_process',side_effect=RuntimeError('cannot stop')):
            with self.assertRaises(ImageRecoveryRequired):
                self.manager.edit('Edit',base64.b64encode(image_bytes()).decode())
        self.assertTrue(self.manager._recovery_reason)
        self.assertEqual(len(list((self.manager.comfy_root/'input').iterdir())),1)

    def test_cancel_during_history_read_wins_over_success_and_targets_only_that_prompt(self):
        identifier=str(uuid4());self.manager._prompt_id=identifier
        calls=[]
        def request(path,body=None,**kwargs):
            calls.append((path,body))
            if path=='/prompt':return {'prompt_id':identifier}
            if path.startswith('/history/'):
                self.manager._cancel.set()
                return {identifier:{'status':{'status_str':'success'},'outputs':{'save':{'images':[{'filename':'image.png'}]}}}}
            if path=='/queue':return {'queue_running':[],'queue_pending':[]}
            return {}
        with patch.object(self.manager,'_request_json',side_effect=request):
            with self.assertRaises(ImageCancelled):self.manager._run_workflow({})
        self.assertIn(('/interrupt',{'prompt_id':identifier}),calls)
        self.assertNotIn(('/interrupt',{}),calls)

    def test_stale_input_cleanup_only_removes_our_files_on_an_idle_service(self):
        directory=self.manager.comfy_root/'input';directory.mkdir(parents=True)
        stale=directory/'LocalAIWorkstation_edit_123456abcdef.png';stale.write_bytes(image_bytes())
        personal=directory/'my-photo.png';personal.write_bytes(image_bytes())
        with patch.object(self.manager,'_request_json',return_value={'queue_running':[[1,'other']]}):self.manager._cleanup_stale_inputs()
        self.assertTrue(stale.exists())
        with patch.object(self.manager,'_request_json',return_value={'queue_running':[],'queue_pending':[]}):self.manager._cleanup_stale_inputs()
        self.assertFalse(stale.exists());self.assertTrue(personal.exists())
