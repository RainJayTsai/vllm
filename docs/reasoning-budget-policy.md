# Thinking Budget Policy

## Repository assessment

Work continues from `RainJayTsai/vllm`, branch `fix/qwen-implicit-budget-v2`,
commit `60010f7dd`, based on upstream `bbaef2973`. This source checkout has no
built version metadata (`vllm.version` reports `dev`); these SHAs identify it.
The previous patch already matches complete implicit ends in committed history
and speculative prefixes. Its remaining bug is forcing an end sequence while
an incomplete multi-token tool opener crosses the budget.

The checked-out worker uses `vllm/v1/worker/gpu/model_runner.py`. There is no
separate legacy V1 sampler/ThinkingBudgetStateHolder to adapt in this revision.
The CPU runner has a separate sampler and is not covered by this extension;
it rejects non-default policies and the legacy implicit-end option explicitly.
Native default CPU budgets are unchanged.

| Lifecycle | Actual source and call site |
| --- | --- |
| Initialize markers | `vllm/config/reasoning.py`, `ReasoningConfig.initialize_token_ids` |
| Initialize request | `gpu/states.py`, `RequestState.add_request`; `gpu/sample/sampler.py`, `Sampler.add_request` |
| Reset budget slot | `gpu/sample/thinking_budget.py`, `ThinkingBudgetState.add_request` and `apply_staged_writes` |
| Finish, abort, preempt | `gpu/model_runner.py`, `finish_requests` and `_remove_request`; `RequestState.remove_request` frees the slot |
| Update committed boundary | `gpu/sample/thinking_budget.py`, `_update_committed_marker_cache_kernel` |
| Exhaustion and forced completion | Same file, `_thinking_budget_kernel` |
| Modify logits | `Sampler.apply_sampling_params`: native/custom processors, budget, temperature, min-p, top-k/top-p |
| Verify drafts | `gpu/spec_decode/rejection_sampler.py`, `RejectionSampler._verify` |
| Commit accepted/replacement/bonus tokens | `GPUModelRunner.postprocess_sampled` → `gpu/input_batch.py`, `post_update` / `_post_update_kernel` |
| DFlash2 | `gpu/spec_decode/dflash2/speculator.py`, shared target sampler and commit path |

Paths prefixed with `gpu/` are under `vllm/v1/worker/`.
Qwen's parser grammar (`vllm/parser/qwen3.py`) transitions from reasoning into
tool preamble on TOOL_START and emits REASONING_END. Parser adapters expose
implicit-end metadata. The live parser is not consulted by sampling.
Inspection of the actual Qwen/Qwen3-0.6B tokenizer/chat template confirms
`<tool_call>` is present; its encoding in that checkpoint is one token. No ID
is hardcoded. Other tokenizations are covered by multi-token kernel tests.

Existing extension conventions include parser registries, class-path KV
connector factories, general plugins and dedicated plugin groups loaded by
`vllm.plugins.load_plugins_by_group`. The new group uses this same loader and
its `VLLM_PLUGINS` filtering, rather than repurposing general plugins.

## Contract and ownership

`vllm.plugins.thinking_budget_policies.ThinkingBudgetPolicy` provides
`boundaries(tokenizer) -> BoundaryRules`. It runs once during configuration
initialization. The immutable result describes implicit-end strings and whether
to guard incomplete prefixes. The existing controller owns explicit starts,
natural ends, budget exhaustion, forced-end completion and per-request caches.
The registry supports `register_policy(name, factory)` and dedicated entry points;
built-ins cannot be overwritten. Unknown names and invalid factories raise errors.

This declarative interface adapts the proposed accepted-token callback contract
to the repository's GPU token matcher. It does not offer arbitrary per-token
Python actions. Policies cannot retain mutable request state; they cannot read
draft candidates. A future stateful policy, such as loop detection, will need
an additional runner contract rather than hiding state in this factory.
No loop detection is implemented.

DefaultPolicy adds no boundaries or prefix guard and preserves the original
branch's opt-in implicit-marker configuration. QwenPolicy checks the actual
chat template and adds `<tool_call>` plus the prefix guard. Configured manual
strings and parser metadata are merged and deduplicated, then encoded with
`add_special_tokens=False`. Native start/end configuration remains unchanged.

A complete implicit end closes the current segment before budget enforcement.
A later explicit start opens another segment with native per-segment accounting.
The guard permits an incomplete marker that began before exhaustion to finish.
A false positive gets at most `max_marker_length - 1` extra tokens after the
budget. Repeated prefixes cannot reset this deadline because their absolute
start must precede exhaustion. A mismatch resumes enforcement on the next row.
A partially forced end sequence takes precedence over prefix grace.
At budget zero, a tool opener that has not begun receives no grace.

Only committed `all_token_ids[:total_len]` updates persistent caches. Each
verification row additionally considers its own effective draft prefix without
storing it. `post_update` commits only `num_sampled` tokens, including replacement
and bonus tokens. Rejected suffixes never enter boundary caches. Request removal
needs no policy callback: state lives in fixed slot arrays; `add_request` resets
all caches before an enabled slot is reused. Disabled requests use budget -1.

No per-token decoding, Python callback, extra device synchronization or request
lock is introduced. Prefix matching is bounded by configured marker lengths;
the extra guard is eliminated by specialization when disabled. Runtime GPU
overhead has not been measured.

## Configuration and plugin example

```bash
vllm serve Qwen/Qwen3-0.6B --reasoning-parser qwen3 \
  --reasoning-config '{"thinking_budget_policy":"qwen"}'
```

Requests continue to use `thinking_token_budget`. The native forced phrase is
still configured by `reasoning_end_str`; natural ends retain parser semantics.
Token-ID properties are derived internally, not new public configuration fields.

A minimal installable example lives in `examples/plugins/thinking_budget_policy`:

```toml
[project.entry-points."vllm.thinking_budget_policies"]
example = "example_budget:ExamplePolicy"
```

Its no-argument factory returns an object implementing `boundaries`. Install it
in the serving environment and select `thinking_budget_policy: "example"`.
If `VLLM_PLUGINS` is set, include `example`. Selection is server-wide; request
budgets and mutable boundary state remain isolated. Plugins must use the same
installed environment as configuration initialization.

## Validation and limitations

The new crossing regression was executed against the unchanged production
kernel using Triton's CPU interpreter: **2 failed, 3 passed**. The compatibility
wrapper omitted the new argument on the pre-fix function; failures were wrong
logits, not signature errors. After the fix, **32 production-kernel cases passed**,
including actual `post_update` commitment with full acceptance/bonus and partial
acceptance/replacement. The standalone interpreter harness extracts production
functions by AST; it does not replace their algorithms and does not exercise
GPU scheduling or rejection probability calculations.

Five policy tests passed with real entry-point discovery and a real Qwen
tokenizer/template. The installable example was also installed into the virtual
environment and successfully loaded through its actual entry point. Sixteen
additional default-policy comparisons against the original branch kernel passed
with exact logits and cache equality. Twenty SM120 offline compilation calls
passed across both kernels, empty/single/multi-token markers and guard variants;
these are compile checks, not GPU execution.

Ruff check/format, compileall and whitespace checks pass. Focused mypy checks
pass for six changed Python files (imports skipped). The broader check reports
six CPU sampler errors; the original CPU sampler produces the same six errors.
Those unrelated annotations were left unchanged. Before publishing the branch,
the repository's changed-file mypy hook and all applicable pre-commit checks
passed after fixing the tokenizer attribute access, config field docstrings
and Markdown table alignment. The unrelated GitHub Actions actionlint hook was
skipped because its Go toolchain could not initialize; no Actions files changed.
Full-repository type checking remains unverified.

Normal GPU suite startup was attempted and failed during
conftest import (`ModuleNotFoundError: zmq`); this environment has no GPU,
CUDA runtime, installed vLLM extensions or model weights. No GPU suite pass,
DFlash2 end-to-end pass, model evaluation or throughput result is claimed.

Added GPU tests cover cancellation/slot reuse with real RequestState and
ReasoningConfig objects. Added real server regressions cover streaming and
non-streaming tool argument continuation and completed JSON. These tests are
**not run here**. The JSON test uses raw completions to deterministically resume
an existing tool call; full Chat/Responses tool-parser lifecycle validation
remains necessary. Existing CI worker and chat-completion test steps select
the suites; the worker dependencies now include the policy package.

Reproduction commands from the repository virtual environment:

```bash
.venv/bin/python -m pytest tests/v1/worker/test_thinking_budget_policy.py -v
.venv/bin/python -m pytest tests/v1/worker/test_gpu_thinking_budget.py -v
.venv/bin/python -m pytest tests/entrypoints/openai/chat_completion/test_thinking_token_budget.py -v
```

GPU validation must additionally exercise DFlash2 with continuous request
addition/removal, all/partial/no acceptance, marker splits and bonus tokens.
Benchmark native/default/Qwen using identical weights, prompts, concurrency and
speculation settings after correctness passes. No benchmark number is available.

## Suggested upstream split

1. Coordinate the existing V2 implicit-end fix with related upstream fixes;
   include its tokenizer metadata, committed/prefix matching and regression tests.
2. Add the bounded-prefix correction with fail-before/pass-after kernel evidence
   and real server JSON regression results.
3. Add the declarative policy registry, Qwen policy, dedicated entry points,
   example, configuration docs and explicit unsupported-backend validation.
4. Supply GPU/DFlash2 lifecycle, model-output and performance evidence before
   claiming production compatibility. No upstream PR was opened by this work.
