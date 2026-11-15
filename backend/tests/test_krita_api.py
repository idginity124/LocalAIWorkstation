from pathlib import Path
import base64
import asyncio
import json
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from app.krita_api import create_krita_router
from app.security import LocalApiSecurity


class KritaApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = Mock(root=Path(self.temp.name))
        self.bridge.execute.return_value = {'layers': [], 'width': 0, 'height': 0}
        app = FastAPI()
        app.include_router(create_krita_router(self.bridge))
        app.add_middleware(LocalApiSecurity, csrf_token='test-token')
        class Client:
            def request(self, method, path, json_data=None, headers=None):
                raw=json.dumps(json_data).encode() if json_data is not None else b''
                scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1',
                       'method':method,'path':path,'raw_path':path.encode(),'query_string':b'',
                       'root_path':'','scheme':'http','server':('127.0.0.1',8000),
                       'client':('127.0.0.1',50000),
                       'headers':[(b'host',b'127.0.0.1:8000'),(b'content-type',b'application/json'),
                                  *[(k.lower().encode(),v.encode()) for k,v in (headers or {}).items()]]}
                messages=[]
                async def receive():return {'type':'http.request','body':raw,'more_body':False}
                async def send(message):messages.append(message)
                async def invoke():
                    # Periodic wakeups also bound requests if a worker fails to return.
                    async def heartbeat():
                        while True: await asyncio.sleep(.02)
                    ticker=asyncio.create_task(heartbeat())
                    try:
                        async with asyncio.timeout(5):
                            await app(scope,receive,send)
                    finally:
                        ticker.cancel()
                        try: await ticker
                        except asyncio.CancelledError: pass
                asyncio.run(invoke())
                response=messages[0]
                content=b''.join(m.get('body',b'') for m in messages[1:])
                return SimpleNamespace(status_code=response['status'],content=content,
                    text=content.decode(errors='replace'),headers={k.decode():v.decode() for k,v in response['headers']})
            def post(self,path,json=None,headers=None):return self.request('POST',path,json,headers)
            def get(self,path):return self.request('GET',path)
            def close(self):pass
        self.client = Client()
        self.headers = {'X-CSRF-Token': 'test-token'}

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_commands_require_csrf_and_trusted_origin(self):
        self.assertEqual(self.client.post('/api/v1/krita/command', json={'op':'state'}).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/krita/command', json={'op':'state'},
                         headers={**self.headers, 'Origin':'https://example.org'}).status_code, 403)
        self.bridge.execute.assert_not_called()

    def test_invalid_payloads_do_not_reach_worker(self):
        for payload in [[], {'op':'open','image':'not-base64'}, {'op':'state','path':'/etc/passwd'},
                        {'op':'open','image':42}]:
            response = self.client.post('/api/v1/krita/command', json=payload, headers=self.headers)
            self.assertEqual(response.status_code, 422, response.text)
        self.bridge.execute.assert_not_called()

    def test_image_payload_and_native_errors(self):
        response = self.client.post('/api/v1/krita/command', json={'op':'open','image':
                    'data:image/png;base64,'+base64.b64encode(b'image').decode()}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.bridge.execute.assert_called_once_with({'op':'open'}, b'image')
        self.bridge.execute.side_effect = RuntimeError('Krita açılamadı')
        self.assertEqual(self.client.post('/api/v1/krita/command', json={'op':'state'},
                         headers=self.headers).status_code, 503)

    def test_downloads_fixed_to_worker_outputs(self):
        self.assertEqual(self.client.get('/api/v1/krita/project').status_code, 404)
        path=self.bridge.root/'project.kra'
        path.write_bytes(b'project')
        response=self.client.get('/api/v1/krita/project')
        self.assertEqual(response.content,b'project')
        self.assertEqual(response.headers['cache-control'],'no-store')
        path.unlink();path.symlink_to(self.bridge.root/'outside')
        (self.bridge.root/'outside').write_bytes(b'private')
        self.assertEqual(self.client.get('/api/v1/krita/project').status_code,404)
