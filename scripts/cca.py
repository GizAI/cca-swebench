#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from string import Template
from traceback import extract_tb

from confucius.core.io.std import StdIOInterface

try:
    from .provider_runtime import (
        CODEX_AUTH_PATH,
        GEMINI_OAUTH_PATH,
        discover_codex_models,
        discover_gemini_models_live,
        list_models,
        prepare_codex_env,
        resolve_runtime_model,
        validate_codex_model_live,
        validate_gemini_model_live,
    )
except Exception:  # pragma: no cover
    from scripts.provider_runtime import (  # type: ignore[no-redef]
        CODEX_AUTH_PATH,
        GEMINI_OAUTH_PATH,
        discover_codex_models,
        discover_gemini_models_live,
        list_models,
        prepare_codex_env,
        resolve_runtime_model,
        validate_codex_model_live,
        validate_gemini_model_live,
    )


class QuietStdIOInterface(StdIOInterface):
    async def _echo(self, text: str) -> None:
        return None

    async def _echo_input(self, input: str) -> None:
        return None


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


def _should_run_tui(args: argparse.Namespace) -> bool:
    if args.tui:
        return True
    if args.prompt:
        return False
    return sys.stdin.isatty()


def _discover_provider_models(provider: str, gemini_oauth_path: Path) -> tuple[list[str], list[str]]:
    discovered_codex_models = discover_codex_models() if provider == "codex" else []
    discovered_gemini_models = (
        discover_gemini_models_live(gemini_oauth_path) if provider == "gemini" else []
    )
    return discovered_codex_models, discovered_gemini_models


def _configure_logging(verbose: bool) -> None:
    try:
        from loguru import logger
    except Exception:  # pragma: no cover
        return
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO")


def _print_runtime_summary(
    *,
    provider: str,
    model: str,
    entry_name: str,
    prompt_source: str,
    tui_mode: bool,
) -> None:
    print("Resolved runtime:")
    print(f"  provider={provider}")
    print(f"  model={model}")
    print(f"  entry_name={entry_name}")
    print(f"  prompt_source={prompt_source}")
    print(f"  mode={'tui' if tui_mode else 'oneshot'}")
    print(f"  OPENAI_BASE_URL={os.environ.get('OPENAI_BASE_URL', '')}")
    print(
        "  OPENAI_CHATGPT_ACCOUNT_ID="
        + ("set" if os.environ.get("OPENAI_CHATGPT_ACCOUNT_ID") else "unset")
    )
    print(
        "  OPENAI_API_KEY="
        + ("set" if os.environ.get("OPENAI_API_KEY") else "unset")
    )
    print(
        "  GEMINI_USE_OAUTH="
        + ("set" if os.environ.get("GEMINI_USE_OAUTH") else "unset")
    )
    print(
        "  GOOGLE_CLOUD_PROJECT="
        + (os.environ.get("GOOGLE_CLOUD_PROJECT") or "")
    )
    print(
        "  GOOGLE_CLOUD_LOCATION="
        + (os.environ.get("GOOGLE_CLOUD_LOCATION") or "")
    )
    print("  CCA_SOLO_MODE=" + (os.environ.get("CCA_SOLO_MODE") or ""))


def _handle_model_listing(
    *,
    provider: str,
    codex_auth_path: Path,
    gemini_oauth_path: Path,
    validate_models_live: bool,
) -> None:
    catalog = list_models(provider, codex_auth_path, gemini_oauth_path)
    print(f"Provider: {provider}")
    if catalog.models:
        print("Models:")
        for model in catalog.models:
            print(f"  {model}")
    else:
        print("Models:\n  (none discovered for this provider)")

    if catalog.aliases:
        print("Aliases:")
        for alias, model in sorted(catalog.aliases.items()):
            print(f"  {alias} -> {model}")

    if not validate_models_live:
        return

    print("Live validation:")
    if not catalog.models:
        print("  no discovered models to validate")
        return

    if provider == "codex":
        prepare_codex_env(codex_auth_path)
        for model in catalog.models:
            ok, msg = validate_codex_model_live(model, codex_auth_path)
            print(f"  {'OK' if ok else 'FAIL'} {model}: {msg}")
        return

    if provider == "gemini":
        for model in catalog.models:
            ok, msg = validate_gemini_model_live(model, gemini_oauth_path)
            print(f"  {'OK' if ok else 'FAIL'} {model}: {msg}")
        return

    print("  live validation is supported for codex and gemini providers")


async def _read_user_input(cf: object) -> str | None:
    if sys.stdin.isatty():
        return await cf.io.get_input(prompt="", placeholder="Send a message (/help)")
    line = await asyncio.to_thread(sys.stdin.readline)
    if line == "":
        return None
    return line.rstrip("\n")


async def _invoke_turn(cf: object, entry_name: str, text: str) -> None:
    try:
        from confucius.core.entry.base import EntryInput
        from confucius.core.entry.entry import Entry

        await cf.invoke_analect(Entry(), EntryInput(question=text, entry_name=entry_name))
    except asyncio.CancelledError:
        await cf.io.on_cancel()
        if cf.exiting:
            raise
    except Exception as exc:
        tb = exc.__traceback__
        tb_str = "\n".join(extract_tb(tb).format()) if tb else ""
        if tb_str:
            print(tb_str, file=sys.stderr)
        await cf.io.error(f"{exc}. Check stderr for details")
    finally:
        await cf.save(raise_exception=False)


async def _run_tui(
    *,
    entry_name: str,
    verbose: bool,
    provider: str,
    model: str,
    initial_prompt: str | None,
) -> None:
    from confucius.analects.code.entry import CodeAssistEntry  # noqa: F401
    from confucius.lib.confucius import Confucius

    cf = Confucius(verbose=verbose, io=QuietStdIOInterface())

    await cf.io.rule("CCA")
    await cf.io.system(f"provider={provider} | model={model} | /help for commands")

    async def repl_loop() -> None:
        if initial_prompt:
            await _invoke_turn(cf, entry_name, initial_prompt)

        while True:
            user_input = await _read_user_input(cf)
            if user_input is None:
                break

            text = user_input.strip()
            if not text:
                continue

            if text in {"/exit", "/quit"}:
                break
            if text == "/help":
                await cf.io.system("Commands: /help, /model, /exit")
                continue
            if text == "/model":
                await cf.io.system(f"provider={provider} model={model}")
                continue

            await _invoke_turn(cf, entry_name, text)

    task = asyncio.create_task(repl_loop())

    async def on_interrupt() -> None:
        if not await cf.cancel_task():
            task.cancel()

    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(on_interrupt()))
    except NotImplementedError:
        pass

    await task


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified Confucius runner: one-shot + TUI + provider runtime"
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Prompt input. If this points to an existing file, file contents are used; otherwise treated as inline text.",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        default=False,
        help="Force interactive TUI mode",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="codex",
        choices=["codex", "openai", "gemini", "bedrock", "custom"],
        help="LLM provider mode",
    )
    parser.add_argument("--model", type=str, default=None, help="Model override")
    parser.add_argument(
        "--list-models",
        action="store_true",
        default=False,
        help="Print discovered models and aliases for the selected provider, then exit",
    )
    parser.add_argument(
        "--validate-models-live",
        action="store_true",
        default=False,
        help="Validate discovered model IDs with live API calls for the selected provider, then exit",
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
        help="Use prompt file/text as-is (skip SWE-bench template wrapping in one-shot mode)",
    )
    parser.add_argument(
        "--codex-auth-path",
        type=str,
        default=str(CODEX_AUTH_PATH),
        help="Path to Codex CLI auth.json",
    )
    parser.add_argument(
        "--gemini-oauth-path",
        type=str,
        default=str(GEMINI_OAUTH_PATH),
        help="Path to Gemini OAuth credentials",
    )
    parser.add_argument("--verbose", action="store_true", default=False, help="Enable verbose logging")
    parser.add_argument(
        "--solo-mode",
        choices=["auto", "on", "off"],
        default="auto",
        help="Solo orchestration mode: auto (on for one-shot, off for TUI), on, or off",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Resolve runtime env/model only; do not invoke agent",
    )
    return parser.parse_args(argv)


def _run_oneshot(prompt: str, entry_name: str, verbose: bool) -> None:
    from confucius.analects.code.entry import CodeAssistEntry  # noqa: F401
    from .utils import run_agent_with_prompt

    asyncio.run(run_agent_with_prompt(prompt, entry_name=entry_name, verbose=verbose))


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    _configure_logging(args.verbose)
    codex_auth_path = Path(args.codex_auth_path)
    gemini_oauth_path = Path(args.gemini_oauth_path)

    if args.list_models or args.validate_models_live:
        try:
            _handle_model_listing(
                provider=args.provider,
                codex_auth_path=codex_auth_path,
                gemini_oauth_path=gemini_oauth_path,
                validate_models_live=args.validate_models_live,
            )
        except Exception as exc:
            print(f"Failed to discover models for provider={args.provider}: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    try:
        discovered_codex_models, discovered_gemini_models = _discover_provider_models(
            args.provider,
            gemini_oauth_path,
        )
        model = resolve_runtime_model(
            args.provider,
            args.model,
            codex_auth_path=codex_auth_path,
            gemini_oauth_path=gemini_oauth_path,
            discovered_codex_models=discovered_codex_models,
            discovered_gemini_models=discovered_gemini_models,
        )
        os.environ["CCA_MODEL"] = model

        tui_mode = _should_run_tui(args)
        prompt_source = "none"
        initial_prompt: str | None = None
        oneshot_prompt: str | None = None

        if args.prompt:
            initial_prompt, prompt_source = _read_prompt_file_or_text(args.prompt)
            oneshot_prompt = initial_prompt
        elif not tui_mode:
            oneshot_prompt = _read_prompt_stdin()
            prompt_source = "stdin"

        if not args.raw_prompt and oneshot_prompt is not None:
            oneshot_prompt = _build_swebench_prompt(oneshot_prompt)

        if args.solo_mode == "on":
            os.environ["CCA_SOLO_MODE"] = "1"
        elif args.solo_mode == "off":
            os.environ["CCA_SOLO_MODE"] = "0"
        else:
            os.environ["CCA_SOLO_MODE"] = "0" if tui_mode else "1"
    except Exception as exc:
        print(f"Failed to prepare runtime: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        _print_runtime_summary(
            provider=args.provider,
            model=model,
            entry_name=args.entry_name,
            prompt_source=prompt_source,
            tui_mode=tui_mode,
        )
        return

    if tui_mode:
        asyncio.run(
            _run_tui(
                entry_name=args.entry_name,
                verbose=args.verbose,
                provider=args.provider,
                model=model,
                initial_prompt=initial_prompt,
            )
        )
        return

    print(f"Running Confucius agent with provider={args.provider}, model={model}")
    try:
        if oneshot_prompt is None:
            raise ValueError("No prompt provided for one-shot mode")
        _run_oneshot(oneshot_prompt, entry_name=args.entry_name, verbose=args.verbose)
        print("Agent completed successfully")
    except Exception as exc:
        print(f"Failed to run agent: {exc}", file=sys.stderr)
        sys.exit(1)


def cli() -> None:
    try:
        main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover
    cli()
