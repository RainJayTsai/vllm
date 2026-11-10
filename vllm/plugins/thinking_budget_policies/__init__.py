# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
"""Compile model boundary policies once, outside the sampling hot path.

Policies are immutable descriptions; request state belongs to the native budget
controller. They must not observe draft candidates or keep per-request state.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from vllm.tokenizers import TokenizerLike

POLICIES_GROUP = "vllm.thinking_budget_policies"


@dataclass(frozen=True)
class BoundaryRules:
    """Additional boundaries consumed by the native force-end controller.

    Complete implicit ends close the current segment. A guarded partial end
    may delay forcing only within the bounded budget-crossing window. Explicit
    starts, natural ends and forced-end completion retain native semantics.
    """

    implicit_end_strs: tuple[str, ...] = ()
    guard_prefix: bool = False


class ThinkingBudgetPolicy(Protocol):
    """Initialization-time policy compiled into incremental token-ID matching.

    This declarative contract deliberately excludes per-token Python callbacks.
    Accepted history and ephemeral verification prefixes are handled separately
    by the runner. Future stateful policies require a separate runner contract.
    """

    def boundaries(self, tokenizer: "TokenizerLike") -> BoundaryRules: ...


class DefaultPolicy:
    def boundaries(self, tokenizer: "TokenizerLike") -> BoundaryRules:
        return BoundaryRules()


class QwenPolicy:
    def boundaries(self, tokenizer: "TokenizerLike") -> BoundaryRules:
        template = getattr(tokenizer, "chat_template", None)
        templates = template.values() if isinstance(template, dict) else [template]
        if not any("<tool_call>" in (value or "") for value in templates):
            raise ValueError(
                "The qwen thinking budget policy requires a chat template with "
                "<tool_call>. Use default with implicit_reasoning_end_strs for "
                "other tool formats."
            )
        return BoundaryRules(("<tool_call>",), guard_prefix=True)


_POLICY_FACTORIES: dict[str, Callable[[], ThinkingBudgetPolicy]] = {
    "default": DefaultPolicy,
    "qwen": QwenPolicy,
}


def register_policy(name: str, policy: Callable[[], ThinkingBudgetPolicy]) -> None:
    """Register a process-local policy factory without replacing built-ins."""
    if not name or name in _POLICY_FACTORIES:
        raise ValueError(
            f"Thinking budget policy already registered or empty: {name!r}"
        )
    _POLICY_FACTORIES[name] = policy


def get_policy(name: str) -> ThinkingBudgetPolicy:
    """Resolve built-ins first, then the dedicated vLLM plugin group."""
    factory = _POLICY_FACTORIES.get(name)
    if factory is None:
        from vllm.plugins import load_plugins_by_group

        factories = load_plugins_by_group(POLICIES_GROUP)
        factory = factories.get(name)
        if factory is None:
            available = sorted(set(_POLICY_FACTORIES) | set(factories))
            raise ValueError(
                f"Unknown thinking budget policy {name!r}. Available: {available}. "
                f"Install an entry point in {POLICIES_GROUP} and check VLLM_PLUGINS."
            )
    policy = factory()
    if not callable(getattr(policy, "boundaries", None)):
        raise TypeError(f"Thinking budget policy {name!r} must implement boundaries()")
    return policy
