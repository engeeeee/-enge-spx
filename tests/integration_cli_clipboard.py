"""Real pinned Linux TUI -> native image -> captured API payload fixture.

No real account, model or personal clipboard. A loopback-only synthetic API
checks image blocks, not a model's visual understanding. Supply official local
CLI executables; do not download or install tools silently from this script.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time

import pyte
from PySide6.QtGui import QImage, QColor

from enge_spx.clipboard_transfer import Attachment, InputAdapter, text_frame
from enge_spx.smart_terminal import TerminalScreen
from enge_spx.terminal_pty import PosixPTY


class FixtureAPI(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.requests = []
        self.lock = threading.Lock()
        self.got_images = threading.Event()


def image_blocks(value):
    if isinstance(value, dict):
        if value.get("type") in ("image", "input_image"):
            yield value
        else:
            for child in value.values():
                yield from image_blocks(child)
    elif isinstance(value, list):
        for child in value:
            yield from image_blocks(child)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def answer(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_CONNECT(self):
        self.answer({"error": "external_requests_not_part_of_fixture"}, 403)

    def do_GET(self):
        self.answer({"data": [], "object": "list"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 32 * 1024 * 1024:
            return self.answer({"error": "fixture_limit"}, 400)
        value = json.loads(self.rfile.read(length))
        images = list(image_blocks(value))
        summaries = []
        for item in images:
            if item["type"] == "image":
                encoded = item.get("source", {}).get("data", "")
            else:
                image_url = item.get("image_url", "")
                encoded = image_url.split(",", 1)[-1] if isinstance(image_url, str) else ""
            raw = base64.b64decode(encoded, validate=True)
            image = QImage.fromData(raw)
            if image.isNull():
                return self.answer({"error": "invalid_fixture_image"}, 400)
            summaries.append({"type": item["type"], "width": image.width(), "height": image.height(), "pixel": image.pixelColor(10, 10).name(), "sha256": hashlib.sha256(raw).hexdigest()})
        if images:
            # Only non-content evidence. Never store full prompts/base64 data.
            with self.server.lock:
                self.server.requests.append({"route": self.path.split("?", 1)[0], "images": summaries})
            if len(images) == 2:
                self.server.got_images.set()
        if "count_tokens" in self.path:
            return self.answer({"input_tokens": 12})
        if "messages" not in self.path and "responses" not in self.path:
            return self.answer({})
        message = "Synthetic endpoint received the request; this is not a model response."
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        if "messages" in self.path:
            events = [
                {"type": "message_start", "message": {"id": "msg_clipboard_fixture", "type": "message", "role": "assistant", "model": value.get("model", "fixture"), "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 12, "output_tokens": 0}}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": message}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 15}},
                {"type": "message_stop"},
            ]
        else:
            item = {"type": "message", "id": "msg_clipboard_fixture", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": message, "annotations": []}]}
            events = [
                {"type": "response.created", "response": {"id": "resp_clipboard_fixture"}},
                {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}},
                {"type": "response.output_text.delta", "item_id": item["id"], "output_index": 0, "content_index": 0, "delta": message},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": {"id": "resp_clipboard_fixture", "status": "completed", "output": [item], "usage": {"input_tokens": 12, "output_tokens": 15, "total_tokens": 27}}},
            ]
        try:
            for event in events:
                self.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class TUI:
    def __init__(self, command, environment, project):
        self.pty = PosixPTY(command, environment, str(project))
        self.lock = threading.RLock()
        self.screen = TerminalScreen(120, 40, self.pty.write)
        self.pty.resize(120, 40)
        self.stream = pyte.ByteStream(self.screen)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        while True:
            data = self.pty.read()
            if not data:
                return
            with self.lock:
                self.stream.feed(data)

    def text(self):
        with self.lock:
            return "\n".join("".join(self.screen.buffer[y][x].data for x in range(self.screen.columns)) for y in range(self.screen.lines))

    def wait(self, predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            text = self.text()
            if predicate(text):
                return text
            if self.pty.poll() is not None:
                raise AssertionError("Owned CLI exited before clipboard evidence")
            time.sleep(.03)
        raise AssertionError("Real TUI did not reach expected fixture state")

    def close(self):
        self.pty.close()
        self.reader.join(3)


def run_tool(tool, executable):
    if os.name == "nt":
        raise RuntimeError("Native Linux TUI fixture; use Windows API/ConPTY tests separately")
    api = FixtureAPI()
    thread = threading.Thread(target=api.serve_forever, daemon=True)
    thread.start()
    nonce = secrets.token_hex(8)
    key, bridge = secrets.token_hex(8), secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="enge-spx-clip-tui-") as temp:
        base = Path(temp)
        home, project = base / "home", base / "project"
        home.mkdir()
        project.mkdir()
        # Real InputAdapter paths without requiring a root /workspace mount.
        attachments = Path("/tmp") / ("enge-spx-clipboard-" + key) / bridge
        attachments.mkdir(parents=True)
        paths = []
        for color in ("#d97757", "#87bbb6"):
            path = attachments / (secrets.token_hex(16) + ".png")
            image = QImage(160, 100, QImage.Format.Format_RGB32)
            image.fill(QColor(color))
            assert image.save(str(path), "PNG")
            paths.append(path)
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "TMP", "TEMP", "PROGRAMFILES", "PROGRAMFILES(X86)"}
        env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
        endpoint = "http://127.0.0.1:" + str(api.server_port)
        env.update(HOME=str(home), USERPROFILE=str(home), LANG="C.UTF-8", TERM="xterm-256color", COLORTERM="truecolor", NO_PROXY="127.0.0.1,localhost", HTTP_PROXY=endpoint, HTTPS_PROXY=endpoint, DO_NOT_TRACK="1")
        command = [str(Path(executable).resolve())]
        version = (2, 1, 319) if tool == "claude" else (0, 167, 0)
        if tool == "claude":
            env.update(ANTHROPIC_API_KEY="sk-ant-synthetic-fixture-not-real", ANTHROPIC_BASE_URL=endpoint, CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1")
            config = home / ".claude"
            config.mkdir()
            fixture_config = {"numStartups": 1, "firstStartVersion": "2.1.319", "migrationVersion": 14,
                              "opusProMigrationComplete": True, "sonnet1m45MigrationComplete": True,
                              "hasResetAutoModeOptInForDefaultOffer": True,
                              "hasCompletedOnboarding": True, "lastOnboardingVersion": "2.1.319",
                              "customApiKeyResponses": {"approved": [env["ANTHROPIC_API_KEY"][-20:]], "rejected": []},
                              "projects": {str(project): {"hasTrustDialogAccepted": True}}}
            (config / ".claude.json").write_text(json.dumps(fixture_config))
            (config / "settings.json").write_text(json.dumps({"theme": "dark"}))
        else:
            (home / ".codex").mkdir()
            env.update(CODEX_HOME=str(home / ".codex"), SPX_CLIPBOARD_TEST_KEY="synthetic-fixture-not-real")
            command += ["--no-daemon", "-m", "gpt-6-sol", "-c", 'model_provider="clipboard_fixture"',
                        "-c", 'model_providers.clipboard_fixture.name="Clipboard Fixture"',
                        "-c", 'model_providers.clipboard_fixture.base_url="' + endpoint + '/v1"',
                        "-c", 'model_providers.clipboard_fixture.wire_api="responses"',
                        "-c", 'model_providers.clipboard_fixture.requires_openai_auth=false',
                        "-c", 'model_providers.clipboard_fixture.supports_websockets=false',
                        "-c", 'model_providers.clipboard_fixture.env_key="SPX_CLIPBOARD_TEST_KEY"',
                        "-c", 'check_for_update_on_startup=false']
        tui = TUI(command, env, project)
        try:
            for _ in range(10):
                text = tui.wait(lambda value: any(x in value for x in ("custom API key", "Yes, I trust this folder", "To get started", "Claude Code v", "OpenAI Codex")))
                if "custom API key" in text:
                    tui.pty.write(b"\x1b[A\r")
                elif "Yes, I trust this folder" in text:
                    tui.pty.write(b"\x1b[B\r")
                elif "Claude Code v" in text and "Welcome to" not in text:
                    break
                elif "To get started" in text:
                    break
                time.sleep(.5)
            # Wait for the actual composer, not an onboarding/trust/menu input.
            tui.wait(lambda value: ("❯" in value and "Claude Code v" in value and "Yes, I trust" not in value) if tool == "claude" else ("To get started" in value or "GPT-6-Sol" in value))
            tui.pty.write(text_frame("请分析图片 " + nonce + "："))
            adapter = InputAdapter(tool, version)
            first = time.monotonic()
            for i, path in enumerate(paths, 1):
                for frame, image in adapter.events([Attachment(str(path), True, "图片-" + str(i) + ".png")]):
                    tui.pty.write(frame)
                    if image:
                        tui.wait(lambda value: "[Image #" + str(i) + "]" in value)
            tui.pty.write(text_frame(" 保留这段后续文字"))
            tui.wait(lambda value: nonce in value and "[Image #2]" in value and "后续文字" in value)
            with api.lock:
                assert not api.requests, "Pasting must not submit any image data before Enter"
            alive_pid = tui.pty.pid
            tui.pty.write(b"\r")  # explicit user submission, only in this test
            if not api.got_images.wait(25):
                raise AssertionError("Native CLI never serialized two visual image inputs")
            assert tui.pty.pid == alive_pid and tui.pty.poll() is None
            with api.lock:
                requests = list(api.requests)
            images = next(x["images"] for x in requests if len(x["images"]) == 2)
            assert [x["pixel"] for x in images] == ["#d97757", "#87bbb6"], images
            return {"tool": tool, "version": ".".join(map(str, version)), "native_chips": 2, "draft_preserved": True, "no_submit_before_enter": True, "same_process": True, "serialized_images": images, "paste_and_submit_seconds": round(time.monotonic() - first, 3), "fixture_only": True, "real_model_understanding": "not_tested"}
        finally:
            tui.close()
            api.shutdown()
            api.server_close()
            for path in paths:
                path.unlink(missing_ok=True)
            attachments.rmdir()
            attachments.parent.rmdir()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", type=Path)
    parser.add_argument("--codex", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [run_tool(tool, executable) for tool, executable in (("claude", args.claude), ("codex", args.codex)) if executable]
    if not results:
        parser.error("provide at least one official CLI executable")
    args.output.write_text(json.dumps({"schema": 1, "tests": results}, indent=2), encoding="utf-8")
    print(json.dumps({"result": "passed", "tools": [x["tool"] for x in results], "real_model_understanding": "not_tested"}))
