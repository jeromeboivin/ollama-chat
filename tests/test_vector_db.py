"""Safety-net tests for vector DB functions BEFORE extraction."""

import pytest
from unittest.mock import patch, MagicMock

import ollama_chat as oc
from ollama_chat_lib import state


# ── load_chroma_client ───────────────────────────────────────────────────

class TestLoadChromaClient:

    def test_skips_when_already_loaded(self, reset_globals):
        state.chroma_client = MagicMock()
        original = state.chroma_client
        oc.load_chroma_client()
        assert state.chroma_client is original

    @patch("ollama_chat_lib.vector_db.chromadb")
    def test_creates_persistent_client(self, mock_chromadb, reset_globals):
        state.chroma_client = None
        state.chroma_db_path = "/tmp/test_chroma"
        state.chroma_client_host = None
        state.chroma_client_port = 0
        oc.load_chroma_client()
        mock_chromadb.PersistentClient.assert_called_once_with(path="/tmp/test_chroma")

    @patch("ollama_chat_lib.vector_db.chromadb")
    def test_creates_http_client(self, mock_chromadb, reset_globals):
        state.chroma_client = None
        state.chroma_db_path = None
        state.chroma_client_host = "localhost"
        state.chroma_client_port = 8000
        oc.load_chroma_client()
        mock_chromadb.HttpClient.assert_called_once_with(host="localhost", port=8000)

    @patch("ollama_chat_lib.vector_db.chromadb")
    def test_handles_failure_gracefully(self, mock_chromadb, reset_globals):
        state.chroma_client = None
        state.chroma_db_path = None
        state.chroma_client_host = None
        state.chroma_client_port = 0
        oc.load_chroma_client()
        assert state.chroma_client is None


# ── set_current_collection ───────────────────────────────────────────────

class TestSetCurrentCollection:

    @patch("ollama_chat_lib.vector_db.load_chroma_client")
    def test_clears_when_name_is_none(self, mock_load, reset_globals):
        state.chroma_client = MagicMock()
        oc.set_current_collection(None)
        assert state.collection is None
        assert state.current_collection_name is None

    @patch("ollama_chat_lib.vector_db.load_chroma_client")
    def test_sets_collection(self, mock_load, reset_globals):
        mock_col = MagicMock()
        mock_col.metadata = {}
        state.chroma_client = MagicMock()
        state.chroma_client.get_or_create_collection.return_value = mock_col
        oc.set_current_collection("test_col")
        assert state.current_collection_name == "test_col"
        assert state.collection is mock_col

    @patch("ollama_chat_lib.vector_db.load_chroma_client")
    def test_updates_description(self, mock_load, reset_globals):
        mock_col = MagicMock()
        mock_col.metadata = {"description": "old"}
        state.chroma_client = MagicMock()
        state.chroma_client.get_or_create_collection.return_value = mock_col
        oc.set_current_collection("test_col", description="new desc")
        mock_col.modify.assert_called_once()


# ── delete_collection ────────────────────────────────────────────────────

class TestDeleteCollection:

    @patch("ollama_chat_lib.vector_db.on_user_input", return_value="y")
    @patch("ollama_chat_lib.vector_db.on_print")
    @patch("ollama_chat_lib.vector_db.load_chroma_client")
    def test_deletes_on_confirm(self, mock_load, mock_print, mock_input, reset_globals):
        state.chroma_client = MagicMock()
        oc.delete_collection("test_col")
        state.chroma_client.delete_collection.assert_called_once_with(name="test_col")

    @patch("ollama_chat_lib.vector_db.on_user_input", return_value="n")
    @patch("ollama_chat_lib.vector_db.on_print")
    @patch("ollama_chat_lib.vector_db.load_chroma_client")
    def test_cancels_on_reject(self, mock_load, mock_print, mock_input, reset_globals):
        state.chroma_client = MagicMock()
        oc.delete_collection("test_col")
        state.chroma_client.delete_collection.assert_not_called()


# ── preprocess_text ──────────────────────────────────────────────────────

class TestPreprocessText:

    def test_lowercases_and_tokenizes(self):
        result = oc.preprocess_text("Hello World")
        assert "hello" in result
        assert "world" in result

    def test_empty_input(self):
        assert oc.preprocess_text("") == []
        assert oc.preprocess_text(None) == []

    def test_removes_stop_words(self):
        result = oc.preprocess_text("the is a this that")
        # Common stop words should be removed
        assert len(result) < 5


# ── query_vector_database ────────────────────────────────────────────────

class TestQueryVectorDatabase:

    def test_empty_question_returns_empty(self, reset_globals):
        result = oc.query_vector_database("")
        assert result == ""

    def test_empty_question_with_metadata(self, reset_globals):
        result, meta = oc.query_vector_database("", return_metadata=True)
        assert result == ""
        assert meta == {}

    def test_zero_results_returns_empty(self, reset_globals):
        result = oc.query_vector_database("anything", n_results=0)
        assert result == ""

    @patch("ollama_chat.ask_ollama", return_value="expanded query")
    @patch("ollama_chat_lib.vector_db.ollama")
    @patch("ollama_chat_lib.vector_db.load_chroma_client")
    def test_queries_collection(self, mock_load, mock_ollama, mock_ask, reset_globals):
        import numpy as np
        
        mock_col = MagicMock()
        mock_col.query.return_value = {
            "documents": [["Doc about AI"]],
            "distances": [[0.1]],
            "metadatas": [[{"title": "AI doc", "url": "http://example.com"}]],
        }
        state.collection = mock_col
        state.current_collection_name = "test"
        state.embeddings_model = "test-embed"
        state.thinking_model = None
        state.current_model = "test-model"
        
        mock_ollama.embeddings.return_value = {"embedding": [0.1] * 768}
        
        result = oc.query_vector_database("What is AI?", collection_name="test")
        assert "Doc about AI" in result

    @patch("ollama_chat_lib.vector_db.ollama")
    @patch("ollama_chat_lib.vector_db.load_chroma_client")
    def test_no_expand_query(self, mock_load, mock_ollama, reset_globals):
        mock_col = MagicMock()
        mock_col.query.return_value = {
            "documents": [["Result"]],
            "distances": [[0.1]],
            "metadatas": [[{"title": "T"}]],
        }
        state.collection = mock_col
        state.current_collection_name = "test"
        state.embeddings_model = "test-embed"
        
        mock_ollama.embeddings.return_value = {"embedding": [0.1] * 768}
        
        result = oc.query_vector_database("query", expand_query=False)
        assert "Result" in result


# ── edit_collection_metadata ─────────────────────────────────────────────

class TestEditCollectionMetadata:

    @patch("ollama_chat_lib.vector_db.on_user_input", return_value="New description")
    @patch("ollama_chat_lib.vector_db.on_print")
    @patch("ollama_chat_lib.vector_db.load_chroma_client")
    def test_updates_metadata(self, mock_load, mock_print, mock_input, reset_globals):
        mock_col = MagicMock()
        mock_col.metadata = {"description": "Old"}
        state.chroma_client = MagicMock()
        state.chroma_client.get_collection.return_value = mock_col
        
        oc.edit_collection_metadata("test_col")
        mock_col.modify.assert_called_once()

    @patch("ollama_chat_lib.vector_db.on_print")
    @patch("ollama_chat_lib.vector_db.load_chroma_client")
    def test_handles_none_name(self, mock_load, mock_print, reset_globals):
        state.chroma_client = MagicMock()
        oc.edit_collection_metadata(None)
        mock_print.assert_called()
