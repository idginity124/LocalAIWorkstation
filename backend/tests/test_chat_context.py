import http.client
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from backend.app.llm import CONTEXT_SIZE, MAX_OUTPUT_TOKENS, CONTEXT_MARGIN, GemmaServer, GemmaCancelled, GemmaUnavailable
from backend.tests.test_llm import FakeProcess, sse_response


class ChatContextTests(unittest.TestCase):
    def setUp(self):
        self.server = GemmaServer(Path('/unused'), '/unused/llama-server')
        self.server.process = FakeProcess()
        self.cancel = threading.Event()

    def count(self, messages, event):
        return sum(len(message['content']) + 10 for message in messages)

    def test_long_history_fits_as_complete_recent_pairs_without_changing_original(self):
        messages = [{'role':'system','content':'instructions'}]
        for index in range(60):
            messages.extend([{'role':'user','content':f'question {index} ' * 10},{'role':'assistant','content':f'answer {index} ' * 10}])
        messages.append({'role':'user','content':'Current question'})
        original = [dict(item) for item in messages]
        with patch.object(self.server,'_count_tokens',side_effect=self.count):
            selected, omitted = self.server._fit_context(messages, self.cancel)
        self.assertGreater(omitted, 0)
        self.assertEqual(omitted % 2, 0)
        self.assertEqual(selected[0], messages[0])
        self.assertEqual(selected[-1], messages[-1])
        self.assertEqual(selected[1:-1], messages[-len(selected)+1:-1])
        self.assertLessEqual(self.count(selected,None) + MAX_OUTPUT_TOKENS + CONTEXT_MARGIN, CONTEXT_SIZE)
        self.assertEqual(messages,original)

    def test_more_than_twenty_turns_do_not_hit_an_arbitrary_message_limit(self):
        messages = [{'role':'system','content':'s'}]
        for _ in range(50):messages += [{'role':'user','content':'q'},{'role':'assistant','content':'a'}]
        messages += [{'role':'user','content':'last'}]
        with patch.object(self.server,'_count_tokens',return_value=100), patch.object(self.server,'_healthy',return_value=True), patch.object(self.server,'_open_stream',return_value=sse_response([{'choices':[{'delta':{'content':'Answer'}, 'finish_reason':'stop'}]},'[DONE]'])):
            self.assertEqual(self.server.chat(messages)['answer'],'Answer')

    def test_oversized_current_question_is_rejected_without_silently_cutting_it(self):
        messages=[{'role':'system','content':'s'},{'role':'user','content':'x' * 2000}]
        with patch.object(self.server,'_count_tokens',side_effect=self.count):
            with self.assertRaisesRegex(ValueError,'bağlam sınırını'):
                self.server._fit_context(messages,self.cancel)
        self.assertEqual(len(messages[-1]['content']),2000)

    def test_continuation_preserves_latest_answer_tail_when_original_prompt_no_longer_fits(self):
        messages=[{'role':'system','content':'s'},{'role':'user','content':'q' * 1400},{'role':'assistant','content':'a' * 700 + 'LATEST END'},{'role':'user','content':'Continue'}]
        with patch.object(self.server,'_count_tokens',side_effect=self.count):
            selected, omitted=self.server._fit_context(messages,self.cancel,continuation=True)
        self.assertTrue(selected[-2]['content'].endswith('LATEST END'))
        self.assertEqual(selected[-1]['content'],'Continue')
        self.assertLessEqual(self.count(selected,None),CONTEXT_SIZE - MAX_OUTPUT_TOKENS - CONTEXT_MARGIN)

    def test_token_counter_uses_model_template_and_tokenizer(self):
        with patch.object(self.server,'_post_json',side_effect=[{'prompt':'formatted chat'},{'tokens':[1,2,3]}]) as post:
            messages=[{'role':'user','content':'Hello'}]
            self.assertEqual(self.server._count_tokens(messages,self.cancel),3)
            self.assertEqual(post.call_args_list[0].args[0],'/apply-template')
            self.assertEqual(post.call_args_list[0].args[1]['messages'],messages)
            self.assertEqual(post.call_args_list[1].args[0],'/tokenize')
            self.assertEqual(post.call_args_list[1].args[1]['content'],'formatted chat')

    def test_truncation_is_returned_explicitly_and_other_finish_errors_are_rejected(self):
        for reason in ('length','content_filter',None):
            with self.subTest(reason=reason), patch.object(self.server,'_healthy',return_value=True), patch.object(self.server,'_count_tokens',return_value=100), patch.object(self.server,'_open_stream',return_value=sse_response([{'choices':[{'delta':{'content':'Answer'}}]},{'choices':[{'delta':{},'finish_reason':reason}]},'[DONE]'])):
                if reason=='length':self.assertEqual(self.server.chat([{'role':'user','content':'Hello'}])['finish_reason'],'length')
                else:
                    with self.assertRaises(GemmaUnavailable):self.server.chat([{'role':'user','content':'Hello'}])

    def test_cancel_interrupts_a_blocked_http_read_without_unloading_model(self):
        entered, released = threading.Event(), threading.Event()
        class Socket:
            def settimeout(self, timeout):pass
            def shutdown(self, how):released.set()
        class Response:
            status=200
            def close(self):pass
            def readline(self):
                entered.set()
                released.wait(2)
                raise OSError('Socket was shut down')
        connection=Mock(sock=Socket())
        connection.getresponse.return_value=Response()
        errors=[]
        def run():
            try:self.server.chat([{'role':'user','content':'Hello'}])
            except Exception as error:errors.append(error)
        with patch.object(self.server,'_healthy',return_value=True), patch.object(self.server,'_count_tokens',return_value=100), patch('backend.app.llm.http.client.HTTPConnection',return_value=connection):
            worker=threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                result=self.server.cancel_response()
                worker.join(.5)
                self.assertFalse(worker.is_alive())
                self.assertTrue(result['model_loaded'])
                self.assertIsInstance(errors[0],GemmaCancelled)
                self.assertFalse(self.server.process.terminated)
                connection.close.assert_called_once()
            finally:
                released.set();worker.join(2)

    def test_pre_cancelled_request_never_starts_network_generation(self):
        self.cancel.set()
        with patch.object(self.server,'_healthy',return_value=True), patch.object(self.server,'_open_stream') as stream:
            with self.assertRaises(GemmaCancelled):
                self.server.chat_stream([{'role':'user','content':'Hello'}],cancel_event=self.cancel)
            stream.assert_not_called()
