import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest

from starlette.requests import ClientDisconnect
from backend.app.chat_stream import ChatStreamResponse
from backend.app.conversations import ConversationRepository, LocalAssistantChat, ConversationBusy
from backend.app.llm import GemmaCancelled
from backend.app.projects import ProjectService
from backend.app.storage import open_database


class ChatStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = open_database(Path(self.temp.name) / 'state.sqlite3')
        self.addCleanup(self.db.close)
        self.repo = ConversationRepository(self.db)
        self.conversation = self.repo.create(kind='assistant')
        self.chat = LocalAssistantChat(self.repo, ProjectService(self.db), None)
        self.threads = []

    def response(self, generate, continuation=False):
        identifier = self.conversation['id']
        cancel = self.repo.begin_turn(identifier)
        prepared = self.chat.prepare_continuation(identifier) if continuation else self.chat.prepare(identifier, 'Question')
        def cancel_worker():
            cancel.set()
        return ChatStreamResponse(generate=generate,
            commit=lambda result:self.chat.commit(prepared, result),
            cancel=cancel_worker, release=lambda:self.repo.end_turn(identifier, cancel), cancel_event=cancel)

    async def collect(self, response):
        async def read():
            return [json.loads(item.removeprefix('data: ').strip()) async for item in response.body_iterator]
        return await asyncio.wait_for(read(), 2)

    async def test_success_truncation_metadata_and_continuation_are_persistent(self):
        def generate(delta):
            delta('First')
            return {'answer':'First', 'finish_reason':'length', 'omitted_messages':4}
        events = await self.collect(self.response(generate))
        self.assertEqual(events[0], {'type':'delta','text':'First'})
        self.assertEqual(events[-1]['finish_reason'], 'length')
        self.assertEqual(events[-1]['omitted_messages'], 4)
        first = self.repo.get_messages(self.conversation['id'])
        self.assertEqual(first[-1]['finish_reason'], 'length')
        events = await self.collect(self.response(lambda delta:{'answer':'Next','finish_reason':'stop'}, continuation=True))
        self.assertEqual(len(events[-1]['messages']), 2)
        self.assertEqual(events[-1]['messages'][-1]['content'], 'First\n\nNext')
        self.assertEqual(events[-1]['messages'][-1]['finish_reason'], 'stop')
        with self.assertRaises(ValueError):
            self.chat.prepare_continuation(self.conversation['id'])

    async def test_failure_does_not_write_exchange_and_releases_ownership(self):
        def fail(delta):
            delta('Partial')
            raise RuntimeError('fixture failure')
        events = await self.collect(self.response(fail))
        self.assertEqual(events[-1]['type'], 'error')
        self.assertEqual(self.repo.get_messages(self.conversation['id']), [])
        cancel = self.repo.begin_turn(self.conversation['id'])
        self.repo.end_turn(self.conversation['id'], cancel)

    async def test_cancel_before_worker_start_is_not_lost(self):
        response = self.response(lambda delta:self.fail('Cancelled generation was launched'))
        self.repo.cancel_turn('gemma-4-12b')
        events = await self.collect(response)
        self.assertEqual(events[-1]['code'], 'cancelled')
        self.assertEqual(self.repo.get_messages(self.conversation['id']), [])

    async def test_disconnected_response_that_never_started_releases_ownership(self):
        response = self.response(lambda delta:self.fail('Unobserved request launched inference'))
        response.close()
        cancel = self.repo.begin_turn(self.conversation['id'])
        self.repo.end_turn(self.conversation['id'], cancel)
        self.assertEqual(await self.collect(response), [])

    async def test_repeated_disconnect_keeps_reservation_until_worker_stops(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def generate(delta):
            entered.set()
            try:
                release.wait(2)
                return {'answer':'Must not save'}
            finally:
                finished.set()
        response = self.response(generate)
        consumer = asyncio.create_task(anext(response.body_iterator))
        try:
            for _ in range(100):
                if entered.is_set():break
                await asyncio.sleep(.005)
            self.assertTrue(entered.is_set())
            consumer.cancel()
            with self.assertRaises(asyncio.CancelledError): await consumer
            response.close(); response.close()
            with self.assertRaises(ConversationBusy):
                self.repo.delete(self.conversation['id'])
            with self.assertRaises(ConversationBusy):
                self.repo.begin_turn(self.conversation['id'])
        finally:
            release.set()
        for _ in range(100):
            if finished.is_set() and self.repo._active_turn is None:break
            await asyncio.sleep(.005)
        self.assertTrue(finished.is_set())
        self.assertEqual(self.repo.get_messages(self.conversation['id']), [])
        cancel = self.repo.begin_turn(self.conversation['id'])
        self.repo.end_turn(self.conversation['id'], cancel)

    async def test_asgi_send_failure_before_first_event_also_releases_ownership(self):
        response = self.response(lambda delta:self.fail('Not started'))
        async def send(message):raise OSError('Client disconnected')
        async def receive():return {'type':'http.disconnect'}
        with self.assertRaises(ClientDisconnect):
            await response({'type':'http','asgi':{'spec_version':'2.4'}},receive,send)
        cancel = self.repo.begin_turn(self.conversation['id'])
        self.repo.end_turn(self.conversation['id'], cancel)
