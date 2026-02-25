"""Diff logic and Rich-based output formatting for model-diff."""

from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from model_diff.models import ModelResult

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
MODEL_COLOURS = [
    "bright_green",
    "bright_blue",
    "bright_yellow",
    "bright_magenta",
    "bright_cyan",
]

ADDED_STYLE = Style(color="green", bold=True)
REMOVED_STYLE = Style(color="red", bold=True)
COMMON_STYLE = Style(color="white", dim=True)
HEADER_STYLE = Style(color="bright_white", bold=True)


# ---------------------------------------------------------------------------
# DiffEngine
# ---------------------------------------------------------------------------

class DiffEngine:
    """Computes and renders diffs between ModelResult objects."""

    def __init__(
        self,
        diff_mode: str = "lines",   # "lines" | "words" | "chars"
        only_diff: bool = False,
        console: Optional[Console] = None,
    ) -> None:
        self.diff_mode = diff_mode
        self.only_diff = only_diff
        self.console = console or Console()

    # ------------------------------------------------------------------
    # Top-level entry points
    # ------------------------------------------------------------------

    def render(
        self,
        prompt: str,
        results: List[ModelResult],
        temperature: float,
        output_file: Optional[str] = None,
    ) -> None:
        """Render the full diff report to the console (and optionally a file)."""
        c = self.console

        # ── Header ──────────────────────────────────────────────────────
        c.print()
        c.print(
            Panel(
                "[bold bright_white]MODEL DIFF REPORT[/bold bright_white]",
                style="bold blue",
                expand=False,
            )
        )
        c.print()

        # ── Meta info ───────────────────────────────────────────────────
        successful = [r for r in results if not r.error]
        failed = [r for r in results if r.error]

        c.print(f"[bold]Prompt:[/bold] [italic]{_truncate(prompt, 120)}[/italic]")
        c.print(f"[bold]Temperature:[/bold] {temperature}")
        c.print(f"[bold]Compared:[/bold] {len(successful)} model(s)")
        if failed:
            for r in failed:
                c.print(
                    f"[yellow]  Warning:[/yellow] [bold]{r.model}[/bold] failed — {r.error}"
                )
        c.print()

        if not successful:
            c.print("[red bold]No successful model responses to display.[/red bold]")
            return

        # ── Individual model outputs ─────────────────────────────────────
        for idx, result in enumerate(successful):
            colour = MODEL_COLOURS[idx % len(MODEL_COLOURS)]
            self._render_model_section(result, colour)

        # ── Diff analysis (only meaningful with 2+ models) ──────────────
        if len(successful) >= 2:
            self._render_diff_analysis(successful)

        # ── Stats table ─────────────────────────────────────────────────
        self._render_stats(successful)

        # ── Save to file ─────────────────────────────────────────────────
        if output_file:
            self._save_json(prompt, temperature, results, output_file)
            c.print(f"\n[green]Results saved to:[/green] {output_file}")

    # ------------------------------------------------------------------
    # Individual model section
    # ------------------------------------------------------------------

    def _render_model_section(self, result: ModelResult, colour: str) -> None:
        c = self.console
        header = (
            f"[bold {colour}]{result.display_name}[/bold {colour}]"
            f"  [dim]({result.token_count} tokens, {result.elapsed:.2f}s)[/dim]"
        )
        c.print(Rule(title=header, style=colour))
        c.print()

        # Wrap text at 88 chars using Rich's word-wrap
        text = Text(result.text)
        c.print(text)
        c.print()

    # ------------------------------------------------------------------
    # Diff analysis section
    # ------------------------------------------------------------------

    def _render_diff_analysis(self, results: List[ModelResult]) -> None:
        c = self.console
        c.print(Rule(title="[bold bright_white]DIFF ANALYSIS[/bold bright_white]", style="bright_white"))
        c.print()

        # For >2 models we do pairwise diffs between adjacent models.
        # The "unique content" analysis uses a simple NLP-style sentence approach.
        pairs = list(zip(results, results[1:]))

        for a, b in pairs:
            colour_a = MODEL_COLOURS[results.index(a) % len(MODEL_COLOURS)]
            colour_b = MODEL_COLOURS[results.index(b) % len(MODEL_COLOURS)]

            similarity = self._similarity(a.text, b.text)
            c.print(
                f"[bold]Similarity[/bold] ({a.model} vs {b.model}): "
                f"[bold bright_yellow]{similarity:.0%}[/bold bright_yellow]"
            )
            c.print()

            # Unique sentences per model
            only_a, only_b, common = self._unique_sentences(a.text, b.text)

            if only_a:
                c.print(f"[bold {colour_a}]Only in {a.display_name}:[/bold {colour_a}]")
                for sent in only_a[:8]:
                    c.print(f"  [green]+ {sent}[/green]")
                c.print()

            if only_b:
                c.print(f"[bold {colour_b}]Only in {b.display_name}:[/bold {colour_b}]")
                for sent in only_b[:8]:
                    c.print(f"  [blue]+ {sent}[/blue]")
                c.print()

            if common:
                c.print("[bold]Common ground:[/bold]")
                for sent in common[:6]:
                    c.print(f"  [dim]• {sent}[/dim]")
                c.print()

            # Textual diff rendering
            self._render_textual_diff(a, b, colour_a, colour_b)

    def _render_textual_diff(
        self,
        a: ModelResult,
        b: ModelResult,
        colour_a: str,
        colour_b: str,
    ) -> None:
        """Render a unified-style diff between two model outputs."""
        c = self.console

        if self.diff_mode == "words":
            a_units = a.text.split()
            b_units = b.text.split()
            joiner = " "
        elif self.diff_mode == "chars":
            a_units = list(a.text)
            b_units = list(b.text)
            joiner = ""
        else:  # lines (default)
            a_units = a.text.splitlines()
            b_units = b.text.splitlines()
            joiner = "\n"

        diff = list(
            difflib.unified_diff(
                a_units,
                b_units,
                fromfile=a.display_name,
                tofile=b.display_name,
                lineterm="",
                n=1,
            )
        )

        if not diff:
            c.print("[dim]  (outputs are identical)[/dim]")
            return

        text = Text()
        shown_any = False
        for line in diff:
            if line.startswith("---") or line.startswith("+++"):
                continue
            if line.startswith("@@"):
                if not self.only_diff:
                    text.append(f"\n{line}\n", style="dim cyan")
                else:
                    text.append("\n...\n", style="dim")
                continue
            if line.startswith("-"):
                text.append(line + "\n", style=f"bold {colour_a}")
                shown_any = True
            elif line.startswith("+"):
                text.append(line + "\n", style=f"bold {colour_b}")
                shown_any = True
            else:
                if not self.only_diff:
                    text.append(line + "\n", style="dim")

        if shown_any or not self.only_diff:
            c.print(
                Panel(
                    text,
                    title=f"[dim]diff {a.display_name} → {b.display_name}[/dim]",
                    border_style="dim",
                    padding=(0, 1),
                )
            )
        c.print()

    # ------------------------------------------------------------------
    # Stats table
    # ------------------------------------------------------------------

    def _render_stats(self, results: List[ModelResult]) -> None:
        c = self.console
        c.print(Rule(title="[bold bright_white]STATS[/bold bright_white]", style="bright_white"))
        c.print()

        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("Model", style="bold", min_width=28)
        table.add_column("Tokens", justify="right", min_width=8)
        table.add_column("Est. Cost", justify="right", min_width=10)
        table.add_column("Time", justify="right", min_width=8)

        for idx, result in enumerate(results):
            colour = MODEL_COLOURS[idx % len(MODEL_COLOURS)]
            cost_str = (
                f"${result.estimated_cost:.4f}"
                if result.estimated_cost is not None
                else "n/a"
            )
            table.add_row(
                f"[{colour}]{result.display_name}[/{colour}]",
                str(result.token_count),
                cost_str,
                f"{result.elapsed:.2f}s",
            )

        c.print(table)
        c.print()

    # ------------------------------------------------------------------
    # Diff / similarity helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """Return a 0-1 similarity score between two strings."""
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        return difflib.SequenceMatcher(None, a, b).ratio()

    @staticmethod
    def _unique_sentences(
        a: str, b: str
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Split both texts into sentences, normalise them, then compute
        which are unique to each text and which appear in both.

        Returns (only_in_a, only_in_b, common).
        """
        def to_sentences(text: str) -> List[str]:
            # Split on sentence-ending punctuation
            raw = re.split(r"(?<=[.!?])\s+", text)
            out: List[str] = []
            for s in raw:
                s = s.strip()
                if len(s) > 20:  # ignore very short fragments
                    out.append(s)
            return out

        def normalise(s: str) -> str:
            return re.sub(r"\s+", " ", s.lower().strip())

        sents_a = to_sentences(a)
        sents_b = to_sentences(b)

        norm_a = {normalise(s): s for s in sents_a}
        norm_b = {normalise(s): s for s in sents_b}

        # Use SequenceMatcher to find "similar" sentences (fuzzy match)
        threshold = 0.55

        common: List[str] = []
        matched_b: set = set()

        for na, orig_a in norm_a.items():
            best_ratio = 0.0
            best_nb = None
            for nb in norm_b:
                if nb in matched_b:
                    continue
                ratio = difflib.SequenceMatcher(None, na, nb).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_nb = nb
            if best_ratio >= threshold and best_nb is not None:
                common.append(_truncate(orig_a, 90))
                matched_b.add(best_nb)

        common_norm_a = set()
        common_norm_b = set(matched_b)
        for sent in common:
            for na in norm_a:
                if _truncate(norm_a[na], 90) == sent or normalise(sent) == na:
                    common_norm_a.add(na)
                    break
                # fallback: fuzzy
                if difflib.SequenceMatcher(None, normalise(sent), na).ratio() >= threshold:
                    common_norm_a.add(na)
                    break

        only_a = [
            _truncate(s, 90)
            for na, s in norm_a.items()
            if not any(
                difflib.SequenceMatcher(None, na, nb).ratio() >= threshold
                for nb in common_norm_b
            )
        ]
        only_b = [
            _truncate(s, 90)
            for nb, s in norm_b.items()
            if nb not in common_norm_b
        ]

        return only_a, only_b, common

    # ------------------------------------------------------------------
    # JSON export
    # ------------------------------------------------------------------

    @staticmethod
    def _save_json(
        prompt: str,
        temperature: float,
        results: List[ModelResult],
        path: str,
    ) -> None:
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "temperature": temperature,
            "results": [
                {
                    "model": r.model,
                    "text": r.text,
                    "error": r.error,
                    "elapsed_seconds": round(r.elapsed, 3),
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "estimated_cost_usd": (
                        round(r.estimated_cost, 6)
                        if r.estimated_cost is not None
                        else None
                    ),
                }
                for r in results
            ],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
