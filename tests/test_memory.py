"""Tests for MemoryManager and LongTermMemoryManager."""
import os
import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import ollama_chat as oc


class TestLongTermMemoryManager:

    def test_load_empty_memory(self, tmp_path):
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.LongTermMemoryManager("test-model", verbose=False)

        assert mgr.memory == {"users": {}}

    def test_load_existing_memory(self, tmp_path):
        data = {"users": {"alice": {"hobby": "reading"}}}
        mem_file = tmp_path / "long_term_memory.json"
        mem_file.write_text(json.dumps(data))

        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.LongTermMemoryManager("test-model", verbose=False)

        assert mgr.memory["users"]["alice"]["hobby"] == "reading"

    def test_save_memory(self, tmp_path):
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.LongTermMemoryManager("test-model", verbose=False)

        mgr.memory["users"]["bob"] = {"name": "Bob"}
        mgr._save_memory()

        saved = json.loads((tmp_path / "long_term_memory.json").read_text())
        assert saved["users"]["bob"]["name"] == "Bob"

    def test_update_user_memory(self, tmp_path):
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.LongTermMemoryManager("test-model", verbose=False)

        mgr._update_user_memory("user1", {"city": "Paris"})
        assert mgr.memory["users"]["user1"]["city"] == "Paris"
        # File should be persisted
        saved = json.loads((tmp_path / "long_term_memory.json").read_text())
        assert saved["users"]["user1"]["city"] == "Paris"

    def test_update_user_memory_merge(self, tmp_path):
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.LongTermMemoryManager("test-model", verbose=False)

        mgr._update_user_memory("user1", {"city": "Paris"})
        mgr._update_user_memory("user1", {"hobby": "chess"})
        assert mgr.memory["users"]["user1"]["city"] == "Paris"
        assert mgr.memory["users"]["user1"]["hobby"] == "chess"

    def test_remove_conflicting_info(self, tmp_path):
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.LongTermMemoryManager("test-model", verbose=False)

        mgr._update_user_memory("u1", {"city": "Paris", "job": "dev"})
        mgr._remove_conflicting_info("u1", {"city": "old value"})
        assert "city" not in mgr.memory["users"]["u1"]
        assert mgr.memory["users"]["u1"]["job"] == "dev"

    def test_get_extraction_prompt(self, tmp_path):
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.LongTermMemoryManager("test-model", verbose=False)

        prompt = mgr._get_extraction_prompt()
        assert "key-value" in prompt.lower()
        assert "json" in prompt.lower()


class TestMemoryManager:

    @pytest.fixture()
    def mock_chroma(self):
        client = MagicMock()
        collection = MagicMock()
        client.get_or_create_collection.return_value = collection
        return client, collection

    def test_init(self, mock_chroma, tmp_path):
        client, collection = mock_chroma
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.MemoryManager(
                collection_name="test_mem",
                chroma_client=client,
                selected_model="test-model",
                embedding_model_name="nomic-embed",
                verbose=False,
            )
        assert mgr.collection_name == "test_mem"
        client.get_or_create_collection.assert_called_once_with(name="test_mem")

    def test_generate_embedding(self, mock_chroma, tmp_path):
        client, collection = mock_chroma
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.MemoryManager(
                collection_name="test_mem",
                chroma_client=client,
                selected_model="test-model",
                embedding_model_name="nomic-embed",
                verbose=False,
            )

        with patch("ollama_chat_lib.memory.ollama.embeddings", return_value={"embedding": [0.1, 0.2, 0.3]}):
            emb = mgr.generate_embedding("hello")
        assert emb == [0.1, 0.2, 0.3]

    def test_generate_embedding_no_model(self, mock_chroma, tmp_path):
        client, collection = mock_chroma
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.MemoryManager(
                collection_name="test_mem",
                chroma_client=client,
                selected_model="test-model",
                embedding_model_name=None,  # No embedding model
                verbose=False,
            )
        emb = mgr.generate_embedding("hello")
        assert emb is None

    def test_retrieve_relevant_memory(self, mock_chroma, tmp_path):
        client, collection = mock_chroma
        collection.query.return_value = {
            "documents": [["memory about Paris"]],
            "distances": [[0.5]],
            "metadatas": [[{"timestamp": "Jan 1"}]],
        }
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.MemoryManager(
                collection_name="test_mem",
                chroma_client=client,
                selected_model="test-model",
                embedding_model_name="nomic-embed",
                verbose=False,
            )

        with patch("ollama_chat_lib.memory.ollama.embeddings", return_value={"embedding": [0.1]}):
            docs, metas = mgr.retrieve_relevant_memory("Paris")
        assert "memory about Paris" in docs
        assert metas[0]["timestamp"] == "Jan 1"

    def test_retrieve_filters_by_distance(self, mock_chroma, tmp_path):
        client, collection = mock_chroma
        collection.query.return_value = {
            "documents": [["close", "far"]],
            "distances": [[1.0, 500.0]],
            "metadatas": [[{"t": "1"}, {"t": "2"}]],
        }
        with patch("ollama_chat_lib.memory.AppDirs") as mock_dirs:
            mock_dirs.return_value.user_data_dir = str(tmp_path)
            mgr = oc.MemoryManager(
                collection_name="test_mem",
                chroma_client=client,
                selected_model="test-model",
                embedding_model_name="nomic-embed",
                verbose=False,
            )

        with patch("ollama_chat_lib.memory.ollama.embeddings", return_value={"embedding": [0.1]}):
            docs, metas = mgr.retrieve_relevant_memory("query", answer_distance_threshold=200)
        assert len(docs) == 1
        assert docs[0] == "close"
