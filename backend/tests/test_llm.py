import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend.app.llm import GemmaCancelled, GemmaServer, GemmaUnavailable
from backend.app.resources import GpuObservation, GpuResourceManager, ResourceState


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.returncode = None
        self.args = args
        self.kwargs = kwargs
        self.terminated = False

    def poll(self): return self.returncode
    def terminate(self): self.terminated = True; self.returncode = 0
    def wait(self, timeout=None): return self.returncode


def sse_response(items):
    class Response:
        status = 200
        def __init__(self): self.lines = [f"data: {json.dumps(item, ensure_ascii=False)}\n".encode() if isinstance(item, dict) else f"data: {item}\n".encode() for item in items]
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def readline(self): return self.lines.pop(0) if self.lines else b""
    return Response()


class GemmaAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        model_dir = root / "gemma-4-12b"
        model_dir.mkdir()
        (model_dir / "gemma-4-12B-it-Q4_0.gguf").write_bytes(b"model")
        (model_dir / "mmproj-gemma-4-12B-it-Q8_0.gguf").write_bytes(b"projector")
        self.server = GemmaServer(root, "/usr/bin/llama-server")
        self.server.log_path = root / "test.log"
        counter = patch.object(GemmaServer, '_count_tokens', return_value=100)
        counter.start()
        self.addCleanup(counter.stop)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cancel_response_keeps_managed_model_loaded(self):
        process = FakeProcess()
        self.server.process = process
        event = threading.Event()
        self.server._active_cancel = event
        result = self.server.cancel_response()
        self.assertTrue(event.is_set())
        self.assertTrue(result["model_loaded"])
        self.assertFalse(process.terminated)

    @patch("backend.app.llm.time.sleep")
    @patch.object(GemmaServer, "_healthy", return_value=True)
    @patch.object(GemmaServer, "_port_open", return_value=False)
    @patch.object(GemmaServer, "_available_ram", return_value=16 * 1024**3)
    @patch("backend.app.llm.subprocess.Popen", FakeProcess)
    def test_start_is_explicit_cpu_only_and_loopback(self, *_mocks) -> None:
        result = self.server.start()
        command = self.server.process.args[0]
        self.assertEqual(result["state"], "RUNNING")
        self.assertIn("--device", command)
        self.assertEqual(command[command.index("--device") + 1], "none")
        self.assertEqual(command[command.index("--gpu-layers") + 1], "0")
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--ctx-size") + 1], "2048")
        self.assertEqual(command[command.index("--parallel") + 1], "1")
        self.assertEqual(command[command.index("--reasoning") + 1], "off")
        self.assertEqual(self.server.process.kwargs["stdout"].name, str(self.server.log_path))
        self.assertEqual(self.server.process.kwargs["stderr"], subprocess.STDOUT)
        self.assertEqual(self.server.process.kwargs["env"]["LLAMA_API_KEY"], self.server.api_key)
        self.assertNotIn(self.server.api_key, command)

    @patch("backend.app.llm.time.sleep")
    @patch.object(GemmaServer, "_healthy", return_value=True)
    @patch.object(GemmaServer, "_port_open", return_value=False)
    @patch.object(GemmaServer, "_available_ram", return_value=16 * 1024**3)
    @patch("backend.app.llm.subprocess.Popen", FakeProcess)
    def test_gpu_start_and_stop_use_a_verified_single_lease(self, *_mocks) -> None:
        class Observations:
            def __init__(self): self.items = [
                GpuObservation(1 * 1024**3, 16 * 1024**3, "test sysfs", True),
                GpuObservation(1 * 1024**3, 16 * 1024**3, "test sysfs", True),
            ]
            async def observe(self): return self.items.pop(0)

        manager = GpuResourceManager(Observations())
        server = GemmaServer(self.server.model_root, "/usr/bin/llama-server", manager)
        server.start()
        command = server.process.args[0]
        self.assertEqual(command[command.index("--device") + 1], "Vulkan0")
        self.assertEqual(command[command.index("--gpu-layers") + 1], "999")
        self.assertEqual(manager.state, ResourceState.RUNNING)
        server.stop()
        self.assertEqual(manager.state, ResourceState.IDLE)

    @patch.object(GemmaServer, "_port_open", return_value=False)
    @patch.object(GemmaServer, "_available_ram", return_value=1)
    @patch("backend.app.llm.subprocess.Popen")
    def test_low_memory_blocks_model_load(self, popen, *_mocks) -> None:
        with self.assertRaisesRegex(GemmaUnavailable, "RAM"):
            self.server.start()
        popen.assert_not_called()

    @patch.object(GemmaServer, "_healthy", return_value=True)
    def test_chat_never_targets_unmanaged_local_service(self, _healthy) -> None:
        with self.assertRaisesRegex(GemmaUnavailable, "hazır değil"):
            self.server.chat([{"role": "user", "content": "Merhaba"}])

    @patch.object(GemmaServer, "_open_stream")
    @patch.object(GemmaServer, "_healthy", return_value=True)
    def test_chat_streams_safe_final_answer_only(self, _healthy, urlopen) -> None:
        self.server.process = FakeProcess()
        urlopen.return_value = sse_response([
            {"choices": [{"delta": {"content": "<|channel>thought" + chr(10) + "özel düşünce"}}]},
            {"choices": [{"delta": {"content": "<channel|>final" + chr(10) + "Yerel "}}]},
            {"choices": [{"delta": {"content": "yanıt"}, "finish_reason":"stop"}]},
            {"choices": [], "usage": {"completion_tokens": 3}, "timings": {"predicted_per_second": 2.5}},
            "[DONE]",
        ])
        visible = []
        result = self.server.chat_stream([{"role": "user", "content": "Merhaba"}], visible.append)
        self.assertEqual(result["answer"], "Yerel yanıt")
        self.assertEqual("".join(visible), "Yerel yanıt")
        self.assertEqual(result["timings"]["predicted_per_second"], 2.5)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18080/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {self.server.api_key}")
        body = json.loads(request.data)
        self.assertEqual(body["messages"][0]["content"], "Merhaba")
        self.assertTrue(body["stream"])
        self.assertEqual(body["reasoning_effort"], "none")

    @patch.object(GemmaServer, "_open_stream")
    @patch.object(GemmaServer, "_healthy", return_value=True)
    def test_incomplete_thinking_is_rejected_without_exposure(self, _healthy, urlopen) -> None:
        self.server.process = FakeProcess()
        urlopen.return_value = sse_response([
            {"choices": [{"delta": {"content": "<|channel>thought" + chr(10) + "private reasoning"}}]},
            "[DONE]",
        ])
        visible = []
        with self.assertRaisesRegex(GemmaUnavailable, "thinking bölümü"):
            self.server.chat_stream([{"role": "user", "content": "Merhaba"}], visible.append)
        self.assertEqual(visible, [])

    @patch.object(GemmaServer, "_open_stream")
    @patch.object(GemmaServer, "_healthy", return_value=True)
    def test_active_stream_can_be_stopped_without_waiting_for_chat_lock(self, _healthy, urlopen) -> None:
        self.server.process = FakeProcess()
        entered = threading.Event()

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def readline(self):
                entered.set()
                while self.server.process is not None and self.server.process.poll() is None:
                    time.sleep(0.005)
                return b""

        response = Response(); response.server = self.server
        urlopen.return_value = response
        errors = []

        def run_chat():
            try: self.server.chat_stream([{"role": "user", "content": "Merhaba"}])
            except Exception as error: errors.append(error)

        worker = threading.Thread(target=run_chat)
        worker.start()
        self.assertTrue(entered.wait(1))
        stopped = self.server.stop()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(stopped["cancelled_active_request"])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], GemmaCancelled)

    @patch("backend.app.llm.LOCAL_OPENER.open")
    def test_health_check_uses_local_random_api_key(self, open_local) -> None:
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_args): return False
        open_local.return_value = Response()
        self.assertTrue(self.server._healthy())
        request = open_local.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18080/health")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {self.server.api_key}")

    @patch.object(GemmaServer, "_healthy", return_value=True)
    def test_chat_rejects_oversized_or_malformed_requests(self, _healthy) -> None:
        self.server.process = FakeProcess()
        with self.assertRaises(ValueError): self.server.chat([{"role": "user", "content": "x" * 32769}])
        with self.assertRaises(ValueError): self.server.chat([{"role": "tool", "content": "x"}])

    @patch("backend.app.llm.time.sleep")
    @patch.object(GemmaServer, "_healthy", return_value=True)
    @patch.object(GemmaServer, "_port_open", return_value=False)
    @patch.object(GemmaServer, "_available_ram", return_value=16 * 1024**3)
    @patch("backend.app.llm.subprocess.Popen", FakeProcess)
    def test_managed_service_stops_gracefully(self, *_mocks) -> None:
        self.server.start()
        process = self.server.process
        self.assertEqual(self.server.stop()["state"], "IDLE")
        self.assertTrue(process.terminated)


if __name__ == "__main__":
    unittest.main()
