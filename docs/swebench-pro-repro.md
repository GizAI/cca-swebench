# SWE-Bench Pro Reproducible Runbook

This runbook provides an end-to-end, reproducible path to:
- generate patches with `cca` + `gpt-5.3-codex-spark`
- evaluate with the official SWE-Bench Pro evaluator (`scaleapi/SWE-bench_Pro-os`)
- produce a final score artifact

## 1) Environment

From `~/opensources/cca-swebench`:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install swebench tiktoken transformers
python3 -m pip install --user -e .
```

Auth requirements:
- `codex login` completed
- `~/.codex/auth.json` exists
- `~/.codex/models_cache.json` exists

## 2) Official Pro Evaluator

```bash
cd /tmp
git clone https://github.com/scaleapi/SWE-bench_Pro-os.git
```

## 3) Single-instance Validation (1 hour timeout)

```bash
cd ~/opensources/cca-swebench
.venv/bin/python scripts/run_swebench_pro_codex.py \
  --provider codex \
  --model gpt-5.3-codex-spark \
  --generation-workers 1 \
  --eval-workers 1 \
  --timeout-sec 3600 \
  --eval-repo /tmp/SWE-bench_Pro-os \
  --run-root artifacts/swebench_pro_onehour_single \
  --instance-id instance_qutebrowser__qutebrowser-f91ace96223cac8161c16dd061907e138fe85111-v059c6fdc75567943479b23ebca7c07b5e9a7f34c
```

Expected outputs:
- generation result: `artifacts/swebench_pro_onehour_single/generation/instances/<instance_id>/result.json`
- evaluation result: `artifacts/swebench_pro_onehour_single/eval/eval_results.json`
- score summary: `artifacts/swebench_pro_onehour_single/score_summary.json`

## 4) Full test split run

```bash
cd ~/opensources/cca-swebench
.venv/bin/python scripts/run_swebench_pro_codex.py \
  --provider codex \
  --model gpt-5.3-codex-spark \
  --generation-workers 24 \
  --eval-workers 24 \
  --timeout-sec 3600 \
  --eval-repo /tmp/SWE-bench_Pro-os \
  --run-root artifacts/swebench_pro_codex53spark_full
```

## 5) Real-time Monitoring

Progress summary (completed statuses and patch count):

```bash
watch -n 2 'cd ~/opensources/cca-swebench && python3 - <<'"'"'PY'"'"'
import json
from pathlib import Path
root=Path("artifacts/swebench_pro_codex53spark_full/generation/instances")
counts={}
with_patch=0
n=0
for p in root.glob("*/result.json"):
    n+=1
    d=json.loads(p.read_text())
    s=d.get("status","unknown")
    counts[s]=counts.get(s,0)+1
    if int(d.get("patch_chars",0))>0:
        with_patch+=1
print("completed=", n, "counts=", counts, "with_patch=", with_patch)
PY'
```

Active Codex processes:

```bash
watch -n 2 'pgrep -af "cca --provider codex --model gpt-5.3-codex-spark" | wc -l'
```

## 6) Final score artifacts

At completion:
- `artifacts/.../score_summary.json`
- `artifacts/.../generation_summary.json`
- `artifacts/.../eval/eval_results.json`

Quick score readout:

```bash
python3 - <<'PY'
import json
from pathlib import Path
summary = json.loads(Path("artifacts/swebench_pro_codex53spark_full/score_summary.json").read_text())
print("total_instances:", summary["total_instances"])
print("evaluated_instances:", summary["evaluated_instances"])
print("solved_instances:", summary["solved_instances"])
print("overall_score:", summary["overall_score"])
PY
```

## 7) Notes

- `429 usage_limit_reached` is a provider quota event, not a harness bug.
- Re-run after quota reset using the same command and run root.
- Use `--force` only when you explicitly want to re-run completed instances.
