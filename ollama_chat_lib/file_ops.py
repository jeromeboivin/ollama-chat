"""File and command operations — read, create, delete files; expand env vars; run shell commands."""
import os
import shlex
import subprocess
from typing import Tuple

from colorama import Fore, Style

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print


def read_file(file_path, encoding="utf-8"):
    """
    Read the contents of a file and return the text.
    
    :param file_path: The full path to the file to read
    :param encoding: The encoding to use when reading the file (default: 'utf-8')
    :return: The file contents as a string, or an error message if the operation fails
    """
    try:
        if not os.path.exists(file_path):
            return f"Error: File '{file_path}' does not exist."
        
        if not os.path.isfile(file_path):
            return f"Error: '{file_path}' is not a file."
        
        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
        
        if state.verbose_mode:
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
    try:
        # Create parent directories if they don't exist
        parent_dir = os.path.dirname(file_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        # Write the file
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        
        # Track the file for session-based deletion
        if file_path not in state.session_created_files:
            state.session_created_files.append(file_path)
        
        if state.verbose_mode:
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
    try:
        # Check if the file was created during this session
        if file_path not in state.session_created_files:
            return f"Error: Cannot delete file '{file_path}'. It was not created during this session."
        
        # Check if the file exists
        if not os.path.exists(file_path):
            # Remove from tracking list even if file doesn't exist
            state.session_created_files.remove(file_path)
            return f"File '{file_path}' was already deleted or does not exist."
        
        # Delete the file
        os.remove(file_path)
        
        # Remove from tracking list
        state.session_created_files.remove(file_path)
        
        if state.verbose_mode:
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
