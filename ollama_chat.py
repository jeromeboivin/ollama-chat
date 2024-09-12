import ollama
import platform
import tempfile
from colorama import Fore, Style
import chromadb

if platform.system() == "Windows":
    import win32clipboard
else:
    import pyperclip
    import readline

import argparse
import re
import os
import sys
import json
import datetime
import importlib.util
import inspect
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import Terminal256Formatter
from duckduckgo_search import DDGS
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter
import requests
from PyPDF2 import PdfReader
import chardet

use_openai = False
no_system_role=False
openai_client = None
chroma_client = None
current_collection_name = None
collection = None
number_of_documents_to_return_from_vector_db = 20
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

# Default ChromaDB client host and port
chroma_client_host = "localhost"
chroma_client_port = 8000

custom_tools = []
web_cache_collection_name = "web_cache"

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
                        "description": "The question to search for"
                    }
                },
                "required": [
                    "question"
                ]
            }
        }
    }]

    # Add custom tools from plugins
    available_tools = default_tools + custom_tools
    return available_tools

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
    def __init__(self, urls, llm_enabled=False, system_prompt='', selected_model='', temperature=0.1, verbose=False, plugins=[]):
        self.urls = urls
        self.articles = []
        self.llm_enabled = llm_enabled
        self.system_prompt = system_prompt
        self.selected_model = selected_model
        self.temperature = temperature
        self.verbose = verbose
        self.plugins = plugins

    def fetch_page(self, url):
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise an exception for HTTP errors
            return response.content  # Return raw bytes instead of text for PDF support
        except requests.exceptions.RequestException as e:
            if self.verbose:
                on_print(f"Error fetching URL {url}: {e}", Fore.RED)
            return None

    def md(self, soup, **options):
        return MarkdownConverter(**options).convert_soup(soup)

    def extract_text_from_html(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove all <script> tags
        for script in soup.find_all('script'):
            script.decompose()

        # Convert the modified HTML content to Markdown
        text = self.md(soup, strip=['a', 'img'], heading_style='ATX', 
                       escape_asterisks=False, escape_underscores=False, 
                       autolinks=False)
        
        # Remove extra newlines
        text = re.sub(r'\n+', '\n', text)

        return text

    def extract_text_from_pdf(self, pdf_content):
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
                          stream_active=self.verbose)

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
                    extracted_text = self.extract_text_from_pdf(content)
                else:
                    if self.verbose:
                        on_print(f"Extracting text from HTML: {url}", Fore.WHITE + Style.DIM)
                    decoded_content = self.decode_content(content)
                    extracted_text = self.extract_text_from_html(decoded_content)

                article = {'url': url, 'text': extracted_text}
                
                if self.llm_enabled and task:
                    if self.verbose:
                        on_print(Fore.WHITE + Style.DIM + f"Using LLM to process the content. Task: {task}")
                    llm_result = self.ask_llm(content=extracted_text, user_input=task)
                    article['llm_result'] = llm_result

                self.articles.append(article)

    def get_articles(self):
        return self.articles

def select_tools(available_tools, selected_tools):
    def display_tool_options():
        on_print("Available tools:\n", Style.RESET_ALL)
        for i, tool in enumerate(available_tools):
            tool_name = tool['function']['name']
            status = "[X]" if tool in selected_tools else "[ ]"
            on_stdout_write(f"{i + 1}. {status} {tool_name}: {tool['function']['description']}\n")
        on_stdout_flush()

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

def discover_plugins(plugin_folder=None):
    global verbose_mode

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
                if inspect.isclass(obj):
                    if verbose_mode:
                        on_print(f"Discovered class: {name}", Fore.WHITE + Style.DIM)

                    plugin = obj()
                    if hasattr(obj, 'set_web_crawler') and callable(getattr(obj, 'set_web_crawler')):
                        plugin.set_web_crawler(SimpleWebCrawler)
                    plugins.append(plugin)
                    if verbose_mode:
                        on_print(f"Discovered plugin: {name}", Fore.WHITE + Style.DIM)
                    if hasattr(obj, 'get_tool_definition') and callable(getattr(obj, 'get_tool_definition')):
                        custom_tools.append(obj().get_tool_definition())
                        if verbose_mode:
                            on_print(f"Discovered tool: {name}", Fore.WHITE + Style.DIM)
    return plugins

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

class DocumentIndexer:
    def __init__(self, root_folder, collection_name, chroma_client, embeddings_model):
        self.root_folder = root_folder
        self.collection_name = collection_name
        self.client = chroma_client
        self.model = embeddings_model
        self.collection = self.client.get_or_create_collection(name=self.collection_name)

    def get_text_files(self):
        """
        Recursively find all .txt and .md files in the root folder.
        """
        text_files = []
        for root, dirs, files in os.walk(self.root_folder):
            for file in files:
                if file.endswith(".txt") or file.endswith(".md") or file.endswith(".tex"):
                    text_files.append(os.path.join(root, file))
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

        for file_path in text_files:
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
                    if is_markdown(file_path):
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
                        on_print(f"Added chunk {chunk_id} to the collection", Fore.WHITE + Style.DIM)
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
                    on_print(f"Added document {document_id} to the collection", Fore.WHITE + Style.DIM)
            except KeyboardInterrupt:
                break

def web_search(query=None, n_results=3, web_cache_collection=web_cache_collection_name, web_embedding_model="nomic-embed-text"):
    global current_model
    global verbose_mode
    global plugins

    if not query:
        return ""
    
    # Ask Ollama to write a short passage about the query in order to expand the context
    # This can be useful for web search queries
    if verbose_mode:
        on_print("Expanding query using Ollama...", Fore.WHITE + Style.DIM)
    expanded_query = ask_ollama("", f"Write a short passage about '{query}' in no more than 1 paragraph.", selected_model=current_model, no_bot_prompt=True, stream_active=False)
    if verbose_mode:
        on_print("Expanded query:", Fore.WHITE + Style.DIM)
        on_print(expanded_query, Fore.WHITE + Style.DIM)
    
    # Try to search the vector database first
    set_current_collection(web_cache_collection)
    search_results = query_vector_database(expanded_query, n_results=10, collection_name=web_cache_collection, answer_distance_threshold=150, query_embeddings_model=web_embedding_model)
    if search_results:
        return search_results

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

    webCrawler = SimpleWebCrawler(urls, llm_enabled=True, system_prompt="You are a web crawler assistant.", selected_model=current_model, temperature=0.1, verbose=verbose_mode, plugins=plugins)
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
    print(additional_metadata)
    document_indexer.index_documents(no_chunking_confirmation=True, additional_metadata=additional_metadata)

    # Remove the temporary folder and its contents
    for file in os.listdir(temp_folder):
        file_path = os.path.join(temp_folder, file)
        os.remove(file_path)
    os.rmdir(temp_folder)

    # Search the vector database for the query
    return query_vector_database(expanded_query, n_results=20, collection_name=web_cache_collection, query_embeddings_model=web_embedding_model)

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
    output = highlight(input_text, lexer, formatter)

    return output

def print_possible_prompt_commands():
    possible_prompt_commands = """
    Possible prompt commands:
    /file <path of a file to load>: Read the file and append the content to user input.
    /search <number of results>: Query the vector database and append the answer to user input (RAG system).
    /web: Perform a web search using DuckDuckGo.
    /model: Change the Ollama model.
    /tools: Prompts the user to select or deselect tools from the available tools list.
    /chatbot: Change the chatbot personality.
    /collection: Change the vector database collection.
    /rmcollection <collection name>: Delete the vector database collection.
    /index <folder path>: Index text files in the folder to the vector database.
    /cb: Replace /cb with the clipboard content.
    /save <filename>: Save the conversation to a file. If no filename is provided, save with a timestamp into current directory.
    /verbose: Toggle verbose mode on or off.
    reset, clear, restart: Reset the conversation.
    quit, exit, bye: Exit the chatbot.
    For multiline input, you can wrap text with triple double quotes.
    """
    return possible_prompt_commands.strip()

# Predefined chatbots personalities
chatbots = [
    {
        "name": "basic",
        "preferred_model": "",
        "description": "Basic chatbot",
        "system_prompt": "You are a helpful chatbot assistant. Possible chatbot prompt commands: " + print_possible_prompt_commands()
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
    filtered_collections = [collection for collection in collections if collection.name != web_cache_collection_name]

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


def query_vector_database(question, n_results=number_of_documents_to_return_from_vector_db, collection_name=current_collection_name, answer_distance_threshold=0, query_embeddings_model=None):
    global collection
    global verbose_mode
    global embeddings_model

    if not query_embeddings_model:
        query_embeddings_model = embeddings_model

    if not collection:
        on_print("No ChromaDB collection loaded.", Fore.RED)
        collection_name = prompt_for_vector_database_collection()
        if not collection_name:
            return ""

    if collection_name and collection_name != current_collection_name:
        set_current_collection(collection_name)
    
    if query_embeddings_model is None:
        result = collection.query(
            query_texts=[question],
            n_results=n_results
        )
    else:
        # generate an embedding for the question and retrieve the most relevant doc
        response = ollama.embeddings(
            prompt=question,
            model=query_embeddings_model
        )
        result = collection.query(
            query_embeddings=[response["embedding"]],
            n_results=n_results
        )

    documents = result["documents"][0]
    distances = result["distances"][0]

    if len(result["metadatas"]) == 0:
        return ""
    
    if len(result["metadatas"][0]) == 0:
        return ""

    metadatas = result["metadatas"][0]

    # Join all possible answers into one string
    answers = []
    answer_index = 0
    for metadata, answer_distance, document in zip(metadatas, distances, documents):
        if answer_distance_threshold > 0 and answer_distance > answer_distance_threshold:
            if verbose_mode:
                on_print("Skipping answer with distance: " + str(answer_distance), Fore.WHITE + Style.DIM)
            continue

        if verbose_mode:
            on_print("Answer distance: " + str(answer_distance), Fore.WHITE + Style.DIM)
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

    # Reverse the order of the answers, so the most relevant answer is at the end
    answers.reverse()

    return '\n\n'.join(answers)

def ask_openai_with_conversation(conversation, selected_model=None, temperature=0.1, prompt_template=None, stream_active=True, tools=[]):
    global openai_client
    global verbose_mode

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

    if len(tools) > 0:
        stream_active = False
    else:
        tools = None

    completion_done = False
    completion = openai_client.chat.completions.create(
        messages=conversation,
        model=selected_model,
        stream=stream_active,
        temperature=temperature,
        tools=tools
    )

    bot_response_is_tool_calls = False
    tool_calls = []

    if verbose_mode:
        on_print("OpenAI Chat Completion:", Fore.WHITE + Style.DIM)
        on_print(completion, Fore.WHITE + Style.DIM)

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
            on_print(bot_response, Fore.WHITE + Style.DIM)

            # Check if the completion is done based on the finish reason
            if completion.choices[0].finish_reason == 'stop' or completion.choices[0].finish_reason == 'function_call' or completion.choices[0].finish_reason == 'content_filter' or completion.choices[0].finish_reason == 'tool_calls':
                completion_done = True
        else:
            bot_response = ""
            try:
                for chunk in completion:
                    delta = chunk.choices[0].delta.content

                    if not delta is None:
                        on_llm_token_response(delta, Style.RESET_ALL)
                        on_stdout_flush()
                        bot_response += delta
                    
                    # Check if the completion is done based on the finish reason
                    if chunk.choices[0].finish_reason == 'stop' or chunk.choices[0].finish_reason == 'function_call' or chunk.choices[0].finish_reason == 'content_filter' or chunk.choices[0].finish_reason == 'tool_calls':
                        completion_done = True
                        break
            except KeyboardInterrupt:
                completion.close()
            except Exception as e:
                on_print(f"Error during streaming completion: {e}", Fore.RED)
                bot_response = ""
                bot_response_is_tool_calls = False

    if not completion_done and not bot_response_is_tool_calls:
        conversation.append({"role": "assistant", "content": bot_response})

    return bot_response, bot_response_is_tool_calls, completion_done

def handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools):
    # Iterate over each function call in the bot response
    tool_found = False
    for tool_call in bot_response:
        if not 'function' in tool_call or not 'name' in tool_call['function']:
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
                                on_print(f"Calling tool function: {tool_name} from plugin: {plugin.__class__.__name__}", Fore.WHITE + Style.DIM)

                            try:
                                # Call the plugin's tool function with parameters
                                tool_response = getattr(plugin, tool_name)(**parameters)
                                if verbose_mode:
                                    on_print(f"Tool response: {tool_response}", Fore.WHITE + Style.DIM)
                                break
                            except Exception as e:
                                on_print(f"Error calling tool function: {tool_name} - {e}", Fore.RED + Style.NORMAL)

                if tool_response:
                    # If the tool response is a string, append it to the conversation
                    tool_role = "tool"
                    tool_call_id = tool_call.get('id', 0)

                    if not model_support_tools:
                        tool_role = "user"
                    if isinstance(tool_response, str):
                        if not model_support_tools:
                            tool_response += "\n" + find_latest_user_message(conversation)
                        conversation.append({"role": tool_role, "content": tool_response, "tool_call_id": tool_call_id})
                    else:
                        # Convert the tool response to a string
                        tool_response_str = json.dumps(tool_response, indent=4)
                        if not model_support_tools:
                            tool_response_str += "\n" + find_latest_user_message(conversation)
                        conversation.append({"role": tool_role, "content": tool_response_str, "tool_call_id": tool_call_id})
    if tool_found:
        bot_response = ask_ollama_with_conversation(conversation, model, temperature, prompt_template, tools=[], no_bot_prompt=True)
    else:
        on_print(f"Tools not found", Fore.RED)
        return None
    
    return bot_response

def ask_ollama_with_conversation(conversation, model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True, prompt="Bot", prompt_color=None):
    global no_system_role
    global syntax_highlighting
    global interactive_mode
    global verbose_mode
    global plugins
    global alternate_model
    global use_openai

    # Some models do not support the "system" role, merge the system message with the first user message
    if no_system_role and len(conversation) > 1 and conversation[0]["role"] == "system":
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

                bot_response = handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools)

                # Consider completion done
                completion_done = True

        return bot_response.strip()

    # If tools are selected, deactivate the stream to get the full response
    if len(tools) > 0:
        stream_active = False

    bot_response = ""
    bot_response_is_tool_calls = False

    try:
        stream = ollama.chat(
            model=model,
            messages=conversation,
            stream=stream_active,
            options={"temperature": temperature},
            tools=tools
        )
    except ollama.ResponseError as e:
        if "does not support tools" in str(e):
            tool_response = generate_tool_response(find_latest_user_message(conversation), tools, model, temperature, prompt_template)
            
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
            if stream_active:
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

    if bot_response and bot_response_is_tool_calls:
        bot_response = handle_tool_response(bot_response, model_support_tools, conversation, model, temperature, prompt_template, tools)

    return bot_response.strip()

def ask_ollama(system_prompt, user_input, selected_model, temperature=0.1, prompt_template=None, tools=[], no_bot_prompt=False, stream_active=True):
    conversation = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
    return ask_ollama_with_conversation(conversation, selected_model, temperature, prompt_template, tools, no_bot_prompt, stream_active)

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

def generate_tool_response(user_input, tools, selected_model, temperature=0.1, prompt_template=None):
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
    tool_response = ask_ollama(system_prompt, user_input, selected_model, temperature, prompt_template, no_bot_prompt=True, stream_active=False)

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
        if model["name"] == model_name:
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

def prompt_for_openai_model(default_model):
    global verbose_mode
    global openai_client

    # List available OpenAI models
    try:
        models = openai_client.models.list().data
    except Exception as e:
        on_print(f"Failed to fetch OpenAI models: {str(e)}", Fore.RED)
        return None
    
    # Remove non-chat models from the list
    models = [model for model in models if model.id.startswith("gpt-")]

    # Display available models
    on_print("Available OpenAI models:\n", Style.RESET_ALL)
    for i, model in enumerate(models):
        star = " *" if model.id == default_model else ""
        on_stdout_write(f"{i}. {model.id}{star}\n")
    on_stdout_flush()

    # Default choice index for default_model
    default_choice_index = None
    for i, model in enumerate(models):
        if model.id == default_model:
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

def prompt_for_ollama_model(default_model):
    global no_system_role
    global verbose_mode

    # List existing ollama models
    try:
        models = ollama.list()["models"]
    except:
        on_print("Ollama API is not running.", Fore.RED)
        return None

    # Ask user to choose a model
    on_print("Available models:\n", Style.RESET_ALL)
    for i, model in enumerate(models):
        star = " *" if model['name'] == default_model else ""
        on_stdout_write(f"{i}. {model['name']} ({bytes_to_gibibytes(model['size'])}){star}\n")
    on_stdout_flush()
    
    # if stable-code:instruct is available, suggest it as the default model
    default_choice_index = None
    for i, model in enumerate(models):
        if model['name'] == default_model:
            default_choice_index = i
            break

    if default_choice_index is None:
        default_choice_index = 0

    choice = int(on_user_input("Enter the number of your preferred model [" + str(default_choice_index) + "]: ") or default_choice_index)

    # Use the chosen model
    selected_model = models[choice]['name']

    if "gemma" in selected_model:
        no_system_role=True
        on_print("The selected model does not support the 'system' role. Merging the system message with the first user message.")

    if verbose_mode:
        on_print(f"Selected model: {selected_model}", Fore.WHITE + Style.DIM)
    return selected_model

def prompt_for_model(default_model):
    global use_openai

    if use_openai:
        return prompt_for_openai_model(default_model)
    else:
        return prompt_for_ollama_model(default_model)

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

        for message in conversation:
            # Skip empty messages or system messages
            if not message["content"] or message["role"] == "system":
                continue

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

    if chroma_client:
        return

    # Initialize the ChromaDB client
    try:
        chroma_client = chromadb.HttpClient(host=chroma_client_host, port=chroma_client_port)
    except:
        if verbose_mode:
            on_print("ChromaDB client could not be initialized. Please check the host and port.", Fore.RED + Style.DIM)
        chroma_client = None

def run():
    global current_collection_name
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
    global plugins
    global plugins_folder
    global selected_tools
    global current_model
    global alternate_model

    prompt_template = None

    # If specified as script named arguments, use the provided ChromaDB client host (--chroma-host) and port (--chroma-port)
    parser = argparse.ArgumentParser(description='Run the Ollama chatbot.')
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
    args = parser.parse_args()

    preferred_collection_name = args.collection
    use_openai = args.use_openai
    chroma_client_host = args.chroma_host
    chroma_client_port = args.chroma_port
    temperature = args.temperature
    no_system_role = bool(args.disable_system_role)
    current_collection_name = preferred_collection_name
    prompt_template = args.prompt_template
    additional_chatbots_file = args.additional_chatbots
    verbose_mode = args.verbose
    initial_system_prompt = args.system_prompt
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
        for bot in chatbots:
            if bot["name"] == args.chatbot:
                chatbot = bot
        if verbose_mode:
            on_print(f"Using chatbot: {chatbot['name']}", Fore.WHITE + Style.DIM)
    
    if chatbot is None:
        # Load the default chatbot
        chatbot = chatbots[0]

    if args.index_documents:
        load_chroma_client()
        document_indexer = DocumentIndexer(args.index_documents, current_collection_name, chroma_client, embeddings_model)
        document_indexer.index_documents()

    system_prompt = chatbot["system_prompt"]
    use_openai = use_openai or (hasattr(chatbot, 'use_openai') and getattr(chatbot, 'use_openai'))
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
        selected_model = prompt_for_model(default_model)
        if selected_model is None:
            return

    if not system_prompt:
        if no_system_role:
            on_print("The selected model does not support the 'system' role.", Fore.WHITE + Style.DIM)
            system_prompt = ""
        else:
            system_prompt = "You are a helpful chatbot assistant. Possible chatbot prompt commands: " + print_possible_prompt_commands()

    user_name = get_personal_info()["user_name"]

    # Set the current collection
    set_current_collection(current_collection_name)

    # Initial system message
    if initial_system_prompt:
        if verbose_mode:
            on_print("Initial system prompt: " + initial_system_prompt, Fore.WHITE + Style.DIM)
        system_prompt = initial_system_prompt

    if not no_system_role and len(user_name) > 0:
        first_name = user_name.split()[0]
        system_prompt += f"\nThe user's name is {user_name}. Address him as {first_name} when necessary."

    if len(system_prompt) > 0:
        if verbose_mode:
            on_print("System prompt: " + system_prompt, Fore.WHITE + Style.DIM)
        initial_message = {"role": "system", "content": system_prompt}
        conversation = [initial_message]
    else:
        initial_message = None
        conversation = []

    current_model = selected_model

    answer_and_exit = False
    if not interactive_mode and user_prompt:
        answer_and_exit = True
    
    while True:
        try:
            if interactive_mode:
                on_prompt("\nYou: ", Fore.YELLOW + Style.NORMAL)

            if user_prompt:
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
        if user_input.lower() in ['/quit', '/exit', '/bye', 'quit', 'exit', 'bye']:
            on_print("Goodbye!", Style.RESET_ALL)
            break

        if user_input.lower() in ['/reset', '/clear', '/restart', 'reset', 'clear', 'restart']:
            on_print("Conversation reset.", Style.RESET_ALL)
            if initial_message:
                conversation = [initial_message]
            else:
                conversation = []
            continue

        for plugin in plugins:
            if hasattr(plugin, "on_user_input_done") and callable(getattr(plugin, "on_user_input_done")):
                user_input_from_plugin = plugin.on_user_input_done(user_input, verbose_mode=verbose_mode)
                if user_input_from_plugin:
                    user_input = user_input_from_plugin

        if "/index" in user_input:
            if not chroma_client:
                on_print("ChromaDB client not initialized.", Fore.RED)
                continue

            load_chroma_client()

            if not current_collection_name:
                on_print("No ChromaDB collection loaded.", Fore.RED)
                set_current_collection(prompt_for_vector_database_collection())

            document_indexer = DocumentIndexer(user_input.split("/index")[1].strip(), current_collection_name, chroma_client, embeddings_model)
            document_indexer.index_documents()
            continue

        if "/verbose" in user_input:
            verbose_mode = not verbose_mode
            on_print(f"Verbose mode: {verbose_mode}", Fore.WHITE + Style.DIM)
            continue

        if "/search" in user_input:
            # If /search is followed by a number, use that number as the number of documents to return (/search can be anywhere in the prompt)
            if re.search(r'/search\s+\d+', user_input):
                n_docs_to_return = int(re.search(r'/search\s+(\d+)', user_input).group(1))
                user_input = user_input.replace(f"/search {n_docs_to_return}", "").strip()
            else:
                user_input = user_input.replace("/search", "").strip()
                n_docs_to_return = number_of_documents_to_return_from_vector_db

            answer_from_vector_db = query_vector_database(user_input, n_docs_to_return, collection_name=current_collection_name)
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
            web_search_response = web_search(user_input)
            if web_search_response:
                initial_user_input = user_input
                user_input += "Context: " + web_search_response
                user_input += "\n\nQuestion: " + initial_user_input
                user_input += "\nAnswer the question as truthfully as possible using the provided web search results, and if the answer is not contained within the text below, say 'I don't know'.\n"
                user_input += "Cite some useful links from the search results to support your answer."

                if verbose_mode:
                    on_print(user_input, Fore.WHITE + Style.DIM)

        if user_input == "/model":
            selected_model = prompt_for_model(default_model)
            current_model = selected_model
            continue

        if user_input == "/model2":
            alternate_model = prompt_for_model(default_model)
            continue

        if "/tools" in user_input:
            selected_tools = select_tools(get_available_tools(), selected_tools)
            continue

        if "/save" in user_input:
            # If the user input contains /save and followed by a filename, save the conversation to that file
            if re.search(r'/save\s+\S+', user_input):
                file_path = re.search(r'/save\s+(\S+)', user_input).group(1)

                if conversations_folder:
                    file_path = os.path.join(conversations_folder, file_path)

                save_conversation_to_file(conversation, file_path)
            else:
                # Save the conversation to a file, use current timestamp as the filename
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

                if conversations_folder:
                    save_conversation_to_file(conversation, os.path.join(conversations_folder, f"conversation_{timestamp}.txt"))
                else:
                    save_conversation_to_file(conversation, f"conversation_{timestamp}.txt")
            continue

        if "/collection" in user_input:
            collection_name = prompt_for_vector_database_collection()
            set_current_collection(collection_name)
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

        if "/chatbot" in user_input:
            chatbot = prompt_for_chatbot()
            system_prompt = chatbot["system_prompt"]
            # Initial system message
            if len(user_name) > 0:
                first_name = user_name.split()[0]
                system_prompt += f"\nThe user's name is {user_name}. Address him as {first_name} when necessary."

            if len(system_prompt) > 0:
                initial_message = {"role": "system", "content": system_prompt}
                conversation = [initial_message]
            else:
                conversation = []
            on_print("Conversation reset.", Style.RESET_ALL)
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
                    with open(file_path, 'r') as file:
                        user_input = user_input.replace("/file", "")
                        user_input += "\n" + file.read()
                except FileNotFoundError:
                    on_print("File not found. Please try again.", Fore.RED)
                    continue
            else:
                user_input = user_input.split("/file")[0].strip()
                image_path = file_path

        # Add user input to conversation history
        if image_path:
            conversation.append({"role": "user", "content": user_input, "images": [image_path]})
        else:
            conversation.append({"role": "user", "content": user_input})

        # Generate response
        bot_response = ask_ollama_with_conversation(conversation, selected_model, temperature=temperature, prompt_template=prompt_template, tools=selected_tools, stream_active=stream_active)

        alternate_bot_response = None
        if alternate_model:
            alternate_bot_response = ask_ollama_with_conversation(conversation, alternate_model, temperature=temperature, prompt_template=prompt_template, tools=selected_tools, prompt="\nAlt", prompt_color=Fore.CYAN, stream_active=stream_active)
        
        bot_response_handled_by_plugin = False
        for plugin in plugins:
            if hasattr(plugin, "on_llm_response") and callable(getattr(plugin, "on_llm_response")):
                plugin_response = getattr(plugin, "on_llm_response")(bot_response)
                bot_response_handled_by_plugin = bot_response_handled_by_plugin or plugin_response

        if not bot_response_handled_by_plugin and syntax_highlighting:
            on_print(colorize(bot_response), Style.RESET_ALL, "\rBot: " if interactive_mode else "")
            
            if alternate_bot_response:
                on_print(colorize(alternate_bot_response), Fore.CYAN, "\rAlt: " if interactive_mode else "")


        if alternate_bot_response:
            # Ask user to select the preferred response
            on_print(f"Select the preferred response:\n1. Original model ({current_model})\n2. Alternate model ({alternate_model})", Fore.WHITE + Style.DIM)
            choice = on_user_input("Enter the number of your preferred response [1]: ") or "1"
            bot_response = bot_response if choice == "1" else alternate_bot_response

        # Add bot response to conversation history
        conversation.append({"role": "assistant", "content": bot_response})

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(bot_response)
                if verbose_mode:
                    on_print(f"Response saved to {output_file}", Fore.WHITE + Style.DIM)

        if answer_and_exit:
            break

    # Stop plugins, calling on_exit if available
    for plugin in plugins:
        if hasattr(plugin, "on_exit") and callable(getattr(plugin, "on_exit")):
            getattr(plugin, "on_exit")()
    
    if auto_save:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if conversations_folder:
            save_conversation_to_file(conversation, os.path.join(conversations_folder, f"conversation_{timestamp}.txt"))
        else:
            save_conversation_to_file(conversation, f"conversation_{timestamp}.txt")

if __name__ == "__main__":
    run()
