"""Safety-net tests for model selection functions BEFORE extraction."""

import pytest
from unittest.mock import patch, MagicMock

import ollama_chat as oc
from ollama_chat_lib import state


# ── select_ollama_model_if_available ─────────────────────────────────────

class TestSelectOllamaModelIfAvailable:

    @patch("ollama_chat_lib.model_selection.ollama")
    def test_returns_model_when_found(self, mock_ollama, reset_globals):
        mock_ollama.list.return_value = {
            "models": [{"model": "llama3:latest", "size": 4_000_000_000}]
        }
        result = oc.select_ollama_model_if_available("llama3:latest")
        assert result == "llama3:latest"

    @patch("ollama_chat_lib.model_selection.on_print")
    @patch("ollama_chat_lib.model_selection.ollama")
    def test_returns_none_when_not_found(self, mock_ollama, mock_print, reset_globals):
        mock_ollama.list.return_value = {
            "models": [{"model": "llama3:latest", "size": 4_000_000_000}]
        }
        result = oc.select_ollama_model_if_available("nonexistent:model")
        assert result is None

    @patch("ollama_chat_lib.model_selection.on_print")
    @patch("ollama_chat_lib.model_selection.ollama")
    def test_returns_none_when_ollama_down(self, mock_ollama, mock_print, reset_globals):
        mock_ollama.list.side_effect = Exception("connection refused")
        result = oc.select_ollama_model_if_available("llama3:latest")
        assert result is None

    def test_returns_none_for_empty_name(self, reset_globals):
        result = oc.select_ollama_model_if_available(None)
        assert result is None


# ── select_openai_model_if_available ─────────────────────────────────────

class TestSelectOpenaiModelIfAvailable:

    def test_returns_model_when_found(self, reset_globals):
        mock_model = MagicMock()
        mock_model.id = "gpt-4"
        state.openai_client = MagicMock()
        state.openai_client.models.list.return_value.data = [mock_model]
        result = oc.select_openai_model_if_available("gpt-4")
        assert result == "gpt-4"

    @patch("ollama_chat_lib.model_selection.on_print")
    def test_returns_none_when_not_found(self, mock_print, reset_globals):
        mock_model = MagicMock()
        mock_model.id = "gpt-4"
        state.openai_client = MagicMock()
        state.openai_client.models.list.return_value.data = [mock_model]
        result = oc.select_openai_model_if_available("nonexistent")
        assert result is None

    def test_returns_none_for_empty_name(self, reset_globals):
        result = oc.select_openai_model_if_available(None)
        assert result is None


# ── is_model_an_ollama_model ─────────────────────────────────────────────

class TestIsModelAnOllamaModel:

    @patch("ollama_chat_lib.model_selection.ollama")
    def test_true_for_existing_model(self, mock_ollama, reset_globals):
        mock_ollama.list.return_value = {
            "models": [{"model": "llama3:latest"}]
        }
        assert oc.is_model_an_ollama_model("llama3:latest") is True

    @patch("ollama_chat_lib.model_selection.ollama")
    def test_false_for_missing_model(self, mock_ollama, reset_globals):
        mock_ollama.list.return_value = {
            "models": [{"model": "llama3:latest"}]
        }
        assert oc.is_model_an_ollama_model("gpt-4") is False

    @patch("ollama_chat_lib.model_selection.ollama")
    def test_false_when_ollama_down(self, mock_ollama, reset_globals):
        mock_ollama.list.side_effect = Exception("connection refused")
        assert oc.is_model_an_ollama_model("llama3:latest") is False


# ── prompt_for_model ─────────────────────────────────────────────────────

class TestPromptForModel:

    @patch("ollama_chat_lib.model_selection.prompt_for_ollama_model", return_value="llama3:latest")
    def test_delegates_to_ollama_when_not_openai(self, mock_prompt, reset_globals):
        state.use_openai = False
        result = oc.prompt_for_model("default", "current")
        assert result == "llama3:latest"
        mock_prompt.assert_called_once_with("default", "current")

    @patch("ollama_chat_lib.model_selection.prompt_for_openai_model", return_value="gpt-4")
    def test_delegates_to_openai(self, mock_prompt, reset_globals):
        state.use_openai = True
        result = oc.prompt_for_model("default", "current")
        assert result == "gpt-4"
        mock_prompt.assert_called_once_with("default", "current")


# ── prompt_for_ollama_model ──────────────────────────────────────────────

class TestPromptForOllamaModel:

    @patch("ollama_chat_lib.model_selection.on_user_input", return_value="0")
    @patch("ollama_chat_lib.model_selection.on_stdout_flush")
    @patch("ollama_chat_lib.model_selection.on_stdout_write")
    @patch("ollama_chat_lib.model_selection.on_print")
    @patch("ollama_chat_lib.model_selection.ollama")
    def test_selects_first_model(self, mock_ollama, mock_print, mock_write, mock_flush, mock_input, reset_globals):
        mock_ollama.list.return_value = {
            "models": [
                {"model": "llama3:latest", "size": 4_000_000_000},
                {"model": "qwen:7b", "size": 7_000_000_000},
            ]
        }
        result = oc.prompt_for_ollama_model("llama3:latest", "llama3:latest")
        assert result == "llama3:latest"


# ── prompt_for_openai_model ──────────────────────────────────────────────

class TestPromptForOpenaiModel:

    @patch("ollama_chat_lib.model_selection.on_user_input", return_value="0")
    @patch("ollama_chat_lib.model_selection.on_stdout_flush")
    @patch("ollama_chat_lib.model_selection.on_stdout_write")
    @patch("ollama_chat_lib.model_selection.on_print")
    def test_selects_first_model(self, mock_print, mock_write, mock_flush, mock_input, reset_globals):
        mock_model = MagicMock()
        mock_model.id = "gpt-4"
        state.openai_client = MagicMock()
        state.openai_client.models.list.return_value.data = [mock_model]
        result = oc.prompt_for_openai_model("gpt-4", "gpt-4")
        assert result == "gpt-4"
