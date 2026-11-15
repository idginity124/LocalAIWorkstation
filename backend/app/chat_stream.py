"""SSE turn lifetime: cancellation cannot strand a conversation reservation."""
from __future__ import annotations

import asyncio
import json
import threading
from fastapi.responses import StreamingResponse

from .llm import GemmaCancelled, GemmaUnavailable


class ChatStreamResponse(StreamingResponse):
    def __init__(self, *, generate, commit, cancel, release, cancel_event):
        self.generate = generate
        self.commit = commit
        self.cancel_worker = cancel
        self.release = release
        self.cancel_event = cancel_event
        self._guard = threading.Lock()
        self._started = False
        self._finished = False
        self._closed = False
        super().__init__(self.events(), media_type='text/event-stream',
                         headers={'Cache-Control':'no-store', 'X-Accel-Buffering':'no'})

    def close(self):
        with self._guard:
            self._closed = True
            self.cancel_event.set()
            running = self._started and not self._finished
        try:
            if running:
                self.cancel_worker()
        finally:
            # If a reader is still stopping, keep ownership until its thread
            # actually exits. There is no await here for repeated cancellation
            # to interrupt, and no lock is released under another active turn.
            if not running:
                self.release()

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.close()

    async def events(self):
        loop = asyncio.get_running_loop()
        pending = asyncio.Queue()

        def deliver(event):
            with self._guard:
                if self._closed:
                    return
            try:
                loop.call_soon_threadsafe(pending.put_nowait, event)
            except RuntimeError:
                # The ASGI event loop has shut down. The worker still releases
                # its reservation below and never writes history from a thread.
                self.close()

        def run():
            try:
                if self.cancel_event.is_set():
                    raise GemmaCancelled('Yanıt durduruldu.')
                result = self.generate(lambda text: deliver({'type':'delta', 'text':text}))
                deliver({'type':'result', 'result':result})
            except BaseException as error:
                deliver({'type':'failure', 'error':error})
            finally:
                with self._guard:
                    self._finished = True
                    closed = self._closed
                if closed:
                    self.release()

        try:
            with self._guard:
                if self._closed:
                    return
                if self.cancel_event.is_set():
                    raise GemmaCancelled('Yanıt durduruldu.')
                self._started = True
            try:
                threading.Thread(target=run, name='chat-turn', daemon=True).start()
            except BaseException:
                with self._guard:
                    self._finished = True
                raise
            while True:
                item = await pending.get()
                if self.cancel_event.is_set():
                    raise GemmaCancelled('Yanıt durduruldu; tamamlanmamış mesaj kaydedilmedi.')
                if item['type'] == 'delta':
                    yield self.encode(item)
                elif item['type'] == 'failure':
                    raise item['error']
                else:
                    result = item['result']
                    committed = self.commit(result)
                    timings = result.get('timings', {})
                    speed = timings.get('predicted_per_second') if isinstance(timings, dict) else None
                    yield self.encode({'type':'done', **committed,
                        'tokens_per_second':speed if isinstance(speed,(int,float)) and speed >= 0 else None,
                        'finish_reason':result.get('finish_reason','stop'),
                        'omitted_messages':result.get('omitted_messages',0)})
                    return
        except GemmaCancelled as error:
            yield self.encode({'type':'error', 'code':'cancelled', 'message':str(error)})
        except (GemmaUnavailable, ValueError) as error:
            yield self.encode({'type':'error', 'code':'unavailable', 'message':str(error)})
        except Exception:
            yield self.encode({'type':'error', 'code':'internal', 'message':'Sohbet yanıtı tamamlanamadı; kısmi içerik kaydedilmedi.'})
        finally:
            self.close()

    @staticmethod
    def encode(value):
        return 'data: ' + json.dumps(value, ensure_ascii=False) + '\n\n'
