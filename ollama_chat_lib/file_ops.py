"""File and command operations — read, create, delete files; expand env vars; run shell commands."""
import os
import shlex
import subprocess
from typing import Tuple, Optional
from pathlib import Path

from colorama import Fore, Style

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print
from ollama_chat_lib.terminal import (
    TerminalSession, get_global_terminal, resolve_in_workspace, run_command as term_run_command
)


def _get_workspace_root() -> Path:
    """Get the workspace root from state or use current directory."""
    if hasattr(state, 'workspace_root') and state.workspace_root:
        return Path(state.workspace_root).resolve()
    return Path.cwd()


def _resolve_path(file_path: str) -> Path:
    """Resolve a file path within the workspace root."""
    workspace_root = _get_workspace_root()
    p = Path(file_path)
    if not p.is_absolute():
        p = (workspace_root / p).resolve()
    else:
        p = p.resolve()
    
    # Check workspace confinement
    try:
        p.relative_to(workspace_root)
    except ValueError:
        raise PermissionError(f"Path '{file_path}' escapes workspace root: {workspace_root}")
    return p


def read_file(file_path, encoding="utf-8"):
    """
    Read the contents of a file and return the text.
    
    :param file_path: The full path to the file to read
    :param encoding: The encoding to use when reading the file (default: 'utf-8')
    :return: The file contents as a string, or an error message if the operation fails
    """
    try:
        resolved_path = _resolve_path(file_path)
        
        if not resolved_path.exists():
            return f"Error: File '{file_path}' does not exist."
        
        if not resolved_path.is_file():
            return f"Error: '{file_path}' is not a file."
        
        with open(resolved_path, 'r', encoding=encoding) as f:
            content = f.read()
        
        if state.verbose_mode:
            on_print(f"Successfully read file: {file_path}", Fore.GREEN + Style.DIM)
        
        return content
    except PermissionError as e:
        return f"Error: {str(e)}"
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
        resolved_path = _resolve_path(file_path)
        
        # Create parent directories if they don't exist
        parent_dir = resolved_path.parent
        if parent_dir and not parent_dir.exists():
            parent_dir.mkdir(parents=True, exist_ok=True)
        
        # Write the file
        with open(resolved_path, 'w', encoding=encoding) as f:
            f.write(content)
        
        # Track the file for session-based deletion
        if str(resolved_path) not in state.session_created_files:
            state.session_created_files.append(str(resolved_path))
        
        if state.verbose_mode:
            on_print(f"Successfully created file: {file_path}", Fore.GREEN + Style.DIM)
        
        return f"File created successfully: {file_path}"
    except PermissionError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error creating file '{file_path}': {str(e)}"


def delete_file(file_path):
    """
    Delete a file that was created during this session. Only files created with the create_file tool can be deleted.
    
    :param file_path: The full path to the file to delete
    :return: A success message or error message
    """
    try:
        resolved_path = _resolve_path(file_path)
        
        # Check if the file was created during this session
        if str(resolved_path) not in state.session_created_files:
            return f"Error: Cannot delete file '{file_path}'. It was not created during this session."
        
        # Check if the file exists
        if not resolved_path.exists():
            # Remove from tracking list even if file doesn't exist
            state.session_created_files.remove(str(resolved_path))
            return f"File '{file_path}' was already deleted or does not exist."
        
        # Delete the file
        resolved_path.unlink()
        
        # Remove from tracking list
        state.session_created_files.remove(str(resolved_path))
        
        if state.verbose_mode:
            on_print(f"Successfully deleted file: {file_path}", Fore.GREEN + Style.DIM)
        
        return f"File deleted successfully: {file_path}"
    except PermissionError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error deleting file '{file_path}': {str(e)}"


def expand_env_vars(command: str) -> str:
    return os.path.expandvars(command)


def run_command(command: str, workspace_root: Optional[str] = None) -> Tuple[str, str]:
    """Run a shell command using the terminal subsystem (backward compatible)."""
    return term_run_command(command, workspace_root)
