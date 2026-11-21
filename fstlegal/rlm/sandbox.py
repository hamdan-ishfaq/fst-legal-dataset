"""The REPL the root model writes code into, in a separate process (SDS 3.5).

Model-written code runs in a child process with a time limit, a whitelist of
modules and no ``open``. Its only way to reach data or the model is through
tool stubs that send the call to the parent over a pipe; the parent decides
what each tool may return. This keeps a confused or manipulated model from
reading files, but it is not a security boundary against deliberately hostile
Python (object introspection can still reach builtins), which is why the
parent never hands the child anything it may not see.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import multiprocessing as mp
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any

ALLOWED_MODULES = {"re", "json", "math", "statistics", "collections", "itertools", "functools",
                   "textwrap", "string", "datetime", "difflib", "heapq", "bisect", "operator"}
_BLOCKED_BUILTINS = {"open", "input", "breakpoint", "exit", "quit", "help", "compile"}


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    answer: dict
    variables: list[str]
    timed_out: bool = False


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in ALLOWED_MODULES:
        raise ImportError(f"module {name!r} is not available in this REPL")
    return __import__(name, globals, locals, fromlist, level)


def _execute(code: str, ns: dict) -> None:
    """Run code; like a notebook, print the value of a bare last expression.
    Upstream discards it, but a model not trained on this REPL relies on it."""
    tree = ast.parse(code)
    last = tree.body[-1] if tree.body and isinstance(tree.body[-1], ast.Expr) else None
    if last:
        tree.body.pop()
    exec(compile(tree, "<repl>", "exec"), ns)
    if last:
        value = eval(compile(ast.Expression(last.value), "<repl>", "eval"), ns)
        if value is not None:
            print(repr(value))


def _child(conn: Connection, tool_names: list[str], variables: dict[str, Any]) -> None:
    safe = {k: v for k, v in vars(builtins).items() if k not in _BLOCKED_BUILTINS}
    safe["__import__"] = _guarded_import
    ns: dict[str, Any] = {"__builtins__": safe, "__name__": "__repl__"}

    def stub(name: str) -> Callable:
        def call(*args, **kwargs):
            conn.send(("call", name, args, kwargs))
            status, value = conn.recv()
            if status == "error":
                raise RuntimeError(value)
            return value
        call.__name__ = name
        return call

    def show_vars() -> str:
        return ", ".join(sorted(k for k in ns if not k.startswith("_") and k not in hidden))

    ns.update({name: stub(name) for name in tool_names})
    ns.update(variables)
    ns["SHOW_VARS"] = show_vars
    ns["answer"] = {"content": "", "ready": False}
    hidden = set(tool_names) | {"SHOW_VARS"}

    while True:
        message = conn.recv()
        if message is None:
            return
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                _execute(message, ns)
            except BaseException:  # SystemExit too: the REPL must survive its code
                err.write(traceback.format_exc(limit=2))
        answer = ns.get("answer")
        if not isinstance(answer, dict):
            answer = {}
        content = answer.get("content", "")
        try:  # results must cross the pipe; anything odd goes back as text
            conn.send(("result", out.getvalue(), err.getvalue(),
                       {"content": content, "ready": bool(answer.get("ready"))}, show_vars()))
        except Exception:
            conn.send(("result", out.getvalue(), err.getvalue(),
                       {"content": str(content), "ready": bool(answer.get("ready"))},
                       show_vars()))


class Sandbox:
    def __init__(self, tools: dict[str, Callable], variables: dict[str, Any],
                 timeout: float = 600, max_output: int = 4000):
        self.tools, self.variables = tools, variables
        self.timeout, self.max_output = timeout, max_output
        self._start()

    def _start(self) -> None:
        ctx = mp.get_context("spawn")
        self._conn, child_conn = ctx.Pipe()
        self._proc = ctx.Process(target=_child, args=(child_conn, list(self.tools),
                                                       self.variables), daemon=True)
        self._proc.start()

    def _clip(self, text: str) -> str:
        if len(text) <= self.max_output:
            return text
        return text[:self.max_output] + f"\n... [{len(text) - self.max_output} chars truncated]"

    def run(self, code: str) -> ExecResult:
        """Run code in the persistent namespace. Tool calls are served here, and
        the clock includes them, since sub-calls are where the time goes."""
        self._conn.send(code)
        deadline = time.monotonic() + self.timeout
        while self._conn.poll(max(0.0, deadline - time.monotonic())):
            try:
                kind, *rest = self._conn.recv()
            except EOFError:
                return self._restart("The REPL process ended unexpectedly")
            if kind == "result":
                stdout, stderr, answer, variables = rest
                return ExecResult(self._clip(stdout), self._clip(stderr), answer,
                                  variables.split(", ") if variables else [])
            name, args, kwargs = rest
            try:
                self._conn.send(("ok", self.tools[name](*args, **kwargs)))
            except Exception as e:
                self._conn.send(("error", f"{name} failed: {type(e).__name__}: {e}"))
        return self._restart(f"Timed out after {self.timeout:.0f}s", timed_out=True)

    def _restart(self, why: str, timed_out: bool = False) -> ExecResult:
        self.close()
        self._start()
        return ExecResult("", f"{why}. The REPL was restarted and variables you created are "
                          "gone.", {"content": "", "ready": False}, [], timed_out)

    def close(self) -> None:
        if self._proc.is_alive():
            try:
                self._conn.send(None)
            except OSError:
                pass
            self._proc.join(1)
            if self._proc.is_alive():
                self._proc.kill()
                self._proc.join()

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
