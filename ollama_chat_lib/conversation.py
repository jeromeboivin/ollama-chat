"""Conversation helpers: UI utilities, chatbot management, save/load,
summarization, and other conversation-related functions.

Functions that need LLM access accept an ``ask_fn`` parameter
(constructor injection) so this module stays decoupled from the monolith.
"""

import os
import re
import json
import math
import base64
import mimetypes

from colorama import Fore, Style
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import Terminal256Formatter

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print, on_stdout_write, on_stdout_flush, on_user_input
from ollama_chat_lib.terminal_ui import (
    format_prompt_commands_help, prompt_for_single_choice, thinking_spinner_prompt,
)


# ── UI helpers ────────────────────────────────────────────────────────────

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


def print_spinning_wheel(print_char_index):
    # use turning block character as spinner
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    spinner_style, spinner_prompt = thinking_spinner_prompt()
    on_stdout_write(spinner[print_char_index % len(spinner)], spinner_style, spinner_prompt)
    on_stdout_flush()


def encode_file_to_base64_with_mime(file_path):
    """
    Reads a file and returns it as a base64-encoded string with the proper MIME type prefix.

    Args:
        file_path: Path to the file

    Returns:
        String in format: "data:<mime-type>;base64,<base64-data>"
    """
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


# ── Prompt commands help ──────────────────────────────────────────────────

def print_possible_prompt_commands():
    return format_prompt_commands_help()


# ── Chatbot management ───────────────────────────────────────────────────

# Default chatbots — populated at import time, mutated via load_additional_chatbots()
DEFAULT_CHATBOTS = [
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
        "system_prompt": "CONTEXT: We are going to create one of the best ChatGPT prompts ever written. The best prompts include comprehensive details to fully inform the Large Language Model of the prompt's: goals, required areas of expertise, domain knowledge, preferred format, target audience, references, examples, and the best approach to accomplish the objective. Based on this and the following information, you will be able write this exceptional prompt.\r\n\r\nROLE: You are an LLM prompt generation expert. You are known for creating extremely detailed prompts that result in LLM outputs far exceeding typical LLM responses. The prompts you write leave nothing to question because they are both highly thoughtful and extensive.\r\n\r\nACTION:\r\n\r\n1) Before you begin writing this prompt, you will first look to receive the prompt topic or theme. If I don't provide the topic or theme for you, please request it.\r\n2) Once you are clear about the topic or theme, please also review the Format and Example provided below.\r\n3) If necessary, the prompt should include \"fill in the blank\" elements for the user to populate based on their needs.\r\n4) Take a deep breath and take it one step at a time.\r\n5) Once you've ingested all of the information, write the best prompt ever created.\r\n\r\nFORMAT: For organizational purposes, you will use an acronym called \"C.R.A.F.T.\" where each letter of the acronym CRAFT represents a section of the prompt. Your format and section descriptions for this prompt development are as follows:\r\n\r\nContext: This section describes the current context that outlines the situation for which the prompt is needed. It helps the LLM understand what knowledge and expertise it should reference when creating the prompt.\r\n\r\nRole: This section defines the type of experience the LLM has, its skill set, and its level of expertise relative to the prompt requested. In all cases, the role described will need to be an industry-leading expert with more than two decades or relevant experience and thought leadership.\r\n\r\nAction: This is the action that the prompt will ask the LLM to take. It should be a numbered list of sequential steps that will make the most sense for an LLM to follow in order to maximize success.\r\n\r\nFormat: This refers to the structural arrangement or presentation style of the LLM's generated content. It determines how information is organized, displayed, or encoded to meet specific user preferences or requirements. Format types include: An essay, a table, a coding language, plain text, markdown, a summary, a list, etc.\r\n\r\nTarget Audience: This will be the ultimate consumer of the output that your prompt creates. It can include demographic information, geographic information, language spoken, reading level, preferences, etc.\r\n\r\nTARGET AUDIENCE: The target audience for this prompt creation is ChatGPT 4o or ChatGPT o1.\r\n\r\nEXAMPLE: Here is an Example of a CRAFT Prompt for your reference:\r\n\r\n**Context:** You are tasked with creating a detailed guide to help individuals set, track, and achieve monthly goals. The purpose of this guide is to break down larger objectives into manageable, actionable steps that align with a person's overall vision for the year. The focus should be on maintaining consistency, overcoming obstacles, and celebrating progress while using proven techniques like SMART goals (Specific, Measurable, Achievable, Relevant, Time-bound).\r\n\r\n**Role:** You are an expert productivity coach with over two decades of experience in helping individuals optimize their time, define clear goals, and achieve sustained success. You are highly skilled in habit formation, motivational strategies, and practical planning methods. Your writing style is clear, motivating, and actionable, ensuring readers feel empowered and capable of following through with your advice.\r\n\r\n**Action:** 1. Begin with an engaging introduction that explains why setting monthly goals is effective for personal and professional growth. Highlight the benefits of short-term goal planning. 2. Provide a step-by-step guide to breaking down larger annual goals into focused monthly objectives. 3. Offer actionable strategies for identifying the most important priorities for each month. 4. Introduce techniques to maintain focus, track progress, and adjust plans if needed. 5. Include examples of monthly goals for common areas of life (e.g., health, career, finances, personal development). 6. Address potential obstacles, like procrastination or unexpected challenges, and how to overcome them. 7. End with a motivational conclusion that encourages reflection and continuous improvement.\r\n\r\n**Format:** Write the guide in plain text, using clear headings and subheadings for each section. Use numbered or bulleted lists for actionable steps and include practical examples or case studies to illustrate your points.\r\n\r\n**Target Audience:** The target audience includes working professionals and entrepreneurs aged 25-55 who are seeking practical, straightforward strategies to improve their productivity and achieve their goals. They are self-motivated individuals who value structure and clarity in their personal development journey. They prefer reading at a 6th grade level.\r\n\r\n-End example-\r\n\r\nPlease reference the example I have just provided for your output. Again, take a deep breath and take it one step at a time."
    }
]


def load_additional_chatbots(json_file):

    if not json_file:
        return

    if not os.path.exists(json_file):
        # Check if the file exists in the same directory as the calling script
        # We use __file__ indirection: the caller should pass an absolute or script-relative path.
        # For backward compat, try relative to cwd.
        if not os.path.exists(json_file):
            on_print(f"Additional chatbots file not found: {json_file}", Fore.RED)
            return

    with open(json_file, 'r', encoding="utf8") as f:
        additional_chatbots = json.load(f)

    for chatbot in additional_chatbots:
        chatbot["system_prompt"] = chatbot["system_prompt"].replace("{possible_prompt_commands}", print_possible_prompt_commands())
        state.chatbots.append(chatbot)


def split_numbered_list(input_text):
    lines = input_text.split('\n')
    output = []
    for line in lines:
        if re.match(r'^\d+\.', line):  # Check if the line starts with a number followed by a period
            output.append(line.split('.', 1)[1].strip())  # Remove the leading number and period, then strip any whitespace
    return output


def prompt_for_chatbot():
    options = []
    for chatbot in state.chatbots:
        options.append({
            "value": chatbot,
            "key": chatbot["name"],
            "label": chatbot["name"],
            "description": chatbot["description"],
            "group": "Chatbots",
        })

    return prompt_for_single_choice(
        "Choose a chatbot. Type to filter or press Tab to browse.",
        options,
        default_value=state.chatbots[0] if state.chatbots else None,
        prompt_label="chatbot",
        read_fn=on_user_input,
        print_fn=on_print,
    )


# ── Conversation persistence ─────────────────────────────────────────────

def save_conversation_to_file(conversation, file_path):

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

    if state.verbose_mode:
        on_print(f"Conversation saved to {file_path}", Fore.WHITE + Style.DIM)

    # Save the conversation to a JSON file
    json_file_path = file_path.replace(".txt", ".json")
    with open(json_file_path, 'w', encoding="utf8") as f:
        json.dump(conversation, f, indent=4)

    if state.verbose_mode:
        on_print(f"Conversation saved to {json_file_path}", Fore.WHITE + Style.DIM)


# ── Summarization ────────────────────────────────────────────────────────

def summarize_chunk(text_chunk, model, max_summary_words, previous_summary=None, num_ctx=None, language='English', ask_fn=None):
    """
    Summarizes a single chunk of text using the provided LLM.

    Args:
        text_chunk (str): The piece of text to summarize.
        model (str): The name of the LLM model to use for summarization.
        max_summary_words (int): The approximate desired word count for the chunk's summary.
        previous_summary (str, optional): The previous summary to include in the prompt.
        num_ctx (int, optional): The number of context tokens to use for the LLM.
        language (str): Language to produce the summary in.
        ask_fn: Callable(system_prompt, user_input, model, ...) for LLM calls.

    Returns:
        str: The summarized text.
    """
    system_prompt = (
        "You are an expert at summarizing text. Your task is to provide a concise summary of the given content, "
        "maintaining context from previous parts. Always produce the summary in the requested language."
    )

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

    state.user_prompt = user_prompt

    if ask_fn is None:
        raise ValueError("ask_fn must be provided for summarize_chunk")

    summary = ask_fn(system_prompt, user_prompt, model, no_bot_prompt=True, stream_active=False, num_ctx=num_ctx)
    return summary or ""


def summarize_text_file(file_path, model=None, chunk_size=400, overlap=50, max_final_words=500, num_ctx=None, language='English', ask_fn=None):
    """
    Summarizes a long text by breaking it into chunks, summarizing them,
    and then iteratively summarizing the summaries until the final text is
    under a specified word count.

    Args:
        file_path (str): The complete text file to summarize.
        model (str): The model name to be used for the summarization.
        chunk_size (int): The number of words in each text chunk.
        overlap (int): The number of words to overlap between consecutive chunks.
        max_final_words (int): The maximum number of words desired for the final summary.
        num_ctx (int, optional): The number of context tokens to use for the LLM.
        language (str): Language for summaries.
        ask_fn: Callable for LLM calls.

    Returns:
        str: The final, concise summary.
    """
    if not model:
        model = state.current_model

    # Read the full text from the file
    with open(file_path, 'r', encoding='utf-8') as f:
        full_text = f.read()

    words = full_text.split()
    current_text_words = words

    while len(current_text_words) > max_final_words:
        if state.verbose_mode:
            on_print(f"\n>>> Iteration: Processing {len(current_text_words)} words...", Fore.WHITE + Style.DIM)

        num_chunks_approx = math.ceil(len(current_text_words) / (chunk_size - overlap))
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
        previous_summary = None
        for i, chunk in enumerate(chunks):
            if state.verbose_mode:
                on_print(f"Processing chunk {i+1}/{len(chunks)} with {len(chunk.split())} words", Fore.WHITE + Style.DIM)
            summary = summarize_chunk(chunk, model, per_chunk_summary_words, previous_summary=previous_summary, num_ctx=num_ctx, language=language, ask_fn=ask_fn)
            summaries.append(summary)
            previous_summary = summary

        combined_summaries = " ".join(summaries)
        current_text_words = combined_summaries.split()

        if state.verbose_mode:
            on_print(f"<<< Iteration Complete: {len(summaries)} summaries created, new word count is {len(current_text_words)}", Fore.WHITE + Style.DIM)
            on_print(f"Current text after summarization: {combined_summaries[:100]}...", Fore.WHITE + Style.DIM)

    final_summary = " ".join(current_text_words)
    return final_summary
