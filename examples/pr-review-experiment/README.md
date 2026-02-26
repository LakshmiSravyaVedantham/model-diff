# PR Review Experiment

This directory contains the full artifact set from a real experiment: running
GPT-4 and Claude as mutual PR reviewers on the same piece of Python code, then
using `model-diff` to analyze where and how their feedback systematically diverged.

Full write-up: [I Put GPT-4 and Claude in the Same Repo and Made Them Review Each Other's PRs. It Got Weird.](https://dev.to/lakshmisravyavedantham/i-put-gpt-4-and-claude-in-the-same-repo-and-made-them-review-each-others-prs-it-got-weird-148e)

---

## What Was Tested

A single Python utility function — `retry_with_backoff.py` — was submitted as a
mock PR. Both models received identical context: the code, a brief description of
the project (a production Python service), and a standard code review prompt.

Each model then reviewed the *other model's* review, and was allowed one rebuttal
round.

Four review artifacts were captured:

| File | Description |
|------|-------------|
| `reviews/claude_round1.md` | Claude's initial review of the code |
| `reviews/gpt4_round1.md` | GPT-4's initial review of the code |
| `reviews/claude_round2.md` | Claude's response to GPT-4's suggestions |
| `reviews/gpt4_round2.md` | GPT-4's rebuttal to Claude's response |

---

## Setup

```bash
pip install model-diff

export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
```

To reproduce the diff between round 1 reviews:

```bash
model-diff \
  "Review this Python retry utility for correctness, style, and production-readiness." \
  --prompt-file retry_with_backoff.py \
  --models gpt-4o,claude-sonnet-4-6 \
  --temperature 0.0 \
  --output round1_diff.json
```

---

## Key Findings

### GPT-4 trends toward abstraction

In both rounds, GPT-4 pushed toward formalizing the API surface: a `RetryConfig`
dataclass, callback hooks, a decorator variant. Each suggestion was individually
reasonable. Taken together, they reflect a consistent prior: *prefer explicit
configuration objects and composable interfaces, even before the need is concrete.*

This is the "design for the library" instinct. It's the right call when code will
be shared across teams or published as a package. It's overengineering when the
code is an application-level utility.

### Claude trends toward YAGNI

Claude's round 2 response explicitly invoked YAGNI and was specific about *why*
each suggestion added indirection without present benefit. The mutable default
argument footgun callout for `RetryConfig` was technically precise. The defense of
`logging` over callbacks was grounded in how the existing observability stack
actually works.

This is the "respect the current context" instinct. It's the right call when you
know the scope. It becomes technical debt when scope assumptions turn out to be
wrong.

### They converged on one concrete improvement

Both models agreed — after prompting — that the decorator variant was worth
adding. GPT-4 introduced `max_jitter_factor` in round 2 as a correctness-adjacent
suggestion; Claude did not rebut it, which amounts to implicit acceptance.

### `model-diff` output on round 1 reviews

Running `model-diff` on the two round-1 reviews with `--diff words` made the
structural difference immediately visible: GPT-4's review was ~40% longer,
introduced three new nouns (`RetryConfig`, `on_retry`, `decorator`) that Claude
never used, and spent more tokens on proposed additions. Claude's review spent
more tokens defending existing decisions.

The diff wasn't just stylistic. It was a window into different design philosophies
encoded in the weights.

---

## Files

```
examples/pr-review-experiment/
├── README.md                    # This file
├── retry_with_backoff.py        # The function under review
└── reviews/
    ├── claude_round1.md         # Claude's initial review
    ├── gpt4_round1.md           # GPT-4's initial review
    ├── claude_round2.md         # Claude's rebuttal to GPT-4
    └── gpt4_round2.md           # GPT-4's rebuttal to Claude
```
