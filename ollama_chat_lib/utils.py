"""Pure utility functions (no dependency on module-level mutable state)."""

import json
import os
import re
import sys


def find_latest_user_message(conversation):
    # Iterate through the conversation list in reverse order
    for message in reversed(conversation):
        if message["role"] == "user":
            return message["content"]
    return None  # If no user message is found

def render_tools(tools):
    """Convert tools into a string format suitable for the system prompt."""
    tool_descriptions = []
    for tool in tools:
        tool_info = f"Tool name: {tool['function']['name']}\nDescription: {tool['function']['description']}\n"
        parameters = json.dumps(tool['function']['parameters'], indent=4)
        tool_info += f"Parameters:\n{parameters}\n"
        tool_descriptions.append(tool_info)
    return "\n".join(tool_descriptions)

def try_parse_json(json_str, verbose=False):
    """Helper function to attempt JSON parsing and return the result if successful."""
    result = None

    if not json_str or not isinstance(json_str, str):
        return result

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError as e:
        if verbose:
            print(f"JSON parsing error: {e}", file=sys.stderr)
        pass

    return result

def try_merge_concatenated_json(json_str, verbose=False):
    """
    Handle concatenated JSON objects (e.g., {"key": "value"}{"key2": "value2"})
    by attempting to extract and merge them intelligently.
    """
    if verbose:
        print(f"[DEBUG] Attempting to parse concatenated JSON: {json_str[:100]}...", file=sys.stderr)
    
    # Try to find and extract individual JSON objects
    json_objects = []
    i = 0
    brace_count = 0
    current_obj = ""
    
    while i < len(json_str):
        char = json_str[i]
        current_obj += char
        
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            
            # When we close a brace and count reaches 0, we have a complete object
            if brace_count == 0 and current_obj.count('{') > 0:
                try:
                    obj = json.loads(current_obj.strip())
                    json_objects.append(obj)
                    if verbose:
                        print(f"[DEBUG] Found JSON object: {obj}", file=sys.stderr)
                    current_obj = ""
                except json.JSONDecodeError:
                    pass
        
        i += 1
    
    if not json_objects:
        if verbose:
            print(f"[DEBUG] No individual JSON objects found in concatenated string", file=sys.stderr)
        return None
    
    # If we have multiple objects, merge them by taking the last (most recent) one
    # or merge them into a single dict if they're all dicts
    if len(json_objects) > 1:
        if verbose:
            print(f"[DEBUG] Found {len(json_objects)} JSON objects, merging...", file=sys.stderr)
        
        # If all are dicts, merge them
        if all(isinstance(obj, dict) for obj in json_objects):
            merged = {}
            for obj in json_objects:
                merged.update(obj)
            if verbose:
                print(f"[DEBUG] Merged objects: {merged}", file=sys.stderr)
            return merged
        else:
            # If not all dicts, return the last one (most recent)
            if verbose:
                print(f"[DEBUG] Not all objects are dicts, returning last one: {json_objects[-1]}", file=sys.stderr)
            return json_objects[-1]
    elif len(json_objects) == 1:
        if verbose:
            print(f"[DEBUG] Single JSON object found: {json_objects[0]}", file=sys.stderr)
        return json_objects[0]
    
    return None

def bytes_to_gibibytes(bytes):
    gigabytes = bytes / (1024 ** 3)
    return f"{gigabytes:.1f} GB"

def get_personal_info():
    personal_info = {}
    user_name = os.getenv('USERNAME') or os.getenv('USER') or ""
    
    # Attempt to read the username from .gitconfig file
    gitconfig_path = os.path.expanduser("~/.gitconfig")
    if os.path.exists(gitconfig_path):
        with open(gitconfig_path, 'r') as f:
            lines = f.readlines()
            for line in lines:
                if line.strip().startswith('name'):
                    user_name = line.split('=')[1].strip()
                    break
    
    personal_info['user_name'] = user_name
    return personal_info


def extract_json(garbage_str, verbose=None, log_fn=None):
    """Extract JSON from a string that may contain surrounding non-JSON text.

    Parameters
    ----------
    verbose : bool | None
        When *None* (default) the function tries ``state.verbose_mode``.
    log_fn : callable | None
        Logging callback; when *None* falls back to ``io_hooks.on_print``.
    """
    # Lazy imports to avoid circular deps at module level
    if verbose is None:
        from ollama_chat_lib import state
        verbose = state.verbose_mode
    if log_fn is None:
        from ollama_chat_lib.io_hooks import on_print
        from colorama import Fore, Style
        log_fn = lambda msg, style="": on_print(msg, style)
    else:
        from colorama import Fore, Style

    if garbage_str is None:
        return []

    # First, try to parse the entire input as JSON directly
    result = try_parse_json(garbage_str, verbose=verbose)
    if result is not None:
        return result

    json_str = None

    if "```json" not in garbage_str:
        # Find the first curly brace or square bracket
        start_index = garbage_str.find("[")
        if start_index == -1:
            start_index = garbage_str.find("{")

        last_index = garbage_str.rfind("]")
        if last_index == -1:
            last_index = garbage_str.rfind("}")

        if start_index != -1 and last_index != -1:
            json_str = garbage_str[start_index:last_index + 1]

            if "\n" in json_str:
                last_index = json_str.rfind("]")
                if last_index == -1:
                    last_index = json_str.rfind("}")
                json_str = json_str[:last_index + 1]

    if not json_str:
        pattern = r'```json\s*(\[\s*.*?\s*\])\s*```'
        match = re.search(pattern, garbage_str, re.DOTALL)
        if match:
            json_str = match.group(1)

    if not json_str:
        pattern = r'<tool_call>\s*(\[\s*.*?\s*\])\s*</tool_call>'
        match = re.search(pattern, garbage_str, re.DOTALL)
        if match:
            json_str = match.group(1)

    if json_str:
        json_str = json_str.strip()
        lines = json_str.splitlines()
        stripped_lines = [line.strip() for line in lines if line.strip()]
        json_str = ''.join(stripped_lines)
        json_str = re.sub(r'"\s*"', '","', json_str)
        json_str = re.sub(r'"\s*{', '",{', json_str)
        json_str = re.sub(r'}\s*"', '},"', json_str)

        if verbose:
            log_fn(f"Extracted JSON: '{json_str}'", Fore.WHITE + Style.DIM)
        result = try_parse_json(json_str, verbose=verbose)
        if result is not None:
            return result

        if verbose:
            log_fn(f"[DEBUG] Initial JSON parsing failed, attempting to handle concatenated JSON objects", Fore.CYAN + Style.DIM)

        merged_result = try_merge_concatenated_json(json_str, verbose=verbose)
        if merged_result is not None:
            return merged_result

        if verbose:
            log_fn("Extracted string is not a valid JSON.", Fore.RED)
    else:
        if verbose:
            log_fn("Extracted string is not a valid JSON.", Fore.RED)

    return []
