# PROJECT_STATE.md

Algora（CodeAgent Eval Lab）当前状态快照。这是**活文档**，每完成一个里程碑或有重要验证结果时更新。规则见 [`AGENTS.md`](AGENTS.md)，任务见 [`TASKS.md`](TASKS.md)。

最后更新：2026-08-04。

## 1. 当前总体状态

闭环已跑通并用真实 LLM（DeepSeek v4-flash）验证。**原 7/7 里程碑 + B1 + V3 地基 W1-1/W1-2/W1-3/W1-5/W1-6/W1-7 已完成**：V3 已有长程 suite、可扩展的 AgentAdapter 接入层和 Claude Code headless adapter（代码层完成，**尚未 live 验证**——本机无 `claude` CLI）。

最低成功线（M1+M2+M4）+ 可演示控制台（M3）+ 可归因的 V1→V2 结果（M4）+ EvalPlus-schema 子集与 judge meta-eval（M5）+ SWE-bench 兼容适配器（C）全部就绪。当前没有完整公开 benchmark 或排行榜成绩。

- 测试：**182 passed, 1 skipped**（skip 是 `RUN_LLM_SMOKE` 门控的真实 LLM 冒烟）。
- Lint：`ruff` 全绿（src/tests/scripts/backend + `datasets/mini_store_long`）。
- 干净虚拟环境验证：仅 `pip install -e ".[dev,api]"` 后，ruff/pytest/selfcheck/check_bounds 全部通过（不依赖 `PYTHONPATH`）。
- 确定性边界门禁：`scripts/check_bounds.py` 在短程 + 长程两个 suite 上 reference=1.00、none=0.00，逐 case 校验。
- benchmark 自检：短程 **9/9 valid**、长程 **4/4 valid**；HumanEval canonical 自检 **10/10**。
- 官方 EvalPlus Smoke Slice：固定 5 个 HumanEval+ 官方任务，canonical oracle Base/Plus **1.00/1.00**；DeepSeek v4-flash **Base 1.00 / Plus 0.80**。
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
- **mini_store_long**（`datasets/mini_store_long/`）：独立干净仓库快照 + **4 个 hard case**（12 文件定价 API 迁移、5 模块退货工作流、单根因级联库存缺陷、7 文件打包/CLI 交付链）；干净仓库 53 tests，全套 canary、hidden、reference/none 锚点齐备。
- 每 case 结构见 `src/codeagent_eval/benchmark/case.py`（EvalCase）。

### Benchmark 实施等级（2026-07-12 校准）

- `mini_store`：**完整私有 benchmark / Golden Dataset**，不是业内公共 benchmark。
- HumanEval 部分：**10 题 EvalPlus-schema 自建/精选子集验证**，不是完整官方 HumanEval+。
- HumanEval+ 官方部分：**B1 Smoke Slice 已完成**（EvalPlus 0.3.1、5 个固定 seed 官方任务、官方 sanitizer/evaluator）；仍不是全量 benchmark。
- SWE-bench 部分：**官方 schema 兼容 + 自建 Compatibility Sample**，未跑真实官方实例。
- Terminal-Bench/Harbor、OctoBench：**Protocol Study 文档已完成**，待前两项公开 benchmark 增量完成后实现少量官方实例 Smoke Slice。

统一方法与路线见 [`docs/benchmark_methodology_and_roadmap.md`](docs/benchmark_methodology_and_roadmap.md)。公开 benchmark 的近期目标是少量官方实例、完整官方协议的可复现实操，不追求高成本全量排行榜。

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

### M5 · EvalPlus-schema 子集 + LLM-Judge + kappa
- `benchmark/humaneval_plus.py`：EvalPlus schema 的自建/精选子集（10 题，含 base/plus 测试；temp 目录 + 超时执行）。DeepSeek Pass@1 100%（base+plus，易题）；该结果只验证流程，不是正式 HumanEval+ 数字。
- `judge/code_review_judge.py`：LLM-Judge（结构化 + 强制引用 + swap 平均 + temperature=0）。
- `judge/meta_eval.py`（拷改 ft_diag）：agreement + Cohen's kappa + trust map；`judge/gold.py` + `data/judge_gold/` 人工 gold（6 case/16 item）。
- 结果：CORRECTNESS/EDGE_CASES kappa=1.0（gate）、READABILITY kappa=0.62（贴 0.6 门槛）。见 `docs/judge_meta_eval_report_v1.md`。
- 脚本：`scripts/run_humaneval.py`、`scripts/run_judge_meta_eval.py`。

### C · SWE-bench 适配器 + Docker 设计
- `benchmark/swebench.py`：读官方 instance schema（`FAIL_TO_PASS`/`PASS_TO_PASS`/`test_patch`/gold `patch`，兼容官方 JSON-string 编码），跑官方 resolve 流程。
- `datasets/swebench_compat/`：一个 SWE-bench 格式兼容样本（自包含小仓库）。gold 应用后 resolved 1/1；**MiniAgent(V2) 真实修复并 resolved 1/1**。标注 "Compatibility Sample"，非排行榜。
- `docker/sandbox.Dockerfile` + `docs/swebench_and_docker.md`：Docker 沙箱设计（本机无 daemon，未 build，作设计验证）+ 真实 SWE-bench Lite 接入路径（clone + env 复现）。
- 脚本：`scripts/run_swebench.py`（gold/agent 双模式）。

### B1 · HumanEval+/EvalPlus 官方 Smoke Slice

- `benchmark/evalplus_official.py`：官方数据延迟加载、模型调用前固定抽样、deterministic override、数据 SHA-256、oracle gate、官方 sanitizer/evaluator、逐题结果解析和溯源 manifest。
- `scripts/run_evalplus_smoke.py`：`--selfcheck`、联网但不执行代码的 `--generate-only`、受限环境 `--resume` 两阶段流程。
- 依赖隔离：`.venv-evalplus`（约 662 MB）+ 项目内 `.cache/evalplus`（约 9.1 MB），均不提交；EvalPlus 固定 0.3.1。
- 结果：5 个官方任务；oracle Base/Plus=1.00/1.00；DeepSeek v4-flash Base=1.00、Plus=0.80，`HumanEval/39` 只在 plus 输入失败。
- 边界：HumanEvalPlus-Mini、小样本、local evaluator 无 Docker；macOS rlimit 兼容设置关闭内存硬限制。见 `docs/evalplus_smoke_report_v1.md`。

### V3 W1-1/W1-2 · 长程数据地基 + AgentAdapter

- `adapters/`：`AgentAdapter` Protocol、`AgentRunResult`、`BudgetContract`、`Capability`、probe/registry 和 `MiniAgentAdapter`；无法硬执行的成本/总 token 预算会明确拒绝，不静默降级。
- `runner.py`：保留 `--agent` 兼容入口，新增 `--adapter mini_agent --harness v2` 与显式 `--max-completion-tokens`；每 trial 写 `agent-result.json` 与环境清单。
- V2 完成门禁：provider 暴露 `finish_reason`；截断、空 summary、无改动、未跑测试或末次测试失败不会被误判为正常结束。V1 的刻意薄基线保持不变。
- 聚合：provider/网络失败记为 infra-invalid，不进入成功率分母；summary 增加动作、模型轮次、测试次数中位数；成本费率缺失时为 `null/unavailable`。

### V3 W1-3 · ClaudeCodeAdapter（headless）

- `adapters/claude_code.py`：`claude -p --output-format stream-json --verbose` 调用；纯函数 `parse_stream_json` 把 system/assistant/user/result 记录归一化为 `TraceEvent`。未知记录类型与畸形行只计数不中断（CLI 升级只应降级轨迹，不应中断已花预算的 trial）。
- `adapters/normalize.py`：跨框架共享的工具语义表（Read→FILE_READ、Bash+pytest→TEST_RESULT、TodoWrite→PLAN_UPDATE…），供 aider/mini-swe-agent 复用；`is_test_command` 有防漂移测试锁定与 MiniAgent loop 的判定一致。
- 三条评测有效性红线：**配置隔离**（每 trial 独立 `CLAUDE_CONFIG_DIR`，操作者真实 `~/.claude` 的 settings/hooks/MCP 不参与）、**成本溯源**（`ANTHROPIC_BASE_URL` 指向第三方端点时 `total_cost_usd` 语义错误，降级为 `unavailable` 而非当作 native）、**原始轨迹留档**（边流边落盘，预算 kill 后仍保留部分轨迹）。
- 预算：wall-clock 用进程组 SIGTERM→SIGKILL 硬执行（子进程 pytest/node 一并终止）；`max_steps`→`--max-turns`；成本/总 token 上限 CLI 无法执行，明确 `UnsupportedCapability` 而非静默忽略。
- 归一化边界如实标注：stream-json 只报 `is_error` 布尔，派生的 `exit_code` 附 `exit_code_source=inferred_from_is_error`；`.claude/` 等 CLI 自建脚手架在导出 patch 前剥离并登记，否则 changed-files 口径跨 adapter 不可比。
- `runner.py`：`--adapter claude_code` 使外部 adapter 成为独立 agent 标签（不再折进 v1/v2 harness 轴）；实验开始前 fail-fast probe；trial 目录自包含（原始轨迹 relocate 到 `rep<k>/native/`）。
- **修复跨 Agent 归因缺陷**：`failure_taxonomy` 原按 MiniAgent 原生 `stop_reason` 字符串匹配，外部 Agent 的 `error_max_turns` 等词汇不在表内会被静默误归因。新增 `TrialResult.canonical_stop_reason`，归因改走框架无关语义；旧产物无该字段时按原映射回退，历史归因不变（有回归测试）。
- 测试：39 条（纯 parser + 用可执行 CLI stand-in 驱动真实 subprocess 的流式落盘、超时进程组 kill、环境白名单、成本降级、脚手架剥离）。

### V3 W1-5 · CI + 容器化评测

- `.github/workflows/ci.yml`：三个独立门禁。**quality**（ruff + pytest + 短/长程 selfcheck）、**sandbox-image**（`docker build` 后在容器内 `--network none` 跑 selfcheck 与确定性边界）、**console**（`tsc && vite build`）。全部无需 LLM key，CI 恒定可跑。
- `sandbox-image` 的设计要点：只 build 不算数——能 build 但跑不了 trial 的镜像不是隔离层。CI 在容器内、断网条件下跑完整评测流水线，这才把 `docker/sandbox.Dockerfile` 从"设计文档"变成"可执行证据"，也是 MVP worktree 沙箱（命令层拦截）做不到的内核级网络隔离。
- `.github/workflows/nightly-eval.yml`：**bounds**（不用 pip 缓存的全新依赖解析 + 边界门禁，捕获上游漂移，例如 pytest 输出变化打断 grader 解析）、**evalplus-oracle**（官方 canonical oracle 必须仍为 1.00/1.00）、**llm-smoke**（有 provider key 时才跑，无 key 干净跳过）。
- nightly 的纪律：**只对基础设施故障失败，不对模型答错失败**。以成功率作为 nightly 门禁会训练出"把 case 改简单来修红灯"的行为，而这正是 benchmark 要检测的失败模式。runner 的退出码 3（infra-invalid）恰好是正确语义。
- `scripts/check_bounds.py`：新增的 benchmark 健康门禁。selfcheck 验单个 case，它验**流水线**——reference 低于 1.00 说明 suite 不可解或 grader 坏了，none 高于 0.00 说明有 case 不干活也能过；两者都是单测抓不到的静默失效。
- `.dockerignore`：把 `.venv`（约 660MB）、缓存和 artifacts 挡在构建上下文外。
- **CI 首跑三个 job 全绿**，含 `sandbox-image`：镜像 build 成功，并在 `--network none` 下跑通 selfcheck 与确定性边界。容器化评测由此不再是设计文档。

### V3 W1-6 · 并行执行 + trial 级断点续跑

- **调度与检查点的单位都是 trial**：`--workers N` 用进程池并发 N 个 trial；每个 trial 最后写 `trial-complete.json` 标记，`--resume <experiment_id>` 只重跑缺失的部分。
- **并行是调度细节，不是语义**：聚合始终按 suite 顺序而非完成顺序，实测 workers=1 与 workers=8 的 summary 逐字段一致（仅 experiment_id / created_at / workers / duration 这些本就该变的字段不同）。实测短程 9 case × 2 repeats：**17.0s → 4.26s（4.0×，565% CPU）**。
- **默认 `--workers 1`**：并行会改变 provider 的限流行为，因此并行是显式选项，已校准的基线保持逐位可复现。
- 修掉一个并行才会暴露的缺陷：`materialize_case` 原先按 `build_root/<case_id>` 建仓，同一 case 的并发 repeats 会互相覆盖。改为每个 trial 独立 build 目录。
- **断点续跑必须诚实**：`manifest.json` 固定实验身份（agent/suite/repeats/cases/run_config），`--resume` 遇到配置不符直接拒绝（退出码 2）——否则会把两套配置的 trial 平均进同一个 summary，而这是下游任何检查都发现不了的溯源失效。
- 完成标记最后写，所以中途被打断的 trial 目录**永远不会被 resume 采纳**；`trial.json`（不含 events，events 从 `trajectory.jsonl` 还原）保证恢复出来的不只是分数，还包括工具调用/测试次数等轨迹派生指标。
- **崩掉的 trial 是缺失证据，不是 Agent 失败**：worker 内部吞掉异常并记为 infra-invalid（形状合法的零分产物），第 47 个 trial 崩了不会丢掉前 46 个，也不会被算成 Agent 答错。进程池整体死亡（OOM/信号）在父进程侧按同样口径记录。
- `scripts/check_bounds.py` 与 CI 的边界门禁改用 `--workers 2`，CI 顺带覆盖并行路径。

### V3 W1-7 · GLM provider + 模型阶梯 + 成本表

- `ProviderSpec` 表取代原先三处平行的 if-chain（client / model / availability）。加 backend 只改一处数据，不会漏改导致"能连上 A 但溯源写成 B 的模型"。GLM（zhipu）由此接入。**这个缺陷是真实存在的**：重构时发现 `_expected_model` 就是漏改的第三处，zhipu 会返回 `None`。
- **模型阶梯 = 一个 flag**：`--model glm-4.6 / glm-4.5-air / glm-4-flash`，显式覆盖优先于 complexity，且写入 run provenance——阶梯之间只差这一个参数，不靠改环境变量。
- `pricing.py` + `config/pricing.json`：**每模型**费率表，三条纪律——
  1. 查不到费率是 `None` 不是 `0.0`（0 在任何表格和图里都读作"这次是免费的"；原先的 `LLM_*_COST_PER_1K_USD` 默认 0，未定价的运行会静默报出"成本为零"）；
  2. 费率必须带 `source` URL 和 `as_of` 日期，缺任一项视为不可用——厂商定价会变；
  3. **不做隐式汇率换算**：CNY 计价的模型只有在操作者显式填了 `usd_per_cny` 时才产出 USD，否则不可用。猜一个汇率等于凭空制造精度，而对比会继承这个精度。
- 缓存命中按 cached 费率计价（兼容 DeepSeek 的 `prompt_cache_hit_tokens` 与 OpenAI 式的 `prompt_tokens_details.cached_tokens` 两种口径）；表里没有 cached 费率时按全价计并标记 `upper_bound=true`，不冒充精确估计。
- trial 级：**只有全部调用都定价成功才报成本**。只把定价成功的那部分加起来会低估总额，却仍然长得像一个真数字。
- 每次运行的 `run_config` 记录 `pricing_revision` / `pricing_path`——否则归档产物里的成本数字在厂商调价后就无法回溯核对。
- ⚠️ **`config/pricing.json` 目前所有费率为 null**，即成本仍是 `unavailable`。填费率是一步需要查厂商官网的手工操作（要连同 source URL 和日期一起填），机制已就绪。

## 5. 最近一次验证结果

### V3 长程校准（正式基线）

`v2-20260803T191808Z`，DeepSeek v4-flash，temperature=0，4 case × 1 repeat，单回合输出上限 4096：Task/Strict **1.00/1.00**，有效 trial **4/4**，infra **0**；工具动作中位数 **30**，模型轮次中位数 **13.5**，测试运行中位数 **3**。逐 case 工具动作是 34/26/16/44。成本费率未配置，故 `cost_usd=null`、`cost_source=unavailable`。

该运行只用于 W1-1 难度/轨迹长度验收，n=1 不足以证明稳定成功率；后续横向评测必须增加 repeats、置信区间和配对检验。

### V2 短程历史结果

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
- **公开 benchmark 证据等级有限**：HumanEval 是自建/精选 schema 子集，SWE-bench 是自建兼容样例；两者均不得包装成正式排行榜结果。
- **统计功效有限**：当前私有集共 13 case，长程正式校准仅 n=1/case，不能把 1.00 外推成稳定能力；横向对比仍需 repeats 与区间。
- **覆盖范围有限**：仍只有 Python 小仓库；虽已补 API refactor 与 build/CLI，但 review/test-generation/performance/security/multi-turn 与多语言仍缺。
- **ClaudeCodeAdapter 未 live 验证**：本机无 `claude` CLI，stream-json 记录结构与 flag 集按官方文档实现 + 容错解析，测试以 CLI stand-in 驱动。**接触真实 CLI 后必须先 probe + 单 case 冒烟核对 schema/flag，再产出任何横向数据**；在此之前不得声称已具备横向评测结果。
- **成本表未填**：`config/pricing.json` 的费率全为 null，因此成本仍诚实记录为 `unavailable`。机制（每模型费率、溯源、汇率不假设、缓存计价）已完成，**缺的是从厂商官网抄费率这一步手工操作**。Claude Code 侧仅在官方端点下报 native 成本。
- **沙箱网络隔离**：MVP 是命令层（拦网络工具），非内核级；内核级隔离由 CI 的 `--network none` 容器执行覆盖（已实跑验证），本地开发路径仍是命令层。
- **并行下的成本/限流未验证**：4.0× 加速是在确定性 reference/none 上测的（CPU-bound）。真实 LLM trial 是 I/O-bound，加速比可能更高，但会撞 provider 限流；首次并行跑真实模型前需要观察 429 与重试行为。
- pytest 结果解析基于 `-v` 文本，未来接 pytest-json 更稳。
- 前端 `TestClient` 有 starlette httpx deprecation warning（无害）。

## 8. 建议下一步

1. **填 `config/pricing.json` 费率**（含 source URL 与 as_of 日期），成本口径才真正可用。
2. **首次用 GLM 跑真实实验**：短程 suite 上跑 glm-4.6 与 glm-4-flash 两档，验证阶梯是否恢复区分度（H2），并小规模观察并行下的限流行为。
3. **V3 W1-4 · planner/v3 prompt**：`update_plan` 工具 + plan 遵守率打点，解锁 Agent 框架线。
4. **ClaudeCodeAdapter live 验证**：一旦有可用 CLI，先 probe + 单 case 冒烟核对 stream-json schema 与 flag 集。
4. **公开 benchmark**：SWE-bench 官方 Smoke Slice 仍是后续 P0，但不冒充全量榜单。
