# -*- coding: utf-8 -*-
"""
run_helpers.py – decomposed sections of the former monolith run() function.

Every function that lives in the monolith (thin wrappers around extracted
modules) is accessed via the *mod* parameter – the monolith module object
(``sys.modules[__name__]`` when called from ollama_chat.py).
"""

import sys
import os
import re
import json
import readline
import tempfile
import platform
import argparse
from datetime import datetime
from colorama import Fore, Style

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import (
    completer, on_user_input, on_print, on_stdout_write,
    on_prompt, on_stdout_flush,
)
from ollama_chat_lib.conversation import (
    colorize, print_possible_prompt_commands,
    load_additional_chatbots, prompt_for_chatbot,
    save_conversation_to_file,
    DEFAULT_CHATBOTS,
)
from ollama_chat_lib.model_selection import (
    select_ollama_model_if_available, select_openai_model_if_available,
    prompt_for_model,
)
from ollama_chat_lib.vector_db import (
    load_chroma_client, set_current_collection,
    prompt_for_vector_database_collection, delete_collection,
    edit_collection_metadata,
)
from ollama_chat_lib.tools import generate_chain_of_thoughts_system_prompt
from ollama_chat_lib.utils import get_personal_info

if platform.system() == "Windows":
    import win32clipboard
else:
    import pyperclip

def parse_args():
    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")

    # If specified as script named arguments, use the provided ChromaDB client host (--chroma-host) and port (--chroma-port)
    parser = argparse.ArgumentParser(description='Run the Ollama chatbot.')
    parser.add_argument('--list-tools', action='store_true', help='List available tools and exit')
    parser.add_argument('--list-collections', action='store_true', help='List available ChromaDB collections and exit')
    parser.add_argument('--chroma-path', type=str, help='ChromaDB database path', default=None)
    parser.add_argument('--chroma-host', type=str, help='ChromaDB client host', default="localhost")
    parser.add_argument('--chroma-port', type=int, help='ChromaDB client port', default=8000)
    parser.add_argument('--docs-to-fetch-from-chroma', type=int, help="Number of documents to return from the vector database when querying for similar documents", default=state.number_of_documents_to_return_from_vector_db)
    parser.add_argument('--collection', type=str, help='ChromaDB collection name', default=None)
    parser.add_argument('--use-openai', type=bool, help='Use OpenAI API or Llama-CPP', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--use-azure-openai', type=bool, help='Use Azure OpenAI API', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--temperature', type=float, help='Temperature for OpenAI API', default=0.1)
    parser.add_argument('--disable-system-role', type=bool, help='Specify if the selected model does not support the system role, like Google Gemma models', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--prompt-template', type=str, help='Prompt template to use for Llama-CPP', default=None)
    parser.add_argument('--additional-chatbots', type=str, help='Path to a JSON file containing additional chatbots', default=None)
    parser.add_argument('--chatbot', type=str, help='Preferred chatbot personality', default=None)
    parser.add_argument('--verbose', type=bool, help='Enable verbose mode', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--embeddings-model', type=str, help='Sentence embeddings model to use for vector database queries', default=None)
    parser.add_argument('--system-prompt', type=str, help='System prompt message', default=None)
    parser.add_argument('--system-prompt-placeholders-json', type=str, help='A JSON file containing a dictionary of key-value pairs to fill system prompt placeholders', default=None)
    parser.add_argument('--prompt', type=str, help='User prompt message', default=None)
    parser.add_argument('--model', type=str, help='Preferred Ollama model', default=None)
    parser.add_argument('--thinking-model', type=str, help='Alternate model to use for more thoughtful responses, like OpenAI o1 or o3 models', default=None)
    parser.add_argument('--thinking-model-reasoning-pattern', type=str, help='Reasoning pattern used by the thinking model', default=None)
    parser.add_argument('--conversations-folder', type=str, help='Folder to save conversations to', default=None)
    parser.add_argument('--auto-save', type=bool, help='Automatically save conversations to a file at the end of the chat', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--syntax-highlighting', type=bool, help='Use syntax highlighting', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--index-documents', type=str, help='Root folder to index text files', default=None)
    parser.add_argument('--chunk-documents', type=bool, help='Enable chunking for large documents during indexing', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--skip-existing', type=bool, help='Skip indexing of documents that already exist in the collection', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--extract-start', type=str, help='Start string for extracting specific text sections during indexing', default=None)
    parser.add_argument('--extract-end', type=str, help='End string for extracting specific text sections during indexing', default=None)
    parser.add_argument('--split-paragraphs', type=bool, help='Split markdown content into paragraphs during indexing', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--add-summary', type=bool, help='Generate and prepend summaries to document chunks during indexing', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--store-full-docs', type=bool, help='Store full original documents for each chunk during indexing (embeddings still computed from chunks)', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--query', type=str, help='Query the vector database and exit (non-interactive mode)', default=None)
    parser.add_argument('--query-n-results', type=int, help='Number of results to return from vector database query', default=None)
    parser.add_argument('--query-distance-threshold', type=float, help='Distance threshold for filtering query results', default=0.0)
    parser.add_argument('--expand-query', type=bool, help='Expand query for better retrieval', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--interactive', type=bool, help='Use interactive mode', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--plugins-folder', type=str, default=None, help='Path to the plugins folder')
    parser.add_argument('--stream', type=bool, help='Use stream mode for Ollama API', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--output', type=str, help='Output file path', default=None)
    parser.add_argument('--other-instance-url', type=str, help="URL of another ollama_chat instance to connect to", default=None)
    parser.add_argument('--listening-port', type=int, help="Listening port for the current ollama_chat instance", default=8000)
    parser.add_argument('--user-name', type=str, help='User name', default=None)
    parser.add_argument('--anonymous', type=bool, help='Do not use the user name from the environment variables', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--memory', type=str, help='Use memory manager for context management', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--context-window', type=int, help='Ollama context window size, if not specified, the default value is used, which is 2048 tokens', default=None) 
    parser.add_argument('--auto-start', type=bool, help="Start the conversation automatically", default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--tools', type=str, help="List of tools to activate and use in the conversation, separated by commas", default=None)
    parser.add_argument('--memory-collection-name', type=str, help="Name of the memory collection to use for context management", default=state.memory_collection_name)
    parser.add_argument('--long-term-memory-file', type=str, help="Long-term memory file name", default=state.long_term_memory_file)
    parser.add_argument('--disable-plugins', type=bool, help='Disable external plugins to speed up execution (plugins will still be loaded if required by requested tools)', default=False, action=argparse.BooleanOptionalAction)

    # Agent instantiation arguments
    parser.add_argument('--instantiate-agent', type=bool, help='Instantiate an agent with tools and process a task', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--agent-task', type=str, help='Task for the agent to solve', default=None)
    parser.add_argument('--agent-system-prompt', type=str, help='System prompt for the agent', default=None)
    parser.add_argument('--agent-tools', type=str, help='Comma-separated list of tools for the agent', default=None)
    parser.add_argument('--agent-name', type=str, help='Name for the agent', default=None)
    parser.add_argument('--agent-description', type=str, help='Description of the agent', default=None)

    # Web search arguments
    parser.add_argument('--web-search', type=str, help='Perform a web search with the given query and answer using search results', default=None)
    parser.add_argument('--web-search-results', type=int, help='Number of web search results to fetch (default: 5)', default=5)
    parser.add_argument('--web-search-region', type=str, help='Region for web search (default: wt-wt for worldwide)', default='wt-wt')
    parser.add_argument('--web-search-show-intermediate', type=bool, help='Show intermediate results during web search (URLs, crawled content, etc.)', default=False, action=argparse.BooleanOptionalAction)

    args = parser.parse_args()
    return args


def initialize(args, mod):
    """Set up state, select model, handle CLI-only operations. Returns ctx dict or None."""
    default_model = None
    state.prompt_template = None

    state.plugins_folder = args.plugins_folder
    state.verbose_mode = args.verbose
    disable_plugins = args.disable_plugins

    # Automatically disable plugins when using RAG-specific parameters (indexing, querying, or web search)
    # These operations don't need plugins and disabling them speeds up execution
    rag_operations_requested = args.index_documents or args.query or args.web_search
    if rag_operations_requested and not disable_plugins:
        disable_plugins = True
        if state.verbose_mode:
            on_print("Plugins automatically disabled for RAG operations (indexing/querying/web-search).", Fore.YELLOW)

    # Parse requested tool names from command line
    requested_tool_names = args.tools.split(',') if args.tools else []

    # We'll also need to check chatbot tools, but we need to load chatbot config first
    # For now, determine if plugins need to be loaded based on command line tools
    # Plugins are loaded if:
    # 1. --disable-plugins is not set, OR
    # 2. Any requested tool is a plugin tool (not built-in)
    load_plugins_initially = not disable_plugins or mod.requires_plugins(requested_tool_names)

    if state.verbose_mode and disable_plugins and not load_plugins_initially:
        on_print("Plugins are disabled and no plugin tools were requested via command line.", Fore.YELLOW)
    elif state.verbose_mode and disable_plugins and load_plugins_initially:
        on_print("Plugins are disabled but plugin tools were requested. Loading plugins anyway.", Fore.YELLOW)

    # Discover plugins before listing tools
    if args.list_tools:
        # Load plugins first
        state.plugins = mod.discover_plugins(state.plugins_folder, load_plugins=True)  # Always load for --list-tools
        if state.verbose_mode:
            on_print(f"\nDiscovered {len(state.plugins)} plugins")

        tools = mod.get_available_tools()
        on_print("\nAvailable tools:")

        # Split tools into built-in and plugin tools
        builtin_tools = [tool for tool in tools if not any(pt['function']['name'] == tool['function']['name'] for p in state.plugins for pt in ([p.get_tool_definition()] if hasattr(p, 'get_tool_definition') and callable(getattr(p, 'get_tool_definition')) else []))]
        plugin_tools = [tool for tool in tools if tool not in builtin_tools]

        # Print built-in tools
        if builtin_tools:
            on_print("\nBuilt-in tools:")
            for tool in builtin_tools:
                on_print(f"\n{tool['function']['name']}:")
                on_print(f"  Description: {tool['function']['description']}")
                if 'parameters' in tool['function']:
                    if 'properties' in tool['function']['parameters']:
                        on_print("  Parameters:")
                        for param_name, param_info in tool['function']['parameters']['properties'].items():
                            required = param_name in tool['function']['parameters'].get('required', [])
                            on_print(f"    {param_name}{'*' if required else ''}: {param_info['description']}")

        # Print plugin tools
        if plugin_tools:
            on_print("\nPlugin tools:")
            for tool in plugin_tools:
                on_print(f"\n{tool['function']['name']}:")
                on_print(f"  Description: {tool['function']['description']}")
                if 'parameters' in tool['function']:
                    if 'properties' in tool['function']['parameters']:
                        on_print("  Parameters:")
                        for param_name, param_info in tool['function']['parameters']['properties'].items():
                            required = param_name in tool['function']['parameters'].get('required', [])
                            on_print(f"    {param_name}{'*' if required else ''}: {param_info['description']}")

        sys.exit(0)

    # Handle listing collections if requested
    if args.list_collections:
        # Initialize ChromaDB client
        state.chroma_client_host = args.chroma_host
        state.chroma_client_port = args.chroma_port
        state.chroma_db_path = args.chroma_path
        state.verbose_mode = args.verbose

        load_chroma_client()

        if not state.chroma_client:
            on_print("Failed to initialize ChromaDB client.", Fore.RED)
            sys.exit(1)

        try:
            collections = state.chroma_client.list_collections()

            if not collections:
                on_print("\nNo collections found.")
            else:
                on_print(f"\nAvailable ChromaDB collections ({len(collections)}):")
                on_print("=" * 80)

                for state.collection in collections:
                    on_print(f"\nCollection: {state.collection.name}")

                    # Get collection metadata
                    if hasattr(state.collection, 'metadata') and state.collection.metadata:
                        if isinstance(state.collection.metadata, dict):
                            if 'description' in state.collection.metadata:
                                on_print(f"  Description: {state.collection.metadata['description']}")

                            # Print other metadata
                            for key, value in state.collection.metadata.items():
                                if key != 'description':
                                    on_print(f"  {key}: {value}")

                    # Get collection count
                    try:
                        count = state.collection.count()
                        on_print(f"  Documents: {count}")
                    except:
                        pass

                on_print("\n" + "=" * 80)

        except Exception as e:
            on_print(f"Error listing collections: {str(e)}", Fore.RED)
            if state.verbose_mode:
                import traceback
                traceback.print_exc()
            sys.exit(1)

        sys.exit(0)

    preferred_collection_name = args.collection
    state.use_openai = args.use_openai
    state.use_azure_openai = args.use_azure_openai
    state.chroma_client_host = args.chroma_host
    state.chroma_client_port = args.chroma_port
    state.chroma_db_path = args.chroma_path
    state.temperature = args.temperature
    state.no_system_role = bool(args.disable_system_role)
    state.current_collection_name = preferred_collection_name
    state.prompt_template = args.prompt_template
    additional_chatbots_file = args.additional_chatbots
    state.verbose_mode = args.verbose
    initial_system_prompt = args.system_prompt
    system_prompt_placeholders_json = args.system_prompt_placeholders_json
    preferred_model = args.model
    state.thinking_model = args.thinking_model
    state.thinking_model_reasoning_pattern = args.thinking_model_reasoning_pattern
    state.number_of_documents_to_return_from_vector_db = args.docs_to_fetch_from_chroma

    if not state.thinking_model:
        state.thinking_model = preferred_model

    if state.verbose_mode:
        on_print(f"Using thinking model: {state.thinking_model}", Fore.WHITE + Style.DIM)

    conversations_folder = args.conversations_folder
    auto_save = args.auto_save
    state.syntax_highlighting = args.syntax_highlighting
    state.interactive_mode = args.interactive
    state.embeddings_model = args.embeddings_model
    state.plugins_folder = args.plugins_folder
    state.user_prompt = args.prompt
    stream_active = args.stream
    output_file = args.output
    state.other_instance_url = args.other_instance_url
    state.listening_port = args.listening_port
    custom_user_name = args.user_name
    no_user_name = args.anonymous
    use_memory_manager = args.memory
    num_ctx = args.context_window
    auto_start_conversation = args.auto_start
    state.memory_collection_name = args.memory_collection_name
    state.long_term_memory_file = args.long_term_memory_file

    if state.verbose_mode and num_ctx:
        on_print(f"Ollama context window size: {num_ctx}", Fore.WHITE + Style.DIM)

    # Get today's date
    today = f"Today's date is {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}."

    system_prompt_placeholders = {}
    if system_prompt_placeholders_json and os.path.exists(system_prompt_placeholders_json):
        with open(system_prompt_placeholders_json, 'r', encoding="utf8") as f:
            system_prompt_placeholders = json.load(f)

    # If output file already exists, ask user for confirmation to overwrite
    if output_file and os.path.exists(output_file):
        if state.interactive_mode:
            confirmation = on_user_input(f"Output file '{output_file}' already exists. Overwrite? (y/n): ").lower()
            if confirmation != 'y' and confirmation != 'yes':
                on_print("Output file not overwritten.")
                output_file = None
            else:
                # Delete the existing file
                os.remove(output_file)
        else:
            # Delete the existing file
            os.remove(output_file)

    if state.verbose_mode and state.user_prompt:
        on_print(f"User prompt: {state.user_prompt}", Fore.WHITE + Style.DIM)

    # Load additional chatbots from a JSON file to check for tools
    load_additional_chatbots(additional_chatbots_file)

    chatbot = None
    if args.chatbot:
        # Trim the chatbot name to remove any leading or trailing spaces, single or double quotes
        args.chatbot = args.chatbot.strip().strip('\'').strip('\"')
        for bot in state.chatbots:
            if bot["name"] == args.chatbot:
                chatbot = bot
                break
        if chatbot is None:
            on_print(f"Chatbot '{args.chatbot}' not found.", Fore.RED)

        if state.verbose_mode and chatbot and 'name' in chatbot:
            on_print(f"Using chatbot: {chatbot['name']}", Fore.WHITE + Style.DIM)

    if chatbot is None:
        # Load the default chatbot
        chatbot = state.chatbots[0]

    # Now check if chatbot has tools that require plugins
    chatbot_tool_names = chatbot.get("tools", []) if chatbot else []
    all_requested_tools = requested_tool_names + chatbot_tool_names

    # Final determination: load plugins if not disabled OR if any requested tool is a plugin tool
    load_plugins = not disable_plugins or mod.requires_plugins(all_requested_tools)

    if state.verbose_mode and disable_plugins and mod.requires_plugins(chatbot_tool_names):
        on_print("Chatbot requires plugin tools. Loading plugins despite --disable-plugins flag.", Fore.YELLOW)

    state.plugins = mod.discover_plugins(state.plugins_folder, load_plugins=load_plugins)

    if state.verbose_mode:
        on_print(f"Verbose mode: {state.verbose_mode}", Fore.WHITE + Style.DIM)

    # Handle document indexing if requested
    if args.index_documents:
        load_chroma_client()

        if not state.chroma_client:
            on_print("Failed to initialize ChromaDB client. Please specify --chroma-path or --chroma-host/--chroma-port.", Fore.RED)
            sys.exit(1)

        if not state.current_collection_name:
            on_print("No ChromaDB collection specified. Use --collection to specify a collection name.", Fore.RED)
            sys.exit(1)

        if state.verbose_mode:
            on_print(f"Indexing documents from: {args.index_documents}", Fore.WHITE + Style.DIM)
            on_print(f"Collection: {state.current_collection_name}", Fore.WHITE + Style.DIM)
            on_print(f"Chunking: {args.chunk_documents}", Fore.WHITE + Style.DIM)
            on_print(f"Skip existing: {args.skip_existing}", Fore.WHITE + Style.DIM)
            if args.extract_start or args.extract_end:
                on_print(f"Extraction range: '{args.extract_start}' to '{args.extract_end}'", Fore.WHITE + Style.DIM)
            on_print(f"Split paragraphs: {args.split_paragraphs}", Fore.WHITE + Style.DIM)
            on_print(f"Add summary: {args.add_summary}", Fore.WHITE + Style.DIM)
            on_print(f"Store full docs: {args.store_full_docs}", Fore.WHITE + Style.DIM)

        document_indexer = mod.DocumentIndexer(
            args.index_documents, 
            state.current_collection_name, 
            state.chroma_client, 
            state.embeddings_model, 
            verbose=state.verbose_mode,
            summary_model=state.current_model
        )

        document_indexer.index_documents(
            allow_chunks=args.chunk_documents,
            no_chunking_confirmation=True,  # Non-interactive mode
            split_paragraphs=args.split_paragraphs,
            num_ctx=num_ctx,
            skip_existing=args.skip_existing,
            extract_start=args.extract_start,
            extract_end=args.extract_end,
            add_summary=args.add_summary,
            store_full_docs=args.store_full_docs
        )

        on_print(f"Indexing completed for folder: {args.index_documents}", Fore.GREEN)

        # If only indexing (no query or interactive mode), exit
        if not args.query and not state.interactive_mode:
            sys.exit(0)

    # Handle vector database query if requested
    if args.query:
        load_chroma_client()

        if not state.current_collection_name:
            on_print("No ChromaDB collection specified. Use --collection to specify a collection name.", Fore.RED)
            sys.exit(1)

        # Set query parameters
        query_n_results = args.query_n_results if args.query_n_results is not None else state.number_of_documents_to_return_from_vector_db

        if state.verbose_mode:
            on_print(f"Querying collection: {state.current_collection_name}", Fore.WHITE + Style.DIM)
            on_print(f"Query: {args.query}", Fore.WHITE + Style.DIM)
            on_print(f"Number of results: {query_n_results}", Fore.WHITE + Style.DIM)
            on_print(f"Distance threshold: {args.query_distance_threshold}", Fore.WHITE + Style.DIM)
            on_print(f"Expand query: {args.expand_query}", Fore.WHITE + Style.DIM)

        # Query the vector database
        query_results = mod.query_vector_database(
            args.query,
            collection_name=state.current_collection_name,
            n_results=query_n_results,
            answer_distance_threshold=args.query_distance_threshold,
            query_embeddings_model=state.embeddings_model,
            expand_query=args.expand_query
        )

        # Output results
        if query_results:
            if output_file:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(query_results)
                on_print(f"Query results saved to: {output_file}", Fore.GREEN)
            else:
                on_print("\n" + "="*80, Fore.CYAN)
                on_print("QUERY RESULTS", Fore.CYAN + Style.BRIGHT)
                on_print("="*80, Fore.CYAN)
                on_print(query_results)
                on_print("="*80, Fore.CYAN)
        else:
            on_print("No results found for the query.", Fore.YELLOW)

        # If not in interactive mode, exit after query
        if not state.interactive_mode:
            sys.exit(0)

    # Note: Web search handling moved to after model initialization (line ~4650)

    # Handle agent instantiation if requested
    if args.instantiate_agent:
        # Validate required parameters
        if not args.agent_task:
            on_print("Error: --agent-task is required when using --instantiate-agent", Fore.RED)
            sys.exit(1)

        if not args.agent_system_prompt:
            on_print("Error: --agent-system-prompt is required when using --instantiate-agent", Fore.RED)
            sys.exit(1)

        if args.agent_tools is None:
            on_print("Error: --agent-tools is required when using --instantiate-agent (use empty string for no tools)", Fore.RED)
            sys.exit(1)

        if not args.agent_name:
            on_print("Error: --agent-name is required when using --instantiate-agent", Fore.RED)
            sys.exit(1)

        if not args.agent_description:
            on_print("Error: --agent-description is required when using --instantiate-agent", Fore.RED)
            sys.exit(1)

        # Parse tools list (handle empty string for no tools)
        agent_tools_list = [tool.strip() for tool in args.agent_tools.split(',') if tool.strip()]

        if state.verbose_mode:
            on_print(f"Instantiating agent: {args.agent_name}", Fore.WHITE + Style.DIM)
            on_print(f"Task: {args.agent_task}", Fore.WHITE + Style.DIM)
            on_print(f"System Prompt: {args.agent_system_prompt}", Fore.WHITE + Style.DIM)
            on_print(f"Tools: {agent_tools_list}", Fore.WHITE + Style.DIM)
            on_print(f"Description: {args.agent_description}", Fore.WHITE + Style.DIM)

        # Load ChromaDB if needed (for agents that use vector database tools)
        load_chroma_client()

        # Ensure plugins are loaded if any of the agent tools require them
        if not state.plugins and mod.requires_plugins(agent_tools_list):
            state.plugins = mod.discover_plugins(state.plugins_folder, load_plugins=True)

        # Initialize the model and API client (required for agent instantiation)
        # Set up Azure OpenAI client if using Azure
        if state.use_azure_openai and not state.openai_client:
            from openai import AzureOpenAI

            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

            if api_key and azure_endpoint and deployment:
                state.openai_client = AzureOpenAI(
                    api_version="2024-02-15-preview",
                    azure_endpoint=azure_endpoint,
                    api_key=api_key,
                )
                state.current_model = deployment
                if state.verbose_mode:
                    on_print(f"Azure OpenAI initialized with deployment: {deployment}", Fore.WHITE + Style.DIM)
            else:
                on_print("Azure OpenAI configuration incomplete, falling back to Ollama", Fore.YELLOW)
                state.use_azure_openai = False

        # Set up OpenAI client if using OpenAI
        if state.use_openai and not state.use_azure_openai and not state.openai_client:
            from openai import OpenAI

            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                state.openai_client = OpenAI(api_key=api_key)
                state.current_model = preferred_model if preferred_model else "gpt-4"
                if state.verbose_mode:
                    on_print(f"OpenAI initialized with model: {state.current_model}", Fore.WHITE + Style.DIM)
            else:
                if state.verbose_mode:
                    on_print("OpenAI API key not found, falling back to Ollama", Fore.YELLOW)
                state.use_openai = False

        # Initialize the model if not using OpenAI/Azure
        if not state.current_model:
            if not state.use_openai and not state.use_azure_openai:
                # For Ollama, select available model
                default_model_temp = preferred_model if preferred_model else "qwen3:4b"
                if ":" not in default_model_temp:
                    default_model_temp += ":latest"
                state.current_model = select_ollama_model_if_available(default_model_temp)

        if state.verbose_mode:
            on_print(f"Using model: {state.current_model}", Fore.WHITE + Style.DIM)
            on_print(f"Use Azure OpenAI: {state.use_azure_openai}", Fore.WHITE + Style.DIM)
            on_print(f"Use OpenAI: {state.use_openai}", Fore.WHITE + Style.DIM)

        # Call the agent instantiation function directly
        result = mod.instantiate_agent_with_tools_and_process_task(
            task=args.agent_task,
            system_prompt=args.agent_system_prompt,
            tools=agent_tools_list,
            agent_name=args.agent_name,
            agent_description=args.agent_description,
            process_task=True
        )

        # Output result
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(str(result))

            if state.verbose_mode:
                on_print(f"Agent result saved to: {output_file}", Fore.GREEN)
        else:
            on_print(result)

        # Exit after agent execution (non-interactive mode)
        if not state.interactive_mode:
            sys.exit(0)

    auto_start_conversation = ("starts_conversation" in chatbot and chatbot["starts_conversation"]) or auto_start_conversation
    system_prompt = chatbot["system_prompt"]
    state.use_openai = state.use_openai or (hasattr(chatbot, 'use_openai') and getattr(chatbot, 'use_openai'))
    state.use_azure_openai = state.use_azure_openai or (hasattr(chatbot, 'use_azure_openai') and getattr(chatbot, 'use_azure_openai'))
    if "preferred_model" in chatbot:
        default_model = chatbot["preferred_model"]
    if preferred_model:
        default_model = preferred_model

    if not state.use_openai and not state.use_azure_openai:
        # If default model does not contain ":", append ":latest" to the model name
        if default_model and ":" not in default_model:
            default_model += ":latest"

        selected_model = select_ollama_model_if_available(default_model)
    elif state.use_azure_openai:
        from openai import AzureOpenAI

        # Get API key from environment variable
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        if not api_key:
            on_print("No Azure OpenAI API key found in the environment variables, make sure to set the AZURE_OPENAI_API_KEY.", Fore.RED)
            state.use_azure_openai = False
        else:
            if state.verbose_mode:
                on_print("Azure OpenAI API key found in the environment variables, redirecting to Azure OpenAI API.", Fore.WHITE + Style.DIM)
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

            if not azure_endpoint:
                on_print("No Azure OpenAI endpoint found in the environment variables, make sure to set the AZURE_OPENAI_ENDPOINT.", Fore.RED)
                state.use_azure_openai = False

            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

            if not deployment:
                on_print("No Azure OpenAI deployment found in the environment variables, make sure to set the AZURE_OPENAI_DEPLOYMENT.", Fore.RED)
                state.use_azure_openai = False

            if state.use_azure_openai:
                if state.verbose_mode:
                    on_print("Using Azure OpenAI API, endpoint: " + azure_endpoint + ", deployment: " + deployment, Fore.WHITE + Style.DIM)

                state.openai_client = AzureOpenAI(
                    api_version="2024-02-15-preview",
                    azure_endpoint=azure_endpoint,
                    api_key=api_key,
                    azure_deployment=deployment
                )

                selected_model = deployment
                state.current_model = selected_model
                state.use_openai = True
                stream_active = False
                state.syntax_highlighting = True
    else:
        from openai import OpenAI

        # Get API key from environment variable
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            if state.verbose_mode:
                on_print("No OpenAI API key found in the environment variables, calling local OpenAI API.", Fore.WHITE + Style.DIM)
            state.openai_client = OpenAI(
                base_url="http://127.0.0.1:8080",
                api_key="none"
            )
        else:
            if state.verbose_mode:
                on_print("OpenAI API key found in the environment variables, redirecting to OpenAI API.", Fore.WHITE + Style.DIM)
            state.openai_client = OpenAI(
                api_key=api_key
            )

        selected_model = select_openai_model_if_available(default_model)

    if selected_model is None:
        selected_model = prompt_for_model(default_model, state.current_model)
        state.current_model = selected_model
        if selected_model is None:
            return

    if not system_prompt:
        if state.no_system_role:
            on_print("The selected model does not support the 'system' role.", Fore.WHITE + Style.DIM)
            system_prompt = ""
        else:
            system_prompt = "You are a helpful chatbot assistant. Possible chatbot prompt commands: " + print_possible_prompt_commands()

    user_name = custom_user_name or get_personal_info()["user_name"]
    if no_user_name:
        user_name = ""
        if state.verbose_mode:
            on_print("User name not used.", Fore.WHITE + Style.DIM)

    # Set the current collection
    set_current_collection(state.current_collection_name, verbose=state.verbose_mode)

    # Initial system message
    if initial_system_prompt:
        if state.verbose_mode:
            on_print("Initial system prompt: " + initial_system_prompt, Fore.WHITE + Style.DIM)
        system_prompt = initial_system_prompt

    if not state.no_system_role and len(user_name) > 0:
        first_name = user_name.split()[0]
        system_prompt += f"\nThe user's name is {user_name}, first name: {first_name}. {today}"

    if len(system_prompt) > 0:
        # Replace placeholders in the system_prompt using the system_prompt_placeholders dictionary
        for key, value in system_prompt_placeholders.items():
            system_prompt = system_prompt.replace(f"{{{{{key}}}}}", value)

        state.initial_message = {"role": "system", "content": system_prompt}
        conversation = [state.initial_message]
    else:
        state.initial_message = None
        conversation = []

    state.current_model = selected_model

    answer_and_exit = False
    if not state.interactive_mode and state.user_prompt:
        answer_and_exit = True

    if use_memory_manager:
        load_chroma_client()

        if state.chroma_client:
            state.memory_manager = mod.MemoryManager(state.memory_collection_name, state.chroma_client, state.current_model, state.embeddings_model, state.verbose_mode, num_ctx=num_ctx, long_term_memory_file=state.long_term_memory_file)

            if state.initial_message:
                # Add long-term memory to the system prompt
                long_term_memory = state.memory_manager.long_term_memory_manager.memory

                state.initial_message["content"] += f"\n\nLong-term memory: {long_term_memory}"
        else:
            use_memory_manager = False

    if state.initial_message and state.verbose_mode:
        on_print("System prompt: " + state.initial_message["content"], Fore.WHITE + Style.DIM)

    user_input = ""

    if "tools" in chatbot and len(chatbot["tools"]) > 0:
        # Append chatbot tools to selected_tools if not already in the array
        if state.selected_tools is None:
            state.selected_tools = []

        for tool in chatbot["tools"]:
            state.selected_tools = mod.select_tool_by_name(mod.get_available_tools(), state.selected_tools, tool)

    selected_tool_names = args.tools.split(',') if args.tools else []
    for tool_name in selected_tool_names:
        # Strip any leading or trailing spaces, single or double quotes
        tool_name = tool_name.strip().strip('\'').strip('\"')
        state.selected_tools = mod.select_tool_by_name(mod.get_available_tools(), state.selected_tools, tool_name)

    # Handle web search if requested (after model initialization)
    if args.web_search:
        show_intermediate = args.web_search_show_intermediate

        if state.verbose_mode:
            on_print(f"Performing web search for: {args.web_search}", Fore.WHITE + Style.DIM)
            on_print(f"Number of results: {args.web_search_results}", Fore.WHITE + Style.DIM)
            on_print(f"Region: {args.web_search_region}", Fore.WHITE + Style.DIM)
            on_print(f"Show intermediate results: {show_intermediate}", Fore.WHITE + Style.DIM)

        # Ensure ChromaDB is loaded for web search caching
        load_chroma_client()

        if not state.chroma_client:
            on_print("Web search requires ChromaDB to be running. Please start ChromaDB server or configure a persistent database path.", Fore.RED)
            sys.exit(1)

        # Perform the web search
        if show_intermediate:
            on_print("\n" + "="*80, Fore.MAGENTA)
            on_print("SEARCHING THE WEB, QUERY: " + args.web_search, Fore.MAGENTA + Style.BRIGHT)
            on_print("="*80, Fore.MAGENTA)

            web_search_response, intermediate_data = mod.web_search(
                args.web_search, 
                n_results=args.web_search_results, 
                region=args.web_search_region,
                web_embedding_model=state.embeddings_model,
                num_ctx=num_ctx,
                return_intermediate=True
            )

            # Display intermediate results
            if intermediate_data:
                on_print("\n" + "="*80, Fore.MAGENTA)
                on_print("INTERMEDIATE RESULTS", Fore.MAGENTA + Style.BRIGHT)
                on_print("="*80, Fore.MAGENTA)

                # Show search results
                if 'search_results' in intermediate_data and intermediate_data['search_results']:
                    on_print("\n" + "-"*80, Fore.MAGENTA)
                    on_print("1. SEARCH RESULTS FROM DUCKDUCKGO", Fore.MAGENTA + Style.BRIGHT)
                    on_print("-"*80, Fore.MAGENTA)
                    for i, result in enumerate(intermediate_data['search_results'], 1):
                        on_print(f"\n{i}. {result.get('title', 'N/A')}", Fore.CYAN + Style.BRIGHT)
                        on_print(f"   URL: {result.get('href', 'N/A')}", Fore.CYAN)
                        on_print(f"   Snippet: {result.get('body', 'N/A')}", Fore.WHITE)

                # Show URLs being crawled
                if 'urls' in intermediate_data and intermediate_data['urls']:
                    on_print("\n" + "-"*80, Fore.MAGENTA)
                    on_print("2. URLS BEING CRAWLED", Fore.MAGENTA + Style.BRIGHT)
                    on_print("-"*80, Fore.MAGENTA)
                    for i, url in enumerate(intermediate_data['urls'], 1):
                        on_print(f"   {i}. {url}", Fore.CYAN)

                # Show crawled articles
                if 'articles' in intermediate_data and intermediate_data['articles']:
                    on_print("\n" + "-"*80, Fore.MAGENTA)
                    on_print("3. CRAWLED CONTENT", Fore.MAGENTA + Style.BRIGHT)
                    on_print("-"*80, Fore.MAGENTA)
                    for i, article in enumerate(intermediate_data['articles'], 1):
                        on_print(f"\n{i}. URL: {article.get('url', 'N/A')}", Fore.CYAN + Style.BRIGHT)
                        content = article.get('text', '')
                        # Show first 500 characters of each article
                        preview = content[:500] + "..." if len(content) > 500 else content
                        on_print(f"   Content preview: {preview}", Fore.WHITE)
                        on_print(f"   Total length: {len(content)} characters", Fore.YELLOW)

                # Show vector DB results
                if 'vector_db_results' in intermediate_data:
                    on_print("\n" + "-"*80, Fore.MAGENTA)
                    on_print("4. VECTOR DATABASE RETRIEVAL RESULTS", Fore.MAGENTA + Style.BRIGHT)
                    on_print("-"*80, Fore.MAGENTA)
                    on_print(intermediate_data['vector_db_results'], Fore.WHITE)

                on_print("\n" + "="*80, Fore.MAGENTA)
        else:
            web_search_response = mod.web_search(
                args.web_search, 
                n_results=args.web_search_results, 
                region=args.web_search_region,
                web_embedding_model=state.embeddings_model,
                num_ctx=num_ctx,
                return_intermediate=False
            )

        if web_search_response:
            # Build the prompt with web search context
            web_search_prompt = f"Context: {web_search_response}\n\n"
            web_search_prompt += f"Question: {args.web_search}\n"
            web_search_prompt += "Answer the question as truthfully as possible using the provided web search results, and if the answer is not contained within the text above, say 'I don't know'.\n"
            web_search_prompt += "Cite some useful links from the search results to support your answer."

            if state.verbose_mode:
                on_print("\n" + "="*80, Fore.CYAN)
                on_print("WEB SEARCH CONTEXT", Fore.CYAN + Style.BRIGHT)
                on_print("="*80, Fore.CYAN)
                on_print(web_search_response, Fore.WHITE + Style.DIM)
                on_print("="*80, Fore.CYAN)

            # Use the current model (already initialized)
            if state.verbose_mode:
                on_print(f"Using model: {state.current_model}", Fore.WHITE + Style.DIM)

            # Get answer from the model
            on_print("\n" + "="*80, Fore.GREEN)
            on_print("ANSWER", Fore.GREEN + Style.BRIGHT)
            on_print("="*80, Fore.GREEN)

            answer = mod.ask_ollama(
                "",
                web_search_prompt,
                state.current_model,
                temperature=state.temperature,
                no_bot_prompt=True,
                stream_active=stream_active,
                num_ctx=num_ctx
            )

            if answer:
                if not stream_active:
                    on_print(answer)
                on_print("\n" + "="*80, Fore.GREEN)

                # Save to output file if specified
                if output_file:
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(f"Query: {args.web_search}\n\n")
                        f.write(f"Context:\n{web_search_response}\n\n")
                        f.write(f"Answer:\n{answer}\n")
                    on_print(f"\nResults saved to: {output_file}", Fore.GREEN)
            else:
                on_print("No answer generated.", Fore.YELLOW)
        else:
            on_print("No web search results found.", Fore.YELLOW)

        # If not in interactive mode, exit after web search
        if not state.interactive_mode:
            sys.exit(0)


    return {
        "selected_model": selected_model,
        "conversation": conversation,
        "system_prompt": system_prompt,
        "chatbot": chatbot,
        "num_ctx": num_ctx,
        "stream_active": stream_active,
        "output_file": output_file,
        "auto_save": auto_save,
        "auto_start_conversation": auto_start_conversation,
        "use_memory_manager": use_memory_manager,
        "user_name": user_name,
        "conversations_folder": conversations_folder,
        "answer_and_exit": answer_and_exit,
        "today": today,
        "system_prompt_placeholders": system_prompt_placeholders,
        "default_model": default_model,
        "args": args,
    }


def main_loop(ctx, mod):
    """Interactive conversation loop."""
    selected_model = ctx["selected_model"]
    conversation = ctx["conversation"]
    system_prompt = ctx["system_prompt"]
    chatbot = ctx["chatbot"]
    num_ctx = ctx["num_ctx"]
    stream_active = ctx["stream_active"]
    output_file = ctx["output_file"]
    auto_save = ctx["auto_save"]
    auto_start_conversation = ctx["auto_start_conversation"]
    use_memory_manager = ctx["use_memory_manager"]
    user_name = ctx["user_name"]
    conversations_folder = ctx["conversations_folder"]
    answer_and_exit = ctx["answer_and_exit"]
    today = ctx["today"]
    system_prompt_placeholders = ctx["system_prompt_placeholders"]
    default_model = ctx["default_model"]
    args = ctx["args"]

    # Main conversation loop
    while True:
        thoughts = None
        if not auto_start_conversation:
            try:
                if state.interactive_mode:
                    on_prompt("\nYou: ", Fore.YELLOW + Style.NORMAL)

                if state.user_prompt:
                    if state.other_instance_url:
                        conversation.append({"role": "assistant", "content": state.user_prompt})
                        user_input = on_user_input(state.user_prompt)
                    else:
                        user_input = state.user_prompt
                    state.user_prompt = None
                else:
                    user_input = on_user_input()

                if user_input.strip().startswith('"""'):
                    multi_line_input = [user_input[3:]]  # Keep the content after the first """
                    on_stdout_write("... ")  # Prompt continuation line

                    while True:
                        line = on_user_input()
                        if line.strip().endswith('"""') and len(line.strip()) > 3:
                            # Handle if the line contains content before """
                            multi_line_input.append(line[:-3])
                            break
                        elif line.strip().endswith('"""'):
                            break
                        else:
                            multi_line_input.append(line)
                            on_stdout_write("... ")  # Prompt continuation line

                    user_input = "\n".join(multi_line_input)

            except EOFError:
                break
            except KeyboardInterrupt:
                auto_save = False
                on_print("\nGoodbye!", Style.RESET_ALL)
                break

            if len(user_input.strip()) == 0:
                continue

        # Exit condition
        if user_input.lower() in ['/quit', '/exit', '/bye', 'quit', 'exit', 'bye', 'goodbye', 'stop'] or re.search(r'\b(bye|goodbye)\b', user_input, re.IGNORECASE):
            on_print("Goodbye!", Style.RESET_ALL)
            if state.memory_manager:
                on_print("Saving conversation to memory...", Fore.WHITE + Style.DIM)
                if state.memory_manager.add_memory(conversation):
                    on_print("Conversation saved to memory.", Fore.WHITE + Style.DIM)
                    on_print("", Style.RESET_ALL)
            break

        if user_input.lower() in ['/reset', '/clear', '/restart', 'reset', 'clear', 'restart']:
            on_print("Conversation reset.", Style.RESET_ALL)
            if state.initial_message:
                conversation = [state.initial_message]
            else:
                conversation = []

            auto_start_conversation = ("starts_conversation" in chatbot and chatbot["starts_conversation"]) or args.auto_start
            user_input = ""
            continue

        for plugin in state.plugins:
            if hasattr(plugin, "on_user_input_done") and callable(getattr(plugin, "on_user_input_done")):
                user_input_from_plugin = plugin.on_user_input_done(user_input, verbose_mode=state.verbose_mode)
                if user_input_from_plugin:
                    user_input = user_input_from_plugin

        # Allow for /context command to be used to set the context window size
        if user_input.startswith("/context"):
            if re.search(r'/context\s+\d+', user_input):
                context_window = int(re.search(r'/context\s+(\d+)', user_input).group(1))
                max_context_length = 125 # 125 * 1024 = 128000 tokens
                if context_window < 0 or context_window > max_context_length:
                    on_print(f"Context window must be between 0 and {max_context_length}.", Fore.RED)
                else:
                    num_ctx = context_window * 1024
                    if state.verbose_mode:
                        on_print(f"Context window changed to {num_ctx} tokens.", Fore.WHITE + Style.DIM)
            else:
                on_print(f"Please specify context window size with /context <number>.", Fore.RED)
            continue

        if "/system" in user_input:
            system_prompt = user_input.replace("/system", "").strip()

            if len(system_prompt) > 0:
                # Replace placeholders in the system_prompt using the system_prompt_placeholders dictionary
                for key, value in system_prompt_placeholders.items():
                    system_prompt = system_prompt.replace(f"{{{{{key}}}}}", value)

                if state.verbose_mode:
                    on_print("System prompt: " + system_prompt, Fore.WHITE + Style.DIM)

                for entry in conversation:
                    if "role" in entry and entry["role"] == "system":
                        entry["content"] = system_prompt
                        break
            continue

        if "/index" in user_input:
            if not state.chroma_client:
                on_print("ChromaDB client not initialized.", Fore.RED)
                continue

            load_chroma_client()

            if not state.current_collection_name:
                on_print("No ChromaDB collection loaded.", Fore.RED)

                collection_name, collection_description = prompt_for_vector_database_collection()
                set_current_collection(collection_name, collection_description, verbose=state.verbose_mode)

            folder_to_index = user_input.split("/index")[1].strip()
            temp_folder = None
            if folder_to_index.startswith("http"):
                base_url = folder_to_index
                temp_folder = tempfile.mkdtemp()
                scraper = mod.SimpleWebScraper(base_url, output_dir=temp_folder, file_types=["html", "htm"], restrict_to_base=True, convert_to_markdown=True, verbose=state.verbose_mode)
                scraper.scrape()
                folder_to_index = temp_folder

            document_indexer = mod.DocumentIndexer(folder_to_index, state.current_collection_name, state.chroma_client, state.embeddings_model, verbose=state.verbose_mode, summary_model=state.current_model)
            document_indexer.index_documents(num_ctx=num_ctx)

            if temp_folder:
                # Remove the temporary folder and its contents
                for file in os.listdir(temp_folder):
                    file_path = os.path.join(temp_folder, file)
                    os.remove(file_path)
                os.rmdir(temp_folder)
            continue

        if user_input == "/verbose":
            state.verbose_mode = not state.verbose_mode
            on_print(f"Verbose mode: {state.verbose_mode}", Fore.WHITE + Style.DIM)
            continue

        if "/cot" in user_input:
            user_input = user_input.replace("/cot", "").strip()
            chain_of_thoughts_system_prompt = generate_chain_of_thoughts_system_prompt(state.selected_tools)

            # Format the current conversation as user/assistant messages
            formatted_conversation = "\n".join([f"{entry['role']}: {entry['content']}" for entry in conversation if "content" in entry and entry["content"] and "role" in entry and entry["role"] != "system" and entry["role"] != "tool"])
            formatted_conversation += "\n\n" + user_input

            thoughts = mod.ask_ollama(chain_of_thoughts_system_prompt, formatted_conversation, state.thinking_model, state.temperature, state.prompt_template, no_bot_prompt=True, stream_active=False, num_ctx=num_ctx)

        if "/search" in user_input:
            # If /search is followed by a number, use that number as the number of documents to return (/search can be anywhere in the prompt)
            if re.search(r'/search\s+\d+', user_input):
                n_docs_to_return = int(re.search(r'/search\s+(\d+)', user_input).group(1))
                user_input = user_input.replace(f"/search {n_docs_to_return}", "").strip()
            else:
                user_input = user_input.replace("/search", "").strip()
                n_docs_to_return = state.number_of_documents_to_return_from_vector_db

            answer_from_vector_db = mod.query_vector_database(user_input, collection_name=state.current_collection_name, n_results=n_docs_to_return)
            if answer_from_vector_db:
                initial_user_input = user_input
                user_input = "Question: " + initial_user_input
                user_input += "\n\nAnswer the question as truthfully as possible using the provided text below, and if the answer is not contained within the text below, say 'I don't know'.\n\n"
                user_input += answer_from_vector_db
                user_input += "\n\nAnswer the question as truthfully as possible using the provided text above, and if the answer is not contained within the text above, say 'I don't know'."
                user_input += "\nQuestion: " + initial_user_input

                if state.verbose_mode:
                    on_print(user_input, Fore.WHITE + Style.DIM)
        elif "/web" in user_input:
            user_input = user_input.replace("/web", "").strip()
            web_search_response = mod.web_search(user_input, num_ctx=num_ctx, web_embedding_model=state.embeddings_model)
            if web_search_response:
                initial_user_input = user_input
                user_input += "Context: " + web_search_response
                user_input += "\n\nQuestion: " + initial_user_input
                user_input += "\nAnswer the question as truthfully as possible using the provided web search results, and if the answer is not contained within the text below, say 'I don't know'.\n"
                user_input += "Cite some useful links from the search results to support your answer."

                if state.verbose_mode:
                    on_print(user_input, Fore.WHITE + Style.DIM)

        if user_input == "/thinking_model":
            selected_model = prompt_for_model(default_model, state.thinking_model)
            state.thinking_model = selected_model
            continue

        if user_input == "/model":
            thinking_model_is_same = state.thinking_model == state.current_model

            if state.use_azure_openai:
                # For Azure OpenAI, just ask for the deployment name
                selected_model = on_user_input(f"Enter Azure OpenAI deployment name [{state.current_model}]: ").strip() or state.current_model
            else:
                selected_model = prompt_for_model(default_model, state.current_model)

            state.current_model = selected_model

            if thinking_model_is_same:
                state.thinking_model = selected_model

            if use_memory_manager:
                load_chroma_client()

                if state.chroma_client:
                    state.memory_manager = mod.MemoryManager(state.memory_collection_name, state.chroma_client, state.current_model, state.embeddings_model, state.verbose_mode, num_ctx=num_ctx, long_term_memory_file=state.long_term_memory_file)
                else:
                    use_memory_manager = False
            continue

        if user_input == "/memory":
            if use_memory_manager:
                # Deactivate memory manager
                state.memory_manager = None
                use_memory_manager = False
                on_print("Memory manager deactivated.", Fore.WHITE + Style.DIM)
            else:
                load_chroma_client()

                if state.chroma_client:
                    state.memory_manager = mod.MemoryManager(state.memory_collection_name, state.chroma_client, state.current_model, state.embeddings_model, state.verbose_mode, num_ctx=num_ctx, long_term_memory_file=state.long_term_memory_file)
                    use_memory_manager = True
                    on_print("Memory manager activated.", Fore.WHITE + Style.DIM)
                else:
                    on_print("ChromaDB client not initialized.", Fore.RED)

            continue

        if user_input == "/model2":
            if state.use_azure_openai:
                # For Azure OpenAI, just ask for the deployment name
                current_alt = state.alternate_model if state.alternate_model else state.current_model
                state.alternate_model = on_user_input(f"Enter Azure OpenAI deployment name for alternate model [{current_alt}]: ").strip() or current_alt
            else:
                state.alternate_model = prompt_for_model(default_model, state.current_model)
            continue

        if user_input == "/tools":
            state.selected_tools = mod.select_tools(mod.get_available_tools(), selected_tools=state.selected_tools)
            continue

        if "/save" in user_input:
            # If the user input contains /save and followed by a filename, save the conversation to that file
            file_path = user_input.split("/save")[1].strip()
            # Remove any leading or trailing spaces, single or double quotes
            file_path = file_path.strip().strip('\'').strip('\"')

            if file_path:
                # Check if the filename contains a folder path (use os path separator to check)
                if os.path.sep in file_path:
                    # Get the folder path and filename
                    folder_path, _ = os.path.split(file_path)
                    # Create the folder if it doesn't exist
                    if not os.path.exists(folder_path):
                        os.makedirs(folder_path)
                elif conversations_folder:
                    file_path = os.path.join(conversations_folder, file_path)

                save_conversation_to_file(conversation, file_path)
            else:
                # Save the conversation to a file, use current timestamp as the filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                if conversations_folder:
                    save_conversation_to_file(conversation, os.path.join(conversations_folder, f"conversation_{timestamp}.txt"))
                else:
                    save_conversation_to_file(conversation, f"conversation_{timestamp}.txt")
            continue

        if "/load" in user_input:
            # If the user input contains /load and followed by a filename, load the conversation from that file (assumed to be a JSON file)
            file_path = user_input.split("/load")[1].strip()
            # Remove any leading or trailing spaces, single or double quotes
            file_path = file_path.strip().strip('\'').strip('\"')

            if file_path:
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding="utf8") as f:
                        conversation = json.load(f)

                        system_prompt = ""
                        state.initial_message = None

                        # Find system prompt in the conversation
                        for entry in conversation:
                            if "role" in entry and entry["role"] == "system":
                                system_prompt = entry["content"]
                                state.initial_message = {"role": "system", "content": system_prompt}
                                break

                        # Reformat each entry tool_calls.function.arguments to be a valid dictionary, unless it's already a dictionary
                        for entry in conversation:
                            if "tool_calls" in entry:
                                for tool_call in entry["tool_calls"]:
                                    if "function" in tool_call and "arguments" in tool_call["function"]:
                                        if isinstance(tool_call["function"]["arguments"], str):
                                            try:
                                                tool_call["function"]["arguments"] = json.loads(tool_call["function"]["arguments"])
                                            except json.JSONDecodeError:
                                                pass

                    on_print(f"Conversation loaded from {file_path}", Fore.WHITE + Style.DIM)
                else:
                    on_print(f"Conversation file '{file_path}' not found.", Fore.RED)
            else:
                on_print("Please specify a file path to load the conversation.", Fore.RED)
            continue

        if user_input == "/collection":
            collection_name, collection_description = prompt_for_vector_database_collection()
            set_current_collection(collection_name, collection_description, verbose=state.verbose_mode)
            continue

        if state.memory_manager and (user_input == "/remember" or user_input == "/memorize"):
            on_print("Saving conversation to memory...", Fore.WHITE + Style.DIM)
            if state.memory_manager.add_memory(conversation):
                on_print("Conversation saved to memory.", Fore.WHITE + Style.DIM)
                on_print("", Style.RESET_ALL)
            continue

        if state.memory_manager and user_input == "/forget":
            # Remove memory collection
            delete_collection(state.memory_collection_name)
            continue

        if "/rmcollection" in user_input or "/deletecollection" in user_input:
            if "/rmcollection" in user_input and len(user_input.split("/rmcollection")) > 1:
                collection_name = user_input.split("/rmcollection")[1].strip()

            if not collection_name and "/deletecollection" in user_input and len(user_input.split("/deletecollection")) > 1:
                collection_name = user_input.split("/deletecollection")[1].strip()

            if not collection_name:
                collection_name, _ = prompt_for_vector_database_collection(prompt_create_new=False, include_web_cache=True)

            if not collection_name:
                continue

            delete_collection(collection_name)
            continue

        if "/editcollection" in user_input:
            collection_name, _ = prompt_for_vector_database_collection()
            edit_collection_metadata(collection_name)
            continue

        if user_input == "/chatbot":
            chatbot = prompt_for_chatbot()
            if "tools" in chatbot and len(chatbot["tools"]) > 0:
                # Append chatbot tools to selected_tools if not already in the array
                if state.selected_tools is None:
                    state.selected_tools = []

                for tool in chatbot["tools"]:
                    state.selected_tools = mod.select_tool_by_name(mod.get_available_tools(), state.selected_tools, tool)

            system_prompt = chatbot["system_prompt"]
            # Initial system message
            if not state.no_system_role and len(user_name) > 0:
                first_name = user_name.split()[0]
                system_prompt += f"\nThe user's name is {user_name}, first name: {first_name}. {today}"

            if len(system_prompt) > 0:
                # Replace placeholders in the system_prompt using the system_prompt_placeholders dictionary
                for key, value in system_prompt_placeholders.items():
                    system_prompt = system_prompt.replace(f"{{{{{key}}}}}", value)

                if state.verbose_mode:
                    on_print("System prompt: " + system_prompt, Fore.WHITE + Style.DIM)

                state.initial_message = {"role": "system", "content": system_prompt}
                conversation = [state.initial_message]
            else:
                conversation = []
            on_print("Conversation reset.", Style.RESET_ALL)
            auto_start_conversation = ("starts_conversation" in chatbot and chatbot["starts_conversation"]) or args.auto_start
            user_input = ""
            continue

        if "/cb" in user_input:
            if platform.system() == "Windows":
                # Replace /cb with the clipboard content
                win32clipboard.OpenClipboard()
                clipboard_content = win32clipboard.GetClipboardData()
                win32clipboard.CloseClipboard()
            else:
                clipboard_content = pyperclip.paste()
            user_input = user_input.replace("/cb", "\n" + clipboard_content + "\n")
            on_print("Clipboard content added to user input.", Fore.WHITE + Style.DIM)

        image_path = None
        # If user input contains '/file <path of a file to load>' anywhere in the prompt, read the file and append the content to user_input
        if "/file" in user_input:
            # Extract the file path, handling quoted paths with spaces
            file_part = user_input.split("/file", 1)[1].strip()

            # Check if the path is quoted
            if file_part.startswith('"'):
                # Find the closing quote
                end_quote = file_part.find('"', 1)
                if end_quote != -1:
                    file_path = file_part[1:end_quote]
                    remaining_text = file_part[end_quote+1:].strip()
                else:
                    file_path = file_part[1:].strip('"')
                    remaining_text = ""
            elif file_part.startswith("'"):
                # Find the closing quote
                end_quote = file_part.find("'", 1)
                if end_quote != -1:
                    file_path = file_part[1:end_quote]
                    remaining_text = file_part[end_quote+1:].strip()
                else:
                    file_path = file_part[1:].strip("'")
                    remaining_text = ""
            else:
                # No quotes, split on first space
                parts = file_part.split(None, 1)
                file_path = parts[0]
                remaining_text = parts[1] if len(parts) > 1 else ""

            # Check if the file exists
            if not os.path.exists(file_path):
                on_print(f"File not found: {file_path}", Fore.RED)
                continue

            # Get the text before /file
            text_before_file = user_input.split("/file", 1)[0].strip()

            # Check if the file is an image or PDF (or other binary file that should be sent as base64)
            _, ext = os.path.splitext(file_path)

            # For OpenAI/Azure OpenAI: treat images, PDFs, and other binary files as attachments
            # For Ollama: only treat images as attachments, read text from other files
            is_binary_file = ext.lower() in [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".pdf"]

            if (state.use_openai or state.use_azure_openai) and is_binary_file:
                # Send as attachment using base64 encoding via Responses API
                user_input = f"{text_before_file} {remaining_text}".strip()
                image_path = file_path
                if state.verbose_mode:
                    on_print(f"File {file_path} will be sent as base64 attachment.", Fore.WHITE + Style.DIM)
            elif not (state.use_openai or state.use_azure_openai) and ext.lower() in [".png", ".jpg", ".jpeg", ".bmp"]:
                # For Ollama, only images are attachments
                user_input = f"{text_before_file} {remaining_text}".strip()
                image_path = file_path
            else:
                # Read text content from the file
                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        file_content = file.read()
                        user_input = f"{text_before_file} {remaining_text}\n{file_content}".strip()
                except Exception as e:
                    on_print(f"Error reading file: {e}", Fore.RED)
                    continue

        if user_input == "/think":
            if not state.think_mode_on:
                state.think_mode_on = True
                if state.verbose_mode:
                    on_print("Think mode activated.", Fore.WHITE + Style.DIM)
            else:
                state.think_mode_on = False
                if state.verbose_mode:
                    on_print("Think mode deactivated.", Fore.WHITE + Style.DIM)
            continue

        # If user input starts with '/' and is not a command, ignore it.
        if user_input.startswith('/') and not user_input.startswith('//'):
            on_print("Invalid command. Please try again.", Fore.RED)
            continue

        # Add user input to conversation history
        if image_path:
            conversation.append({"role": "user", "content": user_input, "images": [image_path]})
        elif len(user_input.strip()) > 0:
            conversation.append({"role": "user", "content": user_input})

        if state.memory_manager:
            state.memory_manager.handle_user_query(conversation)

        if thoughts:
            thoughts = f"Thinking...\n{thoughts}\nEnd of internal thoughts.\n\nFinal response:"
            if state.syntax_highlighting:
                on_print(colorize(thoughts), Style.RESET_ALL, "\rBot: " if state.interactive_mode else "")
            else:
                on_print(thoughts, Style.RESET_ALL, "\rBot: " if state.interactive_mode else "")

            # Add the chain of thoughts to the conversation, as an assistant message
            conversation.append({"role": "assistant", "content": thoughts})

        # Generate response
        bot_response = mod.ask_ollama_with_conversation(conversation, selected_model, temperature=state.temperature, prompt_template=state.prompt_template, tools=state.selected_tools, stream_active=stream_active, num_ctx=num_ctx)

        alternate_bot_response = None
        if state.alternate_model:
            alternate_bot_response = mod.ask_ollama_with_conversation(conversation, state.alternate_model, temperature=state.temperature, prompt_template=state.prompt_template, tools=state.selected_tools, prompt="\nAlt", prompt_color=Fore.CYAN, stream_active=stream_active, num_ctx=num_ctx)

        bot_response_handled_by_plugin = False
        for plugin in state.plugins:
            if hasattr(plugin, "on_llm_response") and callable(getattr(plugin, "on_llm_response")):
                plugin_response = getattr(plugin, "on_llm_response")(bot_response)
                bot_response_handled_by_plugin = bot_response_handled_by_plugin or plugin_response

        if not bot_response_handled_by_plugin:
            if state.syntax_highlighting:
                on_print(colorize(bot_response), Style.RESET_ALL, "\rBot: " if state.interactive_mode else "")

                if alternate_bot_response:
                    on_print(colorize(alternate_bot_response), Fore.CYAN, "\rAlt: " if state.interactive_mode else "")
            elif not state.use_openai and not state.use_azure_openai and len(state.selected_tools) > 0:
                # Ollama cannot stream when tools are used
                on_print(bot_response, Style.RESET_ALL, "\rBot: " if state.interactive_mode else "")

                if alternate_bot_response:
                    on_print(alternate_bot_response, Fore.CYAN, "\rAlt: " if state.interactive_mode else "")

        if alternate_bot_response:
            # Ask user to select the preferred response
            on_print(f"Select the preferred response:\n1. Original model ({state.current_model})\n2. Alternate model ({state.alternate_model})", Fore.WHITE + Style.DIM)
            choice = on_user_input("Enter the number of your preferred response [1]: ") or "1"
            bot_response = bot_response if choice == "1" else alternate_bot_response

        # Add bot response to conversation history
        conversation.append({"role": "assistant", "content": bot_response})

        if auto_start_conversation:
            auto_start_conversation = False

        if output_file:
            if bot_response:
                with open(output_file, 'a', encoding='utf-8') as f:
                    f.write(bot_response)
                    if state.verbose_mode:
                        on_print(f"Response saved to {output_file}", Fore.WHITE + Style.DIM)
            else:
                on_print("No bot response to save.", Fore.YELLOW)

        # Exit condition: if the bot response contains an exit command ('bye', 'goodbye'), using a regex pattern to match the words
        if bot_response and re.search(r'\b(bye|goodbye)\b', bot_response, re.IGNORECASE):
            on_print("Goodbye!", Style.RESET_ALL)
            break

        if answer_and_exit:
            break


    # Stop plugins, calling on_exit if available
    for plugin in state.plugins:
        if hasattr(plugin, "on_exit") and callable(getattr(plugin, "on_exit")):
            getattr(plugin, "on_exit")()

    if auto_save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if conversations_folder:
            save_conversation_to_file(conversation, os.path.join(conversations_folder, f"conversation_{timestamp}.txt"))
        else:
            save_conversation_to_file(conversation, f"conversation_{timestamp}.txt")

