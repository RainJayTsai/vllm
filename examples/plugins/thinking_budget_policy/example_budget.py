# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
from vllm.plugins.thinking_budget_policies import BoundaryRules


class ExamplePolicy:
    def boundaries(self, tokenizer):
        # Replace this marker with the format used by your model's template.
        return BoundaryRules(("<tool_call>",), guard_prefix=True)
