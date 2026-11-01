"""Scripted end-to-end run of the clear-founder path with fake providers (`make e2e-fake`).

Starts a real server + worker as subprocesses on a free port, drives the real `vybd` CLI with
--json (exactly like an agent would), and writes a transcript to
evals/runs/clear_founder-fake-<timestamp>.md. Exits non-zero on any failure.

Needs Postgres migrated (DATABASE_URL). Runs in CI.
"""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import UTC, datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = sys.executable

ANSWERS = {  # evals/personas/clear_founder.md
    "one_liner": "Small-batch hot sauce made with Kerala green chillies and coconut vinegar, "
                 "for people who cook Indian food at home.",
    "customer": "Indian-American home cooks in their 30s, like my friend Divya, who make dal "
                "and sabzi on weeknights and shop at Patel Brothers and Whole Foods.",
    "problem": "Supermarket hot sauces are sweet or vinegary and taste wrong on Indian food, so "
               "people mix their own chilli paste every time.",
    "alternative": "Sriracha, or chilli pickle brought back from India. Sriracha is too sweet; "
                   "pickle is oily and inconsistent.",
    "positioning": "The only hot sauce made to go on Indian home cooking, not on wings.",
    "product_price": "One 5oz bottle of green chilli sauce at $9; a red version later.",
    "channels": "Farmers markets now, then our own website and Indian grocery stores in Texas.",
    "competitors": "Diaspora Co. (spices), Brooklyn Delhi (achaar), and Yellowbird.",
    "goals": "Decide between grocery wholesale and direct online sales for the first six "
             "months, and check whether $9 is the right price.",
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class E2E:
    def __init__(self) -> None:
        self.port = free_port()
        self.home = tempfile.mkdtemp(prefix="vybd-e2e-")
        self.env = {
            **os.environ,
            "LLM_PROVIDER": "fake", "EMBED_PROVIDER": "fake", "SEARCH_PROVIDER": "fake",
            "AUTO_APPROVE_RUNS": "true", "RUNNER_POLL_SECONDS": "0.3",
            "VYBD_API_URL": f"http://127.0.0.1:{self.port}", "VYBD_HOME": self.home,
        }
        self.procs: list[subprocess.Popen] = []
        self.log: list[str] = []
        self.t0 = time.monotonic()

    # ---------- processes ----------

    def start(self) -> None:
        logs = pathlib.Path(self.home)
        self.procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "server.main:app", "--port", str(self.port), "--log-level",
             "warning"], env=self.env, cwd=ROOT, stdout=open(logs / "server.log", "w"),
            stderr=subprocess.STDOUT))
        self.procs.append(subprocess.Popen(
            [PY, "-m", "runner.worker"], env=self.env, cwd=ROOT,
            stdout=open(logs / "worker.log", "w"), stderr=subprocess.STDOUT))
        url = f"http://127.0.0.1:{self.port}/healthz"
        for _ in range(100):
            try:
                urllib.request.urlopen(url, timeout=1)
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f"server did not start; see {logs / 'server.log'}")

    def stop(self) -> None:
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

    # ---------- CLI ----------

    def vybd(self, *args: str, ok: bool = True) -> dict:
        cmd = [PY, "-m", "vybd_cli.main", "--json", *args]
        res = subprocess.run(cmd, env=self.env, cwd=ROOT, capture_output=True, text=True,
                             timeout=120)
        try:
            body = json.loads(res.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"`vybd {' '.join(args)}` printed non-JSON:\n{res.stdout}\n"
                               f"{res.stderr}") from e
        shown = " ".join(a if " " not in a else json.dumps(a) for a in args)
        self.log += [f"### `vybd {shown}`", "", f"exit {res.returncode} · ok={body.get('ok')}"]
        if body.get("agent_instructions"):
            self.log += ["", "> " + body["agent_instructions"].replace("\n", "\n> ")]
        if body.get("errors"):
            self.log += ["", f"errors: `{json.dumps(body['errors'])}`"]
        if body.get("next_actions"):
            self.log += ["", "next: " + ", ".join(f"`{a['action']}`"
                                                  for a in body["next_actions"])]
        self.log.append("")
        if ok and (res.returncode != 0 or not body.get("ok")):
            raise RuntimeError(f"`vybd {shown}` failed: {res.stdout}{res.stderr}")
        return body

    # ---------- the persona flow ----------

    def flow(self) -> dict:
        email = f"meera-{uuid.uuid4().hex[:8]}@example.com"
        self.vybd("signup", "--email", email, "--name", "Meera")
        self.vybd("brand", "create", "Kanthari")

        answered = []
        while True:
            nxt = self.vybd("challenge", "next")
            ch = nxt["data"]["challenge"]
            if ch is None:
                break
            res = self.vybd("challenge", "answer", ch["id"], "--text", ANSWERS[ch["id"]])
            assert res["data"]["claims"], "answer produced no claims"
            answered.append(ch["id"])
        assert len(answered) == 9, answered
        brief_minutes = (time.monotonic() - self.t0) / 60

        self.vybd("note", "We sell about 40 bottles a month at the Austin farmers market.")
        score = self.vybd("score")["data"]["score"]
        assert score["eligible"] and score["total"] == 100, score

        run = self.vybd("run", "submit")["data"]["run"]
        assert run["status"] == "queued", run  # AUTO_APPROVE_RUNS
        deadline = time.monotonic() + 120
        while True:
            st = self.vybd("run", "status")["data"]["run"]
            if st["status"] in ("completed", "failed", "cancelled"):
                break
            if time.monotonic() > deadline:
                raise RuntimeError(f"run stuck in {st['status']}")
            time.sleep(0.5)
        assert st["status"] == "completed", st
        report = self.vybd("run", "report")["data"]["report_md"]
        assert "## 30-day focus plan" in report
        self.vybd("run", "events")

        proposals = self.vybd("proposals")["data"]["proposals"]
        assert proposals, "run produced no proposals"
        self.vybd("proposals", "accept", proposals[0]["id"])
        if len(proposals) > 1:
            self.vybd("proposals", "reject", proposals[1]["id"], "--reason",
                      "our customers buy it weekly; it has to stay an everyday price")
        brief = self.vybd("brief")["data"]
        assert proposals[0]["text"] in brief["markdown"]
        return {"email": email, "run": st, "proposals": len(proposals),
                "brief_minutes": brief_minutes, "report": report,
                "claims": brief["claim_count"]}


def main() -> int:
    e2e = E2E()
    status, result, error = "PASSED", {}, ""
    try:
        e2e.start()
        result = e2e.flow()
    except Exception as e:
        status, error = "FAILED", f"{type(e).__name__}: {e}"
    finally:
        e2e.stop()

    total = time.monotonic() - e2e.t0
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = ROOT / "evals" / "runs" / f"clear_founder-fake-{stamp}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    head = [
        f"# e2e-fake: clear_founder ({status})", "",
        f"- when: {stamp} UTC · total {total:.1f}s · fake providers, AUTO_APPROVE_RUNS",
    ]
    if result:
        head += [f"- brief completed in {result['brief_minutes'] * 60:.1f}s (scripted)",
                 f"- run {result['run']['id']}: {result['run']['status']}, "
                 f"spent {result['run']['spent']}",
                 f"- proposals: {result['proposals']} · claims in brief: {result['claims']}"]
    if error:
        head += [f"- **error:** {error}", f"- logs: {e2e.home}"]
    body = head + ["", "## Transcript", "", *e2e.log]
    if result.get("report"):
        body += ["## Final report", "", result["report"]]
    out.write_text("\n".join(body) + "\n")
    print(f"e2e-fake {status} in {total:.1f}s; transcript: {out}")
    if error:
        print(error, file=sys.stderr)
    return 0 if status == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
