#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datasets import load_dataset


@dataclass(frozen=True)
class Instance:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str


def _repo_slug(repo: str) -> str:
    return repo.replace("/", "__")


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _load_instances(dataset_name: str, split: str) -> list[Instance]:
    dataset = load_dataset(dataset_name, split=split)
    instances: list[Instance] = []
    for row in dataset:
        instances.append(
            Instance(
                instance_id=row["instance_id"],
                repo=row["repo"],
                base_commit=row["base_commit"],
                problem_statement=row["problem_statement"],
            )
        )
    return instances


def _write_raw_sample_jsonl(dataset_name: str, split: str, out_path: Path) -> None:
    dataset = load_dataset(dataset_name, split=split)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in dataset:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


class Generator:
    def __init__(
        self,
        *,
        run_root: Path,
        provider: str,
        model: str,
        timeout_sec: int,
        keep_checkout: bool,
    ) -> None:
        self.run_root = run_root
        self.provider = provider
        self.model = model
        self.timeout_sec = timeout_sec
        self.keep_checkout = keep_checkout
        self.mirror_root = run_root / "generation" / "repos"
        self.instances_root = run_root / "generation" / "instances"
        self.mirror_root.mkdir(parents=True, exist_ok=True)
        self.instances_root.mkdir(parents=True, exist_ok=True)
        self.repo_locks: dict[str, threading.Lock] = {}
        self.repo_locks_lock = threading.Lock()

    def _repo_lock(self, repo: str) -> threading.Lock:
        with self.repo_locks_lock:
            lock = self.repo_locks.get(repo)
            if lock is None:
                lock = threading.Lock()
                self.repo_locks[repo] = lock
            return lock

    def _mirror_path(self, repo: str) -> Path:
        return self.mirror_root / f"{_repo_slug(repo)}.git"

    def _ensure_repo_mirror(self, repo: str) -> Path:
        mirror_path = self._mirror_path(repo)
        lock = self._repo_lock(repo)
        with lock:
            if mirror_path.exists():
                res = _run(["git", "-C", str(mirror_path), "remote", "update", "--prune"])
                if res.returncode != 0:
                    raise RuntimeError(
                        f"Failed to update mirror for {repo}: {res.stderr.strip() or res.stdout.strip()}"
                    )
                return mirror_path
            remote = f"https://github.com/{repo}.git"
            res = _run(["git", "clone", "--mirror", remote, str(mirror_path)])
            if res.returncode != 0:
                raise RuntimeError(
                    f"Failed to clone mirror for {repo}: {res.stderr.strip() or res.stdout.strip()}"
                )
            return mirror_path

    def _instance_paths(self, instance_id: str) -> dict[str, Path]:
        base = self.instances_root / instance_id
        return {
            "base": base,
            "result": base / "result.json",
            "prompt": base / "problem.txt",
            "log": base / "run.log",
            "patch": base / "patch.diff",
            "checkout": base / "repo",
        }

    def _read_existing_result(self, result_path: Path) -> dict[str, Any] | None:
        if not result_path.exists():
            return None
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def run_instance(self, instance: Instance, *, force: bool = False) -> dict[str, Any]:
        paths = self._instance_paths(instance.instance_id)
        paths["base"].mkdir(parents=True, exist_ok=True)

        if not force:
            existing = self._read_existing_result(paths["result"])
            if existing is not None and existing.get("status") in {"success", "error", "timeout"}:
                existing["skipped"] = True
                return existing

        start = time.time()
        result: dict[str, Any] = {
            "instance_id": instance.instance_id,
            "repo": instance.repo,
            "base_commit": instance.base_commit,
            "provider": self.provider,
            "model": self.model,
            "started_at": int(start),
        }

        checkout = paths["checkout"]
        if checkout.exists():
            shutil.rmtree(checkout)

        try:
            mirror = self._ensure_repo_mirror(instance.repo)
            clone_res = _run(["git", "clone", str(mirror), str(checkout)])
            if clone_res.returncode != 0:
                raise RuntimeError(
                    f"clone failed: {clone_res.stderr.strip() or clone_res.stdout.strip()}"
                )

            co_res = _run(["git", "checkout", instance.base_commit], cwd=checkout)
            if co_res.returncode != 0:
                raise RuntimeError(
                    f"checkout failed: {co_res.stderr.strip() or co_res.stdout.strip()}"
                )

            paths["prompt"].write_text(instance.problem_statement.strip() + "\n", encoding="utf-8")

            env = os.environ.copy()
            env.setdefault("PYTHONUTF8", "1")

            cmd = [
                "cca",
                "--provider",
                self.provider,
                "--model",
                self.model,
                "--prompt",
                str(paths["prompt"]),
                "--entry-name",
                "Code",
                "--solo-mode",
                "on",
            ]

            try:
                run_res = _run(cmd, cwd=checkout, timeout=self.timeout_sec, env=env)
                timed_out = False
                stdout = _coerce_text(run_res.stdout)
                stderr = _coerce_text(run_res.stderr)
                return_code = run_res.returncode
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                stdout = _coerce_text(exc.stdout)
                stderr = _coerce_text(exc.stderr) + "\n[TIMEOUT]"
                return_code = 124

            paths["log"].write_text(
                "== STDOUT ==\n"
                + (stdout or "")
                + "\n\n== STDERR ==\n"
                + (stderr or ""),
                encoding="utf-8",
            )

            patch_res = _run(["git", "diff"], cwd=checkout)
            patch_text = patch_res.stdout if patch_res.returncode == 0 else ""
            paths["patch"].write_text(patch_text, encoding="utf-8")

            files_res = _run(["git", "diff", "--name-only"], cwd=checkout)
            changed_files = [line.strip() for line in files_res.stdout.splitlines() if line.strip()]

            result.update(
                {
                    "status": "timeout" if timed_out else ("success" if return_code == 0 else "error"),
                    "return_code": return_code,
                    "timed_out": timed_out,
                    "error": (
                        ""
                        if timed_out or return_code == 0
                        else (stderr.strip().splitlines()[-1] if stderr.strip() else "non-zero exit")
                    ),
                    "patch_chars": len(patch_text),
                    "changed_files": changed_files,
                    "changed_files_count": len(changed_files),
                }
            )

        except Exception as exc:  # noqa: BLE001
            result.update(
                {
                    "status": "error",
                    "return_code": -1,
                    "timed_out": False,
                    "error": str(exc),
                    "patch_chars": 0,
                    "changed_files": [],
                    "changed_files_count": 0,
                }
            )
        finally:
            if not self.keep_checkout and checkout.exists():
                shutil.rmtree(checkout, ignore_errors=True)
            end = time.time()
            result["ended_at"] = int(end)
            result["duration_sec"] = round(end - start, 3)
            paths["result"].write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        return result


def _collect_patches(instances: list[Instance], run_root: Path, prefix: str) -> Path:
    instances_root = run_root / "generation" / "instances"
    patches: list[dict[str, Any]] = []
    for instance in instances:
        inst_dir = instances_root / instance.instance_id
        patch_path = inst_dir / "patch.diff"
        patch = patch_path.read_text(encoding="utf-8") if patch_path.exists() else ""
        patches.append(
            {
                "instance_id": instance.instance_id,
                "patch": patch,
                "prefix": prefix,
            }
        )
    out_path = run_root / "patches.json"
    out_path.write_text(json.dumps(patches, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def _summarize_generation(results: list[dict[str, Any]], total_instances: int) -> dict[str, Any]:
    success = sum(1 for r in results if r.get("status") == "success")
    timeout = sum(1 for r in results if r.get("status") == "timeout")
    error = sum(1 for r in results if r.get("status") == "error")
    with_patch = sum(1 for r in results if int(r.get("patch_chars", 0)) > 0)
    changed = sum(1 for r in results if int(r.get("changed_files_count", 0)) > 0)
    return {
        "total_instances": total_instances,
        "attempted": len(results),
        "success": success,
        "timeout": timeout,
        "error": error,
        "with_patch": with_patch,
        "with_changed_files": changed,
    }


def _run_official_eval(
    *,
    run_root: Path,
    eval_repo: Path,
    raw_sample_path: Path,
    patches_path: Path,
    eval_workers: int,
    dockerhub_username: str,
) -> tuple[int, str, str]:
    eval_out = run_root / "eval"
    eval_out.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(eval_repo / "swe_bench_pro_eval.py"),
        "--raw_sample_path",
        str(raw_sample_path),
        "--patch_path",
        str(patches_path),
        "--output_dir",
        str(eval_out),
        "--scripts_dir",
        str(eval_repo / "run_scripts"),
        "--num_workers",
        str(eval_workers),
        "--dockerhub_username",
        dockerhub_username,
        "--use_local_docker",
    ]
    proc = _run(cmd, cwd=eval_repo)
    (run_root / "eval.log").write_text(
        "== CMD ==\n"
        + " ".join(cmd)
        + "\n\n== STDOUT ==\n"
        + proc.stdout
        + "\n\n== STDERR ==\n"
        + proc.stderr,
        encoding="utf-8",
    )
    return proc.returncode, proc.stdout, proc.stderr


def _read_eval_results(eval_results_path: Path) -> dict[str, bool]:
    if not eval_results_path.exists():
        return {}
    data = json.loads(eval_results_path.read_text(encoding="utf-8"))
    return {str(k): bool(v) for k, v in data.items()}


def parse_args() -> argparse.Namespace:
    cpu = os.cpu_count() or 8
    parser = argparse.ArgumentParser(description="Run Codex SWE-Bench Pro generation + official evaluation")
    parser.add_argument("--dataset", default="ScaleAI/SWE-bench_Pro")
    parser.add_argument("--split", default="test")
    parser.add_argument("--provider", default="codex", choices=["codex", "openai", "gemini", "bedrock", "custom"])
    parser.add_argument("--model", default="gpt-5.3-codex-spark")
    parser.add_argument("--generation-workers", type=int, default=max(2, min(12, cpu // 2)))
    parser.add_argument("--eval-workers", type=int, default=max(2, min(24, cpu - 4)))
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--run-root", type=Path, default=Path("artifacts") / "swebench_pro_codex53spark")
    parser.add_argument("--eval-repo", type=Path, default=Path("/tmp/SWE-bench_Pro-os"))
    parser.add_argument("--dockerhub-username", default="jefzda")
    parser.add_argument(
        "--instance-id",
        action="append",
        default=[],
        help="Run only selected instance_id (repeatable)",
    )
    parser.add_argument("--force", action="store_true", help="Re-run instances even if result.json exists")
    parser.add_argument("--keep-checkout", action="store_true", help="Keep per-instance checked-out repo")
    parser.add_argument("--skip-eval", action="store_true", help="Skip official evaluation step")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_root = args.run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    started_at = int(time.time())

    instances = _load_instances(args.dataset, args.split)
    if args.instance_id:
        selected = set(args.instance_id)
        instances = [instance for instance in instances if instance.instance_id in selected]
        missing = sorted(selected - {instance.instance_id for instance in instances})
        if missing:
            raise ValueError(f"Unknown instance_id(s): {', '.join(missing)}")
        if not instances:
            raise ValueError("No instances selected")
    raw_sample_path = run_root / "raw_sample.jsonl"
    _write_raw_sample_jsonl(args.dataset, args.split, raw_sample_path)

    generator = Generator(
        run_root=run_root,
        provider=args.provider,
        model=args.model,
        timeout_sec=args.timeout_sec,
        keep_checkout=args.keep_checkout,
    )

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.generation_workers) as executor:
        future_map = {
            executor.submit(generator.run_instance, instance, force=args.force): instance
            for instance in instances
        }
        for idx, future in enumerate(concurrent.futures.as_completed(future_map), start=1):
            instance = future_map[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = {
                    "instance_id": instance.instance_id,
                    "repo": instance.repo,
                    "base_commit": instance.base_commit,
                    "status": "error",
                    "error": str(exc),
                    "return_code": -1,
                    "timed_out": False,
                    "patch_chars": 0,
                    "changed_files_count": 0,
                }
            results.append(result)
            if idx % 10 == 0 or idx == len(instances):
                print(
                    f"[generation] {idx}/{len(instances)} complete | "
                    f"success={sum(1 for r in results if r.get('status') == 'success')} "
                    f"timeout={sum(1 for r in results if r.get('status') == 'timeout')} "
                    f"error={sum(1 for r in results if r.get('status') == 'error')}"
                , flush=True)

    generation_summary = _summarize_generation(results, len(instances))
    (run_root / "generation_summary.json").write_text(
        json.dumps(generation_summary, indent=2) + "\n",
        encoding="utf-8",
    )

    patches_path = _collect_patches(instances, run_root, prefix=f"{args.provider}-{args.model}")

    eval_return_code = None
    if not args.skip_eval:
        if not args.eval_repo.exists():
            raise FileNotFoundError(
                f"Official eval repo not found at {args.eval_repo}. Clone https://github.com/scaleapi/SWE-bench_Pro-os"
            )
        eval_return_code, _, _ = _run_official_eval(
            run_root=run_root,
            eval_repo=args.eval_repo,
            raw_sample_path=raw_sample_path,
            patches_path=patches_path,
            eval_workers=args.eval_workers,
            dockerhub_username=args.dockerhub_username,
        )

    eval_results_path = run_root / "eval" / "eval_results.json"
    eval_results = _read_eval_results(eval_results_path)

    total = len(instances)
    solved = sum(1 for v in eval_results.values() if v)
    evaluated = len(eval_results)
    overall_score = solved / total if total else 0.0

    summary = {
        "started_at": started_at,
        "ended_at": int(time.time()),
        "dataset": args.dataset,
        "split": args.split,
        "provider": args.provider,
        "model": args.model,
        "generation_workers": args.generation_workers,
        "eval_workers": args.eval_workers,
        "timeout_sec": args.timeout_sec,
        "total_instances": total,
        "evaluated_instances": evaluated,
        "solved_instances": solved,
        "overall_score": overall_score,
        "generation_summary": generation_summary,
        "eval_return_code": eval_return_code,
        "paths": {
            "run_root": str(run_root),
            "raw_sample": str(raw_sample_path),
            "patches": str(patches_path),
            "eval_results": str(eval_results_path),
        },
    }

    (run_root / "score_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
