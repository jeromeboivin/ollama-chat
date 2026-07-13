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
        expected = {"/help", "/context", "/index", "/reindex", "/verbose", "/search", "/web",
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

    @patch("ollama_chat_lib.terminal_ui.enhanced_prompt_available", return_value=False)
    def test_prompt_for_boolean_setting_keeps_default_on_empty_input(self, mock_available):
        with patch("ollama_chat_lib.run_helpers.on_user_input", return_value=""):
            assert run_helpers.prompt_for_boolean_setting("Chunk large documents?", True) is True
            assert run_helpers.prompt_for_boolean_setting("Chunk large documents?", False) is False

    @patch("ollama_chat_lib.terminal_ui.enhanced_prompt_available", return_value=False)
    def test_prompt_for_indexing_settings_collects_preflight_answers(self, mock_available):
        args = SimpleNamespace(
            chunk_documents=True,
            skip_existing=True,
            document_id_strategy="legacy",
            document_id_namespace=None,
            split_paragraphs=False,
            add_summary=True,
            store_full_docs=False,
            extract_start=None,
            extract_end=None,
        )

        with patch(
            "ollama_chat_lib.run_helpers.on_user_input",
            side_effect=["n", "n", "n", "y", "n", "y", "## Main Code", ""],
        ), patch("ollama_chat_lib.run_helpers.on_print"):
            settings = run_helpers.prompt_for_indexing_settings(args)

        assert settings["chunk_documents"] is False
        assert settings["skip_existing"] is False
        assert settings["document_id_strategy"] == "legacy"
        assert settings["document_id_namespace"] is None
        assert settings["split_paragraphs"] is True
        assert settings["add_summary"] is False
        assert settings["store_full_docs"] is False
        assert settings["extract_start"] == "## Main Code"
        assert settings["extract_end"] is None

    @patch("ollama_chat_lib.terminal_ui.enhanced_prompt_available", return_value=False)
    def test_prompt_for_indexing_settings_collects_collision_safe_namespace(self, mock_available):
        args = SimpleNamespace(
            chunk_documents=False,
            skip_existing=True,
            document_id_strategy="collision-safe",
            document_id_namespace="existing-namespace",
            split_paragraphs=False,
            add_summary=False,
            store_full_docs=False,
            extract_start=None,
            extract_end=None,
        )

        with patch(
            "ollama_chat_lib.run_helpers.on_user_input",
            side_effect=["n", "y", "y", "", "n", "n", "n"],
        ), patch("ollama_chat_lib.run_helpers.on_print"):
            settings = run_helpers.prompt_for_indexing_settings(args)

        assert settings["document_id_strategy"] == "collision-safe"
        assert settings["document_id_namespace"] == "existing-namespace"

    @patch("ollama_chat_lib.terminal_ui.enhanced_prompt_available", return_value=False)
    def test_prompt_for_reindex_settings_omits_skip_existing_prompt(self, mock_available):
        args = SimpleNamespace(
            chunk_documents=False,
            skip_existing=True,
            document_id_strategy="legacy",
            document_id_namespace=None,
            split_paragraphs=False,
            add_summary=True,
            store_full_docs=False,
            extract_start=None,
            extract_end=None,
        )

        with patch(
            "ollama_chat_lib.run_helpers.on_user_input",
            side_effect=["n", "y", "dataset", "n", "n", "n"],
        ), patch("ollama_chat_lib.run_helpers.on_print"):
            settings = run_helpers.prompt_for_reindex_settings(args)

        assert settings["skip_existing"] is False
        assert settings["chunk_documents"] is False
        assert settings["document_id_strategy"] == "collision-safe"
        assert settings["document_id_namespace"] == "dataset"
        assert settings["split_paragraphs"] is False
        assert settings["add_summary"] is False

    def test_resolve_reindex_target_path_reads_inline_path(self):
        with patch("ollama_chat_lib.run_helpers.on_user_input") as mock_input:
            result = run_helpers.resolve_reindex_target_path('/reindex "C:/docs/subset"')

        assert result == "C:/docs/subset"
        mock_input.assert_not_called()

    def test_resolve_reindex_target_path_returns_empty_when_missing(self):
        with patch("ollama_chat_lib.run_helpers.on_user_input") as mock_input:
            result = run_helpers.resolve_reindex_target_path("/reindex")

        assert result == ""
        mock_input.assert_not_called()

    def test_validate_document_identity_settings(self):
        assert run_helpers.validate_document_identity_settings("legacy", None) == ("legacy", None)
        assert run_helpers.validate_document_identity_settings("collision-safe", " dataset ") == (
            "collision-safe",
            "dataset",
        )
        with pytest.raises(ValueError, match="document-id-namespace"):
            run_helpers.validate_document_identity_settings("collision-safe", "")

    def test_default_indexing_settings_uses_args_values(self):
        args = SimpleNamespace(
            chunk_documents=False,
            skip_existing=False,
            document_id_strategy="legacy",
            document_id_namespace=None,
            split_paragraphs=True,
            add_summary=False,
            store_full_docs=True,
            extract_start="## Main Code",
            extract_end=None,
        )

        settings = run_helpers.default_indexing_settings(args)

        assert settings == {
            "chunk_documents": False,
            "skip_existing": False,
            "document_id_strategy": "legacy",
            "document_id_namespace": None,
            "split_paragraphs": True,
            "add_summary": False,
            "store_full_docs": True,
            "extract_start": "## Main Code",
            "extract_end": None,
        }

    def test_resolve_indexing_settings_uses_defaults_when_not_interactive(self):
        args = SimpleNamespace(
            chunk_documents=False,
            skip_existing=False,
            document_id_strategy="legacy",
            document_id_namespace=None,
            split_paragraphs=True,
            add_summary=False,
            store_full_docs=True,
            extract_start="## Main Code",
            extract_end=None,
        )

        with patch("ollama_chat_lib.run_helpers.state.interactive_mode", False), \
             patch("ollama_chat_lib.run_helpers.sys.stdin.isatty", return_value=True), \
             patch("ollama_chat_lib.run_helpers.prompt_for_indexing_settings") as mock_prompt:
            settings = run_helpers.resolve_indexing_settings(args)

        assert settings["extract_start"] == "## Main Code"
        mock_prompt.assert_not_called()

    def test_resolve_indexing_settings_reviews_once_in_interactive_mode(self):
        args = SimpleNamespace(
            chunk_documents=True,
            skip_existing=True,
            document_id_strategy="legacy",
            document_id_namespace=None,
            split_paragraphs=False,
            add_summary=True,
            store_full_docs=False,
            extract_start=None,
            extract_end=None,
        )
        reviewed_settings = {
            "chunk_documents": False,
            "skip_existing": False,
            "document_id_strategy": "legacy",
            "document_id_namespace": None,
            "split_paragraphs": True,
            "add_summary": False,
            "store_full_docs": False,
            "extract_start": "## Main Code",
            "extract_end": None,
        }

        with patch("ollama_chat_lib.run_helpers.state.interactive_mode", True), \
             patch("ollama_chat_lib.run_helpers.sys.stdin.isatty", return_value=True), \
             patch("ollama_chat_lib.run_helpers.prompt_for_boolean_setting", return_value=True), \
             patch("ollama_chat_lib.run_helpers.prompt_for_indexing_settings", return_value=reviewed_settings) as mock_prompt:
            settings = run_helpers.resolve_indexing_settings(args)

        assert settings == reviewed_settings
        mock_prompt.assert_called_once_with(args)

    def test_document_identity_cli_defaults_and_options(self):
        with patch.object(sys, "argv", ["ollama_chat.py"]):
            args = run_helpers.parse_args()
        assert args.document_id_strategy == "legacy"
        assert args.document_id_namespace is None

        with patch.object(sys, "argv", [
            "ollama_chat.py",
            "--document-id-strategy", "collision-safe",
            "--document-id-namespace", "rd-cases",
        ]):
            args = run_helpers.parse_args()
        assert args.document_id_strategy == "collision-safe"
        assert args.document_id_namespace == "rd-cases"


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
        assert "Tab browse" in toolbar
        assert "model llama3.2" in toolbar
        assert "tools" in toolbar
        assert "memory on" in toolbar
        assert "think on" in toolbar

    def test_command_catalog_groups_slash_commands(self):
        commands = oc.command_catalog()
        assert any(entry["group"] == "Chat" and entry["command"] == "/model" for entry in commands)
        assert any(entry["group"] == "Context and Retrieval" and entry["command"] == "/search" for entry in commands)
        assert any(entry["group"] == "Context and Retrieval" and entry["command"] == "/reindex" for entry in commands)
        assert any(entry["group"] == "Workspace and Session" and entry["command"] == "/save" for entry in commands)

    def test_find_matching_commands_supports_fuzzy_search(self):
        matches = oc.find_matching_commands("/mdl")
        assert matches[0]["command"] == "/model"
        assert matches[0]["group"] == "Chat"

    def test_find_matching_commands_keeps_group_order(self):
        matches = oc.find_matching_commands("/")
        assert matches[0]["group"] == "Chat"

    def test_chat_toolbar_surfaces_top_slash_match(self):
        toolbar = oc.format_chat_toolbar("llama3.2", tools_enabled=False, memory_enabled=False, think_enabled=False, command_query="/mdl")
        assert "slash " in toolbar
        assert "top /model" in toolbar

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


class TestChoiceHelpers:

    def test_find_matching_choice_entries_supports_fuzzy_search(self):
        entries = [
            {"value": "llama3:latest", "key": "llama3:latest", "label": "llama3:latest", "description": "Local model", "group": "Models", "aliases": ["llm"], "group_index": 0, "item_index": 0},
            {"value": "qwen:7b", "key": "qwen:7b", "label": "qwen:7b", "description": "Alternative", "group": "Models", "aliases": [], "group_index": 0, "item_index": 1},
        ]

        matches = oc.find_matching_choice_entries("llm", entries)
        assert matches[0]["value"] == "llama3:latest"

    def test_find_matching_choice_entries_prefers_key_over_description(self):
        entries = [
            {"value": "memory", "key": "memory", "label": "Memory", "description": "search", "group": "Modes", "aliases": [], "group_index": 0, "item_index": 0},
            {"value": "search", "key": "search", "label": "Search", "description": "Browse indexed content", "group": "Modes", "aliases": [], "group_index": 0, "item_index": 1},
        ]

        matches = oc.find_matching_choice_entries("search", entries)
        assert matches[0]["value"] == "search"

    def test_format_choice_toolbar_shows_top_match_and_new_hints(self):
        from ollama_chat_lib.terminal_ui import format_choice_toolbar

        entries = [
            {"value": "llama3:latest", "key": "llama3:latest", "label": "llama3:latest", "description": "Local model", "group": "Models", "aliases": [], "group_index": 0, "item_index": 0},
            {"value": "qwen:7b", "key": "qwen:7b", "label": "qwen:7b", "description": "Alternative", "group": "Models", "aliases": [], "group_index": 0, "item_index": 1},
        ]

        toolbar = format_choice_toolbar(entries, default_label="llama3:latest", query_text="qwe")
        assert "top qwen:7b" in toolbar
        assert "Enter accepts top" in toolbar

    @patch("ollama_chat_lib.terminal_ui.enhanced_prompt_available", return_value=False)
    def test_prompt_for_single_choice_uses_fuzzy_match_in_fallback(self, mock_available):
        answers = iter(["llm"])

        result = oc.prompt_for_single_choice(
            "Choose a model",
            [
                {"value": "llama3:latest", "key": "llama3:latest", "label": "llama3:latest", "description": "Local model", "group": "Models"},
                {"value": "qwen:7b", "key": "qwen:7b", "label": "qwen:7b", "description": "Alternative", "group": "Models"},
            ],
            default_value="llama3:latest",
            prompt_label="model",
            read_fn=lambda prompt=None: next(answers),
            print_fn=lambda *args, **kwargs: None,
        )

        assert result == "llama3:latest"

    @patch("ollama_chat_lib.terminal_ui.enhanced_prompt_available", return_value=False)
    def test_prompt_for_multiple_choice_toggles_and_returns_selection(self, mock_available):
        answers = iter(["web, read", ""])
        web_tool = {"function": {"name": "web_search"}}
        read_tool = {"function": {"name": "read_file"}}

        result = oc.prompt_for_multiple_choice(
            "Choose tools",
            [
                {"value": web_tool, "key": "web_search", "label": "web_search", "description": "Search the web", "group": "Built-in tools"},
                {"value": read_tool, "key": "read_file", "label": "read_file", "description": "Read a file", "group": "Built-in tools"},
            ],
            selected_values=[],
            prompt_label="tools",
            read_fn=lambda prompt=None: next(answers),
            print_fn=lambda *args, **kwargs: None,
        )

        assert web_tool in result
        assert read_tool in result

    @patch("ollama_chat_lib.terminal_ui.enhanced_prompt_available", return_value=False)
    def test_prompt_for_confirmation_uses_default_on_empty_input(self, mock_available):
        answers = iter([""])

        result = oc.prompt_for_confirmation(
            "Delete collection?",
            default=True,
            read_fn=lambda prompt=None: next(answers),
            print_fn=lambda *args, **kwargs: None,
        )

        assert result is True
