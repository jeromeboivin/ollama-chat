"""Shared fixtures for ollama-chat tests."""
import sys
import os
import json
import pytest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub heavy third-party imports so we can load ollama_chat without them
# ---------------------------------------------------------------------------

def _ensure_stubs():
    """Pre-populate sys.modules with lightweight stubs for packages that may
    not be installed in the test environment and are not needed for unit tests."""
    stubs = [
        "ollama", "chromadb", "colorama", "readline", "appdirs",
        "pygments", "pygments.lexers", "pygments.formatters",
        "ddgs", "bs4", "markdownify", "requests",
        "PyPDF2", "chardet", "rank_bm25", "pptx", "docx", "lxml",
        "lxml.etree", "openpyxl", "tqdm", "pyperclip",
    ]
    for name in stubs:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

# We do NOT call _ensure_stubs() by default – the project's real deps should
# be available.  Uncomment if you want a lighter test env:
# _ensure_stubs()


@pytest.fixture()
def reset_globals():
    """Reset module-level globals in ollama_chat that tests may mutate."""
    import ollama_chat as oc
    from ollama_chat_lib import state

    saved = {}
    names = [
        "plugins", "custom_tools", "selected_tools", "verbose_mode",
        "chroma_client", "collection", "current_model", "use_openai",
        "use_azure_openai", "openai_client", "memory_manager",
        "other_instance_url", "listening_port", "user_prompt",
        "plugins_folder", "interactive_mode", "temperature",
        "session_created_files", "chroma_db_path",
        "chroma_client_host", "chroma_client_port",
    ]
    for n in names:
        saved[n] = getattr(state, n, None)

    yield oc

    for n, v in saved.items():
        setattr(state, n, v)


@pytest.fixture()
def dummy_plugin():
    """Return a minimal plugin object that has common hooks."""
    class _DummyPlugin:
        def __init__(self):
            self.calls = {}

        def on_print(self, message):
            self.calls.setdefault("on_print", []).append(message)
            return False  # not handled

        def on_stdout_write(self, message):
            self.calls.setdefault("on_stdout_write", []).append(message)
            return False

        def on_llm_token_response(self, token):
            self.calls.setdefault("on_llm_token_response", []).append(token)
            return False

        def on_stdout_flush(self):
            self.calls.setdefault("on_stdout_flush", []).append(True)
            return False

        def on_user_input(self, prompt):
            self.calls.setdefault("on_user_input", []).append(prompt)
            return None  # not intercepted

    return _DummyPlugin()


@pytest.fixture()
def handling_plugin():
    """Return a plugin that intercepts/handles every hook (returns True)."""
    class _HandlingPlugin:
        def on_print(self, message):
            return True

        def on_stdout_write(self, message):
            return True

        def on_llm_token_response(self, token):
            return True

        def on_stdout_flush(self):
            return True

        def on_user_input(self, prompt):
            return "intercepted"

    return _HandlingPlugin()
