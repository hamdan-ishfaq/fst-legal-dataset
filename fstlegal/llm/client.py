"""Chat client for an OpenAI-compatible server such as ``llama-server``."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float


@dataclass
class ChatClient:
    base_url: str = "http://127.0.0.1:8080"
    model: str = "local"
    temperature: float = 0.2
    max_tokens: int = 2048
    timeout: float = 1800
    # Qwen3 thinks before answering unless told not to; structured outputs do not need it
    extra_body: dict = field(
        default_factory=lambda: {"chat_template_kwargs": {"enable_thinking": False}})
    log: list[dict] = field(default_factory=list)  # every call, for the run trace

    def complete(self, messages: list[dict], json_schema: dict | None = None) -> Completion:
        body = {"model": self.model, "messages": messages, "temperature": self.temperature,
                "max_tokens": self.max_tokens, **self.extra_body}
        if json_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "output", "schema": json_schema}}
        start = time.perf_counter()
        r = httpx.post(f"{self.base_url}/v1/chat/completions", json=body, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage", {})
        out = Completion(data["choices"][0]["message"]["content"],
                         usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                         time.perf_counter() - start)
        self.log.append({"messages": messages, "response": out.text,
                         "prompt_tokens": out.prompt_tokens,
                         "completion_tokens": out.completion_tokens, "seconds": out.seconds})
        return out

    def complete_json(self, messages: list[dict], schema: dict) -> dict:
        return json.loads(self.complete(messages, schema).text)
