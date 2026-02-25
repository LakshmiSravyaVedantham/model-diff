"""Tests for the model runner and provider utilities."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from model_diff.models import (
    ALL_SUPPORTED_MODELS,
    ANTHROPIC_MODELS,
    DEFAULT_MODELS,
    OPENAI_MODELS,
    ModelResult,
    ModelRunner,
    _call_anthropic,
    _call_openai,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_default_models_are_supported(self) -> None:
        for m in DEFAULT_MODELS:
            assert m in ALL_SUPPORTED_MODELS

    def test_openai_and_anthropic_disjoint(self) -> None:
        assert OPENAI_MODELS.isdisjoint(ANTHROPIC_MODELS)

    def test_all_supported_is_union(self) -> None:
        assert ALL_SUPPORTED_MODELS == OPENAI_MODELS | ANTHROPIC_MODELS


# ---------------------------------------------------------------------------
# ModelRunner.validate_models
# ---------------------------------------------------------------------------

class TestValidateModels:
    def test_all_valid(self) -> None:
        valid, warnings = ModelRunner.validate_models(["gpt-4o", "claude-sonnet-4-6"])
        assert valid == ["gpt-4o", "claude-sonnet-4-6"]
        assert warnings == []

    def test_unknown_model(self) -> None:
        valid, warnings = ModelRunner.validate_models(["gpt-4o", "gpt-5-fake"])
        assert valid == ["gpt-4o"]
        assert len(warnings) == 1
        assert "gpt-5-fake" in warnings[0]

    def test_all_unknown(self) -> None:
        valid, warnings = ModelRunner.validate_models(["bad-model"])
        assert valid == []
        assert len(warnings) == 1

    def test_empty_list(self) -> None:
        valid, warnings = ModelRunner.validate_models([])
        assert valid == []
        assert warnings == []


# ---------------------------------------------------------------------------
# ModelRunner._get_caller
# ---------------------------------------------------------------------------

class TestGetCaller:
    def test_openai_model_routes_correctly(self) -> None:
        from model_diff.models import _call_openai
        assert ModelRunner._get_caller("gpt-4o") is _call_openai

    def test_anthropic_model_routes_correctly(self) -> None:
        from model_diff.models import _call_anthropic
        assert ModelRunner._get_caller("claude-sonnet-4-6") is _call_anthropic

    def test_unknown_model_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown model"):
            ModelRunner._get_caller("nonexistent-model")


# ---------------------------------------------------------------------------
# _call_openai — unit tests with mocked client
# ---------------------------------------------------------------------------

class TestCallOpenAI:
    def test_missing_api_key(self) -> None:
        result = ModelResult(model="gpt-4o")
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            _call_openai("gpt-4o", "hello", 0.7, result)
        assert result.error is not None
        assert "OPENAI_API_KEY" in result.error

    def test_successful_call(self) -> None:
        result = ModelResult(model="gpt-4o")

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "This is the response."
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            with patch("openai.OpenAI", return_value=mock_client):
                _call_openai("gpt-4o", "What is Python?", 0.7, result)

        assert result.error is None
        assert result.text == "This is the response."
        assert result.input_tokens == 10
        assert result.output_tokens == 20
        assert result.elapsed >= 0.0

    def test_auth_error(self) -> None:
        import openai

        result = ModelResult(model="gpt-4o")
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.AuthenticationError(
            "bad key", response=MagicMock(), body={}
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-bad"}):
            with patch("openai.OpenAI", return_value=mock_client):
                _call_openai("gpt-4o", "prompt", 0.7, result)

        assert result.error is not None
        assert "authentication" in result.error.lower()


# ---------------------------------------------------------------------------
# _call_anthropic — unit tests with mocked client
# ---------------------------------------------------------------------------

class TestCallAnthropic:
    def test_missing_api_key(self) -> None:
        result = ModelResult(model="claude-sonnet-4-6")
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            _call_anthropic("claude-sonnet-4-6", "hello", 0.7, result)
        assert result.error is not None
        assert "ANTHROPIC_API_KEY" in result.error

    def test_successful_call(self) -> None:
        result = ModelResult(model="claude-sonnet-4-6")

        mock_block = MagicMock()
        mock_block.text = "Claude's answer."

        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.usage.input_tokens = 15
        mock_response.usage.output_tokens = 25

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}):
            with patch("anthropic.Anthropic", return_value=mock_client):
                _call_anthropic("claude-sonnet-4-6", "What is Python?", 0.7, result)

        assert result.error is None
        assert result.text == "Claude's answer."
        assert result.input_tokens == 15
        assert result.output_tokens == 25

    def test_auth_error(self) -> None:
        import anthropic

        result = ModelResult(model="claude-sonnet-4-6")
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.AuthenticationError(
            message="bad key", response=MagicMock(), body={}
        )

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-bad"}):
            with patch("anthropic.Anthropic", return_value=mock_client):
                _call_anthropic("claude-sonnet-4-6", "prompt", 0.7, result)

        assert result.error is not None
        assert "authentication" in result.error.lower()


# ---------------------------------------------------------------------------
# ModelRunner.run — concurrent execution
# ---------------------------------------------------------------------------

class TestModelRunnerRun:
    def test_run_returns_results_in_order(self) -> None:
        models = ["gpt-4o", "claude-sonnet-4-6"]
        runner = ModelRunner(models=models, temperature=0.0)

        def fake_openai(model, prompt, temperature, result):
            result.text = "openai response"

        def fake_anthropic(model, prompt, temperature, result):
            result.text = "anthropic response"

        with patch("model_diff.models._call_openai", side_effect=fake_openai):
            with patch("model_diff.models._call_anthropic", side_effect=fake_anthropic):
                results = runner.run("test prompt")

        assert len(results) == 2
        assert results[0].model == "gpt-4o"
        assert results[1].model == "claude-sonnet-4-6"
        assert results[0].text == "openai response"
        assert results[1].text == "anthropic response"

    def test_run_handles_partial_failure(self) -> None:
        """One model fails; the other should still succeed."""
        models = ["gpt-4o", "claude-sonnet-4-6"]
        runner = ModelRunner(models=models)

        def fake_openai(model, prompt, temperature, result):
            result.error = "Simulated failure"

        def fake_anthropic(model, prompt, temperature, result):
            result.text = "Good response"

        with patch("model_diff.models._call_openai", side_effect=fake_openai):
            with patch("model_diff.models._call_anthropic", side_effect=fake_anthropic):
                results = runner.run("prompt")

        assert results[0].error == "Simulated failure"
        assert results[1].text == "Good response"
        assert results[1].error is None

    def test_cost_computed_for_successful_results(self) -> None:
        models = ["gpt-4o"]
        runner = ModelRunner(models=models)

        def fake_openai(model, prompt, temperature, result):
            result.text = "response text here"
            result.input_tokens = 100
            result.output_tokens = 50

        with patch("model_diff.models._call_openai", side_effect=fake_openai):
            results = runner.run("prompt")

        assert results[0].estimated_cost is not None
        assert results[0].estimated_cost > 0
