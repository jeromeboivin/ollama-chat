import ollama
import platform
import tempfile
from colorama import Fore, Style
import chromadb
import readline

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
from appdirs import AppDirs
from datetime import date, datetime
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import Terminal256Formatter
from duckduckgo_search import DDGS
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from markdownify import MarkdownConverter
import requests
from PyPDF2 import PdfReader
import chardet
from rank_bm25 import BM25Okapi

APP_NAME = "ollama-chat"
APP_AUTHOR = ""
APP_VERSION = "1.0.0"

use_openai = False
no_system_role=False
openai_client = None
chroma_client = None
current_collection_name = None
collection = None
number_of_documents_to_return_from_vector_db = 5
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
memory_manager = None

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

stop_words = ['i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', "you're", "you've", "you'll", "you'd", 'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', "she's", 'her', 'hers', 'herself', 'it', "it's", 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves', 'what', 'which', 'who', 'whom', 'this', 'that', "that'll", 'these', 'those', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', "don't", 'should', "should've", 'now', 'd', 'll', 'm', 'o', 're', 've', 'y', 'ain', 'aren', "aren't", 'couldn', "couldn't", 'didn', "didn't", 'doesn', "doesn't", 'hadn', "hadn't", 'hasn', "hasn't", 'haven', "haven't", 'isn', "isn't", 'ma', 'mightn', "mightn't", 'mustn', "mustn't", 'needn', "needn't", 'shan', "shan't", 'shouldn', "shouldn't", 'wasn', "wasn't", 'weren', "weren't", 'won', "won't", 'wouldn', "wouldn't"]

# List of available commands to autocomplete
COMMANDS = [
    "/context", "/index", "/verbose", "/cot", "/search", "/web", "/model",
    "/model2", "/tools", "/save", "/collection", "/memory", "/remember",
    "/memorize", "/forget", "/rmcollection", "/deletecollection", "/chatbot",
    "/cb", "/file", "/quit", "/exit", "/bye"
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
            'description': f'Performs a semantic search using knowledge base collection named: {current_collection_name}',
            'parameters': {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to search for, in a human-readable format, e.g., 'What is the capital of France?'"
                    },
                    "collection_name": {
                        "type": "string",
                        "description": "The name of the collection to search in",
                        "default": current_collection_name
                    },
                    "question_context": {
                        "type": "string",
                        "description": "Current discussion context or topic, based on previous exchanges with the user"
                    }
                },
                "required": [
                    "question",
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
    }]

    # Add custom tools from plugins
    available_tools = default_tools + custom_tools
    return available_tools

def generate_chain_of_thoughts_system_prompt(selected_tools):
    global current_collection_name

    # Base prompt
    prompt = """
**Objective:**
Your role is to assist a smaller language model (LLM) in enhancing its reasoning ability by formulating a reasoning plan (using the Chain of Thoughts method) based on the user’s question. You will not provide direct answers to the user’s query. Instead, you will guide the smaller LLM by breaking down the problem into logical steps, outlining a clear thought process to solve it. Additionally, you will help the smaller LLM identify and ignore irrelevant information that does not contribute to solving the problem.
**Instructions:**
1. **Restate the Question:**
Begin by clearly restating or paraphrasing the user’s question to ensure full understanding of the problem. If there is any irrelevant information, acknowledge it and emphasize that it should be disregarded.
2. **Formulate a Reasoning Plan (Chain of Thoughts):**
Break the question down into a series of small, logical reasoning steps. Each step should progress toward a solution but should not solve the problem directly. The goal is to provide a structured outline for the smaller LLM to follow, ensuring it focuses only on relevant details and ignores unnecessary information.
3. **Highlight Key Elements:**
Identify important components or variables of the problem that need to be considered (e.g., numbers, relationships, or conditions). If there is irrelevant information, make it clear and explain why it can be disregarded.
4. **Provide a Step-by-step Reasoning Outline:**
For each part of the problem:
- Present a logical step or consideration.
- Explain why this step is important for solving the problem.
- Encourage further analysis or exploration in each step.
- Point out irrelevant details that should be ignored to avoid distraction.
5. **Avoid Final Conclusions:**
Do not provide a direct answer to the user’s question. Instead, stop at the point where the reasoning plan is fully outlined, allowing the smaller LLM to complete the task using the structured thinking you provided.
6. **Encourage Reflection and Follow-up Questions:**
Conclude the reasoning plan by encouraging the smaller LLM to ask follow-up questions or re-evaluate steps if something seems unclear or if irrelevant information was mistakenly considered.
"""

    # Check if tools are available and dynamically modify the prompt
    if selected_tools:
        tool_names = [tool['function']['name'] for tool in selected_tools]
        tools_instruction = f"""
**Additional Guidance:**
The following tools are available and can be utilized if they are relevant to solving the problem: {', '.join(tool_names)}.
When formulating the reasoning plan, consider whether any of these tools could assist in completing specific steps. If a tool is useful, include guidance on how it might be applied effectively.
"""
        prompt += tools_instruction

        # Add specific guidance for query_vector_database if available
        if "query_vector_database" in tool_names:
            database_instruction = """
Additionally, the tool `query_vector_database` is available for searching through a collection of documents.
If the reasoning plan involves retrieving relevant information from the collection, outline how to frame the query and what information to seek.
"""
            prompt += database_instruction

    prompt += """
---
**Example Format:**
*User Question:*
Oliver picks 44 kiwis on Friday. Then he picks 58 kiwis on Saturday. On Sunday, he picks double the number of kiwis he did on Friday, but five of them were a bit smaller than average. How many kiwis does Oliver have?
*Chain of Thoughts (Reasoning Plan):*
1. **Restate the problem:**
Oliver picks kiwis over three days, and we need to calculate the total number of kiwis he picks by the end of Sunday. The statement about \"five being smaller than average\" does not affect the total and should be ignored.
2. **Identify key elements:**
- Number of kiwis picked on Friday: 44
- Number of kiwis picked on Saturday: 58
- Number of kiwis picked on Sunday: double the amount picked on Friday
- The information about smaller kiwis is irrelevant and can be disregarded.
3. **Step-by-step reasoning:**
- **Step 1:** Start by considering how many kiwis Oliver picks on Friday.
*Why this step?* It is the first number given and forms part of the total.
- **Step 2:** Think about how many kiwis Oliver picks on Saturday. Add this number to the total from Friday.
*Why this step?* Adding the number of kiwis picked on each day brings you closer to the solution.
- **Step 3:** On Sunday, Oliver picks double the number he picked on Friday. Calculate how many that is and add it to the running total.
*Why this step?* Sunday’s kiwi count is based on Friday’s, so calculating this is essential to reach the final count.
- **Step 4:** Ignore the statement about five kiwis being smaller than average. It does not impact the total.
*Why this step?* Focusing only on relevant information ensures that the LLM calculates the correct total.
4. **Encourage further thought:**
Does ignoring irrelevant details like the size of the kiwis affect the total count? What might happen if we misinterpret irrelevant information as important?
"""

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
            response = requests.get(url)
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
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            print(f"Failed to fetch {url}: {e}")
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
            status = "[X]" if tool in selected_tools else "[ ]"
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

def discover_plugins(plugin_folder=None):
    global verbose_mode
    global other_instance_url
    global listening_port
    global user_prompt

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
    if file_path.endswith(".htm") or file_path.endswith(".html"):
        return True
    
    # Check for HTML files without extensions
    try:
        with open(file_path, 'r') as f:
            first_line = next((line.strip() for line in f if line.strip()), None)
            return first_line and (first_line.lower().startswith('<!doctype html>') or first_line.lower().startswith('<html'))
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return False

def is_markdown(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"The file {file_path} does not exist.")
    
    # Automatically consider .md files as Markdown
    if file_path.endswith('.md'):
        return True
    
    # If the file is not .md, but is .txt, proceed with content checking
    if not file_path.endswith('.txt'):
        raise ValueError(f"The file {file_path} is neither .md nor .txt.")

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
            response = ollama.embeddings(
                prompt=text,
                model=self.embedding_model_name
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
    def __init__(self, root_folder, collection_name, chroma_client, embeddings_model):
        self.root_folder = root_folder
        self.collection_name = collection_name
        self.client = chroma_client
        self.model = embeddings_model
        self.collection = self.client.get_or_create_collection(name=self.collection_name)

    def get_text_files(self):
        """
        Recursively find all .txt, .md, .tex files in the root folder.
        Also include HTML files without extensions if they start with <!DOCTYPE html> or <html.
        Ignore empty lines at the beginning of the file and check only the first non-empty line.
        """
        text_files = []
        for root, dirs, files in os.walk(self.root_folder):
            for file in files:
                # Check for files with extension
                if file.endswith(".txt") or file.endswith(".md") or file.endswith(".tex"):
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
        """
        with open(file_path, 'r', encoding='utf-8') as file:
            try:
                return file.read()
            except:
                return None

    def index_documents(self, allow_chunks=True, no_chunking_confirmation=False, split_paragraphs=False, additional_metadata=None):
        """
        Index all text files in the root folder.
        
        :param allow_chunks: Whether to chunk large documents.
        :param no_chunking_confirmation: Skip confirmation for chunking.
        :param split_paragraphs: Whether to split markdown content into paragraphs.
        :param additional_metadata: Optional dictionary to pass additional metadata by file name.
        """
        # Ask the user to confirm if they want to allow chunking of large documents
        if allow_chunks and not no_chunking_confirmation:
            on_print("Large documents will be chunked into smaller pieces for indexing.")
            allow_chunks = on_user_input("Do you want to continue with chunking (if you answer 'no', large documents will be indexed as a whole)? [y/n]: ").lower() in ['y', 'yes']

        if allow_chunks:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

        # Get the list of text files
        text_files = self.get_text_files()

        if allow_chunks:
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

        from tqdm import tqdm
        # Progress bar for indexing
        progress_bar = tqdm(total=len(text_files), desc="Indexing files", unit="file", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}")

        for file_path in text_files:
            progress_bar.update(1)

            try:
                content = self.read_file(file_path)

                if not content:
                    on_print(f"An error occurred while reading file: {file_path}", Fore.RED)
                    continue

                document_id = os.path.splitext(os.path.basename(file_path))[0]
                
                # Add any additional metadata for the file
                file_metadata = {'filename': file_path}
                if additional_metadata and file_path in additional_metadata:
                    file_metadata.update(additional_metadata[file_path])

                if allow_chunks:
                    chunks = []
                    # Split Markdown files into sections if needed
                    if is_html(file_path):
                        # Convert to Markdown before splitting
                        markdown_splitter = MarkdownSplitter(extract_text_from_html(content), split_paragraphs=split_paragraphs)
                        chunks = markdown_splitter.split()
                    elif is_markdown(file_path):
                        markdown_splitter = MarkdownSplitter(content, split_paragraphs=split_paragraphs)
                        chunks = markdown_splitter.split()
                    else:
                        chunks = text_splitter.split_text(content)
                    
                    for i, chunk in enumerate(chunks):
                        chunk_id = f"{document_id}_{i}"
                        
                        # Embed the content
                        embedding = None
                        if self.model:
                            response = ollama.embeddings(
                                prompt=chunk,
                                model=self.model
                            )
                            embedding = response["embedding"]
                        
                        # Upsert the chunk with additional metadata if available
                        if embedding:
                            self.collection.upsert(
                                documents=[chunk],
                                metadatas=[file_metadata],
                                ids=[chunk_id],
                                embeddings=[embedding]
                            )
                        else:
                            self.collection.upsert(
                                documents=[chunk],
                                metadatas=[file_metadata],
                                ids=[chunk_id]
                            )
                else:
                    # Embed the whole document
                    embedding = None
                    if self.model:
                        response = ollama.embeddings(
                            prompt=content,
                            model=self.model
                        )
                        embedding = response["embedding"]

                    # Upsert the document with additional metadata if available
                    if embedding:
                        self.collection.upsert(
                            documents=[content],
                            metadatas=[file_metadata],
                            ids=[document_id],
                            embeddings=[embedding]
                        )
                    else:
                        self.collection.upsert(
                            documents=[content],
                            metadatas=[file_metadata],
                            ids=[document_id]
                        )
            except KeyboardInterrupt:
                break

def web_search(query=None, n_results=5, web_cache_collection=web_cache_collection_name, web_embedding_model="nomic-embed-text", num_ctx=None):
    global current_model
    global verbose_mode
    global plugins

    if not query:
        return ""

    search = DDGS()
    urls = []
    # Add the search results to the chatbot response
    try:
        search_results = search.text(query, max_results=n_results)
        if search_results:
            for i, search_result in enumerate(search_results):
                urls.append(search_result['href'])
    except:
        # TODO: handle retries in case of duckduckgo_search.exceptions.RatelimitException
        pass

    if verbose_mode:
        on_print("Web Search Results:", Fore.WHITE + Style.DIM)
        on_print(urls, Fore.WHITE + Style.DIM)

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

    # Index the articles in the vector database
    document_indexer = DocumentIndexer(temp_folder, web_cache_collection, chroma_client, web_embedding_model)
    document_indexer.index_documents(no_chunking_confirmation=True, additional_metadata=additional_metadata)

    # Remove the temporary folder and its contents
    for file in os.listdir(temp_folder):
        file_path = os.path.join(temp_folder, file)
        os.remove(file_path)
    os.rmdir(temp_folder)

    # Search the vector database for the query
    return query_vector_database(query, collection_name=web_cache_collection, n_results=10, query_embeddings_model=web_embedding_model)

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
    /cb: Replace /cb with the clipboard content.
    /save <filename>: Save the conversation to a file. If no filename is provided, save with a timestamp into current directory.
    /verbose: Toggle verbose mode on or off.
    /memory: Toggle memory assistant on or off.
    /memorize or /remember: Store the current conversation in memory.
    reset, clear, restart: Reset the conversation.
    quit, exit, bye: Exit the chatbot.
    For multiline input, you can wrap text with triple double quotes.
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

def prompt_for_vector_database_collection(prompt_create_new=True):
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
        return on_user_input("Enter a new collection to create: ")

    # Filter out the web_cache_collection_name
    filtered_collections = [collection for collection in collections if collection.name != web_cache_collection_name and collection.name != memory_collection_name]

    if not filtered_collections:
        on_print("No collections found", Fore.RED)
        return on_user_input("Enter a new collection to create: ")

    # Ask user to choose a collection
    on_print("Available collections:", Style.RESET_ALL)
    for i, collection in enumerate(filtered_collections):
        collection_name = collection.name
        on_print(f"{i}. {collection_name}")

    if prompt_create_new:
        # Propose to create a new collection
        on_print(f"{len(filtered_collections)}. Create a new collection")
    
    choice = int(on_user_input("Enter the number of your preferred collection [0]: ") or 0)

    if prompt_create_new and choice == len(filtered_collections):
        return on_user_input("Enter a new collection to create: ")

    return filtered_collections[choice].name

def set_current_collection(collection_name):
    global collection
    global current_collection_name

    load_chroma_client()

    if not collection_name or not chroma_client:
        collection = None
        current_collection_name = None
        return

    # Get the target collection
    try:
        collection = chroma_client.get_or_create_collection(name=collection_name)
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
        on_print(f"Collection {collection_name} deleted.", Fore.WHITE + Style.DIM)
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

def query_vector_database(question, collection_name=current_collection_name, n_results=number_of_documents_to_return_from_vector_db, answer_distance_threshold=0, query_embeddings_model=None, expand_query=True, question_context=None):
    global collection
    global verbose_mode
    global embeddings_model
    global current_model

    # If question is empty, return empty string
    if not question or len(question) == 0:
        return ""

    # If n_results is a string, convert it to an integer
    if isinstance(n_results, str):
        try:
            n_results = int(n_results)
        except:
            n_results = number_of_documents_to_return_from_vector_db

    # If n_results is 0, return empty string
    if n_results == 0:
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
        set_current_collection(collection_name)

    if not collection:
        on_print("No ChromaDB collection loaded.", Fore.RED)
        collection_name = prompt_for_vector_database_collection()
        if not collection_name:
            return ""

    if collection_name and collection_name != current_collection_name:
        set_current_collection(collection_name)

    if expand_query:
        # Expand the query for better retrieval
        system_prompt = "You are an assistant that helps expand and clarify user questions to improve information retrieval. When a user provides a question, your task is to write a short passage that elaborates on the query by adding relevant background information, inferred details, and related concepts that can help with retrieval. The passage should remain concise and focused, without changing the original meaning of the question.\r\nGuidelines:\r\n1. Expand the question briefly by including additional context or background, staying relevant to the user's original intent.\r\n2. Incorporate inferred details or related concepts that help clarify or broaden the query in a way that aids retrieval.\r\n3. Keep the passage short, usually no more than 2-3 sentences, while maintaining clarity and depth.\r\n4. Avoid introducing unrelated or overly specific topics. Keep the expansion concise and to the point."
        if question_context:
            system_prompt += f"\n\nAdditional context about the user query:\n{question_context}"

        response = ask_ollama(system_prompt, question, selected_model=current_model, no_bot_prompt=True, stream_active=False)
        if response:
            question += "\n" + response
            if verbose_mode:
                on_print("Expanded query:", Fore.WHITE + Style.DIM)
                on_print(question, Fore.WHITE + Style.DIM)
    
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
        return ""
    
    if len(result["metadatas"][0]) == 0:
        return ""

    metadatas = result["metadatas"][0]

    # Preprocess and re-rank using BM25
    preprocessed_query = preprocess_text(question)
    preprocessed_docs = [preprocess_text(doc) for doc in documents]

    # Apply BM25 re-ranking
    bm25 = BM25Okapi(preprocessed_docs)
    bm25_scores = bm25.get_scores(preprocessed_query)

    # Get top rerank_n documents based on BM25 score
    reranked_results = sorted(
        enumerate(zip(metadatas, distances, documents, bm25_scores)),
        key=lambda x: x[1][3],  # Sort by BM25 score
        reverse=True
    )[:n_results]

    # Join all possible answers into one string
    answers = []
    answer_index = 0
    for idx, (metadata, distance, document, bm25_score) in reranked_results:
        if answer_distance_threshold > 0 and distance > answer_distance_threshold:
            if verbose_mode:
                on_print("Skipping answer with distance: " + str(distance), Fore.WHITE + Style.DIM)
            continue

        if verbose_mode:
            on_print("Answer distance: " + str(distance), Fore.WHITE + Style.DIM)
        answer_index += 1
        
        # Format the answer with the title, content, and URL
        title = metadata.get("title", "")
        url = metadata.get("url", "")
        filePath = metadata.get("filePath", "")

        formatted_answer = document

        if title:
            formatted_answer = title + "\n" + formatted_answer
        if url:
            formatted_answer += "\nURL: " + url
        if filePath:
            formatted_answer += "\nFile Path: " + filePath

        answers.append(formatted_answer.strip())

    return '\n\n'.join(answers)

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
        return "", False, completion_done

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

                # if parameters is a string, convert it to a dictionary
                if isinstance(parameters, str):
                    try:
                        parameters = json.loads(parameters)
                    except:
                        parameters = {}

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
        bot_response = ask_ollama_with_conversation(conversation, model, temperature, prompt_template, tools=[], no_bot_prompt=True, stream_active=stream_active, num_ctx=num_ctx)
    else:
        on_print(f"Tools not found", Fore.RED)
        return None
    
    return bot_response

def ask_ollama_with_conversation(conversation, model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True, prompt="Bot", prompt_color=None, num_ctx=None):
    global no_system_role
    global syntax_highlighting
    global interactive_mode
    global verbose_mode
    global plugins
    global alternate_model
    global use_openai

    # Some models do not support the "system" role, merge the system message with the first user message
    if no_system_role and len(conversation) > 1 and conversation[0]["role"] == "system" and not conversation[0]["content"] is None and not conversation[1]["content"] is None:
        conversation[1]["content"] = conversation[0]["content"] + "\n" + conversation[1]["content"]
        conversation = conversation[1:]

    if use_openai:
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

    if use_openai:
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
    bot_response_is_tool_calls = False
    ollama_options = {"temperature": temperature}
    if num_ctx:
        ollama_options["num_ctx"] = num_ctx

    try:
        stream = ollama.chat(
            model=model,
            messages=conversation,
            # If tools are selected, deactivate the stream to get the full response (Ollama API limitation)
            stream=False if len(tools) > 0 else stream_active,
            options=ollama_options,
            tools=tools
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

                    delta = chunk['message'].get('content', '')

                    if len(bot_response) == 0:
                        delta = delta.strip()

                        if len(delta) == 0:
                            continue

                    bot_response += delta
                    
                    if syntax_highlighting and interactive_mode:
                        print_spinning_wheel(chunk_count)
                    else:
                        on_llm_token_response(delta)
                        on_stdout_flush()
                on_llm_token_response("\n")
                on_stdout_flush()
            else:
                tool_calls = stream['message'].get('tool_calls', [])

                if len(tool_calls) > 0:
                    conversation.append(stream['message'])

                    if verbose_mode:
                        on_print(f"Tool calls: {tool_calls}", Fore.WHITE + Style.DIM)
                    bot_response = tool_calls
                    bot_response_is_tool_calls = True
                else:
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

    if not bot_response is None:
        return bot_response.strip()
    else:
        return None

def ask_ollama(system_prompt, user_input, selected_model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True, num_ctx=None):
    conversation = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
    return ask_ollama_with_conversation(conversation, selected_model, temperature, prompt_template, tools, no_bot_prompt, stream_active, num_ctx=num_ctx)

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

def try_parse_json(json_str):
    """Helper function to attempt JSON parsing and return the result if successful."""
    result = None

    if not json_str or not isinstance(json_str, str):
        return result

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        pass

    return result

def extract_json(garbage_str):
    global verbose_mode
    # First, try to parse the entire input as JSON directly
    result = try_parse_json(garbage_str)
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
        result = try_parse_json(json_str)
        if result is not None:
            return result
        else:
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
    
            if "gemma" in selected_model:
                no_system_role=True
                on_print("The selected model does not support the 'system' role. Merging the system message with the first user message.")

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
    
    # Remove non-chat models from the list
    models = [model for model in models if model.id.startswith("gpt-")]

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

    if "gemma" in selected_model:
        no_system_role=True
        on_print("The selected model does not support the 'system' role. Merging the system message with the first user message.")

    if verbose_mode:
        on_print(f"Selected model: {selected_model}", Fore.WHITE + Style.DIM)
    return selected_model

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
    with open(file_path, 'w', encoding="utf8") as f:
        # Convert conversation list of objects to a list of dict
        conversation = [json.loads(json.dumps(obj, default=lambda o: vars(o))) for obj in conversation]

        # Skip empty messages or system messages
        filtered_conversation = [entry for entry in conversation if "content" in entry and entry["content"] and "role" in entry and entry["role"] != "system" and entry["role"] != "tool"]

        for message in filtered_conversation:
            role = message["role"]

            if role == "user":
                role = "Me"
            elif role == "assistant":
                role = "Assistant"
            
            f.write(f"{role}: {message['content']}\n\n")

    on_print(f"Conversation saved to {file_path}", Fore.WHITE + Style.DIM)

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

def run():
    global current_collection_name
    global memory_collection_name
    global long_term_memory_file
    global collection
    global chroma_client
    global openai_client
    global use_openai
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
    
    default_model = None
    prompt_template = None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")  # Enable tab completion

    # If specified as script named arguments, use the provided ChromaDB client host (--chroma-host) and port (--chroma-port)
    parser = argparse.ArgumentParser(description='Run the Ollama chatbot.')
    parser.add_argument('--chroma-path', type=str, help='ChromaDB database path', default=None)
    parser.add_argument('--chroma-host', type=str, help='ChromaDB client host', default="localhost")
    parser.add_argument('--chroma-port', type=int, help='ChromaDB client port', default=8000)
    parser.add_argument('--collection', type=str, help='ChromaDB collection name', default=None)
    parser.add_argument('--use-openai', type=bool, help='Use OpenAI API or Llama-CPP', default=False, action=argparse.BooleanOptionalAction)
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
    parser.add_argument('--conversations-folder', type=str, help='Folder to save conversations to', default=None)
    parser.add_argument('--auto-save', type=bool, help='Automatically save conversations to a file at the end of the chat', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--syntax-highlighting', type=bool, help='Use syntax highlighting', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--index-documents', type=str, help='Root folder to index text files', default=None)
    parser.add_argument('--interactive', type=bool, help='Use interactive mode', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--plugins-folder', type=str, default=None, help='Path to the plugins folder')
    parser.add_argument('--stream', type=bool, help='Use stream mode for Ollama API', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--output', type=str, help='Output file path', default=None)
    parser.add_argument('--other-instance-url', type=str, help=f"URL of another {__name__} instance to connect to", default=None)
    parser.add_argument('--listening-port', type=int, help=f"Listening port for the current {__name__} instance", default=8000)
    parser.add_argument('--user-name', type=str, help='User name', default=None)
    parser.add_argument('--anonymous', type=bool, help='Do not use the user name from the environment variables', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--memory', type=str, help='Use memory manager for context management', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--context-window', type=int, help='Ollama context window size, if not specified, the default value is used, which is 2048 tokens', default=None) 
    parser.add_argument('--auto-start', type=bool, help="Start the conversation automatically", default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--tools', type=str, help="List of tools to activate and use in the conversation, separated by commas", default=None)
    parser.add_argument('--memory-collection-name', type=str, help="Name of the memory collection to use for context management", default=memory_collection_name)
    parser.add_argument('--long-term-memory-file', type=str, help="Long-term memory file name", default=long_term_memory_file)
    args = parser.parse_args()

    preferred_collection_name = args.collection
    use_openai = args.use_openai
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
    today = f"Today's date is {date.today().strftime('%A, %B %d, %Y')}"

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

    plugins = discover_plugins(plugins_folder)

    if verbose_mode:
        on_print(f"Verbose mode: {verbose_mode}", Fore.WHITE + Style.DIM)

    # Load additional chatbots from a JSON file
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

    if args.index_documents:
        load_chroma_client()
        document_indexer = DocumentIndexer(args.index_documents, current_collection_name, chroma_client, embeddings_model)
        document_indexer.index_documents()

    auto_start_conversation = ("starts_conversation" in chatbot and chatbot["starts_conversation"]) or auto_start_conversation
    system_prompt = chatbot["system_prompt"]
    use_openai = use_openai or (hasattr(chatbot, 'use_openai') and getattr(chatbot, 'use_openai'))
    if "preferred_model" in chatbot:
        default_model = chatbot["preferred_model"]
    if preferred_model:
        default_model = preferred_model

    if not use_openai:
        # If default model does not contain ":", append ":latest" to the model name
        if ":" not in default_model:
            default_model += ":latest"

        selected_model = select_ollama_model_if_available(default_model)
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
    set_current_collection(current_collection_name)

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

    while True:
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

        if "/index" in user_input:
            if not chroma_client:
                on_print("ChromaDB client not initialized.", Fore.RED)
                continue

            load_chroma_client()

            if not current_collection_name:
                on_print("No ChromaDB collection loaded.", Fore.RED)
                set_current_collection(prompt_for_vector_database_collection())

            folder_to_index = user_input.split("/index")[1].strip()
            temp_folder = None
            if folder_to_index.startswith("http"):
                base_url = folder_to_index
                temp_folder = tempfile.mkdtemp()
                scraper = SimpleWebScraper(base_url, output_dir=temp_folder, file_types=["html", "htm"], restrict_to_base=True, convert_to_markdown=True, verbose=verbose_mode)
                scraper.scrape()
                folder_to_index = temp_folder

            document_indexer = DocumentIndexer(folder_to_index, current_collection_name, chroma_client, embeddings_model)
            document_indexer.index_documents()

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

            enhanced_input = ask_ollama(chain_of_thoughts_system_prompt, formatted_conversation, selected_model, temperature, prompt_template, no_bot_prompt=True, stream_active=False, num_ctx=num_ctx)
            if enhanced_input:
                user_input = "Question: " + user_input + "\n\n" + enhanced_input
                if verbose_mode:
                    on_print(f"Enhanced input: {user_input}", Fore.WHITE + Style.DIM)

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
            web_search_response = web_search(user_input, num_ctx=num_ctx)
            if web_search_response:
                initial_user_input = user_input
                user_input += "Context: " + web_search_response
                user_input += "\n\nQuestion: " + initial_user_input
                user_input += "\nAnswer the question as truthfully as possible using the provided web search results, and if the answer is not contained within the text below, say 'I don't know'.\n"
                user_input += "Cite some useful links from the search results to support your answer."

                if verbose_mode:
                    on_print(user_input, Fore.WHITE + Style.DIM)

        if user_input == "/model":
            selected_model = prompt_for_model(default_model, current_model)
            current_model = selected_model

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
            alternate_model = prompt_for_model(default_model, current_model)
            continue

        if user_input == "/tools":
            selected_tools = select_tools(get_available_tools(), selected_tools)
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

        if user_input == "/collection":
            collection_name = prompt_for_vector_database_collection()
            set_current_collection(collection_name)
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
                collection_name = prompt_for_vector_database_collection(prompt_create_new=False)

            if not collection_name:
                continue

            delete_collection(collection_name)
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
            file_path = user_input.split("/file")[1].strip()
            file_path = file_path.strip("'\"")
            
            # Check if the file is an image
            _, ext = os.path.splitext(file_path)
            if ext.lower() not in [".png", ".jpg", ".jpeg", ".bmp"]:
                try:
                    with open(file_path, 'r', encoding='utf-8') as file:
                        user_input = user_input.replace("/file", "")
                        user_input += "\n" + file.read()
                except FileNotFoundError:
                    on_print("File not found. Please try again.", Fore.RED)
                    continue
            else:
                user_input = user_input.split("/file")[0].strip()
                image_path = file_path

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
            elif not use_openai and len(selected_tools) > 0:
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
            with open(output_file, 'a', encoding='utf-8') as f:
                f.write(bot_response)
                if verbose_mode:
                    on_print(f"Response saved to {output_file}", Fore.WHITE + Style.DIM)

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
    
    if auto_save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if conversations_folder:
            save_conversation_to_file(conversation, os.path.join(conversations_folder, f"conversation_{timestamp}.txt"))
        else:
            save_conversation_to_file(conversation, f"conversation_{timestamp}.txt")

if __name__ == "__main__":
    run()
