"""Every SAMPLE_EVERY seconds while the Hub serves: memory / CPU of the Hub and of each running addon, and the
addons that stopped without the Hub stopping them (core/monitor.py events). One background thread, never raises."""
from __future__ import annotations

import logging
import os
import threading
import time

from viewer_hub.core import monitor

logger = logging.getLogger(__name__)
SAMPLE_EVERY = 30.0


def _daemon_usage(runner, process_usage) -> tuple[int | None, float | None]:
    """A daemon reports itself (GET /api/process: rss, cpuPct, as my-bridge does); else its pid from /api/health."""
    for path in ("/api/process", "/api/health"):
        try:
            status, body = runner.request("GET", path)
        except Exception:  # noqa: BLE001
            return None, None
        if status != 200 or not isinstance(body, dict):
            continue
        if isinstance(body.get("rss"), int):
            cpu = body.get("cpuPct")
            return body["rss"], float(cpu) if isinstance(cpu, (int, float)) else None
        if isinstance(body.get("pid"), int):
            return process_usage(body["pid"])
    return None, None


def guard_once(hub) -> None:
    """Addon upkeep that runs even with monitoring off: a crashed managed addon is noticed, one flooding its log is
    stopped (runner.Managed.check_log)."""
    from viewer_hub.addons.runner import Managed

    for module in hub.modules:
        if module.addon is not None:
            runner = hub.addons.runner(module.addon)
            if isinstance(runner, Managed):
                runner.check_exit()
                runner.check_log()


def sample_once(hub) -> None:
    from viewer_hub.addons.runner import Daemon, Managed, process_usage

    rec = monitor.recorder()
    if rec is None or not rec.enabled:
        return
    rec.sample("hub", *process_usage(os.getpid()))
    for module in hub.modules:
        addon = module.addon
        if addon is None:
            continue
        runner = hub.addons.runner(addon)
        if isinstance(runner, Managed):
            runner.check_exit()
            if runner.pid:
                rec.sample(addon.id, *process_usage(runner.pid))
        elif isinstance(runner, Daemon) and runner._channel and not runner.problem():
            # only a daemon whose channel is known: asking `status` for it would start a program every time
            if runner.running():
                runner.expected = True
                rec.sample(addon.id, *_daemon_usage(runner, process_usage))
            elif runner.expected:
                runner.expected = False
                monitor.event(addon.id, "crash", "warning", f"{addon.name} đã dừng mà Viewer Hub không dừng nó")


def start(hub) -> threading.Thread:
    def work() -> None:
        while True:
            try:
                guard_once(hub)
                sample_once(hub)
            except Exception:  # noqa: BLE001  (monitoring never breaks the Hub)
                logger.debug("monitor sample failed", exc_info=True)
            time.sleep(SAMPLE_EVERY)

    thread = threading.Thread(target=work, name="monitor-sampler", daemon=True)
    thread.start()
    return thread
