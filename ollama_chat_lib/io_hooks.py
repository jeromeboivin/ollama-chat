"""I/O hook functions that delegate to plugins or fall back to system I/O."""
import sys

from ollama_chat_lib import state
from ollama_chat_lib.constants import COMMANDS


def completer(text, match_index):
    """Autocomplete function for readline."""
    options = [cmd for cmd in COMMANDS if cmd.startswith(text)]
    if match_index < len(options):
        return options[match_index]
    return None


def on_user_input(input_prompt=None):
    for plugin in state.plugins:
        if hasattr(plugin, "on_user_input") and callable(getattr(plugin, "on_user_input")):
            plugin_response = getattr(plugin, "on_user_input")(input_prompt)
            if plugin_response:
                return plugin_response

    if input_prompt:
        return input(input_prompt)
    else:
        return input()


def on_print(message, style="", prompt=""):
    function_handled = False
    for plugin in state.plugins:
        if hasattr(plugin, "on_print") and callable(getattr(plugin, "on_print")):
            plugin_response = getattr(plugin, "on_print")(message)
            function_handled = function_handled or plugin_response

    if not function_handled:
        if style or prompt:
            print(f"{style}{prompt}{message}")
        else:
            print(message)


def on_stdout_write(message, style="", prompt=""):
    function_handled = False
    for plugin in state.plugins:
        if hasattr(plugin, "on_stdout_write") and callable(getattr(plugin, "on_stdout_write")):
            plugin_response = getattr(plugin, "on_stdout_write")(message)
            function_handled = function_handled or plugin_response

    if not function_handled:
        if style or prompt:
            sys.stdout.write(f"{style}{prompt}{message}")
        else:
            sys.stdout.write(message)


def on_llm_token_response(token, style="", prompt=""):
    function_handled = False
    for plugin in state.plugins:
        if hasattr(plugin, "on_llm_token_response") and callable(getattr(plugin, "on_llm_token_response")):
            plugin_response = getattr(plugin, "on_llm_token_response")(token)
            function_handled = function_handled or plugin_response

    if not function_handled:
        if style or prompt:
            sys.stdout.write(f"{style}{prompt}{token}")
        else:
            sys.stdout.write(token)


def on_llm_thinking_token_response(token, style="", prompt=""):
    function_handled = False
    for plugin in state.plugins:
        if hasattr(plugin, "on_llm_thinking_token_response") and callable(getattr(plugin, "on_llm_thinking_token_response")):
            plugin_response = getattr(plugin, "on_llm_thinking_token_response")(token)
            function_handled = function_handled or plugin_response

    if not function_handled:
        if style or prompt:
            sys.stdout.write(f"{style}{prompt}{token}")
        else:
            sys.stdout.write(token)


def on_prompt(prompt, style=""):
    function_handled = False
    for plugin in state.plugins:
        if hasattr(plugin, "on_prompt") and callable(getattr(plugin, "on_prompt")):
            plugin_response = getattr(plugin, "on_prompt")(prompt)
            function_handled = function_handled or plugin_response

    if not function_handled:
        if style:
            sys.stdout.write(f"{style}{prompt}")
        else:
            sys.stdout.write(prompt)


def on_stdout_flush():
    function_handled = False
    for plugin in state.plugins:
        if hasattr(plugin, "on_stdout_flush") and callable(getattr(plugin, "on_stdout_flush")):
            plugin_response = getattr(plugin, "on_stdout_flush")()
            function_handled = function_handled or plugin_response

    if not function_handled:
        sys.stdout.flush()
