"""Human-friendly rendering of envelopes. `--json` bypasses all of this."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def errors(env: dict[str, Any]) -> None:
    for e in env.get("errors") or []:
        field = f" ({e['field']})" if e.get("field") else ""
        err_console.print(
            f"[red]Error[/red] [bold]{e.get('code')}[/bold]{field}: {e.get('message')}"
        )
    if env.get("agent_instructions"):
        err_console.print(f"[dim]{env['agent_instructions']}[/dim]")
    hints(env, to=err_console)


def hints(env: dict[str, Any], to: Console = console) -> None:
    actions = env.get("next_actions") or []
    if not actions:
        return
    to.print("\n[bold]Next:[/bold]")
    for a in actions[:4]:
        to.print(f"  [cyan]{a['cli']}[/cyan]  [dim]{a['description']}[/dim]")


def progress(env: dict[str, Any]) -> None:
    p = env.get("progress")
    if not p:
        return
    bits = [f"{p['completed']}/{p['required']} required done",
            f"~{p['est_minutes_left']:g} min left"]
    if p.get("score") is not None:
        bits.append(f"score {p['score']:g}")
    if p.get("eligible") is not None:
        bits.append("[green]ready to submit[/green]" if p["eligible"] else "not yet eligible")
    console.print("[dim]" + " · ".join(bits) + "[/dim]")


def generic(data: Any) -> None:
    if data in (None, {}, []):
        return
    console.print_json(json.dumps(data, default=str))


def challenge(ch: dict[str, Any], progress_env: dict[str, Any] | None = None) -> None:
    head = f"{ch['title']}  [dim](~{ch['est_minutes']:g} min" + \
        (", optional)" if not ch["required"] else ")") + "[/dim]"
    body = [ch["lesson"].strip(), "", f"[italic dim]Example: {ch['example'].strip()}[/italic dim]",
            "", f"[bold]{ch['task'].strip()}[/bold]"]
    if ch.get("quick_replies"):
        body += ["", "Quick replies: " + " | ".join(ch["quick_replies"])]
    console.print(Panel("\n".join(body), title=head, title_align="left", border_style="cyan",
                        subtitle=f"id: {ch['id']}", subtitle_align="right"))


def claims(items: list[dict[str, Any]]) -> None:
    for c in items:
        console.print(f"  [green]•[/green] {c['text']}  [dim]({c['section']}, {c['kind']})[/dim]")


def table(rows: list[dict[str, Any]], columns: list[tuple[str, str]], title: str = "") -> None:
    t = Table(title=title or None, show_lines=False)
    for _, header in columns:
        t.add_column(header)
    for r in rows:
        t.add_row(*["" if r.get(k) is None else str(r.get(k)) for k, _ in columns])
    console.print(t)


def markdown(text: str) -> None:
    console.print(Markdown(text or "_(empty)_"))
