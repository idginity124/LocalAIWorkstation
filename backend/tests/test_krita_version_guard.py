"""The stale-result precondition runs before any Qt/native document calls."""
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch


class KritaVersionGuardTests(unittest.TestCase):
    def test_stale_ai_result_is_rejected_before_native_mutation(self):
        krita=ModuleType('krita')
        class Extension:
            def __init__(self,parent):pass
        singleton=Mock()
        krita.Extension=Extension
        krita.Krita=SimpleNamespace(instance=lambda:singleton)
        krita.InfoObject=Mock();krita.Selection=Mock()
        krita.QtCore=SimpleNamespace(QT_VERSION_STR='6')
        source=Path(__file__).parents[2]/'experiments/krita-bridge/plugin/ai_workstation_bridge/__init__.py'
        spec=importlib.util.spec_from_file_location('_krita_guard_test',source)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'krita':krita,'PyQt6':ModuleType('PyQt6'),'PyQt6.QtGui':ModuleType('PyQt6.QtGui')}):
            spec.loader.exec_module(module)
        bridge=module.Bridge(singleton);bridge.worker_id='worker';bridge.revision=2
        bridge.mutate=Mock();bridge.snapshot=Mock()
        with self.assertRaisesRegex(ValueError,'Belge AI çalışırken değişti'):
            bridge.execute({'op':'apply_result','expected':'worker:1'})
        bridge.mutate.assert_not_called();bridge.snapshot.assert_not_called()
        with self.assertRaisesRegex(ValueError,'Belge AI çalışırken değişti'):
            bridge.execute({'op':'apply_result','expected':'worker:1','text':'25','rect':[1,1,20,20],'size':12})
        bridge.mutate.assert_not_called();bridge.snapshot.assert_not_called()
