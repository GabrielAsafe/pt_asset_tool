from __future__ import annotations

import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

WATCHDOG_FORMAT = "PT_ASSET_BLENDER_WATCHDOG_V1"


def _proc_pids() -> List[int]:
    out: List[int] = []
    try:
        for name in os.listdir('/proc'):
            if name.isdigit():
                out.append(int(name))
    except OSError:
        pass
    return out


def _ppid(pid: int) -> Optional[int]:
    try:
        for line in Path(f'/proc/{pid}/status').read_text(errors='replace').splitlines():
            if line.startswith('PPid:'):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _cmdline(pid: int) -> str:
    try:
        raw = Path(f'/proc/{pid}/cmdline').read_bytes()
        return raw.replace(b'\0', b' ').decode('utf-8', 'replace').strip()
    except OSError:
        return ''


def _age_seconds(pid: int) -> Optional[float]:
    try:
        text = Path(f'/proc/{pid}/stat').read_text()
        end = text.rfind(')')
        if end < 0:
            return None
        fields = text[end + 2:].split()
        # fields[0] is stat field 3 (state); starttime is stat field 22.
        start_ticks = int(fields[19])
        clk = int(os.sysconf(os.sysconf_names['SC_CLK_TCK']))
        uptime = float(Path('/proc/uptime').read_text().split()[0])
        return max(0.0, uptime - (start_ticks / clk))
    except (OSError, ValueError, IndexError, KeyError):
        return None


def _snapshot_parents() -> Dict[int, int]:
    result: Dict[int, int] = {}
    for pid in _proc_pids():
        parent = _ppid(pid)
        if parent is not None:
            result[pid] = parent
    return result


def descendants(root_pid: int, parents: Optional[Dict[int, int]] = None) -> Set[int]:
    parents = parents or _snapshot_parents()
    children: Dict[int, List[int]] = {}
    for pid, ppid in parents.items():
        children.setdefault(ppid, []).append(pid)
    found: Set[int] = set()
    stack = list(children.get(root_pid, []))
    while stack:
        pid = stack.pop()
        if pid in found:
            continue
        found.add(pid)
        stack.extend(children.get(pid, []))
    return found


def _alive(pid: int) -> bool:
    return Path(f'/proc/{pid}').exists()


def _signal_many(pids: Iterable[int], sig: signal.Signals) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _ancestor_bwrap_chain(pid: int, root_pid: int, parents: Dict[int, int]) -> List[int]:
    chain: List[int] = []
    cur = parents.get(pid)
    seen: Set[int] = set()
    while cur and cur != root_pid and cur not in seen:
        seen.add(cur)
        cmd = _cmdline(cur)
        if 'bwrap' in cmd:
            chain.append(cur)
        cur = parents.get(cur)
    return chain


def _append_event(event_file: Path, event: Dict[str, object]) -> None:
    try:
        event_file.parent.mkdir(parents=True, exist_ok=True)
        with event_file.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + '\n')
    except OSError:
        pass


def terminate_timed_out_blender(
    blender_pid: int,
    *,
    root_pid: int,
    grace_seconds: float,
    event_file: Path,
    timeout_seconds: float,
) -> None:
    parents = _snapshot_parents()
    tree = descendants(blender_pid, parents)
    target = [blender_pid] + sorted(tree, reverse=True)
    bwrap_chain = _ancestor_bwrap_chain(blender_pid, root_pid, parents)
    cmd = _cmdline(blender_pid)
    age = _age_seconds(blender_pid)
    print(
        f"[blender-watchdog] TIMEOUT pid={blender_pid} "
        f"age={age:.1f}s limit={timeout_seconds:.1f}s cmd={cmd[:500]}",
        flush=True,
    )
    _append_event(event_file, {
        'format': WATCHDOG_FORMAT,
        'event': 'TIMEOUT',
        'pid': blender_pid,
        'age_seconds': age,
        'timeout_seconds': timeout_seconds,
        'cmdline': cmd,
        'bwrap_ancestors': bwrap_chain,
        'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    })
    _signal_many(target, signal.SIGTERM)
    deadline = time.monotonic() + max(0.1, grace_seconds)
    while time.monotonic() < deadline and any(_alive(p) for p in target):
        time.sleep(0.1)
    _signal_many([p for p in target if _alive(p)], signal.SIGKILL)
    # Flatpak/bwrap wrappers can survive a dead Blender. Kill only wrappers in
    # the timed-out Blender's ancestor chain, never the pt_asset Python parent.
    _signal_many(bwrap_chain, signal.SIGTERM)
    time.sleep(0.2)
    _signal_many([p for p in bwrap_chain if _alive(p)], signal.SIGKILL)


class BlenderWatchdog:
    def __init__(
        self,
        *,
        root_pid: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        poll_seconds: float = 2.0,
        grace_seconds: float = 3.0,
        event_file: Optional[Path] = None,
    ) -> None:
        self.root_pid = int(root_pid or os.getpid())
        if timeout_seconds is None:
            timeout_seconds = float(os.environ.get('PT_ASSET_BLENDER_TIMEOUT_SEC', '120'))
        requested_timeout_seconds = float(timeout_seconds)
        self.timeout_seconds = min(requested_timeout_seconds, 120.0)
        self.poll_seconds = float(poll_seconds)
        self.grace_seconds = float(grace_seconds)
        self.event_file = event_file or (
            Path(__file__).resolve().parent / 'pt_build' / 'devtest' / 'blender_watchdog' / 'events.jsonl'
        )
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._handled: Set[int] = set()

    @property
    def enabled(self) -> bool:
        value = os.environ.get('PT_ASSET_BLENDER_WATCHDOG', '1').strip().lower()
        return value not in {'0', 'false', 'no', 'off'} and self.timeout_seconds > 0

    def _is_blender_background(self, pid: int) -> bool:
        cmd = _cmdline(pid)
        if not cmd:
            return False
        return 'blender' in cmd and '--background' in cmd

    def _warn_external_blenders(self) -> None:
        own = descendants(self.root_pid)
        app_dir = str(Path(__file__).resolve().parent)
        for pid in _proc_pids():
            if pid == self.root_pid or pid in own:
                continue
            cmd = _cmdline(pid)
            if 'blender' in cmd and '--background' in cmd and app_dir in cmd:
                age = _age_seconds(pid)
                age_text = f'{age:.0f}s' if age is not None else 'unknown'
                print(
                    f"[blender-watchdog] WARN external Blender from same app is already running "
                    f"pid={pid} age={age_text}; not killing it automatically",
                    flush=True,
                )

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            parents = _snapshot_parents()
            for pid in sorted(descendants(self.root_pid, parents)):
                if pid in self._handled or not self._is_blender_background(pid):
                    continue
                age = _age_seconds(pid)
                if age is None or age < self.timeout_seconds:
                    continue
                self._handled.add(pid)
                terminate_timed_out_blender(
                    pid,
                    root_pid=self.root_pid,
                    grace_seconds=self.grace_seconds,
                    event_file=self.event_file,
                    timeout_seconds=self.timeout_seconds,
                )

    def start(self) -> None:
        if not self.enabled:
            print('[blender-watchdog] DISABLED', flush=True)
            return
        print(
            f"[blender-watchdog] ENABLED timeout={self.timeout_seconds:.0f}s "
            f"poll={self.poll_seconds:.1f}s root_pid={self.root_pid}",
            flush=True,
        )
        self._warn_external_blenders()
        self._thread = threading.Thread(target=self._loop, name='pt-blender-watchdog', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.poll_seconds * 2))
