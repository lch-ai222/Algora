# PROJECT_STATE.md

Algora（CodeAgent Eval Lab）当前状态快照。这是**活文档**，每完成一个里程碑或有重要验证结果时更新。规则见 [`AGENTS.md`](AGENTS.md)，任务见 [`TASKS.md`](TASKS.md)。

最后更新：2026-07-11。

## 1. 当前总体状态

闭环已跑通并用真实 LLM（DeepSeek v4-flash）验证。**7/7 里程碑全部完成**：M0、M1、M2、M4、M3、M5、C（+ 长期文档）。

最低成功线（M1+M2+M4）+ 可演示控制台（M3）+ 可归因的 V1→V2 结果（M4）+ 公开 benchmark & judge meta-eval（M5）+ SWE-bench 兼容适配器（C）全部就绪。

- 测试：**70 passed, 1 skipped**（skip 是 `RUN_LLM_SMOKE` 门控的真实 LLM 冒烟）。
- Lint：`ruff` 全绿（src/tests/scripts/backend）。
- benchmark 自检：`scripts/selfcheck.py` **9/9 valid**；HumanEval canonical 自检 **10/10**。
- 前端：TypeScript 干净，`npm run build` 干净（48.75 kB gzip），浏览器实测无 console 报错。

## 2. 当前技术栈

- Python 3.11、pydantic v2、openai SDK（OpenAI 兼容，DeepSeek/OpenAI 可切）。
- 评测：自建确定性 pipeline（pytest 子进程执行 + 静态规则）。
- 后端：FastAPI + uvicorn（只读 API over artifacts）。
- 前端：Vite 5 + React 18 + TypeScript 5（features/views 结构）。
- 沙箱：临时 git worktree + subprocess + timeout + 命令白名单（Docker 后置为“只讲/可选”）。
- 复用 `ft_diag_agent`：`llm.py`（provider）、`observability.py`（拷贝）、`judge_meta_eval` 叙事（待 M5）、FastAPI/React 结构。

## 3. 当前数据资产

- **mini_store**（`datasets/mini_store_src/`）：一个跨模块库存/下单库（models/inventory/pricing/discounts/cart/orders/catalog + refunds/loyalty/bundle），pytest 全绿。
- **mini_store_suite**（`datasets/mini_store_suite/`）：**9 个 case**
  - 4 bugfix：inventory-reserve、pricing-tax、discount-threshold、cart-merge
  - 2 spec：place-order（跨模块，hard）、catalog-search
  - 3 对抗性 regression-trap：refund-fee、loyalty-bonus、bundle-tier（专门暴露 V1 缺乏“完成前跑全套”纪律）
  - 每 case：defect 变体（现构时覆盖）+ hidden 测试（评分时注入）+ visible target + regression（分离文件）。
- 每 case 结构见 `src/codeagent_eval/benchmark/case.py`（EvalCase）。

## 4. 已完成模块

### M0 · 脚手架 + provider 复用
`settings.py / models.py / llm.py / observability.py`。llm.py 保留 tool_completion / json_completion / llm_trace_scope，补齐多轮 loop 由 agent 层驱动。离线测试验证结构化 tool_calls 解析 + trace 采集。

### M1 · MiniAgent + 沙箱（§13 三大全新之一）
- `sandbox/`：`CommandPolicy`（deny-by-default，拦 sudo/rm -rf/docker/网络工具/git push/shell 算子）+ `WorktreeSandbox`（临时 worktree、timeout、输出截断、路径逃逸守卫、干净清理）。25 个单测。
- `tools/`：6 个工具（list_files/search_code/read_file/apply_patch/run_command/git_diff），含禁止路径 + 唯一匹配守卫。
- `agent/`：MiniAgent loop + V1/V2 prompt + 完整 TraceEvent + 完成检查 + 安全终止（final/max_steps/timeout/provider_error/repeated_action）。
- 端到端：scripted provider 驱动修好 seed bug 并导出 diff（离线）。

### M2 · benchmark + 确定性 grader + CLI
- `benchmark/`：case 模型 + `materialize_case`（每 case 现构单缺陷仓库，历史无解）+ `inject_hidden_tests` + `apply_reference_fix`。
- `graders/`：`run_pytest`（逐 test 解析）+ Test/Constraint/Patch grader + Task/Strict 合并。
- `runner.py`：CLI 一键跑 reference/none/v1/v2；落 artifacts（含运行溯源 `config.json`/`summary.run_config`：agent/provider/model/temperature/complexity/max_tokens/max_steps/timeout）；聚合 mean+方差、pass@k vs pass^k。
- `scripts/selfcheck.py`：硬门槛（target 在 base 失败 / 缺陷隔离 / 参考修复后 target+regression+hidden 全过 / hidden 不可读）。

### M4 · V1→V2 回归（money shot）
- `failure_taxonomy.py`：失败自动归因（§9 taxonomy）。
- `compare.py` + `scripts/compare_runs.py`：Version Compare（improved/regressed/stable + 成本 delta）。
- V2 harness = reproduce-first + 完成前跑全套 + git_diff + 重复动作守卫 + 注入 AGENTS.md。

### M3 · FastAPI + React 控制台
- `backend/app/`：只读 API（experiments / experiment / trial / compare），读 `artifacts/runs/`。
- `frontend/`：Experiments 列表、Experiment Detail（指标卡 + case 表 + 失败筛选）、Trace Viewer（step 列表 + 事件详情 + grader 概览 + 着色 diff）、Version Compare。

### M5 · HumanEval+ + LLM-Judge + kappa
- `benchmark/humaneval_plus.py`：HumanEval+ adapter（EvalPlus schema 的自建子集，10 题，含 base/plus 测试；temp 目录 + 超时执行）。DeepSeek Pass@1 100%（base+plus，易题）。
- `judge/code_review_judge.py`：LLM-Judge（结构化 + 强制引用 + swap 平均 + temperature=0）。
- `judge/meta_eval.py`（拷改 ft_diag）：agreement + Cohen's kappa + trust map；`judge/gold.py` + `data/judge_gold/` 人工 gold（6 case/16 item）。
- 结果：CORRECTNESS/EDGE_CASES kappa=1.0（gate）、READABILITY kappa=0.62（贴 0.6 门槛）。见 `docs/judge_meta_eval_report_v1.md`。
- 脚本：`scripts/run_humaneval.py`、`scripts/run_judge_meta_eval.py`。

### C · SWE-bench 适配器 + Docker 设计
- `benchmark/swebench.py`：读官方 instance schema（`FAIL_TO_PASS`/`PASS_TO_PASS`/`test_patch`/gold `patch`，兼容官方 JSON-string 编码），跑官方 resolve 流程。
- `datasets/swebench_compat/`：一个 SWE-bench 格式兼容样本（自包含小仓库）。gold 应用后 resolved 1/1；**MiniAgent(V2) 真实修复并 resolved 1/1**。标注 "Compatibility Sample"，非排行榜。
- `docker/sandbox.Dockerfile` + `docs/swebench_and_docker.md`：Docker 沙箱设计（本机无 daemon，未 build，作设计验证）+ 真实 SWE-bench Lite 接入路径（clone + env 复现）。
- 脚本：`scripts/run_swebench.py`（gold/agent 双模式）。

## 5. 最近一次验证结果

mini_store，DeepSeek v4-flash，9 个 case × 5 repeats，同配置：

| agent | Task | Strict | 备注 |
|---|---|---|---|
| reference | 1.00 | 1.00 | 上界（应用参考修复） |
| **V2** | **1.00** | **1.00** | 每 case pass^k=1（可靠）；工具调用 +~50% |
| V1 | 0.98 | 0.98 | 仅 `regtrap-loyalty-bonus` 0.80、pass^k=0 |
| none | 0.00 | 0.00 | 下界（不改动） |

Version Compare（V1→V2）：**improved=1（loyalty 0.80→1.00），regressed=0，stable=8**。loyalty V1 失败被自动归因为 `PREMATURE_TERMINATION`（target 过但没跑 regression/hidden）。

结论（如实）：强模型在 8/9 的简单/中等 case 上把 V1、V2 都打满（saturation）；harness 纪律恰好决定了 V1 不验证的那一个 case，代价是更多工具调用。这印证 “scaffold 在够难的 case 上决定成败”，也是诚实的区分度发现。

## 6. 当前服务状态

- backend：`uvicorn backend.app.main:app --port 8000`（按需启动，未常驻）。
- frontend：`cd frontend && npm run dev`（:5173，/api 代理到 :8000）。
- 二者仅用于本地演示，非生产。

## 7. 已知问题与风险

- **saturation**：现有 case 对 DeepSeek v4 偏易，V1/V2 套件级差异小（+0.02）。money shot 靠 per-case（loyalty）+ 成本对比 + reference/none 区分度支撑。要更大差异需更难 case 或更弱模型（M4 已如实标注）。
- **对抗 case 的稳定性**：regression-trap 依赖“V1 不跑全套”，强模型偶发主动跑全套 → loyalty 在 n=5 时 0.6~0.8 抖动。已用 repeats≥5 缓解；报均值+方差。
- **沙箱网络隔离**是命令层（拦网络工具），非内核级；真隔离要 Docker（C 层只讲/可选）。
- pytest 结果解析基于 `-v` 文本，未来接 pytest-json 更稳。
- 前端 `TestClient` 有 starlette httpx deprecation warning（无害）。

## 8. 建议下一步

1. **M5**（进行中，P1）：HumanEvalPlusAdapter（20–30 条，Pass@1、Base/Plus）+ 最小 LLM-Judge（Code Review，强制引用 + swap 平均 + temperature=0）+ 拷改 `judge_meta_eval.py`（agreement + Cohen's kappa + 不达标降级）。
2. **C**（P2）：SWEBenchAdapter（读官方格式、真跑 1 条 Lite，标 Compatibility Sample）+ Docker 沙箱设计验证。
3. 可选加固：更难 case 提升 V1/V2 区分度；SSE 实时进度接入控制台；SQLite 结构化存储（当前直接读 artifacts 文件）。
