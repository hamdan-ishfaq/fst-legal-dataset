"""Start llama-server for the chat model and/or the embedding model.

Usage: python scripts/serve.py chat|embedding [model key from config, e.g. rlm_community]
Settings come from [serve.*] in config/runtime.toml.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / "config" / "runtime.toml").read_text(encoding="utf-8"))


def model_path(key: str) -> Path:
    cfg = CONFIG["models"][key]
    folder = ROOT / "runtime" / "models" / cfg["repo"].replace("/", "__")
    gguf = [f for f in cfg["files"] if f.endswith(".gguf")]
    return folder / gguf[0]


def command(role: str, model: str | None = None) -> list[str]:
    s = CONFIG["serve"][role]
    exe = ROOT / "runtime" / "llama.cpp" / CONFIG["llama_cpp"]["tag"] / "llama-server.exe"
    return [str(exe), "-m", str(model_path(model or s["model"])), "--port", str(s["port"]),
            "-c", str(s["ctx_size"]), "-ngl", str(s["gpu_layers"]), "-np", str(s["parallel"]),
            *s["extra"]]


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "chat"
    cmd = command(role, sys.argv[2] if len(sys.argv) > 2 else None)  # optional [models] key
    print(" ".join(cmd), flush=True)
    sys.exit(subprocess.call(cmd))
