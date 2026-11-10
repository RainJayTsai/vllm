# Qwen Reasoning Budget Guard：Phase 0 Source Audit

> 更新：使用者要求以最新版本製作本地 patch 後，已在
> `bbaef29734611db410c9ef6318757767cc68c554` 完成 opt-in implicit-end 修補與
> regression tests。下文保留初次稽核快照；交付現況、測試與限制以
> [實作說明](reasoning-budget-patch.md) 為準。未建立 upstream PR。

## 範圍與結論

稽核日期：2026-11-09。工作區原本沒有部署原始碼；本次另外取得
`https://github.com/vllm-project/vllm.git` 的 shallow checkout：

- SHA：`8581ff066764149b7ae562c38fe58d3d5e1d65bf`
- Commit：`[Transformers backend] Migrate Phi3 (#66559)`
- Commit time：`2026-11-09T16:31:57Z`
- **這不是已確認的部署 baseline**。沒有部署 fork、SHA、模型 revision、啟動命令或 GPU。

Source inspection 確認目前 V2 parser 與 budget kernel 對 implicit end 的
定義不同。這是靜態程式碼證據，尚未取得模型重現結果。

Phase 0 已完成可取得原始碼的稽核；Phase 1–7 尚未實作或驗證。
沒有修改 runtime、增加 feature flag、執行模型測試、建立 Docker image，或發布 PR。

## Repository 規範與重複工作

已讀取根目錄 `AGENTS.md`、`tests/AGENTS.md`。
根目錄規範要求先檢查重複 PR，並規定：

> If an open PR already addresses the same fix, do not open another.

> If work is duplicate/trivial busywork, **do not proceed**.

已執行 `gh pr list --state open --search '44676 in:body'` 與
`gh pr list --state open --search 'thinking budget'`，repo 均為
`vllm-project/vllm`。`gh issue view --comments` 因 GitHub 舊 projectCards
GraphQL 欄位失敗，改用 GitHub REST issues、comments、events 與 pulls。

查到 [PR #44690](https://github.com/vllm-project/vllm/pull/44690) 為 OPEN，
處理相同 implicit-end 問題，只修改舊的
`vllm/v1/sample/thinking_budget_state.py`。PR 說明明確使用固定 token ID
`77093`；不能照搬，亦不能視為符合本計畫的 tokenizer、V2 或 speculative 保證。
本次停止重複 patch，未向 issue 發送訊息。下一步應先取得部署 baseline，
選擇協作既有修復或明確區隔 V2 verification 的非重複範圍。

## Upstream 修復核對

| 項目 | 查詢結果 | 對本次工作的意義 |
| --- | --- | --- |
| [#44676](https://github.com/vllm-project/vllm/issues/44676) | OPEN；原始重現為 vLLM 0.22.0、Qwen3.6-35B-A3B-FP8、Responses streaming，帶自訂 reasoning end phrase | 不是已確認的本部署配置；症狀可由 Chat Completions thinking_token_budget 進入 |
| [#44690](https://github.com/vllm-project/vllm/pull/44690) | OPEN；舊 Holder、固定 token ID | 有重複工作，不能直接移植 |
| [#43757](https://github.com/vllm-project/vllm/pull/43757) | MERGED；merge SHA `cda05ee8c4b39a3e8e8b74444bac11f12277d0a9` | 修的是舊 forced-end re-entry；目前 V2 已無該 Holder，不能據 PR merged 推定 V2 policy 正確 |
| [#45974](https://github.com/vllm-project/vllm/issues/45974) | CLOSED，2026-07-10；closing event 的 commit_id 為 null | issue 關閉不等於本部署含 fix；comments 討論 natural/forced exit 共用 scan_offset reset，未構成本版本實機證據 |
| [#53572](https://github.com/vllm-project/vllm/pull/53572) | OPEN；natural reasoning end 與 budget | 目前原始碼已有獨立 natural-end 欄位，仍需對照部署與該 PR |
| [#61120](https://github.com/vllm-project/vllm/pull/61120) | OPEN；V1 spec decode 自然結束後重複 forcing | 第二個 PR 需先核對，不能從標題推定 V2 覆蓋範圍 |
| [#54467](https://github.com/vllm-project/vllm/pull/54467) | OPEN；V2 forced end 延伸 natural end | 自訂多 token forced sequence 的相關衝突面 |

其餘搜尋結果含 #60077（舊 Holder stale destination）、#58402（forced end
完成後重複 forcing）、#52106（incremental scans）。本次未逐一驗證其 diff。
Shallow checkout 不足以證明歷史 merge 的 ancestry；上述 merged 狀態來自 API。

## 真實程式碼位置與資料流

以下路徑與函式均依本次 SHA，不假設適用其他版本。

| 計畫中的位置／工作 | 本 SHA 的位置與入口 |
| --- | --- |
| `v1/sample/thinking_budget_state.py`、ThinkingBudgetStateHolder | 檔案不存在；改為 `vllm/v1/worker/gpu/sample/thinking_budget.py::ThinkingBudgetState` |
| `v1/sample/sampler.py` | 不存在；`vllm/v1/worker/gpu/sample/sampler.py::Sampler` |
| `v1/sample/metadata.py` | 不存在；V2 使用 `sample/logits_processor/interface.py::LogitsContext`、`input_batch.py::InputBatch` 與 `states.py::RequestState` |
| `reasoning/qwen3_reasoning_parser.py` | 不存在；`reasoning/qwen3_engine_reasoning_parser.py` 匯出 Qwen3ParserReasoningAdapter |
| Reasoning boundary | `vllm/parser/qwen3.py` grammar transitions；`parser/engine/adapters.py::ParserEngineReasoningAdapter` 委派到 engine |
| Tokenizer 與 config | `vllm/config/reasoning.py::ReasoningConfig.initialize_token_ids` |
| Chat budget 傳入 | `entrypoints/openai/chat_completion/protocol.py::ChatCompletionRequest.to_sampling_params` |
| Responses budget 傳入 | `entrypoints/openai/responses/protocol.py::ResponsesRequest.to_sampling_params` |
| Target verification | `v1/worker/gpu/spec_decode/rejection_sampler.py::RejectionSampler._verify`、`__call__` |
| Accepted token 提交 | `v1/worker/gpu/model_runner.py::postprocess_sampled` → `input_batch.py::post_update` → `_post_update_kernel` |
| Chat streaming | `entrypoints/openai/chat_completion/serving.py::OpenAIServingChat.chat_completion_stream_generator` |
| Responses streaming | `entrypoints/openai/responses/streaming_events.py`，含 `emit_simple_tool_call_delta` |
| Responses 最終解析 | `entrypoints/openai/responses/context.py` 呼叫 response_parser.parse |

### 初始化、隔離與清理

`Sampler.__init__` 建立 `ThinkingBudgetState`。
`Sampler.add_request` 呼叫其 `add_request(req_idx, sampling_params)`；
budget buffer 按持久 request slot 索引。啟用 budget 的新請求排入 reset，
`apply_staged_writes` 清除 cached_last_start/end、cached_scan_pos。
沒有 budget 的 slot 設為 -1 並關閉 use_thinking_budget。

`RequestState.add_request` 從 free_indices 取 slot；`remove_request` 釋放 slot。
V2 透過 idx_mapping / expanded_idx_mapping 對應批次順序與持久 slot，
不是沿用舊 Holder 的 move/swap API。BudgetState 沒有獨立 remove 方法；
slot 重用時的 reset 與 disabled→enabled 轉換需要 regression test。

### Budget、force end 與 prompt

`ReasoningConfig` 分開儲存 start、forced end、natural end token IDs。
由 tokenizer.encode(..., add_special_tokens=False) 建立，未硬編碼 ID。
目前只接收 parser 的單一 reasoning_end_str，沒有 implicit end alternatives、
EOS guard、strict 或 force_end/disabled 新 policy。

`ThinkingBudgetState.apply` 呼叫 `apply_thinking_budget`：

1. `_update_committed_marker_cache_kernel` 只掃描 all_token_ids 中已提交的
   `total_len`，更新持久 marker cache；支援多 token marker 與重疊掃描。
2. `_thinking_budget_kernel` 每個 logit row 以 committed cache 加上自己的
   draft prefix 計算暫態 last_start/end，這些暫態值不寫回 cache。
3. 若 latest start 晚於 latest natural end，從 latest start 的結尾算 token
   數；達 budget 時將 forced-end 下一 token 的 logit 寫為 `1.0e9`。
4. 若尾端已有 forced end prefix，繼續下一 token。此機制不同於 request EOS。

`Sampler.apply_sampling_params` 在其他 logits processors 之後執行 budget，
之後仍套用 temperature、min_p、top_k/top_p。需在 greedy 與 seeded sampling
兩條路徑確認完整連續 forcing，不能把靜態 logit 寫入當成整體驗證。

Prompt 會參與 committed marker scan；未關閉 `<think>` 後的 prompt tokens
會算入 budget。不是只掃當前 assistant completion；prompt 中較早訊息的
marker 亦可能影響判斷（另有 #66056）。

### Parser 與 budget 的確認落差

Qwen grammar 中 `(ParserState.REASONING, "TOOL_START")` 轉入 TOOL_PREAMBLE，
同時發出 REASONING_END 和 TOOL_CALL_START。`THINK_END` 則轉入 CONTENT。
Budget kernel 只查 natural_reasoning_end_token_ids，沒有 TOOL_START 檢測。
因此已開始的 tool arguments 仍可能被當作 reasoning，達額度後遭 forcing。

Parser adapter 暴露 reasoning_start_str/end_str 與 boundary 查詢，但
ReasoningConfig 沒有接收所有 end transitions。應擴充既有 metadata，
而不是新增另一套 Qwen parser 或事後修復 JSON。

### Speculative verification

`gather_draft_sampled` 取得各 row 的 draft layout；`RejectionSampler._verify`
先呼叫 sampler.apply_sampling_params，再呼叫 rejection_sample。
Budget 的 `_load_effective_token` 將 local position 0 視為已提交的最後 token，
local positions 1 起為 draft prefix；每一 row 的 effective_len 是
`total_len + local_pos`。這已提供逐位置暫態 boundary 判斷的架構，無須重寫。

`_post_update_kernel` 只將 `range(num_sampled)` 的 accepted/replacement/bonus
輸出寫入 all_token_ids 並增加 total_len；rejected draft suffix 不提交。
不能在暫態 prefix scan 中寫持久狀態。

Implicit end 必須同時加入 committed scan 與每個 verification row 的
effective prefix scan，並且在 budget force 判斷之前完成。
只改下一步的 committed update 無法保護同一 block 後半的 tool arguments。
Bonus row、跨 committed/draft 邊界的多 token marker 亦須覆蓋。

T05 需明確區分「marker 已完成於 prefix」與「當前尚未接受的候選 token」：
前者應優先停止 forcing；後者不能預先提交 boundary。
若 budget 正好耗盡於多 token implicit marker 的中途，還需定義如何保護
合法 marker prefix；單純檢查完整 `<tool_call>` 不足。

### Re-entry 與 EOS

V2 使用 latest start 計算 token 距離，會辨識新 start，但沒有 request-wide
spent-budget 計數；重進 thinking 可取得新的額度。這不等於計畫要求的
strict／累計預算，亦不等於舊 #43757 的 forced-end kill policy。

`sample/logit_bias.py::LogitBiasState` 已處理 min_tokens 的 stop-token mask；
不是 thinking-aware EOS guard。`sampling_params.py::update_from_generation_config`
處理 ignore_eos 及 EOS stop IDs；`v1/core/sched/utils.py::check_stop` 在輸出 token
為 EOS／stop token 或達長度時結束 request。字串 stop 另外走 detokenizer。
本 checkpoint 的 `<|im_end|>` ID／stop-string 身分尚未取得，不可假定。
若增加 guard，須在 target sampling/verification 前套用，保留 max_tokens
及既有 ignore_eos 契約，不能在 request 終止後補 token。

## 現有測試與缺口

主要既有 suite：`tests/v1/worker/test_gpu_thinking_budget.py`。
已閱讀其案例：達額度 forcing、還原被 mask 的 end token、額度前不干預、
多 token forced sequence、natural/forced end 分離、自然結束後不強制、
無 budget 不變、greedy Sampler、latest prefill markers、長輸出 incremental
scan、超大 budget clamp、prompt forced prefix continuation。

Parser suites：`tests/reasoning/test_qwen3_reasoning_parser.py`、
`tests/parser/engine/test_qwen3_reasoning.py`。
這些 parser 測試不能代替 sampling→tool JSON 的端到端證據。

| 計畫案例 | 後續需證明的行為 |
| --- | --- |
| T01/T03/T06/T08/T15/T16 | 延伸現有 kernel suite；真實 tokenizer、跨 decode step 與 flag-off 對照 |
| T02/T04/T05 | committed implicit end、額度相同位置、partial multi-token implicit prefix |
| T07/T09 | EOS guard on/off、ignore_eos、max_tokens、累計 re-entry policy |
| T10/T11 | 真實 LLM/server 的 Chat/Responses streaming 與 non-streaming arguments JSON、delta/final 一致 |
| T12/T13 | 同一 verify block 中 implicit end；接受/拒絕各位置、bonus token、後續 cache 不污染 |
| T14 | persistent slot 重用、batch reorder、移除及 disabled/enabled 切換 |

以上案例都需 greedy 與固定 seed sampling，並包含 patch 關閉對 baseline。
不得用 mock-only 或獨立 reference state machine 宣稱覆蓋真實 kernel。
依 tests/AGENTS.md，user-visible 修復至少需一個真實 LLM/server regression，
並保留 base fail／patch pass 的實際輸出。

CI 後續確認：`.buildkite/test_areas/misc.yaml` 的 v1-executor-worker step
執行 `pytest -v -s v1/worker`，source dependencies 包含 vllm/v1/ 與
tests/v1/worker。API suite 由 `.buildkite/test_areas/entrypoints.yaml` 的
chat_completion step 執行。新案例延伸這兩個既有 suites，無須新增 CI step。

## 實際執行結果與環境限制

- 成功 clone、讀取 source、取得 SHA、查詢 upstream issues/PRs。
- 未找到可用 `nvidia-smi`；預先確認 Python 環境的 torch import 回報
  `ModuleNotFoundError: No module named 'torch'`。
- 未安裝 vLLM／測試依賴，未執行 pytest；沒有任何 pass/fail 模型測試數據。
- 無模型權重、服務 endpoint、實際部署設定或 RTX PRO 6000。
- GPU、CUDA Graph、DFlash2、N-gram、LABD、Chains、API integration、
  streaming、效能測試全部 **NOT RUN**。
- `config/speculative.py` 有 dflash、DFlash2DraftModel 選擇邏輯，以及 ngram/
  ngram_gpu；未找到 LABD/Chains 的對應配置入口。這不證明使用者 fork 不支援。
- 網路在預設 sandbox 連不到繼承 proxy；經工具審核允許的 escalated
  git/curl/gh 成功取得公開 upstream。沒有連線部署機器或發送外部留言。

## 建議的實作順序與交付狀態

1. 取得部署 fork/SHA、model/tokenizer revision、完整啟動參數、容器 digest、
   speculative config 與 backend 來源；在該 baseline 重做差異核對。
2. 區分與 #44690 的協作／非重複範圍；禁止移植固定 token ID。
3. 先加真實入口的 failing regression，再擴充共享 end metadata 與 opt-in flag。
   flag 預設關閉，disabled request 不觸發新增處理；未知模型不可靜默套 Qwen 規則。
4. 第一份 patch 處理 parser/budget implicit boundary 一致性；不得宣稱 spec safe，
   除非同時證明 prefix verification 正確或明確採用可觀測的 target-only fallback。
5. 第二份 patch 完成 verification、bonus/rejection、中途耗盡、slot isolation。
6. EOS/re-entry policy 依需求加入，保持預設不變。再跑全部 correctness tests。
7. 全數 correctness 通過後，才做實機效能比較與 upstream PR description。

本次交付為 audit 文件。最小 runtime patch、feature flag、新 regression tests、
build 驗證、rollback 驗證、benchmark report 與可提交 PR description 均待上述
baseline／重複工作問題解決。未用未執行的測試或空白 benchmark 充當交付完成。

## 後續部署驗證與回滾契約

Docker 應從確認的 baseline 使用其 `docker/Dockerfile`，固定 base image、
CUDA/PyTorch/driver、模型 revision 與 draft revision。尚未確認該版本 SM120
build 參數，不提供假定可用的 build command 或 image tag。

保留現有 image digest 與啟動設定；patch image 必須可由 flag 關閉，並先驗證
flag-off 與原 image 的行為。若需回滾，重新部署原 digest 與原設定；不可只
修改 parser 或用 JSON 後處理掩蓋已被污染的 token stream。

RTX PRO 6000 的 A（baseline）、B（patch target-only）、C（DFlash2）、
D（已確認支援的 LABD/Chains 組合）必須用相同 workload、seed、concurrency、
token limits，先比較 tool JSON validity、boundary accuracy、budget compliance、
streaming parser error，再記錄 TTFT、TPOT、throughput、acceptance rate、VRAM。
所有指標目前無量測值；不能聲稱 SM120、CUDA Graph 或任何 speculative backend
已相容。
