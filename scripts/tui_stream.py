#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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
GEMINI_OAUTH_PATH = Path.home() / ".gemini" / "oauth_creds.json"


class StreamBackend(Protocol):
    name: str

    def preflight(self, args: argparse.Namespace) -> None: ...

    def default_model(self) -> str: ...

    def stream_turn(
        self,
        *,
        model: str,
        system: str,
        history: list[dict[str, str]],
        user_input: str,
        max_tokens: int,
    ) -> str: ...


def _read_user_input() -> str | None:
    if sys.stdin.isatty():
        if tty_prompt is None:
            return input("you> ").strip()
        return tty_prompt("you> ").strip()
    line = sys.stdin.readline()
    if not line:
        return None
    return line.strip()


def _render_cli_prompt(system: str, history: list[dict[str, str]], user_input: str) -> str:
    parts = [f"System: {system}"]
    for item in history[-12:]:
        parts.append(f"{item['role']}: {item['content']}")
    parts.append(f"user: {user_input}")
    parts.append("assistant:")
    return "\n".join(parts)


def _print_stream_text(text: str) -> None:
    if text:
        console.print(text, end="")


@dataclass
class CodexOpenAIBackend:
    name: str
    provider: str  # "codex" | "openai"
    codex_auth_path: Path

    def preflight(self, args: argparse.Namespace) -> None:
        if self.provider == "codex":
            _prepare_codex_env(self.codex_auth_path)
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for openai/codex providers")

    def default_model(self) -> str:
        if self.provider == "openai":
            return "gpt-5.2"
        models = _discover_codex_models(CODEX_MODELS_CACHE_PATH)
        if models:
            return _select_default_codex_model(models)
        return "gpt-5.3-codex"

    def stream_turn(
        self,
        *,
        model: str,
        system: str,
        history: list[dict[str, str]],
        user_input: str,
        max_tokens: int,
    ) -> str:
        # Responses API-style conversation payload
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system}],
            }
        ]
        for item in history:
            messages.append(
                {
                    "role": item["role"],
                    "content": [{"type": "input_text", "text": item["content"]}],
                }
            )
        messages.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_input}],
            }
        )

        request: dict[str, Any] = {
            "model": model,
            "input": messages,
            "stream": True,
        }
        if self.provider != "codex":
            request["max_output_tokens"] = max_tokens
        if self.provider == "codex":
            request["store"] = False
            request["instructions"] = "Streaming terminal session"

        assistant_text = ""
        client = OpenAI()
        stream = client.responses.create(**request)
        for event in stream:
            if getattr(event, "type", "") == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    assistant_text += delta
                    _print_stream_text(delta)
            if getattr(event, "type", "") == "error":
                err = getattr(event, "error", event)
                raise RuntimeError(f"stream error: {err}")

        console.print()
        return assistant_text


@dataclass
class AnthropicBackend:
    name: str

    def preflight(self, args: argparse.Namespace) -> None:
        if Anthropic is None:
            raise RuntimeError(
                "anthropic package is not installed. Run: .venv/bin/pip install anthropic"
            )
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is required for anthropic provider")

    def default_model(self) -> str:
        return "claude-sonnet-4-5-20250929"

    def stream_turn(
        self,
        *,
        model: str,
        system: str,
        history: list[dict[str, str]],
        user_input: str,
        max_tokens: int,
    ) -> str:
        assistant_text = ""
        client = Anthropic()
        messages = history + [{"role": "user", "content": user_input}]

        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                assistant_text += text
                _print_stream_text(text)

        console.print()
        return assistant_text


@dataclass
class JsonCliBackend:
    name: str
    executable: str
    model_flag: str
    stream_args: list[str]
    prompt_flag: str
    oauth_path: Path | None = None

    def preflight(self, args: argparse.Namespace) -> None:
        if shutil.which(self.executable) is None:
            raise RuntimeError(f"{self.executable} is not installed or not in PATH")
        if self.oauth_path is not None and not self.oauth_path.exists():
            raise RuntimeError(
                f"OAuth credentials not found at {self.oauth_path}. Please login first."
            )

    def default_model(self) -> str:
        if self.executable == "claude":
            return "claude-sonnet-4-5-20250929"
        return "gemini-3-flash-preview"

    def stream_turn(
        self,
        *,
        model: str,
        system: str,
        history: list[dict[str, str]],
        user_input: str,
        max_tokens: int,
    ) -> str:
        del max_tokens  # CLI controls token budget via its own defaults/options.
        prompt_text = _render_cli_prompt(system, history, user_input)
        cmd = [
            self.executable,
            *self.stream_args,
            self.model_flag,
            model,
            self.prompt_flag,
            prompt_text,
        ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        assistant_text = ""
        for line in proc.stdout:
            raw = line.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except Exception:
                # Keep non-JSON logs hidden by default to avoid noisy UI.
                continue

            if self.executable == "gemini":
                if event.get("type") == "message" and event.get("role") == "assistant":
                    text = str(event.get("content", ""))
                    if event.get("delta"):
                        assistant_text += text
                        _print_stream_text(text)
                continue

            # claude stream-json
            if event.get("type") == "assistant":
                message = event.get("message", {})
                content = message.get("content", [])
                if isinstance(content, list):
                    for chunk in content:
                        if chunk.get("type") == "text":
                            text = str(chunk.get("text", ""))
                            assistant_text += text
                            _print_stream_text(text)
            if event.get("type") == "result" and event.get("is_error"):
                result = str(event.get("result", "Unknown CLI error"))
                raise RuntimeError(result)

        rc = proc.wait()
        console.print()
        if rc != 0:
            raise RuntimeError(f"{self.executable} exited with code {rc}")
        return assistant_text


def _build_registry(args: argparse.Namespace) -> dict[str, StreamBackend]:
    codex_auth_path = Path(args.codex_auth_path)
    return {
        "codex": CodexOpenAIBackend(
            name="codex",
            provider="codex",
            codex_auth_path=codex_auth_path,
        ),
        "openai": CodexOpenAIBackend(
            name="openai",
            provider="openai",
            codex_auth_path=codex_auth_path,
        ),
        "anthropic": AnthropicBackend(name="anthropic"),
        "claude-code": JsonCliBackend(
            name="claude-code",
            executable="claude",
            model_flag="--model",
            stream_args=["--output-format", "stream-json", "--verbose"],
            prompt_flag="-p",
            oauth_path=None,
        ),
        "gemini-cli": JsonCliBackend(
            name="gemini-cli",
            executable="gemini",
            model_flag="--model",
            stream_args=["--output-format", "stream-json"],
            prompt_flag="-p",
            oauth_path=GEMINI_OAUTH_PATH,
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extensible streaming terminal chat (Codex/OpenAI/Anthropic/Claude/Gemini)"
    )
    parser.add_argument(
        "--provider",
        choices=["codex", "openai", "anthropic", "claude-code", "gemini-cli"],
        default="codex",
        help="Streaming backend provider",
    )
    parser.add_argument("--model", default=None, help="Model override")
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
        help="Maximum output tokens (API backends only)",
    )
    parser.add_argument(
        "--list-providers",
        action="store_true",
        default=False,
        help="List available provider backends and exit",
    )
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    registry = _build_registry(args)

    if args.list_providers:
        console.print("Providers:")
        for key in registry.keys():
            console.print(f"- {key}")
        return

    backend = registry[args.provider]
    backend.preflight(args)
    model = args.model or backend.default_model()

    console.print(
        Markdown(
            "### Streaming TUI\n"
            f"- provider: `{args.provider}`\n"
            f"- backend: `{backend.name}`\n"
            f"- model: `{model}`\n"
            "- exit: type `/exit`"
        )
    )

    history: list[dict[str, str]] = []
    while True:
        user_input = _read_user_input()
        if user_input is None:
            break
        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            break

        console.print("[bold cyan]assistant>[/bold cyan] ", end="")
        text = backend.stream_turn(
            model=model,
            system=args.system,
            history=history,
            user_input=user_input,
            max_tokens=args.max_tokens,
        )
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": text})


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        console.print("\n[dim]exiting[/dim]")
    except Exception as exc:
        console.print(f"[red]error:[/red] {exc}")
        sys.exit(1)
