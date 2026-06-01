"""Model selection helpers – choose / validate Ollama or OpenAI models."""

import ollama
from colorama import Fore, Style

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print, on_stdout_write, on_stdout_flush, on_user_input
from ollama_chat_lib.terminal_ui import prompt_for_single_choice
from ollama_chat_lib.utils import bytes_to_gibibytes


def select_ollama_model_if_available(model_name):
    if not model_name:
        return None
    try:
        models = ollama.list()["models"]
    except Exception:
        on_print("Ollama API is not running.", Fore.RED)
        return None
    for model in models:
        if model["model"] == model_name:
            if state.verbose_mode:
                on_print(f"Selected model: {model_name}", Fore.WHITE + Style.DIM)
            return model_name
    on_print(f"Model {model_name} not found.", Fore.RED)
    return None


def select_openai_model_if_available(model_name):
    if not model_name:
        return None
    try:
        models = state.openai_client.models.list().data
    except Exception as e:
        on_print(f"Failed to fetch OpenAI models: {str(e)}", Fore.RED)
        return None
    models = [m for m in models if m.id.startswith("gpt-") or m.id.startswith("o")]
    for model in models:
        if model.id == model_name:
            if state.verbose_mode:
                on_print(f"Selected model: {model_name}", Fore.WHITE + Style.DIM)
            return model_name
    on_print(f"Model {model_name} not found.", Fore.RED)
    return None


def prompt_for_openai_model(default_model, current_model):
    try:
        models = state.openai_client.models.list().data
    except Exception as e:
        on_print(f"Failed to fetch OpenAI models: {str(e)}", Fore.RED)
        return None
    if current_model is None:
        current_model = default_model
    models = [m for m in models if m.id.startswith("gpt-")]
    options = []
    for model in models:
        description = "Current model" if model.id == current_model else "Available OpenAI model"
        options.append({
            "value": model.id,
            "key": model.id,
            "label": model.id,
            "description": description,
            "group": "OpenAI models",
        })

    selected_model = prompt_for_single_choice(
        "Choose an OpenAI model. Type to filter or press Tab to browse.",
        options,
        default_value=current_model,
        prompt_label="model",
        read_fn=on_user_input,
        print_fn=on_print,
    )
    if state.verbose_mode:
        on_print(f"Selected model: {selected_model}", Fore.WHITE + Style.DIM)
    return selected_model


def prompt_for_ollama_model(default_model, current_model):
    try:
        models = ollama.list()["models"]
    except Exception:
        on_print("Ollama API is not running.", Fore.RED)
        return None
    if current_model is None:
        current_model = default_model
    options = []
    for model in models:
        description = f"Size {bytes_to_gibibytes(model['size'])}"
        if model['model'] == current_model:
            description += " • current model"
        options.append({
            "value": model['model'],
            "key": model['model'],
            "label": model['model'],
            "description": description,
            "group": "Ollama models",
        })

    selected_model = prompt_for_single_choice(
        "Choose a local model. Type to filter or press Tab to browse.",
        options,
        default_value=current_model,
        prompt_label="model",
        read_fn=on_user_input,
        print_fn=on_print,
    )
    if state.verbose_mode:
        on_print(f"Selected model: {selected_model}", Fore.WHITE + Style.DIM)
    return selected_model


def is_model_an_ollama_model(model_name):
    try:
        models = ollama.list()["models"]
    except Exception:
        return False
    for model in models:
        if model["model"] == model_name:
            return True
    return False


def prompt_for_model(default_model, current_model):
    if state.use_openai:
        return prompt_for_openai_model(default_model, current_model)
    else:
        return prompt_for_ollama_model(default_model, current_model)
