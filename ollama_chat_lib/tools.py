"""Tool definitions, selection helpers, chain-of-thought prompt, and web search."""

import os
import re
import tempfile

from colorama import Fore, Style
from ddgs import DDGS

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print, on_user_input
from ollama_chat_lib.terminal_ui import prompt_for_multiple_choice
from ollama_chat_lib.constants import (
    web_cache_collection_name,
    min_quality_results_threshold,
    min_average_bm25_threshold,
)


# ---------------------------------------------------------------------------
# get_available_tools
# ---------------------------------------------------------------------------

def get_available_tools(load_chroma_client_fn):
    """Build the list of available tool definitions.

    *load_chroma_client_fn* – callable that ensures the ChromaDB client is ready.
    """
    load_chroma_client_fn()

    available_collections = []
    available_collections_description = []
    if state.chroma_client:
        collections = state.chroma_client.list_collections()
        for state.collection in collections:
            if state.collection.name == web_cache_collection_name or state.collection.name == state.memory_collection_name:
                continue
            available_collections.append(state.collection.name)
            if type(state.collection.metadata) == dict and "description" in state.collection.metadata:
                available_collections_description.append(f"'{state.collection.name}': {state.collection.metadata['description']}")

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
                        "default": state.current_collection_name,
                        "enum": available_collections
                    },
                    "question_context": {
                        "type": "string",
                        "description": "Current discussion context or topic, based on previous exchanges with the user"
                    },
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
    },
    {
        'type': 'function',
        'function': {
            'name': 'edit_file',
            'description': 'Edit a file by replacing a specific string with a new string. Uses exact string matching with unique-match enforcement and post-edit syntax checking.',
            'parameters': {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to edit (relative to workspace root)"
                    },
                    "old_str": {
                        "type": "string",
                        "description": "The exact string to replace (must match uniquely unless replace_all=true)"
                    },
                    "new_str": {
                        "type": "string",
                        "description": "The replacement string"
                    },
                    "expect_unique": {
                        "type": "boolean",
                        "description": "If true, fail if old_str doesn't match exactly once",
                        "default": True
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "If true, replace all occurrences of old_str",
                        "default": False
                    }
                },
                "required": ["path", "old_str", "new_str"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'apply_patch',
            'description': 'Apply a unified diff patch to a file for larger multi-hunk changes.',
            'parameters': {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to patch (relative to workspace root)"
                    },
                    "unified_diff": {
                        "type": "string",
                        "description": "The unified diff format patch to apply"
                    }
                },
                "required": ["path", "unified_diff"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'list_directory',
            'description': 'List directory contents with optional recursive traversal and gitignore support.',
            'parameters': {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (relative to workspace root)",
                        "default": "."
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Whether to list recursively",
                        "default": False
                    },
                    "respect_gitignore": {
                        "type": "boolean",
                        "description": "Whether to respect .gitignore patterns",
                        "default": True
                    }
                },
                "required": []
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'glob_files',
            'description': 'Find files matching a glob pattern.',
            'parameters': {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.rs')"
                    },
                    "root": {
                        "type": "string",
                        "description": "Root directory (relative to workspace root, default: workspace root)"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results",
                        "default": 100
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'search_code',
            'description': 'Search code using ripgrep (if available) or Python regex fallback.',
            'parameters': {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern (regex or literal string)"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search (relative to workspace root)"
                    },
                    "regex": {
                        "type": "boolean",
                        "description": "Whether pattern is a regex",
                        "default": True
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results",
                        "default": 200
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Optional file glob pattern to filter (e.g., '*.py')"
                    }
                },
                "required": ["pattern"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'todo_write',
            'description': 'Write/replace the entire todo list for task planning.',
            'parameters': {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "List of todo items. Each item should have: content (required), status (optional: pending/in_progress/completed/blocked/failed), id (optional, auto-generated)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "blocked", "failed"]},
                                "id": {"type": "string"}
                            },
                            "required": ["content"]
                        }
                    }
                },
                "required": ["items"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'todo_read',
            'description': 'Read the current todo list.',
            'parameters': {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'todo_update',
            'description': 'Update a todo item by ID.',
            'parameters': {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "string",
                        "description": "ID of the todo to update"
                    },
                    "status": {
                        "type": "string",
                        "description": "New status (pending, in_progress, completed, blocked, failed)",
                        "enum": ["pending", "in_progress", "completed", "blocked", "failed"]
                    },
                    "content": {
                        "type": "string",
                        "description": "New content"
                    },
                    "result": {
                        "type": "string",
                        "description": "Result of completion"
                    },
                    "error": {
                        "type": "string",
                        "description": "Error message if failed"
                    }
                },
                "required": ["todo_id"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'delegate_coding_task',
            'description': 'Delegate a coding task to a worker sub-agent. Returns structured result (not a transcript). Worker has full editing/execution tools but no delegation tools.',
            'parameters': {
                "type": "object",
                "properties": {
                    "task_description": {
                        "type": "string",
                        "description": "Description of the coding task to delegate"
                    },
                    "target_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific file(s)/path(s) the worker should focus on (limits blast radius)"
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context for the worker (e.g., relevant code snippets, error messages, requirements)"
                    },
                    "model": {
                        "type": "string",
                        "description": "Model to use for the worker (defaults to configured worker model)"
                    }
                },
                "required": ["task_description", "target_paths"]
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'delegate_code_review',
            'description': 'Delegate a code review to a read-only reviewer sub-agent. Returns structured findings list with approval status.',
            'parameters': {
                "type": "object",
                "properties": {
                    "target_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File(s)/path(s) to review"
                    },
                    "review_focus": {
                        "type": "string",
                        "description": "Specific focus for the review (e.g., 'security', 'performance', 'correctness', 'style')"
                    },
                    "model": {
                        "type": "string",
                        "description": "Model to use for the reviewer (defaults to configured review model)"
                    }
                },
                "required": ["target_paths"]
            }
        }
    }]

    # Find index of instantiate_agent_with_tools_and_process_task function
    index = -1
    for i, tool in enumerate(default_tools):
        if tool['function']['name'] == 'instantiate_agent_with_tools_and_process_task':
            index = i
            break

    default_tools[index]["function"]["parameters"]["properties"]["tools"]["items"]["enum"] = [tool["function"]["name"] for tool in state.selected_tools]
    default_tools[index]["function"]["parameters"]["properties"]["tools"]["description"] += f" Available tools: {', '.join([tool['function']['name'] for tool in state.selected_tools])}"

    # Find index of create_new_agent_with_tools function
    index = -1
    for i, tool in enumerate(default_tools):
        if tool['function']['name'] == 'create_new_agent_with_tools':
            index = i
            break

    default_tools[index]["function"]["parameters"]["properties"]["tools"]["items"]["enum"] = [tool["function"]["name"] for tool in state.selected_tools]
    default_tools[index]["function"]["parameters"]["properties"]["tools"]["description"] += f" Available tools: {', '.join([tool['function']['name'] for tool in state.selected_tools])}"

    # Add custom tools from plugins
    available_tools = default_tools + state.custom_tools
    return available_tools


# ---------------------------------------------------------------------------
# generate_chain_of_thoughts_system_prompt
# ---------------------------------------------------------------------------

def generate_chain_of_thoughts_system_prompt(selected_tools):
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
     - "How would my reasoning change if this assumption didn't hold?"  
   - Explore contradictions, extreme cases, or absurd scenarios to sharpen your understanding.

### Process for Inner Monologue:  

1. **Define Key Elements**:  
   - **Key Assumptions**: Identify what you're implicitly accepting as true and question whether those assumptions are valid.  
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
   - "Let's imagine an extreme case—how would the reasoning hold up?"  

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
     - "What's missing that could make this more complete?"  

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
    - "Am I sure this holds true? What if I'm wrong?"  
    - "If I assume the opposite, does this still make sense?"  

- **Step 4: Compare and Reflect**  
  - Weigh multiple perspectives or scenarios.  
  - Reflect aloud: "On the one hand, this suggests… But on the other hand, it could mean…"  

- **Step 5: Refine and Iterate**  
  - Summarize your thought process so far.  
  - Ask: "Does this feel complete? If not, where could I dig deeper?"  

### Example Inner Monologue Prompts to Model:  

1. **Speculative Thinking**:  
   - "Let's imagine this were true—what would follow logically? And if it weren't true, what would happen instead?"  

2. **Challenging Assumptions**:  
   - "Am I just assuming X is true without good reason? What happens if X isn't true at all?"  

3. **Exploring Contexts**:  
   - "How would someone from a completely different background think about this? What would change if the circumstances were entirely different?"  

4. **Summarizing and Questioning**:  
   - "So far, I've explored this angle… but does that fully address the problem? What haven't I considered yet?"  

### Notes for the Inner Monologue:

- **Slow Down**: Make your inner thought process deliberate and explicit.  
- **Expand the Scope**: Continuously look for hidden assumptions, missing details, and broader connections.  
- **Challenge the Obvious**: Use contradictions, absurdities, and alternative interpretations to refine your thinking.  
- **Be Curious**: Approach each question as an opportunity to deeply explore the problem space.  
- **Avoid Final Answers**: The goal is to simulate thoughtful reasoning, not to conclude definitively.  

By structuring your reasoning as an inner dialogue, you will create a rich, exploratory process that models curiosity, critical thinking, and creativity.
"""

    if selected_tools:
        tool_names = [tool['function']['name'] for tool in selected_tools]
        tools_instruction = f"""
- The following tools are available and can be utilized if they are relevant to solving the problem: {', '.join(tool_names)}.
- When formulating the reasoning plan, consider whether any of these tools could assist in completing specific steps. If a tool is useful, include guidance on how it might be applied effectively.
"""
        prompt += tools_instruction

        if "query_vector_database" in tool_names:
            database_instruction = """
- Additionally, the tool `query_vector_database` is available for searching through a collection of documents.
- If the reasoning plan involves retrieving relevant information from the collection, outline how to frame the query and what information to seek.
"""
            prompt += database_instruction

    return prompt


# ---------------------------------------------------------------------------
# select_tools / select_tool_by_name / get_builtin_tool_names / requires_plugins
# ---------------------------------------------------------------------------

def select_tools(available_tools, selected_tools):
    if not available_tools:
        on_print("No tools available.", Fore.YELLOW)
        return selected_tools

    builtin_tools = set(get_builtin_tool_names())
    options = []
    for tool in available_tools:
        tool_name = tool['function']['name']
        options.append({
            "value": tool,
            "key": tool_name,
            "label": tool_name,
            "description": tool['function']['description'],
            "group": "Built-in tools" if tool_name in builtin_tools else "Plugin tools",
        })

    return prompt_for_multiple_choice(
        "Choose tools. Type to filter, press Tab to browse, Enter to toggle, and press Enter on an empty prompt when done.",
        options,
        selected_values=selected_tools,
        prompt_label="tools",
        read_fn=on_user_input,
        print_fn=on_print,
    )


def select_tool_by_name(available_tools, selected_tools, target_tool_name):
    for tool in available_tools:
        if tool['function']['name'].lower() == target_tool_name.lower():
            if tool not in selected_tools:
                selected_tools.append(tool)
                if state.verbose_mode:
                    on_print(f"Tool '{target_tool_name}' selected.\n")
            else:
                on_print(f"Tool '{target_tool_name}' is already selected.\n")
            return selected_tools
    on_print(f"Tool '{target_tool_name}' not found.\n")
    return selected_tools


def get_builtin_tool_names():
    return [
        'web_search',
        'query_vector_database',
        'retrieve_relevant_memory',
        'instantiate_agent_with_tools_and_process_task',
        'create_new_agent_with_tools',
        'summarize_text_file',
        # Coding agent tools
        'read_file',
        'create_file',
        'delete_file',
        'run_command',
        'edit_file',
        'apply_patch',
        'list_directory',
        'glob_files',
        'search_code',
        'todo_write',
        'todo_read',
        'todo_update',
        'delegate_coding_task',
        'delegate_code_review',
    ]


def get_orchestrator_tool_names():
    """Tools available to the coding orchestrator (planner/delegator)."""
    return [
        'read_file',
        'list_directory',
        'glob_files',
        'search_code',
        'todo_write',
        'todo_read',
        'todo_update',
        'delegate_coding_task',
        'delegate_code_review',
        'query_vector_database',
        'retrieve_relevant_memory',
        'web_search',
    ]


def get_coding_worker_tool_names():
    """Tools available to coding worker sub-agents (implementers)."""
    return [
        'read_file',
        'create_file',
        'delete_file',
        'edit_file',
        'apply_patch',
        'run_command',
        'list_directory',
        'glob_files',
        'search_code',
        'query_vector_database',
        'retrieve_relevant_memory',
        'web_search',
    ]


def get_review_tool_names():
    """Tools available to code review sub-agents (read-only)."""
    return [
        'read_file',
        'list_directory',
        'glob_files',
        'search_code',
        'run_command',  # Restricted to test/lint commands via system prompt
        'query_vector_database',
        'retrieve_relevant_memory',
        'web_search',
    ]


def requires_plugins(requested_tool_names):
    if not requested_tool_names:
        return False
    builtin_tools = get_builtin_tool_names()
    for tool_name in requested_tool_names:
        tool_name = tool_name.strip().strip('\'').strip('\"')
        if tool_name and tool_name not in builtin_tools:
            return True
    return False


# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------

def web_search(query=None, n_results=5, region="wt-wt", web_embedding_model=None, num_ctx=None, return_intermediate=False,
               *, ask_fn=None, query_vector_database_fn=None, web_crawler_cls=None, document_indexer_cls=None,
               load_chroma_client_fn=None):
    """Perform a web search via DuckDuckGo, index results, and query the vector DB.

    Injected dependencies (keyword-only):
        *ask_fn* – LLM call (ask_ollama signature)
        *query_vector_database_fn* – vector DB query function
        *web_crawler_cls* – SimpleWebCrawler class
        *document_indexer_cls* – DocumentIndexer class
        *load_chroma_client_fn* – callable to init chroma
    """
    if web_embedding_model is None:
        web_embedding_model = state.embeddings_model

    web_cache_collection = web_cache_collection_name or "web_cache"

    if not query:
        if return_intermediate:
            return "", {}
        return ""

    load_chroma_client_fn()

    if not state.chroma_client:
        error_msg = "Web search requires ChromaDB to be running. Please start ChromaDB server or configure a persistent database path."
        if return_intermediate:
            return error_msg, {}
        return error_msg

    if web_embedding_model is None or web_embedding_model == "":
        web_embedding_model = state.embeddings_model

    # OPTIMIZATION: Check cache first
    cache_check_results = ""
    cache_metadata = {}
    skip_web_crawl = False

    try:
        cache_check_results, cache_metadata = query_vector_database_fn(
            query,
            collection_name=web_cache_collection,
            n_results=n_results * 2,
            query_embeddings_model=web_embedding_model,
            use_adaptive_filtering=True,
            return_metadata=True,
            expand_query=False
        )

        if cache_metadata and 'num_results' in cache_metadata:
            num_quality_results = cache_metadata['num_results']
            avg_bm25 = cache_metadata.get('avg_bm25_score', 0.0)
            avg_hybrid = cache_metadata.get('avg_hybrid_score', 0.0)

            quality_check = (
                num_quality_results >= min_quality_results_threshold and
                avg_bm25 >= min_average_bm25_threshold
            )

            if quality_check:
                skip_web_crawl = True
                if state.verbose_mode:
                    on_print(f"Cache hit: Found {num_quality_results} quality results (avg BM25: {avg_bm25:.4f}, avg hybrid: {avg_hybrid:.4f}). Skipping web crawl.", Fore.GREEN + Style.DIM)
            else:
                if state.verbose_mode:
                    reason = []
                    if num_quality_results < min_quality_results_threshold:
                        reason.append(f"only {num_quality_results}/{min_quality_results_threshold} results")
                    if avg_bm25 < min_average_bm25_threshold:
                        reason.append(f"low BM25 {avg_bm25:.4f} < {min_average_bm25_threshold}")
                    on_print(f"Cache insufficient: {', '.join(reason)}. Performing web crawl.", Fore.YELLOW + Style.DIM)

    except Exception as e:
        if state.verbose_mode:
            on_print(f"Cache check failed: {str(e)}. Proceeding with web crawl.", Fore.YELLOW + Style.DIM)
        skip_web_crawl = False

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
    try:
        search_results = search.text(query, region=region, max_results=n_results)
        if search_results:
            for i, search_result in enumerate(search_results):
                urls.append(search_result['href'])
                search_results_list.append(search_result)
    except Exception:
        pass

    if state.verbose_mode:
        on_print("Web Search Results:", Fore.WHITE + Style.DIM)
        on_print(urls, Fore.WHITE + Style.DIM)

    if len(urls) == 0:
        if cache_check_results:
            if state.verbose_mode:
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

    webCrawler = web_crawler_cls(urls, llm_enabled=True, system_prompt="You are a web crawler assistant.", selected_model=state.current_model, temperature=0.1, verbose=state.verbose_mode, plugins=state.plugins, num_ctx=num_ctx)
    webCrawler.crawl()
    articles = webCrawler.get_articles()

    temp_folder = tempfile.mkdtemp()
    additional_metadata = {}
    for i, article in enumerate(articles):
        temp_file_name = re.sub(r'[<>:"/\\|?*]', '', article['url'])
        temp_file_path = os.path.join(temp_folder, f"{temp_file_name}_{i}.txt")
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            f.write(article['text'])
            additional_metadata[temp_file_path] = {'url': article['url']}

    if web_embedding_model is None or web_embedding_model == "":
        web_embedding_model = state.embeddings_model

    document_indexer = document_indexer_cls(temp_folder, web_cache_collection, state.chroma_client, web_embedding_model, verbose=state.verbose_mode, summary_model=state.current_model)
    document_indexer.index_documents(no_chunking_confirmation=True, additional_metadata=additional_metadata)

    for file in os.listdir(temp_folder):
        file_path = os.path.join(temp_folder, file)
        os.remove(file_path)
    os.rmdir(temp_folder)

    results, result_metadata = query_vector_database_fn(
        query,
        collection_name=web_cache_collection,
        n_results=n_results * 2,
        query_embeddings_model=web_embedding_model,
        use_adaptive_filtering=True,
        return_metadata=True
    )

    if not results:
        new_query = ask_fn("", f"No relevant information found. Please provide a refined search query: {query}", state.current_model, temperature=0.7, no_bot_prompt=True, stream_active=False, num_ctx=num_ctx)
        if new_query:
            if state.verbose_mode:
                on_print(f"Refined search query: {new_query}", Fore.WHITE + Style.DIM)
            return web_search(new_query, n_results, region, web_cache_collection, web_embedding_model, num_ctx, return_intermediate,
                              ask_fn=ask_fn, query_vector_database_fn=query_vector_database_fn,
                              web_crawler_cls=web_crawler_cls, document_indexer_cls=document_indexer_cls,
                              load_chroma_client_fn=load_chroma_client_fn)

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


# ---------------------------------------------------------------------------
# Coding agent tool implementations
# ---------------------------------------------------------------------------

def edit_file(path: str, old_str: str, new_str: str, *, ask_fn=None, model: str = None) -> str:
    """Edit a file by replacing exact string matches.
    
    Args:
        path: Path to the file to edit
        old_str: Exact string to replace (must be unique in file)
        new_str: Replacement string
        ask_fn: Optional LLM call function for auto-revert on failure
        model: Optional model name for tracking failures
        
    Returns:
        Success message or error description
    """
    from ollama_chat_lib.code_tools import edit_file as code_edit_file
    return code_edit_file(path, old_str, new_str, ask_fn=ask_fn, model=model)


def apply_patch(patch: str, *, ask_fn=None, model: str = None) -> str:
    """Apply a unified diff patch to files.
    
    Args:
        patch: Unified diff format patch string
        ask_fn: Optional LLM call function for auto-revert on failure
        model: Optional model name for tracking failures
        
    Returns:
        Success message or error description
    """
    from ollama_chat_lib.code_tools import apply_patch as code_apply_patch
    return code_apply_patch(patch, ask_fn=ask_fn, model=model)


def list_directory(path: str = ".", *, ask_fn=None) -> str:
    """List directory contents with gitignore support.
    
    Args:
        path: Directory path to list (relative to workspace root)
        ask_fn: Optional LLM call function
        
    Returns:
        Formatted directory listing
    """
    from ollama_chat_lib.code_tools import list_directory as code_list_directory
    return code_list_directory(path)


def glob_files(pattern: str, *, ask_fn=None) -> str:
    """Find files matching a glob pattern.
    
    Args:
        pattern: Glob pattern (e.g., "**/*.py")
        ask_fn: Optional LLM call function
        
    Returns:
        List of matching file paths
    """
    from ollama_chat_lib.code_tools import glob_files as code_glob_files
    return code_glob_files(pattern)


def search_code(pattern: str, path: str = ".", *, ask_fn=None) -> str:
    """Search for code patterns using ripgrep or Python fallback.
    
    Args:
        pattern: Regex pattern to search for
        path: Directory to search in (relative to workspace root)
        ask_fn: Optional LLM call function
        
    Returns:
        Search results with file paths and line numbers
    """
    from ollama_chat_lib.code_tools import search_code as code_search_code
    return code_search_code(pattern, path)


def todo_write(todos: list, *, ask_fn=None) -> str:
    """Write/replace the entire todo list.
    
    Args:
        todos: List of todo items, each with 'content', 'status', 'priority'
        ask_fn: Optional LLM call function
        
    Returns:
        Confirmation message
    """
    from ollama_chat_lib.planning import get_todo_store
    store = get_todo_store()
    store.write(todos)
    return f"Todo list updated with {len(todos)} items"


def todo_read(*, ask_fn=None) -> str:
    """Read the current todo list.
    
    Args:
        ask_fn: Optional LLM call function
        
    Returns:
        Formatted todo list
    """
    from ollama_chat_lib.planning import get_todo_store
    store = get_todo_store()
    return store.render_checklist()


def todo_update(todo_id: str, content: str = None, status: str = None, priority: str = None, *, ask_fn=None) -> str:
    """Update a specific todo item.
    
    Args:
        todo_id: ID of the todo to update
        content: New content (optional)
        status: New status - 'pending', 'in_progress', 'completed' (optional)
        priority: New priority - 'high', 'medium', 'low' (optional)
        ask_fn: Optional LLM call function
        
    Returns:
        Confirmation message
    """
    from ollama_chat_lib.planning import get_todo_store
    store = get_todo_store()
    store.update(todo_id, content=content, status=status, priority=priority)
    return f"Todo {todo_id} updated"


def delegate_coding_task(task: str, context_files: list = None, *, ask_fn=None, model: str = None) -> str:
    """Delegate a coding task to a worker sub-agent.
    
    Args:
        task: Description of the coding task
        context_files: List of file paths to provide as context
        ask_fn: LLM call function (required)
        model: Model to use (defaults to state.worker_model)
        
    Returns:
        Structured result from the worker agent
    """
    from ollama_chat_lib.llm_core import delegate_coding_task as llm_delegate_coding_task
    from ollama_chat_lib import state
    
    if ask_fn is None:
        return "Error: ask_fn is required for delegate_coding_task"
    
    worker_model = model or state.worker_model
    return llm_delegate_coding_task(task, context_files, ask_fn=ask_fn, model=worker_model)


def delegate_code_review(task: str, context_files: list = None, *, ask_fn=None, model: str = None) -> str:
    """Delegate a code review task to a reviewer sub-agent.
    
    Args:
        task: Description of the review task
        context_files: List of file paths to review
        ask_fn: LLM call function (required)
        model: Model to use (defaults to state.review_model)
        
    Returns:
        Structured review result from the reviewer agent
    """
    from ollama_chat_lib.llm_core import delegate_code_review as llm_delegate_code_review
    from ollama_chat_lib import state
    
    if ask_fn is None:
        return "Error: ask_fn is required for delegate_code_review"
    
    review_model = model or state.review_model
    return llm_delegate_code_review(task, context_files, ask_fn=ask_fn, model=review_model)
