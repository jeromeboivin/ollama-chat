"""Safety-net tests for LLM core functions BEFORE extraction."""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock

import ollama_chat as oc
from ollama_chat_lib import state


# ── ask_ollama ───────────────────────────────────────────────────────────

class TestAskOllama:

    @patch("ollama_chat_lib.llm_core.ask_ollama_with_conversation", return_value="response")
    def test_delegates_to_ask_ollama_with_conversation(self, mock_ask):
        result = oc.ask_ollama("system", "user", "model")
        assert result == "response"
        mock_ask.assert_called_once()
        args = mock_ask.call_args[0]
        assert len(args[0]) == 2  # system + user messages
        assert args[0][0]["role"] == "system"
        assert args[0][1]["role"] == "user"


# ── generate_tool_response ───────────────────────────────────────────────

class TestGenerateToolResponse:

    @patch("ollama_chat_lib.llm_core.extract_json", return_value=[{"function": {"name": "web_search", "arguments": {"query": "test"}}}])
    @patch("ollama_chat_lib.llm_core.ask_ollama", return_value='[{"function": {"name": "web_search", "arguments": {"query": "test"}}}]')
    def test_generates_tool_calls(self, mock_ask, mock_extract):
        tools = [{"function": {"name": "web_search", "description": "Search", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}]
        result = oc.generate_tool_response("search for cats", tools, "model")
        assert isinstance(result, list)
        assert result[0]["function"]["name"] == "web_search"

    @patch("ollama_chat_lib.llm_core.extract_json", return_value=[])
    @patch("ollama_chat_lib.llm_core.ask_ollama", return_value="[]")
    def test_returns_empty_list_when_no_tools(self, mock_ask, mock_extract):
        result = oc.generate_tool_response("hello", [], "model")
        assert result == []


# ── generate_chain_of_thoughts_system_prompt ─────────────────────────────

class TestGenerateChainOfThoughtsSystemPrompt:

    def test_returns_nonempty_prompt(self):
        result = oc.generate_chain_of_thoughts_system_prompt([])
        assert isinstance(result, str)
        assert len(result) > 100

    def test_includes_tool_names(self):
        tools = [{"function": {"name": "web_search", "description": "Search"}}]
        result = oc.generate_chain_of_thoughts_system_prompt(tools)
        assert "web_search" in result

    def test_includes_vector_db_guidance(self):
        tools = [{"function": {"name": "query_vector_database", "description": "Search DB"}}]
        result = oc.generate_chain_of_thoughts_system_prompt(tools)
        assert "query_vector_database" in result
        assert "collection" in result.lower()


# ── handle_tool_response ─────────────────────────────────────────────────

class TestHandleToolResponse:

    @patch("ollama_chat_lib.llm_core.ask_ollama_with_conversation", return_value="final answer")
    @patch("ollama_chat_lib.llm_core.on_print")
    def test_calls_global_function(self, mock_print, mock_ask, reset_globals):
        state.verbose_mode = False
        state.plugins = []

        tool_call = {"function": {"name": "web_search", "arguments": {"query": "test"}}}
        tools = [{"type": "function", "function": {"name": "web_search", "description": "Search", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "query"}}, "required": ["query"]}}}]

        # web_search is found via globals_fn injected by the monolith wrapper
        with patch.object(oc, "web_search", return_value="search results"):
            result = oc.handle_tool_response(
                [tool_call], True, [], "model", 0.1, None, tools, False
            )
            assert result == "final answer"

    @patch("ollama_chat_lib.llm_core.on_print")
    def test_returns_none_when_tool_not_found(self, mock_print, reset_globals):
        state.verbose_mode = False
        state.plugins = []

        tool_call = {"function": {"name": "nonexistent_tool", "arguments": {}}}
        tools = [{"type": "function", "function": {"name": "nonexistent_tool", "description": "N/A", "parameters": {"type": "object", "properties": {}}}}]

        result = oc.handle_tool_response(
            [tool_call], True, [], "model", 0.1, None, tools, False
        )
        assert result is None


# ── ask_ollama_with_conversation (OpenAI path) ───────────────────────────

class TestAskOllamaWithConversation:

    @patch("ollama_chat_lib.llm_core.is_model_an_ollama_model", return_value=False)
    @patch("ollama_chat_lib.llm_core.ask_openai_with_conversation", return_value=("Hello!", False, True))
    @patch("ollama_chat_lib.llm_core.on_prompt")
    @patch("ollama_chat_lib.llm_core.on_stdout_flush")
    @patch("ollama_chat_lib.llm_core.on_stdout_write")
    def test_openai_path(self, mock_write, mock_flush, mock_prompt, mock_ask_oai, mock_is_ollama, reset_globals):
        state.use_openai = True
        state.syntax_highlighting = False
        state.interactive_mode = False
        conversation = [{"role": "user", "content": "Hi"}]
        result = oc.ask_ollama_with_conversation(conversation, "gpt-4", temperature=0.1)
        assert result == "Hello!"

    @patch("ollama_chat_lib.llm_core.is_model_an_ollama_model", return_value=True)
    @patch("ollama_chat_lib.llm_core.ollama")
    @patch("ollama_chat_lib.llm_core.on_prompt")
    @patch("ollama_chat_lib.llm_core.on_stdout_flush")
    @patch("ollama_chat_lib.llm_core.on_stdout_write")
    @patch("ollama_chat_lib.llm_core.on_llm_token_response")
    def test_ollama_non_streaming_path(self, mock_token, mock_write, mock_flush, mock_prompt, mock_ollama, mock_is_ollama, reset_globals):
        state.use_openai = False
        state.use_azure_openai = False
        state.syntax_highlighting = False
        state.interactive_mode = False
        state.plugins = []
        state.think_mode_on = False

        # Mock non-streaming response (tools active)
        mock_ollama.chat.return_value = {
            "message": {"content": "Hello from Ollama!", "tool_calls": None}
        }

        conversation = [{"role": "user", "content": "Hi"}]
        tools = [{"type": "function", "function": {"name": "test", "description": "t"}}]
        result = oc.ask_ollama_with_conversation(conversation, "llama3:latest", tools=tools, stream_active=False)
        assert result == "Hello from Ollama!"


# ── ask_openai_with_conversation ─────────────────────────────────────────

class TestAskOpenaiWithConversation:

    def test_non_streaming_basic(self, reset_globals):
        state.verbose_mode = False
        state.use_azure_openai = False
        state.openai_client = MagicMock()

        mock_choice = MagicMock()
        mock_choice.message.content = "OpenAI reply"
        mock_choice.message.tool_calls = None
        mock_choice.finish_reason = "stop"
        state.openai_client.chat.completions.create.return_value = MagicMock(
            choices=[mock_choice]
        )

        conversation = [{"role": "user", "content": "Hi"}]
        result, is_tools, done = oc.ask_openai_with_conversation(
            conversation, "gpt-4", stream_active=False
        )
        assert result == "OpenAI reply"
        assert is_tools is False
        assert done is True

    @patch("ollama_chat.on_print")
    def test_handles_api_error(self, mock_print, reset_globals):
        state.verbose_mode = False
        state.openai_client = MagicMock()
        state.openai_client.chat.completions.create.side_effect = Exception("API Error")

        conversation = [{"role": "user", "content": "Hi"}]
        result, is_tools, done = oc.ask_openai_with_conversation(
            conversation, "gpt-4", stream_active=False
        )
        assert result == ""
        assert done is True
