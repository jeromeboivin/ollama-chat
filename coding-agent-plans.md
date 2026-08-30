The original plan is architecturally sound, but several phases are still too large for a small coding model: for example, “Terminal subsystem + foundations” combines PTY handling, persistence, streaming, risk classification, and workspace security. I would split it into **15 atomic implementation plans**.

The decomposition below preserves the original architecture and terminology. 

# Recommended execution order

```text
P01 → P02 → P03 → P04
              ↓
              P05 → P06 → P07
                            ↓
                     P08 → P09 → P10
                                  ↓
                           P11 → P12 → P13
                                          ↓
                                   P14 → P15
```

The important principle is that **each plan can be handed to a coding agent as a standalone task**. The agent should not need to understand the entire roadmap.

---

# P01 — Audit existing command execution

### Goal

Understand the current `run_command` implementation before modifying it.

### Files to inspect

* `ollama_chat_lib/file_ops.py`
* `ollama_chat_lib/agent.py`
* `ollama_chat.py`
* `ollama_chat_lib/io_hooks.py`
* relevant tests

### Tasks

1. Find the current implementation of `run_command`.
2. Document:

   * shell selection
   * subprocess handling
   * stdout/stderr handling
   * timeout behavior
   * return-value structure
   * error handling
3. Find every caller of `run_command`.
4. Determine whether moving it to `terminal.py` will break existing APIs.
5. Inspect the existing agent execution loop to understand how tool errors are propagated.
6. Add tests for the current behavior where coverage is missing.

### Constraints

Do **not** redesign command execution yet.

### Acceptance criteria

* Current implementation is documented in code comments or developer documentation.
* All callers of `run_command` are identified.
* Existing behavior has regression tests.
* No existing functionality is intentionally changed.

### Dependency

None.

---

# P02 — Add workspace path confinement

### Goal

Create the common security primitive that prevents coding-agent tools from accessing files outside the workspace.

### Files

Primarily:

* `ollama_chat_lib/file_ops.py`
* new tests

### Tasks

Implement:

```python
resolve_in_workspace(path, workspace_root)
```

The function must:

1. Resolve relative paths against `workspace_root`.
2. Resolve `..`.
3. Resolve symlinks where possible.
4. Reject paths that escape the workspace.
5. Return a canonical absolute path.
6. Produce a clear exception when access is rejected.

Update:

* `read_file`
* `create_file`
* `delete_file`

to use it.

### Acceptance criteria

These cases must work correctly:

```text
workspace/file.py             → allowed
workspace/src/file.py        → allowed
workspace/../outside.txt     → rejected
/tmp/outside.txt             → rejected
symlink-inside → outside     → rejected
```

Existing callers without an explicit workspace should remain backward compatible according to the current application behavior.

### Dependency

P01.

---

# P03 — Create the basic TerminalSession

### Goal

Introduce `terminal.py` with a persistent shell session, initially without advanced risk/security logic.

### File

Create:

```text
ollama_chat_lib/terminal.py
```

### Tasks

Implement:

```python
class TerminalSession:
    start()
    run_command(command)
    close()
```

Requirements:

* persistent working directory
* environment persistence
* stdout/stderr capture
* timeout
* non-zero exit codes represented explicitly
* Windows support
* Unix support

Use the simplest implementation that works reliably on the supported platforms.

### Important

Do **not** implement:

* background processes
* risk classification
* audit logging
* complex PTY behavior

yet.

### Acceptance criteria

This sequence must work:

```text
pwd
cd subdirectory
pwd
```

The second `pwd` must reflect the changed directory.

A command timeout must terminate cleanly and return a structured timeout result.

### Dependency

P02.

---

# P04 — Move `run_command` to TerminalSession

### Goal

Make `terminal.py` the canonical command-execution implementation.

### Tasks

1. Move the execution logic from `file_ops.py` into `terminal.py`.
2. Keep a compatibility wrapper in `file_ops.py`:

```python
run_command(...)
```

3. Make the wrapper delegate to `TerminalSession`.
4. Update relevant imports.
5. Preserve existing return semantics where possible.

### Acceptance criteria

* Existing callers continue to work.
* New code uses `terminal.py`.
* No duplicate command-execution implementation remains.
* Existing tests remain green.

### Dependency

P03.

---

# P05 — Add terminal background processes

### Goal

Allow the coding agent to start and interact with long-running processes.

### Files

`ollama_chat_lib/terminal.py`

### Implement

```python
start_background_process(command)
read_process_output(process_id)
send_process_input(process_id, input)
stop_process(process_id)
```

### Requirements

Each process should have:

```text
process_id
command
status
started_at
exit_code
```

Support:

* starting a process
* reading accumulated output
* sending stdin
* stopping the process
* detecting process completion

### Acceptance criteria

A test can:

1. start a long-running process,
2. read its output,
3. send input,
4. stop it,
5. verify termination.

### Dependency

P04.

---

# P06 — Add command risk classification

### Goal

Classify terminal commands without blocking them.

### File

`ollama_chat_lib/terminal.py`

### Implement

```python
class CommandRisk(Enum):
    LOW
    MEDIUM
    HIGH

class CommandAssessment:
    risk
    reasons
    command
```

Detect examples such as:

### HIGH

* `sudo`
* destructive deletion
* `rm -rf`
* force push
* disk operations
* broad network operations

### MEDIUM

* package installation
* service modification
* dependency changes

### LOW

* `git status`
* `git diff`
* `pytest`
* `npm test`
* reading files

### Important

Risk classification is for **logging/visibility**, not confirmation.

The original design explicitly requires full autonomy while making HIGH-risk actions visible in the audit trail. 

### Acceptance criteria

Every command receives exactly one risk level and a reason list.

Unknown commands must default conservatively rather than silently becoming LOW risk.

### Dependency

P05.

---

# P07 — Add terminal validation, limits, and audit events

### Goal

Make command execution observable and bounded.

### Tasks

Add:

* pre-execution validation
* command timeout
* output-size limits
* structured execution result
* audit event generation

A result should contain something like:

```python
{
    "command": "...",
    "exit_code": 0,
    "stdout": "...",
    "stderr": "...",
    "timed_out": False,
    "risk": "LOW"
}
```

Audit events should capture:

```text
timestamp
agent_id
tool
arguments
risk
result
```

### Acceptance criteria

* oversized output is truncated
* timeout is recorded
* risk classification is recorded
* failures are recorded
* no secret values are deliberately written into audit logs

### Dependency

P06.

---

# P08 — Implement code navigation tools

### Goal

Add read/navigation tools needed by the orchestrator and workers.

### New file

```text
ollama_chat_lib/code_tools.py
```

### Implement

```python
list_directory(...)
glob_files(...)
search_code(...)
```

### Requirements

`list_directory`

* non-recursive by default
* optional recursive mode
* sensible hidden/generated-file handling

`glob_files`

* root directory support
* result limit
* deterministic ordering

`search_code`

* regex support
* result limit
* preferably use `ripgrep`
* Python fallback when unavailable

### Acceptance criteria

All three tools:

* obey workspace confinement
* have bounded results
* return structured results
* work on Windows and Unix

### Dependency

P02.

---

# P09 — Implement `edit_file`

### Goal

Create precise string-based file editing.

### Implement

```python
edit_file(
    path,
    old_str,
    new_str,
    expect_unique=True,
    replace_all=False
)
```

### Behavior

If:

```text
old_str
```

does not exist:

→ return structured failure.

If it occurs multiple times and:

```text
expect_unique=True
```

→ fail without modifying the file.

If successful:

→ modify file and return unified diff.

### Also implement

Post-edit syntax validation for supported languages.

At minimum, make the architecture extensible rather than hard-coding one language.

### Acceptance criteria

* unique replacement works
* missing replacement fails
* duplicate replacement fails when uniqueness is required
* `replace_all=True` works
* returned diff is correct
* invalid syntax causes automatic revert

The original plan explicitly requires post-edit validation and automatic revert. 

### Dependency

P02, P08.

---

# P10 — Add patching and edit-model fallback

### Goal

Support larger edits and make editing resilient to weaker models.

### Implement

```python
apply_patch(path, unified_diff)
```

and a per-session edit failure tracker.

### Fallback behavior

Track:

```text
active model
edit failures
```

After N consecutive `edit_file` failures:

```text
normal edit guidance
        ↓
whole-file rewrite guidance
```

Do not automatically rewrite files inside the tool itself. The mechanism should change the guidance/strategy available to the model.

### Acceptance criteria

* unified patches can be applied
* malformed patches fail safely
* edits are reverted when validation fails
* failure count resets after successful editing
* fallback threshold is configurable

### Dependency

P09.

---

# P11 — Add TodoStore

### Goal

Create lightweight planning state for the orchestrator.

### New file

```text
ollama_chat_lib/planning.py
```

### Implement

```python
TodoStore
    todo_write(items)
    todo_update(id, status)
    todo_read()
```

Suggested item structure:

```python
{
    "id": "...",
    "description": "...",
    "status": "pending|in_progress|completed|blocked"
}
```

### Requirements

* in-memory
* attached to agent state
* deterministic
* safe if an item ID does not exist
* terminal UI can render it

### Acceptance criteria

The agent can:

```text
write todo list
read todo list
mark item in progress
mark item completed
mark item blocked
```

### Dependency

None.

---

# P12 — Add agent execution protections

### Goal

Extend `Agent` without changing its overall architecture.

### File

```text
ollama_chat_lib/agent.py
```

### Implement

1. `workspace_root` constructor parameter.
2. Repeated-tool-call detection.
3. Stall detection.
4. Structured termination reason.
5. Optional fallback checkpoint hook.

Example stall:

```text
same tool
same arguments
no state change
```

repeated N times.

### Acceptance criteria

An agent stuck in a loop eventually terminates.

Termination tells the caller why:

```text
max_iterations
stall_detected
tool_failure
completed
```

### Dependency

P02, P07.

---

# P13 — Implement orchestrator/worker delegation

### Goal

Implement the central architecture: one orchestrator delegates work to coding workers.

This should be treated as **one plan**, not mixed together with the CLI work.

The original design calls for two narrow entry points: `delegate_coding_task` and `delegate_code_review`. 

### Step 1 — Verify existing sub-agent machinery

Inspect:

```text
create_new_agent_with_tools
instantiate_agent_with_tools_and_process_task
_create_new_agent_with_tools
Agent.__init__
```

Determine whether a different model can already be selected per worker.

### Step 2 — Implement

```python
delegate_coding_task(
    task_description,
    target_paths,
    context=None,
    model=None
)
```

Worker receives:

```text
edit_file
create_file
delete_file
apply_patch
run_command
read_file
search_code
```

Worker does **not** receive:

```text
todo_write
delegate_coding_task
delegate_code_review
```

### Step 3 — Implement

```python
delegate_code_review(
    target_paths,
    review_focus=None,
    model=None
)
```

Reviewer receives read-only tools.

### Structured worker result

```python
{
    "status": "success" | "failure",
    "files_changed": [...],
    "diff_summary": "...",
    "test_output": "...",
    "notes": "..."
}
```

### Structured review result

```python
{
    "approved": True,
    "findings": [
        {
            "file": "...",
            "summary": "...",
            "severity": "low|medium|high"
        }
    ]
}
```

### Acceptance criteria

The orchestrator sees only the structured result, not the worker's intermediate tool transcript.

Workers cannot delegate.

Reviewers cannot edit.

Worker model can differ from orchestrator model.

### Dependency

P07, P09, P10, P11, P12.

---

# P14 — Define tool profiles and coding orchestrator chatbot

### Goal

Wire the tools and system prompt into three explicit agent profiles.

### File

Primarily:

```text
ollama_chat_lib/tools.py
ollama_chat_lib/conversation.py
```

### Implement

```python
get_orchestrator_tool_names()
get_coding_worker_tool_names()
get_review_tool_names()
```

### Orchestrator tools

```text
read_file
list_directory
glob_files
search_code
todo_write
todo_read
delegate_coding_task
delegate_code_review
```

### Explicitly exclude

```text
edit_file
create_file
delete_file
apply_patch
run_command
```

### Coding worker

Gets editing + terminal tools.

### Reviewer

Gets read-only inspection + test/lint/typecheck execution.

### Add

```text
coding orchestrator
```

to `DEFAULT_CHATBOTS`.

Its behavior should be:

```text
plan
↓
delegate
↓
inspect result
↓
review
↓
update todo
↓
delegate next task
↓
summarize
```

The original specification explicitly makes tool availability—not merely prompt wording—the enforcement mechanism preventing the orchestrator from editing directly. 

### Also implement

Automatic optional loading of:

```text
AGENTS.md
```

from the project workspace.

### Acceptance criteria

The orchestrator literally has no editing or shell-execution tools.

A worker does.

A reviewer does not.

---

# P15 — Add CLI, session replay, tests, and documentation

### Goal

Expose the completed architecture as a usable CLI feature.

### CLI flags

Implement:

```text
--code-task
--workspace
--test-command
--shell
--max-iterations
--worker-model
--review-model
--replay-session
```

and:

```text
/code <task>
```

The original plan specifies the worker/reviewer model defaults as:

```text
worker-model → orchestrator model
review-model → worker model
```

unless explicitly configured otherwise. 

### Non-interactive mode

Support:

```text
--code-task "..." --no-interactive
```

### Replay

Extend the audit log so a session distinguishes:

```text
ORCHESTRATOR
WORKER
REVIEWER
```

rather than appearing as one flat sequence.

### Tests

Add:

* workspace confinement tests
* edit tests
* terminal tests
* background-process tests
* risk classification tests
* orchestrator tool-profile tests
* worker target-path tests
* structured delegation-result tests
* structured review-result tests
* model-selection tests
* end-to-end two-step orchestration test
* Windows/Unix terminal tests

### Documentation

Add a README section explaining:

```text
ollama-chat --code-task ...
```

and the orchestrator/worker model architecture.

### Acceptance criteria

A complete workflow can execute:

```text
user task
    ↓
orchestrator
    ↓
todo list
    ↓
coding worker
    ↓
review worker
    ↓
next task
    ↓
final summary
```

without the orchestrator directly editing files or executing shell commands.

---

# How I would give these to a small coding agent

I would **not** give the whole roadmap to the model.

Instead, each prompt should follow this structure:

```text
# Task

Implement P09 — edit_file.

## Objective

Add precise string-based file editing to ollama-chat.

## Files

- ollama_chat_lib/code_tools.py
- ollama_chat_lib/file_ops.py
- tests/...

## Requirements

[only the requirements for this task]

## Constraints

- Do not modify agent orchestration.
- Do not add CLI functionality.
- Do not modify unrelated modules.
- Preserve existing APIs.

## Acceptance criteria

[only the criteria for this task]

## Validation

Run the relevant tests.

## Completion

Return:
- files changed
- tests executed
- test results
- known limitations
```

That last part is particularly important for a small model: **the agent should be judged against a finite acceptance contract, not asked to “implement the phase.”**

---

# An even better split for very small models

If the coding model is particularly weak, I would split **P13** and **P15** further.

### P13a

Audit existing sub-agent model selection.

### P13b

Implement `delegate_coding_task`.

### P13c

Implement `delegate_code_review`.

### P13d

Implement worker target-path restrictions.

### P14a

Implement tool profiles.

### P14b

Add coding orchestrator chatbot.

### P14c

Add `AGENTS.md` loading.

### P15a

Add CLI flags.

### P15b

Add `/code`.

### P15c

Add replay-session.

### P15d

Add end-to-end tests.

That gives you roughly **25 very small coding tasks**, which is a much better fit for a lightweight local coding model.

## One architectural recommendation

I would also change the execution strategy slightly: **each plan should end with a clean repository state and tests passing before the next plan starts**. This matches the original checkpoint/recoverability intent while keeping each coding-agent context small. The original plan already calls for automatic checkpoints and structured audit information. 

This decomposition is therefore much more suitable for driving the implementation through a small local coding agent than the original six large phases.
