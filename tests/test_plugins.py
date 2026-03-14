"""Tests for plugin discovery and management."""
import os
import pytest
from unittest.mock import patch, MagicMock
import ollama_chat as oc
from ollama_chat_lib import state


class TestDiscoverPlugins:

    def test_no_folder(self, reset_globals, tmp_path):
        """Non-existent folder returns empty list."""
        result = oc.discover_plugins(plugin_folder=str(tmp_path / "nonexistent"))
        assert result == []

    def test_load_plugins_false(self, reset_globals):
        """When load_plugins=False, returns empty."""
        result = oc.discover_plugins(load_plugins=False)
        assert result == []

    def test_discovers_plugin_class(self, reset_globals, tmp_path):
        """A .py file with a class containing 'plugin' in name is discovered."""
        mod = reset_globals
        # Reset custom_tools to track what's added
        state.custom_tools = []

        plugin_code = '''
class SamplePlugin:
    pass
'''
        (tmp_path / "my_module.py").write_text(plugin_code)
        result = oc.discover_plugins(plugin_folder=str(tmp_path))
        assert len(result) == 1
        assert type(result[0]).__name__ == "SamplePlugin"

    def test_ignores_dunder_files(self, reset_globals, tmp_path):
        """Files starting with __ are ignored."""
        (tmp_path / "__init__.py").write_text("class InitPlugin: pass")
        result = oc.discover_plugins(plugin_folder=str(tmp_path))
        assert result == []

    def test_discovers_tool_definition(self, reset_globals, tmp_path):
        """A plugin with get_tool_definition() adds to custom_tools."""
        mod = reset_globals
        state.custom_tools = []

        plugin_code = '''
class MyPlugin:
    def get_tool_definition(self):
        return {
            "type": "function",
            "function": {
                "name": "my_tool",
                "description": "A test tool",
                "parameters": {"type": "object", "properties": {}}
            }
        }
'''
        (tmp_path / "tool_plugin.py").write_text(plugin_code)
        result = oc.discover_plugins(plugin_folder=str(tmp_path))
        assert len(result) == 1
        assert len(state.custom_tools) == 1
        assert state.custom_tools[0]["function"]["name"] == "my_tool"

    def test_sets_web_crawler(self, reset_globals, tmp_path):
        """Plugin with set_web_crawler receives SimpleWebCrawler."""
        mod = reset_globals
        state.custom_tools = []

        plugin_code = '''
class CrawlerPlugin:
    def __init__(self):
        self.crawler_cls = None
    def set_web_crawler(self, cls):
        self.crawler_cls = cls
'''
        (tmp_path / "crawler_plugin.py").write_text(plugin_code)
        result = oc.discover_plugins(plugin_folder=str(tmp_path))
        assert len(result) == 1
        assert result[0].crawler_cls is oc.SimpleWebCrawler

    def test_multiple_plugins_in_one_file(self, reset_globals, tmp_path):
        """Multiple classes with 'plugin' in name are all discovered."""
        mod = reset_globals
        state.custom_tools = []

        plugin_code = '''
class AlphaPlugin:
    pass

class BetaPlugin:
    pass
'''
        (tmp_path / "multi.py").write_text(plugin_code)
        result = oc.discover_plugins(plugin_folder=str(tmp_path))
        assert len(result) == 2

    def test_class_without_plugin_in_name_ignored(self, reset_globals, tmp_path):
        """Classes without 'plugin' in name are not discovered."""
        mod = reset_globals
        state.custom_tools = []

        plugin_code = '''
class Helper:
    pass
class UtilityTool:
    pass
'''
        (tmp_path / "helpers.py").write_text(plugin_code)
        result = oc.discover_plugins(plugin_folder=str(tmp_path))
        assert result == []
