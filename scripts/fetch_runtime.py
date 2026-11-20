"""Download the pinned llama.cpp build and model weights into runtime/.

Usage: python scripts/fetch_runtime.py [llama_cpp] [embedding] [rlm]
With no arguments everything is fetched. Downloads resume if interrupted, and
files already complete are skipped.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
CONFIG = tomllib.loads((ROOT / "config" / "runtime.toml").read_text(encoding="utf-8"))


def download(url: str, dest: Path) -> None:
    """Download with resume. Uses curl, which is far faster than a Python
    client against the Hugging Face CDN on this network."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    subprocess.run(["curl", "-L", "--fail", "--retry", "5", "-C", "-", "-o", str(part), url],
                   check=True)
    part.replace(dest)


def fetch_llama_cpp() -> None:
    cfg = CONFIG["llama_cpp"]
    out = RUNTIME / "llama.cpp" / cfg["tag"]
    for asset in cfg["assets"]:
        zip_path = RUNTIME / "downloads" / asset
        if not zip_path.exists():
            url = f"https://github.com/ggml-org/llama.cpp/releases/download/{cfg['tag']}/{asset}"
            print(f"llama.cpp: {asset}")
            download(url, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(out)
    print(f"llama.cpp {cfg['tag']} -> {out}")


def fetch_model(name: str) -> None:
    cfg = CONFIG["models"][name]
    out = RUNTIME / "models" / cfg["repo"].replace("/", "__")
    for file in cfg["files"]:
        dest = out / file
        if dest.exists():
            continue
        print(f"{name}: {file}")
        url = f"https://huggingface.co/{cfg['repo']}/resolve/{cfg['revision']}/{file}"
        download(url, dest)
    print(f"{name} -> {out}")


def main(targets: list[str]) -> None:
    targets = targets or ["llama_cpp", "embedding", "rlm"]
    for t in targets:
        fetch_llama_cpp() if t == "llama_cpp" else fetch_model(t)


if __name__ == "__main__":
    main(sys.argv[1:])
