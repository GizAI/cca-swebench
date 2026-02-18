# A Simple Agent Harness Design

This repo is a minimal harness of [Confucius Code Agent (CCA)](https://arxiv.org/abs/2512.10398) to run [SWEBench-Pro](https://scale.com/leaderboard/swe_bench_pro_public)

## Philosophy

**Put the agent inside the container, not outside.**

```
┌────────────────────────────────────────────────────────────────────┐
│                        Docker Container                            │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                          Agent                                │ │
│  │                                                               │ │
│  │  • Receives task                                             │ │
│  │  • Reasons about solution                                    │ │
│  │  • Executes actions directly                                 │ │
│  │  • Returns results                                           │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                              │                                     │
│                              │ direct execution                    │
│                              ▼                                     │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                    Available Actions                          │ │
│  │                                                               │ │
│  │  bash()        → subprocess.run(cmd, shell=True)             │ │
│  │  read_file()   → open(path).read()                           │ │
│  │  write_file()  → open(path, 'w').write(content)              │ │
│  │  ...           → anything Python/system can do               │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                              │                                     │
│                              ▼                                     │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                   Container Filesystem                        │ │
│  │                                                               │ │
│  │  /repo/         ← Target codebase                            │ │
│  │  /workspace/    ← Working directory                          │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

## Why Not an Abstraction Layer?

Frameworks like [SWE-ReX](https://github.com/SWE-agent/SWE-ReX) run the agent on the host and communicate with the container via a runtime abstraction:

```
┌─────────────────────────────────────────────────────────────┐
│                      SWE-agent                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │                    SWEEnv                           │    │
│  │  • deployment: AbstractDeployment                   │    │
│  │  • communicate() → BashAction → BashObservation     │    │
│  │  • read_file(), write_file()                        │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────────┘
                          │ uses
┌─────────────────────────▼───────────────────────────────────┐
│                       SWE-ReX                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │             Deployment Layer                          │  │
│  │  DockerDeployment.start() → podman run               │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Runtime Layer                            │  │
│  │  LocalDockerRuntime → podman exec                    │  │
│  │  BashSession → pexpect shell interaction             │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

This introduces an **abstraction scalability problem**:

- Every operation (bash, read file, write file, ...) needs explicit abstraction
- Adding new capabilities requires changes across ~8 files
- Not well tested on agent implementations other than SWE-Agent.
- Debugging spans multiple layers and network boundaries

**Our approach**: Give the agent direct access. Need to watch a file? Just use `watchdog`. Need to inspect a process? Just use `psutil`. No abstraction layer to extend.

## Who Should Use This?

| You are... | Recommendation |
|------------|----------------|
| **Training models** | ✅ Use this. Your scaffold is frozen anyway—just bake it into the image. Parallelize by spinning up N containers. |
| **Developing agents** | ✅ Use this. Image rebuilds take ~30s with layer caching. The debugging simplicity is worth it. |
| **Need to swap Docker/AWS/Modal dynamically** | ❌ Use SWE-ReX, better support for Modal |

## The Tradeoff

| | Agent Inside (this approach) | Agent Outside (SWE-ReX) |
|---|:---:|:---:|
| Simplicity | ✅ | ❌ |
| Latency | ✅ | ❌ |
| Debugging | ✅ | ❌ |
| Extensibility | ✅ | ❌ |
| Agent isolation from sandbox | ❌ | ✅ |
| Multi-platform abstraction | ❌ | ✅ |

# Getting Started
## Install Confucius-Code-Agent (CCA)
1) Create a conda environment and install dependencies

- From the repo root (this directory contains `confucius/` and `requirements.txt`):
  - Create and activate an environment
    - `conda create -n confucius python=3.12 -y`
    - `conda activate confucius`
  - Install Python dependencies
    - `pip install -r requirements.txt`
2) Configure provider credentials (choose one)

Confucius can talk to multiple LLM providers. Set the env vars for the provider you intend to use, for running swebench we use bedrock API as Anthropic model providers:

- AWS Bedrock (via boto3): ensure your AWS credentials/region are configured
  - `export AWS_REGION=us-east-1`
  - and either `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` or a named profile.
  - optionally a bedrock API key `AWS_BEARER_TOKEN_BEDROCK` can also be exported

## Universal Runner (Codex/OpenAI/Anthropic)

Use `scripts/run_universal_agent.py` as the CLI entrypoint for CCA runtime selection/auth wiring.

### If You Are Migrating From Codex CLI or Claude Code

- Codex CLI users:
  - run `codex login` once
  - use `--provider codex` and optional `--model`
- Claude Code users:
  - keep your Anthropic env (`ANTHROPIC_API_KEY`) configured
  - use `--provider anthropic --model claude-sonnet-4-5` (or another Claude model)

This gives a single execution surface for both ecosystems while keeping provider-specific auth native.

```bash
# Create venv and install dependencies
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Codex mode (default): uses ~/.codex/auth.json (from `codex login`)
.venv/bin/python -m scripts.run_universal_agent --prompt /path/to/problem.txt --provider codex --dry-run

# No file needed: inline prompt via the same --prompt option
.venv/bin/python -m scripts.run_universal_agent --prompt "Fix failing unit tests in current repo" --provider codex --raw-prompt --dry-run

# No file needed: stdin prompt
echo "Fix failing unit tests in current repo" | .venv/bin/python -m scripts.run_universal_agent --provider codex --raw-prompt --dry-run

# List discovered Codex models (+ generated aliases)
.venv/bin/python -m scripts.run_universal_agent --list-models

# Validate discovered model IDs against live Codex API
.venv/bin/python -m scripts.run_universal_agent --validate-models-live

# Run with Codex model
.venv/bin/python -m scripts.run_universal_agent --prompt /path/to/problem.txt --provider codex

# Run with explicit model ID
.venv/bin/python -m scripts.run_universal_agent --prompt /path/to/problem.txt --provider codex --model gpt-5.3-codex-spark

# Run with alias (alias map is generated from discovered models, not hardcoded)
.venv/bin/python -m scripts.run_universal_agent --prompt /path/to/problem.txt --provider codex --model spark

# Run with OpenAI API key flow
OPENAI_API_KEY=... .venv/bin/python -m scripts.run_universal_agent --prompt /path/to/problem.txt --provider openai --model gpt-5.2

# Run with Anthropic model preset
.venv/bin/python -m scripts.run_universal_agent --prompt /path/to/problem.txt --provider anthropic --model claude-sonnet-4-5

# Run from Claude ecosystem with env auth
ANTHROPIC_API_KEY=... .venv/bin/python -m scripts.run_universal_agent --prompt /path/to/problem.txt --provider anthropic --model claude-sonnet-4-5
```

Notes:
- If you already ran `codex login`, no extra auth setup is required for `--provider codex`.
- `--dry-run` prints resolved runtime config without invoking the agent.
- `CCA_MODEL` is auto-set by the launcher so model selection is explicit and reproducible.
- Codex aliases are generated dynamically from discovered model IDs in `~/.codex/models_cache.json`.
- Prompt input options: `--prompt <file-or-text>` or stdin pipe.

## Streaming TUI (Codex / Claude style)

Use `scripts/tui_stream.py` for a minimal real-time streaming terminal UI.

```bash
# Show all pluggable backends
.venv/bin/python -m scripts.tui_stream --list-providers

# Codex streaming TUI (uses `codex login` session)
.venv/bin/python -m scripts.tui_stream --provider codex

# OpenAI API key mode
OPENAI_API_KEY=... .venv/bin/python -m scripts.tui_stream --provider openai --model gpt-5.2

# Anthropic API mode
# one-time install if needed:
.venv/bin/pip install anthropic
ANTHROPIC_API_KEY=... .venv/bin/python -m scripts.tui_stream --provider anthropic --model claude-sonnet-4-5-20250929

# Claude Code CLI backend (uses local Claude Code OAuth/login state)
claude login
.venv/bin/python -m scripts.tui_stream --provider claude-code --model claude-sonnet-4-5-20250929

# Gemini CLI backend (uses local ~/.gemini/oauth_creds.json)
gemini
.venv/bin/python -m scripts.tui_stream --provider gemini-cli --model gemini-3-flash-preview
```

Behavior:
- token-by-token streaming output in terminal
- multi-turn chat history
- `/exit` or `/quit` to stop
- provider backends are registry-based and easy to extend


## Run CCA in Docker Container
This option directly installs CCA in the target docker container and run it along with SWE-bench test instances. Note for some docker images some CCA python libs may not be supported.
### Build
Run the following to package a CF entrypoing into PEX binary, here -m can be any entrypoint of choice, -o is the output binary path, the script "run_swebench.py" is the entrypoint of swe-bench instances when running in a docker environment, including both swebench-pro and swebench-verified.
```bash
# Ensure conda env is packed to tar file
conda activate confucius
conda install -c conda-forge conda-pack
conda-pack -n confucius -o cf_env.tar.gz

pex . \
  -r requirements.txt \
  -m scripts.run_swebench \
  -o app.pex \
  --python-shebang="/usr/bin/env python3"
```

### Docker Entrypoint
Prepare your workspace:
```
workspace/
├── app.pex            # pex build artifact
├── cf_env.tar.gz      # packed conda env
├── solutions/         # output patch
├── logs/              # output agent logs
└── problem_statements/
    ├── <task_id>.txt     # swebench instance problem description
    ...

```

Use the following script as docker entrypoint: [run_sbp.sh](scripts/run_sbp.sh)

Start the container
```bash
docker run --rm -e TASK_ID={} -e AWS_BEARER_TOKEN_BEDROCK=<bedrock token> -v <your workspace>:/data --network host --userns=host --entrypoint /data/run_sbp.sh
```

## Option 2 - Docker As Runtime Layer
There are around 88 instances in SWE-bench-pro which has alpine linux docker images that cannot install the conda env of CCA, for these instances we create a similar setup as SWE-Rex which directly let Confucius agent interact with sandbox like Docker containers.
Coming soon...

## License

MIT — see LICENSE.
