#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

import argparse
import asyncio
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from string import Template
from typing import Any

CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
CODEX_MODELS_CACHE_PATH = Path.home() / ".codex" / "models_cache.json"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_RESPONSES_ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"


def _read_prompt(prompt_file: Path) -> str:
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file does not exist: {prompt_file}")
    content = prompt_file.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError("Prompt file is empty")
    return content


def _read_prompt_file_or_text(prompt_value: str) -> tuple[str, str]:
    possible_file = Path(prompt_value)
    if possible_file.exists() and possible_file.is_file():
        return (_read_prompt(possible_file), str(possible_file))
    content = prompt_value.strip()
    if not content:
        raise ValueError("--prompt is empty")
    return (content, "inline")


def _read_prompt_stdin() -> str:
    if sys.stdin.isatty():
        raise ValueError("stdin is empty")
    content = sys.stdin.read().strip()
    if not content:
        raise ValueError("stdin prompt is empty")
    return content


def _build_swebench_prompt(problem_statement: str) -> str:
    template = Template(
        """## Work directory
I've uploaded a python code repository in your current directory, this will be the repository for you to investigate and make code changes.

## Problem Statement
$problem_statement

## Your Task
Can you help me implement the necessary changes to the repository so that the requirements specified in the problem statement are met?
I've already taken care of all changes to any of the test files described in the problem statement. This means you DON'T have to modify the testing logic or any of the tests in any way!
Your task is to make the minimal changes to non-tests files in the $${working_dir} directory to ensure the problem statement is satisfied.
Follow these steps to resolve the issue:
1. As a first step, it might be a good idea to find and read code relevant to the problem statement
2. Create a script to reproduce the error and execute it with `python <filename.py>` using the bash tool, to confirm the error
3. Edit the source code of the repo to resolve the issue
4. Rerun your reproduction script and confirm that the error is fixed!
5. Think about edge cases and make sure your fix handles them as well

**Note**: this is a HARD problem, which means you need to think HARD! Your thinking should be thorough and so it's fine if it's very long.
**Note**: you are not allowed to modify project dependency files like `pyproject.toml` or `setup.py` or `requirements.txt` or `package.json`

## Exit Criteria
Please carefully follow the steps below to help review your changes.
    1. If you made any changes to your code after running the reproduction script, please run the reproduction script again.
    If the reproduction script is failing, please revisit your changes and make sure they are correct.
    If you have already removed your reproduction script, please ignore this step.

    2. Remove your reproduction script (if you haven't done so already).

    3. If you have modified any TEST files, please revert them to the state they had before you started fixing the issue.
    You can do this with `git checkout -- /path/to/test/file.py`. Use below <diff> to find the files you need to revert.

    4. Commit your change, make sure you only have one commit.
Plz make sure you commit your change at the end, otherwise I won't be able to export your change.
"""
    )
    return template.substitute(problem_statement=problem_statement)


def _http_form_post(url: str, data: dict[str, str]) -> dict[str, Any]:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _refresh_openai_oauth(refresh_token: str) -> dict[str, Any]:
    return _http_form_post(
        f"{OPENAI_OAUTH_ISSUER}/oauth/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CODEX_CLIENT_ID,
        },
    )


def _jwt_claims(jwt_token: str) -> dict[str, Any]:
    parts = jwt_token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload + padding)
    return json.loads(decoded.decode("utf-8"))


def _extract_account_id_from_claims(claims: dict[str, Any]) -> str | None:
    root = claims.get("chatgpt_account_id")
    if isinstance(root, str) and root:
        return root
    auth_claim = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claim, dict):
        nested = auth_claim.get("chatgpt_account_id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _use_codex_runtime(access_token: str, account_id: str | None) -> None:
    os.environ["OPENAI_API_KEY"] = access_token
    os.environ["OPENAI_BASE_URL"] = "https://chatgpt.com/backend-api/codex"
    os.environ["OPENAI_ORIGINATOR"] = os.environ.get("OPENAI_ORIGINATOR", "codex-cli")
    if account_id:
        os.environ["OPENAI_CHATGPT_ACCOUNT_ID"] = account_id


def _prepare_codex_from_codex_cli(codex_auth_path: Path) -> bool:
    if not codex_auth_path.exists():
        return False

    auth = _load_json(codex_auth_path)
    api_key = auth.get("OPENAI_API_KEY")
    if isinstance(api_key, str) and api_key:
        os.environ["OPENAI_API_KEY"] = api_key
        return True

    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        return False

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        return False

    claims = _jwt_claims(access_token)
    expires_epoch = int(claims.get("exp", 0))
    now_epoch = int(time.time())
    account_id = tokens.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        account_id = _extract_account_id_from_claims(claims)

    if expires_epoch <= now_epoch + 10 and isinstance(refresh_token, str) and refresh_token:
        refreshed = _refresh_openai_oauth(refresh_token)
        new_access = refreshed["access_token"]
        new_refresh = refreshed.get("refresh_token") or refresh_token
        tokens["access_token"] = new_access
        tokens["refresh_token"] = new_refresh
        maybe_account_id = (
            tokens.get("account_id")
            if isinstance(tokens.get("account_id"), str)
            else _extract_account_id_from_claims(_jwt_claims(new_access))
        )
        if maybe_account_id:
            tokens["account_id"] = maybe_account_id
        auth["tokens"] = tokens
        auth["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _write_json(codex_auth_path, auth)
        _use_codex_runtime(new_access, maybe_account_id)
        return True

    _use_codex_runtime(access_token, account_id)
    return True


def _prepare_codex_env(codex_auth_path: Path) -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    if _prepare_codex_from_codex_cli(codex_auth_path):
        return
    raise FileNotFoundError(
        "No usable Codex/OpenAI auth found. Login with `codex login`, "
        "or set OPENAI_API_KEY."
    )


def _extract_codex_models(node: Any, result: set[str]) -> None:
    if isinstance(node, dict):
        slug = node.get("slug")
        if isinstance(slug, str) and "codex" in slug:
            result.add(slug)
        for value in node.values():
            _extract_codex_models(value, result)
        return
    if isinstance(node, list):
        for value in node:
            _extract_codex_models(value, result)


def _discover_codex_models(cache_path: Path) -> list[str]:
    if not cache_path.exists():
        return []
    try:
        content = _load_json(cache_path)
    except Exception:
        return []
    models: set[str] = set()
    _extract_codex_models(content, models)
    return sorted(models)


def _model_parts(model_id: str) -> tuple[tuple[int, ...], str]:
    # Examples:
    # gpt-5.3-codex -> ((5, 3), "")
    # gpt-5.3-codex-spark -> ((5, 3), "spark")
    # gpt-5-codex-mini -> ((5,), "mini")
    if not model_id.startswith("gpt-") or "-codex" not in model_id:
        return ((), model_id)
    core = model_id[len("gpt-") :]
    version, _, suffix = core.partition("-codex")
    variant = suffix.lstrip("-")
    version_parts: list[int] = []
    for token in version.split("."):
        if token.isdigit():
            version_parts.append(int(token))
    return (tuple(version_parts), variant)


def _build_dynamic_aliases(models: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    variant_to_models: dict[str, list[str]] = {}

    for model in models:
        versions, variant = _model_parts(model)
        if not versions:
            continue
        version_text = ".".join(str(v) for v in versions)
        aliases[version_text] = model if not variant else aliases.get(version_text, model)
        aliases[f"{version_text}-codex"] = model if not variant else aliases.get(
            f"{version_text}-codex", model
        )
        if variant:
            aliases[f"{version_text}-{variant}"] = model
            variant_to_models.setdefault(variant, []).append(model)

    for variant, variant_models in variant_to_models.items():
        if len(variant_models) == 1:
            aliases[variant] = variant_models[0]

    return aliases


def _select_default_codex_model(models: list[str]) -> str:
    if not models:
        raise ValueError(
            "No Codex models discovered in ~/.codex/models_cache.json. "
            "Pass --model explicitly."
        )
    candidates = sorted(
        models,
        key=lambda m: (
            _model_parts(m)[0],  # higher version first
            _model_parts(m)[1] == "",  # prefer base codex over variant
            _model_parts(m)[1] not in {"mini"},  # then non-mini
        ),
        reverse=True,
    )
    return candidates[0]


def _resolve_codex_model(model: str | None, discovered_models: list[str]) -> str:
    if not model:
        return _select_default_codex_model(discovered_models)
    raw = model.strip()
    if raw in discovered_models:
        return raw
    aliases = _build_dynamic_aliases(discovered_models)
    mapped = aliases.get(raw.lower())
    return mapped or raw


def _codex_request_headers(codex_auth_path: Path) -> dict[str, str]:
    auth = _load_json(codex_auth_path)
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("Invalid Codex auth format: missing tokens")
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access:
        raise ValueError("Invalid Codex auth format: missing access_token")
    account = tokens.get("account_id")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access}",
        "originator": "codex-cli",
    }
    if isinstance(account, str) and account:
        headers["ChatGPT-Account-Id"] = account
    return headers


def _validate_codex_model_live(model: str, codex_auth_path: Path) -> tuple[bool, str]:
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "ping"}],
            }
        ],
        "instructions": "You are terse.",
        "store": False,
        "stream": True,
    }
    request = urllib.request.Request(
        CODEX_RESPONSES_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers=_codex_request_headers(codex_auth_path),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return (response.status == 200, f"HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")
        return (False, f"HTTP {exc.code}: {body[:160].replace(chr(10), ' ')}")


def _apply_provider_defaults(
    provider: str,
    model: str | None,
    codex_auth_path: Path,
    discovered_models: list[str],
) -> str:
    if provider == "codex":
        _prepare_codex_env(codex_auth_path)
        return _resolve_codex_model(model, discovered_models)
    if provider == "openai":
        return model or "gpt-5.2"
    if provider == "anthropic":
        return model or "claude-sonnet-4-5"
    return model or "gpt-5.2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Universal CCA runner with Codex/OpenAI/Anthropic model selection"
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Prompt input. If this points to an existing file, file contents are used; otherwise treated as inline text.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="codex",
        choices=["codex", "openai", "anthropic", "custom"],
        help="LLM provider mode",
    )
    parser.add_argument("--model", type=str, default=None, help="Model override")
    parser.add_argument(
        "--list-models",
        action="store_true",
        default=False,
        help="Print known/discovered Codex models and exit",
    )
    parser.add_argument(
        "--validate-models-live",
        action="store_true",
        default=False,
        help="Validate discovered Codex models with live API calls and exit",
    )
    parser.add_argument(
        "--entry-name",
        type=str,
        default="Code",
        help="Confucius entry name (default: Code)",
    )
    parser.add_argument(
        "--raw-prompt",
        action="store_true",
        default=False,
        help="Use prompt file as-is (skip SWE-bench template wrapping)",
    )
    parser.add_argument(
        "--codex-auth-path",
        type=str,
        default=str(CODEX_AUTH_PATH),
        help="Path to Codex CLI auth.json",
    )
    parser.add_argument("--verbose", action="store_true", default=False, help="Enable verbose logging")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Resolve runtime env/model only; do not invoke agent",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    codex_auth_path = Path(args.codex_auth_path)
    discovered_models = _discover_codex_models(CODEX_MODELS_CACHE_PATH)
    aliases = _build_dynamic_aliases(discovered_models)

    if args.list_models or args.validate_models_live:
        print("Codex models:")
        for model in discovered_models:
            print(f"  {model}")
        if aliases:
            print("Aliases:")
            for alias, model in sorted(aliases.items()):
                print(f"  {alias} -> {model}")
        if args.validate_models_live:
            print("Live validation:")
            if not discovered_models:
                print("  no discovered models to validate")
                return
            _prepare_codex_env(codex_auth_path)
            for model in discovered_models:
                ok, msg = _validate_codex_model_live(model, codex_auth_path)
                print(f"  {'OK' if ok else 'FAIL'} {model}: {msg}")
        return

    prompt_source = "stdin"

    try:
        if args.prompt:
            source_prompt, prompt_source = _read_prompt_file_or_text(args.prompt)
        else:
            source_prompt = _read_prompt_stdin()

        prompt = source_prompt if args.raw_prompt else _build_swebench_prompt(source_prompt)
        model = _apply_provider_defaults(
            args.provider, args.model, codex_auth_path, discovered_models
        )
        os.environ["CCA_MODEL"] = model
    except Exception as exc:
        print(f"Failed to prepare runtime: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("Resolved runtime:")
        print(f"  provider={args.provider}")
        print(f"  model={model}")
        print(f"  entry_name={args.entry_name}")
        print(f"  prompt_source={prompt_source}")
        print(f"  OPENAI_BASE_URL={os.environ.get('OPENAI_BASE_URL', '')}")
        print(f"  OPENAI_CHATGPT_ACCOUNT_ID={'set' if os.environ.get('OPENAI_CHATGPT_ACCOUNT_ID') else 'unset'}")
        print(f"  OPENAI_API_KEY={'set' if os.environ.get('OPENAI_API_KEY') else 'unset'}")
        return

    print(f"Running Confucius agent with provider={args.provider}, model={model}")

    try:
        from confucius.analects.code.entry import CodeAssistEntry  # noqa: F401
        from .utils import run_agent_with_prompt

        asyncio.run(run_agent_with_prompt(prompt, entry_name=args.entry_name, verbose=args.verbose))
        print("Agent completed successfully")
    except Exception as exc:
        print(f"Failed to run agent: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
