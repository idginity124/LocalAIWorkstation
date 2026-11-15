import asyncio
import unittest

from backend.app.security import LocalApiSecurity


class LocalApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.called = False

        async def app(scope, receive, send):
            self.called = True
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        self.middleware = LocalApiSecurity(app, csrf_token="test-token")

    def request(self, *, client=("127.0.0.1", 50000), host=b"127.0.0.1:8000", origin=None, method="GET", token=None):
        headers = [(b"host", host)]
        if origin is not None:
            headers.append((b"origin", origin))
        if token is not None:
            headers.append((b"x-csrf-token", token))
        scope = {"type": "http", "path": "/api/v1/test", "method": method, "headers": headers, "client": client}
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        asyncio.run(self.middleware(scope, receive, send))
        return messages

    def test_loopback_and_allowlisted_origin_reach_app(self) -> None:
        response = self.request(origin=b"http://127.0.0.1:5173")
        self.assertTrue(self.called)
        self.assertEqual(response[0]["status"], 204)

    def test_remote_client_and_untrusted_origin_are_rejected(self) -> None:
        response = self.request(client=("192.168.1.10", 50000))
        self.assertEqual(response[0]["status"], 403)
        self.assertFalse(self.called)
        response = self.request(origin=b"https://attacker.example")
        self.assertEqual(response[0]["status"], 403)
        self.assertFalse(self.called)

    def test_unsafe_methods_require_csrf_and_valid_host(self) -> None:
        self.assertEqual(self.request(method="POST")[0]["status"], 403)
        self.assertEqual(self.request(method="POST", token=b"wrong")[0]["status"], 403)
        self.assertEqual(self.request(method="POST", token=b"test-token")[0]["status"], 204)
        self.assertEqual(self.request(host=b"attacker.example")[0]["status"], 403)


if __name__ == "__main__":
    unittest.main()
