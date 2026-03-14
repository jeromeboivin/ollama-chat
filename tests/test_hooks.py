"""Tests for plugin hook wrapper functions."""
import sys
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO
import ollama_chat as oc
from ollama_chat_lib import state


class TestOnPrint:

    def test_default_print(self, reset_globals, capsys):
        state.plugins = []
        oc.on_print("hello")
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_with_style_and_prompt(self, reset_globals, capsys):
        state.plugins = []
        oc.on_print("world", style=">>", prompt="P:")
        captured = capsys.readouterr()
        assert ">>P:world" in captured.out

    def test_plugin_not_handling(self, reset_globals, dummy_plugin, capsys):
        state.plugins = [dummy_plugin]
        oc.on_print("msg")
        captured = capsys.readouterr()
        # Plugin didn't handle, so default print should fire
        assert "msg" in captured.out
        assert "on_print" in dummy_plugin.calls

    def test_plugin_handling(self, reset_globals, handling_plugin, capsys):
        state.plugins = [handling_plugin]
        oc.on_print("msg")
        captured = capsys.readouterr()
        # Plugin handled it → default print suppressed
        assert "msg" not in captured.out


class TestOnStdoutWrite:

    def test_default_write(self, reset_globals):
        state.plugins = []
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_stdout_write("data")
        assert "data" in buf.getvalue()

    def test_plugin_handling_suppresses(self, reset_globals, handling_plugin):
        state.plugins = [handling_plugin]
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_stdout_write("data")
        assert "data" not in buf.getvalue()


class TestOnLlmTokenResponse:

    def test_default_write(self, reset_globals):
        state.plugins = []
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_llm_token_response("tok")
        assert "tok" in buf.getvalue()

    def test_plugin_intercepts(self, reset_globals, handling_plugin):
        state.plugins = [handling_plugin]
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_llm_token_response("tok")
        assert "tok" not in buf.getvalue()


class TestOnStdoutFlush:

    def test_default_flush(self, reset_globals):
        state.plugins = []
        mock_stdout = MagicMock()
        with patch.object(sys, "stdout", mock_stdout):
            oc.on_stdout_flush()
        mock_stdout.flush.assert_called_once()

    def test_plugin_handling(self, reset_globals, handling_plugin):
        state.plugins = [handling_plugin]
        mock_stdout = MagicMock()
        with patch.object(sys, "stdout", mock_stdout):
            oc.on_stdout_flush()
        mock_stdout.flush.assert_not_called()


class TestOnUserInput:

    def test_default_input(self, reset_globals):
        state.plugins = []
        with patch("builtins.input", return_value="user_text"):
            result = oc.on_user_input("prompt> ")
        assert result == "user_text"

    def test_plugin_intercepts(self, reset_globals, handling_plugin):
        state.plugins = [handling_plugin]
        result = oc.on_user_input("prompt> ")
        assert result == "intercepted"

    def test_plugin_not_intercepting(self, reset_globals, dummy_plugin):
        state.plugins = [dummy_plugin]
        with patch("builtins.input", return_value="typed"):
            result = oc.on_user_input("prompt> ")
        assert result == "typed"

    def test_no_prompt(self, reset_globals):
        state.plugins = []
        with patch("builtins.input", return_value="bare"):
            result = oc.on_user_input()
        assert result == "bare"


class TestOnLlmThinkingTokenResponse:

    def test_default_write(self, reset_globals):
        state.plugins = []
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_llm_thinking_token_response("think")
        assert "think" in buf.getvalue()

    def test_with_style_and_prompt(self, reset_globals):
        state.plugins = []
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_llm_thinking_token_response("t", style="S", prompt="P")
        assert "SPt" in buf.getvalue()

    def test_plugin_intercepts(self, reset_globals):
        class _ThinkPlugin:
            def on_llm_thinking_token_response(self, token):
                return True
        state.plugins = [_ThinkPlugin()]
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_llm_thinking_token_response("tok")
        assert "tok" not in buf.getvalue()

    def test_plugin_not_handling(self, reset_globals, dummy_plugin):
        state.plugins = [dummy_plugin]
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_llm_thinking_token_response("tok")
        assert "tok" in buf.getvalue()


class TestCompleter:

    def test_matches_prefix(self, reset_globals):
        result = oc.completer("/", 0)
        # All commands start with /, so first match should be a command
        assert result is not None
        assert result.startswith("/")

    def test_no_match_returns_none(self, reset_globals):
        result = oc.completer("zzz_nonexistent_", 0)
        assert result is None

    def test_index_out_of_range_returns_none(self, reset_globals):
        result = oc.completer("/", 9999)
        assert result is None

    def test_sequential_indices(self, reset_globals):
        # Collect all matches for "/"
        matches = []
        idx = 0
        while True:
            m = oc.completer("/", idx)
            if m is None:
                break
            matches.append(m)
            idx += 1
        assert len(matches) > 0
        # All should start with "/"
        assert all(m.startswith("/") for m in matches)


class TestOnPrompt:

    def test_default_prompt(self, reset_globals):
        state.plugins = []
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_prompt(">> ")
        assert ">> " in buf.getvalue()

    def test_prompt_with_style(self, reset_globals):
        state.plugins = []
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            oc.on_prompt(">> ", style="S")
        assert "S>> " in buf.getvalue()
