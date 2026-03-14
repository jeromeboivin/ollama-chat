"""Tests for small utility functions."""
import os
import json
import pytest
from unittest.mock import patch, MagicMock
import ollama_chat as oc


# ── completer ────────────────────────────────────────────────────────────────

class TestCompleter:

    def test_matching_commands(self):
        # COMMANDS order: /context, /cot, /collection, ...
        assert oc.completer("/co", 0) == "/context"
        assert oc.completer("/co", 1) == "/cot"
        assert oc.completer("/co", 2) == "/collection"

    def test_no_match(self):
        assert oc.completer("/zzz", 0) is None

    def test_state_out_of_range(self):
        assert oc.completer("/quit", 1) is None  # only one match

    def test_empty_prefix(self):
        result = oc.completer("/", 0)
        assert result is not None


# ── get_builtin_tool_names ───────────────────────────────────────────────────

class TestGetBuiltinToolNames:

    def test_returns_list(self):
        names = oc.get_builtin_tool_names()
        assert isinstance(names, list)
        assert "web_search" in names
        assert "query_vector_database" in names
        assert "retrieve_relevant_memory" in names

    def test_no_plugin_tools(self):
        names = oc.get_builtin_tool_names()
        # Plugin tools have user-defined names, so none of the builtins should
        # match common plugin patterns
        for name in names:
            assert "plugin" not in name.lower()


# ── requires_plugins ─────────────────────────────────────────────────────────

class TestRequiresPlugins:

    def test_empty_list(self):
        assert oc.requires_plugins([]) is False

    def test_none(self):
        assert oc.requires_plugins(None) is False

    def test_builtin_only(self):
        assert oc.requires_plugins(["web_search", "query_vector_database"]) is False

    def test_plugin_tool(self):
        assert oc.requires_plugins(["web_search", "my_custom_plugin_tool"]) is True

    def test_strips_whitespace_and_quotes(self):
        assert oc.requires_plugins(["  'web_search'  "]) is False
        assert oc.requires_plugins(['  "custom_tool"  ']) is True


# ── select_tool_by_name ──────────────────────────────────────────────────────

class TestSelectToolByName:

    def _make_tool(self, name):
        return {"function": {"name": name, "description": f"desc of {name}"}}

    def test_selects_existing_tool(self, reset_globals):
        oc = reset_globals
        available = [self._make_tool("web_search"), self._make_tool("my_tool")]
        selected = []
        result = oc.select_tool_by_name(available, selected, "my_tool")
        assert any(t["function"]["name"] == "my_tool" for t in result)

    def test_case_insensitive(self, reset_globals):
        oc = reset_globals
        available = [self._make_tool("Web_Search")]
        selected = []
        result = oc.select_tool_by_name(available, selected, "web_search")
        assert len(result) == 1

    def test_already_selected(self, reset_globals):
        oc = reset_globals
        tool = self._make_tool("web_search")
        available = [tool]
        selected = [tool]
        result = oc.select_tool_by_name(available, selected, "web_search")
        assert len(result) == 1  # not duplicated

    def test_not_found(self, reset_globals):
        oc = reset_globals
        available = [self._make_tool("web_search")]
        selected = []
        result = oc.select_tool_by_name(available, selected, "nonexistent")
        assert len(result) == 0


# ── find_latest_user_message ─────────────────────────────────────────────────

class TestFindLatestUserMessage:

    def test_basic(self):
        conv = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "bye"},
        ]
        assert oc.find_latest_user_message(conv) == "bye"

    def test_no_user_message(self):
        conv = [{"role": "system", "content": "sys"}]
        assert oc.find_latest_user_message(conv) is None

    def test_empty_conversation(self):
        assert oc.find_latest_user_message([]) is None


# ── extract_json ─────────────────────────────────────────────────────────────

class TestExtractJson:

    def test_plain_json_object(self):
        result = oc.extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_plain_json_array(self):
        result = oc.extract_json('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_json_in_markdown_fence(self):
        text = 'Here is the result:\n```json\n[{"a": 1}]\n```\nDone.'
        result = oc.extract_json(text)
        assert result == [{"a": 1}]

    def test_json_with_surrounding_garbage(self):
        text = 'Some text {"name": "test"} more text'
        result = oc.extract_json(text)
        assert result == {"name": "test"}

    def test_none_input(self):
        assert oc.extract_json(None) == []

    def test_no_json_at_all(self):
        assert oc.extract_json("no json here") == []

    def test_concatenated_json_objects(self):
        text = '{"a": 1}{"b": 2}'
        result = oc.extract_json(text)
        assert isinstance(result, dict)
        assert "a" in result or "b" in result


# ── try_parse_json ───────────────────────────────────────────────────────────

class TestTryParseJson:

    def test_valid(self):
        assert oc.try_parse_json('{"x": 1}') == {"x": 1}

    def test_invalid(self):
        assert oc.try_parse_json("not json") is None

    def test_none_input(self):
        assert oc.try_parse_json(None) is None

    def test_non_string(self):
        assert oc.try_parse_json(42) is None


# ── try_merge_concatenated_json ──────────────────────────────────────────────

class TestTryMergeConcatenatedJson:

    def test_two_dicts(self):
        result = oc.try_merge_concatenated_json('{"a":1}{"b":2}')
        assert result == {"a": 1, "b": 2}

    def test_single_dict(self):
        result = oc.try_merge_concatenated_json('{"a":1}')
        assert result == {"a": 1}

    def test_no_json(self):
        result = oc.try_merge_concatenated_json("no json")
        assert result is None


# ── get_personal_info ────────────────────────────────────────────────────────

class TestGetPersonalInfo:

    def test_returns_dict_with_user_name(self):
        info = oc.get_personal_info()
        assert "user_name" in info
        assert isinstance(info["user_name"], str)


# ── save_conversation_to_file ────────────────────────────────────────────────

class TestSaveConversationToFile:

    def test_saves_txt_and_json(self, tmp_path, reset_globals):
        conv = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        txt_path = str(tmp_path / "conv.txt")
        oc.save_conversation_to_file(conv, txt_path)

        assert os.path.exists(txt_path)
        json_path = txt_path.replace(".txt", ".json")
        assert os.path.exists(json_path)

        with open(txt_path, encoding="utf8") as f:
            text = f.read()
        assert "Me: Hello" in text
        assert "Assistant: Hi there" in text

        with open(json_path, encoding="utf8") as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_filters_system_and_tool_messages(self, tmp_path, reset_globals):
        conv = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
            {"role": "tool", "content": "tool output"},
            {"role": "assistant", "content": "Hello"},
        ]
        txt_path = str(tmp_path / "conv.txt")
        oc.save_conversation_to_file(conv, txt_path)

        with open(txt_path, encoding="utf8") as f:
            text = f.read()
        assert "system" not in text.lower().split(":")[0] if ":" in text else True
        assert "tool output" not in text


# ── render_tools ─────────────────────────────────────────────────────────────

class TestRenderTools:

    def test_basic_render(self):
        tools = [{
            "function": {
                "name": "web_search",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {}}
            }
        }]
        result = oc.render_tools(tools)
        assert "web_search" in result
        assert "Search the web" in result
