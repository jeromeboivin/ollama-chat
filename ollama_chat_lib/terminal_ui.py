"""Interactive terminal presentation helpers."""

import os
import re
import sys

from appdirs import AppDirs
from colorama import Fore, Style

from ollama_chat_lib.constants import APP_AUTHOR, APP_NAME, COMMANDS
from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print, on_user_input


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
            ("/reindex", "Reindex a local file or folder subtree into the vector store."),
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
        return (0, 0, 0, len(candidate_text))

    normalized_query = query_text.lower()
    normalized_candidate = candidate_text.lower()

    if normalized_candidate == normalized_query:
        return (0, 0, 0, len(normalized_candidate))

    if normalized_candidate.startswith(normalized_query):
        return (1, 0, 0, len(normalized_candidate))

    for match in re.finditer(r"[a-z0-9]+", normalized_candidate):
        if match.group(0).startswith(normalized_query):
            return (2, match.start(), 0, len(normalized_candidate))

    contains_at = normalized_candidate.find(normalized_query)
    if contains_at != -1:
        return (3, contains_at, 0, len(normalized_candidate))

    candidate_index = 0
    gaps = 0
    first_match_index = None
    for query_char in normalized_query:
        next_index = normalized_candidate.find(query_char, candidate_index)
        if next_index == -1:
            return None
        if first_match_index is None:
            first_match_index = next_index
        gaps += next_index - candidate_index
        candidate_index = next_index + 1

    return (4, first_match_index or 0, gaps, len(normalized_candidate))


def _rank_candidate_match(query_text, candidate_text, *, field_priority):
    if not candidate_text:
        return None

    fuzzy_score = _fuzzy_score(query_text, candidate_text)
    if fuzzy_score is None:
        return None

    return (fuzzy_score[0], field_priority, fuzzy_score[1], fuzzy_score[2], fuzzy_score[3])


def find_matching_commands(query_text):
    normalized_query = (query_text or "").strip()
    if normalized_query.startswith("/"):
        normalized_query = normalized_query[1:]

    normalized_query = normalized_query.lower()
    if not normalized_query:
        return command_catalog()

    matches = []
    for entry in command_catalog():
        candidate_scores = [
            _rank_candidate_match(normalized_query, entry["command"][1:], field_priority=0),
            _rank_candidate_match(normalized_query, entry["description"], field_priority=2),
            _rank_candidate_match(normalized_query, entry["group"], field_priority=3),
        ]
        candidate_scores = [score for score in candidate_scores if score is not None]

        if normalized_query and not candidate_scores:
            continue

        best_score = min(candidate_scores) if candidate_scores else (0, 0, 0, 0, len(entry["command"]))
        matches.append((
            best_score,
            entry["group_index"],
            entry["item_index"],
            entry,
        ))

    matches.sort(key=lambda item: (item[0], item[1], item[2], item[3]["command"]))
    return [item[3] for item in matches]


def _prepare_choice_entries(options):
    group_order = {}
    entries = []

    for item_index, option in enumerate(options):
        group_name = option.get("group", "Choices")
        if group_name not in group_order:
            group_order[group_name] = len(group_order)

        label = str(option.get("label") or option.get("key") or option.get("value") or "")
        key = str(option.get("key") or option.get("value") or label)
        aliases = [str(alias) for alias in option.get("aliases", []) if alias]

        entries.append({
            "value": option.get("value"),
            "key": key,
            "label": label,
            "description": str(option.get("description", "")),
            "group": group_name,
            "aliases": aliases,
            "group_index": group_order[group_name],
            "item_index": item_index,
        })

    return entries


def find_matching_choice_entries(query_text, entries):
    normalized_query = (query_text or "").strip().lower()
    if not normalized_query:
        return list(entries)

    matches = []
    for entry in entries:
        candidate_scores = [
            _rank_candidate_match(normalized_query, entry["key"], field_priority=0),
            _rank_candidate_match(normalized_query, entry["label"], field_priority=1),
            *[
                _rank_candidate_match(normalized_query, alias, field_priority=2)
                for alias in entry["aliases"]
            ],
            _rank_candidate_match(normalized_query, entry["description"], field_priority=4),
            _rank_candidate_match(normalized_query, entry["group"], field_priority=5),
        ]
        candidate_scores = [score for score in candidate_scores if score is not None]

        if not candidate_scores:
            continue

        best_score = min(candidate_scores)
        matches.append((best_score, entry["group_index"], entry["item_index"], entry))

    matches.sort(key=lambda item: (item[0], item[1], item[2], item[3]["label"]))
    return [item[3] for item in matches]


def _find_default_choice_entry(entries, default_value=None):
    if default_value is None:
        return entries[0] if entries else None

    default_value_str = str(default_value)
    for entry in entries:
        if entry["value"] == default_value or entry["key"] == default_value_str or entry["label"] == default_value_str:
            return entry
    return entries[0] if entries else None


def _resolve_choice_entry(user_input, entries, default_entry=None):
    normalized_input = (user_input or "").strip()
    if not normalized_input:
        return default_entry

    if normalized_input.isdigit():
        numeric_choice = int(normalized_input)
        if numeric_choice == 0 and entries:
            return entries[0]
        index = numeric_choice - 1
        if 0 <= index < len(entries):
            return entries[index]

    lowered_input = normalized_input.lower()
    for entry in entries:
        exact_candidates = [entry["key"], entry["label"], *entry["aliases"]]
        if any(lowered_input == candidate.lower() for candidate in exact_candidates if candidate):
            return entry

    matches = find_matching_choice_entries(normalized_input, entries)
    return matches[0] if matches else None


def _summarize_selected_labels(selected_labels, max_items=3):
    labels = [label for label in selected_labels if label]
    if not labels:
        return "none"
    if len(labels) <= max_items:
        return ", ".join(labels)
    return ", ".join(labels[:max_items]) + f" +{len(labels) - max_items}"


def _format_match_count(match_count):
    return f"{match_count} match" if match_count == 1 else f"{match_count} matches"


def format_choice_toolbar(entries, *, default_label=None, selected_labels=None, query_text=None, allow_multiple=False):
    query_text = (query_text or "").strip()
    matches = find_matching_choice_entries(query_text, entries) if query_text else list(entries)
    match_count = len(matches)

    status_parts = [_format_match_count(match_count)]
    top_match_label = matches[0]["label"] if query_text and matches else None
    if allow_multiple:
        selected_summary = _summarize_selected_labels(selected_labels or [])
        status_parts.insert(0, f"selected {len(selected_labels or [])}: {selected_summary}")
        if top_match_label:
            status_parts.append(f"top {top_match_label}")
        hint_parts = ["type to narrow", "Tab browse", "Enter toggles top", "blank done"]
    else:
        if default_label:
            status_parts.insert(0, f"default {default_label}")
        if top_match_label:
            status_parts.append(f"top {top_match_label}")
        hint_parts = ["type to narrow", "Tab browse", "Enter accepts top", "blank keeps default" if default_label else "blank keeps current"]

    return "  |  ".join(status_parts + hint_parts)


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
        command_matches = find_matching_commands(command_query)
        status_parts.append(f"slash {_format_match_count(len(command_matches))}")
        stripped_query = command_query.strip()
        if stripped_query not in {"", "/"} and command_matches:
            status_parts.append(f"top {command_matches[0]['command']}")

    hint_parts = ["Enter send", "Alt+Enter newline", "Tab browse", "Up history"]
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
                display=f"{entry['command']:<19} {entry['group']}",
                display_meta=entry["description"],
            )

    async def get_completions_async(self, document, complete_event):
        for completion in self.get_completions(document, complete_event):
            yield completion


class ChoicePromptCompleter:
    def __init__(self, completion_cls, entries, selected_keys_getter=None):
        self._completion_cls = completion_cls
        self._entries = list(entries)
        self._selected_keys_getter = selected_keys_getter

    def _display_label(self, entry):
        prefix = ""
        if self._selected_keys_getter is not None and entry["key"] in self._selected_keys_getter():
            prefix = "[x] "
        return f"{prefix}{entry['label']}"

    def _display_meta(self, entry):
        meta_parts = [entry["group"]]
        if entry["description"]:
            meta_parts.append(entry["description"])
        if entry["aliases"]:
            meta_parts.append(f"aliases: {', '.join(entry['aliases'])}")
        return " | ".join(meta_parts)

    def get_completions(self, document, complete_event):
        query_text = document.text_before_cursor.strip()
        for entry in find_matching_choice_entries(query_text, self._entries):
            yield self._completion_cls(
                text=entry["key"],
                start_position=-len(query_text),
                display=self._display_label(entry),
                display_meta=self._display_meta(entry),
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


def prompt_for_single_choice(message, options, *, default_value=None, prompt_label="select", read_fn=on_user_input, print_fn=on_print):
    entries = _prepare_choice_entries(options)
    if not entries:
        return None

    default_entry = _find_default_choice_entry(entries, default_value)

    if not enhanced_prompt_available():
        print_fn(message, Fore.WHITE + Style.DIM)
        for index, entry in enumerate(entries, start=1):
            default_marker = " (default)" if default_entry and entry["key"] == default_entry["key"] else ""
            description = f" - {entry['description']}" if entry["description"] else ""
            print_fn(f"{index}. {entry['label']}{description}{default_marker}")
        choice = read_fn(f"{prompt_label.capitalize()} [{entries.index(default_entry) + 1 if default_entry else 1}]: ")
        resolved_entry = _resolve_choice_entry(choice, entries, default_entry)
        return resolved_entry["value"] if resolved_entry else None

    prompt_modules = _prompt_toolkit_modules()
    prompt_session = _build_prompt_session()
    if prompt_modules is None or prompt_session is None:
        return read_fn(f"{prompt_label.capitalize()}: ")

    print_fn(message, Fore.WHITE + Style.DIM)
    completer = ChoicePromptCompleter(prompt_modules["Completion"], entries)

    while True:
        def _toolbar_text():
            buffer_text = getattr(prompt_session.default_buffer, "text", "") or ""
            return format_choice_toolbar(
                entries,
                default_label=default_entry["label"] if default_entry else None,
                query_text=buffer_text,
            )

        user_input = prompt_session.prompt(
            [("class:prompt", f"\n{prompt_label}> ")],
            completer=completer,
            complete_while_typing=True,
            reserve_space_for_menu=min(max(len(entries), 6), 12),
            bottom_toolbar=_toolbar_text,
        )

        resolved_entry = _resolve_choice_entry(user_input, entries, default_entry)
        if resolved_entry is not None:
            return resolved_entry["value"]

        error_message, error_style = format_status("No matching option. Type to filter or press Tab to browse.", "error")
        print_fn(error_message, error_style)


def prompt_for_multiple_choice(message, options, *, selected_values=None, prompt_label="select", read_fn=on_user_input, print_fn=on_print):
    entries = _prepare_choice_entries(options)
    if not entries:
        return []

    selected_values = selected_values or []
    selected_keys = {
        entry["key"]
        for entry in entries
        if entry["value"] in selected_values or entry["key"] in {str(value) for value in selected_values}
    }

    if not enhanced_prompt_available():
        print_fn(message, Fore.WHITE + Style.DIM)
        while True:
            for index, entry in enumerate(entries, start=1):
                marker = "[x]" if entry["key"] in selected_keys else "[ ]"
                description = f" - {entry['description']}" if entry["description"] else ""
                print_fn(f"{index}. {marker} {entry['label']}{description}")

            user_input = read_fn(f"{prompt_label.capitalize()} (comma-separated, Enter when done): ").strip()
            if not user_input or user_input.lower() == "done":
                return [entry["value"] for entry in entries if entry["key"] in selected_keys]

            for token in [part.strip() for part in user_input.split(",") if part.strip()]:
                resolved_entry = _resolve_choice_entry(token, entries, None)
                if resolved_entry is None:
                    error_message, error_style = format_status(f"No matching option for '{token}'.", "error")
                    print_fn(error_message, error_style)
                    continue
                if resolved_entry["key"] in selected_keys:
                    selected_keys.remove(resolved_entry["key"])
                else:
                    selected_keys.add(resolved_entry["key"])

    prompt_modules = _prompt_toolkit_modules()
    prompt_session = _build_prompt_session()
    if prompt_modules is None or prompt_session is None:
        return selected_values

    print_fn(message, Fore.WHITE + Style.DIM)
    completer = ChoicePromptCompleter(
        prompt_modules["Completion"],
        entries,
        selected_keys_getter=lambda: selected_keys,
    )

    while True:
        def _toolbar_text():
            buffer_text = getattr(prompt_session.default_buffer, "text", "") or ""
            selected_labels = [entry["label"] for entry in entries if entry["key"] in selected_keys]
            return format_choice_toolbar(
                entries,
                selected_labels=selected_labels,
                query_text=buffer_text,
                allow_multiple=True,
            )

        user_input = prompt_session.prompt(
            [("class:prompt", f"\n{prompt_label}> ")],
            completer=completer,
            complete_while_typing=True,
            reserve_space_for_menu=min(max(len(entries), 6), 12),
            bottom_toolbar=_toolbar_text,
        ).strip()

        if not user_input or user_input.lower() == "done":
            return [entry["value"] for entry in entries if entry["key"] in selected_keys]

        normalized_input = user_input.lower()
        if normalized_input in {"all", "*"}:
            selected_keys = {entry["key"] for entry in entries}
            info_message, info_style = format_status("Selected all options.", "success")
            print_fn(info_message, info_style)
            continue
        if normalized_input in {"none", "clear"}:
            selected_keys.clear()
            info_message, info_style = format_status("Cleared the current selection.", "info")
            print_fn(info_message, info_style)
            continue

        resolved_entry = _resolve_choice_entry(user_input, entries, None)
        if resolved_entry is None:
            error_message, error_style = format_status("No matching option. Type to filter or press Tab to browse.", "error")
            print_fn(error_message, error_style)
            continue

        if resolved_entry["key"] in selected_keys:
            selected_keys.remove(resolved_entry["key"])
            info_message, info_style = format_status(f"Removed {resolved_entry['label']}.", "info")
        else:
            selected_keys.add(resolved_entry["key"])
            info_message, info_style = format_status(f"Added {resolved_entry['label']}.", "success")
        print_fn(info_message, info_style)


def prompt_for_confirmation(message, *, default=False, prompt_label="confirm", read_fn=on_user_input, print_fn=on_print):
    if not enhanced_prompt_available():
        default_hint = "Y/n" if default else "y/N"
        response = read_fn(f"{message} [{default_hint}]: ").strip().lower()
        if not response:
            return default
        return response in {"y", "yes"}

    options = [
        {"value": True, "key": "yes", "label": "Yes", "description": "Confirm this action.", "aliases": ["y"], "group": "Confirmation"},
        {"value": False, "key": "no", "label": "No", "description": "Cancel and keep the current state.", "aliases": ["n"], "group": "Confirmation"},
    ]
    return bool(prompt_for_single_choice(message, options, default_value=default, prompt_label=prompt_label, read_fn=read_fn, print_fn=print_fn))