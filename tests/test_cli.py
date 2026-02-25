"""Tests for the CLI entry point."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from model_diff.cli import main
from model_diff.models import ModelResult, ModelRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(model: str, text: str = "Test response.") -> ModelResult:
    r = ModelResult(model=model, text=text, elapsed=0.5)
    r.input_tokens = 20
    r.output_tokens = 30
    r.compute_cost("prompt")
    return r


def _patch_runner(models, texts=None):
    """
    Context manager that patches ModelRunner so:
      - ModelRunner.validate_models() returns (models, [])
      - ModelRunner(...).run() returns pre-built ModelResult objects

    Usage::

        with _patch_runner(["gpt-4o"]) as (MockClass, mock_instance):
            ...
    """
    from contextlib import contextmanager

    if texts is None:
        texts = ["Response from " + m for m in models]

    results = [_make_result(m, t) for m, t in zip(models, texts)]

    @contextmanager
    def _ctx():
        mock_instance = MagicMock()
        mock_instance.run.return_value = results

        MockClass = MagicMock(return_value=mock_instance)
        MockClass.validate_models = MagicMock(return_value=(models, []))

        with patch("model_diff.cli.ModelRunner", MockClass):
            yield MockClass, mock_instance

    return _ctx()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCLI:
    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_help_flag(self) -> None:
        result = self.runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "PROMPT" in result.output or "prompt" in result.output.lower()

    def test_version_flag(self) -> None:
        result = self.runner.invoke(main, ["--version"])
        assert result.exit_code == 0

    def test_no_prompt_exits_with_error(self) -> None:
        result = self.runner.invoke(main, [])
        assert result.exit_code != 0

    def test_inline_prompt(self) -> None:
        models = ["gpt-4o", "claude-sonnet-4-6"]
        with _patch_runner(models) as (_, mock_instance):
            result = self.runner.invoke(
                main,
                ["Hello!", "--models", "gpt-4o,claude-sonnet-4-6"],
            )

        assert result.exit_code == 0, result.output
        mock_instance.run.assert_called_once_with("Hello!")

    def test_prompt_file(self, tmp_path) -> None:
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("My file prompt")

        models = ["gpt-4o"]
        with _patch_runner(models) as (_, mock_instance):
            result = self.runner.invoke(
                main,
                ["--prompt", str(prompt_file), "--models", "gpt-4o"],
            )

        assert result.exit_code == 0, result.output
        mock_instance.run.assert_called_once_with("My file prompt")

    def test_missing_prompt_file(self) -> None:
        result = self.runner.invoke(main, ["--prompt", "/nonexistent/file.txt"])
        assert result.exit_code != 0

    def test_invalid_model_name(self) -> None:
        result = self.runner.invoke(
            main, ["Hello", "--models", "gpt-999-fake"]
        )
        # Should exit non-zero because no valid models remain
        assert result.exit_code != 0

    def test_temperature_passed_to_runner(self) -> None:
        models = ["gpt-4o"]
        with _patch_runner(models) as (MockClass, _):
            result = self.runner.invoke(
                main,
                ["Hello", "--models", "gpt-4o", "--temperature", "0.0"],
            )

        assert result.exit_code == 0, result.output
        MockClass.assert_called_once_with(models=["gpt-4o"], temperature=0.0)

    def test_output_file_flag(self, tmp_path) -> None:
        out_file = str(tmp_path / "out.json")
        models = ["gpt-4o", "claude-sonnet-4-6"]
        with _patch_runner(models) as (_, mock_instance):
            result = self.runner.invoke(
                main,
                ["Hello", "--models", "gpt-4o,claude-sonnet-4-6", "--output", out_file],
            )

        assert result.exit_code == 0, result.output
        assert os.path.exists(out_file)

    def test_all_models_fail_exits_nonzero(self) -> None:
        failed = ModelResult(model="gpt-4o", error="API key missing")

        mock_instance = MagicMock()
        mock_instance.run.return_value = [failed]

        MockClass = MagicMock(return_value=mock_instance)
        MockClass.validate_models = MagicMock(return_value=(["gpt-4o"], []))

        with patch("model_diff.cli.ModelRunner", MockClass):
            result = self.runner.invoke(
                main,
                ["Hello", "--models", "gpt-4o"],
            )

        assert result.exit_code == 2

    def test_diff_mode_words(self) -> None:
        models = ["gpt-4o", "claude-sonnet-4-6"]
        with _patch_runner(models) as (_, _inst):
            result = self.runner.invoke(
                main,
                ["Hello", "--models", "gpt-4o,claude-sonnet-4-6", "--diff", "words"],
            )

        assert result.exit_code == 0, result.output

    def test_only_diff_flag(self) -> None:
        models = ["gpt-4o", "claude-sonnet-4-6"]
        texts = [
            "Line one.\nLine two.\nLine three.",
            "Line one.\nLine TWO modified.\nLine three.",
        ]
        with _patch_runner(models, texts=texts) as (_, _inst):
            result = self.runner.invoke(
                main,
                ["Hello", "--models", "gpt-4o,claude-sonnet-4-6", "--only-diff"],
            )

        assert result.exit_code == 0, result.output
