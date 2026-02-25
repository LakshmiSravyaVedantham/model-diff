"""model-diff: Compare LLM model outputs side-by-side with rich diff visualization."""

__version__ = "0.1.0"
__all__ = ["ModelRunner", "DiffEngine", "ModelResult"]

from model_diff.models import ModelResult, ModelRunner
from model_diff.differ import DiffEngine
