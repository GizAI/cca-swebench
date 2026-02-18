# CCA Harness & Workflow (Original Upstream + Current Fork)

This document is intentionally split into two parts:

- **Part A (Source of truth for original CCA):** behavior from upstream `facebookresearch/cca-swebench` (`origin/main`)
- **Part B (Fork delta):** what changed in this fork after unification

If you only care about original repository behavior, read **Part A only**.

---

## Part A. Original CCA Structure (Upstream `origin/main`)

## A1) What is the original execution surface?

In upstream, there is **no global `cca` command**.
The practical entrypoints are:

1. `scripts/run_swebench.py`
- one-shot run for SWE-bench style prompt file input (`--prompt` required)

2. `confucius` CLI group (`confucius/cli/main.py`)
- `confucius code` launches interactive REPL for `Code` entry

3. Docker entry workflow
- `scripts/run_sbp.sh` + packaged `app.pex` runtime in container mode

## A2) Original one-shot flow (`scripts/run_swebench.py`)

### Inputs
- required `--prompt <path>` (typically `.txt`)
- optional `--verbose`

### Steps
1. read prompt file text
2. wrap it into SWE-bench task template
3. call `run_agent_with_prompt(prompt, entry_name="Code")`

### Call chain

```text
scripts/run_swebench.py
  -> scripts/utils.py::run_agent_with_prompt
    -> Confucius.invoke_analect(Entry, EntryInput)
      -> Entry routes by entry_name="Code"
        -> CodeAssistEntry.impl
          -> AnthropicLLMOrchestrator loop
```

## A3) Original interactive flow (`confucius code`)

`confucius/cli/main.py`:
- creates `Confucius()`
- starts `run_entry_repl(cf, entry_name="Code")`
- handles Ctrl+C by first trying `cf.cancel_task()`

`confucius/lib/entry_repl.py`:
- 반복적으로 입력 받음
- 각 입력마다 `EntryInput(question, entry_name)` 호출
- 각 턴 종료 후 session state 저장

## A4) Original Code analect composition

Upstream `confucius/analects/code/entry.py` extension stack:

1. `LLMCodingArchitectExtension`
2. `FileEditExtension(enable_tool_use=True)`
3. `CommandLineExtension(enable_tool_use=True, allow_bash_script=True)`
4. `FunctionExtension(enable_tool_use=True)`
5. `PlainTextExtension`
6. `HierarchicalMemoryExtension`
7. `AnthropicPromptCaching`
8. `SoloModeExtension` (**always on in upstream**)

Model params in upstream:
- fixed preset `GPT5_2_THINKING`
- no `CCA_MODEL` runtime injection path in upstream code entry

## A5) Original task prompt contract

Upstream `confucius/analects/code/tasks.py` includes:
- understand request
- propose plan
- execute via tools
- minimal and safe changes
- use `str_replace_editor` for file view/edit

Notable upstream characteristics:
- does **not** inject current working directory into task template
- does not include explicit anti-intent-only rules now present in fork

## A6) Orchestrator runtime model (upstream core)

### Core loop
`confucius/orchestrator/base.py`:
- build root output
- process tags/plain text
- run `on_process_messages_complete`
- if interrupted, append interruption messages and recurse

### LLM orchestration
`confucius/orchestrator/llm.py`:
- memory -> lc messages -> prompt
- choose model through `LLMManager`
- extension hooks:
  - `on_invoke_llm`
  - `on_llm_response`
  - `on_llm_output`

### Tool-use queue
`confucius/orchestrator/anthropic.py`:
- parse response content
- queue tool calls
- execute tools
- append tool results into memory
- resume orchestration loop

## A7) Tool layer in upstream

### File tool
`FileEditExtension` + `str_replace_editor` commands:
- `view`, `create`, `str_replace`, `insert`, `undo_edit`

Operational details:
- `view` enforces line limit by `max_output_lines`
- missing file errors include current working directory hint
- directory view supports depth and hidden toggle

### Command tool
`CommandLineExtension` (`bash` tool):
- command allowlist + validators
- parse commands via `bashlex`
- run command in async subprocess shell
- truncate stdout/stderr by configured limits

Allowlist source for Code analect:
- `confucius/analects/code/commands.py`

## A8) LLM manager routing in upstream

`AutoLLMManager` chooses backend by model string:
- Claude -> Bedrock manager
- Gemini -> Google manager
- GPT/o-series/codex prefixes -> OpenAI manager
- Azure prefixes -> Azure manager

OpenAI path uses `OpenAIChat(..., use_responses_api=True)`.

## A9) State and persistence in upstream

`Confucius` persists each session to:
- `~/.confucius/sessions/<session>/memory`
- `~/.confucius/sessions/<session>/storage`
- `~/.confucius/sessions/<session>/artifacts`

Also dumps trajectory JSON to:
- `/tmp/confucius/traj_<session>.json`

## A10) Original architecture quick map

```text
[Entrypoints]
  scripts/run_swebench.py (one-shot)
  confucius code (REPL)

[Harness]
  confucius/lib/confucius.py
  confucius/core/entry/entry.py

[Code analect]
  confucius/analects/code/entry.py
  confucius/analects/code/tasks.py
  confucius/analects/code/commands.py

[Orchestrator]
  confucius/orchestrator/base.py
  confucius/orchestrator/llm.py
  confucius/orchestrator/anthropic.py

[Tools]
  file/edit: confucius/orchestrator/extensions/file/edit.py
  command:   confucius/orchestrator/extensions/command_line/base.py
```

---

## Part B. Fork Delta (What changed here)

This section is **not upstream behavior**, only fork changes.

## B1) Unified launcher introduced

- new: `scripts/cca.py`
- new: `scripts/provider_runtime.py`
- removed legacy split launchers:
  - `scripts/run_universal_agent.py`
  - `scripts/tui_stream.py`

## B2) Model/auth runtime added

- dynamic model discovery/listing/aliasing
- live model validation commands
- Codex OAuth auth ingestion from `~/.codex/auth.json`
- Gemini OAuth + Vertex env plumbing

## B3) Default execution behavior changes

- one command for TUI + one-shot
- prompt supports file/inline/stdin
- default Codex model selection prefers latest spark variant when available

## B4) Additional safeguards

- task template now includes current working directory
- intent-only response guard extension added
- solo mode toggle exposed (`auto/on/off`)

---

## Part C. Practical guidance

If you want to reason about original paper-style CCA harness design:
- trust **Part A** and upstream paths

If you are operating this fork in production shell usage:
- use Part B + current `scripts/cca.py` behavior

---

## Part D. Exact Change Inventory vs Upstream

Baseline used here:
- upstream: `origin/main` at `73d1b99`
- fork state: `HEAD` at `aa8c487`

Regenerate the exact list:

```bash
git diff --name-status origin/main..HEAD
```

### D1) Added files

| Status | Path | Purpose |
|---|---|---|
| `A` | `confucius/analects/code/intent_guard.py` | Guard extension for intent-only turn endings |
| `A` | `scripts/cca.py` | Unified launcher (TUI + one-shot + provider runtime wiring) |
| `A` | `scripts/provider_runtime.py` | Provider auth/model discovery/validation runtime |
| `A` | `tests/test_cca.py` | Unit tests for unified launcher behavior |
| `A` | `tests/test_cca_tui_e2e.py` | Real interactive TUI E2E test |
| `A` | `tests/test_intent_guard.py` | Guard behavior tests |
| `A` | `tests/test_provider_runtime.py` | Provider runtime/model selection tests |
| `A` | `tests/test_tasks.py` | Task template injection tests |

### D2) Modified files

| Status | Path | Change summary |
|---|---|---|
| `M` | `README.md` | Usage/runner/model/runtime documentation updates |
| `M` | `confucius/analects/code/entry.py` | Extension stack updates, env-based model/solo wiring |
| `M` | `confucius/analects/code/llm_params.py` | `CCA_MODEL`/preset-based dynamic model resolution |
| `M` | `confucius/analects/code/tasks.py` | Task rules/runtime context updates |
| `M` | `confucius/core/chat_models/azure/adapters/responses.py` | Codex backend-specific responses handling |
| `M` | `confucius/core/chat_models/bedrock/api/invoke_model/anthropic.py` | Text-editor path description update (workspace absolute path guidance) |
| `M` | `confucius/core/llm_manager/constants.py` | OpenAI model prefix support enabled (`gpt`, `o*`, `codex`) |
| `M` | `confucius/core/llm_manager/google.py` | Gemini OAuth runtime client support |
| `M` | `confucius/core/llm_manager/openai.py` | OpenAI base URL/default header/env-driven runtime support |
| `M` | `pyproject.toml` | `cca` console script and pytest marker config |

### D3) Notes

- This inventory is commit-based (`origin/main..HEAD`), so it is reproducible by git command.
- Any uncommitted local edits (for example additional docs after `HEAD`) are outside this exact inventory until committed.
