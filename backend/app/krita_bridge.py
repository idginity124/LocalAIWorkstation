"""Experimental Krita worker in a private config; never controls the user's Krita."""
from __future__ import annotations

import io
import json
import os
import signal
import secrets
from pathlib import Path
import shutil
import subprocess
import threading
import tempfile
import time

from PIL import Image
from .image_files import inspect_image, MAX_IMAGE_BYTES
from .krita_commands import validate


class KritaBridge:
    def __init__(self, root: Path, progress=None):
        self.root = root.resolve()
        self.progress = progress or (lambda message: None)
        self.lock = threading.Lock()
        self.process = None
        self.failed = False
        self.private_runtime = None

    def start(self):
        if self.process and self.process.poll() is None:
            if self.failed:
                raise RuntimeError('Krita işlemi zaman aşımından sonra yeniden başlatılmalı; uygulamayı yeniden açın.')
            return
        executable = shutil.which('krita')
        if not executable:
            raise RuntimeError('Krita kurulu değil.')
        xvfb = shutil.which('xvfb-run')
        if not xvfb or not shutil.which('Xvfb') or not shutil.which('xauth'):
            raise RuntimeError('Sanal ekran için xorg-server-xvfb ve xorg-xauth paketleri gerekli.')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        config = self.root / 'config'
        config.mkdir(exist_ok=True)
        resources = self.root / 'resources'
        target = resources / 'pykrita'
        target.mkdir(parents=True, exist_ok=True)
        plugin = Path(__file__).resolve().parents[2] / 'experiments/krita-bridge/plugin'
        shutil.copytree(plugin, target, dirs_exist_ok=True)
        # Python plugin discovery can use QStandardPaths instead of the resource override.
        shutil.copytree(plugin, self.root / 'data/krita/pykrita', dirs_exist_ok=True)
        (config / 'kritadisplayrc').write_text('[General]\nOpenGLRenderer=none\n')
        (config / 'kritarc').write_text('[python]\nenable_ai_workstation_bridge=true\n[General]\nShowSplashScreen=false\nuseOpenGL=false\n')
        for name in ('ready', 'request.json', 'response.json'):
            (self.root / name).unlink(missing_ok=True)
        env = dict(os.environ, QT_QPA_PLATFORM='xcb', XDG_CONFIG_HOME=str(config),
                   XDG_DATA_HOME=str(self.root / 'data'), AI_KRITA_BRIDGE_ROOT=str(self.root),
                   DBUS_SESSION_BUS_ADDRESS='unix:path=/nonexistent-ai-krita-bus')
        # The private virtual display must not inherit the desktop connection.
        for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'SESSION_MANAGER'):
            env.pop(key, None)
        env['QT_QUICK_BACKEND'] = 'software'
        env['QT_OPENGL'] = 'software'
        env['QT_FORCE_STDERR_LOGGING'] = '1'
        env['QT_LOGGING_RULES'] = 'krita.scripting.debug=true'
        env['PYTHONUNBUFFERED'] = '1'
        # Krita 6 discovers private .desktop files but misses this directory
        # in the embedded Python interpreter's import search path.
        # Short private paths avoid AF_UNIX's 108-byte pathname limit and
        # keep Qt's single-instance socket separate from the normal Krita.
        if self.private_runtime is not None:self.private_runtime.cleanup()
        self.private_runtime=tempfile.TemporaryDirectory(prefix='law-krita-')
        private=Path(self.private_runtime.name)
        for directory in ('tmp','qt-runtime'):(private/directory).mkdir(mode=0o700)
        env['TMPDIR']=str(private/'tmp')
        env['XDG_RUNTIME_DIR']=str(private/'qt-runtime')
        env['PYTHONPATH'] = str(self.root / 'data/krita/pykrita')
        env.pop('PYTHONHOME', None)
        with (self.root / 'worker.log').open('ab') as log:
            self.process = subprocess.Popen([xvfb, '-a', '-s', '-screen 0 1280x800x24 -nolisten tcp',
                                             executable, '--nosplash', '--resource-location', str(resources)],
                                            env=env, stdout=log, stderr=log, start_new_session=True)
        started = time.monotonic()
        deadline = started + 120
        next_progress = started + 10
        while time.monotonic() < deadline:
            if (self.root / 'ready').exists():
                self.failed = False
                return
            if self.process.poll() is not None:
                raise RuntimeError(f'Krita motoru açılamadı (çıkış: {self.process.returncode}); worker.log kaydını kontrol edin.')
            if time.monotonic() >= next_progress:
                self.progress(f"Krita hazırlanıyor… {int(time.monotonic() - started)} saniye")
                next_progress = time.monotonic() + 10
            time.sleep(.1)
        self._terminate_group()
        raise RuntimeError('Krita eklentisi 120 saniye içinde başlamadı.')

    def execute(self, command: dict, image: bytes | None = None) -> dict:
        with self.lock:
            validate(command)
            command=dict(command)
            normalized = None
            if command['op'] in {'open', 'add', 'apply_result'}:
                if not image or len(image) > MAX_IMAGE_BYTES:
                    raise ValueError('Görsel en fazla 12 MiB olmalı.')
                info = inspect_image(image)
                if max(info['width'], info['height']) > 2048:
                    raise ValueError('Bu denemede görsel kenarı en fazla 2048 piksel olabilir.')
                with Image.open(io.BytesIO(image)) as source:
                    output = io.BytesIO()
                    source.convert('RGBA').save(output, format='PNG')
                    normalized = output.getvalue()
            self.start()
            input_path = None
            if normalized is not None:
                # Reusing input.png triggers Krita's duplicate-file/recovery handling.
                # Never remove the user's old recovery file to work around that.
                input_path=self.root/('input-'+secrets.token_hex(12)+'.png')
                input_path.write_bytes(normalized)
                command['_input_file']=input_path.name
            try:
                (self.root / 'response.json').unlink(missing_ok=True)
                tmp = self.root / 'request.tmp'
                tmp.write_text(json.dumps(command))
                tmp.replace(self.root / 'request.json')
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    response = self.root / 'response.json'
                    if response.exists():
                        data = json.loads(response.read_text())
                        if not data['ok']:
                            raise RuntimeError(data['error'])
                        return data['result']
                    if self.process.poll() is not None:
                        self.failed = True
                        raise RuntimeError('Krita motoru kapandı.')
                    time.sleep(.05)
                self.failed = True
                raise RuntimeError('Krita işlemi zaman aşımına uğradı. Uygulamayı yeniden başlatın.')
            finally:
                if input_path is not None and not self.failed:
                    input_path.unlink(missing_ok=True)

    def _terminate_group(self, sig=signal.SIGTERM):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, sig)
            except ProcessLookupError:
                pass

    def close(self):
        with self.lock:
            if self.process:
                self._terminate_group()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._terminate_group(signal.SIGKILL)
                    self.process.wait(timeout=5)

            if self.private_runtime is not None:
                self.private_runtime.cleanup()
                self.private_runtime=None
