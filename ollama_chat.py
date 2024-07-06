# pip install ollama colorama chromadb pygments duckduckgo_search sentence-transformers pyperclip langchain-text-splitters

# On Windows platform:
# pip install pywin32

import ollama
import platform
from colorama import Fore, Style
import chromadb

if platform.system() == "Windows":
    import win32clipboard
else:
    import pyperclip

import argparse
import re
import os
import sys
import json
import datetime
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import Terminal256Formatter
from duckduckgo_search import DDGS

use_openai = False
no_system_role=False
openai_client = None
chroma_client = None
current_collection_name = None
collection = None
number_of_documents_to_return_from_vector_db = 1
temperature = 0
verbose_mode = False
embeddings_model = None
syntax_highlighting = True
interactive_mode = True

# Default ChromaDB client host and port
chroma_client_host = "localhost"
chroma_client_port = 8000

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

    def index_documents(self):
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        """
        Index all text files in the root folder.
        """
        text_files = self.get_text_files()
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

        for file_path in text_files:
            try:
                content = self.read_file(file_path)

                if not content:
                    print(Fore.RED + f"An error occurred while reading file: {file_path}")
                    continue

                document_id = os.path.splitext(os.path.basename(file_path))[0]
                
                # Split the content using langchain text splitter
                chunks = text_splitter.split_text(content)
                
                for i, chunk in enumerate(chunks):
                    chunk_id = f"{document_id}_{i}"
                    
                    # Embed the content
                    embedding = None

                    if self.model:
                        embedding = self.model.encode(chunk).tolist()
                    
                    # Add the content to the collection
                    if embedding:
                        self.collection.upsert(
                            documents=[chunk],
                            metadatas=[{'filename': file_path}],
                            ids=[chunk_id],
                            embeddings=[embedding]
                        )
                    else:
                        self.collection.upsert(
                            documents=[chunk],
                            metadatas=[{'filename': file_path}],
                            ids=[chunk_id]
                        )
                    print(Fore.WHITE + Style.DIM + f"Added chunk {chunk_id} to the collection")
            except KeyboardInterrupt:
                break

def web_search(query, n_results=10):
    search = DDGS()

    # Perform a chatbot search to get the answer
    result = search.chat(query)

    # Add the search results to the chatbot response
    search_results = search.text(query, max_results=n_results)
    if search_results:
        result += "\n\nSearch results:\n"
        for i, search_result in enumerate(search_results):
            result += f"{i+1}. {search_result['title']}\n{search_result['body']}\n{search_result['href']}\n\n"

    return result

def print_spinning_wheel(print_char_index):
    # use turning block character as spinner
    spinner =  ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    sys.stdout.write(Style.RESET_ALL + '\rBot: ' + spinner[print_char_index % len(spinner)])
    sys.stdout.flush()

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
    /chatbot: Change the chatbot personality.
    /collection: Change the vector database collection.
    /index <folder path>: Index text files in the folder to the vector database.
    /cb: Replace /cb with the clipboard content.
    /save <filename>: Save the conversation to a file. If no filename is provided, save with a timestamp into current directory.
    /verbose: Toggle verbose mode on or off.
    reset, clear, restart: Reset the conversation.
    quit, exit, bye: Exit the chatbot.
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
            print(Fore.RED + f"Additional chatbots file not found: {json_file}")
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

    print(Style.RESET_ALL + "Available chatbots:")
    for i, chatbot in enumerate(chatbots):
        print(f"{i}. {chatbot['name']} - {chatbot['description']}")
    
    choice = int(input("Enter the number of your preferred chatbot [0]: ") or 0)

    return chatbots[choice]

def prompt_for_vector_database_collection():
    global chroma_client

    load_chroma_client()

    # List existing collections
    collections = None
    if chroma_client:
        collections = chroma_client.list_collections()
    else:
        print(Fore.RED + "ChromaDB is not running.")

    if not collections:
        print(Fore.RED + "No collections found")
        return input("Enter a new collection to create: ")

    # Ask user to choose a collection
    print(Style.RESET_ALL + "Available collections:")
    for i, collection in enumerate(collections):
        collection_name = collection.name
        print(f"{i}. {collection_name}")
    
    choice = int(input("Enter the number of your preferred collection [0]: ") or 0)

    return collections[choice].name

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
        print(Fore.WHITE + Style.DIM + f"Collection {collection_name} loaded.")
        current_collection_name = collection_name
    except:
        raise Exception(f"Collection {collection_name} not found")

def query_vector_database(question, n_results, collection_name=current_collection_name, answer_distance_threshold=0):
    global collection
    global verbose_mode
    global embeddings_model

    if not collection:
        print(Fore.RED + "No ChromaDB collection loaded.")
        collection_name = prompt_for_vector_database_collection()
        if not collection_name:
            return ""

    if collection_name and collection_name != current_collection_name:
        set_current_collection(collection_name)
    
    if embeddings_model is None:
        result = collection.query(
            query_texts=[question],
            n_results=n_results
        )
    else:
        result = collection.query(
            query_embeddings=[embeddings_model.encode(question).tolist()],
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
                print(Fore.WHITE + Style.DIM + "Skipping answer with distance: " + str(answer_distance))
            continue
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

def ask_openai_with_conversation(conversation, selected_model="gpt-3.5-turbo", temperature=0.1, prompt_template=None):
    global openai_client
    global verbose_mode

    if prompt_template and verbose_mode:
        print(Fore.WHITE + Style.DIM + "Using OpenAI API with prompt template: " + prompt_template)

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

    completion = openai_client.chat.completions.create(
        messages=conversation,
        model=selected_model,
        stream=False,
        temperature=temperature
    )

    bot_response = completion.choices[0].message.content
    return bot_response.strip()

def ask_ollama_with_conversation(conversation, selected_model, temperature=0.1, prompt_template=None):
    global no_system_role
    global syntax_highlighting
    global interactive_mode

    # Some models do not support the "system" role, merge the system message with the first user message
    if no_system_role and len(conversation) > 1 and conversation[0]["role"] == "system":
        conversation[1]["content"] = conversation[0]["content"] + "\n" + conversation[1]["content"]
        conversation = conversation[1:]

    if use_openai:
        return ask_openai_with_conversation(conversation, selected_model, temperature, prompt_template)

    if not syntax_highlighting:
        if (interactive_mode):
            sys.stdout.write(Style.RESET_ALL + "Bot: ")
        else:
            sys.stdout.write(Style.RESET_ALL)
        sys.stdout.flush()

    stream = ollama.chat(
        model=selected_model,
        messages=conversation,
        stream=True,
        options={"temperature": temperature}
    )

    bot_response = ""
    chunk_count = 0

    try:
        for chunk in stream:
            chunk_count += 1
            delta = chunk['message']['content']
            bot_response += delta
            
            if syntax_highlighting and interactive_mode:
                print_spinning_wheel(chunk_count)
            else:
                sys.stdout.write(delta)
                sys.stdout.flush()
    except KeyboardInterrupt:
        stream.close()

    return bot_response.strip()

def ask_ollama(system_prompt, user_input, selected_model, temperature=0.1, prompt_template=None):
    conversation = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
    return ask_ollama_with_conversation(conversation, selected_model, temperature, prompt_template)

def bytes_to_gibibytes(bytes):
    gigabytes = bytes / (1024 ** 3)
    return f"{gigabytes:.1f} GB"

def select_ollama_model_if_available(model_name):
    global no_system_role
    global verbose_mode

    models = ollama.list()["models"]
    for model in models:
        if model["name"] == model_name:
            selected_model = model
    
            if "gemma" in selected_model:
                no_system_role=True
                print("The selected model does not support the 'system' role. Merging the system message with the first user message.")

            if verbose_mode:
                print(Fore.WHITE + Style.DIM + f"Selected model: {model_name}")
            return model_name
        
    print(Fore.RED + f"Model {model_name} not found.")
    return None

def prompt_for_ollama_model(default_model):
    global no_system_role
    global verbose_mode

    # List existing ollama models
    models = ollama.list()["models"]

    # Ask user to choose a model
    print(Style.RESET_ALL + "Available models:")
    for i, model in enumerate(models):
        print(f"{i}. {model['name']} ({bytes_to_gibibytes(model['size'])})")
    
    # if stable-code:instruct is available, suggest it as the default model
    default_choice_index = None
    for i, model in enumerate(models):
        if model['name'] == default_model:
            default_choice_index = i
            break

    if default_choice_index is None:
        default_choice_index = 0

    choice = int(input("Enter the number of your preferred model [" + str(default_choice_index) + "]: ") or default_choice_index)

    # Use the chosen model
    selected_model = models[choice]['name']

    if "gemma" in selected_model:
        no_system_role=True
        print("The selected model does not support the 'system' role. Merging the system message with the first user message.")

    if verbose_mode:
        print(Fore.WHITE + Style.DIM + f"Selected model: {selected_model}")
    return selected_model

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
    with open(file_path, 'w') as f:
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

    print(Fore.WHITE + Style.DIM + f"Conversation saved to {file_path}")

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
            print(Fore.RED + Style.DIM + "ChromaDB client could not be initialized. Please check the host and port.")
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

    prompt_template = None

    # If specified as script named arguments, use the provided ChromaDB client host (--chroma-host) and port (--chroma-port)
    parser = argparse.ArgumentParser(description='Run the Ollama chatbot.')
    parser.add_argument('--chroma-host', type=str, help='ChromaDB client host', default="localhost")
    parser.add_argument('--chroma-port', type=int, help='ChromaDB client port', default=8000)
    parser.add_argument('--collection', type=str, help='ChromaDB collection name', default=None)
    parser.add_argument('--use-openai', type=bool, help='Use OpenAI API or Llama-CPP', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--temperature', type=float, help='Temperature for OpenAI API', default=0)
    parser.add_argument('--disable-system-role', type=bool, help='Specify if the selected model does not support the system role, like Google Gemma models', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--prompt-template', type=str, help='Prompt template to use for Llama-CPP', default=None)
    parser.add_argument('--additional-chatbots', type=str, help='Path to a JSON file containing additional chatbots', default=None)
    parser.add_argument('--verbose', type=bool, help='Enable verbose mode', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--embeddings-model', type=str, help='Sentence embeddings model to use for vector database queries', default=None)
    parser.add_argument('--system-prompt', type=str, help='System prompt message', default=None)
    parser.add_argument('--model', type=str, help='Preferred Ollama model', default="phi3:mini")
    parser.add_argument('--conversations-folder', type=str, help='Folder to save conversations to', default=None)
    parser.add_argument('--auto-save', type=bool, help='Automatically save conversations to a file at the end of the chat', default=False, action=argparse.BooleanOptionalAction)
    parser.add_argument('--syntax-highlighting', type=bool, help='Use syntax highlighting', default=True, action=argparse.BooleanOptionalAction)
    parser.add_argument('--index-documents', type=str, help='Root folder to index text files', default=None)
    parser.add_argument('--interactive', type=bool, help='Use interactive mode', default=True, action=argparse.BooleanOptionalAction)
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

    if verbose_mode:
        print(Fore.WHITE + Style.DIM + f"Verbose mode: {verbose_mode}")

    if args.embeddings_model:
        try:
            from sentence_transformers import SentenceTransformer
            embeddings_model = SentenceTransformer(args.embeddings_model)

            if verbose_mode:
                print(Fore.WHITE + Style.DIM + f"Using sentence embeddings model: {args.embeddings_model}")
        except:
            print(Fore.RED + "Sentence Transformers library not found. Please install it using 'pip install sentence-transformers'.")
            pass

    # Load additional chatbots from a JSON file
    load_additional_chatbots(additional_chatbots_file)

    if args.index_documents:
        load_chroma_client()
        document_indexer = DocumentIndexer(args.index_documents, current_collection_name, chroma_client, embeddings_model)
        document_indexer.index_documents()

    if not use_openai:
        # Load the default chatbot
        chatbot = chatbots[0]
        system_prompt = chatbot["system_prompt"]
        default_model = chatbot["preferred_model"]

        if preferred_model:
            default_model = preferred_model

            # If default model does not contain ":", append ":latest" to the model name
            if ":" not in default_model:
                default_model += ":latest"

        selected_model = select_ollama_model_if_available(default_model)
        if selected_model is None:
            selected_model = prompt_for_ollama_model(default_model)
    else:
        from openai import OpenAI
        openai_client = OpenAI(
            base_url="http://127.0.0.1:8080",
            api_key="none"
        )
        selected_model = "gpt-3.5-turbo"

        if no_system_role:
            print(Fore.WHITE + Style.DIM + "The selected model does not support the 'system' role.")
            system_prompt = ""
        else:
            system_prompt = "You are a helpful chatbot assistant. Possible chatbot prompt commands: " + print_possible_prompt_commands()

    user_name = get_personal_info()["user_name"]

    # Set the current collection
    set_current_collection(current_collection_name)

    # Initial system message
    if initial_system_prompt:
        if verbose_mode:
            print(Fore.WHITE + Style.DIM + "Initial system prompt: " + initial_system_prompt)
        system_prompt = initial_system_prompt

    if not no_system_role and len(user_name) > 0:
        system_prompt += f"\nYou are talking with {user_name}"

    if len(system_prompt) > 0:
        initial_message = {"role": "system", "content": system_prompt}
        conversation = [initial_message]
    else:
        initial_message = None
        conversation = []
    
    while True:

        try:
            if (interactive_mode):
                sys.stdout.write(Fore.YELLOW + Style.NORMAL + "\nYou: ")
            user_input = input()
        except EOFError:
            break

        if len(user_input) == 0:
            continue
        
        # Exit condition
        if user_input.lower() in ['/quit', '/exit', '/bye', 'quit', 'exit', 'bye']:
            print(Style.RESET_ALL + "Goodbye!")
            break

        if user_input.lower() in ['/reset', '/clear', '/restart', 'reset', 'clear', 'restart']:
            print(Style.RESET_ALL + "Conversation reset.")
            if initial_message:
                conversation = [initial_message]
            else:
                conversation = []
            continue

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
                    print(Fore.RED + "File not found. Please try again.")
                    continue
            else:
                user_input = user_input.split("/file")[0].strip()
                image_path = file_path

        if "/index" in user_input:
            if not chroma_client:
                print(Fore.RED + "ChromaDB client not initialized.")
                continue

            load_chroma_client()

            if not current_collection_name:
                print(Fore.RED + "No ChromaDB collection loaded.")
                set_current_collection(prompt_for_vector_database_collection())

            document_indexer = DocumentIndexer(user_input.split("/index")[1].strip(), current_collection_name, chroma_client, embeddings_model)
            document_indexer.index_documents()
            continue

        if "/verbose" in user_input:
            verbose_mode = not verbose_mode
            print(Fore.WHITE + Style.DIM + f"Verbose mode: {verbose_mode}")
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
                    print(Fore.WHITE + Style.DIM + user_input)
        elif "/web" in user_input:
            user_input = user_input.replace("/web", "").strip()
            web_search_response = web_search(user_input)
            if web_search_response:
                initial_user_input = user_input
                user_input = "Question: " + initial_user_input + "\n"
                user_input += "Answer: " + web_search_response
                user_input += "\n\nAnswer the question as truthfully as possible using the provided web search results, and if the answer is not contained within the text below, say 'I don't know'.\n"
                user_input += "Cite some useful links from the search results to support your answer."

                if verbose_mode:
                    print(Fore.WHITE + Style.DIM + user_input)

        if "/model" in user_input:
            selected_model = prompt_for_ollama_model(default_model)
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

        if "/chatbot" in user_input:
            chatbot = prompt_for_chatbot()
            system_prompt = chatbot["system_prompt"]
            # Initial system message
            if len(user_name) > 0:
                system_prompt += f"\nYou are talking with {user_name}"

            if len(system_prompt) > 0:
                initial_message = {"role": "system", "content": system_prompt}
                conversation = [initial_message]
            else:
                conversation = []
            print(Style.RESET_ALL + "Conversation reset.")
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
            print(Fore.WHITE + Style.DIM + "Clipboard content added to user input.")

        # Add user input to conversation history
        if image_path:
            conversation.append({"role": "user", "content": user_input, "images": [image_path]})
        else:
            conversation.append({"role": "user", "content": user_input})

        # Generate response
        bot_response = ask_ollama_with_conversation(conversation, selected_model, temperature=temperature, prompt_template=prompt_template)
        
        if syntax_highlighting:
            if (interactive_mode):
                print(Style.RESET_ALL + '\rBot: ' + colorize(bot_response))
            else:
                print(Style.RESET_ALL + colorize(bot_response))

        # Add bot response to conversation history
        conversation.append({"role": "assistant", "content": bot_response})

    if auto_save:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if conversations_folder:
            save_conversation_to_file(conversation, os.path.join(conversations_folder, f"conversation_{timestamp}.txt"))
        else:
            save_conversation_to_file(conversation, f"conversation_{timestamp}.txt")

if __name__ == "__main__":
    run()
