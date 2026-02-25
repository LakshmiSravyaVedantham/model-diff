"""CLI entry point for model-diff."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console

from model_diff.models import DEFAULT_MODELS, ALL_SUPPORTED_MODELS, ModelRunner
from model_diff.differ import DiffEngine

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_models(models_str: str) -> List[str]:
    """Split a comma-separated model list and strip whitespace."""
    return [m.strip() for m in models_str.split(",") if m.strip()]


def _load_prompt(prompt_text: Optional[str], prompt_file: Optional[str]) -> str:
    """Return the prompt string from either the positional arg or a file."""
    if prompt_file:
        p = Path(prompt_file)
        if not p.exists():
            console.print(f"[red]Error:[/red] prompt file '{prompt_file}' not found.")
            sys.exit(1)
        return p.read_text(encoding="utf-8").strip()
    if prompt_text:
        return prompt_text.strip()
    console.print(
        "[red]Error:[/red] You must supply a prompt as an argument or via --prompt."
    )
    console.print("Usage: model-diff \"Your prompt here\"")
    console.print("       model-diff --prompt prompt.txt")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------

@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("prompt_text", required=False, metavar="PROMPT")
@click.option(
    "--prompt",
    "prompt_file",
    default=None,
    metavar="FILE",
    help="Path to a text file containing the prompt (alternative to inline PROMPT).",
)
@click.option(
    "--models",
    "models_str",
    default=",".join(DEFAULT_MODELS),
    show_default=True,
    metavar="MODEL1,MODEL2,...",
    help=(
        "Comma-separated list of model IDs to compare.  "
        f"Supported: {', '.join(sorted(ALL_SUPPORTED_MODELS))}"
    ),
)
@click.option(
    "--diff",
    "diff_mode",
    default="lines",
    type=click.Choice(["lines", "words", "chars"], case_sensitive=False),
    show_default=True,
    help="Granularity of the diff: lines, words, or chars.",
)
@click.option(
    "--only-diff",
    is_flag=True,
    default=False,
    help="Hide matching sections and show only the differing parts.",
)
@click.option(
    "--output",
    "output_file",
    default=None,
    metavar="FILE",
    help="Save the full results as JSON to this file.",
)
@click.option(
    "--temperature",
    default=0.7,
    show_default=True,
    type=click.FloatRange(0.0, 2.0),
    help="Sampling temperature passed to each model (0.0 = deterministic).",
)
@click.version_option(package_name="model-diff")
def main(
    prompt_text: Optional[str],
    prompt_file: Optional[str],
    models_str: str,
    diff_mode: str,
    only_diff: bool,
    output_file: Optional[str],
    temperature: float,
) -> None:
    """
    Run the same prompt on multiple LLM models and show a side-by-side diff.

    \b
    Examples:
      model-diff "What is the best way to handle errors in Python?"
      model-diff "Explain recursion" --models gpt-4o,claude-sonnet-4-6
      model-diff --prompt prompt.txt --models gpt-4o-mini,claude-haiku-4-5-20251001
      model-diff "Explain recursion" --diff words --only-diff
      model-diff "Explain recursion" --output results.json --temperature 0.0
    """
    prompt = _load_prompt(prompt_text, prompt_file)

    requested_models = _parse_models(models_str)

    # Validate model names
    valid_models, warnings = ModelRunner.validate_models(requested_models)
    for w in warnings:
        console.print(f"[yellow]Warning:[/yellow] {w}")

    if not valid_models:
        console.print(
            "[red]Error:[/red] No valid models to run.  "
            f"Supported: {', '.join(sorted(ALL_SUPPORTED_MODELS))}"
        )
        sys.exit(1)

    # ── Run the models ────────────────────────────────────────────────
    console.print(
        f"\n[dim]Running prompt on {len(valid_models)} model(s): "
        f"{', '.join(valid_models)}  (temperature={temperature})[/dim]\n"
    )

    runner = ModelRunner(models=valid_models, temperature=temperature)
    results = runner.run(prompt)

    # ── Render ────────────────────────────────────────────────────────
    engine = DiffEngine(diff_mode=diff_mode, only_diff=only_diff, console=console)
    engine.render(
        prompt=prompt,
        results=results,
        temperature=temperature,
        output_file=output_file,
    )

    # Exit with non-zero if every model failed
    if all(r.error for r in results):
        sys.exit(2)
