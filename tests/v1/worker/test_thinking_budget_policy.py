# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project

import importlib
from dataclasses import FrozenInstanceError

import pytest

from vllm.plugins.thinking_budget_policies import (
    BoundaryRules,
    DefaultPolicy,
    QwenPolicy,
    get_policy,
    register_policy,
)


def test_default_policy_remains_native():
    assert isinstance(get_policy("default"), DefaultPolicy)
    assert BoundaryRules().implicit_end_strs == ()
    with pytest.raises(FrozenInstanceError):
        BoundaryRules().guard_prefix = True  # type: ignore[misc]


def test_register_policy_preserves_builtins():
    register_policy("test_native_boundary_policy", DefaultPolicy)
    assert isinstance(get_policy("test_native_boundary_policy"), DefaultPolicy)
    with pytest.raises(ValueError, match="already registered"):
        register_policy("default", QwenPolicy)


def test_policy_entry_point_loading_and_allowlist(tmp_path, monkeypatch):
    """Use real importlib entry-point discovery, without replacing the loader."""
    info = tmp_path / "budget_example-0.0.1.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: budget-example\nVersion: 0.0.1\n")
    (info / "entry_points.txt").write_text(
        "[vllm.thinking_budget_policies]\n"
        "test_external = vllm.plugins.thinking_budget_policies:DefaultPolicy\n"
        "test_invalid = builtins:object\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    monkeypatch.setenv("VLLM_PLUGINS", "test_external,test_invalid")
    assert isinstance(get_policy("test_external"), DefaultPolicy)
    with pytest.raises(TypeError, match="boundaries"):
        get_policy("test_invalid")
    monkeypatch.setenv("VLLM_PLUGINS", "")
    with pytest.raises(ValueError, match="VLLM_PLUGINS"):
        get_policy("test_external")


def test_unknown_policy_is_actionable():
    with pytest.raises(ValueError, match="Unknown thinking budget policy"):
        get_policy("missing_thinking_budget_policy")


def test_qwen_policy_uses_model_template():
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-0.6B")
    rules = get_policy("qwen").boundaries(tokenizer)
    assert rules == BoundaryRules(("<tool_call>",), guard_prefix=True)
    assert tokenizer.encode(rules.implicit_end_strs[0], add_special_tokens=False)
    tokenizer.chat_template = "{{ messages }}"
    with pytest.raises(ValueError, match="chat template"):
        get_policy("qwen").boundaries(tokenizer)
