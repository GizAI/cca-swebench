# CCA-SWE-Bench: Agent Harness for SWE-bench

This repository contains a minimal but production-usable harness around Confucius Code Agent (CCA) for SWE-bench style coding tasks.

## Why this repo exists

The core design keeps the agent inside the target runtime instead of building a heavy host-to-container abstraction layer.

Benefits:
- simple execution path
- low latency tool calls
- fewer moving pieces when debugging
- easier extension of agent capabilities

Tradeoff:
- less platform abstraction compared with runtime-proxy frameworks

## What is in this repository

- `confucius/`: CCA framework core, orchestrators, extensions, IO, model managers
- `scripts/run_swebench.py`: reference one-shot runner for SWE-bench style tasks
- `scripts/cca.py`: unified runner (TUI + one-shot + provider runtime)
- `scripts/provider_runtime.py`: provider auth/model discovery/validation runtime
- `tests/`: unit and e2e tests for launcher/runtime behavior

## Execution Modes

### Reference CCA workflow
- Entry points:
  - `python -m scripts.run_swebench --prompt <file>`
  - `confucius code` (interactive REPL)
- Focus:
  - SWE-bench style execution with CCA harness extensions

### Unified `cca` workflow (recommended)
- Entry point:
  - `cca`
- Features:
  - one command for interactive TUI and one-shot execution
  - dynamic model discovery and alias resolution
  - live model ID validation
  - provider runtime setup from existing local OAuth sessions

For a full architecture and workflow reference, see:
- `docs/cca-harness-workflow.md`

## Quick Start (Recommended)

### 1) Install dependencies

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2) Install global `cca` command

```bash
python3 -m pip install --user -r requirements.txt
python3 -m pip install --user -e .
```

### 3) Run

```bash
cca
```

By default, `cca` enters interactive TUI mode when stdin is a TTY and no prompt is provided.

## Provider Authentication

### Codex provider

Use your existing Codex CLI login state:

```bash
codex login
```

`cca` reads:
- `~/.codex/auth.json`
- `~/.codex/models_cache.json`

It uses those credentials to call the Codex backend API via OpenAI SDK runtime settings.

### OpenAI provider

```bash
export OPENAI_API_KEY=...
```

### Gemini provider

Either:
- API key (`GOOGLE_API_KEY` or `GEMINI_API_KEY`)

Or OAuth flow with local creds:
- `~/.gemini/oauth_creds.json`

### Bedrock provider

```bash
export AWS_REGION=us-east-1
# plus normal AWS credentials/profile
```

## Common `cca` Usage

### Interactive TUI

```bash
cca
```

Or force TUI mode:

```bash
cca --tui
```

### One-shot with file prompt

```bash
cca --provider codex --prompt /path/to/problem.txt
```

### One-shot with inline text

```bash
cca --provider codex --prompt "Fix failing tests" --raw-prompt
```

### One-shot with stdin

```bash
echo "Fix failing tests" | cca --provider codex --raw-prompt
```

### Show resolved runtime only

```bash
cca --tui --dry-run
```

### Select provider/model explicitly

```bash
cca --provider codex --model gpt-5.3-codex-spark --tui
cca --provider openai --model gpt-5.2 --prompt "Update docs" --raw-prompt
cca --provider bedrock --model claude-sonnet-4-5 --prompt /path/to/task.txt
```

## Model discovery and validation

### List discovered models and aliases

```bash
cca --provider codex --list-models
cca --provider gemini --list-models
```

### Validate discovered model IDs with live API calls

```bash
cca --provider codex --validate-models-live
cca --provider gemini --validate-models-live
```

## `cca` mode behavior

Mode selection is automatic:
- TTY + no prompt -> TUI
- prompt provided -> one-shot
- piped stdin + no prompt -> one-shot

Solo mode defaults:
- one-shot: `on`
- TUI: `off`

Override:

```bash
cca --solo-mode on
cca --solo-mode off
```

## TUI commands

- `/help`
- `/model`
- `/exit`
- `/quit`

## Reference run paths

### One-shot SWE-bench style

```bash
.venv/bin/python -m scripts.run_swebench --prompt /path/to/problem.txt
```

### REPL

```bash
.venv/bin/python -m confucius.cli.main code
```

## Testing

### Unit and behavior tests

```bash
.venv/bin/pytest tests/test_cca.py tests/test_tasks.py tests/test_provider_runtime.py tests/test_intent_guard.py -q
```

### Real interactive TUI e2e

Requires valid Codex auth state.

```bash
.venv/bin/pytest tests/test_cca_tui_e2e.py -m e2e -q
```

## Docker workflow

This repo supports the packaged SWE-bench container workflow.

### Build artifacts

```bash
conda activate confucius
conda install -c conda-forge conda-pack
conda-pack -n confucius -o cf_env.tar.gz

pex . \
  -r requirements.txt \
  -m scripts.run_swebench \
  -o app.pex \
  --python-shebang="/usr/bin/env python3"
```

### Expected workspace layout

```text
workspace/
|- app.pex
|- cf_env.tar.gz
|- solutions/
|- logs/
`- problem_statements/
   `- <task_id>.txt
```

### Container run

```bash
docker run --rm \
  -e TASK_ID=<task_id> \
  -e AWS_BEARER_TOKEN_BEDROCK=<token> \
  -v <workspace>:/data \
  --network host \
  --userns=host \
  --entrypoint /data/run_sbp.sh
```

## Troubleshooting

### `Failed to prepare runtime: stdin prompt is empty`
You ran one-shot mode without prompt input. Use one of:
- `--prompt <file-or-text>`
- piped stdin
- `--tui`

### Codex auth not found
Run:

```bash
codex login
```

Then verify files exist:
- `~/.codex/auth.json`
- `~/.codex/models_cache.json`

### Gemini OAuth project errors
Set one explicitly:

```bash
export GEMINI_OAUTH_PROJECT=<project-id>
export GEMINI_OAUTH_LOCATION=us-central1
```

### Model not discovered
Use explicit model ID:

```bash
cca --provider codex --model <model-id> ...
```

## License

MIT. See `LICENSE`.
