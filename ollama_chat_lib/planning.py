"""Planning and todo tracking for the coding agent orchestrator."""

import uuid
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print
from colorama import Fore, Style


class TodoStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass
class TodoItem:
    """A single todo item."""
    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING
    priority: str = "medium"  # high, medium, low
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    result: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['status'] = self.status.value
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TodoItem':
        data = data.copy()
        data['status'] = TodoStatus(data['status'])
        return cls(**data)


class TodoStore:
    """In-memory todo store attached to agent state."""
    
    def __init__(self):
        self._todos: Dict[str, TodoItem] = {}
        self._order: List[str] = []  # Maintains insertion order
    
    def write(self, items: List[Dict[str, Any]]) -> str:
        """
        Write/replace the entire todo list.
        
        Args:
            items: List of dicts with 'content' (required), 'status' (optional), 'id' (optional)
        
        Returns:
            Summary message
        """
        self._todos.clear()
        self._order.clear()
        
        for item_data in items:
            if 'id' not in item_data:
                item_data['id'] = str(uuid.uuid4())[:8]
            if 'status' not in item_data:
                item_data['status'] = 'pending'
            
            if isinstance(item_data['status'], str):
                item_data['status'] = TodoStatus(item_data['status'])
            
            todo = TodoItem(**item_data)
            self._todos[todo.id] = todo
            self._order.append(todo.id)
        
        return f"Todo list updated with {len(items)} item(s)."
    
    def read(self) -> List[Dict[str, Any]]:
        """Read all todos in order."""
        return [self._todos[tid].to_dict() for tid in self._order]
    
    def update(self, todo_id: str, status: Optional[str] = None, content: Optional[str] = None,
               priority: Optional[str] = None, result: Optional[str] = None, error: Optional[str] = None) -> str:
        """
        Update a todo item.
        
        Args:
            todo_id: ID of the todo to update
            status: New status (pending, in_progress, completed, blocked, failed)
            content: New content
            priority: New priority (high, medium, low)
            result: Result of completion
            error: Error message if failed
        
        Returns:
            Status message
        """
        if todo_id not in self._todos:
            return f"Error: Todo '{todo_id}' not found."
        
        todo = self._todos[todo_id]
        
        if status is not None:
            todo.status = TodoStatus(status)
        if content is not None:
            todo.content = content
        if priority is not None:
            todo.priority = priority
        if result is not None:
            todo.result = result
        if error is not None:
            todo.error = error
        
        todo.updated_at = datetime.now().isoformat()
        
        return f"Todo '{todo_id}' updated to {todo.status.value}."
    
    def get(self, todo_id: str) -> Optional[Dict[str, Any]]:
        """Get a single todo by ID."""
        todo = self._todos.get(todo_id)
        return todo.to_dict() if todo else None
    
    def delete(self, todo_id: str) -> str:
        """Delete a todo item."""
        if todo_id not in self._todos:
            return f"Error: Todo '{todo_id}' not found."
        
        del self._todos[todo_id]
        self._order.remove(todo_id)
        return f"Todo '{todo_id}' deleted."
    
    def clear_completed(self) -> int:
        """Remove all completed todos. Returns count removed."""
        completed_ids = [tid for tid, todo in self._todos.items() if todo.status == TodoStatus.COMPLETED]
        for tid in completed_ids:
            del self._todos[tid]
            self._order.remove(tid)
        return len(completed_ids)
    
    def get_pending(self) -> List[Dict[str, Any]]:
        """Get all pending/in-progress todos."""
        return [
            self._todos[tid].to_dict()
            for tid in self._order
            if self._todos[tid].status in (TodoStatus.PENDING, TodoStatus.IN_PROGRESS)
        ]
    
    def get_next_pending(self) -> Optional[Dict[str, Any]]:
        """Get the next pending todo (first in order)."""
        for tid in self._order:
            todo = self._todos[tid]
            if todo.status == TodoStatus.PENDING:
                return todo.to_dict()
        return None
    
    def render_checklist(self) -> str:
        """Render todos as a formatted checklist for terminal UI."""
        if not self._order:
            return f"{Fore.YELLOW}(no todos){Style.RESET_ALL}"
        
        lines = []
        status_icons = {
            TodoStatus.PENDING: f"{Fore.WHITE}[ ]{Style.RESET_ALL}",
            TodoStatus.IN_PROGRESS: f"{Fore.CYAN}[~]{Style.RESET_ALL}",
            TodoStatus.COMPLETED: f"{Fore.GREEN}[✓]{Style.RESET_ALL}",
            TodoStatus.BLOCKED: f"{Fore.YELLOW}[!]{Style.RESET_ALL}",
            TodoStatus.FAILED: f"{Fore.RED}[✗]{Style.RESET_ALL}",
        }
        
        for i, tid in enumerate(self._order, 1):
            todo = self._todos[tid]
            icon = status_icons.get(todo.status, "[?]")
            content = todo.content
            
            # Truncate long content
            if len(content) > 100:
                content = content[:97] + "..."
            
            lines.append(f"  {i}. {icon} {content}")
            
            # Show result/error for completed/failed
            if todo.status == TodoStatus.COMPLETED and todo.result:
                result_preview = todo.result[:80]
                if len(todo.result) > 80:
                    result_preview += "..."
                lines.append(f"      {Fore.GREEN}→ {result_preview}{Style.RESET_ALL}")
            elif todo.status == TodoStatus.FAILED and todo.error:
                error_preview = todo.error[:80]
                if len(todo.error) > 80:
                    error_preview += "..."
                lines.append(f"      {Fore.RED}→ {error_preview}{Style.RESET_ALL}")
            elif todo.status == TodoStatus.BLOCKED and todo.error:
                error_preview = todo.error[:80]
                if len(todo.error) > 80:
                    error_preview += "..."
                lines.append(f"      {Fore.YELLOW}→ blocked: {error_preview}{Style.RESET_ALL}")
        
        return "\n".join(lines)


# Global todo store (attached to state in practice)
_global_todo_store: Optional[TodoStore] = None


def get_todo_store() -> TodoStore:
    """Get or create the global todo store."""
    global _global_todo_store
    if _global_todo_store is None:
        _global_todo_store = TodoStore()
    return _global_todo_store


# Tool functions for the agent

def todo_write(items: List[Dict[str, Any]]) -> str:
    """
    Write/replace the entire todo list.
    
    Args:
        items: List of todo items. Each item should have:
            - content (str, required): The task description
            - status (str, optional): pending, in_progress, completed, blocked, failed
            - id (str, optional): Unique identifier (auto-generated if not provided)
    
    Returns:
        Status message
    """
    store = get_todo_store()
    return store.write(items)


def todo_read() -> str:
    """
    Read the current todo list.
    
    Returns:
        Formatted todo list
    """
    store = get_todo_store()
    todos = store.read()
    
    if not todos:
        return "Todo list is empty."
    
    # Return as JSON for programmatic use, but also render for display
    import json
    return json.dumps(todos, indent=2)


def todo_update(todo_id: str, status: str = None, content: str = None, 
                result: str = None, error: str = None) -> str:
    """
    Update a todo item.
    
    Args:
        todo_id: ID of the todo to update
        status: New status (pending, in_progress, completed, blocked, failed)
        content: New content
        result: Result of completion
        error: Error message if failed
    
    Returns:
        Status message
    """
    store = get_todo_store()
    return store.update(todo_id, status, content, result, error)


def todo_delete(todo_id: str) -> str:
    """Delete a todo item."""
    store = get_todo_store()
    return store.delete(todo_id)


def todo_clear_completed() -> str:
    """Clear all completed todos."""
    store = get_todo_store()
    count = store.clear_completed()
    return f"Cleared {count} completed todo(s)."


def todo_render() -> str:
    """Render the todo list as a formatted checklist."""
    store = get_todo_store()
    return store.render_checklist()