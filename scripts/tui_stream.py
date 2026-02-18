#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown

try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None  # type: ignore[assignment]

try:
    from prompt_toolkit import prompt as tty_prompt
except Exception:
    tty_prompt = None

try:
    from .run_universal_agent import (
        CODEX_AUTH_PATH,
        CODEX_MODELS_CACHE_PATH,
        _discover_codex_models,
        _prepare_codex_env,
        _select_default_codex_model,
    )
except Exception:
    from scripts.run_universal_agent import (  # type: ignore[no-redef]
        CODEX_AUTH_PATH,
        CODEX_MODELS_CACHE_PATH,
        _discover_codex_models,
        _prepare_codex_env,
        _select_default_codex_model,
    )


console = Console()


def _default_model(provider: str) -> str:
    if provider == "codex":
        models = _discover_codex_models(CODEX_MODELS_CACHE_PATH)
        if models:
            return _select_default_codex_model(models)
        return "gpt-5.3-codex"
    if provider == "openai":
        return "gpt-5.2"
    return "claude-sonnet-4-5-20250929"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Streaming terminal chat (Codex/OpenAI/Anthropic)"
    )
    parser.add_argument(
        "--provider",
        choices=["codex", "openai", "anthropic"],
        default="codex",
        help="Model provider",
    )
    parser.add_argument("--model", default=None, help="Model ID override")
    parser.add_argument(
        "--codex-auth-path",
        type=str,
        default=str(CODEX_AUTH_PATH),
        help="Path to Codex CLI auth.json",
    )
    parser.add_argument(
        "--system",
        type=str,
        default="You are a concise coding assistant.",
        help="System instruction",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=2048,
        help="Maximum output tokens",
    )
    return parser.parse_args()


def _read_user_input() -> str | None:
    if sys.stdin.isatty():
        if tty_prompt is None:
            return input("you> ").strip()
        return tty_prompt("you> ").strip()
    line = sys.stdin.readline()
    if not line:
        return None
    return line.strip()


def _stream_openai(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    provider: str,
) -> str:
    request: dict[str, Any] = {
        "model": model,
        "input": messages,
        "stream": True,
    }
    if provider == "codex":
        request["store"] = False
        request["instructions"] = "Streaming terminal session"

    assistant_text = ""
    stream = client.responses.create(**request)
    for event in stream:
        if getattr(event, "type", "") == "response.output_text.delta":
            delta = getattr(event, "delta", "")
            if delta:
                assistant_text += delta
                console.print(delta, end="")
        if getattr(event, "type", "") == "error":
            err = getattr(event, "error", event)
            raise RuntimeError(f"stream error: {err}")
    console.print()
    return assistant_text


def _stream_anthropic(
    client: Any,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    system: str,
) -> str:
    assistant_text = ""
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            assistant_text += text
            console.print(text, end="")
    console.print()
    return assistant_text


def run() -> None:
    args = parse_args()
    model = args.model or _default_model(args.provider)

    if args.provider == "codex":
        _prepare_codex_env(Path(args.codex_auth_path))

    if args.provider in {"codex", "openai"} and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for openai/codex providers")

    if args.provider == "anthropic":
        if Anthropic is None:
            raise RuntimeError(
                "anthropic package is not installed. Run: .venv/bin/pip install anthropic"
            )
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is required for anthropic provider")

    console.print(
        Markdown(
            f"### Streaming TUI\n"
            f"- provider: `{args.provider}`\n"
            f"- model: `{model}`\n"
            f"- exit: type `/exit`"
        )
    )

    history_openai: list[dict[str, Any]] = [
        {"role": "system", "content": [{"type": "input_text", "text": args.system}]}
    ]
    history_anthropic: list[dict[str, str]] = []

    openai_client = OpenAI()
    anthropic_client = Anthropic() if args.provider == "anthropic" else None

    while True:
        user_input = _read_user_input()
        if user_input is None:
            break
        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            break

        console.print("[bold cyan]assistant>[/bold cyan] ", end="")
        if args.provider in {"codex", "openai"}:
            history_openai.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_input}],
                }
            )
            text = _stream_openai(
                client=openai_client,
                model=model,
                messages=history_openai,
                provider=args.provider,
            )
            history_openai.append(
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            )
            continue

        assert anthropic_client is not None
        history_anthropic.append({"role": "user", "content": user_input})
        text = _stream_anthropic(
            client=anthropic_client,
            model=model,
            messages=history_anthropic,
            max_tokens=args.max_tokens,
            system=args.system,
        )
        history_anthropic.append({"role": "assistant", "content": text})


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        console.print("\n[dim]exiting[/dim]")
    except Exception as exc:
        console.print(f"[red]error:[/red] {exc}")
        sys.exit(1)
