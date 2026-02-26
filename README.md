# model-diff

Compare LLM model outputs side-by-side with rich diff visualization.

Run the same prompt on multiple models simultaneously and see exactly what each model says differently.

## Installation

```bash
pip install model-diff
```

Or install from source:

```bash
git clone https://github.com/yourname/model-diff
cd model-diff
pip install -e .
```

## Requirements

Set the API keys for the providers you want to use:

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
```

Missing keys are handled gracefully — models without a key are skipped with a warning.

## Usage

```bash
# Default: compare GPT-4o vs Claude Sonnet
model-diff "What is the best way to handle errors in Python?"

# Specify models explicitly
model-diff "Explain recursion" --models gpt-4o,claude-sonnet-4-6

# Use a prompt file
model-diff --prompt prompt.txt --models gpt-4o,claude-haiku-4-5-20251001,claude-sonnet-4-6

# Word-level diff
model-diff "Explain recursion" --diff words

# Show only differences (hide matching sections)
model-diff "Explain recursion" --only-diff

# Deterministic outputs
model-diff "Explain recursion" --temperature 0.0

# Save results to JSON
model-diff "Explain recursion" --output results.json
```

## Supported Models

| Model ID | Provider | API Key |
|---|---|---|
| `gpt-4o` | OpenAI | `OPENAI_API_KEY` |
| `gpt-4o-mini` | OpenAI | `OPENAI_API_KEY` |
| `claude-opus-4-6` | Anthropic | `ANTHROPIC_API_KEY` |
| `claude-sonnet-4-6` | Anthropic | `ANTHROPIC_API_KEY` |
| `claude-haiku-4-5-20251001` | Anthropic | `ANTHROPIC_API_KEY` |

## Architecture

```
src/model_diff/
├── cli.py      # Click-based CLI entry point
├── models.py   # Provider-specific API callers, run concurrently via threading
└── differ.py   # difflib-based diff engine + Rich output formatter
```

Model calls are issued concurrently using `threading`, so wall time equals the slowest model rather than the sum of all models.

## Real-World Example: PR Review Experiment

See [examples/pr-review-experiment/](examples/pr-review-experiment/) for a full transcript of GPT-4 and Claude reviewing each other's code — with model-diff output showing where they systematically diverge.

Read the full story: [I Put GPT-4 and Claude in the Same Repo and Made Them Review Each Other's PRs. It Got Weird.](https://dev.to/lakshmisravyavedantham/i-put-gpt-4-and-claude-in-the-same-repo-and-made-them-review-each-others-prs-it-got-weird-148e)

## License

MIT
