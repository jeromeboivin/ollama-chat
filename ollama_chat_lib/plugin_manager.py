"""Plugin discovery and loading."""
import importlib.util
import inspect
import os

from colorama import Fore, Style

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print


def discover_plugins(plugin_folder=None, load_plugins=True, web_crawler_cls=None):

    if not load_plugins:
        if state.verbose_mode:
            on_print("Plugin loading is disabled.", Fore.YELLOW)
        return []

    if plugin_folder is None:
        # Get the directory of the current script (main program)
        main_dir = os.path.dirname(os.path.abspath(__file__))
        # Default plugin folder named "plugins" in the same directory
        plugin_folder = os.path.join(main_dir, "plugins")
    
    if not os.path.isdir(plugin_folder):
        if state.verbose_mode:
            on_print("Plugin folder does not exist: " + plugin_folder, Fore.RED)
        return []
    
    state.plugins = []
    for filename in os.listdir(plugin_folder):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            module_path = os.path.join(plugin_folder, filename)
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and "plugin" in name.lower():
                    if state.verbose_mode:
                        on_print(f"Discovered class: {name}", Fore.WHITE + Style.DIM)

                    plugin = obj()
                    if web_crawler_cls is not None and hasattr(obj, 'set_web_crawler') and callable(getattr(obj, 'set_web_crawler')):
                        plugin.set_web_crawler(web_crawler_cls)

                    if state.other_instance_url and hasattr(obj, 'set_other_instance_url') and callable(getattr(obj, 'set_other_instance_url')):
                        plugin.set_other_instance_url(state.other_instance_url)

                    if state.listening_port and hasattr(obj, 'set_listening_port') and callable(getattr(obj, 'set_listening_port')):
                        plugin.set_listening_port(state.listening_port)

                    if state.user_prompt and hasattr(obj, 'set_initial_message') and callable(getattr(obj, 'set_initial_message')):
                        plugin.set_initial_message(state.user_prompt)

                    state.plugins.append(plugin)
                    if state.verbose_mode:
                        on_print(f"Discovered plugin: {name}", Fore.WHITE + Style.DIM)
                    if hasattr(obj, 'get_tool_definition') and callable(getattr(obj, 'get_tool_definition')):
                        state.custom_tools.append(obj().get_tool_definition())
                        if state.verbose_mode:
                            on_print(f"Discovered tool: {name}", Fore.WHITE + Style.DIM)
    return state.plugins
