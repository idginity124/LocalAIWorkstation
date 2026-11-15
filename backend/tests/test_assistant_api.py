import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException


class Request:
    def __init__(self, payload):self.payload = payload
    async def json(self):return self.payload


class AssistantApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        name = 'backend.app._assistant_api_test'
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'app/main.py')
        cls.api = importlib.util.module_from_spec(spec)
        sys.modules[name] = cls.api
        with patch.dict(os.environ, {'AI_WORKSTATION_DATA':cls.temp.name}):
            spec.loader.exec_module(cls.api)

    @classmethod
    def tearDownClass(cls):
        cls.api.AUDIO_JOBS.close()
        cls.api.IMAGE_JOBS.close()
        cls.api.DATABASE.close();cls.api.DATA_LOCK.close()
        sys.modules.pop(cls.api.__name__,None)
        cls.temp.cleanup()

    async def create(self):
        return await self.api.create_conversation(Request({'kind':'assistant','title':'New chat','auto_title':True}))

    async def test_active_delete_and_second_send_return_conflict_without_losing_first_owner(self):
        chat = await self.create()
        response = await self.api.send_conversation_message(chat['id'],Request({'content':'Question'}))
        try:
            with self.assertRaises(HTTPException) as error:await self.api.delete_conversation(chat['id'])
            self.assertEqual(error.exception.status_code,409)
            with self.assertRaises(HTTPException) as error:await self.api.send_conversation_message(chat['id'],Request({'content':'Another'}))
            self.assertEqual(error.exception.status_code,409)
            with self.assertRaises(HTTPException):await self.api.delete_conversation(chat['id'])
        finally:response.close()
        self.assertEqual(await self.api.delete_conversation(chat['id']),{'deleted':True})

    async def test_invalid_preparation_releases_owner_and_does_not_make_next_chat_busy(self):
        chat = await self.create()
        for payload in ({'content':' '},{'continue':True},{'content':'Question','context_path':'secret'}, {'continue':True,'content':'Question'}):
            with self.subTest(payload=payload), self.assertRaises(HTTPException) as error:
                await self.api.send_conversation_message(chat['id'],Request(payload))
            self.assertEqual(error.exception.status_code,422)
        response = await self.api.send_conversation_message(chat['id'],Request({'content':'Valid'}))
        response.close()
        await self.api.delete_conversation(chat['id'])

    async def test_actual_route_commits_truncation_then_appends_continuation(self):
        chat = await self.create()
        with patch.object(self.api.LLMS,'chat_stream',return_value={'answer':'Part one','finish_reason':'length','omitted_messages':2}) as generate:
            response = await self.api.send_conversation_message(chat['id'],Request({'content':'Question'}))
            events = [json.loads(item[6:]) async for item in response.body_iterator]
            self.assertEqual(events[-1]['finish_reason'],'length')
            self.assertEqual(events[-1]['omitted_messages'],2)
            self.assertFalse(generate.call_args.kwargs['continuation'])
            self.assertEqual(events[-1]['conversation']['title'],'Question')
        with patch.object(self.api.LLMS,'chat_stream',return_value={'answer':'Part two','finish_reason':'stop'}) as generate:
            response = await self.api.send_conversation_message(chat['id'],Request({'continue':True}))
            events = [json.loads(item[6:]) async for item in response.body_iterator]
            self.assertTrue(generate.call_args.kwargs['continuation'])
            self.assertEqual(len(events[-1]['messages']),2)
            self.assertEqual(events[-1]['messages'][-1]['content'],'Part one\n\nPart two')
        await self.api.delete_conversation(chat['id'])

    async def test_cancel_route_handles_requests_before_model_worker_registers(self):
        chat = await self.create()
        response = await self.api.send_conversation_message(chat['id'],Request({'content':'Question'}))
        self.assertTrue(self.api.cancel_llm_response('gemma-4-12b')['cancelled_active_request'])
        with patch.object(self.api.LLMS,'chat_stream') as generate:
            events = [json.loads(item[6:]) async for item in response.body_iterator]
            self.assertEqual(events[-1]['code'],'cancelled')
            generate.assert_not_called()
        self.assertEqual(self.api.CONVERSATIONS.get_messages(chat['id']),[])
        await self.api.delete_conversation(chat['id'])
