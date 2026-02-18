import io
import sys
from pathlib import Path

import pexpect
import pytest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
CODEX_AUTH = Path.home() / ".codex" / "auth.json"


@pytest.mark.e2e
@pytest.mark.skipif(not CODEX_AUTH.exists(), reason="Codex auth is required at ~/.codex/auth.json")
def test_tui_codex_spark_real_interactive() -> None:
    cmd = f"{PYTHON} -m scripts.cca --provider codex --model gpt-5.3-codex-spark --tui"
    child = pexpect.spawn(
        cmd,
        cwd=str(ROOT),
        encoding="utf-8",
        timeout=240,
    )
    transcript = io.StringIO()
    child.logfile_read = transcript
    try:
        child.expect(r"provider=codex \| model=gpt-5\.3-codex-spark")

        child.sendline("/help")
        child.expect(r"Commands: /help, /model, /exit")

        child.sendline("/model")
        child.expect(r"provider=codex model=gpt-5\.3-codex-spark")

        child.sendline("Run a bash command 'pwd' and reply with the resulting path only.")
        child.expect(str(ROOT))

        child.sendline("/exit")
        child.expect(pexpect.EOF)
    finally:
        if child.isalive():
            child.sendcontrol("c")
            child.close(force=True)

    log = transcript.getvalue()
    assert "HUMAN ─" not in log
    assert "Progress remains **0%**." not in log
    assert child.exitstatus in {0, None}
