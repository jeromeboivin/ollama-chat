"""Cross-platform persistent terminal subsystem with risk classification.

Provides TerminalSession for PTY-backed persistent shells with streaming output,
background process support, workspace-root confinement, and risk-tiered execution.
"""

import os
import sys
import shlex
import signal
import subprocess
import threading
import time
import select
import fcntl
import termios
import struct
from typing import Optional, Tuple, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json

from ollama_chat_lib import state
from ollama_chat_lib.io_hooks import on_print, on_stdout_write, on_stdout_flush
from colorama import Fore, Style


class RiskTier(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


@dataclass
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    risk_tier: RiskTier = RiskTier.LOW
    timed_out: bool = False
    truncated: bool = False


@dataclass
class BackgroundProcess:
    """Represents a running background process."""
    pid: int
    command: str
    process: subprocess.Popen
    stdout_buffer: List[str] = field(default_factory=list)
    stderr_buffer: List[str] = field(default_factory=list)
    stdout_thread: Optional[threading.Thread] = None
    stderr_thread: Optional[threading.Thread] = None
    finished: bool = False
    returncode: Optional[int] = None
    start_time: float = field(default_factory=time.time)


class TerminalSession:
    """Cross-platform persistent terminal session with PTY support."""
    
    DEFAULT_TIMEOUT = 120  # seconds
    MAX_OUTPUT_SIZE = 1024 * 1024  # 1MB output cap
    
    # Hard denylist - commands that are always blocked
    DENYLIST = {
        'rm -rf /', 'rm -rf /*', ':(){ :|:& };:', 'fork bomb',
        'dd if=/dev/zero', 'mkfs', 'fdisk', 'parted',
        'shutdown', 'reboot', 'halt', 'poweroff',
        'chmod 777 /', 'chown -R root:root /',
        '> /dev/sda', '> /dev/nvme', 'cryptsetup', 'cryptsetup luksFormat',
    }
    
    # Risk classification patterns
    HIGH_RISK_PATTERNS = [
        (r'rm\s+(-rf?|--recursive\s+--force)', 'Recursive deletion'),
        (r'git\s+push\s+.*--force', 'Force push to git remote'),
        (r'git\s+push\s+.*-f\b', 'Force push to git remote'),
        (r'sudo\s+', 'Sudo/root escalation'),
        (r'doas\s+', 'Doas/root escalation'),
        (r'su\s+', 'User switching'),
        (r'chmod\s+777', 'World-writable permissions'),
        (r'chown\s+-R\s+root', 'Recursive root ownership change'),
        (r'curl\s+.*\|\s*(sh|bash)', 'Pipe curl to shell'),
        (r'wget\s+.*\|\s*(sh|bash)', 'Pipe wget to shell'),
        (r'\|\s*(sh|bash)\s*$', 'Pipe to shell'),
        (r'nc\s+-l', 'Netcat listener'),
        (r'ncat\s+-l', 'Ncat listener'),
        (r'socat\s+', 'Socat network tool'),
        (r'/dev/(tcp|udp)/', 'Bash network redirection'),
        (r'mount\s+', 'Filesystem mount'),
        (r'umount\s+', 'Filesystem unmount'),
        (r'fdisk|parted|mkfs|format', 'Disk partitioning/formatting'),
        (r'cryptsetup|luks', 'Disk encryption'),
        (r'iptables|nftables|ufw|firewall', 'Firewall modification'),
        (r'systemctl\s+(start|stop|restart|enable|disable)', 'Service control'),
        (r'service\s+\w+\s+(start|stop|restart)', 'Service control'),
        (r'docker\s+(run|exec|build)\s+.*--privileged', 'Privileged container'),
        (r'kubectl\s+(apply|delete|exec)\s+.*-n\s+kube-system', 'Kube-system namespace'),
    ]
    
    MEDIUM_RISK_PATTERNS = [
        (r'rm\s+', 'File deletion'),
        (r'git\s+(reset|checkout|clean)\s+.*--hard', 'Hard git reset/clean'),
        (r'git\s+rebase', 'Git rebase (history rewrite)'),
        (r'git\s+commit\s+--amend', 'Amend commit (history rewrite)'),
        (r'mv\s+', 'File move/rename'),
        (r'cp\s+-r', 'Recursive copy'),
        (r'chmod\s+', 'Permission change'),
        (r'chown\s+', 'Ownership change'),
        (r'kill\s+', 'Process kill'),
        (r'pkill\s+', 'Process kill by name'),
        (r'killall\s+', 'Kill all by name'),
        (r'pip\s+install|npm\s+install|yarn\s+add|cargo\s+add', 'Package installation'),
        (r'apt\s+install|yum\s+install|dnf\s+install|pacman\s+-S', 'System package install'),
        (r'make\s+', 'Build execution'),
        (r'python\s+-m\s+pip', 'Pip module install'),
        (r'npm\s+run|yarn\s+run|pnpm\s+run', 'Script execution'),
        (r'docker\s+', 'Docker command'),
        (r'kubectl\s+', 'Kubernetes command'),
        (r'terraform\s+(apply|destroy|plan)', 'Terraform apply/destroy'),
        (r'ansible-playbook', 'Ansible playbook'),
    ]
    
    def __init__(
        self,
        workspace_root: str,
        shell: Optional[str] = None,
        cwd: Optional[str] = None,
        on_output: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize a terminal session.
        
        Args:
            workspace_root: Root directory that all paths are confined to
            shell: Shell to use (auto-detected if None)
            cwd: Initial working directory (defaults to workspace_root)
            on_output: Callback for stdout streaming
            on_error: Callback for stderr streaming
        """
        self.workspace_root = Path(workspace_root).resolve()
        self.on_output = on_output or (lambda x: on_stdout_write(x))
        self.on_error = on_error or (lambda x: on_stdout_write(x, Fore.RED))
        
        # Determine shell
        if shell:
            self.shell = shell
        elif sys.platform == "win32":
            self.shell = os.environ.get("COMSPEC", "cmd.exe")
        else:
            self.shell = os.environ.get("SHELL", "/bin/bash")
        
        # Working directory
        self.cwd = Path(cwd or workspace_root).resolve()
        if not self._is_within_workspace(self.cwd):
            self.cwd = self.workspace_root
        
        # PTY/process state
        self._process: Optional[subprocess.Popen] = None
        self._pty_fd: Optional[int] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Background processes
        self._background_processes: Dict[int, BackgroundProcess] = {}
        self._bg_lock = threading.Lock()
        
        # Command history for audit log
        self._command_history: List[Dict[str, Any]] = []
        
        # Initialize session
        self._start_session()
    
    def _is_within_workspace(self, path: Path) -> bool:
        """Check if path is within workspace_root (symlink-aware)."""
        try:
            resolved = path.resolve()
            return resolved.is_relative_to(self.workspace_root)
        except (ValueError, OSError):
            return False
    
    def resolve_in_workspace(self, path: str) -> Path:
        """Resolve a path relative to cwd, ensuring it's within workspace_root."""
        p = Path(path)
        if not p.is_absolute():
            p = (self.cwd / p).resolve()
        else:
            p = p.resolve()
        
        if not self._is_within_workspace(p):
            raise PermissionError(f"Path '{path}' escapes workspace root: {self.workspace_root}")
        return p
    
    def _classify_risk(self, command: str) -> RiskTier:
        """Classify command risk tier."""
        cmd_lower = command.lower().strip()
        
        # Check denylist first
        for denied in self.DENYLIST:
            if denied in cmd_lower:
                return RiskTier.BLOCKED
        
        # Check high risk patterns
        for pattern, desc in self.HIGH_RISK_PATTERNS:
            import re
            if re.search(pattern, cmd_lower):
                return RiskTier.HIGH
        
        # Check medium risk patterns
        for pattern, desc in self.MEDIUM_RISK_PATTERNS:
            import re
            if re.search(pattern, cmd_lower):
                return RiskTier.MEDIUM
        
        return RiskTier.LOW
    
    def _pre_validate(self, command: str) -> Tuple[bool, str]:
        """Pre-execution syntax validation."""
        # Skip validation for shell built-ins and simple commands
        if sys.platform == "win32":
            # Windows: basic check
            return True, ""
        
        # Unix: try bash -n for syntax check
        try:
            result = subprocess.run(
                ["bash", "-n", "-c", command],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return False, f"Syntax error: {result.stderr.strip()}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # bash not available or timeout, skip validation
        
        return True, ""
    
    def _start_session(self):
        """Start the persistent shell session."""
        if sys.platform == "win32":
            self._start_windows_session()
        else:
            self._start_unix_session()
    
    def _start_unix_session(self):
        """Start a Unix PTY session."""
        import pty
        
        # Create PTY
        master_fd, slave_fd = pty.openpty()
        
        # Set up terminal size
        winsize = struct.pack("HHHH", 24, 80, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
        
        # Start shell process
        env = os.environ.copy()
        env["TERM"] = "dumb"
        env["PS1"] = "$ "
        
        self._process = subprocess.Popen(
            [self.shell],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(self.cwd),
            env=env,
            start_new_session=True,  # New process group for signal handling
            close_fds=False,
        )
        
        os.close(slave_fd)
        self._pty_fd = master_fd
        
        # Make non-blocking
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()
        
        # Send initial newline to get prompt
        self._write_to_pty(b"\n")
    
    def _start_windows_session(self):
        """Start a Windows session (ConPTY or fallback)."""
        try:
            import winpty
            self._start_winpty_session()
        except ImportError:
            self._start_windows_fallback()
    
    def _start_winpty_session(self):
        """Start Windows session using winpty (ConPTY)."""
        import winpty
        
        # This is a simplified version - full winpty integration is complex
        # For now, fall back to subprocess
        self._start_windows_fallback()
    
    def _start_windows_fallback(self):
        """Start Windows session using subprocess with pipes."""
        self._process = subprocess.Popen(
            [self.shell],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.cwd),
            text=True,
            bufsize=1,
            env={**os.environ, "TERM": "dumb"},
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop_windows, daemon=True)
        self._reader_thread.start()
    
    def _read_loop(self):
        """Unix PTY read loop."""
        while self._running and self._process and self._process.poll() is None:
            try:
                ready, _, _ = select.select([self._pty_fd], [], [], 0.1)
                if ready:
                    data = os.read(self._pty_fd, 4096)
                    if data:
                        text = data.decode("utf-8", errors="replace")
                        self.on_output(text)
                    else:
                        break
            except (OSError, ValueError):
                break
    
    def _read_loop_windows(self):
        """Windows pipe read loop."""
        while self._running and self._process and self._process.poll() is None:
            try:
                # Read stdout
                if self._process.stdout:
                    line = self._process.stdout.readline()
                    if line:
                        self.on_output(line)
                    else:
                        break
            except (OSError, ValueError):
                break
    
    def _write_to_pty(self, data: bytes):
        """Write data to PTY (Unix) or stdin (Windows)."""
        if sys.platform == "win32":
            if self._process and self._process.stdin:
                try:
                    self._process.stdin.write(data.decode("utf-8"))
                    self._process.stdin.flush()
                except (OSError, ValueError):
                    pass
        else:
            if self._pty_fd is not None:
                try:
                    os.write(self._pty_fd, data)
                except OSError:
                    pass
    
    def run_command(
        self,
        command: str,
        timeout: Optional[int] = None,
        capture: bool = True,
        background: bool = False,
    ) -> CommandResult:
        """
        Run a command in the terminal session.
        
        Args:
            command: Command to execute
            timeout: Timeout in seconds (None for default)
            capture: Whether to capture output (for foreground)
            background: Run in background (returns immediately)
        
        Returns:
            CommandResult with output, return code, and risk tier
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        risk_tier = self._classify_risk(command)
        
        # Check denylist
        if risk_tier == RiskTier.BLOCKED:
            result = CommandResult(
                stderr=f"Command blocked by safety policy: {command}",
                returncode=-1,
                risk_tier=risk_tier,
            )
            self._log_command(command, result)
            return result
        
        # Pre-execution validation
        valid, error = self._pre_validate(command)
        if not valid:
            result = CommandResult(
                stderr=f"Pre-execution validation failed: {error}",
                returncode=-1,
                risk_tier=RiskTier.BLOCKED,
            )
            self._log_command(command, result)
            return result
        
        # Log high/medium risk commands prominently
        if risk_tier in (RiskTier.HIGH, RiskTier.MEDIUM):
            self.on_output(f"\n{Fore.YELLOW}⚠ {risk_tier.value.upper()} RISK COMMAND:{Style.RESET_ALL} {command}\n")
        
        if background:
            return self._run_background(command, timeout, risk_tier)
        else:
            return self._run_foreground(command, timeout, capture, risk_tier)
    
    def _run_foreground(
        self,
        command: str,
        timeout: int,
        capture: bool,
        risk_tier: RiskTier,
    ) -> CommandResult:
        """Run command in foreground, streaming output."""
        stdout_chunks = []
        stderr_chunks = []
        timed_out = False
        
        # Create a temporary capture mechanism
        original_on_output = self.on_output
        original_on_error = self.on_error
        
        def capture_output(text):
            if capture:
                stdout_chunks.append(text)
            original_on_output(text)
        
        def capture_error(text):
            if capture:
                stderr_chunks.append(text)
            original_on_error(text)
        
        if capture:
            self.on_output = capture_output
            self.on_error = capture_error
        
        try:
            # Send command to PTY
            self._write_to_pty((command + "\n").encode("utf-8"))
            
            # Wait for completion with timeout
            start_time = time.time()
            
            if sys.platform == "win32":
                # Windows fallback: use subprocess directly for foreground too
                return self._run_windows_foreground(command, timeout, capture, risk_tier)
            
            while self._running and self._process and self._process.poll() is None:
                if time.time() - start_time > timeout:
                    timed_out = True
                    self._kill_process_group()
                    break
                time.sleep(0.05)
            
            # Give time for final output
            time.sleep(0.1)
            
            returncode = self._process.returncode if self._process else -1
            
            result = CommandResult(
                stdout="".join(stdout_chunks),
                stderr="".join(stderr_chunks),
                returncode=returncode,
                risk_tier=risk_tier,
                timed_out=timed_out,
            )
            
            self._log_command(command, result)
            return result
        finally:
            # Restore original callbacks
            self.on_output = original_on_output
            self.on_error = original_on_error
    
    def _run_windows_foreground(
        self,
        command: str,
        timeout: int,
        capture: bool,
        risk_tier: RiskTier,
    ) -> CommandResult:
        """Run foreground command on Windows using subprocess."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=capture,
                text=True,
                timeout=timeout,
                cwd=str(self.cwd),
                env={**os.environ, "TERM": "dumb"},
            )
            cmd_result = CommandResult(
                stdout=result.stdout if capture else "",
                stderr=result.stderr if capture else "",
                returncode=result.returncode,
                risk_tier=risk_tier,
            )
            if capture and result.stdout:
                self.on_output(result.stdout)
            if capture and result.stderr:
                self.on_error(result.stderr)
            self._log_command(command, cmd_result)
            return cmd_result
        except subprocess.TimeoutExpired:
            cmd_result = CommandResult(
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                returncode=-1,
                risk_tier=risk_tier,
                timed_out=True,
            )
            self._log_command(command, cmd_result)
            return cmd_result
        except Exception as e:
            cmd_result = CommandResult(
                stdout="",
                stderr=str(e),
                returncode=-1,
                risk_tier=risk_tier,
            )
            self._log_command(command, cmd_result)
            return cmd_result
    
    def _run_background(
        self,
        command: str,
        timeout: int,
        risk_tier: RiskTier,
    ) -> CommandResult:
        """Start a background process."""
        if sys.platform == "win32":
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=str(self.cwd),
                env={**os.environ, "TERM": "dumb"},
            )
        else:
            # Use the existing PTY session for background? No, spawn new process
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=str(self.cwd),
                start_new_session=True,
                env={**os.environ, "TERM": "dumb"},
            )
        
        bg_proc = BackgroundProcess(
            pid=proc.pid,
            command=command,
            process=proc,
        )
        
        # Start reader threads
        bg_proc.stdout_thread = threading.Thread(
            target=self._bg_read_stdout, args=(bg_proc,), daemon=True
        )
        bg_proc.stderr_thread = threading.Thread(
            target=self._bg_read_stderr, args=(bg_proc,), daemon=True
        )
        bg_proc.stdout_thread.start()
        bg_proc.stderr_thread.start()
        
        with self._bg_lock:
            self._background_processes[proc.pid] = bg_proc
        
        result = CommandResult(
            stdout=f"Background process started (PID: {proc.pid})",
            stderr="",
            returncode=0,
            risk_tier=risk_tier,
        )
        self._log_command(command, result)
        return result
    
    def _bg_read_stdout(self, bg_proc: BackgroundProcess):
        """Background stdout reader."""
        try:
            for line in iter(bg_proc.process.stdout.readline, ''):
                if not line:
                    break
                bg_proc.stdout_buffer.append(line)
                # Truncate if too large
                if len("".join(bg_proc.stdout_buffer)) > self.MAX_OUTPUT_SIZE:
                    bg_proc.stdout_buffer = ["...[output truncated]..."]
                    break
        except Exception:
            pass
    
    def _bg_read_stderr(self, bg_proc: BackgroundProcess):
        """Background stderr reader."""
        try:
            for line in iter(bg_proc.process.stderr.readline, ''):
                if not line:
                    break
                bg_proc.stderr_buffer.append(line)
                if len("".join(bg_proc.stderr_buffer)) > self.MAX_OUTPUT_SIZE:
                    bg_proc.stderr_buffer = ["...[output truncated]..."]
                    break
        except Exception:
            pass
    
    def read_process_output(self, pid: int, stream: str = "stdout") -> Tuple[str, bool]:
        """Read output from a background process."""
        with self._bg_lock:
            bg_proc = self._background_processes.get(pid)
        
        if not bg_proc:
            return "", True  # Not found, treat as finished
        
        if stream == "stdout":
            output = "".join(bg_proc.stdout_buffer)
            bg_proc.stdout_buffer.clear()
            finished = bg_proc.finished
        else:
            output = "".join(bg_proc.stderr_buffer)
            bg_proc.stderr_buffer.clear()
            finished = bg_proc.finished
        
        # Check if process finished
        if not bg_proc.finished and bg_proc.process.poll() is not None:
            bg_proc.finished = True
            bg_proc.returncode = bg_proc.process.returncode
            finished = True
        
        return output, finished
    
    def send_process_input(self, pid: int, input_text: str) -> bool:
        """Send input to a background process."""
        with self._bg_lock:
            bg_proc = self._background_processes.get(pid)
        
        if not bg_proc or bg_proc.finished:
            return False
        
        try:
            if bg_proc.process.stdin:
                bg_proc.process.stdin.write(input_text)
                bg_proc.process.stdin.flush()
                return True
        except Exception:
            pass
        return False
    
    def stop_process(self, pid: int, force: bool = False) -> CommandResult:
        """Stop a background process."""
        with self._bg_lock:
            bg_proc = self._background_processes.get(pid)
        
        if not bg_proc:
            return CommandResult(stderr=f"No process with PID {pid}", returncode=-1)
        
        try:
            if sys.platform == "win32":
                if force:
                    bg_proc.process.kill()
                else:
                    bg_proc.process.terminate()
            else:
                if force:
                    os.killpg(os.getpgid(bg_proc.process.pid), signal.SIGKILL)
                else:
                    os.killpg(os.getpgid(bg_proc.process.pid), signal.SIGTERM)
            
            bg_proc.process.wait(timeout=5)
            bg_proc.finished = True
            bg_proc.returncode = bg_proc.process.returncode
            
            return CommandResult(
                stdout="Process stopped",
                stderr="",
                returncode=bg_proc.returncode or 0,
            )
        except Exception as e:
            return CommandResult(stderr=str(e), returncode=-1)
    
    def list_background_processes(self) -> List[Dict[str, Any]]:
        """List all background processes."""
        with self._bg_lock:
            result = []
            for pid, bg_proc in self._background_processes.items():
                # Update status
                if not bg_proc.finished and bg_proc.process.poll() is not None:
                    bg_proc.finished = True
                    bg_proc.returncode = bg_proc.process.returncode
                
                result.append({
                    "pid": pid,
                    "command": bg_proc.command,
                    "running": not bg_proc.finished,
                    "returncode": bg_proc.returncode,
                    "duration": time.time() - bg_proc.start_time,
                })
            return result
    
    def _kill_process_group(self):
        """Kill the main process group."""
        if self._process:
            try:
                if sys.platform == "win32":
                    self._process.kill()
                else:
                    os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                    time.sleep(0.5)
                    if self._process.poll() is None:
                        os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
            except Exception:
                pass
    
    def change_directory(self, path: str) -> bool:
        """Change working directory (confined to workspace)."""
        try:
            new_cwd = self.resolve_in_workspace(path)
            if new_cwd.is_dir():
                self.cwd = new_cwd
                # Send cd command to shell
                self._write_to_pty(f"cd {shlex.quote(str(new_cwd))}\n".encode("utf-8"))
                return True
        except PermissionError:
            pass
        return False
    
    def get_cwd(self) -> Path:
        """Get current working directory."""
        return self.cwd
    
    def _log_command(self, command: str, result: CommandResult):
        """Log command to audit history."""
        entry = {
            "timestamp": time.time(),
            "command": command,
            "cwd": str(self.cwd),
            "risk_tier": result.risk_tier.value,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "stdout_len": len(result.stdout),
            "stderr_len": len(result.stderr),
        }
        self._command_history.append(entry)
    
    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Get the command audit log."""
        return self._command_history.copy()
    
    def close(self):
        """Close the terminal session."""
        self._running = False
        self._kill_process_group()
        
        # Stop all background processes
        with self._bg_lock:
            for bg_proc in self._background_processes.values():
                try:
                    if sys.platform == "win32":
                        bg_proc.process.kill()
                    else:
                        os.killpg(os.getpgid(bg_proc.process.pid), signal.SIGTERM)
                except Exception:
                    pass
        
        if self._reader_thread:
            self._reader_thread.join(timeout=2)
        
        if self._pty_fd is not None:
            try:
                os.close(self._pty_fd)
            except Exception:
                pass
        
        self._pty_fd = None


# Global terminal session (for backward compatibility with file_ops.run_command)
_global_terminal: Optional[TerminalSession] = None
_global_terminal_workspace: Optional[str] = None


def get_global_terminal(workspace_root: Optional[str] = None) -> TerminalSession:
    """Get or create the global terminal session."""
    global _global_terminal, _global_terminal_workspace
    if workspace_root is None:
        workspace_root = os.getcwd()
    # Recreate if workspace_root changed
    if _global_terminal is None or _global_terminal_workspace != workspace_root:
        if _global_terminal:
            _global_terminal.stop()
        _global_terminal = TerminalSession(workspace_root)
        _global_terminal_workspace = workspace_root
    return _global_terminal


def run_command(command: str, workspace_root: Optional[str] = None) -> Tuple[str, str]:
    """Backward-compatible run_command using the terminal subsystem."""
    term = get_global_terminal(workspace_root)
    result = term.run_command(command)
    return result.stdout, result.stderr


def resolve_in_workspace(path: str, workspace_root: Optional[str] = None) -> Path:
    """Resolve a path within the workspace root."""
    term = get_global_terminal(workspace_root)
    return term.resolve_in_workspace(path)