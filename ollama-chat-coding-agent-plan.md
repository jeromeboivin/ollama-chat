# ollama-chat → CLI Coding Agent: Implementation Plan

**Scope:** CLI agent mode inside `ollama_chat.py` (aider-style), full autonomy (no per-action confirmation), full harness coverage (editing, navigation, sandboxing, planning). Git is *not* a dedicated subsystem — see §2. The agent runs as an **orchestrator + delegated coding sub-agents**, not one model doing everything — see §6.

---

## 1. What's already there (don't rebuild this)

| Capability | Module | Notes |
|---|---|---|
| Tool-calling loop, dual backend | `llm_core.py` | `ask_ollama_with_conversation`, `ask_openai_with_conversation`, `handle_tool_response` — already dispatches tool calls generically via `globals_fn`|
| Agentic sub-agent w/ iteration budget | `agent.py` | `Agent` class: `max_iterations`, `tools`, `thinking_model`, `ask_fn` injection. **`model` is already a parameter of `Agent.__init__`** — per-agent model selection is structurally possible today |
| Agent spawning helpers | `llm_core.py` | `create_new_agent_with_tools`, `instantiate_agent_with_tools_and_process_task` — generic sub-agent spawning already exists; §6 narrows this for coding |
| Filesystem + shell primitives | `file_ops.py` | `read_file`, `create_file`, `delete_file`, `run_command`, `expand_env_vars` |
| Tool registry / selection | `tools.py` | `get_available_tools`, `select_tools`, `select_tool_by_name`, `get_builtin_tool_names` |
| Plugin system | `plugin_manager.py` | Drop-in tool discovery — new tools don't need core changes to register |
| RAG / code search fallback | `vector_db.py`, `document_indexer.py` | ChromaDB-backed; usable for semantic doc/code search but not precise enough alone for code edits |
| Terminal UI | `terminal_ui.py` | prompt-toolkit, autocomplete, `command_catalog`; pygments already imported in `ollama_chat.py` for syntax highlighting |
| Non-interactive scripted mode | `run_helpers.py` | `--no-interactive`, stdin piping already supported |
| Conversation persistence | `conversation.py` | `save_conversation_to_file` |

This means the **hard part (agentic loop + dual-backend tool calling + sub-agent spawning + extensibility) is done**. The gap is coding-specific tools, a coding-oriented entry point, and — per this revision — narrowing the existing generic sub-agent mechanism into a fixed orchestrator/worker shape instead of a fully open-ended one.

## 2. What other coding agents converge on (research findings)

Before finalizing the toolset, I checked what mandatory tools recur across the coding-agent landscape: Anthropic's own **Claude Code** (via its official, current documentation — `code.claude.com/docs/en/tools-reference` — not the reverse-engineered/leaked source dumps that also turned up in search, which I deliberately didn't use), **Aider**, and the **SWE-agent / OpenHands** research line (the "Agent-Computer Interface" paper, NeurIPS 2024, plus the current OpenHands Agent SDK). Findings that shaped this plan:

1. **Git is universally *not* a dedicated tool.** Claude Code runs git through `Bash` (with special-cased exit-code handling for `git diff`/`git grep`). Aider and OpenHands/SWE-agent do the same. `git_ops.py` is dropped from this plan — git flows through the terminal tool like everything else (§5).
2. **File editing converges on exact string-replace for capable models**, but Aider's benchmarking shows weaker/smaller models do measurably better with whole-file rewrite, which matters here because ollama-chat runs whatever local Ollama model the user has.
3. **Terminal sessions are persistent and risk-classified**, not a stateless allow/deny call — OpenHands' `TerminalTool` is `tmux`-backed with LOW/MEDIUM/HIGH risk tagging; SWE-agent syntax-validates commands before running and auto-reverts edits that break parsing.
4. **Orchestrator/worker delegation is also convergent** (this revision's topic, §6): Claude Code's `Agent` tool spawns a subagent that "works through its task autonomously, then returns a single text result to the parent conversation — the parent doesn't see the subagent's intermediate tool calls." Its documented usage pattern is explicitly *plan → delegate → integrate*: write a todo list, launch a subagent to explore/execute a scoped piece, fold the result back in. Claude Code also ships a `ReportFindings` tool specifically for review-type subagents to return structured findings (file, summary, failure scenario) instead of prose. Aider has the same split under a different name: **architect mode**, where a reasoning model proposes the change and a separate, often smaller, "editor" model performs the actual file edit — the reasoning model never touches files directly. That's precisely the shape you're asking for.

## 3. What's missing

1. **Precise file editing** — `create_file` implies whole-file overwrite; no `edit_file`/patch-apply tool, and no model-capability fallback (see §2.2).
2. **Code navigation** — no `list_directory`, `glob`, or `search_code` (grep-equivalent) tools.
3. **A real, cross-platform, persistent terminal subsystem** — the biggest structural gap. What exists today (inferred from the import list — I haven't seen `file_ops.py`'s actual body, so this should be the first thing audited in Phase 1) is a one-shot subprocess call using the OS default shell, with no persistent state and no way to interact with a running process.
4. **Planning/todo tracking** — no tool for the agent to externalize a multi-step plan.
5. **A fixed orchestrator/worker shape for the existing sub-agent mechanism** — `create_new_agent_with_tools`/`instantiate_agent_with_tools_and_process_task` already exist and already support per-agent tool lists, but they're a fully generic facade: whatever calls them has to author a system prompt, pick a tool list, and (probably) doesn't get to pick a *different model* for the sub-agent without extending the current facade. For "big model plans, small model codes" this needs two purpose-built, narrow entry points instead of the generic one — see §6.
6. **A coding-agent entry point** — no `--code-task` flag or `/code` slash command; no coding-specialized system prompt/chatbot profile.

## 4. Full autonomy → safety design (not a confirmation gate)

You've chosen no per-action confirmation and no dedicated git tool. That raises the bar on what has to be true *before* an action runs, and on recoverability *after*:

- **Workspace root confinement**: every path-touching tool resolves against a configured `workspace_root` and rejects paths that escape it (symlink-aware). This is a hard boundary, not a prompt.
- **Auto-checkpointing via the terminal tool itself**: the coding-agent system prompt instructs the model to run `git commit --no-verify -m "agent: <summary>"` through `run_command` after mutating changes, backed by a fallback hook in `agent.py` in case it forgets.
- **Risk-classified commands, not just a denylist**: `run_command` classifies each command LOW/MEDIUM/HIGH (deletion, force-push, `sudo`, network calls, disk operations → HIGH). HIGH-risk commands still run under full autonomy, but get a distinct, prominent line in the audit log. A small hard denylist still rejects outright regardless of tier.
- **Pre-execution validation**: a cheap syntax check (`bash -n`/PowerShell equivalent) before running a command.
- **Post-edit syntax check + auto-revert**: after `edit_file`/`apply_patch`, run a fast language-appropriate check and revert automatically if it breaks parsing — matters more here than in a human-reviewed tool because a coding *worker* sub-agent's output otherwise only gets checked by another model (§6), not a person.
- **Timeouts + output caps**: every `run_command` call gets a default timeout and truncates stdout/stderr past a size limit.
- **Structured audit log**: log every tool call — including every delegation — its arguments, risk tier, and diff/result.

## 5. New/changed modules

### `ollama_chat_lib/code_tools.py` (new)
- `list_directory(path, recursive=False, respect_gitignore=True)`, `glob_files(pattern, root=None, max_results=100)`, `search_code(pattern, path=None, regex=True, max_results=200)` (ripgrep if on PATH, else Python `re` walk).
- `edit_file(path, old_str, new_str, expect_unique=True, replace_all=False)` — modeled on Claude Code's `Edit`: unique-match enforcement, post-edit syntax check, returns a unified diff.
- **Model-capability fallback**: track per-session `edit_file` match-failure streaks for the active model; after N consecutive failures, switch that session's guidance toward whole-file `create_file` rewrites instead — local equivalent of Aider's per-model edit-format selection. This matters most for **coding worker sub-agents**, since those are the ones most likely to run a deliberately smaller/cheaper model (§6).
- `apply_patch(path, unified_diff)` — optional secondary tool for larger multi-hunk changes.
- Keep `create_file`/`delete_file` for genuinely new/removed files and as the fallback path above.

### `ollama_chat_lib/terminal.py` (new)
The cross-platform, persistent, risk-aware terminal subsystem.
- **`TerminalSession`**: Windows via `pywinpty`/ConPTY (PowerShell default, `cmd.exe` configurable); Unix via `libtmux` or the stdlib `pty`/`ptyprocess`; `subprocess.Popen` fallback with no PTY available. One session per *agent instance* — see §6 for what that means when sub-agents are involved.
- Tool surface: `run_command`, `start_background_process`, `read_process_output`, `send_process_input`, `stop_process` — all risk-classified and pre-validated per §4.
- Streaming via existing `io_hooks.on_stdout_write`/`on_stdout_flush`. UTF-8 decoding consistent with `ollama_chat.py`'s existing Windows stdout handling. `--shell` CLI flag.
- Safety chokepoint: workspace-root confinement, denylist, risk classification all live here — every execution path, including git, routes through this module.

### `ollama_chat_lib/planning.py` (new)
- `TodoStore` (in-memory, attached to `state`): `todo_write(items)`, `todo_update(id, status)`, `todo_read()`. **This is the orchestrator's primary tool** (§6) — it plans by writing/updating the todo list, not by writing code.
- Rendered into the terminal UI as a checklist.

### `ollama_chat_lib/file_ops.py` (refactor)
- `run_command` moves to `terminal.py`, thin backward-compatible wrapper kept.
- `read_file`/`create_file`/`delete_file` gain workspace-root confinement via a shared `resolve_in_workspace(path)` helper.

### `ollama_chat_lib/agent.py` (extend, don't fork)
- Add `workspace_root` param to `Agent.__init__`.
- Add loop/stall detection: same `(tool_name, args)` repeating N times without state change → break early.
- Add the fallback-commit hook from §4.
- **§6's actual work happens here and in `llm_core.py`** — see below.

### `ollama_chat_lib/conversation.py` (extend)
- Add a `"coding orchestrator"` entry to `DEFAULT_CHATBOTS` — this *is* the top-level agent the user talks to. Its system prompt states the workspace root, instructs it to plan with `todo_write`, delegate implementation and review work rather than edit files or run commands itself, and integrate results.
- Support an optional per-project `AGENTS.md` convention appended to the system prompt automatically.

## 6. Orchestrator / worker sub-agent architecture

This is the core change requested here: **one big/smart model plans and delegates; it never edits files or runs commands directly.** Small, cheap, tightly-scoped sub-agents do the actual coding and reviewing.

### Why this needs narrowing, not new plumbing
`create_new_agent_with_tools` and `instantiate_agent_with_tools_and_process_task` already do sub-agent spawning with a per-agent tool list, and `Agent.__init__` already accepts a `model` parameter — the underlying capability is there. What's missing is that the generic facade makes the *caller* (i.e., the orchestrator model, via a tool call) responsible for authoring a system prompt, choosing a tool list, and — this needs verifying/extending, since I haven't seen `_create_new_agent_with_tools`'s body — for actually being able to pick a **different model** than the parent's. That's too much surface for a model to reliably drive well, especially a model that might itself be running locally on modest hardware. The fix is two narrow, opinionated tools instead of the generic API.

### Two new facade functions (in `llm_core.py`, alongside the existing ones)
- **`delegate_coding_task(task_description, target_paths, context=None, model=None)`**
  Spawns a worker `Agent` with: the full coding toolset (`edit_file`, `create_file`, `delete_file`, `apply_patch`, `run_command`, `read_file`, `search_code`) but *no* `todo_write`/delegation tools — a worker never re-delegates; a fixed, small `max_iterations` (e.g. 6–8, configurable); `workspace_root` optionally narrowed to `target_paths` if you want an extra blast-radius reducer (worth doing, cheap to add given confinement already exists); and `model` defaulting to a configured **worker model** distinct from the orchestrator's, per `--worker-model` (§7). Returns a **structured result**, not a transcript: `{status: "success"|"failure", files_changed: [...], diff_summary, test_output, notes}`. Mirrors Claude Code's Agent tool behavior directly: the orchestrator never sees the worker's intermediate tool calls, only this final structured result — keeps the orchestrator's context small regardless of how much exploration the worker did.
- **`delegate_code_review(target_paths, review_focus=None, model=None)`**
  Spawns a *read-only* `Agent`: `read_file`, `search_code`, `run_command` restricted to test/lint/typecheck commands only (no edits, no arbitrary shell). Returns a structured findings list — `{approved: bool, findings: [{file, summary, severity}]}` — deliberately modeled on Claude Code's `ReportFindings` tool, which exists for exactly this "review subagent reports structured findings instead of prose" case. `model` defaults to a configured **review model** (can equal the worker model, or be a third option — e.g. reviewing with a *different* model than the one that wrote the code catches a different class of mistakes).

### Tool-list split (in `tools.py`)
- `get_orchestrator_tool_names()` → `read_file`, `list_directory`, `glob_files`, `search_code`, `todo_write`, `todo_read`, `delegate_coding_task`, `delegate_code_review`. **No `edit_file`, `create_file`, `delete_file`, `apply_patch`, or `run_command`.** This is the important part: the "don't code yourself" instruction is enforced by tool *availability*, not just prompt wording — much more reliable, since the orchestrator physically cannot call a tool it doesn't have.
- `get_coding_worker_tool_names()` → the full editing/execution toolset from earlier in this plan, used only by delegated workers.
- `get_review_tool_names()` → read-only subset, used only by delegated reviewers.

### Orchestration loop (what the `"coding orchestrator"` chatbot's system prompt encodes)
1. Break the task into a todo list (`todo_write`).
2. For each item: `delegate_coding_task` with a tightly scoped description and the specific file(s)/path(s) in play — not the whole repo context, just what that item needs.
3. On a worker `failure` result, either re-delegate with the failure notes as added context, or (if it keeps failing) mark the todo item blocked and surface it rather than looping indefinitely — this is where the loop/stall detection in `agent.py` (§4/§5) also applies at the orchestration level, not just inside one agent's tool-call loop.
4. Optionally `delegate_code_review` before marking an item done, especially for anything touching more than one file.
5. Update the todo list, move to the next item, and commit (per §4) once a coherent unit of work lands.
6. Report a summary back to the user at the end — not a replay of every worker's internal steps.

### Execution model
Sub-agents run **in-process and sequentially by default** — same Python process, one worker at a time, context isolation coming from each worker getting its own fresh conversation/system prompt rather than OS-level process separation. This is deliberately the simple option for v1. Parallel fan-out (spawning several independent `delegate_coding_task` calls for unrelated todo items at once) is a reasonable v2 addition once the sequential path is solid, but adds real complexity (concurrent writes to the same working tree, interleaved terminal sessions) that isn't worth taking on before the basic shape works.

## 7. CLI / entry-point wiring (`run_helpers.py`, `ollama_chat.py`)

- New flags: `--code-task "<description>"`, `--workspace <path>`, `--test-command "<cmd>"`, `--shell <powershell|cmd|bash|zsh|sh>`, `--max-iterations <n>` (orchestrator budget).
- **`--worker-model <name>`** (defaults to `--model` if unset) and **`--review-model <name>`** (defaults to `--worker-model` if unset) — this is the knob that makes "smart big orchestrator, cheap small workers" actually configurable, e.g. `--model llama3.1:70b --worker-model qwen2.5-coder:7b`.
- New slash command `/code <task>` — switches to the `"coding orchestrator"` chatbot, pre-selects `get_orchestrator_tool_names()`, sets `workspace_root`, starts the loop.
- `--code-task` + `--no-interactive` for the scripted/CI path.

## 8. Observability & tests

- Extend the audit log into a lightweight `--replay-session <file>` that also distinguishes orchestrator turns from delegated-worker turns and delegated-review turns, so a session review reads as a plan/delegate/integrate trace, not one flat tool-call list.
- `tests/`: coverage for `edit_file`/workspace confinement/`terminal.py` risk classification as before, **plus**: `delegate_coding_task` returns the structured result contract (not a transcript), the orchestrator's tool list genuinely excludes editing/execution tools, a worker's `target_paths` scoping is enforced, and an end-to-end test where the orchestrator plans a two-step change, delegates both steps, and integrates the result.

## 9. Suggested phasing

1. **Terminal subsystem + foundations** — audit current `run_command`, build `terminal.py` (cross-platform PTY/tmux, persistent state, streaming, background processes, risk classification), `resolve_in_workspace`, workspace-root confinement.
2. **Editing & navigation** — `edit_file` (with model-fallback tracking, post-edit syntax check), `apply_patch`, `list_directory`, `glob_files`, `search_code`.
3. **Checkpointing + planning** — git-commit system-prompt convention + fallback hook, `planning.py`, `--replay-session`/audit log.
4. **Orchestrator/worker split** — audit `_create_new_agent_with_tools`'s current model-selection behavior first (confirm whether per-agent model is already wired through or needs extending), then `delegate_coding_task`/`delegate_code_review` in `llm_core.py`, the three tool-list profiles in `tools.py`, and the `"coding orchestrator"` chatbot entry with its plan/delegate/integrate system prompt.
5. **CLI wiring** — `--code-task`, `--workspace`, `--worker-model`, `--review-model`, `--test-command`, `--shell`, `/code`.
6. **Tests & docs** — unit + end-to-end coverage including the orchestrator/worker split, Windows + Unix matrix for `terminal.py`, README section.

Phase 1 remains the hard dependency for everything after it. Phase 4 depends on 2 and 3 (workers need the editing tools and the checkpointing convention to exist first) but is otherwise the most architecturally significant phase in this revision — worth its own review pass before wiring it into the CLI in phase 5.

## 10. Note

This is structurally similar to the patterns already in your Rust `agent-core`/`agent-cli` work (sub-agent orchestration, JSONL/session persistence, scriptable output) — worth keeping the tool-call audit log format, the todo-list schema, and now the orchestrator/worker split itself consistent across both projects if you want to eventually share tooling or documentation between them.
