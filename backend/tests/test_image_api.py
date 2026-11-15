import base64
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from fastapi import HTTPException

from backend.app.image_jobs import ImageInputRequest
from backend.tests.test_comfy import image_bytes


class ImageApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        name='backend.app._image_api_test'
        spec=importlib.util.spec_from_file_location(name,Path(__file__).parents[1]/'app/main.py')
        cls.api=importlib.util.module_from_spec(spec);sys.modules[name]=cls.api
        with patch.dict(os.environ,{'AI_WORKSTATION_DATA':cls.temp.name}):spec.loader.exec_module(cls.api)

    @classmethod
    def tearDownClass(cls):
        cls.api.AUDIO_JOBS.close();cls.api.IMAGE_JOBS.close();cls.api.DATABASE.close();cls.api.DATA_LOCK.close()
        sys.modules.pop(cls.api.__name__,None);cls.temp.cleanup()

    def test_reference_validation_accepts_webp_and_rejects_a_signature_only(self):
        result=self.api.validate_image_input(ImageInputRequest(init_image=base64.b64encode(image_bytes((80,120),'WEBP')).decode()))
        self.assertEqual((result['width'],result['height']),(80,120))
        self.assertEqual(result['extension'],'.webp')
        with self.assertRaises(HTTPException) as error:
            self.api.validate_image_input(ImageInputRequest(init_image=base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()))
        self.assertEqual(error.exception.status_code,422)

    def test_image_history_endpoint_exposes_pagination_and_input_errors(self):
        page=self.api.image_jobs(limit=10,before=None,search='')
        self.assertEqual(page,{'jobs':[],'next_cursor':None})

    def test_output_route_obeys_configured_directory_and_rejects_symlinks(self):
        directory=Path(self.temp.name)/'custom-output';directory.mkdir()
        (directory/'valid.png').write_bytes(image_bytes())
        (directory/'link.png').symlink_to(directory/'valid.png')
        with patch.object(self.api.COMFY_MANAGER,'output_dir',directory):
            response=self.api.z_image_output_file('valid.png')
            self.assertEqual(response.path,directory/'valid.png')
            for name in ('../escape.png','link.png','missing.png'):
                with self.assertRaises(HTTPException):self.api.z_image_output_file(name)
