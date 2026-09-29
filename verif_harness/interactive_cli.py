"""Submit one visible startup turn to a newly launched interactive Kimi TUI."""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import sys
import termios
import time
import tty

from .store import HarnessError


def kimi_ready(output: bytes) -> bool:
    text = output.decode("utf-8", errors="ignore")
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return "Ask When Needed" in text and bool(re.search(
        r"(?:^|[\r\n])[ \t]*(?:│[ \t]*)?>[ \t]*(?:│[ \t]*)?(?:[\r\n]|$)", text,
    ))


def _write(fd: int, data: bytes) -> None:
    while data:
        data = data[os.write(fd, data):]


def terminal_input(data: bytes) -> tuple[bytes, bool]:
    """Separate (possibly split) terminal replies from actual typed text."""
    while data:
        reply = re.match(rb'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))', data)
        if reply:
            data = data[reply.end():]
        elif len(data) < 512 and (
            data == b'\x1b' or re.fullmatch(rb'\x1b\[[0-?]*[ -/]*', data)
            or re.fullmatch(rb'\x1b\][^\x07\x1b]*\x1b?', data)
        ):
            return data, False
        else:
            return b'', True
    return b'', False


def run_kimi(command: list[str], root: Path, prompt: str, lock_fd: int) -> int:
    """Keep stdin interactive; never send text to a shell or an existing session."""
    input_fd, output_fd = sys.stdin.fileno(), sys.stdout.fileno()
    if not os.isatty(input_fd) or not os.isatty(output_fd):
        raise HarnessError("自动接续交互 CLI 需要终端；请在终端运行 setup，安装环境可用 --no-agent")
    # A single pasted turn cannot be interpreted as terminal control sequences.
    if not prompt or any(ord(char) < 32 or ord(char) == 127 for char in prompt):
        raise HarnessError("交互启动提示必须是单行文本，不能包含终端控制字符")
    saved = termios.tcgetattr(input_fd)
    pid, master = pty.fork()
    if pid == 0:
        try:
            os.chdir(root)
            os.set_inheritable(lock_fd, True)
            os.execvpe(command[0], command, os.environ)
        except BaseException:
            os._exit(127)

    def resize(_number=None, _frame=None):
        size = fcntl.ioctl(input_fd, termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(master, termios.TIOCSWINSZ, size)

    def forward(number, _frame):
        try:
            os.killpg(pid, number)
        except ProcessLookupError:
            pass

    old_handlers = {
        sig: signal.signal(sig, handler)
        for sig, handler in ((signal.SIGWINCH, resize), (signal.SIGTERM, forward))
    }
    pending, output, deadline = True, b"", time.monotonic() + 30
    reply_buffer, reply_deadline = b"", 0.0
    reaped = False
    try:
        resize()
        tty.setraw(input_fd)
        while True:
            readable, _, _ = select.select([master, input_fd], [], [], .1)
            if master in readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    break
                if not chunk:
                    break
                _write(output_fd, chunk)
                output = (output + chunk)[-65536:]
            if input_fd in readable:
                chunk = os.read(input_fd, 65536)
                if not chunk:
                    break
                # Color, keyboard-protocol and focus replies are not typed text.
                # Preserve split escape sequences until complete (or timed out).
                reply_buffer, typed = terminal_input(reply_buffer + chunk)
                reply_deadline = time.monotonic() + .2
                trust_dialog = b"Trust this folder?" in output and b"Welcome to Kimi Code!" not in output
                if trust_dialog:
                    # The owner, not the launcher, chooses whether to trust a new
                    # workspace. That choice must not discard the startup task.
                    deadline = time.monotonic() + 30
                elif typed:
                    pending = False
                _write(master, chunk)
            if reply_buffer and time.monotonic() >= reply_deadline:
                pending, reply_buffer = False, b""
            if pending and not reply_buffer and kimi_ready(output):
                _write(master, b"\x1b[200~" + prompt.encode("utf-8") + b"\x1b[201~\r")
                pending = False
            elif pending and time.monotonic() >= deadline and not (
                b"Trust this folder?" in output and b"Welcome to Kimi Code!" not in output
            ):
                pending = False
                _write(output_fd, (
                    "\r\n未识别到 Kimi 输入框，未自动发送任务。请在输入框输入：\r\n"
                    + prompt + "\r\n"
                ).encode("utf-8"))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            finished, status = os.waitpid(pid, os.WNOHANG)
            if finished:
                reaped = True
                return os.waitstatus_to_exitcode(status)
            time.sleep(.01)
        return 1
    finally:
        try:
            termios.tcsetattr(input_fd, termios.TCSANOW, saved)
        except termios.error:
            pass  # A disconnected terminal must not prevent child cleanup.
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        os.close(master)
        if not reaped:
            forward(signal.SIGHUP, None)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                finished, _ = os.waitpid(pid, os.WNOHANG)
                if finished:
                    reaped = True
                    break
                time.sleep(.01)
            if not reaped:
                forward(signal.SIGKILL, None)
                os.waitpid(pid, 0)
