"""Safety-net tests for conversation helpers (colorize, print_spinning_wheel,
encode_file_to_base64_with_mime, chatbot helpers, save_conversation_to_file,
summarize_chunk, summarize_text_file, print_possible_prompt_commands, etc.)
These tests cover functions BEFORE they are moved out of ollama_chat.py."""

import os
import json
import math
import tempfile
import pytest
from unittest.mock import patch, MagicMock, call

import ollama_chat as oc
from ollama_chat_lib import state


# ── colorize ──────────────────────────────────────────────────────────────

class TestColorize:

    def test_returns_highlighted_markdown(self):
        result = oc.colorize("# Hello", "md")
        # Should return non-empty string with ANSI codes
        assert len(result) > 0

    def test_unknown_language_returns_input(self):
        result = oc.colorize("some text", "nonexistent_language_xyz")
        assert result == "some text"

    def test_none_input_returns_empty(self):
        result = oc.colorize(None)
        assert result == ""

    def test_default_language_is_md(self):
        result = oc.colorize("**bold**")
        assert len(result) > 0


# ── print_spinning_wheel ─────────────────────────────────────────────────

class TestPrintSpinningWheel:

    @patch("ollama_chat_lib.conversation.on_stdout_flush")
    @patch("ollama_chat_lib.conversation.on_stdout_write")
    def test_writes_spinner_char(self, mock_write, mock_flush):
        oc.print_spinning_wheel(0)
        mock_write.assert_called_once()
        mock_flush.assert_called_once()
        # First spinner char should be "⠋"
        args = mock_write.call_args
        assert "⠋" in args[0][0]

    @patch("ollama_chat_lib.conversation.on_stdout_flush")
    @patch("ollama_chat_lib.conversation.on_stdout_write")
    def test_cycles_through_spinner(self, mock_write, mock_flush):
        oc.print_spinning_wheel(1)
        args = mock_write.call_args
        assert "⠙" in args[0][0]


# ── encode_file_to_base64_with_mime ──────────────────────────────────────

class TestEncodeFileToBase64:

    def test_encodes_text_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = oc.encode_file_to_base64_with_mime(str(f))
        assert result.startswith("data:")
        assert ";base64," in result

    def test_png_mime_type(self, tmp_path):
        f = tmp_path / "img.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
        result = oc.encode_file_to_base64_with_mime(str(f))
        assert "image/png" in result

    def test_pdf_mime_type(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4")
        result = oc.encode_file_to_base64_with_mime(str(f))
        assert "application/pdf" in result


# ── print_possible_prompt_commands ───────────────────────────────────────

class TestPrintPossiblePromptCommands:

    def test_returns_nonempty_string(self):
        result = oc.print_possible_prompt_commands()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_key_commands(self):
        result = oc.print_possible_prompt_commands()
        assert "/cot" in result
        assert "/file" in result
        assert "/search" in result
        assert "/web" in result
        assert "/model" in result
        assert "/tools" in result


# ── split_numbered_list ──────────────────────────────────────────────────

class TestSplitNumberedList:

    def test_basic_numbered_list(self):
        text = "1. Apple\n2. Banana\n3. Cherry"
        result = oc.split_numbered_list(text)
        assert result == ["Apple", "Banana", "Cherry"]

    def test_non_numbered_lines_ignored(self):
        text = "Header\n1. First\n2. Second\nFooter"
        result = oc.split_numbered_list(text)
        assert result == ["First", "Second"]

    def test_empty_input(self):
        assert oc.split_numbered_list("") == []


# ── load_additional_chatbots ─────────────────────────────────────────────

class TestLoadAdditionalChatbots:

    def test_loads_from_json(self, tmp_path, reset_globals):
        state.chatbots = []
        bots = [{"name": "test_bot", "description": "Test", "system_prompt": "You are a test bot."}]
        f = tmp_path / "bots.json"
        f.write_text(json.dumps(bots))
        oc.load_additional_chatbots(str(f))
        assert len(state.chatbots) == 1
        assert state.chatbots[0]["name"] == "test_bot"

    def test_none_input_does_nothing(self, reset_globals):
        initial_len = len(state.chatbots)
        oc.load_additional_chatbots(None)
        assert len(state.chatbots) == initial_len

    @patch("ollama_chat_lib.conversation.on_print")
    def test_missing_file_prints_error(self, mock_print, reset_globals):
        oc.load_additional_chatbots("/nonexistent/file.json")
        mock_print.assert_called()


# ── prompt_for_chatbot ───────────────────────────────────────────────────

class TestPromptForChatbot:

    @patch("ollama_chat_lib.conversation.on_user_input", return_value="0")
    @patch("ollama_chat_lib.conversation.on_print")
    def test_selects_first_chatbot(self, mock_print, mock_input, reset_globals):
        state.chatbots = [
            {"name": "bot1", "description": "First", "system_prompt": "prompt1"},
            {"name": "bot2", "description": "Second", "system_prompt": "prompt2"},
        ]
        result = oc.prompt_for_chatbot()
        assert result["name"] == "bot1"


# ── save_conversation_to_file ────────────────────────────────────────────

class TestSaveConversationToFile:

    def test_saves_txt_and_json(self, tmp_path, reset_globals):
        conversation = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        file_path = str(tmp_path / "conv.txt")
        oc.save_conversation_to_file(conversation, file_path)

        assert os.path.exists(file_path)
        assert os.path.exists(file_path.replace(".txt", ".json"))

        # Text file should NOT contain system messages
        with open(file_path, "r") as f:
            text = f.read()
        assert "You are helpful" not in text
        assert "Hello" in text
        assert "Hi there" in text

    def test_json_contains_all_messages(self, tmp_path, reset_globals):
        conversation = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
            {"role": "assistant", "content": "ast"},
        ]
        file_path = str(tmp_path / "conv.txt")
        oc.save_conversation_to_file(conversation, file_path)

        json_path = file_path.replace(".txt", ".json")
        with open(json_path, "r") as f:
            data = json.load(f)
        assert len(data) == 3


# ── summarize_chunk ──────────────────────────────────────────────────────

class TestSummarizeChunk:

    @patch("ollama_chat.ask_ollama", return_value="Summary of chunk")
    def test_returns_summary(self, mock_ask):
        result = oc.summarize_chunk("Some long text here...", "model", 50)
        assert result == "Summary of chunk"
        mock_ask.assert_called_once()

    @patch("ollama_chat.ask_ollama", return_value=None)
    def test_returns_empty_on_none(self, mock_ask):
        result = oc.summarize_chunk("text", "model", 50)
        assert result == ""

    @patch("ollama_chat.ask_ollama", return_value="Context-aware summary")
    def test_includes_previous_summary(self, mock_ask):
        result = oc.summarize_chunk("chunk", "model", 50, previous_summary="prev")
        assert result == "Context-aware summary"
        call_args = mock_ask.call_args
        assert "prev" in call_args[0][1]  # user_input should contain previous summary


# ── summarize_text_file ──────────────────────────────────────────────────

class TestSummarizeTextFile:

    @patch("ollama_chat.ask_ollama", return_value="Final summary")
    def test_summarizes_short_file(self, mock_ask, tmp_path, reset_globals):
        # File under max_final_words => no summarization needed
        f = tmp_path / "short.txt"
        f.write_text("A short text with just a few words.")
        result = oc.summarize_text_file(str(f), model="test_model", max_final_words=500)
        assert isinstance(result, str)
        # No summarization should be called since text is short
        mock_ask.assert_not_called()

    @patch("ollama_chat.ask_ollama", return_value="summary")
    def test_summarizes_long_file(self, mock_ask, tmp_path, reset_globals):
        state.current_model = "test_model"
        # Create a long file that needs summarization
        f = tmp_path / "long.txt"
        f.write_text(" ".join(["word"] * 2000))  # 2000 words
        result = oc.summarize_text_file(str(f), model="test_model", max_final_words=100)
        assert isinstance(result, str)
        assert mock_ask.called
