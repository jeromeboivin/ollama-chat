"""Tests for CLI argument parsing (the argparse inside run())."""
import asyncio
import importlib
import sys
import pytest
from unittest.mock import patch, MagicMock
import ollama_chat as oc
from types import SimpleNamespace
from ollama_chat_lib import run_helpers
from ollama_chat_lib import state


def _parse_args(argv):
    """Helper: patch sys.argv and invoke run() just far enough to parse args.

    We patch argparse and the heavy initialization to avoid side effects.
    Actually, since the arg parser lives inside run(), we'll test it via
    a subprocess or by extracting globals after run() sets them.

    For a simpler approach, we test the argparse block by importing the
    module and checking the globals that argparse would set.
    """
    # We can't easily isolate argparse from run() without refactoring.
    # Instead, test via the module-level globals that run() writes to.
    pass


class TestCLIFlags:
    """Smoke-test that known CLI flags exist and parse without error.

    Since argparse is embedded in run(), these tests verify behavior
    through the known globals and function signatures rather than
    invoking run() directly.
    """

    def test_commands_list_completeness(self):
        """COMMANDS should include all documented slash commands."""
        expected = {"/help", "/context", "/index", "/verbose", "/search", "/web",
                    "/model", "/tools", "/load", "/save", "/quit", "/exit",
                    "/bye", "/collection", "/memory", "/remember", "/think"}
        assert expected.issubset(set(oc.COMMANDS))

    def test_default_globals(self):
        """Default values of key globals are sane."""
        importlib.reload(state)
        assert state.temperature == 0.1
        assert state.verbose_mode is False
        assert state.use_openai is False
        assert state.use_azure_openai is False
        assert state.interactive_mode is True
        assert state.syntax_highlighting is True
        assert isinstance(state.plugins, list)
        assert isinstance(state.selected_tools, list)
        assert isinstance(state.custom_tools, list)

    def test_rag_parameters_defaults(self):
        """RAG tuning parameters have expected defaults."""
        assert oc.min_quality_results_threshold == 5
        assert oc.min_average_bm25_threshold == 0.5
        assert oc.min_hybrid_score_threshold == 0.1
        assert oc.distance_percentile_threshold == 75
        assert oc.semantic_weight == 0.5
        assert oc.adaptive_distance_multiplier == 2.5

    def test_stop_words_populated(self):
        """Stop words list is populated."""
        assert len(oc.stop_words) > 50
        assert "the" in oc.stop_words
        assert "and" in oc.stop_words


class TestIndexingPrompts:

    def test_prompt_for_boolean_setting_keeps_default_on_empty_input(self):
        with patch("ollama_chat_lib.run_helpers.on_user_input", return_value=""):
            assert run_helpers.prompt_for_boolean_setting("Chunk large documents?", True) is True
            assert run_helpers.prompt_for_boolean_setting("Chunk large documents?", False) is False

    def test_prompt_for_indexing_settings_collects_preflight_answers(self):
        args = SimpleNamespace(
            chunk_documents=True,
            skip_existing=True,
            split_paragraphs=False,
            add_summary=True,
            store_full_docs=False,
            extract_start=None,
            extract_end=None,
        )

        with patch(
            "ollama_chat_lib.run_helpers.on_user_input",
            side_effect=["n", "n", "y", "n", "y", "## Main Code", ""],
        ), patch("ollama_chat_lib.run_helpers.on_print"):
            settings = run_helpers.prompt_for_indexing_settings(args)

        assert settings["chunk_documents"] is False
        assert settings["skip_existing"] is False
        assert settings["split_paragraphs"] is True
        assert settings["add_summary"] is False
        assert settings["store_full_docs"] is False
        assert settings["extract_start"] == "## Main Code"
        assert settings["extract_end"] is None


class TestCollectMultilineInput:

    @patch("ollama_chat_lib.run_helpers.on_stdout_write")
    @patch("ollama_chat_lib.run_helpers.on_user_input", side_effect=["second line \\", "final line"])
    def test_collects_backslash_continuation(self, mock_input, mock_write):
        result = run_helpers.collect_multiline_input("first line \\")
        assert result == "first line\nsecond line\nfinal line"
        assert mock_input.call_count == 2
        assert mock_write.call_count == 2

    @patch("ollama_chat_lib.run_helpers.on_stdout_write")
    @patch("ollama_chat_lib.run_helpers.on_user_input", side_effect=["middle line", "closing line\"\"\""])
    def test_collects_triple_quote_multiline(self, mock_input, mock_write):
        result = run_helpers.collect_multiline_input('"""opening line')
        assert result == "opening line\nmiddle line\nclosing line"
        assert mock_input.call_count == 2
        assert mock_write.call_count == 2


class TestEnhancedPromptHelpers:

    def test_toolbar_includes_model_and_modes(self):
        toolbar = oc.format_chat_toolbar("llama3.2", tools_enabled=True, memory_enabled=True, think_enabled=True)
        assert "Enter send" in toolbar
        assert "Alt+Enter newline" in toolbar
        assert "Tab picker" in toolbar
        assert "model llama3.2" in toolbar
        assert "tools" in toolbar
        assert "memory on" in toolbar
        assert "think on" in toolbar

    def test_command_catalog_groups_slash_commands(self):
        commands = oc.command_catalog()
        assert any(entry["group"] == "Chat" and entry["command"] == "/model" for entry in commands)
        assert any(entry["group"] == "Context and Retrieval" and entry["command"] == "/search" for entry in commands)
        assert any(entry["group"] == "Workspace and Session" and entry["command"] == "/save" for entry in commands)

    def test_find_matching_commands_supports_fuzzy_search(self):
        matches = oc.find_matching_commands("/mdl")
        assert matches[0]["command"] == "/model"
        assert matches[0]["group"] == "Chat"

    def test_find_matching_commands_keeps_group_order(self):
        matches = oc.find_matching_commands("/")
        assert matches[0]["group"] == "Chat"

    @patch("ollama_chat_lib.terminal_ui._prompt_toolkit_modules", return_value=None)
    def test_enhanced_prompt_available_false_without_prompt_toolkit(self, mock_modules):
        assert oc.enhanced_prompt_available() is False

    @patch("ollama_chat_lib.terminal_ui._build_prompt_session", return_value=None)
    @patch("ollama_chat_lib.terminal_ui.enhanced_prompt_available", return_value=True)
    def test_read_chat_input_falls_back_when_session_unavailable(self, mock_available, mock_session):
        result = oc.read_chat_input(lambda: "fallback")
        assert result == "fallback"

    @patch("ollama_chat_lib.terminal_ui.enhanced_prompt_available", return_value=True)
    def test_read_chat_input_uses_prompt_session(self, mock_available):
        fake_session = MagicMock()
        fake_session.prompt.return_value = "typed"
        fake_session.default_buffer.text = "/mo"

        with patch("ollama_chat_lib.terminal_ui._build_prompt_session", return_value=fake_session):
            result = oc.read_chat_input(lambda: "fallback", model_name="llama3.2", tools_enabled=True, memory_enabled=False)

        assert result == "typed"
        fake_session.prompt.assert_called_once()
        prompt_kwargs = fake_session.prompt.call_args.kwargs
        assert callable(prompt_kwargs["bottom_toolbar"])
        assert "slash" in prompt_kwargs["bottom_toolbar"]()

    def test_async_slash_completions_work(self):
        from prompt_toolkit.completion import Completion, CompleteEvent
        from prompt_toolkit.document import Document
        from ollama_chat_lib.terminal_ui import SlashCommandCompleter

        async def _collect():
            completer = SlashCommandCompleter(Completion)
            results = []
            async for item in completer.get_completions_async(Document("/mo"), CompleteEvent()):
                results.append(item.text)
            return results

        completions = asyncio.run(_collect())
        assert "/model" in completions
