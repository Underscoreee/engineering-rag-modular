#!/usr/bin/env python3
"""Record the local-only MinerU runtime and host capabilities."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--mineru-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    environment = os.environ.copy()
    environment["MINERU_HOME"] = str(args.mineru_home.resolve())
    version = _run([str(args.executable), "version", "--json"], environment)
    model_info = _run([str(args.executable.parent / "mineru-kit"), "models", "show"], environment)
    parse_help = _run([str(args.executable.parent / "mineru-kit"), "parse", "--help"], environment)
    gpu = _run(["nvidia-smi"], environment) if shutil.which("nvidia-smi") else None
    memory = _proc_memory()
    disk = shutil.disk_usage(args.output.parent)
    payload = {
        "platform": platform.platform(),
        "wsl": "microsoft" in platform.release().lower(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "cpu_model": _cpu_model(),
        "memory": memory,
        "disk": {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free},
        "mineru_home": str(args.mineru_home.resolve()),
        "local_only": True,
        "mineru_version": version,
        "model_configuration": model_info,
        "parse_help": parse_help,
        "nvidia_smi": gpu,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(args.output)
    return 0


def _run(argv: list[str], environment: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-16_384:],
        "stderr": completed.stderr[-16_384:],
    }


def _proc_memory() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            name, raw = line.split(":", maxsplit=1)
            if name in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                values[f"{name.lower()}_bytes"] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {}
    return values


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", maxsplit=1)[1].strip()
    except (OSError, IndexError):
        return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
