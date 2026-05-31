"""Interactive terminal presentation helpers."""

import os
import sys

from appdirs import AppDirs
from colorama import Fore, Style

from ollama_chat_lib.constants import APP_AUTHOR, APP_NAME, COMMANDS
from ollama_chat_lib import state


_PROMPT_SESSION = None

_COMMAND_GROUPS = [
    (
        "Chat",
        [
            ("/help", "Show the grouped slash-command guide."),
            ("/cot", "Draft chain-of-thought guidance before the final answer."),
            ("/model", "Switch the active model."),
            ("/thinking_model", "Choose the reasoning model."),
            ("/model2", "Set an alternate comparison model."),
            ("/think", "Toggle deeper reasoning mode."),
            ("/chatbot", "Switch chatbot persona and reset the session."),
        ],
    ),
    (
        "Context and Retrieval",
        [
            ("/context", "Change the model context window in k tokens."),
            ("/search", "Query the vector database and answer from matches."),
            ("/web", "Search the web and answer with sources."),
            ("/collection", "Switch the active vector collection."),
            ("/index", "Index a folder or crawled site into the vector store."),
            ("/rmcollection", "Delete a vector collection by name."),
            ("/deletecollection", "Alias for deleting a vector collection."),
            ("/editcollection", "Edit collection metadata."),
        ],
    ),
    (
        "Workspace and Session",
        [
            ("/file", "Attach an image or inline a text file."),
            ("/cb", "Paste clipboard content into the prompt."),
            ("/tools", "Enable or disable available tools."),
            ("/memory", "Toggle long-term memory support."),
            ("/remember", "Save the current conversation to memory."),
            ("/memorize", "Alias for saving the conversation to memory."),
            ("/forget", "Delete the active memory collection."),
            ("/load", "Load a saved conversation JSON file."),
            ("/save", "Save the current conversation transcript."),
            ("/verbose", "Toggle verbose diagnostics."),
            ("/quit", "Exit the chat session."),
            ("/exit", "Alias for exiting the chat session."),
            ("/bye", "Friendly exit alias."),
        ],
    ),
]


_STATUS_STYLES = {
    "info": Fore.WHITE + Style.DIM,
    "success": Fore.GREEN + Style.BRIGHT,
    "warning": Fore.YELLOW + Style.BRIGHT,
    "error": Fore.RED + Style.BRIGHT,
}

_STATUS_ICONS = {
    "info": "•",
    "success": "✓",
    "warning": "!",
    "error": "x",
}


def user_prompt():
    return Fore.CYAN + Style.BRIGHT, "\n> "


def continuation_prompt():
    return Fore.WHITE + Style.DIM, "... "


def _normalize_prompt_name(prompt_name):
    normalized = (prompt_name or "assistant").strip().lower().replace(":", "")
    return normalized or "assistant"


def assistant_stream_prompt(prompt_name="assistant", prompt_color=None):
    normalized = _normalize_prompt_name(prompt_name)
    if normalized in {"alt", "alternate"}:
        return prompt_color or Fore.CYAN + Style.BRIGHT, "\nalt> "
    return prompt_color or Style.RESET_ALL, "\n"


def assistant_render_prompt(prompt_name="assistant"):
    normalized = _normalize_prompt_name(prompt_name)
    if normalized in {"alt", "alternate"}:
        return "\ralt> "
    return "\r"


def thinking_spinner_prompt():
    return Fore.WHITE + Style.DIM, "\rthinking "


def format_status(message, level="info"):
    style = _STATUS_STYLES.get(level, _STATUS_STYLES["info"])
    icon = _STATUS_ICONS.get(level, _STATUS_ICONS["info"])
    return f"{icon} {message}", style


def format_session_hint(model_name=None, tools_enabled=False, memory_enabled=False):
    parts = []
    if model_name:
        parts.append(f"model {model_name}")
    if tools_enabled:
        parts.append("tools on")
    if memory_enabled:
        parts.append("memory on")

    details = " | ".join(parts)
    if details:
        details = f" {details}"

    return format_status(
        f"Ready.{details}  Type /help or ? for commands.",
        "info",
    )


def command_catalog():
    entries = []
    for group_index, (group_name, group_entries) in enumerate(_COMMAND_GROUPS):
        for item_index, (command_name, description) in enumerate(group_entries):
            entries.append({
                "command": command_name,
                "description": description,
                "group": group_name,
                "group_index": group_index,
                "item_index": item_index,
            })

    known_commands = {entry["command"] for entry in entries}
    for item_index, command_name in enumerate(COMMANDS):
        if command_name in known_commands:
            continue
        entries.append({
            "command": command_name,
            "description": "Available slash command.",
            "group": "Other",
            "group_index": len(_COMMAND_GROUPS),
            "item_index": item_index,
        })
    return entries


def _fuzzy_score(query_text, candidate_text):
    if not query_text:
        return (0, 0, len(candidate_text))

    normalized_query = query_text.lower()
    normalized_candidate = candidate_text.lower()

    if normalized_candidate.startswith(normalized_query):
        return (0, 0, len(normalized_candidate))

    contains_at = normalized_candidate.find(normalized_query)
    if contains_at != -1:
        return (1, contains_at, len(normalized_candidate))

    candidate_index = 0
    gaps = 0
    for query_char in normalized_query:
        next_index = normalized_candidate.find(query_char, candidate_index)
        if next_index == -1:
            return None
        gaps += next_index - candidate_index
        candidate_index = next_index + 1

    return (2, gaps, len(normalized_candidate))


def find_matching_commands(query_text):
    normalized_query = (query_text or "").strip()
    if normalized_query.startswith("/"):
        normalized_query = normalized_query[1:]

    normalized_query = normalized_query.lower()
    if not normalized_query:
        return command_catalog()

    matches = []
    for entry in command_catalog():
        command_score = _fuzzy_score(normalized_query, entry["command"][1:])
        description_score = _fuzzy_score(normalized_query, entry["description"])
        group_score = _fuzzy_score(normalized_query, entry["group"])
        candidate_scores = [score for score in (command_score, description_score, group_score) if score is not None]

        if normalized_query and not candidate_scores:
            continue

        best_score = min(candidate_scores) if candidate_scores else (0, 0, len(entry["command"]))
        matches.append((
            best_score,
            entry["group_index"],
            entry["item_index"],
            entry,
        ))

    matches.sort(key=lambda item: (item[0], item[1], item[2], item[3]["command"]))
    return [item[3] for item in matches]


def format_prompt_commands_help():
    sections = ["Slash commands", ""]
    grouped_entries = {}
    for entry in command_catalog():
        grouped_entries.setdefault(entry["group"], []).append(entry)

    for group_name, _ in _COMMAND_GROUPS:
        sections.append(group_name)
        for entry in grouped_entries.get(group_name, []):
            sections.append(f"  {entry['command']:<19} {entry['description']}")
        sections.append("")

    if grouped_entries.get("Other"):
        sections.append("Other")
        for entry in grouped_entries["Other"]:
            sections.append(f"  {entry['command']:<19} {entry['description']}")
        sections.append("")

    sections.extend([
        "Input tips",
        "  ?                   Show this help without leaving the prompt loop.",
        "  End a line with \\ to continue the prompt on the next line.",
        "  Wrap text with \"\"\" ... \"\"\" to keep the legacy multiline flow.",
        "  Start with / to open the slash-command picker with fuzzy search.",
        "  Use --query, --web-search, or --index-documents for non-interactive runs.",
    ])
    return "\n".join(sections)


def format_chat_toolbar(model_name=None, tools_enabled=False, memory_enabled=False, think_enabled=False, command_query=None):
    selected_tools = state.selected_tools if state.selected_tools is not None else []
    tools_active = tools_enabled or bool(selected_tools)
    tool_status = f"tools {len(selected_tools)}" if tools_active else "tools off"
    memory_status = "memory on" if memory_enabled or state.memory_manager else "memory off"
    think_status = "think on" if think_enabled or state.think_mode_on else "think off"
    model_status = f"model {model_name}" if model_name else "model unset"

    status_parts = [model_status, tool_status, memory_status, think_status]
    if command_query and command_query.lstrip().startswith("/"):
        match_count = len(find_matching_commands(command_query))
        status_parts.append(f"slash {match_count} matches")

    hint_parts = ["Enter send", "Alt+Enter newline", "Tab picker", "Up history"]
    return "  |  ".join(status_parts + hint_parts)


def _prompt_toolkit_modules():
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.application import get_app
        from prompt_toolkit.completion import Completion
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.styles import Style as PromptStyle
    except ImportError:
        return None

    return {
        "PromptSession": PromptSession,
        "AutoSuggestFromHistory": AutoSuggestFromHistory,
        "Completion": Completion,
        "Condition": Condition,
        "FileHistory": FileHistory,
        "KeyBindings": KeyBindings,
        "PromptStyle": PromptStyle,
        "get_app": get_app,
    }


def _history_file_path():
    dirs = AppDirs(APP_NAME, APP_AUTHOR or False)
    history_dir = dirs.user_state_dir or dirs.user_data_dir
    os.makedirs(history_dir, exist_ok=True)
    return os.path.join(history_dir, "prompt_history.txt")


def enhanced_prompt_available(input_stream=None, output_stream=None):
    if _prompt_toolkit_modules() is None:
        return False

    active_input = input_stream or sys.stdin
    active_output = output_stream or sys.stdout
    return bool(active_input.isatty() and active_output.isatty())


def _build_key_bindings(key_bindings_cls):
    key_bindings = key_bindings_cls()

    @key_bindings.add("enter")
    def _submit_prompt(event):
        event.current_buffer.validate_and_handle()

    @key_bindings.add("escape", "enter")
    def _insert_newline(event):
        event.current_buffer.insert_text("\n")

    @key_bindings.add("/")
    def _open_command_picker(event):
        buffer = event.current_buffer
        document = buffer.document

        buffer.insert_text("/")
        if not document.text.strip():
            buffer.start_completion(select_first=False)

    return key_bindings


class SlashCommandCompleter:
    def __init__(self, completion_cls):
        self._completion_cls = completion_cls

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return

        command_query = text.split(None, 1)[0]
        for entry in find_matching_commands(command_query):
            yield self._completion_cls(
                text=entry["command"],
                start_position=-len(command_query),
                display=f"{entry['group']:<23} {entry['command']}",
                display_meta=entry["description"],
            )

    async def get_completions_async(self, document, complete_event):
        for completion in self.get_completions(document, complete_event):
            yield completion


def _build_prompt_session():
    global _PROMPT_SESSION

    if _PROMPT_SESSION is not None:
        return _PROMPT_SESSION

    prompt_modules = _prompt_toolkit_modules()
    if prompt_modules is None:
        return None

    prompt_style = prompt_modules["PromptStyle"].from_dict({
        "prompt": "ansicyan bold",
        "continuation": "ansigray",
        "bottom-toolbar": "ansiblack bg:ansibrightblack",
    })

    complete_while_typing = prompt_modules["Condition"](
        lambda: prompt_modules["get_app"]().current_buffer.text.lstrip().startswith("/")
    )

    _PROMPT_SESSION = prompt_modules["PromptSession"](
        history=prompt_modules["FileHistory"](_history_file_path()),
        auto_suggest=prompt_modules["AutoSuggestFromHistory"](),
        completer=SlashCommandCompleter(prompt_modules["Completion"]),
        complete_while_typing=complete_while_typing,
        reserve_space_for_menu=6,
        multiline=True,
        key_bindings=_build_key_bindings(prompt_modules["KeyBindings"]),
        style=prompt_style,
    )
    return _PROMPT_SESSION


def read_chat_input(fallback_read, model_name=None, tools_enabled=False, memory_enabled=False):
    if not enhanced_prompt_available():
        return fallback_read()

    prompt_session = _build_prompt_session()
    if prompt_session is None:
        return fallback_read()

    def _toolbar_text():
        buffer_text = ""
        if hasattr(prompt_session, "default_buffer"):
            buffer_text = getattr(prompt_session.default_buffer, "text", "") or ""

        return format_chat_toolbar(
            model_name=model_name,
            tools_enabled=tools_enabled,
            memory_enabled=memory_enabled,
            think_enabled=state.think_mode_on,
            command_query=buffer_text,
        )

    return prompt_session.prompt(
        [("class:prompt", "\n> ")],
        prompt_continuation=lambda width, line_number, is_soft_wrap: [("class:continuation", "... ")],
        bottom_toolbar=_toolbar_text,
    )