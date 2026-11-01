"""vybd CLI — thin HTTP client over the server API (spec §9). No business logic here.

Human-friendly output by default; `--json` prints the raw envelope (for agents).
Exit codes: 0 ok, 1 error envelope, 2 server unreachable / local config problem.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Annotated, Any

import typer

from vybd_cli import client, config, render

app = typer.Typer(help="Vybd Brand Builder CLI", no_args_is_help=True, add_completion=False)
brand_app = typer.Typer(help="Create, list and switch brands.", no_args_is_help=True)
challenge_app = typer.Typer(help="Work through the brand brief challenges.",
                            no_args_is_help=True)
run_app = typer.Typer(help="Submit and follow Brand Brain runs.", no_args_is_help=True)
proposals_app = typer.Typer(help="Review proposed brief changes (lists them by default).",
                            invoke_without_command=True)
admin_app = typer.Typer(help="Admin: approve or cancel runs.", no_args_is_help=True)
app.add_typer(brand_app, name="brand")
app.add_typer(challenge_app, name="challenge")
app.add_typer(run_app, name="run")
app.add_typer(proposals_app, name="proposals")
app.add_typer(admin_app, name="admin")

JsonOpt = Annotated[bool, typer.Option("--json", help="Print the raw response envelope.")]
_state = {"json": False}


@app.callback()
def _main(as_json: JsonOpt = False) -> None:
    _state["json"] = as_json


# ---------------- plumbing ----------------

def _fail_local(message: str, as_json: bool, code: str = "local_error") -> None:
    if as_json or _state["json"]:
        typer.echo(json.dumps({"ok": False, "data": None, "agent_instructions": message,
                               "next_actions": [], "progress": None,
                               "errors": [{"code": code, "message": message, "field": None}]}))
    else:
        render.err_console.print(f"[red]{message}[/red]")
    raise typer.Exit(2)


def call(method: str, path: str, *, as_json: bool, render_fn: Callable[[dict], None] | None,
         json_body: Any = None, params: dict | None = None, auth: bool = True,
         on_ok: Callable[[dict], None] | None = None) -> dict:
    """Do the request, persist any local state (`on_ok`) BEFORE printing, then render."""
    as_json = as_json or _state["json"]
    try:
        env = client.request(method, path, json=json_body, params=params, auth=auth)
    except client.Unreachable as e:
        _fail_local(f"{e} Is it running? (`make dev`, or set VYBD_API_URL)", as_json,
                    code="unreachable")
    if env.get("ok") and on_ok:
        on_ok(env)
    if as_json:
        typer.echo(json.dumps(env, indent=2))
    elif not env.get("ok"):
        render.errors(env)
    else:
        (render_fn or (lambda e: render.generic(e.get("data"))))(env)
        render.progress(env)
        render.hints(env)
    if not env.get("ok"):
        raise typer.Exit(1)
    return env


def brand_id(as_json: bool) -> str:
    bid = config.load().get("current_brand")
    if not bid:
        _fail_local("No current brand. Run `vybd brand create \"Name\"` or `vybd brand use <id>`.",
                    as_json, code="no_brand")
    return bid


def run_id(rid: str | None, as_json: bool) -> str:
    rid = rid or config.load().get("last_run")
    if not rid:
        _fail_local("No run id given and no recent run. Pass one, or `vybd run submit` first.",
                    as_json, code="no_run")
    return rid


def read_text(text: str) -> str:
    return sys.stdin.read() if text == "-" else text


# ---------------- misc ----------------

@app.command()
def health(as_json: JsonOpt = False) -> None:
    """Check the server is up."""
    call("GET", "/healthz", as_json=as_json, auth=False,
         render_fn=lambda e: render.console.print(f"vybd-server [green]up[/green] at "
                                                  f"{config.api_url()}"))


@app.command()
def ui(open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True) -> None:
    """Open the brand view in your browser, signed in as you (token stays in the URL fragment)."""
    import webbrowser
    from urllib.parse import urlencode

    cfg = config.load()
    if not cfg.get("token"):
        _fail_local("Not signed in. Run `vybd signup --email ...` first.", False, code="no_token")
    frag = {"token": cfg["token"]}
    if cfg.get("current_brand"):
        frag["brand"] = cfg["current_brand"]
    url = f"{config.api_url()}/ui#{urlencode(frag)}"
    if open_browser:
        webbrowser.open(url)
    typer.echo(f"Brand view: {config.api_url()}/ui  (opened signed in)" if open_browser else url)


@app.command()
def version() -> None:
    """Print the CLI version."""
    typer.echo("vybd-cli 0.0.0")


# ---------------- auth ----------------

@app.command()
def signup(email: Annotated[str, typer.Option("--email", help="Your email")],
           name: Annotated[str | None, typer.Option("--name", help="Display name")] = None,
           as_json: JsonOpt = False) -> None:
    """Create an account. The token is saved to ~/.vybd/config.toml."""
    def show(env: dict) -> None:
        u = env["data"]["user"]
        render.console.print(f"Signed up as [bold]{u['email']}[/bold]. Token saved to "
                             f"{config.path()}.")

    def save(env: dict) -> None:
        config.update(token=env["data"]["token"], email=env["data"]["user"]["email"],
                      current_brand=None, last_run=None)

    call("POST", "/v1/auth/signup", as_json=as_json, render_fn=show, on_ok=save,
         json_body={"email": email, "display_name": name}, auth=False)


@app.command()
def whoami(as_json: JsonOpt = False) -> None:
    """Show the signed-in user."""
    def show(env: dict) -> None:
        u = env["data"]["user"]
        admin = " [magenta](admin)[/magenta]" if u.get("is_admin") else ""
        render.console.print(f"{u['display_name']} <{u['email']}>{admin} · "
                             f"{u.get('brand_count', 0)} brand(s)")
        cur = config.load().get("current_brand")
        if cur:
            render.console.print(f"[dim]current brand: {cur}[/dim]")

    call("GET", "/v1/me", as_json=as_json, render_fn=show)


# ---------------- brands ----------------

@brand_app.command("create")
def brand_create(name: str, as_json: JsonOpt = False) -> None:
    """Create a brand and make it current."""
    def show(env: dict) -> None:
        b = env["data"]["brand"]
        render.console.print(f"Created [bold]{b['name']}[/bold] ({b['id']}) — now current.")

    call("POST", "/v1/brands", as_json=as_json, render_fn=show, json_body={"name": name},
         on_ok=lambda env: config.update(current_brand=env["data"]["brand"]["id"],
                                         last_run=None))


@brand_app.command("list")
def brand_list(as_json: JsonOpt = False) -> None:
    """List your brands."""
    cur = config.load().get("current_brand")

    def show(env: dict) -> None:
        rows = [{**b, "cur": "*" if b["id"] == cur else ""} for b in env["data"]["brands"]]
        if not rows:
            render.console.print("No brands yet.")
            return
        render.table(rows, [("cur", ""), ("name", "Name"), ("id", "ID")])

    call("GET", "/v1/brands", as_json=as_json, render_fn=show)


@brand_app.command("use")
def brand_use(brand: str, as_json: JsonOpt = False) -> None:
    """Switch the current brand (client-side; checked against your brand list)."""
    try:
        env = client.request("GET", "/v1/brands")
    except client.Unreachable as e:
        _fail_local(str(e), as_json, code="unreachable")
    if not env.get("ok"):
        if as_json or _state["json"]:
            typer.echo(json.dumps(env, indent=2))
        else:
            render.errors(env)
        raise typer.Exit(1)
    ids = {b["id"]: b["name"] for b in env["data"]["brands"]}
    if brand not in ids:
        _fail_local(f"Brand {brand} isn't one of yours. See `vybd brand list`.", as_json,
                    code="not_found")
    config.update(current_brand=brand, last_run=None)
    if as_json or _state["json"]:
        typer.echo(json.dumps({"ok": True, "data": {"current_brand": brand}, "errors": [],
                               "agent_instructions": "", "next_actions": [], "progress": None}))
    else:
        render.console.print(f"Current brand: [bold]{ids[brand]}[/bold] ({brand})")


# ---------------- brief, challenges, notes, score ----------------

@app.command()
def brief(section: Annotated[str | None, typer.Option("--section")] = None,
          as_json: JsonOpt = False) -> None:
    """Show the brand brief built so far."""
    bid = brand_id(as_json)

    def show(env: dict) -> None:
        d = env["data"]
        render.console.print(f"[bold]{d['brand']['name']}[/bold] [dim]brief v{d['version']} · "
                             f"{d['claim_count']} claims[/dim]\n")
        if section:
            for s in d["sections"]:
                render.markdown(f"## {s['title']}\n" + "\n".join(f"- {c['text']}"
                                                                 for c in s["claims"]))
        else:
            render.markdown(d["markdown"])

    call("GET", f"/v1/brands/{bid}/brief", as_json=as_json, render_fn=show,
         params={"section": section} if section else None)


@challenge_app.command("next")
def challenge_next(as_json: JsonOpt = False) -> None:
    """Get the next challenge."""
    bid = brand_id(as_json)

    def show(env: dict) -> None:
        ch = env["data"]["challenge"]
        if ch:
            render.challenge(ch)
        else:
            render.console.print("[green]All challenges answered — the brief is ready.[/green]")

    call("GET", f"/v1/brands/{bid}/challenges/next", as_json=as_json, render_fn=show)


@challenge_app.command("list")
def challenge_list(as_json: JsonOpt = False) -> None:
    """List all challenges and their status."""
    bid = brand_id(as_json)

    def show(env: dict) -> None:
        rows = []
        for c in env["data"]["challenges"]:
            ans = c.get("answer") or ""
            rows.append({**c, "req": "yes" if c["required"] else "optional",
                         "answer": (ans[:60] + "…") if len(ans) > 60 else ans,
                         "status": "✓" if c["status"] == "answered" else "·"})
        render.table(rows, [("status", ""), ("id", "ID"), ("title", "Title"), ("req", "Required"),
                            ("answer", "Answer")])

    call("GET", f"/v1/brands/{bid}/challenges", as_json=as_json, render_fn=show)


@challenge_app.command("answer")
def challenge_answer(
    challenge_id: str,
    text: Annotated[str, typer.Option("--text", help="The founder's answer ('-' reads stdin)")],
    evidence: Annotated[list[str] | None, typer.Option("--evidence", help="Supporting URL")] = None,
    as_json: JsonOpt = False,
) -> None:
    """Submit the founder's answer to a challenge."""
    bid = brand_id(as_json)

    def show(env: dict) -> None:
        d = env["data"]
        render.console.print(f"[green]Saved[/green] {d['challenge_id']}:")
        render.claims(d["claims"])
        if d.get("superseded_claim_ids"):
            render.console.print("[dim](replaced your earlier answer)[/dim]")
        fb = d.get("feedback") or {}
        if fb.get("note"):
            render.console.print(f"\n[yellow]Feedback:[/yellow] {fb['note']}")
            if fb.get("suggestion"):
                render.console.print(f"[dim]Suggestion: {fb['suggestion']}[/dim]")
        if d.get("next_challenge"):
            render.console.print()
            render.challenge(d["next_challenge"])
        else:
            render.console.print("\n[green]All challenges answered — the brief is ready.[/green]")

    call("POST", f"/v1/brands/{bid}/challenges/{challenge_id}/answer", as_json=as_json,
         render_fn=show, json_body={"text": read_text(text), "evidence": evidence or []})


@app.command()
def note(text: Annotated[str, typer.Argument(help="Note text ('-' reads stdin)")],
         as_json: JsonOpt = False) -> None:
    """Add a free-form note to the brand brain."""
    bid = brand_id(as_json)

    def show(env: dict) -> None:
        render.console.print("[green]Note saved.[/green]")
        render.claims(env["data"]["claims"])

    call("POST", f"/v1/brands/{bid}/notes", as_json=as_json, render_fn=show,
         json_body={"text": read_text(text)})


@app.command()
def score(as_json: JsonOpt = False) -> None:
    """Show the brief score and run eligibility."""
    bid = brand_id(as_json)

    def show(env: dict) -> None:
        sc = env["data"].get("score") or {}
        state = "[green]eligible[/green]" if sc.get("eligible") else "[yellow]not eligible[/yellow]"
        render.console.print(f"Score [bold]{sc.get('total', 0):g}[/bold]/100 · {state}")
        for k, v in (sc.get("by_section") or {}).items():
            render.console.print(f"  {k}: {v:g}")
        for reason in sc.get("missing") or []:
            render.console.print(f"  [dim]missing: {reason}[/dim]")

    call("GET", f"/v1/brands/{bid}/score", as_json=as_json, render_fn=show)


# ---------------- runs ----------------

def _show_run(env: dict) -> None:
    r = env["data"]["run"]
    render.console.print(f"Run [bold]{r['id']}[/bold]: [cyan]{r['status']}[/cyan]"
                         + (f" · phase {r['current_phase']}" if r.get("current_phase") else ""))
    spent = r.get("spent") or {}
    if spent:
        render.console.print("[dim]spent: " + ", ".join(f"{k}={v}" for k, v in spent.items())
                             + "[/dim]")
    if r.get("error"):
        render.console.print(f"[red]{r['error']}[/red]")


@run_app.command("submit")
def run_submit(as_json: JsonOpt = False) -> None:
    """Submit the brief for a Brand Brain run."""
    bid = brand_id(as_json)
    call("POST", f"/v1/brands/{bid}/runs", as_json=as_json, render_fn=_show_run,
         on_ok=lambda env: config.update(last_run=env["data"]["run"]["id"]))


@run_app.command("status")
def run_status(rid: Annotated[str | None, typer.Argument(metavar="RUN_ID")] = None,
               as_json: JsonOpt = False) -> None:
    """Show a run's status (defaults to your latest run)."""
    call("GET", f"/v1/runs/{run_id(rid, as_json)}", as_json=as_json, render_fn=_show_run)


@run_app.command("events")
def run_events(rid: Annotated[str | None, typer.Argument(metavar="RUN_ID")] = None,
               as_json: JsonOpt = False) -> None:
    """Show a run's event log."""
    def show(env: dict) -> None:
        render.table(env["data"]["events"], [("created_at", "Time"), ("phase", "Phase"),
                                              ("kind", "Kind"), ("message", "Message")])

    call("GET", f"/v1/runs/{run_id(rid, as_json)}/events", as_json=as_json, render_fn=show)


@run_app.command("report")
def run_report(rid: Annotated[str | None, typer.Argument(metavar="RUN_ID")] = None,
               as_json: JsonOpt = False) -> None:
    """Show a finished run's report."""
    call("GET", f"/v1/runs/{run_id(rid, as_json)}/report", as_json=as_json,
         render_fn=lambda env: render.markdown(env["data"].get("report_md") or ""))


# ---------------- proposals ----------------

@proposals_app.callback()
def proposals_list(ctx: typer.Context,
                   status: Annotated[str, typer.Option("--status")] = "pending",
                   as_json: JsonOpt = False) -> None:
    """List proposed brief changes (default: pending)."""
    if ctx.invoked_subcommand:
        return
    bid = brand_id(as_json)

    def show(env: dict) -> None:
        items = env["data"]["proposals"]
        if not items:
            render.console.print(f"No {status} proposals.")
            return
        for p in items:
            render.console.print(f"[bold]{p['id']}[/bold] [dim]{p['section']} · {p['kind']} · "
                                 f"{p['status']}[/dim]\n  {p['text']}\n  [dim]why: "
                                 f"{p['rationale']}[/dim]")

    call("GET", f"/v1/brands/{bid}/proposals", as_json=as_json, render_fn=show,
         params={"status": status})


@proposals_app.command("accept")
def proposals_accept(proposal_id: str, as_json: JsonOpt = False) -> None:
    """Accept a proposal into the brief."""
    bid = brand_id(as_json)
    call("POST", f"/v1/brands/{bid}/proposals/{proposal_id}/accept", as_json=as_json,
         render_fn=lambda env: render.console.print("[green]Accepted[/green] — added to the "
                                                    "brief."))


@proposals_app.command("reject")
def proposals_reject(proposal_id: str,
                     reason: Annotated[str, typer.Option("--reason", help="Why (remembered)")],
                     as_json: JsonOpt = False) -> None:
    """Reject a proposal; the reason is remembered so it isn't proposed again."""
    bid = brand_id(as_json)
    call("POST", f"/v1/brands/{bid}/proposals/{proposal_id}/reject", as_json=as_json,
         json_body={"reason": reason},
         render_fn=lambda env: render.console.print("Rejected. The reason was saved to the "
                                                    "brain."))


# ---------------- admin ----------------

@admin_app.command("runs")
def admin_runs(status: Annotated[str, typer.Option("--status")] = "requested",
               as_json: JsonOpt = False) -> None:
    """List runs (default: awaiting approval)."""
    def show(env: dict) -> None:
        runs = env["data"]["runs"]
        if not runs:
            render.console.print(f"No {status} runs.")
            return
        render.table(runs, [("id", "Run"), ("brand_name", "Brand"), ("status", "Status"),
                            ("created_at", "Requested")])

    call("GET", "/v1/admin/runs", as_json=as_json, render_fn=show, params={"status": status})


@admin_app.command("approve")
def admin_approve(rid: Annotated[str, typer.Argument(metavar="RUN_ID")],
                  as_json: JsonOpt = False) -> None:
    """Approve a requested run (it is queued for a worker)."""
    call("POST", f"/v1/admin/runs/{rid}/approve", as_json=as_json, render_fn=_show_run)


@admin_app.command("cancel")
def admin_cancel(rid: Annotated[str, typer.Argument(metavar="RUN_ID")],
                 as_json: JsonOpt = False) -> None:
    """Cancel a run."""
    call("POST", f"/v1/admin/runs/{rid}/cancel", as_json=as_json, render_fn=_show_run)


if __name__ == "__main__":
    app()
