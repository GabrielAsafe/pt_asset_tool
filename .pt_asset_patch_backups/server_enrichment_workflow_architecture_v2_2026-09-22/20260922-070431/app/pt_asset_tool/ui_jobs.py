from __future__ import annotations

import collections
import os
import pathlib
import signal
import subprocess
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    action: str
    asset: str | None
    command: list[str]
    cwd: str
    log_path: str
    status: str = "QUEUED"
    returncode: int | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    pid: int | None = None
    process: subprocess.Popen[str] | None = field(default=None, repr=False)
    interactive: bool = False
    responses_sent: int = 0

    def public(self, tail: str | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "asset": self.asset,
            "command": self.command,
            "command_display": " ".join(_quote(x) for x in self.command),
            "cwd": self.cwd,
            "log_path": self.log_path,
            "status": self.status,
            "returncode": self.returncode,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pid": self.pid,
            "interactive": self.interactive,
            "accepts_input": bool(self.interactive and self.status == "RUNNING" and self.process is not None),
            "responses_sent": self.responses_sent,
            "tail": tail,
        }


def _quote(s: str) -> str:
    if not s or any(c.isspace() or c in "'\"$&;()[]{}" for c in s):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


class JobManager:
    def __init__(self, project_root: pathlib.Path, max_concurrent: int = 2, env_overrides: dict[str, str] | None = None):
        self.project_root = project_root.resolve()
        self.env_overrides = {str(k): str(v) for k, v in (env_overrides or {}).items()}
        self.log_root = self.project_root / "pt_build" / "ui_jobs"
        self.log_root.mkdir(parents=True, exist_ok=True)
        self.max_concurrent = max(1, int(max_concurrent))
        self._jobs: "collections.OrderedDict[str, Job]" = collections.OrderedDict()
        self._lock = threading.RLock()
        self._sem = threading.Semaphore(self.max_concurrent)

    def submit(self, action: str, asset: str | None, command: list[str], *, interactive: bool = False) -> Job:
        jid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        log = self.log_root / f"{jid}.log"
        job = Job(jid, action, asset, list(command), str(self.project_root), str(log), interactive=bool(interactive))
        with self._lock:
            self._jobs[jid] = job
            while len(self._jobs) > 200:
                self._jobs.popitem(last=False)
        t = threading.Thread(target=self._run, args=(job,), daemon=True, name=f"pt-ui-job-{jid}")
        t.start()
        return job

    def _run(self, job: Job) -> None:
        with self._sem:
            with self._lock:
                job.status = "RUNNING"
                job.started_at = time.time()
            env = os.environ.copy()
            env.update(self.env_overrides)
            env.setdefault("PYTHONUNBUFFERED", "1")
            try:
                with open(job.log_path, "w", encoding="utf-8", errors="replace") as out:
                    out.write("$ " + " ".join(_quote(x) for x in job.command) + "\n\n")
                    out.flush()
                    proc = subprocess.Popen(
                        job.command,
                        cwd=job.cwd,
                        env=env,
                        stdin=subprocess.PIPE if job.interactive else subprocess.DEVNULL,
                        stdout=out,
                        stderr=subprocess.STDOUT,
                        text=True,
                        shell=False,
                        # Keep each job and all Blender/tool children in one
                        # process group so Cancel does not orphan Blender.
                        start_new_session=(os.name != "nt"),
                    )
                    with self._lock:
                        job.process = proc
                        job.pid = proc.pid
                    rc = proc.wait()
                    if proc.stdin is not None:
                        try:
                            proc.stdin.close()
                        except Exception:
                            pass
                with self._lock:
                    was_cancelled = job.status == "CANCELLING"
                    job.returncode = rc
                    job.status = "CANCELLED" if was_cancelled else ("PASS" if rc == 0 else "FAIL")
            except Exception as exc:
                try:
                    with open(job.log_path, "a", encoding="utf-8", errors="replace") as out:
                        out.write(f"\nPT_UI_JOB_ERROR={type(exc).__name__}:{exc}\n")
                except Exception:
                    pass
                with self._lock:
                    job.returncode = -1
                    job.status = "ERROR"
            finally:
                with self._lock:
                    job.finished_at = time.time()
                    job.process = None


    def send_input(self, jid: str, value: str) -> bool:
        """Send one constrained human-review answer to an interactive job.

        The current validators only accept yes/no/skip prompts, so this bridge
        deliberately refuses arbitrary stdin text.
        """
        value = str(value or "").strip().lower()
        aliases = {"y": "y", "yes": "y", "pass": "y", "n": "n", "no": "n", "fail": "n", "s": "s", "skip": "s"}
        answer = aliases.get(value)
        if answer is None:
            return False
        with self._lock:
            job = self._jobs.get(jid)
            proc = job.process if job else None
            if not job or not job.interactive or job.status != "RUNNING" or proc is None or proc.stdin is None:
                return False
            # Do not allow callers to pre-seed stdin before the validator has
            # actually emitted a human-review prompt.  Each emitted prompt can
            # consume at most one response.
            prompt = "[y]es / [n]o / [s]kip:"
            emitted = _tail(pathlib.Path(job.log_path), 128000).count(prompt)
            if emitted <= job.responses_sent:
                return False
            try:
                proc.stdin.write(answer + "\n")
                proc.stdin.flush()
                job.responses_sent += 1
                return True
            except Exception:
                return False

    def cancel(self, jid: str) -> bool:
        with self._lock:
            job = self._jobs.get(jid)
            proc = job.process if job else None
            if not job:
                return False
            if proc and job.status == "RUNNING":
                try:
                    if os.name != "nt":
                        os.killpg(proc.pid, signal.SIGTERM)
                    else:
                        proc.terminate()
                    job.status = "CANCELLING"
                    return True
                except Exception:
                    try:
                        proc.terminate()
                        job.status = "CANCELLING"
                        return True
                    except Exception:
                        return False
            return False


    def has_active(self, asset: str | None, action: str | None = None) -> bool:
        with self._lock:
            for job in self._jobs.values():
                if job.status not in {"QUEUED", "RUNNING", "CANCELLING"}:
                    continue
                if asset is not None and job.asset != asset:
                    continue
                if action is not None and job.action != action:
                    continue
                return True
        return False

    def get(self, jid: str, tail_bytes: int = 24000) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(jid)
            if not job:
                return None
            public = job.public()
        public["tail"] = _tail(pathlib.Path(public["log_path"]), tail_bytes)
        prompt = "[y]es / [n]o / [s]kip:"
        prompt_count = public["tail"].count(prompt)
        public["awaiting_input"] = bool(
            public.get("accepts_input") and prompt_count > int(public.get("responses_sent") or 0)
        )
        public["input_prompt"] = _latest_review_prompt(public["tail"]) if public["awaiting_input"] else None
        return public

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())[-max(1, min(200, limit)):]
        return [j.public(_tail(pathlib.Path(j.log_path), 3000)) for j in reversed(jobs)]



def _latest_review_prompt(text: str) -> str | None:
    """Return the human-readable label of the latest unanswered review prompt.

    ValidationRunner._ask emits ``<label> [y]es / [n]o / [s]kip:``.  Keep
    extraction deliberately narrow so arbitrary subprocess output is never
    interpreted as a UI instruction.
    """
    matches = re.findall(r"(?:^|\n)([^\n]{1,240}?) \[y\]es / \[n\]o / \[s\]kip:\s*", text or "")
    if not matches:
        return None
    label = matches[-1].strip()
    return label or None

def _tail(path: pathlib.Path, max_bytes: int) -> str:
    try:
        with path.open("rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
