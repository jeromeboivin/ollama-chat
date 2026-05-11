"""Tests for CLI argument parsing (the argparse inside run())."""
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
        expected = {"/context", "/index", "/verbose", "/search", "/web",
                    "/model", "/tools", "/load", "/save", "/quit", "/exit",
                    "/bye", "/collection", "/memory", "/remember", "/think"}
        assert expected.issubset(set(oc.COMMANDS))

    def test_default_globals(self):
        """Default values of key globals are sane."""
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
