import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from app.krita_bridge import KritaBridge


class KritaBoundaryTests(unittest.TestCase):
    def test_invalid_commands_never_launch_krita(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge = KritaBridge(Path(temp))
            commands = [{'op': 'arbitrary'}, {'op': 'layer', 'id': '../outside', 'opacity': 999},
                        {'op': 'layer', 'id': 'id', 'visible': 'false'},
                        {'op': 'open'}]
            with patch.object(bridge, 'start') as start:
                for command in commands:
                    with self.subTest(command=command), self.assertRaises(ValueError):
                        bridge.execute(command)
                start.assert_not_called()

    def test_oversize_and_invalid_images_rejected_before_start(self):
        output = io.BytesIO()
        Image.new('RGB', (2049, 1)).save(output, format='PNG')
        with tempfile.TemporaryDirectory() as temp:
            bridge = KritaBridge(Path(temp))
            with patch.object(bridge, 'start') as start:
                for data in [b'not an image', output.getvalue(), b'x' * (12 * 1024**2 + 1)]:
                    with self.assertRaises(ValueError):
                        bridge.execute({'op': 'open'}, data)
                start.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class KritaInputHandoffTests(unittest.TestCase):
    def test_unique_input_names_and_recovery_file_preserved(self):
        import json
        import threading
        import time
        from types import SimpleNamespace
        output=io.BytesIO();Image.new('RGBA',(32,32),'red').save(output,format='PNG')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bridge=KritaBridge(root)
            bridge.process=SimpleNamespace(poll=lambda:None)
            recovery=root/'input.png-autosave.kra';recovery.write_bytes(b'preserve-user-recovery')
            seen=[];errors=[]
            def worker():
                try:
                    for _ in range(2):
                        request=root/'request.json';deadline=time.monotonic()+4
                        while not request.exists():
                            if time.monotonic()>deadline:raise RuntimeError('No request')
                            time.sleep(.01)
                        data=json.loads(request.read_text());request.unlink()
                        path=root/data['_input_file'];seen.append(path.name)
                        self.assertTrue(path.is_file());self.assertNotEqual(path.name,'input.png')
                        with Image.open(path) as image:self.assertEqual(image.size,(32,32))
                        tmp=root/'response.tmp';tmp.write_text(json.dumps({'ok':True,'result':{'width':32}}));tmp.replace(root/'response.json')
                except Exception as error:errors.append(error)
            thread=threading.Thread(target=worker,daemon=True);thread.start()
            with patch.object(bridge,'start'):
                for _ in range(2):self.assertEqual(bridge.execute({'op':'open'},output.getvalue()),{'width':32})
            thread.join(timeout=5)
            self.assertFalse(errors,errors);self.assertFalse(thread.is_alive())
            self.assertEqual(len(set(seen)),2)
            self.assertEqual(recovery.read_bytes(),b'preserve-user-recovery')
            self.assertFalse(any(root.glob('input-*.png')))
