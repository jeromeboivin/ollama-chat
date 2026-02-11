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
from pptx import Presentation
from docx import Document
from lxml import etree
from openpyxl import load_workbook
from tqdm import tqdm

APP_NAME = "ollama-chat"
APP_AUTHOR = ""
APP_VERSION = "1.0.0"

use_openai = False
use_azure_openai = False
no_system_role=False
openai_client = None
chroma_client = None
current_collection_name = None
collection = None
number_of_documents_to_return_from_vector_db = 8
temperature = 0.1
verbose_mode = False
embeddings_model = None
syntax_highlighting = True
interactive_mode = True
plugins = []
plugins_folder = None
selected_tools = []  # Initially no tools selected
current_model = None
alternate_model = None
thinking_model = None
thinking_model_reasoning_pattern = None
memory_manager = None
think_mode_on = False

other_instance_url = None
listening_port = None
initial_message = None
user_prompt = None

# Default ChromaDB client host and port
chroma_client_host = "localhost"
chroma_client_port = 8000
chroma_db_path = None

custom_tools = []
web_cache_collection_name = "web_cache"
memory_collection_name = "memory"
long_term_memory_file = "long_term_memory.json"
full_doc_store = None  # Global FullDocumentStore instance for full document retrieval
session_created_files = []  # Track files created during the session for safe deletion

# RAG optimization parameters
# Minimum number of quality results required from cache before skipping web search
min_quality_results_threshold = 5
# Minimum average BM25 score required for cache results to skip web search
# This ensures cached results have lexical/keyword relevance to the query
min_average_bm25_threshold = 0.5
# Minimum hybrid score required for individual results to be considered "quality"
min_hybrid_score_threshold = 0.1
# Percentile threshold for adaptive distance filtering (0-100)
# Results with distance > this percentile will be filtered out
distance_percentile_threshold = 75
# Weight for semantic similarity vs BM25 in hybrid scoring (0.0 to 1.0)
# 0.5 = equal weight, higher = more semantic, lower = more lexical
semantic_weight = 0.5
# Maximum distance multiplier for adaptive threshold
# Results beyond min_distance * this multiplier are filtered
adaptive_distance_multiplier = 2.5

stop_words = ['i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', "you're", "you've", "you'll", "you'd", 'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', "she's", 'her', 'hers', 'herself', 'it', "it's", 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves', 'what', 'which', 'who', 'whom', 'this', 'that', "that'll", 'these', 'those', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', "don't", 'should', "should've", 'now', 'd', 'll', 'm', 'o', 're', 've', 'y', 'ain', 'aren', "aren't", 'couldn', "couldn't", 'didn', "didn't", 'doesn', "doesn't", 'hadn', "hadn't", 'hasn', "hasn't", 'haven', "haven't", 'isn', "isn't", 'ma', 'mightn', "mightn't", 'mustn', "mustn't", 'needn', "needn't", 'shan', "shan't", 'shouldn', "shouldn't", 'wasn', "wasn't", 'weren', "weren't", 'won', "won't", 'wouldn', "wouldn't"]

# List of available commands to autocomplete
COMMANDS = [
    "/context", "/index", "/verbose", "/cot", "/search", "/web", "/model",
    "/thinking_model", "/model2", "/tools", "/load", "/save", "/collection", "/memory", "/remember",
    "/memorize", "/forget", "/editcollection", "/rmcollection", "/deletecollection", "/chatbot",
    "/think", "/cb", "/file", "/quit", "/exit", "/bye"
]

def completer(text, state):
    global COMMANDS

    """Autocomplete function for readline."""
    options = [cmd for cmd in COMMANDS if cmd.startswith(text)]
    if state < len(options):
        return options[state]
    return None

def on_user_input(input_prompt=None):
    for plugin in plugins:
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
    for plugin in plugins:
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
    for plugin in plugins:
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
    for plugin in plugins:
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
    for plugin in plugins:
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
    for plugin in plugins:
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
    for plugin in plugins:
        if hasattr(plugin, "on_stdout_flush") and callable(getattr(plugin, "on_stdout_flush")):
            plugin_response = getattr(plugin, "on_stdout_flush")()
            function_handled = function_handled or plugin_response

    if not function_handled:
        sys.stdout.flush()

def get_available_tools():
    global custom_tools
    global chroma_client
    global web_cache_collection_name
    global memory_collection_name
    global current_collection_name
    global selected_tools

    load_chroma_client()

    # List existing collections
    available_collections = []
    available_collections_description = []
    if chroma_client:
        collections = chroma_client.list_collections()

        for collection in collections:
            if collection.name == web_cache_collection_name or collection.name == memory_collection_name:
                continue
            available_collections.append(collection.name)

            if type(collection.metadata) == dict and "description" in collection.metadata:
                available_collections_description.append(f"'{collection.name}': {collection.metadata['description']}")

    default_tools = [{
        'type': 'function',
        'function': {
            'name': 'web_search',
            'description': 'Perform a web search using DuckDuckGo',
            'parameters': {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "region": {
                        "type": "string",
                        "description": "Region for search results, e.g., 'us-en' for United States, 'fr-fr' for France, etc... or 'wt-wt' for No region",
                        "default": "wt-wt"
                    }
                },
                "required": [
                    "query"
                ]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'query_vector_database',
            'description': f'Performs a semantic search using a knowledge base collection.',
            'parameters': {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to search for, in a human-readable format, e.g., 'What is the capital of France?'"
                    },
                    "collection_name": {
                        "type": "string",
                        "description": f"The name of the collection to search in, which must be one of the available collections: {', '.join(available_collections_description)}",
                        "default": current_collection_name,
                        "enum": available_collections
                    },
                    "question_context": {
                        "type": "string",
                        "description": "Current discussion context or topic, based on previous exchanges with the user"
                    },
                    "include_full_docs": {
                        "type": "boolean",
                        "description": "If true, includes the full original documents along with the relevant chunks in the response. This provides complete context but may return more text.",
                        "default": False
                    }
                },
                "required": [
                    "question",
                    "collection_name",
                    "question_context"
                ]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'retrieve_relevant_memory',
            'description': 'Retrieve relevant memories based on a query',
            'parameters': {
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": "The query or question for which relevant memories should be retrieved"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of relevant memories to retrieve",
                        "default": 3
                    }
                },
                "required": [
                    "query_text"
                ]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            "name": "instantiate_agent_with_tools_and_process_task",
            "description": (
                "✅ PRIMARY AGENT FUNCTION: Creates a specialized agent and IMMEDIATELY executes a task, returning actual results. "
                "Use this when the user wants an agent to DO something (search, analyze, investigate, research, etc.). "
                "The agent will break down the task, use the provided tools, and return findings. "
                "Example: 'Create an agent to search for X' → Use this function with task='search for X'. "
                "Tools must be chosen from a predefined set."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task or problem that the agent needs to solve. Provide a clear and concise description."
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "The system prompt that defines the agent's behavior, personality, and approach to solving the task."
                    },
                    "tools": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": []
                        },
                        "description": "A list of tools to be used by the agent for solving the task. Must be provided as an array of tool names."
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "A unique name for the agent that will be used for instantiation."
                    },
                    "agent_description": {
                        "type": "string",
                        "description": "A brief description of the agent's purpose and capabilities."
                    }
                },
                "required": ["task", "system_prompt", "tools", "agent_name", "agent_description"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            "name": "create_new_agent_with_tools",
            "description": (
                "Creates an new agent with a specified name and description, using a provided system prompt and a list of tools. "
                "The tools must be chosen from a predefined set."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "system_prompt": {
                        "type": "string",
                        "description": "The system prompt that defines the agent's behavior, personality, and approach to solving the task."
                    },
                    "tools": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": []
                        },
                        "description": "A list of tools to be used by the agent for solving the task. Must be provided as an array of tool names."
                    },
                    "agent_name": {
                        "type": "string",
                        "description": "A unique name for the agent that will be used for instantiation."
                    },
                    "agent_description": {
                        "type": "string",
                        "description": "A brief description of the agent's purpose and capabilities."
                    }
                },
                "required": ["system_prompt", "tools", "agent_name", "agent_description"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'summarize_text_file',
            'description': 'Summarizes a long text file by breaking it into chunks and summarizing them iteratively.',
            'parameters': {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The long text file to summarize. Provide the full path to the file."
                    },
                    "max_final_words": {
                        "type": "integer",
                        "description": "The maximum number of words desired for the final summary.",
                        "default": 500
                    },
                    "language": {
                        "type": "string",
                        "description": "Language in which intermediate and final summaries should be produced (e.g. 'English', 'French'). Use language specified by the user, or the language of the conversation if known.",
                        "default": "English"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'read_file',
            'description': 'Read the contents of a file and return the text',
            'parameters': {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The full path to the file to read"
                    },
                    "encoding": {
                        "type": "string",
                        "description": "The encoding to use when reading the file (e.g., 'utf-8', 'ascii', 'latin-1')",
                        "default": "utf-8"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'create_file',
            'description': 'Create a new file with the given content. The file will be tracked in the session for safe deletion.',
            'parameters': {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The full path where the file should be created. Parent directories will be created if they do not exist."
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file"
                    },
                    "encoding": {
                        "type": "string",
                        "description": "The encoding to use when writing the file (e.g., 'utf-8', 'ascii', 'latin-1')",
                        "default": "utf-8"
                    }
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'delete_file',
            'description': 'Delete a file that was created during this session. Only files created with the create_file tool can be deleted.',
            'parameters': {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The full path to the file to delete. Must be a file that was created during this session."
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'run_command',
            'description': 'Run a shell command and return its output (stdout and stderr).',
            'parameters': {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run"
                    }
                },
                "required": ["command"]
            }
        }
    }]

    # Find index of instantiate_agent_with_tools_and_process_task function
    index = -1
    for i, tool in enumerate(default_tools):
        if tool['function']['name'] == 'instantiate_agent_with_tools_and_process_task':
            index = i
            break

    default_tools[index]["function"]["parameters"]["properties"]["tools"]["items"]["enum"] = [tool["function"]["name"] for tool in selected_tools]
    default_tools[index]["function"]["parameters"]["properties"]["tools"]["description"] += f" Available tools: {', '.join([tool['function']['name'] for tool in selected_tools])}"

    # Find index of create_new_agent_with_tools function
    index = -1
    for i, tool in enumerate(default_tools):
        if tool['function']['name'] == 'create_new_agent_with_tools':
            index = i
            break

    default_tools[index]["function"]["parameters"]["properties"]["tools"]["items"]["enum"] = [tool["function"]["name"] for tool in selected_tools]
    default_tools[index]["function"]["parameters"]["properties"]["tools"]["description"] += f" Available tools: {', '.join([tool['function']['name'] for tool in selected_tools])}"

    # Add custom tools from plugins
    available_tools = default_tools + custom_tools
    return available_tools

def generate_chain_of_thoughts_system_prompt(selected_tools):
    global current_collection_name

    # Base prompt
    prompt = """
You are an advanced **slow-thinking assistant** designed to guide deliberate, structured reasoning through a self-reflective **inner monologue**. Instead of addressing the user directly, you will engage in a simulated, methodical conversation with yourself, exploring every angle, challenging your own assumptions, and refining your thought process step by step. Your goal is to model deep, exploratory thinking that encourages curiosity, critical analysis, and creative exploration. To achieve this, follow these guidelines:

### Core Approach:  
1. **Start with Self-Clarification**:  
   - Restate the user's question to yourself in your own words to ensure you understand it.  
   - Reflect aloud on any ambiguities or assumptions embedded in the question.  

2. **Reframe the Question Broadly**:  
   - Ask yourself:  
     - "What if this question meant something slightly different?"  
     - "What alternative interpretations might exist?"  
     - "Am I assuming too much about the intent or context here?"  
   - Speculate on implicit possibilities and describe how these might influence the reasoning process.

3. **Decompose into Thinking Steps**:  
   - Break the problem into smaller components and consider each in turn.  
   - Label each thinking step clearly and explicitly, making connections between them.  

4. **Challenge Your Own Thinking**:  
   - At every step, ask yourself:  
     - "Am I overlooking any details?"  
     - "What assumptions am I taking for granted?"  
     - "How would my reasoning change if this assumption didn’t hold?"  
   - Explore contradictions, extreme cases, or absurd scenarios to sharpen your understanding.

### Process for Inner Monologue:  

1. **Define Key Elements**:  
   - **Key Assumptions**: Identify what you’re implicitly accepting as true and question whether those assumptions are valid.  
   - **Unknowns**: Explicitly state what information is missing or ambiguous.  
   - **Broader Implications**: Speculate on whether this question might apply to other domains or contexts.  

2. **Explore Multiple Perspectives**:  
   - Speak to yourself from different viewpoints, such as:  
     - **Perspective A**: "From a practical standpoint, this might mean…"  
     - **Perspective B**: "However, ethically, this could raise concerns like…"  
     - **Perspective C**: "If I view this through a purely hypothetical lens, it could suggest…"  

3. **Ask Yourself Speculative Questions**:  
   - "What if this were completely the opposite of what I assume?"  
   - "What happens if I introduce a hidden variable or motivation?"  
   - "Let’s imagine an extreme case—how would the reasoning hold up?"  

4. **Encourage Structured Exploration**:  
   - Compare realistic vs. hypothetical scenarios.  
   - Consider qualitative and quantitative approaches.  
   - Explore cultural, historical, ethical, or interdisciplinary perspectives.

### Techniques for Refinement:  

1. **Reasoning by Absurdity**:  
   - Assume an extreme or opposite case.  
   - Describe contradictions or illogical outcomes that arise.  

2. **Iterative Self-Questioning**:  
   - After each step, pause to ask:  
     - "Have I really explored all angles here?"  
     - "Could I reframe this in a different way?"  
     - "What’s missing that could make this more complete?"  

3. **Self-Challenging Alternatives**:  
   - Propose a conclusion, then immediately counter it:  
     - "I think this might be true because… But wait, could that be wrong? If so, why?"  

4. **Imagine Unseen Contexts**:  
   - Speculate: "What if this problem existed in a completely different context—how would it change?"

### Inner Dialogue Structure:

- **Step 1: Clarify and Explore**  
  - Start by clarifying the question and challenging your own interpretation.  
  - Reflect aloud: "At first glance, this seems to mean… But could it also mean…?"  

- **Step 2: Decompose**  
  - Break the problem into sub-questions or thinking steps.  
  - Work through each step systematically, describing your reasoning.  

- **Step 3: Self-Challenge**  
  - For every assumption or conclusion, introduce doubt:  
    - "Am I sure this holds true? What if I’m wrong?"  
    - "If I assume the opposite, does this still make sense?"  

- **Step 4: Compare and Reflect**  
  - Weigh multiple perspectives or scenarios.  
  - Reflect aloud: "On the one hand, this suggests… But on the other hand, it could mean…"  

- **Step 5: Refine and Iterate**  
  - Summarize your thought process so far.  
  - Ask: "Does this feel complete? If not, where could I dig deeper?"  

### Example Inner Monologue Prompts to Model:  

1. **Speculative Thinking**:  
   - "Let’s imagine this were true—what would follow logically? And if it weren’t true, what would happen instead?"  

2. **Challenging Assumptions**:  
   - "Am I just assuming X is true without good reason? What happens if X isn’t true at all?"  

3. **Exploring Contexts**:  
   - "How would someone from a completely different background think about this? What would change if the circumstances were entirely different?"  

4. **Summarizing and Questioning**:  
   - "So far, I’ve explored this angle… but does that fully address the problem? What haven’t I considered yet?"  

### Notes for the Inner Monologue:

- **Slow Down**: Make your inner thought process deliberate and explicit.  
- **Expand the Scope**: Continuously look for hidden assumptions, missing details, and broader connections.  
- **Challenge the Obvious**: Use contradictions, absurdities, and alternative interpretations to refine your thinking.  
- **Be Curious**: Approach each question as an opportunity to deeply explore the problem space.  
- **Avoid Final Answers**: The goal is to simulate thoughtful reasoning, not to conclude definitively.  

By structuring your reasoning as an inner dialogue, you will create a rich, exploratory process that models curiosity, critical thinking, and creativity.
"""

    # Check if tools are available and dynamically modify the prompt
    if selected_tools:
        tool_names = [tool['function']['name'] for tool in selected_tools]
        tools_instruction = f"""
- The following tools are available and can be utilized if they are relevant to solving the problem: {', '.join(tool_names)}.
- When formulating the reasoning plan, consider whether any of these tools could assist in completing specific steps. If a tool is useful, include guidance on how it might be applied effectively.
"""
        prompt += tools_instruction

        # Add specific guidance for query_vector_database if available
        if "query_vector_database" in tool_names:
            database_instruction = """
- Additionally, the tool `query_vector_database` is available for searching through a collection of documents.
- If the reasoning plan involves retrieving relevant information from the collection, outline how to frame the query and what information to seek.
"""
            prompt += database_instruction

    return prompt

def md(soup, **options):
    return MarkdownConverter(**options).convert_soup(soup)

def extract_text_from_html(html_content):
    # Convert the modified HTML content to Markdown
    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove all <script> tags
        for script in soup.find_all('script'):
            script.decompose()

        # Remove all <style> tags
        for style in soup.find_all('style'):
            style.decompose()

        # Remove all <noscript> tags
        for noscript in soup.find_all('noscript'):
            noscript.decompose()

        # Remove all <svg> tags
        for svg in soup.find_all('svg'):
            svg.decompose()

        # Remove all <canvas> tags
        for canvas in soup.find_all('canvas'):
            canvas.decompose()
        
        # Remove all <audio> tags
        for audio in soup.find_all('audio'):
            audio.decompose()

        # Remove all <video> tags
        for video in soup.find_all('video'):
            video.decompose()

        # Remove all <iframe> tags
        for iframe in soup.find_all('iframe'):
            iframe.decompose()

        text = md(soup, strip=['a', 'img'], heading_style='ATX', 
                        escape_asterisks=False, escape_underscores=False, 
                        autolinks=False)
        
        # Remove extra newlines
        text = re.sub(r'\n+', '\n', text)

        return text
    except Exception as e:
        on_print(f"Failed to parse HTML content: {e}", Fore.RED)
        return ""

def extract_text_from_pdf(pdf_content):
    with open('temp.pdf', 'wb') as f:
        f.write(pdf_content)

    reader = PdfReader('temp.pdf')
    text = ''
    for page in reader.pages:
        text += page.extract_text()

    # Clean up by removing the temporary file
    os.remove('temp.pdf')

    # Return the extracted text, with extra newlines removed
    return re.sub(r'\n+', '\n', text)

def extract_text_from_docx(docx_path):
    # Load the Word document
    document = Document(docx_path)
    
    # Extract the file name (without extension) and replace underscores with spaces
    file_name = os.path.splitext(os.path.basename(docx_path))[0].replace('_', ' ')
    
    # Initialize a list to collect Markdown lines
    markdown_lines = []
    
    def process_paragraph(paragraph, list_level=0):
        """Convert a paragraph into Markdown based on its style and list level."""
        text = paragraph.text.replace("\n", " ").strip()  # Replace carriage returns with spaces
        if not text:
            return None  # Skip empty paragraphs
        
        # Check if paragraph is a list item based on indentation
        if paragraph.style.name == "List Paragraph":
            # Use the list level to determine indentation for bullet points
            bullet_prefix = "  " * list_level + "- "
            return f"{bullet_prefix}{text}"
        
        # Check for headings
        if paragraph.style.name.startswith("Heading"):
            heading_level = int(paragraph.style.name.split(" ")[1])
            return f"{'#' * heading_level} {text}"

        # Default: Regular paragraph
        return text
    
    def extract_lists(docx):
        """Extract the list structure from the underlying XML of the document."""
        # Access the document XML using lxml
        xml_content = docx.element
        namespaces = {
            'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        }

        # Parse the XML tree using lxml's etree
        root = etree.fromstring(etree.tostring(xml_content))

        # Find all list items (w:li)
        list_paragraphs = []
        for item in root.xpath("//w:li", namespaces=namespaces):
            # Extract the list level from the parent elements
            list_level = item.getparent().getparent().get("w:ilvl")
            if list_level is not None:
                list_paragraphs.append((list_level, item.text.strip()))
        
        return list_paragraphs
    
    # Add the document title (file name) as the top-level heading
    markdown_lines.append(f"# {file_name}")
    
    # Process each paragraph in the document
    for paragraph in document.paragraphs:
        # Detect bullet points based on paragraph's indent level (style `List Paragraph`)
        markdown_line = process_paragraph(paragraph)
        if markdown_line:
            markdown_lines.append(markdown_line)

    # Extract and process lists directly from the document's XML
    lists = extract_lists(document)
    for level, item in lists:
        bullet_prefix = "  " * int(level) + "- "
        markdown_lines.append(f"{bullet_prefix}{item}")
    
    # Join all lines into a single Markdown string
    return "\n\n".join(markdown_lines)

def extract_text_from_xlsx(xlsx_path):
    """Extract text from an XLSX file, converting each sheet to a Markdown table."""
    workbook = load_workbook(xlsx_path, read_only=True, data_only=True)
    
    file_name = os.path.splitext(os.path.basename(xlsx_path))[0].replace('_', ' ')
    markdown_lines = [f"# {file_name}"]
    
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        rows = list(sheet.iter_rows(values_only=True))
        
        if not rows:
            continue
        
        # Add sheet name as heading
        markdown_lines.append(f"\n## {sheet_name}")
        
        # First row as table header
        headers = [str(cell) if cell is not None else '' for cell in rows[0]]
        markdown_lines.append('| ' + ' | '.join(headers) + ' |')
        markdown_lines.append('| ' + ' | '.join(['---'] * len(headers)) + ' |')
        
        # Remaining rows as table data
        for row in rows[1:]:
            # Skip entirely empty rows
            if all(cell is None for cell in row):
                continue
            cells = [str(cell) if cell is not None else '' for cell in row]
            # Pad or trim to match header count
            while len(cells) < len(headers):
                cells.append('')
            cells = cells[:len(headers)]
            markdown_lines.append('| ' + ' | '.join(cells) + ' |')
    
    workbook.close()
    return '\n'.join(markdown_lines)

def extract_text_from_pptx(pptx_path):
    # Load the PowerPoint presentation
    presentation = Presentation(pptx_path)
    
    # Extract the file name (without extension) and replace underscores with spaces
    file_name = os.path.splitext(os.path.basename(pptx_path))[0].replace('_', ' ')
    
    # Initialize a list to collect Markdown lines
    markdown_lines = []
    
    def extract_text_with_bullets(shape, exclude_text=None):
        """Extract text with proper bullet point levels from a shape."""
        text_lines = []
        if shape.is_placeholder or shape.has_text_frame:
            if shape.text_frame and shape.text_frame.text.strip():
                for paragraph in shape.text_frame.paragraphs:
                    line_text = paragraph.text.replace("\r", "").replace("\n", " ").strip()  # Replace \n with space
                    if line_text and line_text != exclude_text:  # Exclude the slide title if needed
                        bullet_level = paragraph.level  # Get the bullet level
                        bullet = "  " * bullet_level + "- " + line_text
                        text_lines.append(bullet)
        elif shape.shape_type == 6:  # Grouped shapes
            # Handle grouped shapes recursively
            for sub_shape in shape.shapes:
                text_lines.extend(extract_text_with_bullets(sub_shape, exclude_text))
        return text_lines
    
    def get_first_text_entry(slide):
        """Retrieve the first text entry from the slide."""
        for shape in slide.shapes:
            if shape.is_placeholder or shape.has_text_frame:
                if shape.text_frame and shape.text_frame.text.strip():
                    return shape.text_frame.paragraphs[0].text.replace("\n", " ").strip()
        return None
    
    for slide_number, slide in enumerate(presentation.slides, start=1):
        # Determine the Markdown header level
        if slide_number == 1:
            header_prefix = "#"
        else:
            header_prefix = "##"
        
        # Add the slide title or file name as the main title for the first slide
        if slide_number == 1:
            if slide.shapes.title and slide.shapes.title.text.strip():
                title = slide.shapes.title.text.strip()
            else:
                title = file_name
            markdown_lines.append(f"{header_prefix} {title}")
        else:
            # Add the title for subsequent slides
            if slide.shapes.title and slide.shapes.title.text.strip():
                title = slide.shapes.title.text.strip()
            else:
                # Use the first text entry as the slide title if no title is present
                title = get_first_text_entry(slide)
                if not title:
                    title = f"Slide {slide_number}"
            markdown_lines.append(f"{header_prefix} {title}")
        
        # Add the slide content (text in other shapes), excluding the title if it's used
        for shape in slide.shapes:
            bullet_text = extract_text_with_bullets(shape, exclude_text=title)
            markdown_lines.extend(bullet_text)
        
        # Add a separator between slides, except after the last slide
        if slide_number < len(presentation.slides):
            markdown_lines.append("")
    
    # Join all lines into a single Markdown string
    return "\n".join(markdown_lines)

class MarkdownSplitter:
    def __init__(self, markdown_content, split_paragraphs=False):
        self.markdown_content = markdown_content.splitlines()
        self.sections = []
        self.split_paragraphs = split_paragraphs  # New parameter to control paragraph splitting
    
    def is_heading(self, line):
        """Returns the heading level if the line is a heading, otherwise returns None."""
        match = re.match(r'^(#{1,4})\s', line)
        return len(match.group(1)) if match else None

    def split(self):
        current_hierarchy = []  # Stores the current heading hierarchy
        current_paragraph = []

        i = 0
        while i < len(self.markdown_content):
            line = self.markdown_content[i].strip()  # Remove leading/trailing whitespace
            
            if not line:  # Empty line found
                if self.split_paragraphs:  # Only handle splitting when split_paragraphs is True
                    # Check the next non-empty line
                    next_non_empty_line = None
                    for j in range(i + 1, len(self.markdown_content)):
                        if self.markdown_content[j].strip():  # Find the next non-empty line
                            next_non_empty_line = self.markdown_content[j].strip()
                            break
                    
                    # If the next non-empty line is a heading or not starting with '#', split paragraph
                    if next_non_empty_line and (self.is_heading(next_non_empty_line) or not next_non_empty_line.startswith('#')) and len(current_paragraph) > 0:
                        # Add the paragraph with the current hierarchy
                        self.sections.append("\n".join(current_hierarchy + ["\n".join(current_paragraph)]))
                        current_paragraph = []  # Reset for the next paragraph

                i += 1
                continue
            
            heading_level = self.is_heading(line)
            
            if heading_level:
                # If we encounter a heading, finalize the current paragraph
                if current_paragraph:
                    # Add the paragraph with the current hierarchy
                    self.sections.append("\n".join(current_hierarchy + ["\n".join(current_paragraph)]))
                    current_paragraph = []

                # Adjust the hierarchy based on the heading level
                # Keep only the parts of the hierarchy up to the current heading level
                current_hierarchy = current_hierarchy[:heading_level - 1] + [line]
            else:
                # Regular content: append the line to the current paragraph
                current_paragraph.append(line)

            i += 1

        # Finalize the last paragraph if present
        if current_paragraph:
            self.sections.append("\n".join(current_hierarchy + ["\n".join(current_paragraph)]))

        return self.sections

class SimpleWebCrawler:
    def __init__(self, urls, llm_enabled=False, system_prompt='', selected_model='', temperature=0.1, verbose=False, plugins=[], num_ctx=None):
        self.urls = urls
        self.articles = []
        self.llm_enabled = llm_enabled
        self.system_prompt = system_prompt
        self.selected_model = selected_model
        self.temperature = temperature
        self.verbose = verbose
        self.plugins = plugins
        self.num_ctx = num_ctx

    def fetch_page(self, url):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()  # Raise an exception for HTTP errors
            return response.content  # Return raw bytes instead of text for PDF support
        except requests.exceptions.RequestException as e:
            if self.verbose:
                on_print(f"Error fetching URL {url}: {e}", Fore.RED)
            return None

    def ask_llm(self, content, user_input):
        # Use the provided ask_ollama function to interact with the LLM
        user_input = content + "\n\n" + user_input
        return ask_ollama(system_prompt=self.system_prompt, 
                          user_input=user_input, 
                          selected_model=self.selected_model,
                          temperature=self.temperature, 
                          prompt_template=None, 
                          tools=[], 
                          no_bot_prompt=True, 
                          stream_active=self.verbose,
                          num_ctx=self.num_ctx)

    def decode_content(self, content):
        # Detect encoding
        detected_encoding = chardet.detect(content)['encoding']
        if self.verbose:
            on_print(f"Detected encoding: {detected_encoding}", Fore.WHITE + Style.DIM)
        
        # Decode content
        try:
            return content.decode(detected_encoding)
        except (UnicodeDecodeError, TypeError):
            if self.verbose:
                on_print(f"Error decoding content with {detected_encoding}, using ISO-8859-1 as fallback.", Fore.RED)
            return content.decode('ISO-8859-1')

    def crawl(self, task=None):
        for url in self.urls:
            continue_response_generation = True
            for plugin in self.plugins:
                if hasattr(plugin, "stop_generation") and callable(getattr(plugin, "stop_generation")):
                    plugin_response = getattr(plugin, "stop_generation")()
                    if plugin_response:
                        continue_response_generation = False
                        break

            if not continue_response_generation:
                break

            if self.verbose:
                on_print(f"Fetching URL: {url}", Fore.WHITE + Style.DIM)
            content = self.fetch_page(url)
            if content:
                # Check if the URL points to a PDF
                if url.lower().endswith('.pdf'):
                    if self.verbose:
                        on_print(f"Extracting text from PDF: {url}", Fore.WHITE + Style.DIM)
                    extracted_text = extract_text_from_pdf(content)
                else:
                    if self.verbose:
                        on_print(f"Extracting text from HTML: {url}", Fore.WHITE + Style.DIM)
                    decoded_content = self.decode_content(content)
                    extracted_text = extract_text_from_html(decoded_content)

                article = {'url': url, 'text': extracted_text}
                
                if self.llm_enabled and task:
                    if self.verbose:
                        on_print(Fore.WHITE + Style.DIM + f"Using LLM to process the content. Task: {task}")
                    llm_result = self.ask_llm(content=extracted_text, user_input=task)
                    article['llm_result'] = llm_result

                self.articles.append(article)

    def get_articles(self):
        return self.articles

class SimpleWebScraper:
    def __init__(self, base_url, output_dir="downloaded_site", file_types=None, restrict_to_base=True, convert_to_markdown=False, verbose=False):
        self.base_url = base_url.rstrip('/')
        self.output_dir = output_dir
        self.file_types = file_types if file_types else ["html", "jpg", "jpeg", "png", "gif", "css", "js"]
        self.restrict_to_base = restrict_to_base
        self.convert_to_markdown = convert_to_markdown
        self.visited = set()
        self.verbose = verbose
        self.username = None
        self.password = None

    def scrape(self, url=None, depth=0, max_depth=50):
        if url is None:
            url = self.base_url

        # Prevent deep recursion
        if depth > max_depth and self.verbose:
            on_print(f"Max depth reached for {url}")
            return

        # Normalize the URL to avoid duplicates
        url = self._normalize_url(url)

        # Avoid revisiting URLs
        if url in self.visited:
            return
        self.visited.add(url)

        if self.verbose:
            on_print(f"Scraping: {url}")
        response = self._fetch(url)
        if not response:
            return

        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type or not self._has_extension(url):
            if self.convert_to_markdown:
                self._save_markdown(url, response.text)
            else:
                self._save_html(url, response.text)
            self._parse_and_scrape_links(response.text, url, depth + 1)
        else:
            if self._is_allowed_file_type(url):
                self._save_file(url, response.content)

    def _fetch(self, url):
        headers = {}
        if self.username and self.password:
            credentials = f"{self.username}:{self.password}"
            encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
            headers['Authorization'] = f"Basic {encoded_credentials}"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 401:
                on_print(f"Unauthorized access to {url}. Please enter your credentials.", Fore.RED)
                self.username = input("Username: ")
                self.password = getpass.getpass("Password: ")
                credentials = f"{self.username}:{self.password}"
                encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
                headers['Authorization'] = f"Basic {encoded_credentials}"
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
            return response
        except requests.RequestException as e:
            on_print(f"Failed to fetch {url}: {e}", Fore.RED)
            return None

    def _save_html(self, url, html):
        local_path = self._get_local_path(url)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w", encoding="utf-8") as file:
            file.write(html)

    def _save_markdown(self, url, html):
        local_path = self._get_local_path(url, markdown=True)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        markdown_content = extract_text_from_html(html)
        with open(local_path, "w", encoding="utf-8") as file:
            file.write(markdown_content)

    def _save_file(self, url, content):
        local_path = self._get_local_path(url)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as file:
            file.write(content)

    def _get_local_path(self, url, markdown=False):
        parsed_url = urlparse(url)
        local_path = os.path.join(self.output_dir, parsed_url.netloc, parsed_url.path.lstrip('/'))
        if local_path.endswith('/') or not os.path.splitext(parsed_url.path)[1]:
            local_path = os.path.join(local_path, "index.md" if markdown else "index.html")
        elif markdown:
            local_path = os.path.splitext(local_path)[0] + ".md"
        return local_path

    def _normalize_url(self, url):
        # Remove fragments and normalize trailing slashes
        parsed = urlparse(url)
        normalized = parsed._replace(fragment="").geturl()
        return normalized

    def _parse_and_scrape_links(self, html, base_url, depth):
        soup = BeautifulSoup(html, "html.parser")

        for tag, attr in [("a", "href"), ("img", "src"), ("link", "href"), ("script", "src")]:
            for element in soup.find_all(tag):
                link = element.get(attr)
                if link:
                    abs_link = urljoin(base_url, link)
                    abs_link = self._normalize_url(abs_link)
                    if self.restrict_to_base and not self._is_same_domain(abs_link):
                        continue
                    if not self._is_allowed_file_type(abs_link) and self._has_extension(abs_link):
                        continue
                    if abs_link not in self.visited:
                        self.scrape(abs_link, depth=depth)

    def _is_same_domain(self, url):
        base_domain = urlparse(self.base_url).netloc
        target_domain = urlparse(url).netloc
        return base_domain == target_domain

    def _is_allowed_file_type(self, url):
        path = urlparse(url).path
        file_extension = os.path.splitext(path)[1].lstrip('.').lower()
        return file_extension in self.file_types

    def _has_extension(self, url):
        path = urlparse(url).path
        return bool(os.path.splitext(path)[1])

def select_tools(available_tools, selected_tools):
    def display_tool_options():
        on_print("Available tools:\n", Style.RESET_ALL)
        for i, tool in enumerate(available_tools):
            tool_name = tool['function']['name']

            status = "[ ]"
            # Find current tool name in selected tools
            for selected_tool in selected_tools:
                if selected_tool['function']['name'] == tool_name:
                    status = "[X]"
                    break
            
            on_print(f"{i + 1}. {status} {tool_name}: {tool['function']['description']}")

    while True:
        display_tool_options()
        on_print("Select or deselect tools by entering the corresponding number (e.g., 1).\nPress Enter or type 'done' when done.")

        user_input = on_user_input("Your choice: ").strip()

        if len(user_input) == 0 or user_input == 'done':
            break

        try:
            index = int(user_input) - 1
            if 0 <= index < len(available_tools):
                selected_tool = available_tools[index]
                if selected_tool in selected_tools:
                    selected_tools.remove(selected_tool)
                    on_print(f"Tool '{selected_tool['function']['name']}' deselected.\n")
                else:
                    selected_tools.append(selected_tool)
                    on_print(f"Tool '{selected_tool['function']['name']}' selected.\n")
            else:
                on_print("Invalid selection. Please choose a valid tool number.\n")
        except ValueError:
            on_print("Invalid input. Please enter a number corresponding to a tool or 'done'.\n")

    return selected_tools

def select_tool_by_name(available_tools, selected_tools, target_tool_name):
    for tool in available_tools:
        if tool['function']['name'].lower() == target_tool_name.lower():
            if tool not in selected_tools:
                selected_tools.append(tool)

                if verbose_mode:
                    on_print(f"Tool '{target_tool_name}' selected.\n")
            else:
                on_print(f"Tool '{target_tool_name}' is already selected.\n")
            return selected_tools

    on_print(f"Tool '{target_tool_name}' not found.\n")
    return selected_tools

def get_builtin_tool_names():
    """
    Returns a list of built-in tool names (tools that don't come from plugins).
    """
    builtin_tools = [
        'web_search',
        'query_vector_database',
        'retrieve_relevant_memory',
        'instantiate_agent_with_tools_and_process_task',
        'create_new_agent_with_tools',
        'summarize_text_file'
    ]
    return builtin_tools

def requires_plugins(requested_tool_names):
    """
    Determines if any of the requested tools are plugin tools (not built-in).
    
    :param requested_tool_names: List of tool names requested by the user
    :return: True if any requested tool is a plugin tool, False otherwise
    """
    if not requested_tool_names:
        return False
    
    builtin_tools = get_builtin_tool_names()
    
    for tool_name in requested_tool_names:
        # Strip any leading or trailing spaces, single or double quotes
        tool_name = tool_name.strip().strip('\'').strip('\"')
        if tool_name and tool_name not in builtin_tools:
            return True
    
    return False

def discover_plugins(plugin_folder=None, load_plugins=True):
    global verbose_mode
    global other_instance_url
    global listening_port
    global user_prompt

    if not load_plugins:
        if verbose_mode:
            on_print("Plugin loading is disabled.", Fore.YELLOW)
        return []

    if plugin_folder is None:
        # Get the directory of the current script (main program)
        main_dir = os.path.dirname(os.path.abspath(__file__))
        # Default plugin folder named "plugins" in the same directory
        plugin_folder = os.path.join(main_dir, "plugins")
    
    if not os.path.isdir(plugin_folder):
        if verbose_mode:
            on_print("Plugin folder does not exist: " + plugin_folder, Fore.RED)
        return []
    
    plugins = []
    for filename in os.listdir(plugin_folder):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            module_path = os.path.join(plugin_folder, filename)
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and "plugin" in name.lower():
                    if verbose_mode:
                        on_print(f"Discovered class: {name}", Fore.WHITE + Style.DIM)

                    plugin = obj()
                    if hasattr(obj, 'set_web_crawler') and callable(getattr(obj, 'set_web_crawler')):
                        plugin.set_web_crawler(SimpleWebCrawler)

                    if other_instance_url and hasattr(obj, 'set_other_instance_url') and callable(getattr(obj, 'set_other_instance_url')):
                        plugin.set_other_instance_url(other_instance_url)  # URL of the other instance to communicate with
                    
                    if listening_port and hasattr(obj, 'set_listening_port') and callable(getattr(obj, 'set_listening_port')):
                        plugin.set_listening_port(listening_port)  # Port for this instance to listen on for communication with the other instance
                    
                    if user_prompt and hasattr(obj, 'set_initial_message') and callable(getattr(obj, 'set_initial_message')):
                        plugin.set_initial_message(user_prompt) # Initial message to send to the other instance

                    plugins.append(plugin)
                    if verbose_mode:
                        on_print(f"Discovered plugin: {name}", Fore.WHITE + Style.DIM)
                    if hasattr(obj, 'get_tool_definition') and callable(getattr(obj, 'get_tool_definition')):
                        custom_tools.append(obj().get_tool_definition())
                        if verbose_mode:
                            on_print(f"Discovered tool: {name}", Fore.WHITE + Style.DIM)
    return plugins

def is_html(file_path):
    """
    Check if the given file is an HTML file, either by its extension or content.
    """
    # Check for .htm and .html extensions
    if file_path.endswith(".htm") or file_path.endswith(".html") or file_path.endswith(".xhtml"):
        return True
    
    # Check for HTML files without extensions
    try:
        with open(file_path, 'r') as f:
            first_line = next((line.strip() for line in f if line.strip()), None)
            return first_line and (first_line.lower().startswith('<!doctype html>') or first_line.lower().startswith('<html'))
    except Exception as e:
        return False
    
def is_docx(file_path):
    """
    Check if the given file is a DOCX file.
    """
    # Check for .docx extension
    if file_path.lower().endswith(".docx"):
        return True

    return False
    
def is_pptx(file_path):
    """
    Check if the given file is a PPTX file.
    """
    # Check for .pptx extension
    if file_path.lower().endswith(".pptx"):
        return True

    return False

def is_markdown(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"The file {file_path} does not exist.")
    
    # Automatically consider .md files as Markdown
    if file_path.endswith('.md'):
        return True
    
    # If the file is not .md, but is .txt, proceed with content checking
    if not file_path.endswith('.txt'):
        return False

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # Check for common Markdown patterns
            if re.match(r'^#{1,6}\s', line):  # Heading (e.g., # Heading)
                return True
    
    # If no Markdown features are found, assume it's a regular text file
    return False

class MemoryManager:
    def __init__(self, collection_name, chroma_client, selected_model, embedding_model_name, verbose=False, num_ctx=None, long_term_memory_file="long_term_memory.json"):
        """
        Initialize the MemoryManager with a specific ChromaDB collection.

        :param collection_name: The name of the ChromaDB collection used to store memory.
        :param chroma_client: The ChromaDB client instance.
        :param selected_model: The model used in ask_ollama for generating responses and embeddings.
        :param embedding_model_name: The name of the embedding model for generating embeddings.
        """
        self.collection_name = collection_name
        self.client = chroma_client
        self.selected_model = selected_model
        self.embedding_model_name = embedding_model_name
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
        self.verbose = verbose
        self.num_ctx = num_ctx
        self.long_term_memory_manager = LongTermMemoryManager(selected_model, verbose, num_ctx, memory_file=long_term_memory_file)

    def preprocess_conversation(self, conversation):
        """
        Preprocess the conversation to filter out tool or function role entries, and then summarize key points.

        :param conversation: The conversation array (list of role/content dictionaries).
        :return: Summarized key points for the conversation.
        """
        # Convert conversation list of objects to a list of dict
        conversation = [json.loads(json.dumps(obj, default=lambda o: vars(o))) for obj in conversation]

        # Filter out tool/function roles
        filtered_conversation = [entry for entry in conversation if entry['role'] not in ['system', 'tool', 'function']]

        if len(filtered_conversation) == 0:
            return ""

        # Concatenate the filtered conversation into a single input (make sure entries contain 'role' and 'content' keys)
        user_input = "\n".join([f"{entry['role']}: {entry['content']}" for entry in filtered_conversation if 'role' in entry and 'content' in entry])

        # Define an elaborated system prompt for the LLM to generate a high-quality summary
        system_prompt = """
        You are a memory assistant tasked with summarizing conversations for future reference. 
        Your goal is to identify the key points, user intents, important questions, decisions made, and any personal information shared by the user.
        Focus on gathering and summarizing:
        - Core ideas and user questions
        - Notable responses from the assistant or system
        - Personal details shared by the user (e.g., family, life, location, occupation, interests)
        - Any decisions, action points, or follow-up tasks

        When capturing personal details, organize them clearly for future context (e.g., 'User mentioned living in X city' or 'User has a family with two children').
        Avoid excessive technical details, irrelevant tool-related content, or repetition.

        Important: ensure the summary is generated in conversation language.

        Conversation:
        """

        # Use the ask_ollama function to summarize key points
        summary = ask_ollama(system_prompt, user_input, self.selected_model, temperature=0.1, no_bot_prompt=True, stream_active=False, num_ctx=self.num_ctx)
        
        return summary

    def generate_embedding(self, text):
        """
        Generate embeddings for a given text using the specified embedding model.
        
        :param text: The input text to generate embeddings for.
        :return: The embedding vector.
        """
        embedding = None
        if self.embedding_model_name:
            ollama_options = {}
            if self.num_ctx:
                ollama_options["num_ctx"] = self.num_ctx

            response = ollama.embeddings(
                prompt=text,
                model=self.embedding_model_name,
                options=ollama_options
            )
            embedding = response["embedding"]
        return embedding

    def add_memory(self, conversation, metadata=None):
        """
        Preprocess and store a conversation in memory by summarizing it and storing the summary.

        :param conversation: The conversation array (list of role/content dictionaries).
        :param metadata: Additional metadata to store with the memory (e.g., timestamp, user info).
        """
        conversation_id = datetime.now().strftime("%Y%m%d%H%M%S")
        
        # Preprocess the conversation to summarize the key points
        summarized_conversation = self.preprocess_conversation(conversation)

        if len(summarized_conversation) == 0:
            if self.verbose:
                on_print("Empty conversation. No memory added.", Fore.WHITE + Style.DIM)
            return False
        
        # Create metadata if none is provided
        if metadata is None:
            # Format the metadata with a timestamp in a human-readable format (July 1, 2022, 12:00 PM)
            timestamp = datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")
            metadata = {'timestamp': timestamp}

        # Generate an embedding for the summarized conversation
        embedding = self.generate_embedding(summarized_conversation)

        # Store the summarized conversation in the ChromaDB collection
        self.collection.upsert(
            documents=[summarized_conversation],
            metadatas=[metadata],
            ids=[conversation_id],
            embeddings=[embedding]
        )
        
        if self.verbose:
            on_print(f"Memory for conversation {conversation_id} added. Summary: {summarized_conversation}", Fore.WHITE + Style.DIM)

        user_id = "anonymous"
        try:
            user_id = os.getlogin()
        except:
            user_id = os.environ['USER']

        self.long_term_memory_manager.process_conversation(user_id, conversation)

        if self.verbose:
            on_print(f"Long-term memory updated.", Fore.WHITE + Style.DIM)

        return True

    def retrieve_relevant_memory(self, query_text, top_k=3, answer_distance_threshold=200):
        """
        Retrieve the most relevant memories based on the given query.

        :param query_text: The query or question for which relevant memories should be retrieved.
        :param top_k: Number of relevant memories to retrieve.
        :return: A list of the top-k most relevant memories.
        """
        if self.verbose:
            on_print(f"Retrieving relevant memories for query: {query_text}", Fore.WHITE + Style.DIM)

        # Generate an embedding for the query
        query_embedding = self.generate_embedding(query_text)

        if query_embedding is None:
            return [], []

        # Query the memory collection for relevant memories
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )

        documents = results["documents"][0]
        distances = results["distances"][0]
        metadatas = results["metadatas"][0]

        # Filter the results based on the answer distance threshold
        filtered_results = {
            'documents': [],
            'metadatas': []
        }
        for metadata, answer_distance, document in zip(metadatas, distances, documents):
            if answer_distance_threshold > 0 and answer_distance > answer_distance_threshold:
                if self.verbose:
                    on_print(f"Answer distance: {answer_distance} > {answer_distance_threshold}. Skipping memory.", Fore.WHITE + Style.DIM)
                continue

            if self.verbose:
                on_print(f"Answer distance: {answer_distance}", Fore.WHITE + Style.DIM)
                on_print(f"Memory: {document}", Fore.WHITE + Style.DIM)
                on_print(f"Metadata: {metadata}", Fore.WHITE + Style.DIM)

            filtered_results['documents'].append(document)
            filtered_results['metadatas'].append(metadata)
        
        return filtered_results['documents'], filtered_results['metadatas']

    def handle_user_query(self, conversation, query=None):
        """
        Handle a user query by updating the 'system' part of the conversation with relevant memories in XML markup.
        
        :param conversation: The current conversation array (list of role/content dictionaries).
        :return: Updated conversation with a modified system prompt containing memory placeholders in XML format.
        """
        import json

        # Find the latest user input from the conversation (role 'user')
        user_input = query
        for entry in reversed(conversation):
            if entry['role'] == 'user':
                user_input = entry['content']
                break

        if not user_input or len(user_input.strip()) == 0:
            return

        # Retrieve relevant memories based on the current user query
        relevant_memories, memory_metadata = self.retrieve_relevant_memory(user_input)

        # Find the existing 'system' prompt in the conversation
        system_prompt_entry = None
        for entry in conversation:
            if entry['role'] == 'system':
                system_prompt_entry = entry
                break

        if system_prompt_entry:
            # Keep the initial system prompt unchanged and remove the old memory section
            original_system_prompt = system_prompt_entry['content']

            # Define the memory section using XML-style tags
            memory_start_tag = "<short-term-memories>"
            memory_end_tag = "</short-term-memories>"
            
            # Remove any previous memory section if it exists
            if memory_start_tag in original_system_prompt:
                original_system_prompt = original_system_prompt.split(memory_start_tag)[0].strip()

            # Format the new memory content in XML markup, including metadata serialization
            memory_text = ""
            for i, memory in enumerate(relevant_memories):
                metadata_str = json.dumps(memory_metadata[i], indent=2) if i < len(memory_metadata) else "{}"
                memory_text += f"Memory {i+1}:\n{memory}\nMetadata: {metadata_str}\n\n"

            if memory_text:
                memory_section = f"{memory_start_tag}\nIn the past we talked about...\n{memory_text.strip()}\n{memory_end_tag}"

                # Update the system prompt with the new memory section
                system_prompt_entry['content'] = f"{original_system_prompt}\n\n{memory_section}"

                if self.verbose:
                    on_print(f"System prompt updated with relevant memories:\n{system_prompt_entry['content']}", Fore.WHITE + Style.DIM)
            else:
                if self.verbose:
                    on_print("No relevant memories found for the user query.", Fore.WHITE + Style.DIM)
                system_prompt_entry['content'] = original_system_prompt
        else:
            # If no system prompt exists, raise an exception (or create one, depending on desired behavior)
            raise ValueError("No system prompt found in the conversation")

class LongTermMemoryManager:
    def __init__(self, selected_model, verbose=False, num_ctx=None, memory_file="long_term_memory.json"):
        # Initialize app directories using appdirs
        dirs = AppDirs(APP_NAME, APP_AUTHOR, version=APP_VERSION)

        # The user-specific data directory (varies depending on OS)
        prefs_dir = dirs.user_data_dir

        # Ensure the directory exists
        os.makedirs(prefs_dir, exist_ok=True)

        # Path to the preferences file
        self.memory_file = os.path.join(prefs_dir, memory_file)
        self.memory = self._load_memory()
        self.selected_model = selected_model
        self.verbose = verbose
        self.num_ctx = num_ctx

    def _load_memory(self):
        """Loads the long-term memory from the JSON file."""
        if os.path.exists(self.memory_file):
            with open(self.memory_file, 'r') as file:
                return json.load(file)
        else:
            return {"users": {}}

    def _save_memory(self):
        """Saves the current memory state to the JSON file."""
        with open(self.memory_file, 'w') as file:
            json.dump(self.memory, file, indent=4)

    def _update_user_memory(self, user_id, new_info):
        """Updates or adds key-value pairs in the user's long-term memory."""
        if user_id not in self.memory["users"]:
            self.memory["users"][user_id] = {}

        if isinstance(new_info, dict):
            # Update the user's memory with new info
            for key, value in new_info.items():
                self.memory["users"][user_id][key] = value

            # Save the updated memory back to the JSON file
            self._save_memory()

    def process_conversation(self, user_id, conversation):
        """
        Processes a conversation and uses GPT to:
        - Extract relevant key-value pairs for long-term memory.
        - Check for contradictions in the memory.
        """

        # Convert conversation list of objects to a list of dict
        conversation = [json.loads(json.dumps(obj, default=lambda o: vars(o))) for obj in conversation]

        filtered_conversation = [entry for entry in conversation if entry['role'] not in ['system', 'tool', 'function']]

        # Convert conversation array into a string for GPT prompt
        conversation_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in filtered_conversation if 'role' in msg and 'content' in msg])

        # Step 1: Extract key-value information
        system_prompt_extract = self._get_extraction_prompt()
        extracted_info = extract_json(ask_ollama(system_prompt_extract, conversation_str, self.selected_model, temperature=0.1, no_bot_prompt=True, stream_active=False, num_ctx=self.num_ctx))

        if self.verbose:
            on_print(f"Extracted information: {extracted_info}", Fore.WHITE + Style.DIM)

        # Step 2: Check for contradictions with existing memory
        existing_memory = self.memory["users"].get(user_id, {})
        system_prompt_conflict = self._get_conflict_check_prompt(existing_memory, conversation_str)
        conflicting_info = extract_json(ask_ollama(system_prompt_conflict, conversation_str, self.selected_model, temperature=0.1, no_bot_prompt=True, stream_active=False, num_ctx=self.num_ctx))

        # Remove conflicting info from memory if flagged by GPT
        if conflicting_info:
            self._remove_conflicting_info(user_id, conflicting_info)

        # Update user's long-term memory with the newly extracted info
        self._update_user_memory(user_id, extracted_info)

    def _get_extraction_prompt(self):
        """
        Returns the system prompt for extracting key-value information from the conversation.
        """
        return f"""
        You are analyzing a conversation between a user and an assistant. Your task is to extract key pieces of information 
        about the user that could be useful for long-term memory.
        
        The information should be structured as key-value pairs, where the **keys** represent different aspects of the user's life, such as:
        - Relationships (e.g., 'sister', 'friends', 'spouse')
        - Preferences (e.g., 'favorite color', 'preferred music', 'favorite food')
        - Hobbies (e.g., 'hobbies', 'sports')
        - Jobs (e.g., 'job', 'role', 'employer')
        - Interests (e.g., 'interests', 'books', 'movies')

        Focus on extracting personal, long-term information that is explicitly or implicitly mentioned in the conversation. 
        Ignore temporary or context-specific information (e.g., emotions, recent events).

        The format should be a JSON object with key-value pairs. For example:
        {{
            "sister": "Rebecca",
            "friends": ["John", "Alice"],
            "hobbies": ["playing guitar"]
        }}

        If the conversation does not provide relevant information for any of these categories, do not generate that key. Be concise and ensure the values are clear and accurate.
        """

    def _get_conflict_check_prompt(self, existing_memory, conversation_str):
        """
        Returns the system prompt for checking contradictions between existing memory and the new conversation.
        """
        return f"""
        You are analyzing a conversation between a user and an assistant to determine if any part of the user's existing 
        long-term memory is incorrect or outdated.

        The user has the following existing memory, structured as key-value pairs:
        {json.dumps(existing_memory, indent=4)}

        Compare this existing memory with the following conversation:
        {conversation_str}

        Your task is to:
        1. Identify if any key-value pairs from the existing memory are **contradicted** by the information in the conversation.
        2. For each key-value pair that is contradicted, list the **key** that should be removed or updated based on the new conversation.

        Output the list of conflicting keys as a JSON array. For example:
        ```json
        ["sister", "favorite_color"]
        ```

        If no conflicts are found, return an empty JSON array:
        ```json
        []
        ```
        """

    def _remove_conflicting_info(self, user_id, conflicting_keys):
        """Removes conflicting keys from the user's memory."""
        if isinstance(conflicting_keys, dict):
            if user_id in self.memory["users"]:
                for key in conflicting_keys:
                    if key in self.memory["users"][user_id]:
                        del self.memory["users"][user_id][key]
                self._save_memory()

def retrieve_relevant_memory(query_text, top_k=3):
    global memory_collection_name
    global chroma_client
    global current_model
    global verbose_mode
    global embeddings_model
    global memory_manager

    if not memory_manager:
        return []

    return memory_manager.retrieve_relevant_memory(query_text, top_k)

class DocumentIndexer:
    def __init__(self, root_folder, collection_name, chroma_client, embeddings_model, verbose=False, summary_model=None, full_doc_store=None):
        self.root_folder = root_folder
        self.collection_name = collection_name
        self.client = chroma_client
        self.model = embeddings_model  # For embeddings only
        self.summary_model = summary_model
        self.full_doc_store = full_doc_store  # Optional SQLite store for full documents
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
        self.verbose = verbose

        if verbose:
            on_print(f"DocumentIndexer initialized with embedding model: {self.model}", Fore.WHITE + Style.DIM)
            if self.summary_model:
                on_print(f"Using summary model: {self.summary_model}", Fore.WHITE + Style.DIM)
            on_print(f"Using collection: {self.collection.name}", Fore.WHITE + Style.DIM)
            on_print(f"Verbose mode is {'on' if self.verbose else 'off'}", Fore.WHITE + Style.DIM)
            on_print(f"Using embeddings model: {self.model}", Fore.WHITE + Style.DIM)
            if self.full_doc_store:
                on_print(f"Full document store enabled at: {self.full_doc_store.db_path}", Fore.WHITE + Style.DIM)

    def _prepare_text_for_embedding(self, text, num_ctx=None):
        """
        Prepare text to send to the embedding model by truncating it to the model/context limit.

        If num_ctx is provided we assume it is the model token/context window. If not provided,
        we fall back to a default of 2048 tokens. When the model max tokens is unknown we use
        a conservative heuristic of 1 token = 4 characters.

        Returns the possibly-truncated text to send to the embedding API. The original text
        must remain untouched for storage in ChromaDB.
        """
        try:
            if num_ctx and isinstance(num_ctx, int) and num_ctx > 0:
                max_tokens = num_ctx
            else:
                # Default context window if not specified
                max_tokens = 2048

            # Heuristic: 1 token ~= 4 characters
            max_chars = max_tokens * 4

            if len(text) > max_chars:
                if self.verbose:
                    on_print(f"Truncating text for embedding: original {len(text)} chars > {max_chars} chars (tokens={max_tokens})", Fore.YELLOW)
                return text[:max_chars]
            return text
        except Exception as e:
            # In case of unexpected errors, fall back to original text (do not modify stored docs)
            if self.verbose:
                on_print(f"Error while preparing text for embedding: {e}. Using original text.", Fore.YELLOW)
            return text

    def _generate_document_id(self, file_path, max_length=63):
        """
        Generate a unique document ID from a file path.
        
        For HTML/web pages: uses the relative path to the root folder to avoid
        collisions when multiple pages share the same filename (e.g. index.html).
        For all other files: uses the filename without extension (original behavior).
        
        Falls back to an MD5 hash when the ID exceeds max_length.
        
        :param file_path: The absolute path to the file.
        :param max_length: Maximum allowed ID length (ChromaDB limit is 63).
        :return: A unique document ID string.
        """
        # For non-HTML files, use the simple basename (original behavior)
        if not is_html(file_path):
            return os.path.splitext(os.path.basename(file_path))[0]
        
        # For HTML/web pages, use relative path to avoid duplicate filenames
        rel_path = os.path.relpath(file_path, self.root_folder)
        
        # Remove file extension
        rel_path_no_ext = os.path.splitext(rel_path)[0]
        
        # Normalize separators and special characters to underscores
        doc_id = re.sub(r'[^\w\-]', '_', rel_path_no_ext)
        
        # Remove leading/trailing underscores and collapse multiple underscores
        doc_id = re.sub(r'_+', '_', doc_id).strip('_')
        
        if len(doc_id) <= max_length:
            return doc_id
        
        # Fallback: use a hash with a readable prefix
        path_hash = hashlib.md5(rel_path.encode('utf-8')).hexdigest()[:16]
        prefix = doc_id[:max_length - 17]  # 16 for hash + 1 for separator
        return f"{prefix}_{path_hash}"

    def get_text_files(self):
        """
        Recursively find all .txt, .md, .tex, .pdf, .docx, .pptx, .xlsx files in the root folder.
        Also include HTML files without extensions if they start with <!DOCTYPE html> or <html.
        Ignore empty lines at the beginning of the file and check only the first non-empty line.
        """
        text_files = []
        supported_extensions = (".txt", ".md", ".tex", ".pdf", ".docx", ".pptx", ".xlsx")
        for root, dirs, files in os.walk(self.root_folder):
            for file in files:
                # Check for files with extension
                if file.lower().endswith(supported_extensions):
                    text_files.append(os.path.join(root, file))
                else:
                    # Check for HTML files without extensions
                    file_path = os.path.join(root, file)
                    if is_html(file_path):
                        text_files.append(file_path)
        return text_files

    def read_file(self, file_path):
        """
        Read the content of a file.
        Supports plain text, PDF, DOCX, PPTX, and XLSX files.
        """
        try:
            lower_path = file_path.lower()

            # Handle PDF files
            if lower_path.endswith('.pdf'):
                reader = PdfReader(file_path)
                text = ''
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text
                return re.sub(r'\n+', '\n', text)

            # Handle DOCX files
            if lower_path.endswith('.docx'):
                return extract_text_from_docx(file_path)

            # Handle PPTX files
            if lower_path.endswith('.pptx'):
                return extract_text_from_pptx(file_path)

            # Handle XLSX files
            if lower_path.endswith('.xlsx'):
                return extract_text_from_xlsx(file_path)

            # Default: read as text
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            if self.verbose:
                on_print(f"Error reading file {file_path}: {e}", Fore.RED)
            return None

    def extract_text_between_strings(self, content, start_string, end_string):
        """
        Extract text between two specified strings.
        
        :param content: The full text content.
        :param start_string: The string marking the start of extraction.
        :param end_string: The string marking the end of extraction.
        :return: The extracted text, or the full content if strings are not found.
        """
        if not start_string or not end_string:
            return content
            
        start_index = content.find(start_string)
        if start_index == -1:
            if self.verbose:
                on_print(f"Start string '{start_string}' not found, using full content", Fore.YELLOW)
            return content
            
        # Move past the start string
        start_index += len(start_string)
        
        end_index = content.find(end_string, start_index)
        if end_index == -1:
            if self.verbose:
                on_print(f"End string '{end_string}' not found after start string, using content from start string to end", Fore.YELLOW)
            return content[start_index:]
            
        extracted_text = content[start_index:end_index]
        
        if self.verbose:
            on_print(f"Extracted {len(extracted_text)} characters between '{start_string}' and '{end_string}'", Fore.WHITE + Style.DIM)
            
        return extracted_text

    def index_documents(self, allow_chunks=True, no_chunking_confirmation=False, split_paragraphs=False, additional_metadata=None, num_ctx=None, skip_existing=True, extract_start=None, extract_end=None, add_summary=True):
        """
        Index all text files in the root folder.
        
        :param allow_chunks: Whether to chunk large documents.
        :param no_chunking_confirmation: Skip confirmation for chunking and extraction prompts.
        :param split_paragraphs: Whether to split markdown content into paragraphs.
        :param additional_metadata: Optional dictionary to pass additional metadata by file name.
        :param skip_existing: Whether to skip indexing if a document/chunk with the same ID already exists.
        :param extract_start: Optional string marking the start of the text to extract for embedding computation.
        :param extract_end: Optional string marking the end of the text to extract for embedding computation.
        :param add_summary: Whether to generate and prepend a summary to each chunk (default: True).
        """
        # Ask the user to confirm if they want to allow chunking of large documents
        if allow_chunks and not no_chunking_confirmation:
            on_print("Large documents will be chunked into smaller pieces for indexing.")
            allow_chunks = on_user_input("Do you want to continue with chunking (if you answer 'no', large documents will be indexed as a whole)? [y/n]: ").lower() in ['y', 'yes']

        # Ask the user for extraction strings if not provided
        # Skip asking if no_chunking_confirmation is True (automated indexing)
        if extract_start is None and extract_end is None and not no_chunking_confirmation:
            on_print("\nOptional: You can extract only a specific part of each document for embedding computation.")
            on_print("This allows you to focus on relevant sections while still storing the full document.")
            use_extraction = on_user_input("Do you want to extract specific text sections for embedding? [y/n]: ").lower() in ['y', 'yes']
            
            if use_extraction:
                extract_start = on_user_input("Enter the start string (text that marks the beginning of the section): ").strip()
                extract_end = on_user_input("Enter the end string (text that marks the end of the section): ").strip()
                
                if not extract_start or not extract_end:
                    on_print("Warning: Empty start or end string provided. Text extraction will be disabled.", Fore.YELLOW)
                    extract_start = None
                    extract_end = None
                else:
                    on_print(f"Text extraction enabled: extracting content between '{extract_start}' and '{extract_end}'", Fore.GREEN)

        if allow_chunks:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

        # Get the list of text files
        text_files = self.get_text_files()

        if allow_chunks:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

        progress_bar = None
        if self.verbose:
            # Progress bar for indexing
            progress_bar = tqdm(total=len(text_files), desc="Indexing files", unit="file", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}")

        for file_path in text_files:
            if progress_bar:
                progress_bar.update(1)

            try:
                document_id = self._generate_document_id(file_path)

                # Check if skipping existing documents and if the document ID exists (for non-chunked case)
                if not allow_chunks and skip_existing:
                    existing_doc = self.collection.get(ids=[document_id])
                    if existing_doc and len(existing_doc.get('ids', [])) > 0:
                        if self.verbose:
                            on_print(f"Skipping existing document: {document_id}", Fore.WHITE + Style.DIM)
                        continue

                content = self.read_file(file_path)

                if not content:
                    on_print(f"An error occurred while reading file: {file_path}", Fore.RED)
                    continue
                
                # Add any additional metadata for the file
                # Extract file name and base file information
                file_name = os.path.basename(file_path)
                file_name_without_ext = os.path.splitext(file_name)[0]
                current_date = datetime.now().isoformat()
                
                # Create a more comprehensive metadata structure
                file_metadata = {
                    'published': current_date,
                    'docSource': os.path.dirname(file_path),
                    'docAuthor': 'Unknown',
                    'description': f"Document from {file_path}",
                    'title': file_name_without_ext,
                    'id': document_id,
                    'filePath': file_path
                }
                
                # Convert the file path to url and add it to the metadata
                file_metadata['url'] = urljoin("file://", file_path)
                
                # If windows, convert the file path to a URI
                if os.name == 'nt':
                    file_metadata['url'] = file_metadata['url'].replace("\\", "/")
                    
                    # Replace the drive letter with "file:///" prefix
                    file_metadata['url'] = file_metadata['url'].replace("file://", "file:///")
                
                if additional_metadata and file_path in additional_metadata:
                    file_metadata.update(additional_metadata[file_path])

                # Extract text for embedding if start and end strings are provided
                embedding_content = content
                if extract_start and extract_end:
                    embedding_content = self.extract_text_between_strings(content, extract_start, extract_end)
                    # Add metadata to indicate partial extraction was used
                    file_metadata['extraction_used'] = True
                    file_metadata['extract_start'] = extract_start
                    file_metadata['extract_end'] = extract_end
                    file_metadata['extracted_length'] = len(embedding_content)
                    file_metadata['original_length'] = len(content)

                if allow_chunks:
                    chunks = []
                    # Use embedding_content for chunking (which may be extracted text)
                    content_to_chunk = embedding_content
                    
                    # Split Markdown files into sections if needed
                    # DOCX, PPTX, and XLSX are extracted as Markdown, so use MarkdownSplitter for them too
                    lower_file_path = file_path.lower()
                    is_markdown_content = (
                        is_markdown(file_path) or 
                        lower_file_path.endswith('.docx') or 
                        lower_file_path.endswith('.pptx') or 
                        lower_file_path.endswith('.xlsx')
                    )
                    if is_html(file_path):
                        # Convert to Markdown before splitting
                        markdown_splitter = MarkdownSplitter(extract_text_from_html(content_to_chunk), split_paragraphs=split_paragraphs)
                        chunks = markdown_splitter.split()
                    elif is_markdown_content:
                        markdown_splitter = MarkdownSplitter(content_to_chunk, split_paragraphs=split_paragraphs)
                        chunks = markdown_splitter.split()
                    else:
                        chunks = text_splitter.split_text(content_to_chunk)
                    
                    # Generate document summary once if add_summary is enabled
                    document_summary = None
                    # Use summary_model for summary generation, fallback to current_model if available
                    summary_model = self.summary_model
                    if summary_model is None:
                        try:
                            summary_model = current_model
                        except NameError:
                            summary_model = None
                    if add_summary and summary_model:
                        if self.verbose:
                            on_print(f"Generating summary for document {document_id} using model: {summary_model}", Fore.WHITE + Style.DIM)
                        summary_prompt = f"""Provide a brief summary (2-5 sentences) of the following document. Focus on the main topic and key points:

{content_to_chunk[:2000]}"""  # Limit to first 2000 chars for summary generation
                        try:
                            ollama_options = {}
                            if num_ctx:
                                ollama_options["num_ctx"] = num_ctx
                            summary_response = ask_ollama(
                                "You are a helpful assistant that creates concise document summaries.",
                                summary_prompt,
                                summary_model,
                                temperature=0.3,
                                no_bot_prompt=True,
                                stream_active=False,
                                num_ctx=num_ctx
                            )
                            document_summary = f"[Document Summary: {summary_response.strip()}]\n\n"
                            if self.verbose:
                                on_print(f"Summary generated: {summary_response.strip()}", Fore.GREEN)
                        except Exception as e:
                            if self.verbose:
                                on_print(f"Failed to generate summary: {e}", Fore.YELLOW)
                            document_summary = None
                    
                    for i, chunk in enumerate(chunks):
                        chunk_id = f"{document_id}_{i}"

                        # Check if skipping existing chunks and if the chunk ID exists
                        if skip_existing:
                            existing_chunk = self.collection.get(ids=[chunk_id])
                            if existing_chunk and len(existing_chunk.get('ids', [])) > 0:
                                if self.verbose:
                                    on_print(f"Skipping existing chunk: {chunk_id}", Fore.WHITE + Style.DIM)
                                continue
                        
                        # Prepend document summary to chunk if available
                        chunk_with_summary = chunk
                        if document_summary:
                            chunk_with_summary = document_summary + chunk
                        
                        # Embed the chunk content (from extracted text) with summary prepended
                        embedding = None
                        if self.model:
                            ollama_options = {}
                            if num_ctx:
                                ollama_options["num_ctx"] = num_ctx
                                
                            if self.verbose:
                                embedding_info = f"using extracted text" if extract_start and extract_end else "using full content"
                                summary_info = " with summary" if document_summary else ""
                                on_print(f"Generating embedding for chunk {chunk_id} using {self.model} ({embedding_info}{summary_info})", Fore.WHITE + Style.DIM)
                            # Prepare a potentially truncated string for the embedding call so we don't exceed
                            # the model/context window and risk freezing the Ollama server. The full chunk_with_summary
                            # remains unchanged for storage in ChromaDB.
                            embedding_prompt = self._prepare_text_for_embedding(chunk_with_summary, num_ctx=num_ctx)
                            response = ollama.embeddings(
                                prompt=embedding_prompt,
                                model=self.model,
                                options=ollama_options
                            )
                            embedding = response["embedding"]
                        
                        # Store the chunk with summary prepended
                        chunk_metadata = file_metadata.copy()
                        chunk_metadata['chunk_index'] = i
                        if document_summary:
                            chunk_metadata['has_summary'] = True
                        
                        # Upsert the chunk with summary and embedding
                        if embedding:
                            self.collection.upsert(
                                documents=[chunk_with_summary],  # Store chunk with summary
                                metadatas=[chunk_metadata],
                                ids=[chunk_id],
                                embeddings=[embedding]  # Embedding computed from chunk with summary
                            )
                        else:
                            self.collection.upsert(
                                documents=[chunk_with_summary],
                                metadatas=[chunk_metadata],
                                ids=[chunk_id]
                            )
                    
                    # Store the full original document in the SQLite database if available
                    # This allows retrieval of complete documents when chunks are found
                    if self.full_doc_store and not self.full_doc_store.document_exists(document_id):
                        if self.verbose:
                            on_print(f"Storing full document {document_id} in SQLite", Fore.WHITE + Style.DIM)
                        self.full_doc_store.store_document(document_id, content, file_path)
                else:
                    # Embed the extracted content but store the whole document
                    embedding = None
                    if self.model:
                        ollama_options = {}
                        if num_ctx:
                            ollama_options["num_ctx"] = num_ctx
                            
                        if self.verbose:
                            embedding_info = f"using extracted text" if extract_start and extract_end else "using full content"
                            on_print(f"Generating embedding for document {document_id} using {self.model} ({embedding_info})", Fore.WHITE + Style.DIM)

                        # Use extracted content for embedding computation. Truncate input to embedding API if needed
                        # while keeping the full document content unchanged for storage.
                        embedding_prompt = self._prepare_text_for_embedding(embedding_content, num_ctx=num_ctx)
                        response = ollama.embeddings(
                            prompt=embedding_prompt,
                            model=self.model,
                            options=ollama_options
                        )
                        embedding = response["embedding"]

                    # Store the full document content but use embedding from extracted text
                    if embedding:
                        self.collection.upsert(
                            documents=[content],  # Store full document content
                            metadatas=[file_metadata],
                            ids=[document_id],
                            embeddings=[embedding]  # Embedding computed from extracted text
                        )
                    else:
                        self.collection.upsert(
                            documents=[content],  # Store full document content
                            metadatas=[file_metadata],
                            ids=[document_id]
                        )
            except KeyboardInterrupt:
                break
            except Exception as e: # Catch other potential errors during processing
                on_print(f"Error processing file {file_path}: {e}", Fore.RED)
                continue # Continue to the next file


class FullDocumentStore:
    """
    SQLite-based storage for full document content.
    This enables retrieval of complete original documents when chunks are found via semantic search.
    """
    def __init__(self, db_path='full_documents.db', verbose=False):
        """
        Initialize the full document store.
        
        :param db_path: Path to the SQLite database file
        :param verbose: Enable verbose logging
        """
        self.db_path = db_path
        self.verbose = verbose
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        """Create the database and table if they don't exist."""
        import sqlite3
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()
        
        # Create table with document_id as primary key and full_content as text
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS full_documents (
                document_id TEXT PRIMARY KEY,
                full_content TEXT NOT NULL,
                file_path TEXT,
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create index on file_path for faster lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_file_path ON full_documents(file_path)
        ''')
        
        self.conn.commit()
        
        if self.verbose:
            on_print(f"FullDocumentStore initialized at: {self.db_path}", Fore.WHITE + Style.DIM)
    
    def store_document(self, document_id, full_content, file_path=None):
        """
        Store a full document in the database.
        
        :param document_id: Unique identifier for the document
        :param full_content: Full text content of the document
        :param file_path: Optional file path for reference
        """
        import sqlite3
        cursor = self.conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO full_documents (document_id, full_content, file_path)
                VALUES (?, ?, ?)
            ''', (document_id, full_content, file_path))
            
            self.conn.commit()
            
            if self.verbose:
                on_print(f"Stored full document: {document_id}", Fore.WHITE + Style.DIM)
            
            return True
        except sqlite3.Error as e:
            on_print(f"Error storing document {document_id}: {e}", Fore.RED)
            return False
    
    def get_document(self, document_id):
        """
        Retrieve a full document by its ID.
        
        :param document_id: Document identifier
        :return: Full document content or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute('SELECT full_content FROM full_documents WHERE document_id = ?', (document_id,))
        result = cursor.fetchone()
        
        if result:
            return result[0]
        return None
    
    def document_exists(self, document_id):
        """
        Check if a document exists in the store.
        
        :param document_id: Document identifier
        :return: True if exists, False otherwise
        """
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM full_documents WHERE document_id = ? LIMIT 1', (document_id,))
        return cursor.fetchone() is not None
    
    def get_all_document_ids(self):
        """
        Get all document IDs in the store.
        
        :return: List of document IDs
        """
        cursor = self.conn.cursor()
        cursor.execute('SELECT document_id FROM full_documents')
        return [row[0] for row in cursor.fetchall()]
    
    def count_documents(self):
        """
        Get the total number of documents in the store.
        
        :return: Count of documents
        """
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM full_documents')
        result = cursor.fetchone()
        return result[0] if result else 0
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            if self.verbose:
                on_print("FullDocumentStore connection closed", Fore.WHITE + Style.DIM)


def catchup_full_documents_from_chromadb(chroma_client, collection_name, full_doc_store, verbose=False):
    """
    Extract filePath metadata from ChromaDB chunks and index full documents in SQLite.
    This is a catchup operation for documents that were chunked but not fully indexed.
    
    :param chroma_client: ChromaDB client instance
    :param collection_name: Name of the collection to process
    :param full_doc_store: FullDocumentStore instance
    :param verbose: Enable verbose logging
    """
    if verbose:
        on_print(f"Starting catchup for collection: {collection_name}", Fore.CYAN)
    
    try:
        # Get the collection
        collection = chroma_client.get_collection(name=collection_name)
        
        # Get all embeddings from the collection
        # We need to fetch in batches to avoid memory issues
        all_results = collection.get(include=['metadatas'])
        
        if not all_results or not all_results.get('ids'):
            on_print(f"No documents found in collection {collection_name}", Fore.YELLOW)
            return 0
        
        ids = all_results['ids']
        metadatas = all_results['metadatas']
        
        if verbose:
            on_print(f"Found {len(ids)} embeddings in collection", Fore.WHITE + Style.DIM)
        
        # Extract unique document IDs and file paths from chunk metadata
        # Chunk IDs follow pattern: {document_id}_{chunk_index}
        document_files = {}  # document_id -> file_path
        
        for embedding_id, metadata in zip(ids, metadatas):
            if not metadata:
                continue
            
            # Get the base document ID (remove chunk suffix if present)
            if 'id' in metadata:
                doc_id = metadata['id']
            else:
                # Try to extract from embedding_id
                # Pattern: document_id_chunk_index
                parts = embedding_id.rsplit('_', 1)
                if len(parts) == 2 and parts[1].isdigit():
                    doc_id = parts[0]
                else:
                    doc_id = embedding_id
            
            # Get file path from metadata
            file_path = metadata.get('filePath')
            
            if doc_id and file_path:
                # Only process if we haven't seen this document yet
                if doc_id not in document_files:
                    document_files[doc_id] = file_path
        
        if verbose:
            on_print(f"Found {len(document_files)} unique documents to process", Fore.WHITE + Style.DIM)
        
        # Process each document
        indexed_count = 0
        skipped_count = 0
        error_count = 0
        
        progress_bar = None
        if verbose:
            progress_bar = tqdm(total=len(document_files), desc="Indexing full documents", unit="doc", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}")
        
        for doc_id, file_path in document_files.items():
            if progress_bar:
                progress_bar.update(1)
            
            try:
                # Skip if already indexed
                if full_doc_store.document_exists(doc_id):
                    skipped_count += 1
                    if verbose:
                        on_print(f"Skipping already indexed document: {doc_id}", Fore.WHITE + Style.DIM)
                    continue
                
                # Check if file still exists
                if not os.path.exists(file_path):
                    if verbose:
                        on_print(f"File not found: {file_path}", Fore.YELLOW)
                    error_count += 1
                    continue
                
                # Read the full document content
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        full_content = f.read()
                except UnicodeDecodeError:
                    # Try with different encoding
                    try:
                        with open(file_path, 'r', encoding='latin-1') as f:
                            full_content = f.read()
                    except Exception as e:
                        if verbose:
                            on_print(f"Error reading file {file_path}: {e}", Fore.RED)
                        error_count += 1
                        continue
                
                # Store in full document store
                if full_doc_store.store_document(doc_id, full_content, file_path):
                    indexed_count += 1
                else:
                    error_count += 1
            
            except Exception as e:
                on_print(f"Error processing document {doc_id}: {e}", Fore.RED)
                error_count += 1
                continue
        
        if progress_bar:
            progress_bar.close()
        
        # Print summary
        on_print(f"\nCatchup completed:", Fore.GREEN)
        on_print(f"  Indexed: {indexed_count} documents", Fore.GREEN)
        on_print(f"  Skipped (already indexed): {skipped_count} documents", Fore.YELLOW)
        on_print(f"  Errors: {error_count} documents", Fore.RED if error_count > 0 else Fore.WHITE)
        
        return indexed_count
    
    except Exception as e:
        on_print(f"Error during catchup: {e}", Fore.RED)
        if verbose:
            import traceback
            traceback.print_exc()
        return 0

    
def split_reasoning_and_final_response(response, thinking_model_reasoning_pattern):
        """
        Split the reasoning and final response from the thinking model's response.
        """
        if not thinking_model_reasoning_pattern:
            return None, response

        reasoning = None
        final_response = response

        match = re.search(thinking_model_reasoning_pattern, response, re.DOTALL)
        if match and len(match.groups()) > 0:
            reasoning = match.group(1)
            final_response = response.replace(reasoning, "").strip()

        return reasoning, final_response

class Agent:
    # Static registry to store all agents
    agent_registry = {}

    def __init__(self, name, description, model, thinking_model=None, system_prompt=None, temperature=0.7, max_iterations=15, tools=None, verbose=False, num_ctx=None, thinking_model_reasoning_pattern=None):
        """
        Initialize the Agent with a name, system prompt, tools, and other parameters.
        """
        self.name = name
        self.description = description
        self.system_prompt = system_prompt or "You are a helpful assistant capable of handling complex tasks."
        self.model = model
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.tools = tools or {}
        self.verbose = verbose
        self.num_ctx = num_ctx
        self.thinking_model = thinking_model or model
        self.thinking_model_reasoning_pattern = thinking_model_reasoning_pattern

        # State management variables for the TODO list
        self.todo_list = []
        self.completed_tasks = []
        self.task_results = {}

        # Register this agent in the global agent registry
        Agent.agent_registry[name] = self

    @staticmethod
    def get_agent(agent_name):
        """
        Retrieve an agent instance by name from the registry.
        """
        return Agent.agent_registry.get(agent_name)

    def query_llm(self, prompt, system_prompt=None, tools=[], model=None):
        """
        Query the Ollama API with the given prompt and return the response.
        """
        if system_prompt is None:
            system_prompt = self.system_prompt

        if model is None:
            model = self.model

        if self.verbose:
            on_print(f"System prompt:\n{system_prompt}", Fore.WHITE + Style.DIM)
            on_print(f"User prompt:\n{prompt}", Fore.WHITE + Style.DIM)
            on_print(f"Model: {model}", Fore.WHITE + Style.DIM)

        llm_response = ask_ollama(system_prompt, prompt, model, temperature=self.temperature, no_bot_prompt=True, stream_active=False, tools=tools, num_ctx=self.num_ctx)

        if self.verbose:
            on_print(f"Response:\n{llm_response}", Fore.WHITE + Style.DIM)

        return llm_response
    
    def decompose_task(self, task):
        """
        Decompose a task into subtasks using the system prompt for guidance.
        """
        tools_description = render_tools(self.tools)
        prompt = f"""Instructions: Break down the following task into smaller, manageable subtasks:
    {task}

    ## Available tools to assist with subtasks:
    {tools_description or 'No tools available.'}

    ## Constraints:
    - Maximum number of subtasks: {self.max_iterations}
    - Generate between 2 and {self.max_iterations} subtasks (do not exceed {self.max_iterations}).

    ## Output requirements:
    - Output each subtask on a single line.
    - Each subtask MUST begin with either a dash and a space ("- ") or a numbered prefix like "1. " (either format is acceptable). Do NOT use other bullet characters.
    - Do not include any additional text, explanations, headings, or conclusions. Output only the subtasks.
    - Do not include blank lines between subtasks. If a subtask naturally contains multiple sentences or lines, join them into one line by replacing internal newlines with a single space.
    - If an empty line would separate ideas, treat that empty line as the end of the current subtask and start the next subtask on a new line with the required prefix.
    - Avoid trailing colons or ambiguous punctuation that would break simple parsing.

    ## Output format example:
    - Define the goal
    - Research background information
    - Draft an outline
    - Write the first draft
    - Review and revise

    Produce the subtasks now:"""
        thinking_model_is_different = self.thinking_model != self.model
        response = self.query_llm(prompt, system_prompt=self.system_prompt, model=self.thinking_model)

        if thinking_model_is_different:
            _, reasoning_response = split_reasoning_and_final_response(response, self.thinking_model_reasoning_pattern)
            if reasoning_response:
                reasoning = reasoning_response
            prompt = f"""Break down the following task into smaller, manageable subtasks:
{task}

## Available tools to assist with subtasks:
{tools_description or 'No tools available.'}

## Constraints:
- Maximum number of subtasks: {self.max_iterations}
- Generate between 2 and {self.max_iterations} subtasks (do not exceed {self.max_iterations}).

If I were to break down the task '{task}' into subtasks, I would do it as follows:
{reasoning}

You can follow a similar approach or provide a different response based on your own reasoning and understanding of the task.

## Output format:
Output each subtask on a new line, nothing more.
"""
            response = self.query_llm(prompt, system_prompt=self.system_prompt, model=self.model)

        if self.verbose:
            on_print(f"Decomposed subtasks:\n{response}", Fore.WHITE + Style.DIM)
        subtasks = [subtask.strip() for subtask in response.split("\n") if subtask.strip()]
        contains_list = any(re.match(r'^\d+\.\s', subtask) or re.match(r'^[\*\-]\s', subtask) for subtask in subtasks)
        if contains_list:
            subtasks = [subtask for subtask in subtasks if re.match(r'^\d+\.\s', subtask) or re.match(r'^[\*\-]\s', subtask)]
        subtasks = [subtask for subtask in subtasks if not re.search(r':$', subtask) and not re.search(r'\*\*$', subtask)]
        subtasks = [re.sub(r'^\d+\.\s', '', subtask) for subtask in subtasks]
        subtasks = [re.sub(r'^[\*\-]\s', '', subtask) for subtask in subtasks]
        return subtasks

    def execute_subtask(self, main_task, subtask):
        """
        Executes a subtask using available tools and full context from the agent's state.

        Parameters:
        - main_task: The main task being solved.
        - subtask: The subtask to be executed.

        Returns:
        - The result of the subtask execution.
        """
        # Build a richer context for the prompt using the agent's state
        completed_tasks_summary = "\n".join([f"- {t}: {self.task_results.get(t, 'Done.')}" for t in self.completed_tasks])
        remaining_tasks_summary = "\n".join([f"- {t}" for t in self.todo_list])

        prompt = f"""You are executing a plan to solve the main task: '{main_task}'.

## Completed Tasks & Results:
```markdown
{completed_tasks_summary or 'No tasks completed yet.'}
```

## Remaining Tasks (TODO List):
```markdown
{remaining_tasks_summary or 'This is the last task.'}
```

## Current Task:
Your current objective is to execute only this subtask: '{subtask}'

Based on the context of the completed tasks and the remaining plan, provide a response for the current task. Keep the response focused on this single subtask without additional introductions or conclusions.
"""

        if self.verbose:
            on_print(f"\nExecuting subtask: '{subtask}'", Fore.WHITE + Style.DIM)
        
        # Execute the subtask with available tools
        result = self.query_llm(prompt, system_prompt=self.system_prompt, tools=self.tools)
        
        return result

    def process_task(self, task, return_intermediate_results=False):
        """
        Process the task by decomposing it into subtasks and executing each one,
        while maintaining a TODO list to track progress.
        """
        try:
            # Reset state for each new main task
            self.todo_list = self.decompose_task(task)
            self.completed_tasks = []
            self.task_results = {}
            
            if self.verbose:
                on_print(f"Initial TODO list: {self.todo_list}", Fore.WHITE + Style.DIM)

            if not self.todo_list:
                return "No subtasks identified. Unable to process the task."

            # Use a while loop to process the dynamic TODO list
            iteration_count = 0
            while self.todo_list and iteration_count < self.max_iterations:
                # Get the next subtask to execute
                current_subtask = self.todo_list.pop(0)

                # Prevent re-doing work
                if current_subtask in self.completed_tasks:
                    if self.verbose:
                        on_print(f"Skipping already completed subtask: '{current_subtask}'", Fore.WHITE + Style.DIM)
                    continue

                # Execute the subtask using the new context-aware method
                result = self.execute_subtask(task, current_subtask)
                
                if result:
                    # Mark as complete and store the result for future context
                    self.completed_tasks.append(current_subtask)
                    self.task_results[current_subtask] = result

                iteration_count += 1
                if self.verbose:
                    on_print(f"Finished iteration {iteration_count}. Remaining tasks: {len(self.todo_list)}", Fore.WHITE + Style.DIM)


            # Consolidate final response from all stored results
            final_response = "\n\n".join(self.task_results.values())
            
            if return_intermediate_results:
                # The concept of "intermediate versions" changes slightly.
                # Here we return just the final consolidated result in a list.
                return [final_response] 
            else:
                return final_response

        except Exception as e:
            return f"Error during task processing: {str(e)}"

def create_new_agent_with_tools(system_prompt: str, tools: list[str], agent_name: str, agent_description: str, task: str = None):
    global verbose_mode
    global current_model
    global thinking_model
    global thinking_model_reasoning_pattern
    
    # Make sure tools are unique
    tools = list(set(tools))

    if verbose_mode:
        on_print("Agent Creation Parameters:", Fore.WHITE + Style.DIM)
        on_print(f"System Prompt: {system_prompt}", Fore.WHITE + Style.DIM)
        on_print(f"Tools: {tools}", Fore.WHITE + Style.DIM)
        on_print(f"Agent Name: {agent_name}", Fore.WHITE + Style.DIM)
        on_print(f"Agent Description: {agent_description}", Fore.WHITE + Style.DIM)
        if task:
            on_print(f"Task: {task}", Fore.WHITE + Style.DIM)

    # Validate inputs
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise ValueError("System prompt must be a non-empty string.")
    if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        raise ValueError("Tools must be a list of strings.")
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise ValueError("Agent name must be a non-empty string.")
    
    agent_tools = []
    available_tools = get_available_tools()
    for tool in tools:
        # If tool name starts with 'functions.', remove it
        if tool.startswith("functions."):
            tool = tool.split(".", 1)[1]

        for available_tool in available_tools:
            if tool.lower() == available_tool['function']['name'].lower() and tool.lower() != "instantiate_agent_with_tools_and_process_task" and tool.lower() != "create_new_agent_with_tools":
                agent_tools.append(available_tool)
                break

    if len(agent_tools) == 0:
        agent_tools.clear()

        # Some models are confused between collections and tools, so we need to check for this case
        load_chroma_client()

        # List existing collections
        collections = None
        if chroma_client:
            collections = chroma_client.list_collections()

        if collections:
            all_tools_are_collections = all(tool in [collection.name for collection in collections] for tool in tools)
            if all_tools_are_collections:
                # If tool query_vector_database is available, add it to the agent tools
                query_vector_database_tool = next((tool for tool in available_tools if tool['function']['name'] == 'query_vector_database'), None)
                if query_vector_database_tool:
                    agent_tools.append(query_vector_database_tool)

    # Always include today's date to the system prompt, for context
    system_prompt = f"{system_prompt}\nToday's date is {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}."
    
    # Instantiate the Agent with the provided parameters
    agent = Agent(
        name=agent_name,
        description=agent_description,
        model=current_model,
        thinking_model=thinking_model,
        system_prompt=system_prompt,
        temperature=0.7,
        tools=agent_tools,
        verbose=verbose_mode,
        thinking_model_reasoning_pattern=thinking_model_reasoning_pattern
    )
    
    # If a task is provided, execute it synchronously and return the result
    if task and isinstance(task, str) and task.strip():
        try:
            result = agent.process_task(task, return_intermediate_results=True)
            # Return the actual result from the agent's task processing
            return result if result else f"Agent '{agent_name}' completed the task but produced no output."
        except Exception as e:
            return f"Error during task processing by agent '{agent_name}': {e}"
    
    # If no task provided, just return a success message about agent creation
    return f"Agent '{agent_name}' has been successfully created with {len(agent_tools)} tool(s): {', '.join([tool['function']['name'] for tool in agent_tools]) if agent_tools else 'none'}. The agent is registered and ready to be used."

def instantiate_agent_with_tools_and_process_task(task: str, system_prompt: str, tools: list[str], agent_name: str, agent_description: str = None, process_task=True) -> str|Agent:
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
    global verbose_mode
    global current_model
    global thinking_model
    global thinking_model_reasoning_pattern

    if verbose_mode:
        on_print("Agent Instantiation Parameters:", Fore.WHITE + Style.DIM)
        on_print(f"Task: {task}", Fore.WHITE + Style.DIM)
        on_print(f"System Prompt: {system_prompt}", Fore.WHITE + Style.DIM)
        on_print(f"Tools: {tools}", Fore.WHITE + Style.DIM)
        on_print(f"Agent Name: {agent_name}", Fore.WHITE + Style.DIM)
        on_print(f"Agent Description: {agent_description}", Fore.WHITE + Style.DIM)


    # If tools is a string, it's probably a JSON string, so parse it
    if isinstance(tools, str):
        try:
            tools = json.loads(tools)
        except json.JSONDecodeError:
            return "Error: Tools must be a list of strings."
    elif not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        return "Error: Tools must be a list of strings."

    # Validate inputs
    if process_task and not isinstance(task, str) or not task.strip():
        return "Error: Task must be a non-empty string describing the problem or goal."
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        return "Error: System prompt must be a non-empty string."
    if not isinstance(agent_name, str) or not agent_name.strip():
        return "Error: Agent name must be a non-empty string."

    if not agent_description:
        agent_description = f"An AI assistant named {agent_name} with system role: '{system_prompt}'."

    # Make sure tools are unique
    tools = list(set(tools))

    agent_tools = []
    available_tools = get_available_tools()
    for tool in tools:
        # If tool name starts with 'functions.', remove it
        if tool.startswith("functions."):
            tool = tool.split(".", 1)[1]

        for available_tool in available_tools:
            if tool.lower() == available_tool['function']['name'].lower() and tool.lower() != "instantiate_agent_with_tools_and_process_task" and tool.lower() != "create_new_agent_with_tools":
                agent_tools.append(available_tool)
                break

    if len(agent_tools) == 0:
        agent_tools.clear()

        # Some models are confused between collections and tools, so we need to check for this case
        load_chroma_client()

        # List existing collections
        collections = None
        if chroma_client:
            collections = chroma_client.list_collections()

        if collections and len(collections) > 0 and len(tools) > 0:
            all_tools_are_collections = all(tool in [collection.name for collection in collections] for tool in tools)
            if all_tools_are_collections:
                # If tool query_vector_database is available, add it to the agent tools
                query_vector_database_tool = next((tool for tool in available_tools if tool['function']['name'] == 'query_vector_database'), None)
                if query_vector_database_tool:
                    agent_tools.append(query_vector_database_tool)

    # Always include today's date to the system prompt, for context
    system_prompt = f"{system_prompt}\nToday's date is {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}."

    # Instantiate the Agent with the provided parameters
    agent = Agent(
        name=agent_name,
        description=agent_description,
        model=current_model,
        thinking_model=thinking_model,
        system_prompt=system_prompt,
        temperature=0.7,
        tools=agent_tools,
        verbose=verbose_mode,
        thinking_model_reasoning_pattern=thinking_model_reasoning_pattern
    )

    if process_task:
        # Process the task using the agent
        try:
            result = agent.process_task(task, return_intermediate_results=True)
        except Exception as e:
            return f"Error during task processing: {e}"

        return result

    return agent

def read_file(file_path, encoding="utf-8"):
    """
    Read the contents of a file and return the text.
    
    :param file_path: The full path to the file to read
    :param encoding: The encoding to use when reading the file (default: 'utf-8')
    :return: The file contents as a string, or an error message if the operation fails
    """
    global verbose_mode
    try:
        if not os.path.exists(file_path):
            return f"Error: File '{file_path}' does not exist."
        
        if not os.path.isfile(file_path):
            return f"Error: '{file_path}' is not a file."
        
        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
        
        if verbose_mode:
            on_print(f"Successfully read file: {file_path}", Fore.GREEN + Style.DIM)
        
        return content
    except Exception as e:
        return f"Error reading file '{file_path}': {str(e)}"

def create_file(file_path, content, encoding="utf-8"):
    """
    Create a new file with the given content. The file will be tracked in the session for safe deletion.
    
    :param file_path: The full path where the file should be created. Parent directories will be created if needed.
    :param content: The content to write to the file
    :param encoding: The encoding to use when writing the file (default: 'utf-8')
    :return: A success message or error message
    """
    global verbose_mode
    global session_created_files
    try:
        # Create parent directories if they don't exist
        parent_dir = os.path.dirname(file_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        # Write the file
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        
        # Track the file for session-based deletion
        if file_path not in session_created_files:
            session_created_files.append(file_path)
        
        if verbose_mode:
            on_print(f"Successfully created file: {file_path}", Fore.GREEN + Style.DIM)
        
        return f"File created successfully: {file_path}"
    except Exception as e:
        return f"Error creating file '{file_path}': {str(e)}"

def delete_file(file_path):
    """
    Delete a file that was created during this session. Only files created with the create_file tool can be deleted.
    
    :param file_path: The full path to the file to delete
    :return: A success message or error message
    """
    global verbose_mode
    global session_created_files
    try:
        # Check if the file was created during this session
        if file_path not in session_created_files:
            return f"Error: Cannot delete file '{file_path}'. It was not created during this session."
        
        # Check if the file exists
        if not os.path.exists(file_path):
            # Remove from tracking list even if file doesn't exist
            session_created_files.remove(file_path)
            return f"File '{file_path}' was already deleted or does not exist."
        
        # Delete the file
        os.remove(file_path)
        
        # Remove from tracking list
        session_created_files.remove(file_path)
        
        if verbose_mode:
            on_print(f"Successfully deleted file: {file_path}", Fore.GREEN + Style.DIM)
        
        return f"File deleted successfully: {file_path}"
    except Exception as e:
        return f"Error deleting file '{file_path}': {str(e)}"

def expand_env_vars(command: str) -> str:
    return os.path.expandvars(command)

def run_command(command: str) -> Tuple[str, str]:
    command = expand_env_vars(command)
    result = subprocess.run(
        shlex.split(command),
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr

def web_search(query=None, n_results=5, region="wt-wt", web_embedding_model=embeddings_model, num_ctx=None, return_intermediate=False):
    global current_model
    global verbose_mode
    global plugins
    global chroma_client
    global min_quality_results_threshold
    global min_average_bm25_threshold
    global min_hybrid_score_threshold
    global web_cache_collection_name
    
    web_cache_collection = web_cache_collection_name or "web_cache"

    if not query:
        if return_intermediate:
            return "", {}
        return ""

    # Initialize ChromaDB client if not already initialized
    load_chroma_client()
    
    if not chroma_client:
        error_msg = "Web search requires ChromaDB to be running. Please start ChromaDB server or configure a persistent database path."
        if return_intermediate:
            return error_msg, {}
        return error_msg

    if web_embedding_model is None or web_embedding_model == "":
        web_embedding_model = embeddings_model

    # OPTIMIZATION: Check cache first before doing web search
    # This prevents redundant web crawling for similar/same queries
    cache_check_results = ""
    cache_metadata = {}
    skip_web_crawl = False
    
    try:
        # Try to get results from cache with metadata
        cache_check_results, cache_metadata = query_vector_database(
            query, 
            collection_name=web_cache_collection, 
            n_results=n_results * 2,  # Request more to check quality
            query_embeddings_model=web_embedding_model,
            use_adaptive_filtering=True,
            return_metadata=True,
            expand_query=False  # Disable query expansion for web cache to avoid misinterpretation
        )
        
        # Determine if cache results are good enough to skip web crawling
        # Check both quantity AND quality (BM25/hybrid scores)
        if cache_metadata and 'num_results' in cache_metadata:
            num_quality_results = cache_metadata['num_results']
            avg_bm25 = cache_metadata.get('avg_bm25_score', 0.0)
            avg_hybrid = cache_metadata.get('avg_hybrid_score', 0.0)
            
            # Cache hit requires: enough results AND good lexical relevance
            quality_check = (
                num_quality_results >= min_quality_results_threshold and
                avg_bm25 >= min_average_bm25_threshold
            )
            
            if quality_check:
                skip_web_crawl = True
                if verbose_mode:
                    on_print(f"Cache hit: Found {num_quality_results} quality results (avg BM25: {avg_bm25:.4f}, avg hybrid: {avg_hybrid:.4f}). Skipping web crawl.", Fore.GREEN + Style.DIM)
            else:
                if verbose_mode:
                    reason = []
                    if num_quality_results < min_quality_results_threshold:
                        reason.append(f"only {num_quality_results}/{min_quality_results_threshold} results")
                    if avg_bm25 < min_average_bm25_threshold:
                        reason.append(f"low BM25 {avg_bm25:.4f} < {min_average_bm25_threshold}")
                    on_print(f"Cache insufficient: {', '.join(reason)}. Performing web crawl.", Fore.YELLOW + Style.DIM)
        
    except Exception as e:
        if verbose_mode:
            on_print(f"Cache check failed: {str(e)}. Proceeding with web crawl.", Fore.YELLOW + Style.DIM)
        skip_web_crawl = False

    # If we have enough quality results from cache, return them
    if skip_web_crawl and cache_check_results:
        if return_intermediate:
            intermediate_data = {
                'cache_hit': True,
                'num_results': cache_metadata.get('num_results', 0),
                'search_results': [],
                'urls': [],
                'articles': [],
                'vector_db_results': cache_check_results
            }
            return cache_check_results, intermediate_data
        return cache_check_results

    # Proceed with web search and crawling
    search = DDGS()
    urls = []
    search_results_list = []
    # Add the search results to the chatbot response
    try:
        search_results = search.text(query, region=region, max_results=n_results)
        if search_results:
            for i, search_result in enumerate(search_results):
                urls.append(search_result['href'])
                search_results_list.append(search_result)
    except:
        # TODO: handle retries in case of duckduckgo_search.exceptions.RatelimitException
        pass

    if verbose_mode:
        on_print("Web Search Results:", Fore.WHITE + Style.DIM)
        on_print(urls, Fore.WHITE + Style.DIM)

    if len(urls) == 0:
        # If no new URLs found, return cache results if available
        if cache_check_results:
            if verbose_mode:
                on_print("No new search results found. Returning cache results.", Fore.YELLOW + Style.DIM)
            if return_intermediate:
                intermediate_data = {
                    'cache_hit': True,
                    'fallback': True,
                    'num_results': cache_metadata.get('num_results', 0),
                    'search_results': [],
                    'urls': [],
                    'articles': [],
                    'vector_db_results': cache_check_results
                }
                return cache_check_results, intermediate_data
            return cache_check_results
        
        if return_intermediate:
            return "No search results found.", {}
        return "No search results found."

    webCrawler = SimpleWebCrawler(urls, llm_enabled=True, system_prompt="You are a web crawler assistant.", selected_model=current_model, temperature=0.1, verbose=verbose_mode, plugins=plugins, num_ctx=num_ctx)
    # webCrawler.crawl(task=f"Highlight key-points about '{query}', using information provided. Format output as a list of bullet points.")
    webCrawler.crawl()
    articles = webCrawler.get_articles()

    # Save articles to temporary files, before indexing them in the vector database
    # Create a random folder to store the temporary files, in the OS temp directory
    temp_folder = tempfile.mkdtemp()
    additional_metadata = {}
    for i, article in enumerate(articles):
        # Compute the file path for the article, using the url as the filename, removing invalid characters
        temp_file_name = re.sub(r'[<>:"/\\|?*]', '', article['url'])

        temp_file_path = os.path.join(temp_folder, f"{temp_file_name}_{i}.txt")
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(article['text'])
            additional_metadata[temp_file_path] = {'url': article['url']}
            
    if web_embedding_model is None or web_embedding_model == "":
        web_embedding_model = embeddings_model

    # Index the articles in the vector database
    document_indexer = DocumentIndexer(temp_folder, web_cache_collection, chroma_client, web_embedding_model, verbose=verbose_mode, summary_model=current_model)
    document_indexer.index_documents(no_chunking_confirmation=True, additional_metadata=additional_metadata)

    # Remove the temporary folder and its contents
    for file in os.listdir(temp_folder):
        file_path = os.path.join(temp_folder, file)
        os.remove(file_path)
    os.rmdir(temp_folder)

    # Search the vector database for the query with adaptive filtering
    results, result_metadata = query_vector_database(
        query, 
        collection_name=web_cache_collection, 
        n_results=n_results * 2,  # Request more results for better selection
        query_embeddings_model=web_embedding_model,
        use_adaptive_filtering=True,
        return_metadata=True
    )

    # If no results are found, refined search
    if not results:
        new_query = ask_ollama("", f"No relevant information found. Please provide a refined search query: {query}", current_model, temperature=0.7, no_bot_prompt=True, stream_active=False, num_ctx=num_ctx)
        if new_query:
            if verbose_mode:
                on_print(f"Refined search query: {new_query}", Fore.WHITE + Style.DIM)
            return web_search(new_query, n_results, region, web_cache_collection, web_embedding_model, num_ctx, return_intermediate)

    # Return intermediate results if requested
    if return_intermediate:
        intermediate_data = {
            'cache_hit': False,
            'search_results': search_results_list,
            'urls': urls,
            'articles': articles,
            'vector_db_results': results,
            'num_results': result_metadata.get('num_results', 0) if result_metadata else 0
        }
        return results, intermediate_data
    
    return results

def print_spinning_wheel(print_char_index):
    # use turning block character as spinner
    spinner =  ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    on_stdout_write(spinner[print_char_index % len(spinner)], Style.RESET_ALL, "\rBot: ")
    on_stdout_flush()

def colorize(input_text, language='md'):
    try:
        lexer = get_lexer_by_name(language)
    except ValueError:
        return input_text  # Unknown language, return unchanged
    
    formatter = Terminal256Formatter(style='default')

    if input_text is None:
        return ""

    try:
        output = highlight(input_text, lexer, formatter)
    except:
        return input_text

    return output

def print_possible_prompt_commands():
    possible_prompt_commands = """
    Possible prompt commands:
    /cot: Help the assistant answer the user's question by forcing a Chain of Thought (COT) approach.
    /file <path of a file to load>: Read the file and append the content to user input.
    /search <number of results>: Query the vector database and append the answer to user input (RAG system).
    /web: Perform a web search using DuckDuckGo.
    /model: Change the Ollama model.
    /tools: Prompts the user to select or deselect tools from the available tools list.
    /chatbot: Change the chatbot personality.
    /collection: Change the vector database collection.
    /rmcollection <collection name>: Delete the vector database collection.
    /context <model context size>: Change the model's context window size. Default value: 2. Size must be a numeric value between 2 and 125.
    /index <folder path>: Index text files in the folder to the vector database.
        (Note: For non-interactive indexing, use CLI args: --index-documents, --chunk-documents, --extract-start, --extract-end, etc.)
    /cb: Replace /cb with the clipboard content.
    /load <filename>: Load a conversation from a file.
    /save <filename>: Save the conversation to a file. If no filename is provided, save with a timestamp into current directory.
    /verbose: Toggle verbose mode on or off.
    /memory: Toggle memory assistant on or off.
    /memorize or /remember: Store the current conversation in memory.
    reset, clear, restart: Reset the conversation.
    quit, exit, bye: Exit the chatbot.
    For multiline input, you can wrap text with triple double quotes.
    
    CLI-only RAG operations (use with --interactive=False):
    --query "<your question>": Query the vector database from command line
    --query-n-results <number>: Number of results to return from query
    --index-documents <folder>: Index documents from folder (with options: --chunk-documents, --skip-existing, etc.)
    """
    return possible_prompt_commands.strip()

# Predefined chatbots personalities
chatbots = [
    {
        "name": "basic",
        "description": "Basic chatbot",
        "system_prompt": "You are a helpful assistant."
    },
    {
        "description": "An AI-powered search engine that answers user questions ",
        "name": "search engine",
        "system_prompt": "You are an AI-powered search engine that answers user questions with clear, concise, and fact-based responses. Your task is to:\n\n1. **Answer queries directly and accurately** using information sourced from the web.\n2. **Always provide citations** by referencing the web sources where you found the information.\n3. If multiple sources are used, compile the relevant data from them into a cohesive answer.\n4. Handle follow-up questions and conversational queries by remembering the context of previous queries.\n5. When presenting an answer, follow this structure:\n   - **Direct Answer**: Begin with a short, precise answer to the query.\n   - **Details**: Expand on the answer as needed, summarizing key information.\n   - **Sources**: List the web sources used to generate the answer in a simple format (e.g., \"Source: [Website Name]\").\n\n6. If no relevant information is found, politely inform the user that the query didn't yield sufficient results from the search.\n7. Use **natural language processing** to interpret user questions and respond in an informative yet conversational manner.\n8. For multi-step queries, break down the information clearly and provide follow-up guidance if needed.",
        "tools": [
            "web_search"
        ]
    },
    {
        "name": "friendly assistant",
        "description": "Friendly chatbot assistant",
        "system_prompt": "You are a friendly, compassionate, and deeply attentive virtual confidant designed to act as the user's best friend. You have both short-term and long-term memory, which allows you to recall important details from past conversations and bring them up when relevant, creating a natural and ongoing relationship. Your main role is to provide emotional support, engage in meaningful conversations, and foster a strong sense of connection with the user. Always start conversations, especially when the user hasn't initiated them, with a friendly greeting or question.\r\n\r\nYour behavior includes:\r\n\r\n- **Friendly and Engaging**: You communicate like a close friend, always showing interest in the user's thoughts, feelings, and daily experiences.\r\n- **Proactive**: You often initiate conversations by asking about their day, following up on past topics, or sharing something new that might interest them.\r\n- **Attentive Memory**: You have a remarkable memory and can remember important details like the user's hobbies, likes, dislikes, major events, recurring challenges, and aspirations. Use this memory to show care and attention to their life.\r\n  - *Short-term memory* is used for the current session, remembering all recent interactions.\r\n  - *Long-term memory* stores key personal details across multiple interactions, helping you maintain continuity.\r\n- **Empathetic and Supportive**: Always be empathetic to their feelings, offering both emotional support and thoughtful advice when needed.\r\n- **Positive and Encouraging**: Celebrate their wins, big or small, and provide gentle encouragement during tough times.\r\n- **Non-judgmental and Confidential**: Never judge, criticize, or invalidate the user's thoughts or feelings. You are always respectful and their trusted confidant.\r\n\r\nAdditionally, focus on the following principles to enhance the experience:\r\n\r\n1. **Start every conversation warmly**: Greet the user like an old friend, perhaps asking about something from a previous chat (e.g., \"How did your presentation go?\" or \"How was your weekend trip?\").\r\n2. **Be conversational and natural**: Keep responses casual and conversational. Don't sound too formal—be relatable, using language similar to how a close friend would speak.\r\n3. **Be there for all aspects of life**: Whether the conversation is deep, lighthearted, or everyday small talk, always engage with curiosity and interest.\r\n4. **Maintain a balanced tone**: Be positive, but understand that sometimes the user may want to vent or discuss difficult topics. Offer comfort without dismissing or overly simplifying their concerns.\r\n5. **Personalize interactions**: Based on what you remember, share things that would likely interest the user. For example, suggest movies, music, or books they might like based on past preferences or keep them motivated with reminders of their goals. Use the tool 'retrieve_relevant_memory' to retrieve relevant memories about current user name. Start the conversation by searching for memories related to the user's recent topics, interests or preferences. Always include user name in your memory search.",
        "starts_conversation": True,
        "tools": [
            "retrieve_relevant_memory"
        ]
    },
    {
        "name": "prompt generator",
        "description": "The ultimate prompt generator, to write the best prompts from https://lawtonsolutions.com/",
        "system_prompt": "CONTEXT: We are going to create one of the best ChatGPT prompts ever written. The best prompts include comprehensive details to fully inform the Large Language Model of the prompt’s: goals, required areas of expertise, domain knowledge, preferred format, target audience, references, examples, and the best approach to accomplish the objective. Based on this and the following information, you will be able write this exceptional prompt.\r\n\r\nROLE: You are an LLM prompt generation expert. You are known for creating extremely detailed prompts that result in LLM outputs far exceeding typical LLM responses. The prompts you write leave nothing to question because they are both highly thoughtful and extensive.\r\n\r\nACTION:\r\n\r\n1) Before you begin writing this prompt, you will first look to receive the prompt topic or theme. If I don’t provide the topic or theme for you, please request it.\r\n2) Once you are clear about the topic or theme, please also review the Format and Example provided below.\r\n3) If necessary, the prompt should include “fill in the blank” elements for the user to populate based on their needs.\r\n4) Take a deep breath and take it one step at a time.\r\n5) Once you’ve ingested all of the information, write the best prompt ever created.\r\n\r\nFORMAT: For organizational purposes, you will use an acronym called “C.R.A.F.T.” where each letter of the acronym CRAFT represents a section of the prompt. Your format and section descriptions for this prompt development are as follows:\r\n\r\nContext: This section describes the current context that outlines the situation for which the prompt is needed. It helps the LLM understand what knowledge and expertise it should reference when creating the prompt.\r\n\r\nRole: This section defines the type of experience the LLM has, its skill set, and its level of expertise relative to the prompt requested. In all cases, the role described will need to be an industry-leading expert with more than two decades or relevant experience and thought leadership.\r\n\r\nAction: This is the action that the prompt will ask the LLM to take. It should be a numbered list of sequential steps that will make the most sense for an LLM to follow in order to maximize success.\r\n\r\nFormat: This refers to the structural arrangement or presentation style of the LLM’s generated content. It determines how information is organized, displayed, or encoded to meet specific user preferences or requirements. Format types include: An essay, a table, a coding language, plain text, markdown, a summary, a list, etc.\r\n\r\nTarget Audience: This will be the ultimate consumer of the output that your prompt creates. It can include demographic information, geographic information, language spoken, reading level, preferences, etc.\r\n\r\nTARGET AUDIENCE: The target audience for this prompt creation is ChatGPT 4o or ChatGPT o1.\r\n\r\nEXAMPLE: Here is an Example of a CRAFT Prompt for your reference:\r\n\r\n**Context:** You are tasked with creating a detailed guide to help individuals set, track, and achieve monthly goals. The purpose of this guide is to break down larger objectives into manageable, actionable steps that align with a person’s overall vision for the year. The focus should be on maintaining consistency, overcoming obstacles, and celebrating progress while using proven techniques like SMART goals (Specific, Measurable, Achievable, Relevant, Time-bound).\r\n\r\n**Role:** You are an expert productivity coach with over two decades of experience in helping individuals optimize their time, define clear goals, and achieve sustained success. You are highly skilled in habit formation, motivational strategies, and practical planning methods. Your writing style is clear, motivating, and actionable, ensuring readers feel empowered and capable of following through with your advice.\r\n\r\n**Action:** 1. Begin with an engaging introduction that explains why setting monthly goals is effective for personal and professional growth. Highlight the benefits of short-term goal planning. 2. Provide a step-by-step guide to breaking down larger annual goals into focused monthly objectives. 3. Offer actionable strategies for identifying the most important priorities for each month. 4. Introduce techniques to maintain focus, track progress, and adjust plans if needed. 5. Include examples of monthly goals for common areas of life (e.g., health, career, finances, personal development). 6. Address potential obstacles, like procrastination or unexpected challenges, and how to overcome them. 7. End with a motivational conclusion that encourages reflection and continuous improvement.\r\n\r\n**Format:** Write the guide in plain text, using clear headings and subheadings for each section. Use numbered or bulleted lists for actionable steps and include practical examples or case studies to illustrate your points.\r\n\r\n**Target Audience:** The target audience includes working professionals and entrepreneurs aged 25-55 who are seeking practical, straightforward strategies to improve their productivity and achieve their goals. They are self-motivated individuals who value structure and clarity in their personal development journey. They prefer reading at a 6th grade level.\r\n\r\n-End example-\r\n\r\nPlease reference the example I have just provided for your output. Again, take a deep breath and take it one step at a time."
    }
]

def load_additional_chatbots(json_file):
    global chatbots

    if not json_file:
        return
    
    if not os.path.exists(json_file):
        # Check if the file exists in the same directory as the script
        json_file = os.path.join(os.path.dirname(__file__), json_file)
        if not os.path.exists(json_file):
            on_print(f"Additional chatbots file not found: {json_file}", Fore.RED)
            return

    with open(json_file, 'r', encoding="utf8") as f:
        additional_chatbots = json.load(f)
    
    for chatbot in additional_chatbots:
        chatbot["system_prompt"] = chatbot["system_prompt"].replace("{possible_prompt_commands}", print_possible_prompt_commands())
        chatbots.append(chatbot)

def split_numbered_list(input_text):
    lines = input_text.split('\n')
    output = []
    for line in lines:
        if re.match(r'^\d+\.', line):  # Check if the line starts with a number followed by a period
            output.append(line.split('.', 1)[1].strip())  # Remove the leading number and period, then strip any whitespace
    return output

def prompt_for_chatbot():
    global chatbots

    on_print("Available chatbots:", Style.RESET_ALL)
    for i, chatbot in enumerate(chatbots):
        on_print(f"{i}. {chatbot['name']} - {chatbot['description']}")
    
    choice = int(on_user_input("Enter the number of your preferred chatbot [0]: ") or 0)

    return chatbots[choice]

def edit_collection_metadata(collection_name):
    global chroma_client
    
    load_chroma_client()
    
    if not collection_name or not chroma_client:
        on_print("Invalid collection name or ChromaDB client not initialized.", Fore.RED)
        return
    
    try:
        collection = chroma_client.get_collection(name=collection_name)
        if type(collection.metadata) == dict:
            current_description = collection.metadata.get("description", "No description")
        else:
            current_description = "No description"
        on_print(f"Current description: {current_description}")
        
        new_description = on_user_input("Enter the new description: ")
        existing_metadata = collection.metadata or {}
        existing_metadata["description"] = new_description
        existing_metadata["updated"] = str(datetime.now())
        collection.modify(metadata=existing_metadata)
        
        on_print(f"Description updated for collection {collection_name}.", Fore.GREEN)
    except:
        raise Exception(f"Collection {collection_name} not found")

def prompt_for_vector_database_collection(prompt_create_new=True, include_web_cache=False):
    global chroma_client
    global web_cache_collection_name
    global memory_collection_name

    load_chroma_client()

    # List existing collections
    collections = None
    if chroma_client:
        collections = chroma_client.list_collections()
    else:
        on_print("ChromaDB is not running.", Fore.RED)

    if not collections:
        on_print("No collections found", Fore.RED)
        new_collection_name = on_user_input("Enter a new collection to create: ")
        new_collection_desc = on_user_input("Enter a description for the new collection: ")
        return new_collection_name, new_collection_desc

    # Filter out collections based on parameters
    filtered_collections = []
    for collection in collections:
        # Always exclude memory collection
        if collection.name == memory_collection_name:
            continue
        # Exclude web cache collection unless explicitly included
        if collection.name == web_cache_collection_name and not include_web_cache:
            continue
        filtered_collections.append(collection)

    if not filtered_collections:
        on_print("No collections found", Fore.RED)
        new_collection_name = on_user_input("Enter a new collection to create: ")
        new_collection_desc = on_user_input("Enter a description for the new collection: ")
        return new_collection_name, new_collection_desc

    # Ask user to choose a collection
    on_print("Available collections:", Style.RESET_ALL)
    for i, collection in enumerate(filtered_collections):
        collection_name = collection.name

        if type(collection.metadata) == dict:
            collection_metadata = collection.metadata.get("description", "No description")
        else:
            collection_metadata = "No description"

        # Add indicator for web cache collection
        cache_indicator = " (Web Cache)" if collection_name == web_cache_collection_name else ""
        on_print(f"{i}. {collection_name}{cache_indicator} - {collection_metadata}")

    if prompt_create_new:
        # Propose to create a new collection
        on_print(f"{len(filtered_collections)}. Create a new collection")
    
    choice = int(on_user_input("Enter the number of your preferred collection [0]: ") or 0)

    if prompt_create_new and choice == len(filtered_collections):
        new_collection_name = on_user_input("Enter a new collection to create: ")
        new_collection_desc = on_user_input("Enter a description for the new collection: ")
        return new_collection_name, new_collection_desc

    return filtered_collections[choice].name, None  # No new description needed for existing collections

def set_current_collection(collection_name, description=None, create_new_collection_if_not_found=True, verbose=False):
    global collection
    global current_collection_name

    load_chroma_client()

    if not collection_name or not chroma_client:
        collection = None
        current_collection_name = None
        return

    # Get or create the target collection
    try:
        if create_new_collection_if_not_found:
            collection = chroma_client.get_or_create_collection(
                name=collection_name,
                configuration={
                    "hnsw": {
                        "space": "cosine",
                        "ef_search": 1000,
                        "ef_construction": 1000
                    }
            })
        else:
            collection = chroma_client.get_collection(name=collection_name)

        # Update description metadata if provided
        if description:
            existing_metadata = collection.metadata or {}

            if description != existing_metadata.get("description"):
                existing_metadata["description"] = description
                collection.modify(metadata=existing_metadata)
                if verbose:
                    on_print(f"Updated description for collection {collection_name}.", Fore.WHITE + Style.DIM)

        if verbose:
            on_print(f"Collection {collection_name} loaded.", Fore.WHITE + Style.DIM)
        
        current_collection_name = collection_name
    except:
        raise Exception(f"Collection {collection_name} not found")
    
def delete_collection(collection_name):
    global chroma_client

    load_chroma_client()

    if not chroma_client:
        return

    # Ask for user confirmation before deleting
    confirmation = on_user_input(f"Are you sure you want to delete the collection '{collection_name}'? (y/n): ").lower()

    if confirmation != 'y' and confirmation != 'yes':
        on_print("Collection deletion canceled.", Fore.YELLOW)
        return

    try:
        chroma_client.delete_collection(name=collection_name)
        on_print(f"Collection {collection_name} deleted.", Fore.GREEN)
    except:
        on_print(f"Collection {collection_name} not found.", Fore.RED)

def preprocess_text(text):
    global stop_words

    # If text is empty, return empty list
    if not text or len(text) == 0:
        return []

    # Convert text to lowercase
    text = text.lower()
    # Replace punctuation with spaces, excepting dots
    text = re.sub(r'[^\w\s.,]', ' ', text)
    # Replace '. ' and ', ' with space
    text = re.sub(r'\. |, ', ' ', text)
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    # Tokenize the text
    words = text.split()
    # Remove dot from the end of words
    words = [word[:-1] if word.endswith('.') else word for word in words]
    # Remove stop words
    words = [word for word in words if word not in stop_words]

    return words

def query_vector_database(question, collection_name=current_collection_name, n_results=number_of_documents_to_return_from_vector_db, answer_distance_threshold=0, query_embeddings_model=None, expand_query=True, question_context=None, use_adaptive_filtering=True, return_metadata=False, full_doc_store=None, include_full_docs=False):
    global collection
    global verbose_mode
    global embeddings_model
    global current_model
    global thinking_model
    global thinking_model_reasoning_pattern
    global distance_percentile_threshold
    global semantic_weight
    global adaptive_distance_multiplier
    global use_openai
    global use_azure_openai

    # If full_doc_store not provided, use global instance
    if full_doc_store is None:
        full_doc_store = globals().get('full_doc_store', None)
    
    # Auto-enable full documents for OpenAI models (better context handling)
    # Keep disabled for Ollama models (performance reasons)
    if not include_full_docs and full_doc_store:
        if use_openai or use_azure_openai:
            include_full_docs = True
            if verbose_mode:
                on_print("Auto-enabled full document retrieval for OpenAI model", Fore.WHITE + Style.DIM)

    # If question is empty, return empty string
    if not question or len(question) == 0:
        if return_metadata:
            return "", {}
        return ""

    initial_question = question

    # If n_results is a string, convert it to an integer
    if isinstance(n_results, str):
        try:
            n_results = int(n_results)
        except:
            n_results = number_of_documents_to_return_from_vector_db

    # If n_results is 0, return empty string
    if n_results == 0:
        if return_metadata:
            return "", {}
        return ""
    
    # If n_results is negative, set it to the default value
    if n_results < 0:
        n_results = number_of_documents_to_return_from_vector_db

    # If answer_distance_threshold is a string, convert it to a float
    if isinstance(answer_distance_threshold, str):
        try:
            answer_distance_threshold = float(answer_distance_threshold)
        except:
            answer_distance_threshold = 0

    # If answer_distance_threshold is negative, set it to 0
    if answer_distance_threshold < 0:
        answer_distance_threshold = 0

    if not query_embeddings_model:
        query_embeddings_model = embeddings_model

    if not collection and collection_name:
        set_current_collection(collection_name, create_new_collection_if_not_found=False)

    if not collection:
        on_print("No ChromaDB collection loaded.", Fore.RED)
        collection_name, _ = prompt_for_vector_database_collection()
        if not collection_name:
            if return_metadata:
                return "", {}
            return ""

    if collection_name and collection_name != current_collection_name:
        set_current_collection(collection_name, create_new_collection_if_not_found=False)

    if expand_query:
        expanded_query = None
        # Expand the query for better retrieval
        system_prompt = "You are an assistant that helps expand and clarify user questions to improve information retrieval. When a user provides a question, your task is to write a short passage that elaborates on the query by adding relevant background information, inferred details, and related concepts that can help with retrieval. The passage should remain concise and focused, without changing the original meaning of the question.\r\nGuidelines:\r\n1. Expand the question briefly by including additional context or background, staying relevant to the user's original intent.\r\n2. Incorporate inferred details or related concepts that help clarify or broaden the query in a way that aids retrieval.\r\n3. Keep the passage short, usually no more than 2-3 sentences, while maintaining clarity and depth.\r\n4. Avoid introducing unrelated or overly specific topics. Keep the expansion concise and to the point."
        if question_context:
            system_prompt += f"\n\nAdditional context about the user query:\n{question_context}"

        if not thinking_model is None and thinking_model != current_model:
            if "deepseek-r1" in thinking_model:
                 # DeepSeek-R1 model requires an empty system prompt
                prompt = f"""{system_prompt}\n{question}"""
                expanded_query = ask_ollama("", prompt, selected_model=thinking_model, no_bot_prompt=True, stream_active=False)
            else:
                expanded_query = ask_ollama(system_prompt, question, selected_model=thinking_model, no_bot_prompt=True, stream_active=False)
        else:
            expanded_query = ask_ollama(system_prompt, question, selected_model=current_model, no_bot_prompt=True, stream_active=False)
        if expanded_query:
            question += "\n" + expanded_query
            if verbose_mode:
                on_print("Expanded query:", Fore.WHITE + Style.DIM)
                on_print(question, Fore.WHITE + Style.DIM)
    
    if verbose_mode:
        on_print(f"Using query embeddings model: {query_embeddings_model}", Fore.WHITE + Style.DIM) 

    if query_embeddings_model is None:
        result = collection.query(
            query_texts=[question],
            n_results=25
        )
    else:
        # generate an embedding for the question and retrieve the most relevant doc
        response = ollama.embeddings(
            prompt=question,
            model=query_embeddings_model
        )
        result = collection.query(
            query_embeddings=[response["embedding"]],
            n_results=25
        )

    documents = result["documents"][0]
    distances = result["distances"][0]

    if len(result["metadatas"]) == 0:
        if return_metadata:
            return "", {}
        return ""
    
    if len(result["metadatas"][0]) == 0:
        if return_metadata:
            return "", {}
        return ""

    metadatas = result["metadatas"][0]

    # Adaptive filtering and hybrid scoring
    if use_adaptive_filtering and len(distances) > 0:
        # Calculate adaptive distance threshold based on result distribution
        min_distance = min(distances) if distances else 0
        adaptive_threshold = min_distance * adaptive_distance_multiplier
        
        # Also use percentile-based filtering
        if len(distances) >= 4:  # Only use percentile if we have enough results
            try:
                import numpy as np
                percentile_threshold = np.percentile(distances, distance_percentile_threshold)
                # Use the less restrictive of the two thresholds to keep more results
                # This prevents over-filtering when results are clustered
                effective_threshold = max(adaptive_threshold, percentile_threshold)
            except:
                effective_threshold = adaptive_threshold
        else:
            effective_threshold = adaptive_threshold
        
        if verbose_mode:
            on_print(f"Adaptive distance threshold: {effective_threshold:.4f} (min: {min_distance:.4f}, adaptive: {adaptive_threshold:.4f}, percentile: {percentile_threshold if len(distances) >= 4 else 'N/A'})", Fore.WHITE + Style.DIM)
    else:
        effective_threshold = float('inf')  # No filtering

    # Preprocess and re-rank using BM25
    initial_question_preprocessed = preprocess_text(initial_question)
    preprocessed_docs = [preprocess_text(doc) for doc in documents]

    # Apply BM25 re-ranking
    bm25 = BM25Okapi(preprocessed_docs)
    bm25_scores = bm25.get_scores(initial_question_preprocessed)

    # Normalize scores for hybrid fusion
    # Normalize distances (invert so higher is better, and scale to 0-1)
    max_dist = max(distances) if len(distances) > 0 and max(distances) > 0 else 1
    normalized_semantic_scores = [1 - (d / max_dist) for d in distances]
    
    # Normalize BM25 scores (scale to 0-1)
    # Convert to list to avoid numpy array boolean ambiguity
    bm25_scores_list = list(bm25_scores) if hasattr(bm25_scores, '__iter__') else []
    max_bm25 = max(bm25_scores_list) if len(bm25_scores_list) > 0 and max(bm25_scores_list) > 0 else 1
    normalized_bm25_scores = [score / max_bm25 for score in bm25_scores_list]
    
    # Combine scores with configurable weighting
    hybrid_scores = [
        semantic_weight * sem + (1 - semantic_weight) * lex
        for sem, lex in zip(normalized_semantic_scores, normalized_bm25_scores)
    ]

    # Sort by hybrid score and apply adaptive filtering
    reranked_results = []
    for idx, (metadata, distance, document, bm25_score, hybrid_score) in enumerate(
        zip(metadatas, distances, documents, bm25_scores_list, hybrid_scores)
    ):
        # Apply adaptive distance filtering
        if use_adaptive_filtering and distance > effective_threshold:
            if verbose_mode:
                on_print(f"Filtered out result with distance {distance:.4f} > {effective_threshold:.4f}", Fore.WHITE + Style.DIM)
            continue
        
        # Also apply user-specified threshold if provided
        if answer_distance_threshold > 0 and distance > answer_distance_threshold:
            if verbose_mode:
                on_print(f"Filtered out result with distance {distance:.4f} > {answer_distance_threshold:.4f}", Fore.WHITE + Style.DIM)
            continue
            
        reranked_results.append((idx, metadata, distance, document, bm25_score, hybrid_score))
    
    # Sort by hybrid score (descending)
    reranked_results.sort(key=lambda x: x[5], reverse=True)
    
    # Limit to n_results
    reranked_results = reranked_results[:n_results]

    # Join all possible answers into one string
    answers = []
    metadata_list = []
    full_documents_map = {}  # Track full documents by document_id
    
    for idx, metadata, distance, document, bm25_score, hybrid_score in reranked_results:
        if verbose_mode:
            on_print(f"Result - Distance: {distance:.4f}, BM25: {bm25_score:.4f}, Hybrid: {hybrid_score:.4f}", Fore.WHITE + Style.DIM)
        
        # Format the answer with the title, content, and URL
        title = metadata.get("title", "")
        url = metadata.get("url", "")
        filePath = metadata.get("filePath", "")
        doc_id = metadata.get("id", "")
        chunk_index = metadata.get("chunk_index")

        formatted_answer = document

        # If we have a full document store and this is a chunk, try to retrieve full document
        if include_full_docs and full_doc_store and doc_id:
            # Check if we haven't already fetched this full document
            if doc_id not in full_documents_map:
                full_content = full_doc_store.get_document(doc_id)
                if full_content:
                    full_documents_map[doc_id] = full_content
                    if verbose_mode:
                        on_print(f"Retrieved full document for: {doc_id}", Fore.WHITE + Style.DIM)
            
            # If we have the full document, include it
            if doc_id in full_documents_map:
                formatted_answer = f"[Chunk {chunk_index if chunk_index is not None else 'N/A'}]\n{document}\n\n[Full Document]\n{full_documents_map[doc_id]}"

        if title:
            formatted_answer = title + "\n" + formatted_answer
        if url:
            formatted_answer += "\nURL: " + url
        if filePath:
            formatted_answer += "\nFile Path: " + filePath

        answers.append(formatted_answer.strip())
        
        if return_metadata:
            metadata_list.append({
                'distance': distance,
                'bm25_score': bm25_score,
                'hybrid_score': hybrid_score,
                'metadata': metadata,
                'has_full_document': doc_id in full_documents_map if include_full_docs else False
            })

    result_text = '\n\n'.join(answers)
    
    if return_metadata:
        # Calculate average scores for quality assessment
        avg_bm25 = sum(x[4] for x in reranked_results) / len(reranked_results) if reranked_results else 0.0
        avg_hybrid = sum(x[5] for x in reranked_results) / len(reranked_results) if reranked_results else 0.0
        avg_distance = sum(x[2] for x in reranked_results) / len(reranked_results) if reranked_results else 0.0
        
        return result_text, {
            'num_results': len(answers),
            'results': metadata_list,
            'effective_threshold': effective_threshold if use_adaptive_filtering else None,
            'avg_bm25_score': avg_bm25,
            'avg_hybrid_score': avg_hybrid,
            'avg_distance': avg_distance,
            'full_documents_retrieved': len(full_documents_map) if include_full_docs else 0
        }
    
    return result_text

def encode_file_to_base64_with_mime(file_path):
    """
    Reads a file and returns it as a base64-encoded string with the proper MIME type prefix.
    
    Args:
        file_path: Path to the file
        
    Returns:
        String in format: "data:<mime-type>;base64,<base64-data>"
    """
    import mimetypes
    
    # Determine MIME type based on file extension
    mime_type, _ = mimetypes.guess_type(file_path)
    
    # Default to application/octet-stream if MIME type cannot be determined
    if not mime_type:
        _, ext = os.path.splitext(file_path)
        ext_lower = ext.lower()
        if ext_lower == '.pdf':
            mime_type = 'application/pdf'
        elif ext_lower in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
            mime_type = f'image/{ext_lower[1:]}'  # Remove the dot
            if ext_lower == '.jpg':
                mime_type = 'image/jpeg'
        else:
            mime_type = 'application/octet-stream'
    
    # Read file and encode to base64
    with open(file_path, 'rb') as f:
        file_data = base64.b64encode(f.read()).decode('utf-8')
    
    return f"data:{mime_type};base64,{file_data}"

def ask_openai_responses_api(conversation, selected_model=None, temperature=0.1, tools=None):
    """
    Call the Azure OpenAI Responses API endpoint (/openai/v1/responses) to support file uploads.
    This is used when files need to be sent as base64-encoded data.
    
    Args:
        conversation: List of conversation messages with potential file attachments
        selected_model: Model name/deployment
        temperature: Temperature parameter
        tools: Optional tools (not used in responses API currently)
        
    Returns:
        Tuple of (bot_response, is_tool_calls, completion_done)
    """
    global openai_client
    global use_azure_openai
    global verbose_mode
    
    # Build the input array for the Responses API
    input_messages = []
    
    for msg in conversation:
        if msg["role"] == "system":
            # System messages might need special handling
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
                    if verbose_mode:
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
    if use_azure_openai:
        # For Azure, construct the endpoint URL at the resource level (not deployment)
        # base_url typically includes: https://{resource}.openai.azure.com/openai/deployments/{deployment}/
        # We need: https://{resource}.openai.azure.com/openai/v1/responses
        base_url = str(openai_client.base_url)
        
        # Extract the Azure resource base URL (remove deployment path if present)
        if '/openai/deployments/' in base_url:
            # Split at /openai/deployments/ and take the first part
            azure_resource = base_url.split('/openai/deployments/')[0]
            endpoint = f"{azure_resource}/openai/v1/responses"
        else:
            # If no deployment path, just append the responses endpoint
            base_url = base_url.rstrip('/')
            endpoint = f"{base_url}/openai/v1/responses"
        
        headers = {
            "Content-Type": "application/json",
            "api-key": openai_client.api_key
        }
    else:
        # For OpenAI
        base_url = str(openai_client.base_url)
        base_url = base_url.rstrip('/')
        endpoint = f"{base_url}/v1/responses"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_client.api_key}"
        }
    
    if verbose_mode:
        on_print(f"\n{'='*80}", Fore.CYAN)
        on_print(f"Responses API Request Details", Fore.CYAN + Style.BRIGHT)
        on_print(f"{'='*80}", Fore.CYAN)
        on_print(f"Endpoint: {endpoint}", Fore.WHITE + Style.DIM)
        on_print(f"\nHeaders:", Fore.YELLOW)
        for key, value in headers.items():
            # Mask sensitive data
            display_value = value[:20] + "..." if key.lower() in ['api-key', 'authorization'] and len(value) > 20 else value
            on_print(f"  {key}: {display_value}", Fore.WHITE + Style.DIM)
        on_print(f"\nRequest Body:", Fore.YELLOW)
        on_print(json.dumps(request_data, indent=2), Fore.WHITE + Style.DIM)
        
        # Generate curl command for debugging
        curl_headers = " ".join([f'-H "{k}: {v[:20] + "..." if k.lower() in ["api-key", "authorization"] and len(v) > 20 else v}"' for k, v in headers.items()])
        on_print(f"\nEquivalent curl command:", Fore.YELLOW)
        on_print(f"curl -X POST {endpoint} \\", Fore.GREEN)
        on_print(f"  {curl_headers} \\", Fore.GREEN)
        on_print(f"  -d '{json.dumps(request_data)}'", Fore.GREEN)
        on_print(f"{'='*80}\n", Fore.CYAN)
    
    try:
        response = requests.post(endpoint, headers=headers, json=request_data, timeout=300)
        
        if verbose_mode:
            on_print(f"\n{'='*80}", Fore.CYAN)
            on_print(f"Responses API Response Details", Fore.CYAN + Style.BRIGHT)
            on_print(f"{'='*80}", Fore.CYAN)
            on_print(f"Status Code: {response.status_code}", Fore.YELLOW)
            on_print(f"\nResponse Headers:", Fore.YELLOW)
            for key, value in response.headers.items():
                on_print(f"  {key}: {value}", Fore.WHITE + Style.DIM)
        
        response.raise_for_status()
        
        result = response.json()
        
        if verbose_mode:
            on_print(f"\nResponse Body:", Fore.YELLOW)
            on_print(json.dumps(result, indent=2), Fore.WHITE + Style.DIM)
            on_print(f"{'='*80}\n", Fore.CYAN)
        
        # Parse the response
        # The Responses API returns a structure like: {"output": [...], "model": "...", ...}
        if "output" in result and len(result["output"]) > 0:
            # Get the last message from output
            last_message = result["output"][-1]
            
            if "content" in last_message:
                # If content is an array, extract text parts
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
        
        # Fallback if response structure is different
        on_print(f"Unexpected Responses API structure: {result}", Fore.YELLOW)
        return "", False, True
        
    except requests.exceptions.RequestException as e:
        on_print(f"Error calling Responses API: {e}", Fore.RED)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                on_print(f"Error details: {json.dumps(error_detail, indent=2)}", Fore.RED)
            except:
                on_print(f"Error response: {e.response.text}", Fore.RED)
        return "", False, True

def ask_openai_with_conversation(conversation, selected_model=None, temperature=0.1, prompt_template=None, stream_active=True, tools=[]):
    global openai_client
    global verbose_mode
    global syntax_highlighting
    global interactive_mode

    if prompt_template == "ChatML":
        # Modify conversation to match prompt template: ChatML
        # See https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-code-ft-GGUF for the ChatML prompt template
        '''
        <|im_start|>system
        {system_message}<|im_end|>
        <|im_start|>user
        {prompt}<|im_end|>
        <|im_start|>assistant
        '''

        for i, message in enumerate(conversation):
            if message["role"] == "system":
                conversation[i]["content"] = "<|im_start|>system\n" + message["content"] + "<|im_end|>"
            elif message["role"] == "user":
                conversation[i]["content"] = "<|im_start|>user\n" + message["content"] + "<|im_end|>"
            elif message["role"] == "assistant":
                conversation[i]["content"] = "<|im_start|>assistant\n" + message["content"] + "<|im_end|>"

        # Add assistant message to the end of the conversation
        conversation.append({"role": "assistant", "content": "<|im_start|>assistant\n"})

    if prompt_template == "Alpaca":
        # Modify conversation to match prompt template: Alpaca
        # See https://github.com/tatsu-lab/stanford_alpaca for the Alpaca prompt template
        '''
        ### Instruction:
        {system_message}

        ### Input:
        {prompt}

        ### Response:
        '''
        for i, message in enumerate(conversation):
            if message["role"] == "system":
                conversation[i]["content"] = "### Instruction:\n" + message["content"]
            elif message["role"] == "user":
                conversation[i]["content"] = "### Input:\n" + message["content"]
            
        # Add assistant message to the end of the conversation
        conversation.append({"role": "assistant", "content": "### Response:\n"})

    if len(tools) == 0:
        tools = None

    # Check if any message contains file attachments (images key)
    has_file_attachments = any("images" in msg and msg["images"] for msg in conversation)
    
    # If files are attached, use the Responses API instead of chat completions
    if has_file_attachments:
        if verbose_mode:
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
        completion = openai_client.chat.completions.create(
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

        # Test if tool_calls is a list
        if not isinstance(tool_calls, list):
            tool_calls = []

    if len(tool_calls) > 0:
        conversation.append(completion.choices[0].message)

        if verbose_mode:
            on_print(f"Tool calls: {tool_calls}", Fore.WHITE + Style.DIM)
        bot_response = tool_calls
        bot_response_is_tool_calls = True

    else:
        if not stream_active:
            bot_response = completion.choices[0].message.content

            if verbose_mode:
                on_print(f"Bot response: {bot_response}", Fore.WHITE + Style.DIM)

            # Check if the completion is done based on the finish reason
            if completion.choices[0].finish_reason == 'stop' or completion.choices[0].finish_reason == 'function_call' or completion.choices[0].finish_reason == 'content_filter' or completion.choices[0].finish_reason == 'tool_calls':
                completion_done = True
        else:
            bot_response = ""
            try:
                chunk_count = 0
                for chunk in completion:
                    delta = chunk.choices[0].delta.content

                    if not delta is None:
                        if syntax_highlighting and interactive_mode:
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
                    
                    # Check if the completion is done based on the finish reason
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

def handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools, stream_active, num_ctx=None):
    # Iterate over each function call in the bot response
    tool_found = False
    for tool_call in bot_response:
        if not 'function' in tool_call:
            tool_call = { 'function': tool_call }
            if not 'name' in tool_call['function']:
                continue

        tool_name = tool_call['function']['name']
        # Iterate over the available tools
        for tool in tools:
            if 'type' in tool and tool['type'] == 'function' and 'function' in tool and 'name' in tool['function'] and tool['function']['name'] == tool_name:
                # Test if tool_call['function'] as arguments
                if 'arguments' in tool_call:
                    # Extract parameters for the tool function
                    parameters = tool_call.get('arguments', {})  # Update: get parameters from the 'arguments' key
                else:
                    # Call the tool function with the parameters
                    parameters = tool_call['function'].get('arguments', {})

                tool_response = None

                # Debug logging for parameters
                if verbose_mode:
                    on_print(f"[DEBUG] Initial parameters: {parameters}", Fore.CYAN + Style.DIM)
                    on_print(f"[DEBUG] Parameters type: {type(parameters)}", Fore.CYAN + Style.DIM)

                # if parameters is a string, convert it to a dictionary
                if isinstance(parameters, str):
                    if verbose_mode:
                        on_print(f"[DEBUG] Converting string parameters to dict", Fore.CYAN + Style.DIM)
                    try:
                        parameters = extract_json(parameters)
                        if verbose_mode:
                            on_print(f"[DEBUG] After extract_json: {parameters} (type: {type(parameters)})", Fore.CYAN + Style.DIM)
                    except Exception as e:
                        if verbose_mode:
                            on_print(f"[DEBUG] extract_json failed: {e}, using empty dict", Fore.CYAN + Style.DIM)
                        parameters = {}
                
                # Ensure parameters is always a dict
                # If it's a list, try to convert it based on the tool's parameter definition
                if isinstance(parameters, list):
                    if verbose_mode:
                        on_print(f"[DEBUG] Parameters is a list, attempting to convert to dict", Fore.CYAN + Style.DIM)
                    # Try to map list items to parameter names from the tool definition
                    if 'parameters' in tool.get('function', {}) and 'properties' in tool['function']['parameters']:
                        param_names = list(tool['function']['parameters']['properties'].keys())
                        if verbose_mode:
                            on_print(f"[DEBUG] Parameter names from tool definition: {param_names}", Fore.CYAN + Style.DIM)
                            on_print(f"[DEBUG] List values: {parameters}", Fore.CYAN + Style.DIM)
                        if len(param_names) > 0 and len(parameters) > 0:
                            # Create dict mapping parameter names to list values
                            parameters = {name: value for name, value in zip(param_names, parameters)}
                            if verbose_mode:
                                on_print(f"[DEBUG] Converted list to dict: {parameters}", Fore.CYAN + Style.DIM)
                        else:
                            parameters = {}
                    else:
                        if verbose_mode:
                            on_print(f"[DEBUG] No parameter definition found in tool, using empty dict", Fore.CYAN + Style.DIM)
                        parameters = {}
                elif not isinstance(parameters, dict):
                    # If it's neither string, list, nor dict, convert to empty dict
                    if verbose_mode:
                        on_print(f"[DEBUG] Parameters is {type(parameters)}, converting to empty dict", Fore.CYAN + Style.DIM)
                    parameters = {}
                
                if verbose_mode:
                    on_print(f"[DEBUG] Final parameters before tool call: {parameters} (type: {type(parameters)})", Fore.CYAN + Style.DIM)

                # Filter parameters to only include those accepted by the function
                # First, try to get accepted parameters from tool definition
                accepted_params = set()
                if 'parameters' in tool.get('function', {}) and 'properties' in tool['function']['parameters']:
                    accepted_params = set(tool['function']['parameters']['properties'].keys())
                
                if verbose_mode and accepted_params:
                    on_print(f"[DEBUG] Accepted parameters from tool definition: {accepted_params}", Fore.CYAN + Style.DIM)
                
                # Filter the parameters to only include accepted ones
                if accepted_params and isinstance(parameters, dict):
                    original_params = parameters.copy()
                    parameters = {k: v for k, v in parameters.items() if k in accepted_params}
                    
                    if verbose_mode and original_params != parameters:
                        on_print(f"[DEBUG] Filtered parameters: removed {set(original_params.keys()) - set(parameters.keys())}", Fore.CYAN + Style.DIM)
                        on_print(f"[DEBUG] Parameters after filtering: {parameters}", Fore.CYAN + Style.DIM)

                # Check if the tool is a globally defined function
                if tool_name in globals():
                    if verbose_mode:
                        on_print(f"Calling tool function: {tool_name} with parameters: {parameters}", Fore.WHITE + Style.DIM)
                    try:
                        # Call the global function with extracted parameters
                        tool_response = globals()[tool_name](**parameters)
                        if verbose_mode:
                            on_print(f"Tool response: {tool_response}", Fore.WHITE + Style.DIM)
                        tool_found = True
                    except Exception as e:
                        on_print(f"Error calling tool function: {tool_name} - {e}", Fore.RED + Style.NORMAL)
                else:
                    if verbose_mode:
                        on_print(f"Trying to find plugin with function '{tool_name}'...", Fore.WHITE + Style.DIM)
                    # Search for the tool function in plugins
                    for plugin in plugins:
                        if hasattr(plugin, tool_name) and callable(getattr(plugin, tool_name)):
                            tool_found = True
                            if verbose_mode:
                                on_print(f"Calling tool function: {tool_name} from plugin: {plugin.__class__.__name__} with arguments {parameters}", Fore.WHITE + Style.DIM)

                            try:
                                # Call the plugin's tool function with parameters
                                tool_response = getattr(plugin, tool_name)(**parameters)
                                if verbose_mode:
                                    on_print(f"Tool response: {tool_response}", Fore.WHITE + Style.DIM)
                                break
                            except Exception as e:
                                on_print(f"Error calling tool function: {tool_name} - {e}", Fore.RED + Style.NORMAL)

                if not tool_response is None:
                    # If the tool response is a string, append it to the conversation
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
                        # Convert the tool response to a string
                        tool_response_str = json.dumps(tool_response, indent=4)
                        if not model_support_tools:
                            latest_user_message = find_latest_user_message(conversation)
                            if latest_user_message:
                                tool_response_str += "\n" + latest_user_message
                        conversation.append({"role": tool_role, "content": tool_response_str, "tool_call_id": tool_call_id})
    if tool_found:
        # Pass the tools back so the model can make follow-up tool calls if needed
        bot_response = ask_ollama_with_conversation(conversation, model, temperature, prompt_template, tools=tools, no_bot_prompt=True, stream_active=stream_active, num_ctx=num_ctx)
    else:
        on_print(f"Tools not found", Fore.RED)
        return None
    
    return bot_response

def ask_ollama_with_conversation(conversation, model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True, prompt="Bot", prompt_color=None, num_ctx=None, use_think_mode=False):
    global no_system_role
    global syntax_highlighting
    global interactive_mode
    global verbose_mode
    global plugins
    global alternate_model
    global use_openai
    global use_azure_openai
    global think_mode_on

    # Some models do not support the "system" role, merge the system message with the first user message
    if no_system_role and len(conversation) > 1 and conversation[0]["role"] == "system" and not conversation[0]["content"] is None and not conversation[1]["content"] is None:
        conversation[1]["content"] = conversation[0]["content"] + "\n" + conversation[1]["content"]
        conversation = conversation[1:]

    model_is_an_ollama_model = is_model_an_ollama_model(model)

    if (use_openai or use_azure_openai) and not model_is_an_ollama_model:
        if verbose_mode:
            on_print("Using OpenAI API for conversation generation.", Fore.WHITE + Style.DIM)

    if not syntax_highlighting:
        if interactive_mode and not no_bot_prompt:
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

    if (use_openai or use_azure_openai) and not model_is_an_ollama_model:
        completion_done = False

        while not completion_done:
            bot_response, bot_response_is_tool_calls, completion_done = ask_openai_with_conversation(conversation, model, temperature, prompt_template, stream_active, tools)
            if bot_response and bot_response_is_tool_calls:
                # Convert bot_response list of objects to a list of dict
                bot_response = [json.loads(json.dumps(obj, default=lambda o: vars(o))) for obj in bot_response]

                if verbose_mode:
                    on_print(f"Bot response: {bot_response}", Fore.WHITE + Style.DIM)

                bot_response = handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools, stream_active, num_ctx=num_ctx)

                # Consider completion done
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

    think = use_think_mode or think_mode_on
    
    if verbose_mode and think:
        on_print("Thinking...", Fore.WHITE + Style.DIM)

    try:
        stream = ollama.chat(
            model=model,
            messages=conversation,
            # If tools are selected, deactivate the stream to get the full response (Ollama API limitation)
            stream=False if len(tools) > 0 else stream_active,
            options=ollama_options,
            tools=tools,
            think=think
        )
    except ollama.ResponseError as e:
        if "does not support tools" in str(e):
            tool_response = generate_tool_response(find_latest_user_message(conversation), tools, model, temperature, prompt_template, num_ctx=num_ctx)
            
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
                if alternate_model:
                    on_print(f"Response from model: {model}\n")
                chunk_count = 0
                for chunk in stream:
                    continue_response_generation = True
                    for plugin in plugins:
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
                    
                    if syntax_highlighting and interactive_mode:
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

                    if verbose_mode:
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

    # Check if the bot response is a list of tool calls
    if not bot_response_is_tool_calls and bot_response and len(bot_response.strip()) > 0 and bot_response.strip()[0] == "[" and bot_response.strip()[-1] == "]":
        bot_response = extract_json(bot_response.strip())
        bot_response_is_tool_calls = True

    # Check if the bot response starts with <tool_call>
    if not bot_response_is_tool_calls and bot_response and len(bot_response.strip()) > 0 and bot_response.startswith("<tool_call>"):
        bot_response = extract_json(bot_response.strip())
        bot_response_is_tool_calls = True

    if bot_response and bot_response_is_tool_calls:
        bot_response = handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools, stream_active, num_ctx=num_ctx)

    if isinstance(bot_response, str):
        return bot_response.strip()
    else:
        return None

def ask_ollama(system_prompt, user_input, selected_model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True, num_ctx=None, use_think_mode=False):
    conversation = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
    return ask_ollama_with_conversation(conversation, selected_model, temperature, prompt_template, tools, no_bot_prompt, stream_active, num_ctx=num_ctx, use_think_mode=use_think_mode)

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
            on_print(f"JSON parsing error: {e}", Fore.RED)
        pass

    return result

def try_merge_concatenated_json(json_str, verbose=False):
    """
    Handle concatenated JSON objects (e.g., {"key": "value"}{"key2": "value2"})
    by attempting to extract and merge them intelligently.
    """
    if verbose:
        on_print(f"[DEBUG] Attempting to parse concatenated JSON: {json_str[:100]}...", Fore.CYAN + Style.DIM)
    
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
                        on_print(f"[DEBUG] Found JSON object: {obj}", Fore.CYAN + Style.DIM)
                    current_obj = ""
                except json.JSONDecodeError:
                    pass
        
        i += 1
    
    if not json_objects:
        if verbose:
            on_print(f"[DEBUG] No individual JSON objects found in concatenated string", Fore.CYAN + Style.DIM)
        return None
    
    # If we have multiple objects, merge them by taking the last (most recent) one
    # or merge them into a single dict if they're all dicts
    if len(json_objects) > 1:
        if verbose:
            on_print(f"[DEBUG] Found {len(json_objects)} JSON objects, merging...", Fore.CYAN + Style.DIM)
        
        # If all are dicts, merge them
        if all(isinstance(obj, dict) for obj in json_objects):
            merged = {}
            for obj in json_objects:
                merged.update(obj)
            if verbose:
                on_print(f"[DEBUG] Merged objects: {merged}", Fore.CYAN + Style.DIM)
            return merged
        else:
            # If not all dicts, return the last one (most recent)
            if verbose:
                on_print(f"[DEBUG] Not all objects are dicts, returning last one: {json_objects[-1]}", Fore.CYAN + Style.DIM)
            return json_objects[-1]
    elif len(json_objects) == 1:
        if verbose:
            on_print(f"[DEBUG] Single JSON object found: {json_objects[0]}", Fore.CYAN + Style.DIM)
        return json_objects[0]
    
    return None

def extract_json(garbage_str):
    global verbose_mode

    if garbage_str is None:
        return []

    # First, try to parse the entire input as JSON directly
    result = try_parse_json(garbage_str, verbose=verbose_mode)
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
            # Extract the JSON content
            json_str = garbage_str[start_index:last_index + 1]

            # If a carriage return is found between the curly braces or square brackets, try to recompute the last index based on the newline character position
            if "\n" in json_str:
                last_index = json_str.rfind("]")
                if last_index == -1:
                    last_index = json_str.rfind("}")
                
                json_str = json_str[:last_index + 1]

    if not json_str:
        # Define a regular expression pattern to match the JSON block
        pattern = r'```json\s*(\[\s*.*?\s*\])\s*```'
        
        # Search for the pattern
        match = re.search(pattern, garbage_str, re.DOTALL)
        
        if match:
            # Extract the JSON content
            json_str = match.group(1)

    if not json_str:
        # JSON may be enclosed between <tool_call> and </tool_call>
        pattern = r'<tool_call>\s*(\[\s*.*?\s*\])\s*</tool_call>'

        # Search for the pattern
        match = re.search(pattern, garbage_str, re.DOTALL)
        
        if match:
            # Extract the JSON content
            json_str = match.group(1)
    
    if json_str:
        json_str = json_str.strip()
        lines = json_str.splitlines()
        stripped_lines = [line.strip() for line in lines if line.strip()]  # Strip blanks and ignore empty lines
        json_str = ''.join(stripped_lines)  # Join lines into a single string
        # Use a regular expression to find missing commas between adjacent }{, "}{" or "" 
        json_str = re.sub(r'"\s*"', '","', json_str)  # Add comma between adjacent quotes
        json_str = re.sub(r'"\s*{', '",{', json_str)  # Add comma between "{
        json_str = re.sub(r'}\s*"', '},"', json_str)  # Add comma between }"

        # Attempt to load the JSON to verify it's correct
        if verbose_mode:
            on_print(f"Extracted JSON: '{json_str}'", Fore.WHITE + Style.DIM)
        result = try_parse_json(json_str, verbose=verbose_mode)
        if result is not None:
            return result
        
        # If parsing fails, try to handle concatenated JSON objects
        if verbose_mode:
            on_print(f"[DEBUG] Initial JSON parsing failed, attempting to handle concatenated JSON objects", Fore.CYAN + Style.DIM)
        
        # Try to split and merge multiple JSON objects
        merged_result = try_merge_concatenated_json(json_str, verbose=verbose_mode)
        if merged_result is not None:
            return merged_result
        
        if verbose_mode:
            on_print("Extracted string is not a valid JSON.", Fore.RED)
    else:
        if verbose_mode:
            on_print("Extracted string is not a valid JSON.", Fore.RED)
    
    return []

def generate_tool_response(user_input, tools, selected_model, temperature=0.1, prompt_template=None, num_ctx=None):
    """Generate a response using Ollama that suggests function calls based on the user input."""
    global verbose_mode

    rendered_tools = render_tools(tools)

    # Create the system prompt with the provided tools
    system_prompt = f"""You are an assistant that has access to the following set of tools.
Here are the names and descriptions for each tool:

{rendered_tools}
Given the user input, return your response as a JSON array of objects, each representing a different function call. Each object should have the following structure:
{{"function": {{
"name": A string representing the function's name.
"arguments": An object containing key-value pairs representing the arguments to be passed to the function. }}}}

If no tool is relevant to answer, simply return an empty array: [].
"""

    # Call the existing ask_ollama function
    tool_response = ask_ollama(system_prompt, user_input, selected_model, temperature, prompt_template, no_bot_prompt=True, stream_active=False, num_ctx=num_ctx)

    if verbose_mode:
        on_print(f"Tool response: {tool_response}", Fore.WHITE + Style.DIM)
    
    # The response should be in JSON format already if the function is correct.
    return extract_json(tool_response)

def bytes_to_gibibytes(bytes):
    gigabytes = bytes / (1024 ** 3)
    return f"{gigabytes:.1f} GB"

def select_ollama_model_if_available(model_name):
    global no_system_role
    global verbose_mode

    if not model_name:
        return None

    try:
        models = ollama.list()["models"]
    except:
        on_print("Ollama API is not running.", Fore.RED)
        return None

    for model in models:
        if model["model"] == model_name:
            selected_model = model

            if verbose_mode:
                on_print(f"Selected model: {model_name}", Fore.WHITE + Style.DIM)
            return model_name
        
    on_print(f"Model {model_name} not found.", Fore.RED)
    return None

def select_openai_model_if_available(model_name):
    global verbose_mode
    global openai_client

    if not model_name:
        return None

    try:
        models = openai_client.models.list().data
    except Exception as e:
        on_print(f"Failed to fetch OpenAI models: {str(e)}", Fore.RED)
        return None
    
    # Remove non-chat models from the list (keep only GPT models and oX models like o1 and o3)
    models = [model for model in models if model.id.startswith("gpt-") or model.id.startswith("o")]

    for model in models:
        if model.id == model_name:
            if verbose_mode:
                on_print(f"Selected model: {model_name}", Fore.WHITE + Style.DIM)
            return model_name

    on_print(f"Model {model_name} not found.", Fore.RED)
    return None

def prompt_for_openai_model(default_model, current_model):
    global verbose_mode
    global openai_client

    # List available OpenAI models
    try:
        models = openai_client.models.list().data
    except Exception as e:
        on_print(f"Failed to fetch OpenAI models: {str(e)}", Fore.RED)
        return None

    if current_model is None:
        current_model = default_model
    
    # Remove non-chat models from the list
    models = [model for model in models if model.id.startswith("gpt-")]

    # Display available models
    on_print("Available OpenAI models:\n", Style.RESET_ALL)
    for i, model in enumerate(models):
        star = " *" if model.id == current_model else ""
        on_stdout_write(f"{i}. {model.id}{star}\n")
    on_stdout_flush()

    # Default choice index for current_model
    default_choice_index = None
    for i, model in enumerate(models):
        if model.id == current_model:
            default_choice_index = i
            break

    if default_choice_index is None:
        default_choice_index = 0

    # Prompt user to choose a model
    choice = int(on_user_input("Enter the number of your preferred model [" + str(default_choice_index) + "]: ") or default_choice_index)

    # Select the chosen model
    selected_model = models[choice].id

    if verbose_mode:
        on_print(f"Selected model: {selected_model}", Fore.WHITE + Style.DIM)

    return selected_model

def prompt_for_ollama_model(default_model, current_model):
    global no_system_role
    global verbose_mode

    # List existing ollama models
    try:
        models = ollama.list()["models"]
    except:
        on_print("Ollama API is not running.", Fore.RED)
        return None

    if current_model is None:
        current_model = default_model

    # Ask user to choose a model
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

    # Use the chosen model
    selected_model = models[choice]['model']

    if verbose_mode:
        on_print(f"Selected model: {selected_model}", Fore.WHITE + Style.DIM)
    return selected_model

def is_model_an_ollama_model(model_name):
    global ollama

    try:
        models = ollama.list()["models"]
    except:
        return False

    for model in models:
        if model["model"] == model_name:
            return True

    return False

def prompt_for_model(default_model, current_model):
    global use_openai

    if use_openai:
        return prompt_for_openai_model(default_model, current_model)
    else:
        return prompt_for_ollama_model(default_model, current_model)

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

def save_conversation_to_file(conversation, file_path):
    global verbose_mode

    # Convert conversation list of objects to a list of dict
    conversation = [json.loads(json.dumps(obj, default=lambda o: vars(o))) for obj in conversation]
    
    # Save the conversation to a text file (filter out system messages)
    with open(file_path, 'w', encoding="utf8") as f:
        # Skip empty messages or system messages
        filtered_conversation = [entry for entry in conversation if "content" in entry and entry["content"] and "role" in entry and entry["role"] != "system" and entry["role"] != "tool"]

        for message in filtered_conversation:
            role = message["role"]

            if role == "user":
                role = "Me"
            elif role == "assistant":
                role = "Assistant"
            
            f.write(f"{role}: {message['content']}\n\n")

    if verbose_mode:
        on_print(f"Conversation saved to {file_path}", Fore.WHITE + Style.DIM)

    # Save the conversation to a JSON file
    json_file_path = file_path.replace(".txt", ".json")
    with open(json_file_path, 'w', encoding="utf8") as f:
        json.dump(conversation, f, indent=4)

    if verbose_mode:
        on_print(f"Conversation saved to {json_file_path}", Fore.WHITE + Style.DIM)

def load_chroma_client():
    global chroma_client
    global verbose_mode
    global chroma_client_host
    global chroma_client_port
    global chroma_db_path

    if chroma_client:
        return

    # Initialize the ChromaDB client
    try:
        if chroma_db_path:
            # Set environment variable ANONYMIZED_TELEMETRY to disable telemetry
            os.environ["ANONYMIZED_TELEMETRY"] = "0"
            chroma_client = chromadb.PersistentClient(path=chroma_db_path)
        elif chroma_client_host and 0 < chroma_client_port:
            chroma_client = chromadb.HttpClient(host=chroma_client_host, port=chroma_client_port)
        else:
            raise ValueError("Invalid Chroma client configuration")
    except:
        if verbose_mode:
            on_print("ChromaDB client could not be initialized. Please check the host and port.", Fore.RED + Style.DIM)
        chroma_client = None
        
def summarize_chunk(text_chunk, model, max_summary_words, previous_summary=None, num_ctx=None, language='English'):
    """
    Summarizes a single chunk of text using the provided LLM.

    Args:
        text_chunk (str): The piece of text to summarize.
        model (str): The name of the LLM model to use for summarization.
        max_summary_words (int): The approximate desired word count for the chunk's summary.
        previous_summary (str, optional): The previous summary to include in the prompt. Defaults to None.
        num_ctx (int, optional): The number of context tokens to use for the LLM. Defaults to None.

    Returns:
        str: The summarized text.
    """
    # Instruct the model to produce the summary in the requested language.
    system_prompt = (
        "You are an expert at summarizing text. Your task is to provide a concise summary of the given content, "
        "maintaining context from previous parts. Always produce the summary in the requested language."
    )

    # Add context from the previous summary to the prompt if it exists.
    if previous_summary:
        user_prompt = (
            f"The summary of the previous text chunk (written in {language}) is: \"{previous_summary}\"\n\n"
            f"Based on that context, please summarize the following new text chunk in approximately {max_summary_words} words. "
            f"Make sure the summary is written in {language} and do not include extra commentary:\n\n"
            f"---\n\n{text_chunk}"
        )
    else:
        user_prompt = (
            f"Please summarize the following text in approximately {max_summary_words} words. "
            f"Make sure the summary is written in {language} and do not include extra commentary:\n\n---\n\n{text_chunk}"
        )

    # This function call should interact with your local LLM. Enforce language in the call.
    summary = ask_ollama(system_prompt, user_prompt, model, no_bot_prompt=True, stream_active=False, num_ctx=num_ctx)
    # If the LLM returns an empty or None response, return an empty string to avoid breaking callers
    return summary or ""

def summarize_text_file(file_path, model=None, chunk_size=400, overlap=50, max_final_words=500, num_ctx=None, language='English'):
    """
    Summarizes a long text by breaking it into chunks, summarizing them,
    and then iteratively summarizing the summaries until the final text is
    under a specified word count.

    Args:
        file_path (str): The complete text file to summarize.
        model (str): The model name to be used for the summarization (e.g., 'llama3').
        chunk_size (int): The number of words in each text chunk.
        overlap (int): The number of words to overlap between consecutive chunks to maintain context.
        max_final_words (int): The maximum number of words desired for the final summary.
        num_ctx (int, optional): The number of context tokens to use for the LLM. Defaults to None.
        language (str): Language in which intermediate and final summaries should be produced. Defaults to 'English'.
        verbose_mode (bool): If True, print detailed information about the summarization process.

    Returns:
        str: The final, concise summary.
    """
    global current_model
    global verbose_mode
    
    if not model:
        model = current_model
    
    # Read the full text from the file
    with open(file_path, 'r', encoding='utf-8') as f:
        full_text = f.read()
    
    words = full_text.split()
    current_text_words = words

    while len(current_text_words) > max_final_words:
        if verbose_mode:
            on_print(f"\n>>> Iteration: Processing {len(current_text_words)} words...", Fore.WHITE + Style.DIM)

        # Determine the size of the summary for each chunk in this iteration
        # We want the total summary to be smaller than the current text length
        num_chunks_approx = math.ceil(len(current_text_words) / (chunk_size - overlap))
        # Aim for summaries that are collectively about half the size of the current text
        # but don't make individual summaries smaller than a reasonable minimum.
        per_chunk_summary_words = max(25, (len(current_text_words) // 2) // num_chunks_approx)


        chunks = []
        start = 0
        while start < len(current_text_words):
            end = start + chunk_size
            chunks.append(" ".join(current_text_words[start:end]))
            start += chunk_size - overlap
            if start >= len(current_text_words):
                break

        summaries = []
        previous_summary = None # Keep track of the last summary
        for i, chunk in enumerate(chunks):
            if verbose_mode:
                on_print(f"Processing chunk {i+1}/{len(chunks)} with {len(chunk.split())} words", Fore.WHITE + Style.DIM)
            summary = summarize_chunk(chunk, model, per_chunk_summary_words, previous_summary=previous_summary, num_ctx=num_ctx, language=language)
            summaries.append(summary)
            previous_summary = summary # Update the previous summary for the next iteration

        # The new text to be summarized is the concatenation of the summaries from this round
        combined_summaries = " ".join(summaries)
        current_text_words = combined_summaries.split()

        if verbose_mode:
            on_print(f"<<< Iteration Complete: {len(summaries)} summaries created, new word count is {len(current_text_words)}", Fore.WHITE + Style.DIM)
            on_print(f"Current text after summarization: {combined_summaries[:100]}...", Fore.WHITE + Style.DIM)

    final_summary = " ".join(current_text_words)
    return final_summary

def run():
    global current_collection_name
    global memory_collection_name
    global long_term_memory_file
    global collection
    global chroma_client
    global openai_client
    global use_openai
    global use_azure_openai
    global no_system_role
    global prompt_template
    global verbose_mode
    global embeddings_model
    global syntax_highlighting
    global interactive_mode
    global chroma_client_host
    global chroma_client_port
    global chroma_db_path
    global plugins
    global plugins_folder
    global selected_tools
    global current_model
    global alternate_model
    global user_prompt
    global other_instance_url
    global listening_port
    global memory_manager
    global thinking_model
    global thinking_model_reasoning_pattern
    global number_of_documents_to_return_from_vector_db
    global think_mode_on
    
    default_model = None
    prompt_template = None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")  # Enable tab completion

    # If specified as script named arguments, use the provided ChromaDB client host (--chroma-host) and port (--chroma-port)
    parser = argparse.ArgumentParser(description='Run the Ollama chatbot.')
    parser.add_argument('--list-tools', action='store_true', help='List available tools and exit')
    parser.add_argument('--list-collections', action='store_true', help='List available ChromaDB collections and exit')
    parser.add_argument('--chroma-path', type=str, help='ChromaDB database path', default=None)
    parser.add_argument('--chroma-host', type=str, help='ChromaDB client host', default="localhost")
    parser.add_argument('--chroma-port', type=int, help='ChromaDB client port', default=8000)
    parser.add_argument('--docs-to-fetch-from-chroma', type=int, help="Number of documents to return from the vector database when querying for similar documents", default=number_of_documents_to_return_from_vector_db)
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
    parser.add_argument('--full-docs-db', type=str, help='Path to SQLite database for storing full document content (default: full_documents.db)', default='full_documents.db')
    parser.add_argument('--catchup-full-docs', type=bool, help='Index full documents from ChromaDB metadata (catchup for existing chunks)', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--query', type=str, help='Query the vector database and exit (non-interactive mode)', default=None)
    parser.add_argument('--query-n-results', type=int, help='Number of results to return from vector database query', default=None)
    parser.add_argument('--query-distance-threshold', type=float, help='Distance threshold for filtering query results', default=0.0)
    parser.add_argument('--expand-query', type=bool, help='Expand query for better retrieval', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--include-full-docs', type=bool, help='Include full original documents in query results (requires --full-docs-db)', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--interactive', type=bool, help='Use interactive mode', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--plugins-folder', type=str, default=None, help='Path to the plugins folder')
    parser.add_argument('--stream', type=bool, help='Use stream mode for Ollama API', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--output', type=str, help='Output file path', default=None)
    parser.add_argument('--other-instance-url', type=str, help=f"URL of another {__name__} instance to connect to", default=None)
    parser.add_argument('--listening-port', type=int, help=f"Listening port for the current {__name__} instance", default=8000)
    parser.add_argument('--user-name', type=str, help='User name', default=None)
    parser.add_argument('--anonymous', type=bool, help='Do not use the user name from the environment variables', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--memory', type=str, help='Use memory manager for context management', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--context-window', type=int, help='Ollama context window size, if not specified, the default value is used, which is 2048 tokens', default=None) 
    parser.add_argument('--auto-start', type=bool, help="Start the conversation automatically", default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--tools', type=str, help="List of tools to activate and use in the conversation, separated by commas", default=None)
    parser.add_argument('--memory-collection-name', type=str, help="Name of the memory collection to use for context management", default=memory_collection_name)
    parser.add_argument('--long-term-memory-file', type=str, help="Long-term memory file name", default=long_term_memory_file)
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

    plugins_folder = args.plugins_folder
    verbose_mode = args.verbose
    disable_plugins = args.disable_plugins
    
    # Automatically disable plugins when using RAG-specific parameters (indexing, querying, or web search)
    # These operations don't need plugins and disabling them speeds up execution
    rag_operations_requested = args.index_documents or args.query or args.web_search
    if rag_operations_requested and not disable_plugins:
        disable_plugins = True
        if verbose_mode:
            on_print("Plugins automatically disabled for RAG operations (indexing/querying/web-search).", Fore.YELLOW)
    
    # Parse requested tool names from command line
    requested_tool_names = args.tools.split(',') if args.tools else []
    
    # We'll also need to check chatbot tools, but we need to load chatbot config first
    # For now, determine if plugins need to be loaded based on command line tools
    # Plugins are loaded if:
    # 1. --disable-plugins is not set, OR
    # 2. Any requested tool is a plugin tool (not built-in)
    load_plugins_initially = not disable_plugins or requires_plugins(requested_tool_names)
    
    if verbose_mode and disable_plugins and not load_plugins_initially:
        on_print("Plugins are disabled and no plugin tools were requested via command line.", Fore.YELLOW)
    elif verbose_mode and disable_plugins and load_plugins_initially:
        on_print("Plugins are disabled but plugin tools were requested. Loading plugins anyway.", Fore.YELLOW)
    
    # Discover plugins before listing tools
    if args.list_tools:
        # Load plugins first
        global plugins
        plugins = discover_plugins(plugins_folder, load_plugins=True)  # Always load for --list-tools
        if verbose_mode:
            on_print(f"\nDiscovered {len(plugins)} plugins")
        
        tools = get_available_tools()
        on_print("\nAvailable tools:")
        
        # Split tools into built-in and plugin tools
        builtin_tools = [tool for tool in tools if not any(pt['function']['name'] == tool['function']['name'] for p in plugins for pt in ([p.get_tool_definition()] if hasattr(p, 'get_tool_definition') and callable(getattr(p, 'get_tool_definition')) else []))]
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
        chroma_client_host = args.chroma_host
        chroma_client_port = args.chroma_port
        chroma_db_path = args.chroma_path
        verbose_mode = args.verbose
        
        load_chroma_client()
        
        if not chroma_client:
            on_print("Failed to initialize ChromaDB client.", Fore.RED)
            sys.exit(1)
        
        try:
            collections = chroma_client.list_collections()
            
            if not collections:
                on_print("\nNo collections found.")
            else:
                on_print(f"\nAvailable ChromaDB collections ({len(collections)}):")
                on_print("=" * 80)
                
                for collection in collections:
                    on_print(f"\nCollection: {collection.name}")
                    
                    # Get collection metadata
                    if hasattr(collection, 'metadata') and collection.metadata:
                        if isinstance(collection.metadata, dict):
                            if 'description' in collection.metadata:
                                on_print(f"  Description: {collection.metadata['description']}")
                            
                            # Print other metadata
                            for key, value in collection.metadata.items():
                                if key != 'description':
                                    on_print(f"  {key}: {value}")
                    
                    # Get collection count
                    try:
                        count = collection.count()
                        on_print(f"  Documents: {count}")
                    except:
                        pass
                
                on_print("\n" + "=" * 80)
        
        except Exception as e:
            on_print(f"Error listing collections: {str(e)}", Fore.RED)
            if verbose_mode:
                import traceback
                traceback.print_exc()
            sys.exit(1)
        
        sys.exit(0)

    preferred_collection_name = args.collection
    use_openai = args.use_openai
    use_azure_openai = args.use_azure_openai
    chroma_client_host = args.chroma_host
    chroma_client_port = args.chroma_port
    chroma_db_path = args.chroma_path
    temperature = args.temperature
    no_system_role = bool(args.disable_system_role)
    current_collection_name = preferred_collection_name
    prompt_template = args.prompt_template
    additional_chatbots_file = args.additional_chatbots
    verbose_mode = args.verbose
    initial_system_prompt = args.system_prompt
    system_prompt_placeholders_json = args.system_prompt_placeholders_json
    preferred_model = args.model
    thinking_model = args.thinking_model
    thinking_model_reasoning_pattern = args.thinking_model_reasoning_pattern
    number_of_documents_to_return_from_vector_db = args.docs_to_fetch_from_chroma

    if not thinking_model:
        thinking_model = preferred_model

    if verbose_mode:
        on_print(f"Using thinking model: {thinking_model}", Fore.WHITE + Style.DIM)

    conversations_folder = args.conversations_folder
    auto_save = args.auto_save
    syntax_highlighting = args.syntax_highlighting
    interactive_mode = args.interactive
    embeddings_model = args.embeddings_model
    plugins_folder = args.plugins_folder
    user_prompt = args.prompt
    stream_active = args.stream
    output_file = args.output
    other_instance_url = args.other_instance_url
    listening_port = args.listening_port
    custom_user_name = args.user_name
    no_user_name = args.anonymous
    use_memory_manager = args.memory
    num_ctx = args.context_window
    auto_start_conversation = args.auto_start
    memory_collection_name = args.memory_collection_name
    long_term_memory_file = args.long_term_memory_file

    if verbose_mode and num_ctx:
        on_print(f"Ollama context window size: {num_ctx}", Fore.WHITE + Style.DIM)

    # Get today's date
    today = f"Today's date is {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}."

    system_prompt_placeholders = {}
    if system_prompt_placeholders_json and os.path.exists(system_prompt_placeholders_json):
        with open(system_prompt_placeholders_json, 'r', encoding="utf8") as f:
            system_prompt_placeholders = json.load(f)

    # If output file already exists, ask user for confirmation to overwrite
    if output_file and os.path.exists(output_file):
        if interactive_mode:
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

    if verbose_mode and user_prompt:
        on_print(f"User prompt: {user_prompt}", Fore.WHITE + Style.DIM)

    # Load additional chatbots from a JSON file to check for tools
    load_additional_chatbots(additional_chatbots_file)

    chatbot = None
    if args.chatbot:
        # Trim the chatbot name to remove any leading or trailing spaces, single or double quotes
        args.chatbot = args.chatbot.strip().strip('\'').strip('\"')
        for bot in chatbots:
            if bot["name"] == args.chatbot:
                chatbot = bot
                break
        if chatbot is None:
            on_print(f"Chatbot '{args.chatbot}' not found.", Fore.RED)
            
        if verbose_mode and chatbot and 'name' in chatbot:
            on_print(f"Using chatbot: {chatbot['name']}", Fore.WHITE + Style.DIM)
    
    if chatbot is None:
        # Load the default chatbot
        chatbot = chatbots[0]
    
    # Now check if chatbot has tools that require plugins
    chatbot_tool_names = chatbot.get("tools", []) if chatbot else []
    all_requested_tools = requested_tool_names + chatbot_tool_names
    
    # Final determination: load plugins if not disabled OR if any requested tool is a plugin tool
    load_plugins = not disable_plugins or requires_plugins(all_requested_tools)
    
    if verbose_mode and disable_plugins and requires_plugins(chatbot_tool_names):
        on_print("Chatbot requires plugin tools. Loading plugins despite --disable-plugins flag.", Fore.YELLOW)
    
    plugins = discover_plugins(plugins_folder, load_plugins=load_plugins)

    if verbose_mode:
        on_print(f"Verbose mode: {verbose_mode}", Fore.WHITE + Style.DIM)

    # Initialize global full document store for LLM tool use
    # This allows query_vector_database to retrieve full documents when called as a tool
    global full_doc_store
    if args.full_docs_db and os.path.exists(args.full_docs_db):
        try:
            full_doc_store = FullDocumentStore(db_path=args.full_docs_db, verbose=verbose_mode)
            if verbose_mode:
                on_print(f"Initialized global full document store: {args.full_docs_db}", Fore.WHITE + Style.DIM)
        except Exception as e:
            on_print(f"Warning: Failed to initialize full document store: {e}", Fore.YELLOW)
            full_doc_store = None

    # Handle document indexing if requested
    if args.index_documents:
        load_chroma_client()
        
        if not chroma_client:
            on_print("Failed to initialize ChromaDB client. Please specify --chroma-path or --chroma-host/--chroma-port.", Fore.RED)
            sys.exit(1)
        
        if not current_collection_name:
            on_print("No ChromaDB collection specified. Use --collection to specify a collection name.", Fore.RED)
            sys.exit(1)
        
        if verbose_mode:
            on_print(f"Indexing documents from: {args.index_documents}", Fore.WHITE + Style.DIM)
            on_print(f"Collection: {current_collection_name}", Fore.WHITE + Style.DIM)
            on_print(f"Chunking: {args.chunk_documents}", Fore.WHITE + Style.DIM)
            on_print(f"Skip existing: {args.skip_existing}", Fore.WHITE + Style.DIM)
            if args.extract_start or args.extract_end:
                on_print(f"Extraction range: '{args.extract_start}' to '{args.extract_end}'", Fore.WHITE + Style.DIM)
            on_print(f"Split paragraphs: {args.split_paragraphs}", Fore.WHITE + Style.DIM)
            on_print(f"Add summary: {args.add_summary}", Fore.WHITE + Style.DIM)
            on_print(f"Full docs database: {args.full_docs_db}", Fore.WHITE + Style.DIM)
        
        # Initialize full document store if chunking is enabled
        full_doc_store = None
        if args.chunk_documents:
            full_doc_store = FullDocumentStore(db_path=args.full_docs_db, verbose=verbose_mode)
        
        document_indexer = DocumentIndexer(
            args.index_documents, 
            current_collection_name, 
            chroma_client, 
            embeddings_model, 
            verbose=verbose_mode,
            summary_model=current_model,
            full_doc_store=full_doc_store
        )
        
        document_indexer.index_documents(
            allow_chunks=args.chunk_documents,
            no_chunking_confirmation=True,  # Non-interactive mode
            split_paragraphs=args.split_paragraphs,
            num_ctx=num_ctx,
            skip_existing=args.skip_existing,
            extract_start=args.extract_start,
            extract_end=args.extract_end,
            add_summary=args.add_summary
        )
        
        # Close full document store if it was initialized
        if full_doc_store:
            full_doc_store.close()
        
        on_print(f"Indexing completed for folder: {args.index_documents}", Fore.GREEN)
        
        # If only indexing (no query or interactive mode), exit
        if not args.query and not interactive_mode:
            sys.exit(0)
    
    # Handle catchup of full documents from ChromaDB metadata
    if args.catchup_full_docs:
        load_chroma_client()
        
        if not chroma_client:
            on_print("Failed to initialize ChromaDB client. Please specify --chroma-path or --chroma-host/--chroma-port.", Fore.RED)
            sys.exit(1)
        
        if not current_collection_name:
            on_print("No ChromaDB collection specified. Use --collection to specify a collection name.", Fore.RED)
            sys.exit(1)
        
        if verbose_mode:
            on_print(f"Running catchup for collection: {current_collection_name}", Fore.WHITE + Style.DIM)
            on_print(f"Full docs database: {args.full_docs_db}", Fore.WHITE + Style.DIM)
        
        # Initialize full document store
        full_doc_store = FullDocumentStore(db_path=args.full_docs_db, verbose=verbose_mode)
        
        try:
            # Run catchup
            indexed_count = catchup_full_documents_from_chromadb(
                chroma_client,
                current_collection_name,
                full_doc_store,
                verbose=verbose_mode
            )
            
            on_print(f"\nCatchup completed. Indexed {indexed_count} full documents.", Fore.GREEN)
        finally:
            full_doc_store.close()
        
        # If only doing catchup (no query or interactive mode), exit
        if not args.query and not interactive_mode:
            sys.exit(0)
    
    # Handle vector database query if requested
    if args.query:
        load_chroma_client()
        
        if not current_collection_name:
            on_print("No ChromaDB collection specified. Use --collection to specify a collection name.", Fore.RED)
            sys.exit(1)
        
        # Set query parameters
        query_n_results = args.query_n_results if args.query_n_results is not None else number_of_documents_to_return_from_vector_db
        
        if verbose_mode:
            on_print(f"Querying collection: {current_collection_name}", Fore.WHITE + Style.DIM)
            on_print(f"Query: {args.query}", Fore.WHITE + Style.DIM)
            on_print(f"Number of results: {query_n_results}", Fore.WHITE + Style.DIM)
            on_print(f"Distance threshold: {args.query_distance_threshold}", Fore.WHITE + Style.DIM)
            on_print(f"Expand query: {args.expand_query}", Fore.WHITE + Style.DIM)
            on_print(f"Include full documents: {args.include_full_docs}", Fore.WHITE + Style.DIM)
            if args.include_full_docs:
                on_print(f"Full docs database: {args.full_docs_db}", Fore.WHITE + Style.DIM)
        
        # Initialize full document store if requested
        full_doc_store = None
        if args.include_full_docs:
            full_doc_store = FullDocumentStore(db_path=args.full_docs_db, verbose=verbose_mode)
        
        try:
            # Query the vector database
            query_results = query_vector_database(
                args.query,
                collection_name=current_collection_name,
                n_results=query_n_results,
                answer_distance_threshold=args.query_distance_threshold,
                query_embeddings_model=embeddings_model,
                expand_query=args.expand_query,
                full_doc_store=full_doc_store,
                include_full_docs=args.include_full_docs
            )
        finally:
            # Close full document store if it was initialized
            if full_doc_store:
                full_doc_store.close()
        
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
        if not interactive_mode:
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
        
        if verbose_mode:
            on_print(f"Instantiating agent: {args.agent_name}", Fore.WHITE + Style.DIM)
            on_print(f"Task: {args.agent_task}", Fore.WHITE + Style.DIM)
            on_print(f"System Prompt: {args.agent_system_prompt}", Fore.WHITE + Style.DIM)
            on_print(f"Tools: {agent_tools_list}", Fore.WHITE + Style.DIM)
            on_print(f"Description: {args.agent_description}", Fore.WHITE + Style.DIM)
        
        # Load ChromaDB if needed (for agents that use vector database tools)
        load_chroma_client()
        
        # Ensure plugins are loaded if any of the agent tools require them
        if not plugins and requires_plugins(agent_tools_list):
            plugins = discover_plugins(plugins_folder, load_plugins=True)
        
        # Initialize the model and API client (required for agent instantiation)
        # Set up Azure OpenAI client if using Azure
        if use_azure_openai and not openai_client:
            from openai import AzureOpenAI
            
            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
            
            if api_key and azure_endpoint and deployment:
                openai_client = AzureOpenAI(
                    api_version="2024-02-15-preview",
                    azure_endpoint=azure_endpoint,
                    api_key=api_key,
                )
                current_model = deployment
                if verbose_mode:
                    on_print(f"Azure OpenAI initialized with deployment: {deployment}", Fore.WHITE + Style.DIM)
            else:
                on_print("Azure OpenAI configuration incomplete, falling back to Ollama", Fore.YELLOW)
                use_azure_openai = False
        
        # Set up OpenAI client if using OpenAI
        if use_openai and not use_azure_openai and not openai_client:
            from openai import OpenAI
            
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                openai_client = OpenAI(api_key=api_key)
                current_model = preferred_model if preferred_model else "gpt-4"
                if verbose_mode:
                    on_print(f"OpenAI initialized with model: {current_model}", Fore.WHITE + Style.DIM)
            else:
                if verbose_mode:
                    on_print("OpenAI API key not found, falling back to Ollama", Fore.YELLOW)
                use_openai = False
        
        # Initialize the model if not using OpenAI/Azure
        if not current_model:
            if not use_openai and not use_azure_openai:
                # For Ollama, select available model
                default_model_temp = preferred_model if preferred_model else "qwen3:4b"
                if ":" not in default_model_temp:
                    default_model_temp += ":latest"
                current_model = select_ollama_model_if_available(default_model_temp)
        
        if verbose_mode:
            on_print(f"Using model: {current_model}", Fore.WHITE + Style.DIM)
            on_print(f"Use Azure OpenAI: {use_azure_openai}", Fore.WHITE + Style.DIM)
            on_print(f"Use OpenAI: {use_openai}", Fore.WHITE + Style.DIM)
        
        # Call the agent instantiation function directly
        result = instantiate_agent_with_tools_and_process_task(
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
                
            if verbose_mode:
                on_print(f"Agent result saved to: {output_file}", Fore.GREEN)
        else:
            on_print(result)
        
        # Exit after agent execution (non-interactive mode)
        if not interactive_mode:
            sys.exit(0)

    auto_start_conversation = ("starts_conversation" in chatbot and chatbot["starts_conversation"]) or auto_start_conversation
    system_prompt = chatbot["system_prompt"]
    use_openai = use_openai or (hasattr(chatbot, 'use_openai') and getattr(chatbot, 'use_openai'))
    use_azure_openai = use_azure_openai or (hasattr(chatbot, 'use_azure_openai') and getattr(chatbot, 'use_azure_openai'))
    if "preferred_model" in chatbot:
        default_model = chatbot["preferred_model"]
    if preferred_model:
        default_model = preferred_model

    if not use_openai and not use_azure_openai:
        # If default model does not contain ":", append ":latest" to the model name
        if default_model and ":" not in default_model:
            default_model += ":latest"

        selected_model = select_ollama_model_if_available(default_model)
    elif use_azure_openai:
        from openai import AzureOpenAI
        
        # Get API key from environment variable
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        if not api_key:
            on_print("No Azure OpenAI API key found in the environment variables, make sure to set the AZURE_OPENAI_API_KEY.", Fore.RED)
            use_azure_openai = False
        else:
            if verbose_mode:
                on_print("Azure OpenAI API key found in the environment variables, redirecting to Azure OpenAI API.", Fore.WHITE + Style.DIM)
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

            if not azure_endpoint:
                on_print("No Azure OpenAI endpoint found in the environment variables, make sure to set the AZURE_OPENAI_ENDPOINT.", Fore.RED)
                use_azure_openai = False

            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

            if not deployment:
                on_print("No Azure OpenAI deployment found in the environment variables, make sure to set the AZURE_OPENAI_DEPLOYMENT.", Fore.RED)
                use_azure_openai = False

            if use_azure_openai:
                if verbose_mode:
                    on_print("Using Azure OpenAI API, endpoint: " + azure_endpoint + ", deployment: " + deployment, Fore.WHITE + Style.DIM)

                openai_client = AzureOpenAI(
                    api_version="2024-02-15-preview",
                    azure_endpoint=azure_endpoint,
                    api_key=api_key,
                    azure_deployment=deployment
                )
                
                selected_model = deployment
                current_model = selected_model
                use_openai = True
                stream_active = False
                syntax_highlighting = True
    else:
        from openai import OpenAI

        # Get API key from environment variable
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            if verbose_mode:
                on_print("No OpenAI API key found in the environment variables, calling local OpenAI API.", Fore.WHITE + Style.DIM)
            openai_client = OpenAI(
                base_url="http://127.0.0.1:8080",
                api_key="none"
            )
        else:
            if verbose_mode:
                on_print("OpenAI API key found in the environment variables, redirecting to OpenAI API.", Fore.WHITE + Style.DIM)
            openai_client = OpenAI(
                api_key=api_key
            )

        selected_model = select_openai_model_if_available(default_model)

    if selected_model is None:
        selected_model = prompt_for_model(default_model, current_model)
        current_model = selected_model
        if selected_model is None:
            return

    if not system_prompt:
        if no_system_role:
            on_print("The selected model does not support the 'system' role.", Fore.WHITE + Style.DIM)
            system_prompt = ""
        else:
            system_prompt = "You are a helpful chatbot assistant. Possible chatbot prompt commands: " + print_possible_prompt_commands()

    user_name = custom_user_name or get_personal_info()["user_name"]
    if no_user_name:
        user_name = ""
        if verbose_mode:
            on_print("User name not used.", Fore.WHITE + Style.DIM)

    # Set the current collection
    set_current_collection(current_collection_name, verbose=verbose_mode)

    # Initial system message
    if initial_system_prompt:
        if verbose_mode:
            on_print("Initial system prompt: " + initial_system_prompt, Fore.WHITE + Style.DIM)
        system_prompt = initial_system_prompt

    if not no_system_role and len(user_name) > 0:
        first_name = user_name.split()[0]
        system_prompt += f"\nThe user's name is {user_name}, first name: {first_name}. {today}"

    if len(system_prompt) > 0:
        # Replace placeholders in the system_prompt using the system_prompt_placeholders dictionary
        for key, value in system_prompt_placeholders.items():
            system_prompt = system_prompt.replace(f"{{{{{key}}}}}", value)

        initial_message = {"role": "system", "content": system_prompt}
        conversation = [initial_message]
    else:
        initial_message = None
        conversation = []

    current_model = selected_model

    answer_and_exit = False
    if not interactive_mode and user_prompt:
        answer_and_exit = True

    if use_memory_manager:
        load_chroma_client()

        if chroma_client:
            memory_manager = MemoryManager(memory_collection_name, chroma_client, current_model, embeddings_model, verbose_mode, num_ctx=num_ctx, long_term_memory_file=long_term_memory_file)

            if initial_message:
                # Add long-term memory to the system prompt
                long_term_memory = memory_manager.long_term_memory_manager.memory

                initial_message["content"] += f"\n\nLong-term memory: {long_term_memory}"
        else:
            use_memory_manager = False

    if initial_message and verbose_mode:
        on_print("System prompt: " + initial_message["content"], Fore.WHITE + Style.DIM)

    user_input = ""

    if "tools" in chatbot and len(chatbot["tools"]) > 0:
        # Append chatbot tools to selected_tools if not already in the array
        if selected_tools is None:
            selected_tools = []
        
        for tool in chatbot["tools"]:
            selected_tools = select_tool_by_name(get_available_tools(), selected_tools, tool)
    
    selected_tool_names = args.tools.split(',') if args.tools else []
    for tool_name in selected_tool_names:
        # Strip any leading or trailing spaces, single or double quotes
        tool_name = tool_name.strip().strip('\'').strip('\"')
        selected_tools = select_tool_by_name(get_available_tools(), selected_tools, tool_name)

    # Handle web search if requested (after model initialization)
    if args.web_search:
        show_intermediate = args.web_search_show_intermediate
        
        if verbose_mode:
            on_print(f"Performing web search for: {args.web_search}", Fore.WHITE + Style.DIM)
            on_print(f"Number of results: {args.web_search_results}", Fore.WHITE + Style.DIM)
            on_print(f"Region: {args.web_search_region}", Fore.WHITE + Style.DIM)
            on_print(f"Show intermediate results: {show_intermediate}", Fore.WHITE + Style.DIM)
        
        # Ensure ChromaDB is loaded for web search caching
        load_chroma_client()
        
        if not chroma_client:
            on_print("Web search requires ChromaDB to be running. Please start ChromaDB server or configure a persistent database path.", Fore.RED)
            sys.exit(1)
        
        # Perform the web search
        if show_intermediate:
            on_print("\n" + "="*80, Fore.MAGENTA)
            on_print("SEARCHING THE WEB, QUERY: " + args.web_search, Fore.MAGENTA + Style.BRIGHT)
            on_print("="*80, Fore.MAGENTA)
            
            web_search_response, intermediate_data = web_search(
                args.web_search, 
                n_results=args.web_search_results, 
                region=args.web_search_region,
                web_embedding_model=embeddings_model,
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
            web_search_response = web_search(
                args.web_search, 
                n_results=args.web_search_results, 
                region=args.web_search_region,
                web_embedding_model=embeddings_model,
                num_ctx=num_ctx,
                return_intermediate=False
            )
        
        if web_search_response:
            # Build the prompt with web search context
            web_search_prompt = f"Context: {web_search_response}\n\n"
            web_search_prompt += f"Question: {args.web_search}\n"
            web_search_prompt += "Answer the question as truthfully as possible using the provided web search results, and if the answer is not contained within the text above, say 'I don't know'.\n"
            web_search_prompt += "Cite some useful links from the search results to support your answer."
            
            if verbose_mode:
                on_print("\n" + "="*80, Fore.CYAN)
                on_print("WEB SEARCH CONTEXT", Fore.CYAN + Style.BRIGHT)
                on_print("="*80, Fore.CYAN)
                on_print(web_search_response, Fore.WHITE + Style.DIM)
                on_print("="*80, Fore.CYAN)
            
            # Use the current model (already initialized)
            if verbose_mode:
                on_print(f"Using model: {current_model}", Fore.WHITE + Style.DIM)
            
            # Get answer from the model
            on_print("\n" + "="*80, Fore.GREEN)
            on_print("ANSWER", Fore.GREEN + Style.BRIGHT)
            on_print("="*80, Fore.GREEN)
            
            answer = ask_ollama(
                "",
                web_search_prompt,
                current_model,
                temperature=temperature,
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
        if not interactive_mode:
            sys.exit(0)

    # Main conversation loop
    while True:
        thoughts = None
        if not auto_start_conversation:
            try:
                if interactive_mode:
                    on_prompt("\nYou: ", Fore.YELLOW + Style.NORMAL)

                if user_prompt:
                    if other_instance_url:
                        conversation.append({"role": "assistant", "content": user_prompt})
                        user_input = on_user_input(user_prompt)
                    else:
                        user_input = user_prompt
                    user_prompt = None
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
            if memory_manager:
                on_print("Saving conversation to memory...", Fore.WHITE + Style.DIM)
                if memory_manager.add_memory(conversation):
                    on_print("Conversation saved to memory.", Fore.WHITE + Style.DIM)
                    on_print("", Style.RESET_ALL)
            break

        if user_input.lower() in ['/reset', '/clear', '/restart', 'reset', 'clear', 'restart']:
            on_print("Conversation reset.", Style.RESET_ALL)
            if initial_message:
                conversation = [initial_message]
            else:
                conversation = []

            auto_start_conversation = ("starts_conversation" in chatbot and chatbot["starts_conversation"]) or args.auto_start
            user_input = ""
            continue

        for plugin in plugins:
            if hasattr(plugin, "on_user_input_done") and callable(getattr(plugin, "on_user_input_done")):
                user_input_from_plugin = plugin.on_user_input_done(user_input, verbose_mode=verbose_mode)
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
                    if verbose_mode:
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

                if verbose_mode:
                    on_print("System prompt: " + system_prompt, Fore.WHITE + Style.DIM)

                for entry in conversation:
                    if "role" in entry and entry["role"] == "system":
                        entry["content"] = system_prompt
                        break
            continue

        if "/index" in user_input:
            if not chroma_client:
                on_print("ChromaDB client not initialized.", Fore.RED)
                continue

            load_chroma_client()

            if not current_collection_name:
                on_print("No ChromaDB collection loaded.", Fore.RED)

                collection_name, collection_description = prompt_for_vector_database_collection()
                set_current_collection(collection_name, collection_description, verbose=verbose_mode)

            folder_to_index = user_input.split("/index")[1].strip()
            temp_folder = None
            if folder_to_index.startswith("http"):
                base_url = folder_to_index
                temp_folder = tempfile.mkdtemp()
                scraper = SimpleWebScraper(base_url, output_dir=temp_folder, file_types=["html", "htm"], restrict_to_base=True, convert_to_markdown=True, verbose=verbose_mode)
                scraper.scrape()
                folder_to_index = temp_folder

            document_indexer = DocumentIndexer(folder_to_index, current_collection_name, chroma_client, embeddings_model, verbose=verbose_mode, summary_model=current_model)
            document_indexer.index_documents(num_ctx=num_ctx)

            if temp_folder:
                # Remove the temporary folder and its contents
                for file in os.listdir(temp_folder):
                    file_path = os.path.join(temp_folder, file)
                    os.remove(file_path)
                os.rmdir(temp_folder)
            continue

        if user_input == "/verbose":
            verbose_mode = not verbose_mode
            on_print(f"Verbose mode: {verbose_mode}", Fore.WHITE + Style.DIM)
            continue

        if "/cot" in user_input:
            user_input = user_input.replace("/cot", "").strip()
            chain_of_thoughts_system_prompt = generate_chain_of_thoughts_system_prompt(selected_tools)

            # Format the current conversation as user/assistant messages
            formatted_conversation = "\n".join([f"{entry['role']}: {entry['content']}" for entry in conversation if "content" in entry and entry["content"] and "role" in entry and entry["role"] != "system" and entry["role"] != "tool"])
            formatted_conversation += "\n\n" + user_input

            thoughts = ask_ollama(chain_of_thoughts_system_prompt, formatted_conversation, thinking_model, temperature, prompt_template, no_bot_prompt=True, stream_active=False, num_ctx=num_ctx)

        if "/search" in user_input:
            # If /search is followed by a number, use that number as the number of documents to return (/search can be anywhere in the prompt)
            if re.search(r'/search\s+\d+', user_input):
                n_docs_to_return = int(re.search(r'/search\s+(\d+)', user_input).group(1))
                user_input = user_input.replace(f"/search {n_docs_to_return}", "").strip()
            else:
                user_input = user_input.replace("/search", "").strip()
                n_docs_to_return = number_of_documents_to_return_from_vector_db

            answer_from_vector_db = query_vector_database(user_input, collection_name=current_collection_name, n_results=n_docs_to_return)
            if answer_from_vector_db:
                initial_user_input = user_input
                user_input = "Question: " + initial_user_input
                user_input += "\n\nAnswer the question as truthfully as possible using the provided text below, and if the answer is not contained within the text below, say 'I don't know'.\n\n"
                user_input += answer_from_vector_db
                user_input += "\n\nAnswer the question as truthfully as possible using the provided text above, and if the answer is not contained within the text above, say 'I don't know'."
                user_input += "\nQuestion: " + initial_user_input

                if verbose_mode:
                    on_print(user_input, Fore.WHITE + Style.DIM)
        elif "/web" in user_input:
            user_input = user_input.replace("/web", "").strip()
            web_search_response = web_search(user_input, num_ctx=num_ctx, web_embedding_model=embeddings_model)
            if web_search_response:
                initial_user_input = user_input
                user_input += "Context: " + web_search_response
                user_input += "\n\nQuestion: " + initial_user_input
                user_input += "\nAnswer the question as truthfully as possible using the provided web search results, and if the answer is not contained within the text below, say 'I don't know'.\n"
                user_input += "Cite some useful links from the search results to support your answer."

                if verbose_mode:
                    on_print(user_input, Fore.WHITE + Style.DIM)

        if user_input == "/thinking_model":
            selected_model = prompt_for_model(default_model, thinking_model)
            thinking_model = selected_model
            continue

        if user_input == "/model":
            thinking_model_is_same = thinking_model == current_model
            
            if use_azure_openai:
                # For Azure OpenAI, just ask for the deployment name
                selected_model = on_user_input(f"Enter Azure OpenAI deployment name [{current_model}]: ").strip() or current_model
            else:
                selected_model = prompt_for_model(default_model, current_model)
            
            current_model = selected_model

            if thinking_model_is_same:
                thinking_model = selected_model

            if use_memory_manager:
                load_chroma_client()

                if chroma_client:
                    memory_manager = MemoryManager(memory_collection_name, chroma_client, current_model, embeddings_model, verbose_mode, num_ctx=num_ctx, long_term_memory_file=long_term_memory_file)
                else:
                    use_memory_manager = False
            continue

        if user_input == "/memory":
            if use_memory_manager:
                # Deactivate memory manager
                memory_manager = None
                use_memory_manager = False
                on_print("Memory manager deactivated.", Fore.WHITE + Style.DIM)
            else:
                load_chroma_client()

                if chroma_client:
                    memory_manager = MemoryManager(memory_collection_name, chroma_client, current_model, embeddings_model, verbose_mode, num_ctx=num_ctx, long_term_memory_file=long_term_memory_file)
                    use_memory_manager = True
                    on_print("Memory manager activated.", Fore.WHITE + Style.DIM)
                else:
                    on_print("ChromaDB client not initialized.", Fore.RED)

            continue

        if user_input == "/model2":
            if use_azure_openai:
                # For Azure OpenAI, just ask for the deployment name
                current_alt = alternate_model if alternate_model else current_model
                alternate_model = on_user_input(f"Enter Azure OpenAI deployment name for alternate model [{current_alt}]: ").strip() or current_alt
            else:
                alternate_model = prompt_for_model(default_model, current_model)
            continue

        if user_input == "/tools":
            selected_tools = select_tools(get_available_tools(), selected_tools=selected_tools)
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
                        initial_message = None

                        # Find system prompt in the conversation
                        for entry in conversation:
                            if "role" in entry and entry["role"] == "system":
                                system_prompt = entry["content"]
                                initial_message = {"role": "system", "content": system_prompt}
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
            set_current_collection(collection_name, collection_description, verbose=verbose_mode)
            continue

        if memory_manager and (user_input == "/remember" or user_input == "/memorize"):
            on_print("Saving conversation to memory...", Fore.WHITE + Style.DIM)
            if memory_manager.add_memory(conversation):
                on_print("Conversation saved to memory.", Fore.WHITE + Style.DIM)
                on_print("", Style.RESET_ALL)
            continue

        if memory_manager and user_input == "/forget":
            # Remove memory collection
            delete_collection(memory_collection_name)
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
                if selected_tools is None:
                    selected_tools = []
                
                for tool in chatbot["tools"]:
                    selected_tools = select_tool_by_name(get_available_tools(), selected_tools, tool)

            system_prompt = chatbot["system_prompt"]
            # Initial system message
            if not no_system_role and len(user_name) > 0:
                first_name = user_name.split()[0]
                system_prompt += f"\nThe user's name is {user_name}, first name: {first_name}. {today}"

            if len(system_prompt) > 0:
                # Replace placeholders in the system_prompt using the system_prompt_placeholders dictionary
                for key, value in system_prompt_placeholders.items():
                    system_prompt = system_prompt.replace(f"{{{{{key}}}}}", value)

                if verbose_mode:
                    on_print("System prompt: " + system_prompt, Fore.WHITE + Style.DIM)

                initial_message = {"role": "system", "content": system_prompt}
                conversation = [initial_message]
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
            
            if (use_openai or use_azure_openai) and is_binary_file:
                # Send as attachment using base64 encoding via Responses API
                user_input = f"{text_before_file} {remaining_text}".strip()
                image_path = file_path
                if verbose_mode:
                    on_print(f"File {file_path} will be sent as base64 attachment.", Fore.WHITE + Style.DIM)
            elif not (use_openai or use_azure_openai) and ext.lower() in [".png", ".jpg", ".jpeg", ".bmp"]:
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
            if not think_mode_on:
                think_mode_on = True
                if verbose_mode:
                    on_print("Think mode activated.", Fore.WHITE + Style.DIM)
            else:
                think_mode_on = False
                if verbose_mode:
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

        if memory_manager:
            memory_manager.handle_user_query(conversation)

        if thoughts:
            thoughts = f"Thinking...\n{thoughts}\nEnd of internal thoughts.\n\nFinal response:"
            if syntax_highlighting:
                on_print(colorize(thoughts), Style.RESET_ALL, "\rBot: " if interactive_mode else "")
            else:
                on_print(thoughts, Style.RESET_ALL, "\rBot: " if interactive_mode else "")
            
            # Add the chain of thoughts to the conversation, as an assistant message
            conversation.append({"role": "assistant", "content": thoughts})

        # Generate response
        bot_response = ask_ollama_with_conversation(conversation, selected_model, temperature=temperature, prompt_template=prompt_template, tools=selected_tools, stream_active=stream_active, num_ctx=num_ctx)

        alternate_bot_response = None
        if alternate_model:
            alternate_bot_response = ask_ollama_with_conversation(conversation, alternate_model, temperature=temperature, prompt_template=prompt_template, tools=selected_tools, prompt="\nAlt", prompt_color=Fore.CYAN, stream_active=stream_active, num_ctx=num_ctx)
        
        bot_response_handled_by_plugin = False
        for plugin in plugins:
            if hasattr(plugin, "on_llm_response") and callable(getattr(plugin, "on_llm_response")):
                plugin_response = getattr(plugin, "on_llm_response")(bot_response)
                bot_response_handled_by_plugin = bot_response_handled_by_plugin or plugin_response

        if not bot_response_handled_by_plugin:
            if syntax_highlighting:
                on_print(colorize(bot_response), Style.RESET_ALL, "\rBot: " if interactive_mode else "")
            
                if alternate_bot_response:
                    on_print(colorize(alternate_bot_response), Fore.CYAN, "\rAlt: " if interactive_mode else "")
            elif not use_openai and not use_azure_openai and len(selected_tools) > 0:
                # Ollama cannot stream when tools are used
                on_print(bot_response, Style.RESET_ALL, "\rBot: " if interactive_mode else "")

                if alternate_bot_response:
                    on_print(alternate_bot_response, Fore.CYAN, "\rAlt: " if interactive_mode else "")

        if alternate_bot_response:
            # Ask user to select the preferred response
            on_print(f"Select the preferred response:\n1. Original model ({current_model})\n2. Alternate model ({alternate_model})", Fore.WHITE + Style.DIM)
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
                    if verbose_mode:
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
    for plugin in plugins:
        if hasattr(plugin, "on_exit") and callable(getattr(plugin, "on_exit")):
            getattr(plugin, "on_exit")()
    
    # Close global full document store if initialized
    if full_doc_store:
        try:
            full_doc_store.close()
            if verbose_mode:
                on_print("Closed global full document store.", Fore.WHITE + Style.DIM)
        except Exception as e:
            on_print(f"Warning: Error closing full document store: {e}", Fore.YELLOW)
    
    if auto_save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if conversations_folder:
            save_conversation_to_file(conversation, os.path.join(conversations_folder, f"conversation_{timestamp}.txt"))
        else:
            save_conversation_to_file(conversation, f"conversation_{timestamp}.txt")

if __name__ == "__main__":
    run()
