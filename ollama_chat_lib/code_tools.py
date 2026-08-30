"""Code-specific tools: precise editing, navigation, search."""

import os
import re
import difflib
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, field

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print
from ollama_chat_lib.file_ops import _resolve_path, _get_workspace_root
from colorama import Fore, Style


@dataclass
class EditResult:
    """Result of an edit operation."""
    success: bool
    message: str
    diff: str = ""
    match_failures: int = 0


# Track edit_file match failures per session for model-capability fallback
_edit_failure_streaks: Dict[str, int] = {}  # model_name -> consecutive failures
_EDIT_FAILURE_THRESHOLD = 3  # Switch to whole-file rewrite after N failures


def _get_active_model() -> str:
    """Get the currently active model name."""
    return state.current_model or "unknown"


def _record_edit_failure(model: str):
    """Record an edit_file match failure for the model."""
    _edit_failure_streaks[model] = _edit_failure_streaks.get(model, 0) + 1


def _record_edit_success(model: str):
    """Reset edit failure streak on success."""
    _edit_failure_streaks[model] = 0


def _should_use_whole_file_rewrite(model: str) -> bool:
    """Check if we should suggest whole-file rewrite for this model."""
    return _edit_failure_streaks.get(model, 0) >= _EDIT_FAILURE_THRESHOLD


def _get_syntax_check_cmd(file_path: Path) -> Optional[List[str]]:
    """Get appropriate syntax check command for a file type."""
    suffix = file_path.suffix.lower()
    
    # Python
    if suffix == '.py':
        return ['python', '-m', 'py_compile']
    # JavaScript/TypeScript
    if suffix in ('.js', '.jsx', '.ts', '.tsx'):
        # Check for node/deno/bun
        for cmd in ['node', 'deno', 'bun']:
            try:
                subprocess.run([cmd, '--version'], capture_output=True, check=False)
                if cmd == 'node':
                    return ['node', '--check']
                elif cmd == 'deno':
                    return ['deno', 'check']
                elif cmd == 'bun':
                    return ['bun', 'check']
            except FileNotFoundError:
                continue
    # Go
    if suffix == '.go':
        return ['go', 'build']
    # Rust
    if suffix == '.rs':
        return ['rustc', '--emit=metadata', '-o', '/dev/null']
    # Shell
    if suffix in ('.sh', '.bash'):
        return ['bash', '-n']
    # JSON
    if suffix == '.json':
        return ['python', '-m', 'json.tool']
    # YAML
    if suffix in ('.yaml', '.yml'):
        return ['python', '-c', 'import yaml, sys; yaml.safe_load(sys.stdin)']
    
    return None


def _syntax_check(file_path: Path) -> Tuple[bool, str]:
    """Run syntax check on a file. Returns (success, error_message)."""
    cmd = _get_syntax_check_cmd(file_path)
    if not cmd:
        return True, ""  # No checker available, assume OK
    
    try:
        if cmd[0] == 'python' and '-m' in cmd:
            # Special case for python modules that read from stdin
            with open(file_path, 'r') as f:
                result = subprocess.run(cmd, stdin=f, capture_output=True, text=True, timeout=10)
        else:
            result = subprocess.run(cmd + [str(file_path)], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip() or result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Syntax check timed out"
    except FileNotFoundError:
        return True, ""  # Checker not installed, skip
    except Exception as e:
        return False, str(e)


def list_directory(path: str = ".", recursive: bool = False, respect_gitignore: bool = True) -> str:
    """
    List directory contents.
    
    :param path: Directory path (relative to workspace root)
    :param recursive: Whether to list recursively
    :param respect_gitignore: Whether to respect .gitignore patterns
    :return: Formatted directory listing
    """
    try:
        resolved = _resolve_path(path)
        
        if not resolved.exists():
            return f"Error: Directory '{path}' does not exist."
        
        if not resolved.is_dir():
            return f"Error: '{path}' is not a directory."
        
        workspace_root = _get_workspace_root()
        
        # Get gitignore patterns if requested
        ignore_patterns = []
        if respect_gitignore:
            gitignore_path = workspace_root / '.gitignore'
            if gitignore_path.exists():
                try:
                    with open(gitignore_path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                ignore_patterns.append(line)
                except Exception:
                    pass
        
        import fnmatch
        
        def should_ignore(p: Path) -> bool:
            rel = p.relative_to(workspace_root)
            rel_str = str(rel)
            for pattern in ignore_patterns:
                # Simple glob matching using fnmatch
                if pattern.endswith('/'):
                    # Directory pattern
                    if rel_str.startswith(pattern.rstrip('/') + '/') or rel_str == pattern.rstrip('/'):
                        return True
                else:
                    # File pattern
                    if fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(rel.name, pattern):
                        return True
            return False
        
        entries = []
        
        if recursive:
            for root, dirs, files in os.walk(resolved):
                root_path = Path(root)
                # Filter dirs in-place for os.walk
                dirs[:] = [d for d in dirs if not should_ignore(root_path / d)]
                
                for f in files:
                    file_path = root_path / f
                    if not should_ignore(file_path):
                        rel = file_path.relative_to(workspace_root)
                        entries.append(str(rel))
        else:
            for entry in sorted(resolved.iterdir()):
                if not should_ignore(entry):
                    rel = entry.relative_to(workspace_root)
                    suffix = '/' if entry.is_dir() else ''
                    entries.append(f"{rel}{suffix}")
        
        if not entries:
            return f"Directory '{path}' is empty (or all entries ignored)."
        
        return "\n".join(entries)
    
    except PermissionError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error listing directory '{path}': {str(e)}"


def glob_files(pattern: str, root: Optional[str] = None, max_results: int = 100) -> str:
    """
    Find files matching a glob pattern.
    
    :param pattern: Glob pattern (e.g., '**/*.py', 'src/**/*.rs')
    :param root: Root directory (relative to workspace root, default: workspace root)
    :param max_results: Maximum number of results
    :return: List of matching files
    """
    try:
        workspace_root = _get_workspace_root()
        
        if root:
            search_root = _resolve_path(root)
        else:
            search_root = workspace_root
        
        # Use pathlib's glob
        matches = list(search_root.glob(pattern))
        
        # Filter to files only and within workspace
        files = []
        for m in matches:
            if m.is_file():
                try:
                    rel = m.relative_to(workspace_root)
                    files.append(str(rel))
                except ValueError:
                    pass  # Outside workspace
        
        files.sort()
        
        if len(files) > max_results:
            files = files[:max_results]
            return "\n".join(files) + f"\n... ({len(files)} total, showing first {max_results})"
        
        if not files:
            return f"No files matching pattern '{pattern}' in '{root or '.'}'"
        
        return "\n".join(files)
    
    except PermissionError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error searching for files: {str(e)}"


def search_code(
    pattern: str,
    path: Optional[str] = None,
    regex: bool = True,
    max_results: int = 200,
    file_pattern: Optional[str] = None,
) -> str:
    """
    Search code using ripgrep (if available) or Python regex fallback.
    
    :param pattern: Search pattern (regex or literal string)
    :param path: Directory to search (relative to workspace root)
    :param regex: Whether pattern is a regex
    :param max_results: Maximum number of results
    :param file_pattern: Optional file glob pattern to filter (e.g., '*.py')
    :return: Formatted search results
    """
    try:
        workspace_root = _get_workspace_root()
        
        if path:
            search_path = _resolve_path(path)
        else:
            search_path = workspace_root
        
        # Try ripgrep first
        rg_cmd = ['rg', '--no-heading', '--line-number', '--color=never']
        
        if not regex:
            rg_cmd.append('--fixed-strings')
        
        if file_pattern:
            rg_cmd.extend(['-g', file_pattern])
        
        rg_cmd.append(pattern)
        rg_cmd.append(str(search_path))
        
        try:
            result = subprocess.run(rg_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode in (0, 1):  # 0 = matches, 1 = no matches
                lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
                if len(lines) > max_results:
                    lines = lines[:max_results]
                    return "\n".join(lines) + f"\n... (showing first {max_results} of {len(lines)} matches)"
                return "\n".join(lines) if lines else "No matches found."
        except FileNotFoundError:
            pass  # ripgrep not available, fall back to Python
        
        # Python fallback
        import fnmatch
        
        matches = []
        file_count = 0
        
        for root, dirs, files in os.walk(search_path):
            # Skip .git directory
            if '.git' in dirs:
                dirs.remove('.git')
            
            for f in files:
                file_path = Path(root) / f
                
                # Check file pattern
                if file_pattern and not fnmatch.fnmatch(f, file_pattern):
                    continue
                
                # Skip binary files
                try:
                    with open(file_path, 'r', encoding='utf-8') as fp:
                        content = fp.read()
                except (UnicodeDecodeError, PermissionError, OSError):
                    continue
                
                file_count += 1
                if file_count > 1000:  # Limit files scanned
                    break
                
                for i, line in enumerate(content.splitlines(), 1):
                    if regex:
                        if re.search(pattern, line):
                            rel = file_path.relative_to(workspace_root)
                            matches.append(f"{rel}:{i}:{line}")
                            if len(matches) >= max_results:
                                break
                    else:
                        if pattern in line:
                            rel = file_path.relative_to(workspace_root)
                            matches.append(f"{rel}:{i}:{line}")
                            if len(matches) >= max_results:
                                break
                
                if len(matches) >= max_results:
                    break
            
            if len(matches) >= max_results:
                break
        
        if not matches:
            return "No matches found."
        
        return "\n".join(matches)
    
    except PermissionError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error searching code: {str(e)}"


def edit_file(
    path: str,
    old_str: str,
    new_str: str,
    expect_unique: bool = True,
    replace_all: bool = False,
) -> str:
    """
    Edit a file by replacing old_str with new_str (exact string replacement).
    
    Modeled on Claude Code's Edit tool: requires unique match by default,
    returns unified diff, runs post-edit syntax check, auto-reverts on failure.
    
    :param path: File path (relative to workspace root)
    :param old_str: Exact string to replace (must match uniquely unless replace_all=True)
    :param new_str: Replacement string
    :param expect_unique: If True, fail if old_str doesn't match exactly once
    :param replace_all: If True, replace all occurrences
    :return: Result message with diff or error
    """
    try:
        resolved = _resolve_path(path)
        
        if not resolved.exists():
            return f"Error: File '{path}' does not exist."
        
        if not resolved.is_file():
            return f"Error: '{path}' is not a file."
        
        # Read original content
        with open(resolved, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        # Count occurrences
        occurrences = original_content.count(old_str)
        
        model = _get_active_model()
        
        if occurrences == 0:
            _record_edit_failure(model)
            
            # Provide helpful context
            suggestion = ""
            if _should_use_whole_file_rewrite(model):
                suggestion = f"\n{Fore.YELLOW}Note: This model has had {_EDIT_FAILURE_THRESHOLD}+ consecutive edit failures. Consider using create_file for whole-file rewrite instead.{Style.RESET_ALL}"
            
            # Show context around expected match
            lines = original_content.splitlines()
            # Try to find similar lines
            best_match = None
            best_ratio = 0
            for i, line in enumerate(lines):
                ratio = difflib.SequenceMatcher(None, old_str[:100], line[:100]).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = (i + 1, line[:200])
            
            context = ""
            if best_match and best_ratio > 0.5:
                context = f"\nNearest match at line {best_match[0]} (similarity: {best_ratio:.0%}):\n  {best_match[1]}"
            
            return f"Error: old_str not found in file. Expected exactly one match, found 0.{context}{suggestion}"
        
        if expect_unique and not replace_all and occurrences > 1:
            _record_edit_failure(model)
            return f"Error: old_str matches {occurrences} locations. Use replace_all=True to replace all, or provide more context to make it unique."
        
        # Perform replacement
        if replace_all:
            new_content = original_content.replace(old_str, new_str)
            replaced_count = occurrences
        else:
            new_content = original_content.replace(old_str, new_str, 1)
            replaced_count = 1
        
        # Generate unified diff
        diff = _generate_unified_diff(original_content, new_content, path)
        
        # Write new content
        with open(resolved, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        # Post-edit syntax check
        syntax_ok, syntax_error = _syntax_check(resolved)
        
        if not syntax_ok:
            # Auto-revert
            with open(resolved, 'w', encoding='utf-8') as f:
                f.write(original_content)
            _record_edit_failure(model)
            return f"Error: Syntax check failed after edit, changes reverted.\n{syntax_error}\n\nDiff that was attempted:\n{diff}"
        
        _record_edit_success(model)
        
        result = f"Successfully edited '{path}' ({replaced_count} replacement{'s' if replaced_count != 1 else ''}).\n\nDiff:\n{diff}"
        
        if _should_use_whole_file_rewrite(model):
            result += f"\n{Fore.YELLOW}Note: This model has had {_EDIT_FAILURE_THRESHOLD}+ consecutive edit failures. Consider using create_file for whole-file rewrite instead.{Style.RESET_ALL}"
        
        return result
    
    except PermissionError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error editing file '{path}': {str(e)}"


def apply_patch(path: str, unified_diff: str) -> str:
    """
    Apply a unified diff patch to a file.
    
    :param path: File path (relative to workspace root)
    :param unified_diff: Unified diff format patch
    :return: Result message
    """
    try:
        resolved = _resolve_path(path)
        
        if not resolved.exists():
            return f"Error: File '{path}' does not exist."
        
        if not resolved.is_file():
            return f"Error: '{path}' is not a file."
        
        # Read original content
        with open(resolved, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        # Parse and apply patch
        new_content = _apply_unified_diff(original_content, unified_diff)
        
        if new_content == original_content:
            return "Error: Patch did not change the file (no hunks applied)."
        
        # Write new content
        with open(resolved, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        # Post-edit syntax check
        syntax_ok, syntax_error = _syntax_check(resolved)
        
        if not syntax_ok:
            # Auto-revert
            with open(resolved, 'w', encoding='utf-8') as f:
                f.write(original_content)
            return f"Error: Syntax check failed after patch, changes reverted.\n{syntax_error}"
        
        # Generate diff for display
        diff = _generate_unified_diff(original_content, new_content, path)
        
        return f"Successfully applied patch to '{path}'.\n\nDiff:\n{diff}"
    
    except PermissionError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error applying patch to '{path}': {str(e)}"


def _generate_unified_diff(old: str, new: str, path: str) -> str:
    """Generate a unified diff between two strings."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm=""
    )
    
    return "\n".join(diff)


def _apply_unified_diff(content: str, unified_diff: str) -> str:
    """Apply a unified diff to content. Simple implementation for basic patches."""
    lines = content.splitlines(keepends=True)
    diff_lines = unified_diff.splitlines(keepends=True)
    
    # Parse unified diff header
    i = 0
    while i < len(diff_lines) and not diff_lines[i].startswith('@@'):
        i += 1
    
    if i >= len(diff_lines):
        return content  # No hunks
    
    # Simple hunk application - this is a basic implementation
    # For production, consider using `patch` command or a proper diff library
    result_lines = lines[:]
    
    while i < len(diff_lines):
        line = diff_lines[i]
        if line.startswith('@@'):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            import re
            match = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@', line)
            if match:
                old_start = int(match.group(1)) - 1  # 0-indexed
                old_count = int(match.group(2)) if match.group(2) else 1
                new_start = int(match.group(3)) - 1
                # new_count = int(match.group(4)) if match.group(4) else 1
                
                # Collect hunk lines
                hunk_lines = []
                i += 1
                while i < len(diff_lines) and not diff_lines[i].startswith('@@'):
                    hunk_lines.append(diff_lines[i])
                    i += 1
                
                # Apply hunk
                new_hunk = []
                for hunk_line in hunk_lines:
                    if hunk_line.startswith(' '):
                        new_hunk.append(hunk_line[1:])
                    elif hunk_line.startswith('+'):
                        new_hunk.append(hunk_line[1:])
                    elif hunk_line.startswith('-'):
                        pass  # Deleted line
                
                # Replace in result
                end = min(old_start + old_count, len(result_lines))
                result_lines = result_lines[:old_start] + new_hunk + result_lines[end:]
                continue
        i += 1
    
    return "".join(result_lines)


def get_edit_failure_info(model: Optional[str] = None) -> str:
    """Get information about edit failure streaks."""
    if model is None:
        model = _get_active_model()
    
    failures = _edit_failure_streaks.get(model, 0)
    if failures > 0:
        return f"Model '{model}' has {failures} consecutive edit_file match failure(s). Threshold for whole-file rewrite suggestion: {_EDIT_FAILURE_THRESHOLD}."
    return f"Model '{model}' has no recent edit failures."