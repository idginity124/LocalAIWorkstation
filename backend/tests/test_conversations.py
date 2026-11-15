from pathlib import Path
import tempfile
import unittest

from backend.app.conversations import CodeAssistantChat, ConversationRepository
from backend.app.projects import ProjectService
from backend.app.storage import open_database


class FakeChatBackend:
    def __init__(self):
        self.calls = []
        self.answer = "Yanıt"
        self.fail = False

    def chat(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("model error")
        return {"answer": self.answer, "reasoning_content": "bu alan kaydedilmemeli"}


class ConversationPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.db = open_database(self.base / "state.sqlite3")
        self.repository = ConversationRepository(self.db)
        self.projects = ProjectService(self.db)
        self.backend = FakeChatBackend()
        self.chat = CodeAssistantChat(self.repository, self.projects, self.backend)
        self.conversation = self.repository.create(kind="code")

    def tearDown(self) -> None:
        self.db.close()
        self.temp_dir.cleanup()

    def test_multi_turn_history_persists_in_order_and_keeps_only_final_answer(self) -> None:
        first = self.chat.ask(self.conversation["id"], "İlk soru")
        self.assertEqual([m["role"] for m in first["messages"]], ["user", "assistant"])
        self.assertEqual(first["messages"][1]["content"], "Yanıt")
        self.assertNotIn("reasoning_content", str(first["messages"]))

        self.backend.answer = "İkinci yanıt"
        second = self.chat.ask(self.conversation["id"], "İkinci soru")
        sent = self.backend.calls[1]
        self.assertEqual([m["role"] for m in sent], ["system", "user", "assistant", "user"])
        self.assertIn("güvenilmeyen veri", sent[0]["content"])
        self.assertEqual(sent[1]["content"], "İlk soru")
        self.assertEqual(sent[2]["content"], "Yanıt")
        self.assertEqual(len(second["messages"]), 4)

    def test_failed_inference_does_not_write_partial_exchange(self) -> None:
        self.backend.fail = True
        with self.assertRaisesRegex(RuntimeError, "model error"):
            self.chat.ask(self.conversation["id"], "Başarısız soru")
        self.assertEqual(self.repository.get_messages(self.conversation["id"]), [])

    def test_context_must_be_inside_registered_project_and_unsaved_buffer_is_used(self) -> None:
        root = self.base / "chosen"
        root.mkdir()
        (root / "main.py").write_text("saved = True\n", encoding="utf-8")
        project = self.projects.register(str(root))
        self.chat.ask(self.conversation["id"], "Açıkla", project_id=project["id"],
                      context_path="main.py", context_content="unsaved = True\n")
        self.assertIn("Seçili dosya: main.py", self.backend.calls[0][-1]["content"])
        self.assertIn("unsaved = True", self.backend.calls[0][-1]["content"])
        with self.assertRaises(PermissionError):
            self.chat.ask(self.conversation["id"], "Oku", project_id=project["id"],
                          context_path=".env", context_content="secret")

    def test_rename_delete_and_message_cascade(self) -> None:
        self.chat.ask(self.conversation["id"], "Bir soru")
        renamed = self.repository.rename(self.conversation["id"], "Yeni başlık")
        self.assertEqual(renamed["title"], "Yeni başlık")
        self.repository.delete(self.conversation["id"])
        with self.assertRaises(KeyError):
            self.repository.get(self.conversation["id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)

    def test_conversation_and_final_messages_survive_database_reopen(self) -> None:
        self.chat.ask(self.conversation["id"], "Kalıcı soru")
        database_path = self.base / "state.sqlite3"
        self.db.close()
        self.db = open_database(database_path)
        restored = ConversationRepository(self.db)
        self.assertEqual(restored.get(self.conversation["id"])["title"], "Kalıcı soru")
        self.assertEqual([message["content"] for message in restored.get_messages(self.conversation["id"])], ["Kalıcı soru", "Yanıt"])

    def test_blank_message_and_invalid_title_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.chat.ask(self.conversation["id"], " \n ")
        with self.assertRaises(ValueError):
            self.repository.rename(self.conversation["id"], " ")

    def test_code_conversation_retains_alternative_local_model(self) -> None:
        for identifier in ("qwen3.5-9b-q8_0", "gpt-oss-20b-mxfp4"):
            conversation = self.repository.create(kind="code", model_id=identifier)
            self.assertEqual(self.repository.get(conversation["id"])["model_id"], identifier)
            self.assertEqual(self.repository.list("code")[0]["model_id"], identifier)

    def test_general_assistant_and_code_conversations_are_separated(self) -> None:
        from backend.app.conversations import LocalAssistantChat

        assistant_conversation = self.repository.create(kind="assistant")
        assistant = LocalAssistantChat(self.repository, self.projects, self.backend)
        result = assistant.ask(assistant_conversation["id"], "Merhaba")
        self.assertEqual(result["messages"][0]["content"], "Merhaba")
        self.assertEqual(self.repository.list("assistant")[0]["id"], assistant_conversation["id"])
        self.assertEqual(self.repository.list("code")[0]["id"], self.conversation["id"])
        with self.assertRaises(KeyError):
            assistant.prepare(self.conversation["id"], "Bu kod sohbeti")
        with self.assertRaises(ValueError):
            assistant.prepare(assistant_conversation["id"], "Merhaba", context_path="secret.txt")


if __name__ == "__main__":
    unittest.main()

class AssistantRegressionTests(unittest.TestCase):
    setUp = ConversationPersistenceTests.setUp
    tearDown = ConversationPersistenceTests.tearDown

    def test_titles_are_generated_independently_of_interface_language(self):
        for title in ('Yeni sohbet','New chat','新对话','Nouvelle conversation','محادثة جديدة'):
            conversation = self.repository.create(title=title, kind='assistant', auto_title=True)
            self.repository.add_exchange(conversation['id'], '\nFirst question\nmore', 'Answer')
            self.assertEqual(self.repository.get(conversation['id'])['title'], 'First question')
        custom = self.repository.create(title='My title', auto_title=False)
        self.repository.add_exchange(custom['id'], 'First question', 'Answer')
        self.assertEqual(self.repository.get(custom['id'])['title'], 'My title')

    def test_manual_title_is_preserved_during_generation(self):
        identifier = self.conversation['id']
        cancel = self.repository.begin_turn(identifier)
        self.repository.rename(identifier, 'Chosen title')
        self.repository.add_exchange(identifier, 'Question', 'Answer')
        self.repository.end_turn(identifier, cancel)
        self.assertEqual(self.repository.get(identifier)['title'], 'Chosen title')

    def test_active_delete_and_overlapping_turns_are_rejected_by_backend(self):
        from backend.app.conversations import ConversationBusy
        identifier = self.conversation['id']
        other = self.repository.create(kind='assistant')
        cancel = self.repository.begin_turn(identifier)
        with self.assertRaises(ConversationBusy): self.repository.delete(identifier)
        with self.assertRaises(ConversationBusy): self.repository.begin_turn(other['id'])
        self.repository.delete(other['id'])
        # Unrelated/stale owners cannot release the active turn.
        import threading
        self.repository.end_turn(identifier, threading.Event())
        with self.assertRaises(ConversationBusy): self.repository.delete(identifier)
        self.repository.end_turn(identifier, cancel)
        self.repository.delete(identifier)

    def test_cancelled_or_stale_continuation_never_overwrites_newer_messages(self):
        from backend.app.conversations import LocalAssistantChat
        chat = LocalAssistantChat(self.repository, self.projects, self.backend)
        conversation = self.repository.create(kind='assistant')
        identifier = conversation['id']
        self.repository.add_exchange(identifier, 'Question', 'Part one', 'length')
        prepared = chat.prepare_continuation(identifier)
        # A failed continuation has no write to roll back.
        self.assertEqual(self.repository.get_messages(identifier)[-1]['content'], 'Part one')
        self.repository.add_exchange(identifier, 'New question', 'New answer')
        with self.assertRaises(ValueError): chat.commit(prepared, {'answer':'Stale continuation','finish_reason':'stop'})
        self.assertEqual(self.repository.get_messages(identifier)[-1]['content'], 'New answer')
