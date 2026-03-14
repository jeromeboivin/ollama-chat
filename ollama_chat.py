# -*- coding: utf-8 -*-
import sys
import io

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import ollama
import platform
import tempfile
from colorama import Fore, Style
import chromadb
import readline
import base64
import getpass
import math

if platform.system() == "Windows":
    import win32clipboard
else:
    import pyperclip

import argparse
import re
import os
import sys
import json
import importlib.util
import inspect
import subprocess
import shlex
from typing import Tuple, List, Dict, Any
from appdirs import AppDirs
from datetime import date, datetime
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import Terminal256Formatter
from ddgs import DDGS
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from markdownify import MarkdownConverter
import requests
from PyPDF2 import PdfReader
import chardet
from rank_bm25 import BM25Okapi
import hashlib
import csv
from pptx import Presentation
from docx import Document
from lxml import etree
from openpyxl import load_workbook
from tqdm import tqdm

# --- Extracted modules ---------------------------------------------------
from ollama_chat_lib.constants import (
    APP_NAME, APP_AUTHOR, APP_VERSION,
    web_cache_collection_name,
    min_quality_results_threshold, min_average_bm25_threshold,
    min_hybrid_score_threshold, distance_percentile_threshold,
    semantic_weight, adaptive_distance_multiplier,
    stop_words, COMMANDS,
)
from ollama_chat_lib.splitters import TabularDataSplitter, MarkdownSplitter
from ollama_chat_lib.text_extraction import (
    md, extract_text_from_html, extract_text_from_pdf,
    extract_text_from_docx, extract_text_from_csv,
    extract_text_from_xlsx, extract_text_from_pptx,
    is_html, is_docx, is_pptx, is_markdown,
)
from ollama_chat_lib.utils import (
    find_latest_user_message, render_tools,
    try_parse_json, try_merge_concatenated_json,
    bytes_to_gibibytes, get_personal_info,
    extract_json,
)
from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import (
    completer, on_user_input, on_print, on_stdout_write,
    on_llm_token_response, on_llm_thinking_token_response,
    on_prompt, on_stdout_flush,
)
from ollama_chat_lib.tools import (
    get_available_tools as _get_available_tools,
    generate_chain_of_thoughts_system_prompt,
    select_tools, select_tool_by_name,
    get_builtin_tool_names, requires_plugins,
    web_search as _web_search,
)
from ollama_chat_lib.vector_db import (
    load_chroma_client, edit_collection_metadata,
    prompt_for_vector_database_collection, set_current_collection,
    delete_collection, preprocess_text,
    query_vector_database as _query_vector_database,
)
from ollama_chat_lib.model_selection import (
    select_ollama_model_if_available, select_openai_model_if_available,
    prompt_for_openai_model, prompt_for_ollama_model,
    is_model_an_ollama_model, prompt_for_model,
)
from ollama_chat_lib.conversation import (
    colorize, print_spinning_wheel, encode_file_to_base64_with_mime,
    print_possible_prompt_commands, split_numbered_list,
    load_additional_chatbots, prompt_for_chatbot,
    save_conversation_to_file,
    summarize_chunk as _summarize_chunk,
    summarize_text_file as _summarize_text_file,
    DEFAULT_CHATBOTS,
)
# -------------------------------------------------------------------------


def get_available_tools():
    return _get_available_tools(load_chroma_client_fn=load_chroma_client)

from ollama_chat_lib.web_crawler import SimpleWebCrawler as _SimpleWebCrawler, SimpleWebScraper  # noqa: E402

class SimpleWebCrawler(_SimpleWebCrawler):
    """Thin compatibility shim that auto-injects ask_fn=ask_ollama."""
    def __init__(self, urls, llm_enabled=False, system_prompt='', selected_model='', temperature=0.1, verbose=False, plugins=[], num_ctx=None, ask_fn=None):
        super().__init__(urls, llm_enabled=llm_enabled, system_prompt=system_prompt, selected_model=selected_model,
                         temperature=temperature, verbose=verbose, plugins=plugins, num_ctx=num_ctx,
                         ask_fn=ask_fn or ask_ollama)

from ollama_chat_lib.plugin_manager import discover_plugins as _discover_plugins  # noqa: E402

def discover_plugins(plugin_folder=None, load_plugins=True):
    """Facade that injects SimpleWebCrawler into the extracted discover_plugins."""
    return _discover_plugins(plugin_folder=plugin_folder, load_plugins=load_plugins, web_crawler_cls=SimpleWebCrawler)

from ollama_chat_lib.memory import MemoryManager as _MemoryManager, LongTermMemoryManager as _LongTermMemoryManager  # noqa: E402

class MemoryManager(_MemoryManager):
    """Thin shim that auto-injects ask_fn=ask_ollama."""
    def __init__(self, collection_name, chroma_client, selected_model, embedding_model_name, verbose=False, num_ctx=None, long_term_memory_file="long_term_memory.json", ask_fn=None):
        super().__init__(collection_name, chroma_client, selected_model, embedding_model_name,
                         verbose=verbose, num_ctx=num_ctx, long_term_memory_file=long_term_memory_file,
                         ask_fn=ask_fn or ask_ollama)

class LongTermMemoryManager(_LongTermMemoryManager):
    """Thin shim that auto-injects ask_fn=ask_ollama."""
    def __init__(self, selected_model, verbose=False, num_ctx=None, memory_file="long_term_memory.json", ask_fn=None):
        super().__init__(selected_model, verbose=verbose, num_ctx=num_ctx, memory_file=memory_file,
                         ask_fn=ask_fn or ask_ollama)

def retrieve_relevant_memory(query_text, top_k=3):

    if not state.memory_manager:
        return []

    return state.memory_manager.retrieve_relevant_memory(query_text, top_k)

from ollama_chat_lib.document_indexer import DocumentIndexer as _DocumentIndexer  # noqa: E402

class DocumentIndexer(_DocumentIndexer):
    """Thin shim that auto-injects ask_fn=ask_ollama."""
    def __init__(self, root_folder, collection_name, chroma_client, embeddings_model, verbose=False, summary_model=None, ask_fn=None):
        super().__init__(root_folder, collection_name, chroma_client, embeddings_model,
                         verbose=verbose, summary_model=summary_model,
                         ask_fn=ask_fn or ask_ollama)

from ollama_chat_lib.agent import split_reasoning_and_final_response, Agent as _Agent  # noqa: E402

class Agent(_Agent):
    """Thin shim that auto-injects ask_fn=ask_ollama."""
    def __init__(self, name, description, model, thinking_model=None, system_prompt=None, temperature=0.7, max_iterations=15, tools=None, verbose=False, num_ctx=None, thinking_model_reasoning_pattern=None, ask_fn=None):
        super().__init__(name, description, model, thinking_model=thinking_model, system_prompt=system_prompt,
                         temperature=temperature, max_iterations=max_iterations, tools=tools, verbose=verbose,
                         num_ctx=num_ctx, thinking_model_reasoning_pattern=thinking_model_reasoning_pattern,
                         ask_fn=ask_fn or ask_ollama)

from ollama_chat_lib.llm_core import (
    ask_openai_responses_api as _ask_openai_responses_api,
    ask_openai_with_conversation as _ask_openai_with_conversation,
    handle_tool_response as _handle_tool_response,
    ask_ollama_with_conversation as _ask_ollama_with_conversation,
    ask_ollama as _ask_ollama,
    generate_tool_response as _generate_tool_response,
    create_new_agent_with_tools as _create_new_agent_with_tools,
    instantiate_agent_with_tools_and_process_task as _instantiate_agent_with_tools_and_process_task,
)

def create_new_agent_with_tools(system_prompt: str, tools: list[str], agent_name: str, agent_description: str, task: str = None):
    return _create_new_agent_with_tools(system_prompt, tools, agent_name, agent_description, task=task,
                                         get_available_tools_fn=get_available_tools, load_chroma_client_fn=load_chroma_client, agent_cls=Agent)

def instantiate_agent_with_tools_and_process_task(task: str, system_prompt: str, tools: list[str], agent_name: str, agent_description: str = None, process_task=True):
    return _instantiate_agent_with_tools_and_process_task(task, system_prompt, tools, agent_name, agent_description=agent_description, process_task=process_task,
                                                           get_available_tools_fn=get_available_tools, load_chroma_client_fn=load_chroma_client, agent_cls=Agent)

from ollama_chat_lib.file_ops import read_file, create_file, delete_file, expand_env_vars, run_command  # noqa: E402

def web_search(query=None, n_results=5, region="wt-wt", web_embedding_model=None, num_ctx=None, return_intermediate=False):
    return _web_search(query=query, n_results=n_results, region=region, web_embedding_model=web_embedding_model, num_ctx=num_ctx, return_intermediate=return_intermediate,
                       ask_fn=ask_ollama, query_vector_database_fn=query_vector_database, web_crawler_cls=SimpleWebCrawler,
                       document_indexer_cls=DocumentIndexer, load_chroma_client_fn=load_chroma_client)

# chatbots data, load_additional_chatbots, split_numbered_list, prompt_for_chatbot
# → imported from ollama_chat_lib.conversation
state.chatbots = list(DEFAULT_CHATBOTS)

# vector_db functions → imported from ollama_chat_lib.vector_db

def query_vector_database(question, collection_name=None, n_results=None, answer_distance_threshold=0, query_embeddings_model=None, expand_query=True, question_context=None, use_adaptive_filtering=True, return_metadata=False):
    return _query_vector_database(question, collection_name=collection_name, n_results=n_results, answer_distance_threshold=answer_distance_threshold, query_embeddings_model=query_embeddings_model, expand_query=expand_query, question_context=question_context, use_adaptive_filtering=use_adaptive_filtering, return_metadata=return_metadata, ask_fn=ask_ollama)

def ask_openai_responses_api(conversation, selected_model=None, temperature=0.1, tools=None):
    return _ask_openai_responses_api(conversation, selected_model=selected_model, temperature=temperature, tools=tools)

def ask_openai_with_conversation(conversation, selected_model=None, temperature=0.1, prompt_template=None, stream_active=True, tools=[]):
    return _ask_openai_with_conversation(conversation, selected_model=selected_model, temperature=temperature, prompt_template=prompt_template, stream_active=stream_active, tools=tools)

def handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools, stream_active, num_ctx=None):
    return _handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools, stream_active, num_ctx=num_ctx, globals_fn=lambda: globals())

def ask_ollama_with_conversation(conversation, model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True, prompt="Bot", prompt_color=None, num_ctx=None, use_think_mode=False):
    return _ask_ollama_with_conversation(conversation, model, temperature, prompt_template, tools, no_bot_prompt, stream_active, prompt=prompt, prompt_color=prompt_color, num_ctx=num_ctx, use_think_mode=use_think_mode, globals_fn=lambda: globals())

def ask_ollama(system_prompt, user_input, selected_model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True, num_ctx=None, use_think_mode=False):
    return _ask_ollama(system_prompt, user_input, selected_model, temperature=temperature, prompt_template=prompt_template, tools=tools, no_bot_prompt=no_bot_prompt, stream_active=stream_active, num_ctx=num_ctx, use_think_mode=use_think_mode, globals_fn=lambda: globals())

def generate_tool_response(user_input, tools, selected_model, temperature=0.1, prompt_template=None, num_ctx=None):
    return _generate_tool_response(user_input, tools, selected_model, temperature=temperature, prompt_template=prompt_template, num_ctx=num_ctx, globals_fn=lambda: globals())

# model selection functions → imported from ollama_chat_lib.model_selection
# save_conversation_to_file → imported from ollama_chat_lib.conversation
# load_chroma_client → imported from ollama_chat_lib.vector_db
def summarize_chunk(text_chunk, model, max_summary_words, previous_summary=None, num_ctx=None, language='English'):
    return _summarize_chunk(text_chunk, model, max_summary_words, previous_summary=previous_summary, num_ctx=num_ctx, language=language, ask_fn=ask_ollama)

def summarize_text_file(file_path, model=None, chunk_size=400, overlap=50, max_final_words=500, num_ctx=None, language='English'):
    return _summarize_text_file(file_path, model=model, chunk_size=chunk_size, overlap=overlap, max_final_words=max_final_words, num_ctx=num_ctx, language=language, ask_fn=ask_ollama)

def run():
    import sys
    from ollama_chat_lib.run_helpers import parse_args, initialize, main_loop

    args = parse_args()
    ctx = initialize(args, sys.modules[__name__])
    if ctx is None:
        return
    main_loop(ctx, sys.modules[__name__])


if __name__ == "__main__":
    run()
