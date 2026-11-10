# Qwen implicit reasoning end：最新版 V2 patch

## 基底與範圍

- Upstream：`https://github.com/vllm-project/vllm`
- Base SHA：`bbaef29734611db410c9ef6318757767cc68c554`
- 本地 branch：`fix/qwen-implicit-budget-v2`
- 2026-11-09 重新 fetch main 後固定此 SHA；不是未指定的「永遠最新」。
- #44690 查詢結果為 OPEN、mergedAt=null。本 patch 未發布 upstream PR。

本 patch 修復 Qwen parser 已接受 `<tool_call>` 為 implicit reasoning end，
但 V2 thinking budget 仍在 tool arguments 中 forcing 的不一致。
除 committed history，也處理同一 speculative verification block 每個位置的
draft prefix；只有已提交的 tokens 更新持久 cache。

這是原計畫中 implicit end 與 budget 一致性的第一份 patch，並包含不可分割的
verification-prefix 修正，並已新增手動設定與多 token implicit markers。
它不宣稱完成 EOS guard、累計 re-entry policy、所有 speculative backend 或實機驗證。
既有多 token explicit end 保持支援；沒有新增英文 transition phrase、
固定 token ID、parser 或 JSON 修復邏輯。

## 修改

| 檔案 | 修改與理由 |
| --- | --- |
| `vllm/config/reasoning.py` | 新增預設 false 的 `enable_implicit_reasoning_end` 與預設空陣列的 `implicit_reasoning_end_strs`；將手動字串經模型 tokenizer 編碼後，與 parser metadata 合併、去重 |
| `vllm/v1/worker/gpu/sample/thinking_budget.py` | 在 committed cold/incremental scan 與每個 verification prefix 掃描 implicit IDs；先判斷 boundary，再考慮 budget forcing |
| `tests/v1/worker/test_gpu_thinking_budget.py` | 21 個參數化 kernel regression cases，含 rejected draft、bonus row、batch reorder、disabled budget，以及多 token implicit marker 跨 decode step／committed-draft 邊界 |
| `tests/entrypoints/openai/chat_completion/test_thinking_token_budget.py` | 新增 4 組真實 completions continuation 測試（stream on/off、temperature 0/0.7、seed 42），以及手動 marker 無 parser、合併去重、停用、空字串拒絕等 config 測試 |
| `docs/features/reasoning_outputs.md` | 記錄 flag、適用範圍與限制 |

完整 natural/implicit end 若已出現在有效 prefix，該 row 不再 forcing。
尚未被 target 接受的當前候選 token 不會提前提交 boundary。
Parser metadata 可供應單 token IDs；手動字串也可編碼為多 token sequences。
只有完整 marker 停止預算，未完成的 prefix 不會暫停 enforcement，以免繞過額度。

## 套用與啟用

在對應版本的乾淨 checkout 套用交付的 patch：

```bash
git switch -c fix/qwen-implicit-budget bbaef29734611db410c9ef6318757767cc68c554
git apply --check /path/to/qwen-implicit-budget-v2.patch
git apply /path/to/qwen-implicit-budget-v2.patch
```

若已套用前一版交付的 patch，改用增量檔
`qwen-implicit-budget-manual-settings.patch`，先 `git apply --check` 再套用。
完整 patch 與增量 patch 二擇一，不要重複套用。

若你的 baseline 不同，先核對 source audit，不能假設可直接套用。
將下列欄位合併進既有 reasoning config，保留部署原有其他設定：

```bash
vllm serve Qwen/Qwen3-0.6B \
  --reasoning-parser qwen3 \
  --reasoning-config '{"enable_implicit_reasoning_end":true,"implicit_reasoning_end_strs":["<tool_call>"]}'
```

實際部署應使用你的固定 checkpoint/revision 與其正確 tool-call parser。
請求透過 `thinking_token_budget` 指定 budget。Flag 不改變 tool format。
未設定 flag 預設 false；未指定 budget 的 request 不啟用 budget forcing。

不需為每個模型改 parser 才能指定 budget boundary。手動 strings 使用
`tokenizer.encode(..., add_special_tokens=False)`，並與 parser metadata 聯集去重。
若完全不設定 reasoning parser，仍須提供原有的 reasoning_start_str 與
reasoning_end_str，才能初始化 budget；serving parser 仍需理解實際工具格式。
空字串或編碼後沒有 token 的 marker 會在啟用時報錯。Flag false 會忽略手動列表。

## 已執行的驗證

沒有可用 GPU，因此以獨立 runner 執行 production Triton kernel 本體：
runner 僅透過 AST 載入現有函式，避開 vLLM CUDA extension 與重量級 conftest，
並載入新增 kernel tests，沒有替換 kernel 演算法。

環境：Python 3.12、torch 2.15.0+cpu、Triton 3.9.0、pytest 9.2.0。
runner 與完整輸出隨 artifacts 一起交付。

```bash
TRITON_INTERPRET=1 BUDGET_BASE_REVISION=bbaef29734611db410c9ef6318757767cc68c554 \
  .venv/bin/python -m pytest --confcutdir=/path/to/artifacts \
  /path/to/artifacts/test_budget_interpreter.py -q
# 15 failed, 6 passed

TRITON_INTERPRET=1 .venv/bin/python -m pytest \
  --confcutdir=/path/to/artifacts /path/to/artifacts/test_budget_interpreter.py -q
# 21 passed

TRITON_CACHE_DIR=/tmp/triton-cache \
  .venv/bin/python /path/to/artifacts/compile_budget_sm120.py
# 24 combinations compiled to SM120 cubin
```

若 checkout 不在 `/workspace/vllm`，設定 `VLLM_SOURCE_ROOT` 指向它。
Baseline runner 只移除舊 API 不接受的新增 metadata 參數，其 kernel 原封不動。
失敗來自錯誤的 logit forcing／boundary cache，而非缺少參數的 TypeError。

SM120 離線編譯覆蓋兩個 kernels × implicit marker 長度組合
`()`、`(1,)`、`(1,1)`、`(2,)`、`(1,3)`、`(3,2)` × natural end 長度 1/2；
這不是 RTX PRO 6000 上的執行或 CUDA Graph 證據。

Ruff check、format 與 `git diff --check` 通過。
亦已將 5 個修改檔案從固定 base 匯出到乾淨目錄，確認交付 patch 的
`git apply --check`、實際套用，以及 `git apply -R --check` 均成功；
4 個修改的 Python 檔案通過 compileall。
正常 GPU pytest 啟動嘗試因 tests/conftest.py 缺少 `tblib` 而在 collection
前失敗；環境同時沒有完整 vLLM serving/test dependencies、GPU 或模型權重。

## 尚需執行的驗證

在依 repository 開發流程安裝的 GPU 環境執行：

```bash
.venv/bin/python -m pytest tests/v1/worker/test_gpu_thinking_budget.py -v
.venv/bin/python -m pytest \
  tests/entrypoints/openai/chat_completion/test_thinking_token_budget.py -v
```

新增 API test 用真實 Qwen3-0.6B 權重，從工具參數內部的 prompt continuation
開始，透過 logit_bias 產生指定 token，確認小 budget 不插入 `</think>`。
這使 regression 可重現，避免依賴小模型是否主動呼叫工具；但它不是完整
Chat/Responses function-call JSON 端到端測試，後者仍需使用部署模型驗證。

既有 CI worker 與 chat_completion steps 會選取這兩個檔案。本次未跑遠端 CI。

| 實機驗證 | 狀態 |
| --- | --- |
| RTX PRO 6000 SM120 執行 | NOT RUN |
| CUDA Graph capture/replay | NOT RUN |
| DFlash2 / N-gram verification、接受率 | NOT RUN；只有共同 budget kernel 路徑測試 |
| LABD / Chains | NOT RUN；需部署 fork/backend 資料 |
| Chat/Responses function-call JSON、stream/final 一致性 | NOT RUN |
| EOS / strict re-entry policy | 未納入此 patch |
| TTFT、TPOT、throughput、VRAM、JSON valid rate、budget compliance rate | 無實機數據，未作效能結論 |

## Docker 與回滾

在固定 SHA、套用 patch 後，以該版既有 Dockerfile 建立 image：

```bash
docker build -f docker/Dockerfile --target vllm-openai \
  -t vllm:qwen-implicit-bbaef297 .
```

該版 Dockerfile 的預設 torch_cuda_arch_list 已含 `12.0`。
本次未執行 Docker build；仍需驗證 image、driver 與部署的 SM120 runtime。
不要在 correctness 尚未通過時切換效能設定。

回滾可先將新 flag 改為 false 並重啟服務；若需移除 patch，在無額外修改的
patched checkout 使用 `git apply -R --check` 再 `git apply -R`。
容器部署保留原 image digest 與完整啟動參數，以原 digest 重建原服務。
本次沒有修改模型權重或 tokenizer vocabulary。

## Upstream PR description 草稿（尚未發布）

Title: [Bugfix][Model Runner V2] Honor parser implicit reasoning ends in thinking budgets

Qwen can enter a tool call without emitting the explicit reasoning end marker.
Model Runner V2 currently continues counting tool arguments as reasoning and
can force an end sequence into those arguments. Add an opt-in config that
merges the parser's existing implicit-end IDs with user-configured strings
encoded by the model tokenizer. Match complete single- or multi-token markers
in committed history and per-row speculative prefixes. Draft-prefix transitions
remain local to verification rows; rejected drafts never enter the cache.

Unlike open PR #44690, this change targets the current V2 Triton implementation,
uses tokenizer-derived parser metadata instead of a fixed token ID, and covers
the remainder of the same verification block. Coordinate with that PR before
submission; this local patch does not open a competing PR.

Validation: production-kernel CPU interpreter regressions fail on the base
(15 failed, 6 passed) and pass with this patch (21 passed); 24 SM120 offline
kernel configurations compile. Ruff and whitespace checks pass. GPU execution,
real server regressions and model evaluations remain pending; no serving or
performance improvement is claimed from these checks alone.

AI assistance was used to implement and inspect this patch. Human line-by-line
review and relevant GPU/model tests are required before upstream submission.
