"""Tests for tool catalog generation and selection."""
import pytest
from unittest.mock import patch, MagicMock
import ollama_chat as oc
from ollama_chat_lib import state


class TestGetAvailableTools:

    def test_returns_default_tools(self, reset_globals):
        mod = reset_globals
        state.chroma_client = MagicMock()
        state.chroma_client.list_collections.return_value = []
        state.selected_tools = []
        state.custom_tools = []

        tools = oc.get_available_tools()
        names = [t["function"]["name"] for t in tools]
        assert "web_search" in names
        assert "query_vector_database" in names
        assert "retrieve_relevant_memory" in names
        assert "instantiate_agent_with_tools_and_process_task" in names
        assert "create_new_agent_with_tools" in names
        assert "summarize_text_file" in names
        assert "read_file" in names
        assert "create_file" in names
        assert "delete_file" in names
        assert "run_command" in names

    def test_includes_custom_tools(self, reset_globals):
        mod = reset_globals
        state.chroma_client = MagicMock()
        state.chroma_client.list_collections.return_value = []
        state.selected_tools = []
        state.custom_tools = [{
            "type": "function",
            "function": {
                "name": "my_plugin_tool",
                "description": "Custom",
                "parameters": {"type": "object", "properties": {}}
            }
        }]

        tools = oc.get_available_tools()
        names = [t["function"]["name"] for t in tools]
        assert "my_plugin_tool" in names

    def test_collections_populate_enum(self, reset_globals):
        mod = reset_globals
        mock_col = MagicMock()
        mock_col.name = "my_docs"
        mock_col.metadata = {"description": "My documents"}
        state.chroma_client = MagicMock()
        state.chroma_client.list_collections.return_value = [mock_col]
        state.selected_tools = []
        state.custom_tools = []

        tools = oc.get_available_tools()
        # Find query_vector_database tool
        qvd = None
        for t in tools:
            if t["function"]["name"] == "query_vector_database":
                qvd = t
                break
        assert qvd is not None
        enum = qvd["function"]["parameters"]["properties"]["collection_name"]["enum"]
        assert "my_docs" in enum

    def test_agent_tool_enum_matches_selected(self, reset_globals):
        mod = reset_globals
        state.chroma_client = MagicMock()
        state.chroma_client.list_collections.return_value = []
        state.custom_tools = []
        state.selected_tools = [{
            "function": {"name": "web_search", "description": "Search"}
        }]

        tools = oc.get_available_tools()
        agent_tool = None
        for t in tools:
            if t["function"]["name"] == "instantiate_agent_with_tools_and_process_task":
                agent_tool = t
                break
        assert agent_tool is not None
        enum = agent_tool["function"]["parameters"]["properties"]["tools"]["items"]["enum"]
        assert "web_search" in enum

    def test_web_cache_and_memory_excluded(self, reset_globals):
        mod = reset_globals
        cols = []
        for name in ["web_cache", "memory", "user_docs"]:
            c = MagicMock()
            c.name = name
            c.metadata = {}
            cols.append(c)
        state.chroma_client = MagicMock()
        state.chroma_client.list_collections.return_value = cols
        state.selected_tools = []
        state.custom_tools = []

        tools = oc.get_available_tools()
        qvd = next(t for t in tools if t["function"]["name"] == "query_vector_database")
        enum = qvd["function"]["parameters"]["properties"]["collection_name"]["enum"]
        assert "web_cache" not in enum
        assert "memory" not in enum
        assert "user_docs" in enum
