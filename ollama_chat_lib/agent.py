"""Agent: task decomposition and execution with tool support."""

import re

from colorama import Fore, Style

from ollama_chat_lib.io_hooks import on_print
from ollama_chat_lib.utils import render_tools


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

    def __init__(self, name, description, model, thinking_model=None, system_prompt=None, temperature=0.7, max_iterations=15, tools=None, verbose=False, num_ctx=None, thinking_model_reasoning_pattern=None, ask_fn=None):
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
        self._ask_fn = ask_fn

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

        llm_response = self._ask_fn(system_prompt, prompt, model, temperature=self.temperature, no_bot_prompt=True, stream_active=False, tools=tools, num_ctx=self.num_ctx)

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
