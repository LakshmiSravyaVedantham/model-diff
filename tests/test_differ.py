"""Tests for the diff engine."""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from rich.console import Console

from model_diff.differ import DiffEngine, _truncate
from model_diff.models import ModelResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def null_console() -> Console:
    """Return a Console that writes to /dev/null so tests stay clean."""
    return Console(file=open(os.devnull, "w"), highlight=False)


def _result(model: str, text: str, elapsed: float = 0.5) -> ModelResult:
    r = ModelResult(model=model, text=text, elapsed=elapsed)
    r.output_tokens = int(len(text.split()) * 1.3)
    return r


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_string_unchanged(self) -> None:
        assert _truncate("hello", 20) == "hello"

    def test_long_string_truncated(self) -> None:
        result = _truncate("a" * 100, 10)
        assert len(result) == 10
        assert result.endswith("...")

    def test_exact_length_unchanged(self) -> None:
        s = "a" * 10
        assert _truncate(s, 10) == s


# ---------------------------------------------------------------------------
# DiffEngine.similarity
# ---------------------------------------------------------------------------

class TestSimilarity:
    def test_identical_texts(self) -> None:
        assert DiffEngine._similarity("hello world", "hello world") == 1.0

    def test_empty_strings(self) -> None:
        assert DiffEngine._similarity("", "") == 1.0

    def test_completely_different(self) -> None:
        ratio = DiffEngine._similarity("aaa", "bbb")
        assert ratio == 0.0

    def test_partial_overlap(self) -> None:
        ratio = DiffEngine._similarity("hello world", "hello there")
        assert 0.0 < ratio < 1.0

    def test_one_empty(self) -> None:
        assert DiffEngine._similarity("", "something") == 0.0


# ---------------------------------------------------------------------------
# DiffEngine._unique_sentences
# ---------------------------------------------------------------------------

class TestUniqueSentences:
    def test_disjoint_texts(self) -> None:
        a = "The cat sat on the mat. It was a fine day."
        b = "Dogs love to run in the park. Sunsets are beautiful."
        only_a, only_b, common = DiffEngine._unique_sentences(a, b)
        assert len(common) == 0

    def test_identical_texts(self) -> None:
        text = "Python is great for scripting. It has a clean syntax."
        only_a, only_b, common = DiffEngine._unique_sentences(text, text)
        # All sentences should be common
        assert len(common) > 0
        assert len(only_a) == 0
        assert len(only_b) == 0

    def test_partial_overlap(self) -> None:
        # Sentences need to be >20 chars to survive the filter in _unique_sentences
        a = (
            "Python is a great programming language for scripting. "
            "Use try/except blocks for error handling. "
            "Logging is very important in production code."
        )
        b = (
            "Python is a great programming language for scripting. "
            "Always validate your inputs carefully. "
            "Use type hints for better readability."
        )
        only_a, only_b, common = DiffEngine._unique_sentences(a, b)
        # The first sentence is identical, so it should appear in common
        assert any("Python" in s for s in common)


# ---------------------------------------------------------------------------
# DiffEngine.render — smoke tests (no API calls)
# ---------------------------------------------------------------------------

class TestRender:
    def test_render_two_results(self, null_console: Console) -> None:
        engine = DiffEngine(console=null_console)
        results = [
            _result("gpt-4o", "Python uses try/except blocks for error handling."),
            _result("claude-sonnet-4-6", "Error handling in Python relies on try/except."),
        ]
        # Should not raise
        engine.render("How do you handle errors?", results, temperature=0.7)

    def test_render_no_successful_results(self, null_console: Console) -> None:
        engine = DiffEngine(console=null_console)
        failed = ModelResult(model="gpt-4o", error="API key missing")
        # Should not raise even with zero successful results
        engine.render("A prompt", [failed], temperature=0.7)

    def test_render_single_result(self, null_console: Console) -> None:
        engine = DiffEngine(console=null_console)
        results = [_result("gpt-4o", "Some response text here.")]
        engine.render("A prompt", results, temperature=0.7)

    def test_render_only_diff_flag(self, null_console: Console) -> None:
        engine = DiffEngine(only_diff=True, console=null_console)
        results = [
            _result("gpt-4o", "Line one.\nLine two.\nLine three."),
            _result("claude-sonnet-4-6", "Line one.\nLine TWO changed.\nLine three."),
        ]
        engine.render("prompt", results, temperature=0.0)

    def test_render_word_diff_mode(self, null_console: Console) -> None:
        engine = DiffEngine(diff_mode="words", console=null_console)
        results = [
            _result("gpt-4o", "Use try except blocks"),
            _result("claude-sonnet-4-6", "Use try catch blocks"),
        ]
        engine.render("error handling", results, temperature=0.7)

    def test_render_saves_json(self, null_console: Console) -> None:
        engine = DiffEngine(console=null_console)
        results = [
            _result("gpt-4o", "First model response."),
            _result("claude-sonnet-4-6", "Second model response."),
        ]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            engine.render("prompt", results, temperature=0.7, output_file=path)
            with open(path) as f:
                data = json.load(f)
            assert data["prompt"] == "prompt"
            assert len(data["results"]) == 2
            assert data["results"][0]["model"] == "gpt-4o"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# ModelResult helpers
# ---------------------------------------------------------------------------

class TestModelResult:
    def test_token_count_uses_output_tokens(self) -> None:
        r = ModelResult(model="gpt-4o", text="hello world", output_tokens=42)
        assert r.token_count == 42

    def test_token_count_estimates_from_text(self) -> None:
        r = ModelResult(model="gpt-4o", text="one two three four five")
        # 5 words * 1.3 ≈ 6 or 7
        assert r.token_count >= 6

    def test_display_name(self) -> None:
        r = ModelResult(model="gpt-4o")
        assert r.display_name == "GPT-4O"

    def test_compute_cost_known_model(self) -> None:
        r = ModelResult(
            model="gpt-4o",
            text="hello world",
            input_tokens=1000,
            output_tokens=500,
        )
        r.compute_cost("some prompt")
        assert r.estimated_cost is not None
        assert r.estimated_cost > 0.0

    def test_compute_cost_unknown_model(self) -> None:
        r = ModelResult(model="unknown-model", text="hello", output_tokens=10)
        r.compute_cost("prompt")
        assert r.estimated_cost is None
