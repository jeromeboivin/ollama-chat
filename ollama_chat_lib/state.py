"""Mutable runtime state for ollama-chat.

Every module-level variable that is mutated at runtime via ``global X``
statements lives here, so it can be shared cleanly across sub-modules
without circular imports or namespace issues.

Modules that need to **read** or **write** state should::

    from ollama_chat_lib import state

    # read
    if state.verbose_mode: ...

    # write
    state.verbose_mode = True
"""

# ── Provider / backend flags ──────────────────────────────────────────────
use_openai = False
use_azure_openai = False
no_system_role = False
openai_client = None

# ── ChromaDB ──────────────────────────────────────────────────────────────
chroma_client = None
current_collection_name = None
collection = None
chroma_client_host = "localhost"
chroma_client_port = 8000
chroma_db_path = None

# ── Model selection ───────────────────────────────────────────────────────
current_model = None
alternate_model = None
thinking_model = None
thinking_model_reasoning_pattern = None
embeddings_model = None

# ── Conversation / generation settings ────────────────────────────────────
temperature = 0.1
number_of_documents_to_return_from_vector_db = 8
think_mode_on = False

# ── UI / output ───────────────────────────────────────────────────────────
verbose_mode = False
syntax_highlighting = True
interactive_mode = True

# ── Plugins & tools ───────────────────────────────────────────────────────
plugins = []
plugins_folder = None
selected_tools = []          # Initially no tools selected
custom_tools = []

# ── Memory ────────────────────────────────────────────────────────────────
memory_manager = None
memory_collection_name = "memory"
long_term_memory_file = "long_term_memory.json"

# ── Networking / multi-instance ───────────────────────────────────────────
other_instance_url = None
listening_port = None
initial_message = None
user_prompt = None

# ── Session bookkeeping ──────────────────────────────────────────────────
session_created_files = []   # Track files created during the session
prompt_template = None
chatbots = []                # Loaded at startup, mutated by load_additional_chatbots()
