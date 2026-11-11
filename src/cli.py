"""Rich CLI interface for heal-qa locator inspector and test patcher."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from src.matcher.dom_healer import DOMHealer
from src.patcher.code_patcher import TestPatcher

app = typer.Typer(
    name="heal-qa",
    help="Self-healing e2e test runner & locator resolver for Playwright/UI tests.",
    add_completion=False,
)
console = Console()


def _load_html_snapshot(html_source: str) -> tuple[str, str]:
    """Load HTML snapshot from URL, file path, or raw string.

    Returns:
        tuple[str, str]: (html_content, description_of_source)
    """
    source_lower = html_source.strip().lower()

    if source_lower.startswith("http://") or source_lower.startswith("https://"):
        try:
            req = urllib.request.Request(
                html_source,
                headers={"User-Agent": "heal-qa/0.1.0 (Python Playwright Healer)"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                return content, f"URL: {html_source}"
        except Exception as err:
            console.print(f"[bold red]Error fetching URL '{html_source}':[/] {err}")
            raise typer.Exit(code=1)

    path = Path(html_source)
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8"), f"File: {path.resolve()}"
        except Exception as err:
            console.print(f"[bold red]Error reading file '{html_source}':[/] {err}")
            raise typer.Exit(code=1)

    # Raw HTML string
    return html_source, "Inline HTML Snapshot"


@app.command(name="inspect", help="Interactively inspect broken selector against DOM snapshot.")
def inspect_command(
    selector: str = typer.Option(..., "--selector", "-s", help="Broken selector to heal"),
    html: str = typer.Option(..., "--html", "-h", help="Path to HTML file, URL, or raw HTML string"),
    expected_text: Optional[str] = typer.Option(
        None, "--text", "-t", "--expected-text", help="Expected visible text / label / placeholder"
    ),
    expected_tag: Optional[str] = typer.Option(
        None, "--tag", "--expected-tag", help="Expected HTML tag name (e.g. button, input)"
    ),
    threshold: float = typer.Option(
        0.5, "--threshold", min=0.0, max=1.0, help="Confidence threshold (0.0 - 1.0)"
    ),
) -> None:
    """Inspect broken selector and output ranked candidates with confidence scoring."""
    content, source_desc = _load_html_snapshot(html)

    console.print(
        Panel.fit(
            f"[bold cyan]Broken Selector:[/] [bold red]{selector}[/]\n"
            f"[bold cyan]Snapshot Source:[/] {source_desc}\n"
            f"[bold cyan]Expected Text:[/] [yellow]{expected_text or '<None>'}[/]\n"
            f"[bold cyan]Expected Tag:[/] [magenta]{expected_tag or '<Auto>'}[/]\n"
            f"[bold cyan]Confidence Threshold:[/] {threshold:.0%}",
            title="[bold green]heal-qa DOM Inspector[/]",
            border_style="cyan",
        )
    )

    healer = DOMHealer(min_confidence=threshold)
    candidates = healer.find_candidates(
        broken_selector=selector,
        html_snapshot=content,
        expected_text=expected_text,
        expected_tag=expected_tag,
    )

    if not candidates:
        console.print("[bold red]No candidate elements found in the DOM snapshot.[/]")
        raise typer.Exit(code=1)

    # Build rich table
    table = Table(
        title="Candidate Match Ranking",
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
    )
    table.add_column("#", justify="center", width=4)
    table.add_column("Candidate Selector", style="bold cyan")
    table.add_column("Confidence", justify="right")
    table.add_column("Text (40%)", justify="right")
    table.add_column("A11y (30%)", justify="right")
    table.add_column("Tag (20%)", justify="right")
    table.add_column("Class/ID (10%)", justify="right")
    table.add_column("Tag & Details", style="dim")

    top_candidates = candidates[:10]
    for idx, c in enumerate(top_candidates, 1):
        if c.score >= 0.7:
            score_style = "[bold green]"
        elif c.score >= threshold:
            score_style = "[bold yellow]"
        else:
            score_style = "[red]"

        elem_preview = f"<{c.element.name}"
        if c.element.get("id"):
            elem_preview += f" id=\"{c.element['id']}\""
        if c.element.get("class"):
            cls_str = " ".join(c.element["class"]) if isinstance(c.element["class"], list) else c.element["class"]
            elem_preview += f" class=\"{cls_str}\""
        elem_preview += ">"

        table.add_row(
            str(idx),
            c.selector,
            f"{score_style}{c.score:.1%}[/]",
            f"{c.text_score:.2f}",
            f"{c.a11y_score:.2f}",
            f"{c.tag_score:.2f}",
            f"{c.class_id_score:.2f}",
            elem_preview[:40] + ("..." if len(elem_preview) > 40 else ""),
        )

    console.print(table)

    best = candidates[0]
    if best.score >= threshold:
        console.print(
            Panel(
                f"[bold green]✓ Recommended Replacement:[/] [bold white on blue] {best.selector} [/] "
                f"(Confidence: [bold green]{best.score:.1%}[/])\n\n"
                f"[dim]To apply fix to a test file, run:[/]\n"
                f"[bold cyan]heal-qa patch --file <test_file.py> --old \"{selector}\" --new \"{best.selector}\"[/]",
                title="[bold green]Healing Recommendation[/]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]✗ No candidate reached confidence threshold ({threshold:.0%}).[/]\n"
                f"Top candidate had confidence of [bold yellow]{best.score:.1%}[/] ({best.selector}).\n"
                f"[dim]False healing prevented to protect test suite integrity.[/]",
                title="[bold red]Threshold Warning[/]",
                border_style="red",
            )
        )


@app.command(name="patch", help="Safely update broken selector in test file with diff.")
def patch_command(
    file: str = typer.Option(..., "--file", "-f", help="Path to test file to patch"),
    old_selector: str = typer.Option(..., "--old", "-o", help="Old broken selector string"),
    new_selector: str = typer.Option(..., "--new", "-n", help="New healed selector string"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Display unified diff without modifying the test file"
    ),
) -> None:
    """Safely patch test file locators while preserving indentation, comments, and quotes."""
    path = Path(file)
    if not path.is_file():
        console.print(f"[bold red]Error:[/] File '{file}' does not exist.")
        raise typer.Exit(code=1)

    patcher = TestPatcher()
    try:
        diff = patcher.get_diff(path, old_selector=old_selector, new_selector=new_selector)
    except Exception as err:
        console.print(f"[bold red]Error preparing diff:[/] {err}")
        raise typer.Exit(code=1)

    if not diff:
        console.print(
            f"[bold yellow]Warning:[/] No occurrences of selector '{old_selector}' found in '{file}'. Nothing to patch."
        )
        raise typer.Exit(code=0)

    console.print(
        Panel(
            Syntax(diff, "diff", theme="monokai", line_numbers=True),
            title=f"[bold cyan]Proposed Changes for {path.name}[/]",
            border_style="cyan",
        )
    )

    if dry_run:
        console.print("[yellow]Dry-run mode: no changes were written to file.[/]")
        return

    success = patcher.patch_test_file(path, old_selector=old_selector, new_selector=new_selector)
    if success:
        console.print(
            Panel(
                f"[bold green]✓ Successfully updated test file:[/] [cyan]{path.resolve()}[/]\n"
                f"Replaced: [red]'{old_selector}'[/] ➔ [green]'{new_selector}'[/]",
                border_style="green",
            )
        )
    else:
        console.print("[yellow]File was not modified.[/]")


if __name__ == "__main__":
    app()
