import asyncio
import json
import os
from dataclasses import dataclass
from typing import Awaitable, Callable


UpdateCallback = Callable[[str], Awaitable[None]]


def _expand_env(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


@dataclass
class AgentConfig:
    command: str
    args: list[str]
    working_dir: str
    env: dict[str, str]


class AcpConnection:
    def __init__(self, config: AgentConfig):
        self._config = config
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._notify_queue: asyncio.Queue | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._next_id = 1
        self._session_id: str | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        env = os.environ.copy()
        env.update({key: _expand_env(value) for key, value in self._config.env.items()})
        self._proc = await asyncio.create_subprocess_exec(
            self._config.command,
            *self._config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._config.working_dir,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())
        await self.initialize()
        await self.session_new()

    def alive(self) -> bool:
        return (
            self._proc is not None
            and self._proc.returncode is None
            and self._reader_task is not None
            and not self._reader_task.done()
        )

    async def initialize(self) -> None:
        await self._send_request(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {},
                "clientInfo": {"name": "discord-echo-bot", "version": "0.1.0"},
            },
            timeout=120,
        )

    async def session_new(self) -> None:
        response = await self._send_request(
            "session/new",
            {"cwd": self._config.working_dir, "mcpServers": []},
            timeout=120,
        )
        session_id = response.get("result", {}).get("sessionId")
        if not session_id:
            raise RuntimeError("ACP session/new did not return a sessionId")
        self._session_id = session_id

    async def prompt(self, prompt: str, on_update: UpdateCallback | None = None) -> str:
        async with self._lock:
            if not self.alive():
                raise RuntimeError("ACP connection is not alive")
            if not self._session_id:
                raise RuntimeError("ACP session is not initialized")

            queue: asyncio.Queue = asyncio.Queue()
            self._notify_queue = queue
            request_id = self._next_request_id()
            future = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future

            try:
                await self._send_raw(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "session/prompt",
                        "params": {
                            "sessionId": self._session_id,
                            "prompt": [{"type": "text", "text": prompt}],
                        },
                    }
                )

                parts: list[str] = []
                tool_lines: list[str] = []
                current_display = "..."

                if on_update is not None:
                    await on_update(current_display)

                while True:
                    message = await queue.get()
                    if message.get("id") == request_id:
                        break

                    update = message.get("params", {}).get("update", {})
                    kind = update.get("sessionUpdate")
                    if kind == "agent_message_chunk":
                        text = update.get("content", {}).get("text", "")
                        if text:
                            parts = _append_text_chunk(parts, text)
                    elif kind == "tool_call":
                        title = update.get("title") or "tool"
                        tool_lines.append(f"🔧 `{title}`...")
                    elif kind == "tool_call_update":
                        title = update.get("title") or "tool"
                        status = update.get("status") or ""
                        if status in {"completed", "failed"}:
                            icon = "✅" if status == "completed" else "❌"
                            for index in range(len(tool_lines) - 1, -1, -1):
                                if title in tool_lines[index]:
                                    tool_lines[index] = f"{icon} `{title}`"
                                    break
                            else:
                                tool_lines.append(f"{icon} `{title}`")

                    new_display = _compose_display(tool_lines, "".join(parts)) or "..."
                    if on_update is not None and new_display != current_display:
                        current_display = new_display
                        await on_update(current_display)

                return "".join(parts).strip()
            finally:
                self._notify_queue = None
                self._pending.pop(request_id, None)

    async def _stderr_loop(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            print(f"[codex-stderr] {line.decode(errors='replace').rstrip()}")

    async def _reader_loop(self) -> None:
        if self._proc is None or self._proc.stdout is None:
            return
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break

            raw = line.decode(errors="replace").strip()
            if not raw:
                continue

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if message.get("method") == "session/request_permission" and message.get("id") is not None:
                await self._send_raw(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {"optionId": "allow_always"},
                    }
                )
                continue

            message_id = message.get("id")
            if message_id is not None and message_id in self._pending:
                future = self._pending.pop(message_id)
                if not future.done():
                    future.set_result(message)
                if self._notify_queue is not None:
                    self._notify_queue.put_nowait(message)
                continue

            if self._notify_queue is not None:
                self._notify_queue.put_nowait(message)

        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("ACP connection closed"))
        self._pending.clear()

    async def _send_request(self, method: str, params: dict, timeout: int = 30) -> dict:
        if self._proc is None:
            raise RuntimeError("ACP process not started")

        request_id = self._next_request_id()
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send_raw(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            response = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

        error = response.get("error")
        if error:
            raise RuntimeError(f"ACP {method} failed: {error}")
        return response

    async def _send_raw(self, message: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("ACP process stdin is unavailable")
        data = json.dumps(message) + "\n"
        self._proc.stdin.write(data.encode())
        await self._proc.stdin.drain()

    def _next_request_id(self) -> int:
        current = self._next_id
        self._next_id += 1
        return current


class SessionPool:
    def __init__(self, config: AgentConfig):
        self._config = config
        self._connections: dict[str, AcpConnection] = {}
        self._lock = asyncio.Lock()

    def has_session(self, session_key: str) -> bool:
        connection = self._connections.get(session_key)
        return connection is not None and connection.alive()

    async def get_or_create(self, session_key: str) -> AcpConnection:
        async with self._lock:
            connection = self._connections.get(session_key)
            if connection is not None and connection.alive():
                return connection

            connection = AcpConnection(self._config)
            await connection.start()
            self._connections[session_key] = connection
            return connection


def _compose_display(tool_lines: list[str], text: str) -> str:
    output = []
    if tool_lines:
        output.extend(tool_lines)
        output.append("")
    if text.strip():
        output.append(text.strip())
    return "\n".join(output).strip()


def _append_text_chunk(parts: list[str], chunk: str) -> list[str]:
    if not chunk:
        return parts

    existing = "".join(parts)
    if not existing:
        parts.append(chunk)
        return parts

    if existing.endswith(chunk):
        return parts

    max_overlap = min(len(existing), len(chunk))
    for overlap in range(max_overlap, 0, -1):
        if existing.endswith(chunk[:overlap]):
            parts.append(chunk[overlap:])
            return parts

    parts.append(chunk)
    return parts
