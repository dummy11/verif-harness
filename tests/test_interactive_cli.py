"""Exercise the interactive bridge through real PTYs, without an LLM or network."""

import errno
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest import mock

from verif_harness.interactive_cli import kimi_ready, run_kimi, terminal_input
from verif_harness.store import HarnessError


ROOT = Path(__file__).resolve().parents[1]
READY = '\r\n│ >   │\r\nAsk When Needed\r\n'


class InteractiveCliTest(unittest.TestCase):
    def test_terminal_query_replies_are_not_user_text(self):
        self.assertEqual(terminal_input(b'\x1b]11;rgb:0000/0000/0000\x07\x1b[?0u\x1b[I'), (b'', False))
        partial, typed = terminal_input(b'\x1b]11;rgb:0000/0000')
        self.assertFalse(typed)
        self.assertEqual(terminal_input(partial + b'/0000\x1b\\'), (b'', False))
        self.assertEqual(terminal_input(b'\x1b[12;'), (b'\x1b[12;', False))
        self.assertEqual(terminal_input(b'\x1b[12;4R'), (b'', False))
        for value in (b'x', b'\r', b'\x03', b'\x1b[200~manual\x1b[201~'):
            self.assertTrue(terminal_input(value)[1])

    def test_only_empty_tui_input_is_ready(self):
        self.assertTrue(kimi_ready(READY.encode()))
        self.assertTrue(kimi_ready(b'\x1b[2K\r\n > \r\n\x1b[32mAsk When Needed\x1b[0m'))
        for output in ('Trust this folder?\n❯ Trust\n', 'Login: > ',
                       'Ask When Needed\n> user already typing\n', '> \n'):
            self.assertFalse(kimi_ready(output.encode()), output)

    def test_no_tty_or_control_characters_fail_before_launch(self):
        with mock.patch('os.isatty', return_value=False), mock.patch('pty.fork') as fork:
            with self.assertRaisesRegex(HarnessError, '需要终端'):
                run_kimi(['kimi'], ROOT, 'continue', 0)
            fork.assert_not_called()
        with mock.patch('os.isatty', return_value=True), mock.patch('pty.fork') as fork:
            for prompt in ('', 'task\n/exit', '\x1b[31mtask', 'task\x7f'):
                with self.assertRaises(HarnessError):
                    run_kimi(['kimi'], ROOT, prompt, 0)
            fork.assert_not_called()

    def exercise(self, mode):
        child = '''
import os, sys, tty
tty.setraw(0)
def out(text): os.write(1, text.encode())
def turn():
    data = b''
    while not data.endswith(b'\\r'):
        data += os.read(0, 1)
    return data
'''
        if mode == 'trust':
            child += "out('Trust this folder?\\r\\n'); turn(); out('Welcome to Kimi Code!\\r\\n')\n"
        if mode == 'manual':
            child += "out('BOOT\\r\\n'); assert os.read(0,1) == b'x'\n"
        child += f"out({READY!r})\n"
        child += '''
first = turn()
out('FIRST:' + first.hex() + '\\r\\n')
'''
        child += f"out({READY!r})\n"
        child += "second = turn(); out('SECOND:' + second.hex() + '\\r\\n'); sys.exit(7)\n"
        with tempfile.TemporaryDirectory() as directory:
            wrapper = (
                'from pathlib import Path; from verif_harness.interactive_cli import run_kimi; '
                f'root=Path({directory!r}); lock=(root/"lock").open("w"); '
                f'raise SystemExit(run_kimi({[sys.executable, "-c", child]!r}, root, "继续验证", lock.fileno()))'
            )
            master, slave = pty.openpty()
            saved = termios.tcgetattr(slave)
            process = subprocess.Popen([sys.executable, '-c', wrapper], cwd=ROOT,
                                       stdin=slave, stdout=slave, stderr=slave)
            output = b''

            def until(marker):
                nonlocal output
                deadline = time.monotonic() + 10
                while marker not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        try:
                            output += os.read(master, 65536)
                        except OSError as exc:
                            if exc.errno != errno.EIO:
                                raise
                            break
                self.assertIn(marker, output)

            try:
                if mode == 'trust':
                    until(b'Trust this folder?')
                    self.assertNotIn(b'FIRST:', output)
                    os.write(master, b'\r')  # Only the owner accepts trust.
                if mode == 'manual':
                    until(b'BOOT')
                    os.write(master, b'x')
                    until(b'Ask When Needed')
                    os.write(master, b'manual\r')
                expected = b'manual\r' if mode == 'manual' else b'\x1b[200~' + '继续验证'.encode() + b'\x1b[201~\r'
                until(b'FIRST:' + expected.hex().encode())
                self.assertIsNone(process.poll(), 'CLI must remain interactive after the startup turn')
                os.write(master, b'second\r')
                until(b'SECOND:' + b'second\r'.hex().encode())
                self.assertEqual(process.wait(timeout=5), 7, output.decode(errors='replace'))
                restored = termios.tcgetattr(slave)
                # macOS may set PENDIN while flushing/retyping terminal input;
                # it is not an input/echo/raw-mode setting controlled by us.
                restored[3] &= ~getattr(termios, 'PENDIN', 0)
                saved[3] &= ~getattr(termios, 'PENDIN', 0)
                self.assertEqual(restored, saved)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                os.close(master)
                os.close(slave)

    def test_startup_is_submitted_once_and_cli_remains_interactive(self):
        self.exercise('normal')

    def test_trust_choice_does_not_discard_startup_turn(self):
        self.exercise('trust')

    def test_user_typing_takes_precedence(self):
        self.exercise('manual')


if __name__ == '__main__':
    unittest.main()
