"""Runs addon programs (docs/addons.md §4): the only Hub file besides explorer (fsearch) that starts a process.

Both lifecycles get, in the environment:

    VIEWER_HUB_ADDON_ID        its id
    VIEWER_HUB_ADDON_DATA      <data>/user/addons/<id>/  (the only place it writes)
    VIEWER_HUB_ADDON_SETTINGS  <that folder>/settings.json (the form on its page)
    VIEWER_HUB_ADDON_TOKEN     random per run; a managed addon refuses calls without X-Viewer-Hub-Token

* ``managed``: started by the Hub on first use, stopped when the Hub exits; if the Hub is killed instead, the addon
  sees its stdin (a pipe from the Hub) close and exits too. Python addons run on the Hub's own
  Python (``python -I -c <boot> <folder> serve --port N``, viewer_hub/addons/host.py), Node addons as
  ``node <entry> serve --port N``. It serves HTTP on 127.0.0.1:N: /health, /api/*, /mcp, /shutdown.
* ``external``: a program the user installs and runs (any language): the Hub starts and stops nothing, it only
  talks to 127.0.0.1:<port setting> with the managed HTTP contract (/health, /api/*, /mcp). No token (the Hub did not
  start it, so it cannot hand it one), no log of its own.
* ``daemon``: a program with its own life (the MCP Bridge). The Hub runs its ``init`` / ``start`` / ``status``
  commands; ``status --json`` names its ``adminChannel`` (channel.py), where it answers ``GET /api/health`` and
  ``POST /api/daemon/shutdown``. It keeps running when the Hub closes: on Windows in its own console window
  (minimised, never hidden), on macOS / Linux in its own session.

Logs belong to the Hub: every addon's output goes to ``<logs>/addon-<id>.log`` (the Settings page and the addon's
page show it whole). A daemon runs under ``tee`` below (the Hub's own Python): its output still shows in its window
and is copied to the log, which is rotated at LOG_MAX (one older file, ``addon-<id>.1.log``).

Always an argument list, never a shell; node is the addon's own ``node/node.exe`` on Windows, else the machine's.
``process_usage`` also runs ``ps`` (macOS / Linux) or ``tasklist`` (Windows) to read one process's memory and CPU for
the Giám sát page. Starts, stops and unexpected exits are recorded there too (core/monitor.py).
"""
from __future__ import annotations

import atexit
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from viewer_hub.addons import channel, proxy
from viewer_hub.addons.manifest import Addon
from viewer_hub.core import atomic, monitor

START_WAIT = 20.0
DAEMON_START_WAIT = 8.0
STOP_WAIT = 10.0
CLI_TIMEOUT = 60
CRASH_WINDOW, CRASH_LIMIT, CRASH_PAUSE = 300.0, 3, 60.0  # 3 failures in 5 minutes: no new start for a minute
LOG_MAX = 2 * 1024 * 1024
LOG_FLOOD = 50 * 1024 * 1024  # a managed addon's log (rotated only when it starts) past this: it is stopped
PARENT_PIPE = "VIEWER_HUB_PARENT_PIPE"
_TEE = ("import sys; sys.path[:0] = {paths!r}; from viewer_hub.addons.runner import tee; "
        "raise SystemExit(tee(sys.argv[1], sys.argv[2:]))")
_BOOT = ("import sys; sys.path[:0] = {paths!r}; from viewer_hub.addons.host import main; "
         "raise SystemExit(main(sys.argv[1:]))")


def _hub_paths() -> list[str]:
    return [p for p in sys.path if p and Path(p).is_dir()]


def rotate(log: Path, limit: int = LOG_MAX) -> None:
    """Keeps one older file once ``log`` passes ``limit`` (never fails: a log file in use stays as it is)."""
    try:
        if log.stat().st_size > limit:
            os.replace(log, log.with_name(log.stem + ".1" + log.suffix))
    except OSError:
        pass


def tee(log_path: str, argv: list[str]) -> int:
    """Runs ``argv``; each line it prints goes to this console and to ``log_path`` (rotated while it runs)."""
    log = Path(log_path)
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = open(log, "ab")  # noqa: SIM115  (reopened on rotation)
    try:
        for line in iter(process.stdout.readline, b""):
            try:
                sys.stdout.write(line.decode("utf-8", errors="replace"))
                sys.stdout.flush()
            except (OSError, ValueError):
                pass  # no console (closed window, a session without one): the log still gets it
            out.write(line)
            out.flush()
            if out.tell() > LOG_MAX:
                out.close()
                rotate(log)
                out = open(log, "ab")  # noqa: SIM115
        return process.wait()
    finally:
        out.close()


class AddonUnavailable(Exception):
    """The addon could not be started or does not answer; the message is for the user."""


def free_port() -> int:
    with socket.socket() as probe:  # binds 127.0.0.1 only to learn a free port; connects nowhere
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Base:
    def __init__(self, addon: Addon, data: Path, logs: Path) -> None:
        self.addon = addon
        self.data = data
        self.logs = logs
        self.token = ""

    @property
    def settings_file(self) -> Path:
        return self.data / "settings.json"

    @property
    def log_file(self) -> Path:
        return self.logs / f"addon-{self.addon.id}.log"

    def log_tail(self, lines: int = 15) -> list[str]:
        return self.log_text().splitlines()[-lines:]

    def log_text(self) -> str:
        """The whole log (at most LOG_MAX and a bit, rotate() keeps it small)."""
        try:
            with open(self.log_file, "rb") as log:
                log.seek(0, os.SEEK_END)
                size = log.tell()
                log.seek(max(0, size - LOG_MAX - 256 * 1024))
                data = log.read()
        except OSError:
            return ""
        text = data.decode("utf-8", errors="replace")
        return text if size <= len(data) else text.split("\n", 1)[-1]

    def mark(self, log, what: str) -> None:
        log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {what} {self.addon.id} {self.addon.version}\n".encode())
        log.flush()

    def node(self) -> str | None:
        bundled = self.addon.folder / "node" / "node.exe"
        return str(bundled) if sys.platform == "win32" and bundled.is_file() else shutil.which("node")

    def problem(self) -> str:
        if self.addon.runtime == "node" and not self.node():
            return f"Cần Node.js {self.addon.min_node or '22'}+ (node) để chạy {self.addon.name}."
        return ""

    def program(self) -> list[str]:
        """The interpreter and entry, without the lifecycle's own arguments."""
        if self.addon.runtime == "python":
            return [sys.executable, "-I", "-c", _BOOT.format(paths=_hub_paths()), str(self.addon.folder)]
        return [self.node() or "node", str(self.addon.main)]

    def env(self) -> dict[str, str]:
        self.data.mkdir(parents=True, exist_ok=True)
        return {**os.environ, "VIEWER_HUB_ADDON_ID": self.addon.id, "VIEWER_HUB_ADDON_DATA": str(self.data),
                "VIEWER_HUB_ADDON_SETTINGS": str(self.settings_file), "VIEWER_HUB_ADDON_TOKEN": self.token,
                "PYTHONIOENCODING": "utf-8"}


class Managed(_Base):
    """An addon process the Hub owns: started on first use, stopped with the Hub."""

    def __init__(self, addon: Addon, data: Path, logs: Path) -> None:
        super().__init__(addon, data, logs)
        self.port = 0
        self.process: subprocess.Popen | None = None
        self.read_only_tools: set[str] = set()
        self._lock = threading.Lock()
        self._failures: list[float] = []  # monotonic times it crashed or failed to start

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _failed(self) -> None:
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < CRASH_WINDOW] + [now]

    def _paused(self) -> str:
        """Why no new start now (an addon that keeps crashing is not restarted on every request), else ''."""
        now = time.monotonic()
        recent = [t for t in self._failures if now - t < CRASH_WINDOW]
        if len(recent) >= CRASH_LIMIT and now - recent[-1] < CRASH_PAUSE:
            wait = int(CRASH_PAUSE - (now - recent[-1])) + 1
            return (f"{self.addon.name} dừng bất thường {len(recent)} lần trong 5 phút; Viewer Hub chờ {wait} giây rồi "
                    "mới chạy lại (xem Nhật ký của addon)")
        return ""

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.running() else None

    def check_exit(self) -> int | None:
        """The exit code of a process that ended without the Hub stopping it (recorded once), else None."""
        process = self.process
        if process is None or process.poll() is None:
            return None
        self.process = None
        self._failed()
        monitor.event(self.addon.id, "crash", "error", f"{self.addon.name} dừng bất thường (mã thoát {process.returncode})")
        return process.returncode

    def check_log(self) -> bool:
        """Stop an addon that floods its log (a loop printing errors would fill the disk the Hub writes to). True when
        stopped; the next use starts it again with a fresh log, unless it keeps doing it (_paused)."""
        try:
            size = self.log_file.stat().st_size
        except OSError:
            return False
        if not self.running() or size <= LOG_FLOOD:
            return False
        self.stop()
        self._failed()
        monitor.event(self.addon.id, "log-flood", "error",
                      f"{self.addon.name} ghi nhật ký quá nhiều (hơn {LOG_FLOOD // (1024 * 1024)} MB): đã dừng")
        return True

    def ensure(self) -> tuple[int, str]:
        """(port, token) of a running process, starting it if needed; AddonUnavailable if it cannot run."""
        with self._lock:
            if self.running():
                return self.port, self.token
            self.check_exit()
            problem = self.problem() or self._paused()
            if problem:
                raise AddonUnavailable(problem)
            self.port, self.token = free_port(), secrets.token_urlsafe(24)
            self.read_only_tools = set()
            self.logs.mkdir(parents=True, exist_ok=True)
            rotate(self.log_file)
            with open(self.log_file, "ab") as log:
                self.mark(log, "start")
                # stdin is a pipe the Hub never writes to: it closes when the Hub ends, however it ends (closed,
                # killed, crashed), and the addon exits on that end of input (VIEWER_HUB_PARENT_PIPE, host.py).
                self.process = subprocess.Popen([*self.program(), "serve", "--port", str(self.port)],
                                                cwd=str(self.addon.folder), env={**self.env(), PARENT_PIPE: "1"},
                                                stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                                close_fds=True)
            deadline = time.monotonic() + START_WAIT
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    self.process = None
                    self._failed()
                    monitor.event(self.addon.id, "start_failed", "error", f"{self.addon.name} dừng ngay khi chạy")
                    raise AddonUnavailable(f"{self.addon.name} dừng ngay khi chạy (xem log)")
                if proxy.healthy(self.port, self.token):
                    monitor.event(self.addon.id, "start", "info", f"Đã chạy {self.addon.name}")
                    return self.port, self.token
                time.sleep(0.2)
            self._kill()
            self._failed()
            monitor.event(self.addon.id, "start_failed", "error", f"{self.addon.name} không trả lời sau {int(START_WAIT)} giây")
            raise AddonUnavailable(f"{self.addon.name} không trả lời sau {int(START_WAIT)} giây (xem log)")

    def start(self) -> tuple[bool, str]:
        try:
            self.ensure()
        except AddonUnavailable as exc:
            return False, str(exc)
        return True, f"Đã chạy {self.addon.name}"

    def _kill(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        if process.stdin:
            process.stdin.close()
        process.terminate()
        try:
            process.wait(3)
        except subprocess.TimeoutExpired:
            process.kill()

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if self.running():
                try:
                    proxy.request(self.port, self.token, "POST", "/shutdown", timeout=3)
                    self.process.wait(3)
                except (proxy.Unavailable, subprocess.TimeoutExpired):
                    pass
                self._kill()
                monitor.event(self.addon.id, "stop", "info", f"Đã dừng {self.addon.name}")
        return True, f"Đã dừng {self.addon.name}"

    def status(self) -> dict:
        return {"running": self.running()}


class Daemon(_Base):
    """A program with its own life; the Hub runs its commands and talks to it on its admin channel."""

    def __init__(self, addon: Addon, data: Path, logs: Path) -> None:
        super().__init__(addon, data, logs)
        self._channel = ""
        self.expected = False  # seen running (or started by the Hub) and not stopped by it: an exit is unexpected

    def cli(self, *args: str) -> tuple[int, str]:
        if self.problem():
            return 127, self.problem()
        result = subprocess.run([*self.program(), *args], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=CLI_TIMEOUT, stdin=subprocess.DEVNULL,
                                cwd=str(self.addon.folder), env=self.env())
        return result.returncode, (result.stdout + result.stderr).strip()

    def status(self) -> dict:
        """``status`` command's JSON (works without the daemon); {} when it fails."""
        try:
            code, out = self.cli(*self.addon.commands["status"])
        except (OSError, subprocess.TimeoutExpired):
            return {}
        if code != 0 or "{" not in out:
            return {}
        try:
            data = json.loads(out[out.index("{"):])
        except ValueError:
            return {}
        if isinstance(data.get("adminChannel"), str):
            self._channel = data["adminChannel"]
        return data

    def channel(self) -> str:
        """Where the daemon listens: asked once from ``status``, then remembered."""
        if not self._channel:
            self.status()
        return self._channel

    def request(self, method: str, path: str, **kwargs):
        return channel.request(self.channel(), method, path, **kwargs)

    def events(self):
        return channel.events(self.channel())

    def running(self) -> bool:
        try:
            return self.request("GET", "/api/health")[0] == 200
        except (channel.Unavailable, OSError, ValueError):
            return False

    @property
    def applied_file(self) -> Path:
        return self.data / "applied.json"

    def _applied(self) -> dict:
        try:
            data = json.loads(self.applied_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def setting_args(self, values: dict, command: str) -> list[str]:
        """Arguments from the settings for ``command``. ``init`` gets a value only when it differs from the one it
        was last given (applied.json): the daemon keeps what the user changed elsewhere (its own CLI or page) until
        the user changes that setting in the Hub again. ``start`` arguments are for one run, so always given."""
        applied = self._applied() if command == "init" else {}
        out: list[str] = []
        for setting in self.addon.settings:
            value = values.get(setting.key)
            value = "" if value is None else str(value).strip()
            if value and setting.arg and setting.on == command and applied.get(setting.key) != value:
                out += [setting.arg, value]
        return out

    def _remember_init(self, values: dict) -> None:
        applied = self._applied()
        for setting in self.addon.settings:
            value = values.get(setting.key)
            value = "" if value is None else str(value).strip()
            if setting.arg and setting.on == "init" and value:
                applied[setting.key] = value
        atomic.write_json(self.applied_file, applied)

    def start(self, settings: dict | None = None) -> tuple[bool, str]:
        """``init`` (with the saved settings), then the daemon in the background; waits until it answers."""
        name = self.addon.name
        if self.running():
            return True, f"{name} đang chạy"
        if self.problem():
            return False, self.problem()
        values = settings or {}
        code, out = self.cli(*self.addon.commands["init"], *self.setting_args(values, "init"))
        if code != 0:
            return False, out or f"{name}: init lỗi"
        self._remember_init(values)
        self._channel = ""  # init may have moved it (a new home); ask again
        self.channel()
        daemon = [*self.program(), *self.addon.commands["start"], *self.setting_args(values, "start")]
        self.logs.mkdir(parents=True, exist_ok=True)
        rotate(self.log_file)
        with open(self.log_file, "ab") as log:
            self.mark(log, "start")
        command = [sys.executable, "-I", "-c", _TEE.format(paths=_hub_paths()), str(self.log_file), *daemon]
        if sys.platform == "win32":
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = 7  # SW_SHOWMINNOACTIVE: a visible console window, minimised
            subprocess.Popen(command, stdin=subprocess.DEVNULL, startupinfo=info, close_fds=True, env=self.env(),
                             cwd=str(self.addon.folder),
                             creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True, start_new_session=True, env=self.env(), cwd=str(self.addon.folder))
        deadline = time.monotonic() + DAEMON_START_WAIT
        while time.monotonic() < deadline:
            if self.running():
                self.expected = True
                monitor.event(self.addon.id, "start", "info", f"Đã chạy {name}")
                return True, f"Đã chạy {name}"
            time.sleep(0.4)
        monitor.event(self.addon.id, "start_failed", "error", f"{name} không khởi động được")
        return False, f"{name} không khởi động được (xem nhật ký)"

    def stop(self) -> tuple[bool, str]:
        name = self.addon.name
        if not self.running():
            return True, f"{name} đã dừng"
        self.expected = False
        monitor.event(self.addon.id, "stop", "info", f"Dừng {name}")
        try:
            self.request("POST", "/api/daemon/shutdown")
        except channel.Unavailable:
            return True, f"{name} đã dừng"
        deadline = time.monotonic() + STOP_WAIT
        while time.monotonic() < deadline:
            if not self.running():
                return True, f"Đã dừng {name}"
            time.sleep(0.3)
        return False, f"{name} chưa dừng sau {int(STOP_WAIT)} giây"


class External(_Base):
    """A program the user runs on this machine (addon.json "service"); the Hub only connects to it."""

    def port(self) -> int:
        saved = atomic.read_json(self.settings_file, {}) or {}
        value = saved.get("port") if isinstance(saved, dict) else None
        try:
            port = int(str(value).strip()) if value not in (None, "") else self.addon.port
        except ValueError:
            return 0
        return port if 1024 <= port <= 65535 else 0

    @property
    def read_only_tools(self) -> set[str]:
        return self._tools

    def __init__(self, addon: Addon, data: Path, logs: Path) -> None:
        super().__init__(addon, data, logs)
        self._tools: set[str] = set()
        self._seen = 0

    def problem(self) -> str:
        return "" if self.port() else "Cổng của chương trình phải là số 1024-65535 (mục Cài đặt bên dưới)"

    def running(self) -> bool:
        port = self.port()
        return bool(port) and proxy.healthy(port, "")

    def ensure(self) -> tuple[int, str]:
        port = self.port()
        if not port:
            raise AddonUnavailable(self.problem())
        if port != self._seen:  # pointed at another program: its tools are asked again
            self._seen, self._tools = port, set()
        if not proxy.healthy(port, ""):
            raise AddonUnavailable(f"không kết nối được chương trình ở 127.0.0.1:{port}: hãy mở chương trình "
                                   f"{self.addon.name} (Viewer Hub không tự chạy nó)")
        return port, ""

    def start(self, settings: dict | None = None) -> tuple[bool, str]:
        return False, f"{self.addon.name} là chương trình ngoài: tự mở nó, Viewer Hub chỉ kết nối"

    def stop(self) -> tuple[bool, str]:
        return True, ""  # never stops a program it did not start

    def log_text(self) -> str:
        return ""

    def status(self) -> dict:
        return {"running": self.running(), "port": self.port()}


_owned: list[Managed] = []


def process_usage(pid: int | None) -> tuple[int | None, float | None]:
    """(resident memory in bytes, CPU %) of one process, (None, None) when unknown. Windows gives memory only."""
    if not pid:
        return None, None
    try:
        if sys.platform == "win32":
            result = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"], capture_output=True,
                                    text=True, timeout=5, stdin=subprocess.DEVNULL)  # the Hub's own console
            fields = [f.strip('"') for f in result.stdout.strip().split('","')]
            if len(fields) < 5:
                return None, None
            kb = int("".join(ch for ch in fields[4] if ch.isdigit()) or 0)
            return kb * 1024, None
        result = subprocess.run(["ps", "-o", "rss=,%cpu=", "-p", str(int(pid))], capture_output=True, text=True,
                                timeout=5, stdin=subprocess.DEVNULL)
        parts = result.stdout.split()
        if len(parts) < 2:
            return None, None
        return int(parts[0]) * 1024, float(parts[1].replace(",", "."))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, None


def managed(addon: Addon, data: Path, logs: Path) -> Managed:
    runner = Managed(addon, data, logs)
    _owned.append(runner)
    return runner


@atexit.register
def _stop_all() -> None:
    for runner in _owned:
        if runner.running():
            runner.stop()
