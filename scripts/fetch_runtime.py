"""Download the pinned llama.cpp build and model weights into runtime/.

Usage: python scripts/fetch_runtime.py [llama_cpp] [embedding] [rlm]
With no arguments everything is fetched. Downloads resume if interrupted, and
files already complete are skipped.
"""

from __future__ import annotations

import sys
import tomllib
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
CONFIG = tomllib.loads((ROOT / "config" / "runtime.toml").read_text(encoding="utf-8"))


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as r:
        if r.status_code == 416:  # already complete
            part.replace(dest)
            return
        r.raise_for_status()
        total = done + int(r.headers.get("content-length", 0))
        with part.open("ab" if done else "wb") as f:
            for i, chunk in enumerate(r.iter_bytes(1 << 20)):
                f.write(chunk)
                done += len(chunk)
                if i % 256 == 0:
                    print(f"  {dest.name}: {done / 1e9:.2f} / {total / 1e9:.2f} GB", flush=True)
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
