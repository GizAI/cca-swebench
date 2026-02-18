import argparse
import io
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import cca


class _FakeStdin(io.StringIO):
    def __init__(self, value: str, *, tty: bool) -> None:
        super().__init__(value)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.mark.asyncio
async def test_quiet_stdio_interface_echo_is_suppressed() -> None:
    io_iface = cca.QuietStdIOInterface()
    await io_iface._echo("hello")
    await io_iface._echo_input("hello")


def test_read_prompt_and_file_or_text(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("hello\n", encoding="utf-8")
    assert cca._read_prompt(prompt_file) == "hello"
    assert cca._read_prompt_file_or_text(str(prompt_file)) == ("hello", str(prompt_file))
    assert cca._read_prompt_file_or_text("inline prompt") == ("inline prompt", "inline")

    empty_file = tmp_path / "empty.txt"
    empty_file.write_text(" \n", encoding="utf-8")
    with pytest.raises(ValueError):
        cca._read_prompt(empty_file)
    with pytest.raises(ValueError):
        cca._read_prompt_file_or_text("   ")
    with pytest.raises(FileNotFoundError):
        cca._read_prompt(tmp_path / "missing.txt")


def test_read_prompt_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdin("", tty=True))
    with pytest.raises(ValueError):
        cca._read_prompt_stdin()

    monkeypatch.setattr(sys, "stdin", _FakeStdin("   ", tty=False))
    with pytest.raises(ValueError):
        cca._read_prompt_stdin()

    monkeypatch.setattr(sys, "stdin", _FakeStdin("from stdin\n", tty=False))
    assert cca._read_prompt_stdin() == "from stdin"


def test_mode_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    args = argparse.Namespace(tui=True, prompt=None)
    assert cca._should_run_tui(args) is True
    args = argparse.Namespace(tui=False, prompt="x")
    assert cca._should_run_tui(args) is False
    args = argparse.Namespace(tui=False, prompt=None)
    monkeypatch.setattr(sys, "stdin", _FakeStdin("", tty=True))
    assert cca._should_run_tui(args) is True
    monkeypatch.setattr(sys, "stdin", _FakeStdin("", tty=False))
    assert cca._should_run_tui(args) is False


def test_discover_provider_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cca, "discover_codex_models", lambda: ["c1"])
    monkeypatch.setattr(cca, "discover_gemini_models_live", lambda _p: ["g1"])
    codex, gemini = cca._discover_provider_models("codex", Path("/tmp/x"))
    assert codex == ["c1"]
    assert gemini == []
    codex, gemini = cca._discover_provider_models("gemini", Path("/tmp/x"))
    assert codex == []
    assert gemini == ["g1"]
    codex, gemini = cca._discover_provider_models("openai", Path("/tmp/x"))
    assert codex == []
    assert gemini == []


def test_print_runtime_summary(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com")
    monkeypatch.setenv("OPENAI_CHATGPT_ACCOUNT_ID", "aid")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_USE_OAUTH", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "l")
    cca._print_runtime_summary(
        provider="codex",
        model="m",
        entry_name="Code",
        prompt_source="inline",
        tui_mode=False,
    )
    out = capsys.readouterr().out
    assert "provider=codex" in out
    assert "mode=oneshot" in out
    assert "OPENAI_CHATGPT_ACCOUNT_ID=set" in out


def test_handle_model_listing_paths(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cca,
        "list_models",
        lambda *_: types.SimpleNamespace(provider="codex", models=["m1"], aliases={"a": "m1"}),
    )
    monkeypatch.setattr(cca, "prepare_codex_env", lambda *_: None)
    monkeypatch.setattr(cca, "validate_codex_model_live", lambda *_: (True, "ok"))
    cca._handle_model_listing(
        provider="codex",
        codex_auth_path=Path("/tmp/c"),
        gemini_oauth_path=Path("/tmp/g"),
        validate_models_live=True,
    )
    out = capsys.readouterr().out
    assert "Provider: codex" in out
    assert "OK m1: ok" in out
    assert "Aliases:" in out

    cca._handle_model_listing(
        provider="codex",
        codex_auth_path=Path("/tmp/c"),
        gemini_oauth_path=Path("/tmp/g"),
        validate_models_live=False,
    )
    out = capsys.readouterr().out
    assert "Live validation:" not in out

    monkeypatch.setattr(
        cca,
        "list_models",
        lambda *_: types.SimpleNamespace(provider="gemini", models=["g1"], aliases={}),
    )
    monkeypatch.setattr(cca, "validate_gemini_model_live", lambda *_: (False, "bad"))
    cca._handle_model_listing(
        provider="gemini",
        codex_auth_path=Path("/tmp/c"),
        gemini_oauth_path=Path("/tmp/g"),
        validate_models_live=True,
    )
    out = capsys.readouterr().out
    assert "FAIL g1: bad" in out

    monkeypatch.setattr(
        cca,
        "list_models",
        lambda *_: types.SimpleNamespace(provider="openai", models=["o1"], aliases={}),
    )
    cca._handle_model_listing(
        provider="openai",
        codex_auth_path=Path("/tmp/c"),
        gemini_oauth_path=Path("/tmp/g"),
        validate_models_live=True,
    )
    out = capsys.readouterr().out
    assert "live validation is supported for codex and gemini providers" in out

    monkeypatch.setattr(
        cca,
        "list_models",
        lambda *_: types.SimpleNamespace(provider="custom", models=[], aliases={}),
    )
    cca._handle_model_listing(
        provider="custom",
        codex_auth_path=Path("/tmp/c"),
        gemini_oauth_path=Path("/tmp/g"),
        validate_models_live=True,
    )
    out = capsys.readouterr().out
    assert "no discovered models to validate" in out


@pytest.mark.asyncio
async def test_read_user_input(monkeypatch: pytest.MonkeyPatch) -> None:
    class _IO:
        async def get_input(self, **_kwargs):
            return "tty-input"

    cf = types.SimpleNamespace(io=_IO())
    monkeypatch.setattr(sys, "stdin", _FakeStdin("", tty=True))
    assert await cca._read_user_input(cf) == "tty-input"

    monkeypatch.setattr(sys, "stdin", _FakeStdin("", tty=False))
    assert await cca._read_user_input(cf) is None

    monkeypatch.setattr(sys, "stdin", _FakeStdin("line\n", tty=False))
    assert await cca._read_user_input(cf) == "line"


@pytest.mark.asyncio
async def test_invoke_turn_success_and_errors(capsys: pytest.CaptureFixture[str]) -> None:
    class _IO:
        def __init__(self) -> None:
            self.cancelled = 0
            self.errors: list[str] = []

        async def on_cancel(self) -> None:
            self.cancelled += 1

        async def error(self, text: str) -> None:
            self.errors.append(text)

    class _CF:
        def __init__(self, behavior: str, exiting: bool = False) -> None:
            self.behavior = behavior
            self.exiting = exiting
            self.io = _IO()
            self.saved = 0

        async def invoke_analect(self, *_args) -> None:
            if self.behavior == "ok":
                return
            if self.behavior == "cancel":
                raise asyncio.CancelledError()
            raise RuntimeError("boom")

        async def save(self, **_kwargs) -> None:
            self.saved += 1

    import asyncio

    ok = _CF("ok")
    await cca._invoke_turn(ok, "Code", "hello")
    assert ok.saved == 1

    cancelled = _CF("cancel", exiting=False)
    await cca._invoke_turn(cancelled, "Code", "hello")
    assert cancelled.io.cancelled == 1
    assert cancelled.saved == 1

    cancelled_raise = _CF("cancel", exiting=True)
    with pytest.raises(asyncio.CancelledError):
        await cca._invoke_turn(cancelled_raise, "Code", "hello")
    assert cancelled_raise.saved == 1

    failed = _CF("error")
    await cca._invoke_turn(failed, "Code", "hello")
    assert failed.saved == 1
    assert failed.io.errors and "boom" in failed.io.errors[0]
    assert "tests/test_cca.py" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_run_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _IO:
        async def rule(self, _title: str) -> None:
            calls.append("rule")

        async def system(self, text: str) -> None:
            calls.append(f"system:{text}")

    class _FakeConfucius:
        def __init__(self, verbose: bool = False, io=None) -> None:
            self.verbose = verbose
            self.io = io or _IO()
            self.exiting = False

        async def cancel_task(self) -> bool:
            calls.append("cancel")
            return True

    fake_confucius_module = types.ModuleType("confucius.lib.confucius")
    fake_confucius_module.Confucius = _FakeConfucius
    monkeypatch.setitem(sys.modules, "confucius.lib.confucius", fake_confucius_module)

    inputs = iter(["   ", "/help", "/model", "hello", "/quit"])

    async def fake_read_user_input(_cf):
        return next(inputs)

    async def fake_invoke_turn(_cf, _entry_name: str, text: str):
        calls.append(f"invoke:{text}")

    class _Loop:
        def add_signal_handler(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(cca, "_read_user_input", fake_read_user_input)
    monkeypatch.setattr(cca, "_invoke_turn", fake_invoke_turn)
    monkeypatch.setattr(cca.asyncio, "get_event_loop", lambda: _Loop())

    await cca._run_tui(
        entry_name="Code",
        verbose=False,
        provider="codex",
        model="gpt-5.3-codex-spark",
        initial_prompt="init",
    )
    assert "invoke:init" in calls
    assert "invoke:hello" in calls


@pytest.mark.asyncio
async def test_run_tui_signal_not_implemented(monkeypatch: pytest.MonkeyPatch) -> None:
    class _IO:
        async def rule(self, _title: str) -> None:
            return None

        async def system(self, _text: str) -> None:
            return None

    class _FakeConfucius:
        def __init__(self, verbose: bool = False, io=None) -> None:
            self.verbose = verbose
            self.io = io or _IO()
            self.exiting = False

        async def cancel_task(self) -> bool:
            return False

    fake_confucius_module = types.ModuleType("confucius.lib.confucius")
    fake_confucius_module.Confucius = _FakeConfucius
    monkeypatch.setitem(sys.modules, "confucius.lib.confucius", fake_confucius_module)

    async def fake_read_user_input(_cf):
        return None

    class _Loop:
        def add_signal_handler(self, *_args, **_kwargs):
            raise NotImplementedError

    monkeypatch.setattr(cca, "_read_user_input", fake_read_user_input)
    monkeypatch.setattr(cca.asyncio, "get_event_loop", lambda: _Loop())
    await cca._run_tui(
        entry_name="Code",
        verbose=False,
        provider="codex",
        model="m",
        initial_prompt=None,
    )


@pytest.mark.asyncio
async def test_run_tui_interrupt_cancels_task(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    class _IO:
        async def rule(self, _title: str) -> None:
            return None

        async def system(self, _text: str) -> None:
            return None

    class _FakeConfucius:
        def __init__(self, verbose: bool = False, io=None) -> None:
            self.verbose = verbose
            self.io = io or _IO()
            self.exiting = False

        async def cancel_task(self) -> bool:
            return False

    fake_confucius_module = types.ModuleType("confucius.lib.confucius")
    fake_confucius_module.Confucius = _FakeConfucius
    monkeypatch.setitem(sys.modules, "confucius.lib.confucius", fake_confucius_module)

    async def fake_read_user_input(_cf):
        await asyncio.sleep(1)
        return None

    class _Loop:
        def add_signal_handler(self, _sig, callback):
            callback()

    monkeypatch.setattr(cca, "_read_user_input", fake_read_user_input)
    monkeypatch.setattr(cca.asyncio, "get_event_loop", lambda: _Loop())
    with pytest.raises(asyncio.CancelledError):
        await cca._run_tui(
            entry_name="Code",
            verbose=False,
            provider="codex",
            model="m",
            initial_prompt=None,
        )


def test_parse_args() -> None:
    args = cca.parse_args(["--provider", "custom", "--model", "x", "--tui"])
    assert args.provider == "custom"
    assert args.model == "x"
    assert args.tui is True
    assert args.solo_mode == "auto"


def test_configure_logging() -> None:
    cca._configure_logging(verbose=False)
    cca._configure_logging(verbose=True)


def test_run_oneshot(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    fake_entry_module = types.ModuleType("confucius.analects.code.entry")
    fake_entry_module.CodeAssistEntry = object
    monkeypatch.setitem(sys.modules, "confucius.analects.code.entry", fake_entry_module)

    async def fake_run_agent_with_prompt(prompt: str, entry_name: str, verbose: bool) -> None:
        called["prompt"] = prompt
        called["entry_name"] = entry_name
        called["verbose"] = verbose

    import scripts.utils as utils

    monkeypatch.setattr(utils, "run_agent_with_prompt", fake_run_agent_with_prompt)
    cca._run_oneshot("hello", "Code", True)
    assert called == {"prompt": "hello", "entry_name": "Code", "verbose": True}


def test_main_paths(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cca, "_configure_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cca, "_handle_model_listing", lambda **_kwargs: None)
    cca.main(["--list-models", "--provider", "custom", "--model", "x"])

    def boom_listing(**_kwargs):
        raise RuntimeError("listing failed")

    monkeypatch.setattr(cca, "_handle_model_listing", boom_listing)
    with pytest.raises(SystemExit):
        cca.main(["--list-models", "--provider", "custom", "--model", "x"])
    assert "listing failed" in capsys.readouterr().err

    monkeypatch.setattr(cca, "_discover_provider_models", lambda *_args: (_ for _ in ()).throw(RuntimeError("prep failed")))
    with pytest.raises(SystemExit):
        cca.main(["--provider", "custom", "--model", "x"])
    assert "prep failed" in capsys.readouterr().err


def test_main_dry_run_and_tui_and_oneshot(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cca, "_discover_provider_models", lambda *_args: ([], []))
    monkeypatch.setattr(cca, "resolve_runtime_model", lambda *_args, **_kwargs: "model-x")
    monkeypatch.setattr(cca, "_print_runtime_summary", lambda **_kwargs: print("dry-run-ok"))
    monkeypatch.setattr(cca, "_should_run_tui", lambda _args: False)
    monkeypatch.setattr(cca, "_read_prompt_file_or_text", lambda _p: ("hello", "inline"))
    monkeypatch.setattr(cca, "_run_oneshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(cca, "_configure_logging", lambda *_args, **_kwargs: None)
    cca.main(["--provider", "custom", "--model", "x", "--prompt", "hi", "--dry-run"])
    assert "dry-run-ok" in capsys.readouterr().out

    async def fake_run_tui(**_kwargs):
        print("tui-ok")

    monkeypatch.setattr(cca, "_should_run_tui", lambda _args: True)
    monkeypatch.setattr(cca, "_run_tui", fake_run_tui)
    cca.main(["--provider", "custom", "--model", "x"])
    assert "tui-ok" in capsys.readouterr().out
    assert os.environ["CCA_SOLO_MODE"] == "0"

    payload = {}

    def fake_run_oneshot(prompt: str, entry_name: str, verbose: bool) -> None:
        payload["prompt"] = prompt
        payload["entry_name"] = entry_name
        payload["verbose"] = verbose

    monkeypatch.setattr(cca, "_should_run_tui", lambda _args: False)
    monkeypatch.setattr(cca, "_read_prompt_stdin", lambda: "stdin prompt")
    monkeypatch.setattr(cca, "_run_oneshot", fake_run_oneshot)
    cca.main(["--provider", "custom", "--model", "x"])
    assert "## Work directory" in payload["prompt"]
    assert payload["entry_name"] == "Code"
    assert payload["verbose"] is False
    assert os.environ["CCA_SOLO_MODE"] == "1"

    monkeypatch.setattr(cca, "_read_prompt_stdin", lambda: "stdin prompt")
    monkeypatch.setattr(cca, "_run_oneshot", lambda *_args, **_kwargs: None)
    cca.main(["--provider", "custom", "--model", "x", "--solo-mode", "off"])
    assert os.environ["CCA_SOLO_MODE"] == "0"

    monkeypatch.setattr(cca, "_should_run_tui", lambda _args: True)
    monkeypatch.setattr(cca, "_run_tui", fake_run_tui)
    cca.main(["--provider", "custom", "--model", "x", "--solo-mode", "on"])
    assert os.environ["CCA_SOLO_MODE"] == "1"

    monkeypatch.setattr(cca, "_should_run_tui", lambda _args: False)
    monkeypatch.setattr(cca, "_read_prompt_stdin", lambda: None)
    with pytest.raises(SystemExit):
        cca.main(["--provider", "custom", "--model", "x"])
    assert "No prompt provided for one-shot mode" in capsys.readouterr().err

    def fail_oneshot(*_args, **_kwargs):
        raise RuntimeError("oneshot boom")

    monkeypatch.setattr(cca, "_read_prompt_stdin", lambda: "ok")
    monkeypatch.setattr(cca, "_run_oneshot", fail_oneshot)
    with pytest.raises(SystemExit):
        cca.main(["--provider", "custom", "--model", "x", "--raw-prompt"])
    assert "oneshot boom" in capsys.readouterr().err


def test_main_sets_cca_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cca, "_discover_provider_models", lambda *_args: ([], []))
    monkeypatch.setattr(cca, "resolve_runtime_model", lambda *_args, **_kwargs: "the-model")
    monkeypatch.setattr(cca, "_should_run_tui", lambda _args: True)
    monkeypatch.setattr(cca, "_configure_logging", lambda *_args, **_kwargs: None)

    async def fake_run_tui(**_kwargs):
        return None

    monkeypatch.setattr(cca, "_run_tui", fake_run_tui)
    monkeypatch.delenv("CCA_MODEL", raising=False)
    cca.main(["--provider", "custom", "--model", "x"])
    assert os.environ["CCA_MODEL"] == "the-model"


def test_cli_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cca, "main", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    cca.cli()
