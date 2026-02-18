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

## Unified Runner + TUI (Confucius Harness)

Use `scripts/cca.py` as the single launcher for provider auth + model selection while keeping execution inside the Confucius harness.

Install global `cca` command:

```bash
python3 -m pip install --user -r requirements.txt
python3 -m pip install --user -e .
```

After install, run from anywhere:

```bash
cca
```

`cca` defaults to interactive TUI when no prompt is provided.

Supported providers:
- `codex`: OAuth from `codex login` (`~/.codex/auth.json`)
- `openai`: `OPENAI_API_KEY`
- `gemini`: `GOOGLE_API_KEY`/`GEMINI_API_KEY` or Gemini OAuth (`~/.gemini/oauth_creds.json`) via Vertex mode
- `bedrock`: AWS Bedrock (`AWS_REGION` + AWS credentials)
- `custom`: explicit `--model`

```bash
# Create venv and install dependencies
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Codex dry-run (uses codex login session)
.venv/bin/python -m scripts.cca --provider codex --prompt "Fix lint errors" --raw-prompt --dry-run

# Prompt can be file path or inline text with the same option
.venv/bin/python -m scripts.cca --provider codex --prompt /path/to/problem.txt
.venv/bin/python -m scripts.cca --provider codex --prompt "Fix failing tests" --raw-prompt

# Stdin prompt
echo "Fix failing tests" | .venv/bin/python -m scripts.cca --provider codex --raw-prompt

# Dynamic model discovery + aliases (provider-scoped)
.venv/bin/python -m scripts.cca --provider codex --list-models
.venv/bin/python -m scripts.cca --provider gemini --list-models

# Live model validation
.venv/bin/python -m scripts.cca --provider codex --validate-models-live
.venv/bin/python -m scripts.cca --provider gemini --validate-models-live

# Explicit model selection
.venv/bin/python -m scripts.cca --provider codex --model gpt-5.3-codex-spark --prompt /path/to/problem.txt
OPENAI_API_KEY=... .venv/bin/python -m scripts.cca --provider openai --model gpt-5.2 --prompt /path/to/problem.txt
AWS_REGION=us-east-1 .venv/bin/python -m scripts.cca --provider bedrock --model claude-sonnet-4-5 --prompt /path/to/problem.txt

# Force interactive TUI
.venv/bin/python -m scripts.cca --provider codex --tui

# TUI with optional initial prompt (file or inline)
.venv/bin/python -m scripts.cca --provider codex --tui --prompt "Review this repository structure"

# Explicit solo behavior override
.venv/bin/python -m scripts.cca --provider codex --tui --solo-mode off
.venv/bin/python -m scripts.cca --provider codex --prompt "fix tests" --solo-mode on
```

Notes:
- `CCA_MODEL` is set by the launcher and consumed by Confucius.
- Codex aliases are generated dynamically from `~/.codex/models_cache.json`.
- For `provider=codex`, default model is selected dynamically from discovered IDs and prefers the latest `-spark` variant when available.
- Gemini OAuth mode auto-discovers a Google Cloud project from the OAuth account if `GEMINI_OAUTH_PROJECT` is unset.
- Gemini OAuth requires Vertex access in the selected project (if Vertex API is disabled, live generation validation will fail fast).
- Mode selection is automatic: without `--prompt`, TTY input enters TUI and piped stdin runs one-shot.
- `--solo-mode auto` is the default: TUI uses solo mode off (prevents endless progress loops), one-shot uses solo mode on.

TUI commands:
- `/help`
- `/model`
- `/exit` or `/quit`

### Real TUI E2E Test

Run a pseudo-terminal integration test (real interactive session) with Codex OAuth + Spark model:

```bash
.venv/bin/pytest tests/test_cca_tui_e2e.py -m e2e -q
```

What it validates:
- TUI startup banner with selected provider/model
- `/help` and `/model` commands
- Real prompt execution against `gpt-5.3-codex-spark`
- Clean `/exit` shutdown


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
