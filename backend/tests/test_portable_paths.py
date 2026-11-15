"""Exercise engine/catalog defaults in a different user's clean environment."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[2]
PROBE = """
import json
from backend.app.catalog import model_root
from backend.app.comfy import MODEL_ROOT, COMFY_ROOT
from backend.app.llm import DEFAULT_ROOT
print(json.dumps([str(p) for p in (model_root(), MODEL_ROOT, DEFAULT_ROOT, COMFY_ROOT)]))
"""


class PortablePathTests(unittest.TestCase):
    def probe(self, home, **overrides):
        environment = {k: v for k, v in os.environ.items() if not k.startswith('AI_WORKSTATION_')}
        environment.update(HOME=str(home), PYTHONDONTWRITEBYTECODE='1', **overrides)
        result = subprocess.run(
            [sys.executable, '-c', PROBE], cwd=PROJECT, env=environment,
            capture_output=True, text=True, check=True, timeout=15,
        )
        return json.loads(result.stdout)

    def test_catalog_and_engines_use_current_users_home_without_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            self.assertEqual(self.probe(home), [str(home / 'AI/models')] * 3 + [str(home / 'AI/ComfyUI')])
            self.assertFalse((home / 'AI').exists())

    def test_explicit_model_and_comfy_paths_are_shared_and_expand_tilde(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            self.assertEqual(
                self.probe(home, AI_WORKSTATION_MODEL_DIR='~/weights', AI_WORKSTATION_COMFYUI_DIR='~/engines/comfy'),
                [str(home / 'weights')] * 3 + [str(home / 'engines/comfy')],
            )
