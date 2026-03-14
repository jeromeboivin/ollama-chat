"""Model selection helpers – choose / validate Ollama or OpenAI models."""

import ollama
from colorama import Fore, Style

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print, on_stdout_write, on_stdout_flush, on_user_input
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
    on_print("Available OpenAI models:\n", Style.RESET_ALL)
    for i, model in enumerate(models):
        star = " *" if model.id == current_model else ""
        on_stdout_write(f"{i}. {model.id}{star}\n")
    on_stdout_flush()
    default_choice_index = None
    for i, model in enumerate(models):
        if model.id == current_model:
            default_choice_index = i
            break
    if default_choice_index is None:
        default_choice_index = 0
    choice = int(on_user_input("Enter the number of your preferred model [" + str(default_choice_index) + "]: ") or default_choice_index)
    selected_model = models[choice].id
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
    on_print("Available models:\n", Style.RESET_ALL)
    for i, model in enumerate(models):
        star = " *" if model['model'] == current_model else ""
        on_stdout_write(f"{i}. {model['model']} ({bytes_to_gibibytes(model['size'])}){star}\n")
    on_stdout_flush()
    default_choice_index = None
    for i, model in enumerate(models):
        if model['model'] == current_model:
            default_choice_index = i
            break
    if default_choice_index is None:
        default_choice_index = 0
    choice = int(on_user_input("Enter the number of your preferred model [" + str(default_choice_index) + "]: ") or default_choice_index)
    selected_model = models[choice]['model']
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
