# -*- coding: utf-8 -*-
"""LLM core: OpenAI / Ollama conversation drivers, tool dispatch, agent creation."""

import json
import os
from datetime import datetime
from colorama import Fore, Style
import ollama
import requests

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import (
    on_print, on_stdout_write, on_stdout_flush,
    on_llm_token_response, on_llm_thinking_token_response, on_prompt,
)
from ollama_chat_lib.utils import find_latest_user_message, extract_json, render_tools
from ollama_chat_lib.conversation import encode_file_to_base64_with_mime, print_spinning_wheel
from ollama_chat_lib.model_selection import is_model_an_ollama_model


# ---------------------------------------------------------------------------
# ask_openai_responses_api
# ---------------------------------------------------------------------------

def ask_openai_responses_api(conversation, selected_model=None, temperature=0.1, tools=None):
    """
    Call the Azure OpenAI Responses API endpoint (/openai/v1/responses) to support file uploads.
    This is used when files need to be sent as base64-encoded data.

    Returns:
        Tuple of (bot_response, is_tool_calls, completion_done)
    """

    # Build the input array for the Responses API
    input_messages = []

    for msg in conversation:
        if msg["role"] == "system":
            continue  # Responses API may not support system role directly

        content_array = []

        # Handle file attachments (images or files with base64)
        if "images" in msg and msg["images"]:
            for file_path in msg["images"]:
                try:
                    base64_data = encode_file_to_base64_with_mime(file_path)
                    filename = os.path.basename(file_path)

                    content_array.append({
                        "type": "input_file",
                        "filename": filename,
                        "file_data": base64_data
                    })
                except Exception as e:
                    if state.verbose_mode:
                        on_print(f"Error encoding file {file_path}: {e}", Fore.RED)

        # Add text content
        if "content" in msg and msg["content"]:
            content_array.append({
                "type": "input_text",
                "text": msg["content"]
            })

        if content_array:
            input_messages.append({
                "role": msg["role"],
                "content": content_array
            })

    # Prepare the request
    request_data = {
        "model": selected_model,
        "input": input_messages
    }

    if temperature is not None:
        request_data["temperature"] = temperature

    # Get endpoint and auth from the openai_client
    if state.use_azure_openai:
        base_url = str(state.openai_client.base_url)

        if '/openai/deployments/' in base_url:
            azure_resource = base_url.split('/openai/deployments/')[0]
            endpoint = f"{azure_resource}/openai/v1/responses"
        else:
            base_url = base_url.rstrip('/')
            endpoint = f"{base_url}/openai/v1/responses"

        headers = {
            "Content-Type": "application/json",
            "api-key": state.openai_client.api_key
        }
    else:
        base_url = str(state.openai_client.base_url)
        base_url = base_url.rstrip('/')
        endpoint = f"{base_url}/v1/responses"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {state.openai_client.api_key}"
        }

    if state.verbose_mode:
        on_print(f"\n{'='*80}", Fore.CYAN)
        on_print(f"Responses API Request Details", Fore.CYAN + Style.BRIGHT)
        on_print(f"{'='*80}", Fore.CYAN)
        on_print(f"Endpoint: {endpoint}", Fore.WHITE + Style.DIM)
        on_print(f"\nHeaders:", Fore.YELLOW)
        for key, value in headers.items():
            display_value = value[:20] + "..." if key.lower() in ['api-key', 'authorization'] and len(value) > 20 else value
            on_print(f"  {key}: {display_value}", Fore.WHITE + Style.DIM)
        on_print(f"\nRequest Body:", Fore.YELLOW)
        on_print(json.dumps(request_data, indent=2), Fore.WHITE + Style.DIM)

        curl_headers = " ".join([f'-H "{k}: {v[:20] + "..." if k.lower() in ["api-key", "authorization"] and len(v) > 20 else v}"' for k, v in headers.items()])
        on_print(f"\nEquivalent curl command:", Fore.YELLOW)
        on_print(f"curl -X POST {endpoint} \\", Fore.GREEN)
        on_print(f"  {curl_headers} \\", Fore.GREEN)
        on_print(f"  -d '{json.dumps(request_data)}'", Fore.GREEN)
        on_print(f"{'='*80}\n", Fore.CYAN)

    try:
        response = requests.post(endpoint, headers=headers, json=request_data, timeout=300)

        if state.verbose_mode:
            on_print(f"\n{'='*80}", Fore.CYAN)
            on_print(f"Responses API Response Details", Fore.CYAN + Style.BRIGHT)
            on_print(f"{'='*80}", Fore.CYAN)
            on_print(f"Status Code: {response.status_code}", Fore.YELLOW)
            on_print(f"\nResponse Headers:", Fore.YELLOW)
            for key, value in response.headers.items():
                on_print(f"  {key}: {value}", Fore.WHITE + Style.DIM)

        response.raise_for_status()

        result = response.json()

        if state.verbose_mode:
            on_print(f"\nResponse Body:", Fore.YELLOW)
            on_print(json.dumps(result, indent=2), Fore.WHITE + Style.DIM)
            on_print(f"{'='*80}\n", Fore.CYAN)

        # Parse the response
        if "output" in result and len(result["output"]) > 0:
            last_message = result["output"][-1]

            if "content" in last_message:
                if isinstance(last_message["content"], list):
                    bot_response = ""
                    for content_item in last_message["content"]:
                        if isinstance(content_item, dict) and content_item.get("type") == "output_text":
                            bot_response += content_item.get("text", "")
                        elif isinstance(content_item, str):
                            bot_response += content_item
                else:
                    bot_response = last_message["content"]

                return bot_response, False, True

        on_print(f"Unexpected Responses API structure: {result}", Fore.YELLOW)
        return "", False, True

    except requests.exceptions.RequestException as e:
        on_print(f"Error calling Responses API: {e}", Fore.RED)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                on_print(f"Error details: {json.dumps(error_detail, indent=2)}", Fore.RED)
            except Exception:
                on_print(f"Error response: {e.response.text}", Fore.RED)
        return "", False, True


# ---------------------------------------------------------------------------
# ask_openai_with_conversation
# ---------------------------------------------------------------------------

def ask_openai_with_conversation(conversation, selected_model=None, temperature=0.1, prompt_template=None, stream_active=True, tools=[]):

    if prompt_template == "ChatML":
        for i, message in enumerate(conversation):
            if message["role"] == "system":
                conversation[i]["content"] = "<|im_start|>system\n" + message["content"] + "<|im_end|>"
            elif message["role"] == "user":
                conversation[i]["content"] = "<|im_start|>user\n" + message["content"] + "<|im_end|>"
            elif message["role"] == "assistant":
                conversation[i]["content"] = "<|im_start|>assistant\n" + message["content"] + "<|im_end|>"
        conversation.append({"role": "assistant", "content": "<|im_start|>assistant\n"})

    if prompt_template == "Alpaca":
        for i, message in enumerate(conversation):
            if message["role"] == "system":
                conversation[i]["content"] = "### Instruction:\n" + message["content"]
            elif message["role"] == "user":
                conversation[i]["content"] = "### Input:\n" + message["content"]
        conversation.append({"role": "assistant", "content": "### Response:\n"})

    if len(tools) == 0:
        tools = None

    # Check if any message contains file attachments (images key)
    has_file_attachments = any("images" in msg and msg["images"] for msg in conversation)

    # If files are attached, use the Responses API instead of chat completions
    if has_file_attachments:
        if state.verbose_mode:
            on_print("File attachments detected, using Responses API...", Fore.WHITE + Style.DIM)

        try:
            bot_response, bot_response_is_tool_calls, completion_done = ask_openai_responses_api(
                conversation, selected_model, temperature, tools
            )
            return bot_response, bot_response_is_tool_calls, completion_done
        except Exception as e:
            on_print(f"Error during Responses API call: {e}", Fore.RED)
            return "", False, True

    completion_done = False
    completion = None
    try:
        completion = state.openai_client.chat.completions.create(
            messages=conversation,
            model=selected_model,
            stream=stream_active,
            temperature=temperature,
            tools=tools
        )
    except Exception as e:
        on_print(f"Error during OpenAI completion: {e}", Fore.RED)
        return "", False, True

    bot_response_is_tool_calls = False
    tool_calls = []

    if hasattr(completion, 'choices') and len(completion.choices) > 0 and hasattr(completion.choices[0], 'message') and hasattr(completion.choices[0].message, 'tool_calls'):
        tool_calls = completion.choices[0].message.tool_calls
        if not isinstance(tool_calls, list):
            tool_calls = []

    if len(tool_calls) > 0:
        conversation.append(completion.choices[0].message)

        if state.verbose_mode:
            on_print(f"Tool calls: {tool_calls}", Fore.WHITE + Style.DIM)
        bot_response = tool_calls
        bot_response_is_tool_calls = True

    else:
        if not stream_active:
            bot_response = completion.choices[0].message.content

            if state.verbose_mode:
                on_print(f"Bot response: {bot_response}", Fore.WHITE + Style.DIM)

            if completion.choices[0].finish_reason == 'stop' or completion.choices[0].finish_reason == 'function_call' or completion.choices[0].finish_reason == 'content_filter' or completion.choices[0].finish_reason == 'tool_calls':
                completion_done = True
        else:
            bot_response = ""
            try:
                chunk_count = 0
                for chunk in completion:
                    delta = chunk.choices[0].delta.content

                    if not delta is None:
                        if state.syntax_highlighting and state.interactive_mode:
                            print_spinning_wheel(chunk_count)
                        else:
                            on_llm_token_response(delta, Style.RESET_ALL)
                            on_stdout_flush()
                        bot_response += delta
                    elif isinstance(chunk.choices[0].delta.tool_calls, list) and len(chunk.choices[0].delta.tool_calls) > 0:
                        if isinstance(bot_response, str) and not bot_response_is_tool_calls:
                            bot_response = chunk.choices[0].delta.tool_calls
                            bot_response_is_tool_calls = True
                        elif isinstance(bot_response, list) and bot_response_is_tool_calls:
                            for tool_call, tool_call_index in zip(chunk.choices[0].delta.tool_calls, range(len(chunk.choices[0].delta.tool_calls))):
                                bot_response[tool_call_index].function.arguments += tool_call.function.arguments

                    if chunk.choices[0].finish_reason == 'stop' or chunk.choices[0].finish_reason == 'function_call' or chunk.choices[0].finish_reason == 'content_filter' or chunk.choices[0].finish_reason == 'tool_calls':
                        completion_done = True
                        break

                    chunk_count += 1

                if bot_response_is_tool_calls:
                    conversation.append({"role": "assistant", "tool_calls": bot_response})

            except KeyboardInterrupt:
                completion.close()
            except Exception as e:
                on_print(f"Error during streaming completion: {e}", Fore.RED)
                bot_response = ""
                bot_response_is_tool_calls = False

    if not completion_done and not bot_response_is_tool_calls:
        conversation.append({"role": "assistant", "content": bot_response})

    return bot_response, bot_response_is_tool_calls, completion_done


# ---------------------------------------------------------------------------
# handle_tool_response
# ---------------------------------------------------------------------------

def handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools, stream_active, num_ctx=None, globals_fn=None):
    """Dispatch tool calls from the LLM response.

    Parameters
    ----------
    globals_fn : callable, optional
        A callable that returns the dict of global names to search for tool
        functions.  Defaults to ``None``; callers in the monolith pass
        ``globals`` so that module-level wrappers (web_search, etc.) are
        found.
    """
    tool_found = False
    for tool_call in bot_response:
        if not 'function' in tool_call:
            tool_call = { 'function': tool_call }
            if not 'name' in tool_call['function']:
                continue

        tool_name = tool_call['function']['name']
        for tool in tools:
            if 'type' in tool and tool['type'] == 'function' and 'function' in tool and 'name' in tool['function'] and tool['function']['name'] == tool_name:
                if 'arguments' in tool_call:
                    parameters = tool_call.get('arguments', {})
                else:
                    parameters = tool_call['function'].get('arguments', {})

                tool_response = None

                if state.verbose_mode:
                    on_print(f"[DEBUG] Initial parameters: {parameters}", Fore.CYAN + Style.DIM)
                    on_print(f"[DEBUG] Parameters type: {type(parameters)}", Fore.CYAN + Style.DIM)

                if isinstance(parameters, str):
                    if state.verbose_mode:
                        on_print(f"[DEBUG] Converting string parameters to dict", Fore.CYAN + Style.DIM)
                    try:
                        parameters = extract_json(parameters)
                        if state.verbose_mode:
                            on_print(f"[DEBUG] After extract_json: {parameters} (type: {type(parameters)})", Fore.CYAN + Style.DIM)
                    except Exception as e:
                        if state.verbose_mode:
                            on_print(f"[DEBUG] extract_json failed: {e}, using empty dict", Fore.CYAN + Style.DIM)
                        parameters = {}

                if isinstance(parameters, list):
                    if state.verbose_mode:
                        on_print(f"[DEBUG] Parameters is a list, attempting to convert to dict", Fore.CYAN + Style.DIM)
                    if 'parameters' in tool.get('function', {}) and 'properties' in tool['function']['parameters']:
                        param_names = list(tool['function']['parameters']['properties'].keys())
                        if state.verbose_mode:
                            on_print(f"[DEBUG] Parameter names from tool definition: {param_names}", Fore.CYAN + Style.DIM)
                            on_print(f"[DEBUG] List values: {parameters}", Fore.CYAN + Style.DIM)
                        if len(param_names) > 0 and len(parameters) > 0:
                            parameters = {name: value for name, value in zip(param_names, parameters)}
                            if state.verbose_mode:
                                on_print(f"[DEBUG] Converted list to dict: {parameters}", Fore.CYAN + Style.DIM)
                        else:
                            parameters = {}
                    else:
                        if state.verbose_mode:
                            on_print(f"[DEBUG] No parameter definition found in tool, using empty dict", Fore.CYAN + Style.DIM)
                        parameters = {}
                elif not isinstance(parameters, dict):
                    if state.verbose_mode:
                        on_print(f"[DEBUG] Parameters is {type(parameters)}, converting to empty dict", Fore.CYAN + Style.DIM)
                    parameters = {}

                if state.verbose_mode:
                    on_print(f"[DEBUG] Final parameters before tool call: {parameters} (type: {type(parameters)})", Fore.CYAN + Style.DIM)

                accepted_params = set()
                if 'parameters' in tool.get('function', {}) and 'properties' in tool['function']['parameters']:
                    accepted_params = set(tool['function']['parameters']['properties'].keys())

                if state.verbose_mode and accepted_params:
                    on_print(f"[DEBUG] Accepted parameters from tool definition: {accepted_params}", Fore.CYAN + Style.DIM)

                if accepted_params and isinstance(parameters, dict):
                    original_params = parameters.copy()
                    parameters = {k: v for k, v in parameters.items() if k in accepted_params}

                    if state.verbose_mode and original_params != parameters:
                        on_print(f"[DEBUG] Filtered parameters: removed {set(original_params.keys()) - set(parameters.keys())}", Fore.CYAN + Style.DIM)
                        on_print(f"[DEBUG] Parameters after filtering: {parameters}", Fore.CYAN + Style.DIM)

                # Look up tool in the caller's globals dict
                _globals = globals_fn() if globals_fn else {}
                if tool_name in _globals:
                    if state.verbose_mode:
                        on_print(f"Calling tool function: {tool_name} with parameters: {parameters}", Fore.WHITE + Style.DIM)
                    try:
                        tool_response = _globals[tool_name](**parameters)
                        if state.verbose_mode:
                            on_print(f"Tool response: {tool_response}", Fore.WHITE + Style.DIM)
                        tool_found = True
                    except Exception as e:
                        on_print(f"Error calling tool function: {tool_name} - {e}", Fore.RED + Style.NORMAL)
                else:
                    if state.verbose_mode:
                        on_print(f"Trying to find plugin with function '{tool_name}'...", Fore.WHITE + Style.DIM)
                    for plugin in state.plugins:
                        if hasattr(plugin, tool_name) and callable(getattr(plugin, tool_name)):
                            tool_found = True
                            if state.verbose_mode:
                                on_print(f"Calling tool function: {tool_name} from plugin: {plugin.__class__.__name__} with arguments {parameters}", Fore.WHITE + Style.DIM)

                            try:
                                tool_response = getattr(plugin, tool_name)(**parameters)
                                if state.verbose_mode:
                                    on_print(f"Tool response: {tool_response}", Fore.WHITE + Style.DIM)
                                break
                            except Exception as e:
                                on_print(f"Error calling tool function: {tool_name} - {e}", Fore.RED + Style.NORMAL)

                if not tool_response is None:
                    tool_role = "tool"
                    tool_call_id = tool_call.get('id', 0)

                    if not model_support_tools:
                        tool_role = "user"
                    if isinstance(tool_response, str):
                        if not model_support_tools:
                            latest_user_message = find_latest_user_message(conversation)
                            if latest_user_message:
                                tool_response += "\n" + latest_user_message
                        conversation.append({"role": tool_role, "content": tool_response, "tool_call_id": tool_call_id})
                    else:
                        tool_response_str = json.dumps(tool_response, indent=4)
                        if not model_support_tools:
                            latest_user_message = find_latest_user_message(conversation)
                            if latest_user_message:
                                tool_response_str += "\n" + latest_user_message
                        conversation.append({"role": tool_role, "content": tool_response_str, "tool_call_id": tool_call_id})
    if tool_found:
        bot_response = ask_ollama_with_conversation(conversation, model, temperature, prompt_template, tools=tools, no_bot_prompt=True, stream_active=stream_active, num_ctx=num_ctx, globals_fn=globals_fn)
    else:
        on_print(f"Tools not found", Fore.RED)
        return None

    return bot_response


# ---------------------------------------------------------------------------
# ask_ollama_with_conversation
# ---------------------------------------------------------------------------

def ask_ollama_with_conversation(conversation, model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True, prompt="Bot", prompt_color=None, num_ctx=None, use_think_mode=False, globals_fn=None):

    if state.no_system_role and len(conversation) > 1 and conversation[0]["role"] == "system" and not conversation[0]["content"] is None and not conversation[1]["content"] is None:
        conversation[1]["content"] = conversation[0]["content"] + "\n" + conversation[1]["content"]
        conversation = conversation[1:]

    model_is_an_ollama_model = is_model_an_ollama_model(model)

    if (state.use_openai or state.use_azure_openai) and not model_is_an_ollama_model:
        if state.verbose_mode:
            on_print("Using OpenAI API for conversation generation.", Fore.WHITE + Style.DIM)

    if not state.syntax_highlighting:
        if state.interactive_mode and not no_bot_prompt:
            if prompt_color:
                on_prompt(f"{prompt}: ", prompt_color)
            else:
                on_prompt(f"{prompt}: ", Style.RESET_ALL)
        else:
            if prompt_color:
                on_stdout_write("", prompt_color)
            else:
                on_stdout_write("", Style.RESET_ALL)
        on_stdout_flush()

    model_support_tools = True

    if (state.use_openai or state.use_azure_openai) and not model_is_an_ollama_model:
        completion_done = False

        while not completion_done:
            bot_response, bot_response_is_tool_calls, completion_done = ask_openai_with_conversation(conversation, model, temperature, prompt_template, stream_active, tools)
            if bot_response and bot_response_is_tool_calls:
                bot_response = [json.loads(json.dumps(obj, default=lambda o: vars(o))) for obj in bot_response]

                if state.verbose_mode:
                    on_print(f"Bot response: {bot_response}", Fore.WHITE + Style.DIM)

                bot_response = handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools, stream_active, num_ctx=num_ctx, globals_fn=globals_fn)

                completion_done = True
        if not bot_response is None:
            return bot_response.strip()
        else:
            return None

    bot_response = ""
    bot_thinking_response = ""
    bot_response_is_tool_calls = False
    ollama_options = {"temperature": temperature}
    if num_ctx:
        ollama_options["num_ctx"] = num_ctx

    think = use_think_mode or state.think_mode_on

    if state.verbose_mode and think:
        on_print("Thinking...", Fore.WHITE + Style.DIM)

    try:
        stream = ollama.chat(
            model=model,
            messages=conversation,
            stream=False if len(tools) > 0 else stream_active,
            options=ollama_options,
            tools=tools,
            think=think
        )
    except ollama.ResponseError as e:
        if "does not support tools" in str(e):
            tool_response = generate_tool_response(find_latest_user_message(conversation), tools, model, temperature, prompt_template, num_ctx=num_ctx, globals_fn=globals_fn)

            if not tool_response is None and len(tool_response) > 0:
                bot_response = tool_response
                bot_response_is_tool_calls = True
                model_support_tools = False
            else:
                return ""
        else:
            on_print(f"An error occurred during the conversation: {e}", Fore.RED)
            return ""

    if not bot_response_is_tool_calls:
        try:
            if stream_active and len(tools) == 0:
                if state.alternate_model:
                    on_print(f"Response from model: {model}\n")
                chunk_count = 0
                for chunk in stream:
                    continue_response_generation = True
                    for plugin in state.plugins:
                        if hasattr(plugin, "stop_generation") and callable(getattr(plugin, "stop_generation")):
                            plugin_response = getattr(plugin, "stop_generation")()
                            if plugin_response:
                                continue_response_generation = False
                                break

                    if not continue_response_generation:
                        stream.close()
                        break

                    chunk_count += 1

                    thinking_delta = ""
                    if think:
                        thinking_delta = chunk['message'].get('thinking', '')

                        if thinking_delta is None:
                            thinking_delta = ""
                        else:
                            bot_thinking_response += thinking_delta

                    delta = chunk['message'].get('content', '')

                    if len(bot_response) == 0 and len(thinking_delta) == 0:
                        delta = delta.strip()

                        if len(delta) == 0:
                            continue

                    bot_response += delta

                    if state.syntax_highlighting and state.interactive_mode:
                        print_spinning_wheel(chunk_count)
                    else:
                        if think and len(thinking_delta) > 0:
                            on_llm_thinking_token_response(thinking_delta, Fore.WHITE + Style.DIM)
                        else:
                            on_llm_token_response(delta, Fore.WHITE + Style.NORMAL)
                        on_stdout_flush()

                on_llm_token_response("\n")
                on_stdout_flush()
            else:
                tool_calls = stream['message'].get('tool_calls', [])
                if tool_calls is None:
                    tool_calls = []

                if len(tool_calls) > 0:
                    conversation.append(stream['message'])

                    if state.verbose_mode:
                        on_print(f"Tool calls: {tool_calls}", Fore.WHITE + Style.DIM)
                    bot_response = tool_calls
                    bot_response_is_tool_calls = True
                else:
                    if think:
                        bot_thinking_response = stream['message'].get('thinking', '')
                    bot_response = stream['message']['content']
        except KeyboardInterrupt:
            stream.close()
        except ollama.ResponseError as e:
            on_print(f"An error occurred during the conversation: {e}", Fore.RED)
            return ""

    # Check if the bot response is a tool call object
    if not bot_response_is_tool_calls and bot_response and len(bot_response.strip()) > 0 and bot_response.strip()[0] == "{" and bot_response.strip()[-1] == "}":
        bot_response = [extract_json(bot_response.strip())]
        bot_response_is_tool_calls = True

    if not bot_response_is_tool_calls and bot_response and len(bot_response.strip()) > 0 and bot_response.strip()[0] == "[" and bot_response.strip()[-1] == "]":
        bot_response = extract_json(bot_response.strip())
        bot_response_is_tool_calls = True

    if not bot_response_is_tool_calls and bot_response and len(bot_response.strip()) > 0 and bot_response.startswith("<tool_call>"):
        bot_response = extract_json(bot_response.strip())
        bot_response_is_tool_calls = True

    if bot_response and bot_response_is_tool_calls:
        bot_response = handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools, stream_active, num_ctx=num_ctx, globals_fn=globals_fn)

    if isinstance(bot_response, str):
        return bot_response.strip()
    else:
        return None


# ---------------------------------------------------------------------------
# ask_ollama
# ---------------------------------------------------------------------------

def ask_ollama(system_prompt, user_input, selected_model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True, num_ctx=None, use_think_mode=False, globals_fn=None):
    conversation = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
    return ask_ollama_with_conversation(conversation, selected_model, temperature, prompt_template, tools, no_bot_prompt, stream_active, num_ctx=num_ctx, use_think_mode=use_think_mode, globals_fn=globals_fn)


# ---------------------------------------------------------------------------
# generate_tool_response
# ---------------------------------------------------------------------------

def generate_tool_response(user_input, tools, selected_model, temperature=0.1, prompt_template=None, num_ctx=None, globals_fn=None):
    """Generate a response using Ollama that suggests function calls based on the user input."""

    rendered_tools = render_tools(tools)

    system_prompt = f"""You are an assistant that has access to the following set of tools.
Here are the names and descriptions for each tool:

{rendered_tools}
Given the user input, return your response as a JSON array of objects, each representing a different function call. Each object should have the following structure:
{{"function": {{
"name": A string representing the function's name.
"arguments": An object containing key-value pairs representing the arguments to be passed to the function. }}}}

If no tool is relevant to answer, simply return an empty array: [].
"""

    tool_response = ask_ollama(system_prompt, user_input, selected_model, temperature, prompt_template, no_bot_prompt=True, stream_active=False, num_ctx=num_ctx, globals_fn=globals_fn)

    if state.verbose_mode:
        on_print(f"Tool response: {tool_response}", Fore.WHITE + Style.DIM)

    return extract_json(tool_response)


# ---------------------------------------------------------------------------
# create_new_agent_with_tools
# ---------------------------------------------------------------------------

def create_new_agent_with_tools(system_prompt: str, tools: list[str], agent_name: str, agent_description: str, task: str = None, get_available_tools_fn=None, load_chroma_client_fn=None, agent_cls=None):

    tools = list(set(tools))

    if state.verbose_mode:
        on_print("Agent Creation Parameters:", Fore.WHITE + Style.DIM)
        on_print(f"System Prompt: {system_prompt}", Fore.WHITE + Style.DIM)
        on_print(f"Tools: {tools}", Fore.WHITE + Style.DIM)
        on_print(f"Agent Name: {agent_name}", Fore.WHITE + Style.DIM)
        on_print(f"Agent Description: {agent_description}", Fore.WHITE + Style.DIM)
        if task:
            on_print(f"Task: {task}", Fore.WHITE + Style.DIM)

    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise ValueError("System prompt must be a non-empty string.")
    if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        raise ValueError("Tools must be a list of strings.")
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise ValueError("Agent name must be a non-empty string.")

    agent_tools = []
    available_tools = get_available_tools_fn() if get_available_tools_fn else []
    for tool in tools:
        if tool.startswith("functions."):
            tool = tool.split(".", 1)[1]

        for available_tool in available_tools:
            if tool.lower() == available_tool['function']['name'].lower() and tool.lower() != "instantiate_agent_with_tools_and_process_task" and tool.lower() != "create_new_agent_with_tools":
                agent_tools.append(available_tool)
                break

    if len(agent_tools) == 0:
        agent_tools.clear()

        if load_chroma_client_fn:
            load_chroma_client_fn()

        collections = None
        if state.chroma_client:
            collections = state.chroma_client.list_collections()

        if collections:
            all_tools_are_collections = all(tool in [state.collection.name for state.collection in collections] for tool in tools)
            if all_tools_are_collections:
                query_vector_database_tool = next((tool for tool in available_tools if tool['function']['name'] == 'query_vector_database'), None)
                if query_vector_database_tool:
                    agent_tools.append(query_vector_database_tool)

    system_prompt = f"{system_prompt}\nToday's date is {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}."

    _Agent = agent_cls or type(None)
    agent = _Agent(
        name=agent_name,
        description=agent_description,
        model=state.current_model,
        thinking_model=state.thinking_model,
        system_prompt=system_prompt,
        temperature=0.7,
        tools=agent_tools,
        verbose=state.verbose_mode,
        thinking_model_reasoning_pattern=state.thinking_model_reasoning_pattern
    )

    if task and isinstance(task, str) and task.strip():
        try:
            result = agent.process_task(task, return_intermediate_results=True)
            return result if result else f"Agent '{agent_name}' completed the task but produced no output."
        except Exception as e:
            return f"Error during task processing by agent '{agent_name}': {e}"

    return f"Agent '{agent_name}' has been successfully created with {len(agent_tools)} tool(s): {', '.join([tool['function']['name'] for tool in agent_tools]) if agent_tools else 'none'}. The agent is registered and ready to be used."


# ---------------------------------------------------------------------------
# instantiate_agent_with_tools_and_process_task
# ---------------------------------------------------------------------------

def instantiate_agent_with_tools_and_process_task(task: str, system_prompt: str, tools: list[str], agent_name: str, agent_description: str = None, process_task=True, get_available_tools_fn=None, load_chroma_client_fn=None, agent_cls=None):
    """
    Instantiate an Agent with a given name, system prompt, a list of tools, and solve a given task.

    Parameters:
    - task (str): The task or problem that the agent will solve.
    - system_prompt (str): The system prompt to guide the agent's behavior and approach.
    - tools (list[str]): A list of tools (from a predefined set) that the agent can use.
    - agent_name (str): A unique name for the agent.
    - agent_description (str): A description of the agent's capabilities and purpose.
    - process_task (bool): Whether to process the task immediately after instantiation.

    Returns:
    - str: The final result after the agent processes the task.
    """

    if state.verbose_mode:
        on_print("Agent Instantiation Parameters:", Fore.WHITE + Style.DIM)
        on_print(f"Task: {task}", Fore.WHITE + Style.DIM)
        on_print(f"System Prompt: {system_prompt}", Fore.WHITE + Style.DIM)
        on_print(f"Tools: {tools}", Fore.WHITE + Style.DIM)
        on_print(f"Agent Name: {agent_name}", Fore.WHITE + Style.DIM)
        on_print(f"Agent Description: {agent_description}", Fore.WHITE + Style.DIM)

    if isinstance(tools, str):
        try:
            tools = json.loads(tools)
        except json.JSONDecodeError:
            return "Error: Tools must be a list of strings."
    elif not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        return "Error: Tools must be a list of strings."

    if process_task and not isinstance(task, str) or not task.strip():
        return "Error: Task must be a non-empty string describing the problem or goal."
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        return "Error: System prompt must be a non-empty string."
    if not isinstance(agent_name, str) or not agent_name.strip():
        return "Error: Agent name must be a non-empty string."

    if not agent_description:
        agent_description = f"An AI assistant named {agent_name} with system role: '{system_prompt}'."

    tools = list(set(tools))

    agent_tools = []
    available_tools = get_available_tools_fn() if get_available_tools_fn else []
    for tool in tools:
        if tool.startswith("functions."):
            tool = tool.split(".", 1)[1]

        for available_tool in available_tools:
            if tool.lower() == available_tool['function']['name'].lower() and tool.lower() != "instantiate_agent_with_tools_and_process_task" and tool.lower() != "create_new_agent_with_tools":
                agent_tools.append(available_tool)
                break

    if len(agent_tools) == 0:
        agent_tools.clear()

        if load_chroma_client_fn:
            load_chroma_client_fn()

        collections = None
        if state.chroma_client:
            collections = state.chroma_client.list_collections()

        if collections and len(collections) > 0 and len(tools) > 0:
            all_tools_are_collections = all(tool in [state.collection.name for state.collection in collections] for tool in tools)
            if all_tools_are_collections:
                query_vector_database_tool = next((tool for tool in available_tools if tool['function']['name'] == 'query_vector_database'), None)
                if query_vector_database_tool:
                    agent_tools.append(query_vector_database_tool)

    system_prompt = f"{system_prompt}\nToday's date is {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}."

    _Agent = agent_cls or type(None)
    agent = _Agent(
        name=agent_name,
        description=agent_description,
        model=state.current_model,
        thinking_model=state.thinking_model,
        system_prompt=system_prompt,
        temperature=0.7,
        tools=agent_tools,
        verbose=state.verbose_mode,
        thinking_model_reasoning_pattern=state.thinking_model_reasoning_pattern
    )

    if process_task:
        try:
            result = agent.process_task(task, return_intermediate_results=True)
        except Exception as e:
            return f"Error during task processing: {e}"

        return result

    return agent
