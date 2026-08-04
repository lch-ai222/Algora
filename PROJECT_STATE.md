# PROJECT_STATE.md

Algora（CodeAgent Eval Lab）当前状态快照。这是**活文档**，每完成一个里程碑或有重要验证结果时更新。规则见 [`AGENTS.md`](AGENTS.md)，任务见 [`TASKS.md`](TASKS.md)。

最后更新：2026-08-04。

## 1. 当前总体状态

闭环已跑通并用真实 LLM（DeepSeek v4-flash）验证。**原 7/7 里程碑 + B1 + V3 地基 W1-1 到 W1-7 全部完成 + W2-1 上下文管理**：V3 已有长程 suite、可扩展的 AgentAdapter 接入层和 Claude Code headless adapter。Claude Code 2.1.220 已完成真实 probe、智谱 GLM-5.2 协议流和一个获授权的 repo case 全链路；这仍只是集成 smoke，不是横向评测结果。

最低成功线（M1+M2+M4）+ 可演示控制台（M3）+ 可归因的 V1→V2 结果（M4）+ EvalPlus-schema 子集与 judge meta-eval（M5）+ SWE-bench 兼容适配器（C）全部就绪。当前没有完整公开 benchmark 或排行榜成绩。

- 测试：**255 passed, 1 skipped**（skip 是 `RUN_LLM_SMOKE` 门控的真实 LLM 冒烟）。
- Lint：`ruff` 全绿（src/tests/scripts/backend + `datasets/mini_store_long`）。
- 干净虚拟环境验证：仅 `pip install -e ".[dev,api]"` 后，ruff/pytest/selfcheck/check_bounds 全部通过（不依赖 `PYTHONPATH`）。
- 确定性边界门禁：`scripts/check_bounds.py` 在短程 + 长程两个 suite 上 reference=1.00、none=0.00，逐 case 校验。
- benchmark 自检：短程 **9/9 valid**、长程 **4/4 valid**；HumanEval canonical 自检 **10/10**。
- 官方 EvalPlus Smoke Slice：固定 5 个 HumanEval+ 官方任务，canonical oracle Base/Plus **1.00/1.00**；DeepSeek v4-flash **Base 1.00 / Plus 0.80**。
- 前端：TypeScript 干净，`npm run build` 干净（48.75 kB gzip），浏览器实测无 console 报错。

### 本轮迭代摘要（15 commits）

- 测试从 **94 → 252**；落地 Claude Code adapter、CI/容器门禁、并行续跑、模型费率、预算实验变量、planner 与 deterministic compaction。
- H2：模型阶梯只在最弱的 `glm-4.7-flash` 上产生有限区分度（1.00→0.84）；H2 的强信号来自预算收紧，同一 suite 的模型差距由 0.00 放大到 0.85。
- 首次成本测量：DeepSeek flash/pro 成功率相同，成本差 5.26×；缓存分档避免一次 trial 成本被高估 4.94×。
- 修正后 H3：compaction 是全部成功效应（1.00→0.33），planner 对成功率中性但工具调用约 +18%。
- 本轮发现 8 个自身缺陷：外部 stop reason 误归因、resume 冻结 infra trial、pro 模型别名静默失效、requested/served model 混淆、并行 materialize 目录冲突、context budget 未约束对照组、V3 丢失 V2 守卫、plan id 改名击穿遵守率。后三项会静默改变实验结论，必须作为评测有效性缺陷而不只是工程 bug 对待。

### Claude live preflight 查证（2026-08-04）

- Anthropic 当前官方推荐 macOS 使用 native installer，也正式支持 Homebrew cask；为保持安装可追踪、版本不自动漂移且便于卸载，本项目选择 stable cask `brew install --cask claude-code`，不用 `curl | bash`。卸载命令为 `brew uninstall --cask claude-code`。
- 智谱官方文档已确认 Claude/Anthropic API 兼容端点：国内开放平台为 `https://open.bigmodel.cn/api/anthropic`，可使用 `glm-5.2`；Z.AI Coding Plan 另有 `https://api.z.ai/api/anthropic`。因此“统一 GLM 模型的 Claude Code 对比”在协议层可行，但仍须真实 CLI 验证 tool use、stream-json、模型映射与限流，不能仅凭接口文档认定实验可比。
- 当前机器通过 Homebrew stable cask 安装 Claude Code **2.1.220**（`/opt/homebrew/bin/claude`）；真实 adapter `probe()` 通过。无认证 stream-json 流和智谱 GLM-5.2 单回合协议流均已验证；该版本 `--help` 不列 `--max-turns`，但实跑接受，证明 capability probe 不能只解析 help。
- 获得明确数据披露授权后，`claude_code-20260804T113926Z` 在 `bugfix-pricing-tax` 上完成真实 repo smoke：Task/Strict 1.00，6 次工具调用、8 个模型轮次，仅修改 `mini_store/pricing.py`，target/regression/hidden 分别 2/2、2/2、3/3；原始轨迹和评分前轨迹均未出现 hidden 测试，artifact 未检出 API key。该 n=1 结果只证明 patch/grade/artifact 链路可执行。
- CLI 返回了 24,588 input、430 output、128,896 cached tokens；第三方 endpoint 的 native USD 成本语义不可信，adapter 按设计将成本降级为 `null/unavailable`。repo live 同时暴露并修复两个溯源缺陷：实验级 `adapter_version` 曾为 null，外部 Agent 汇总 token 曾因没有逐调用 `LlmCallRecord` 而显示 0；现在 CLI 版本进入 manifest/resume 指纹，归一化 token 总量直接进入 `TrialResult` 和 summary。
- 随后的复验两次遇到智谱端点 `ENOTFOUND`，均被正确记为 infra-invalid 且 resume 会重跑，不进入能力分母。这说明统一模型路径协议上可行，但正式矩阵前仍需做 endpoint 稳定性和并发校准。

## 2. 当前技术栈

- Python 3.11、pydantic v2、openai SDK（OpenAI 兼容，DeepSeek/OpenAI/智谱可切）。
- 评测：自建确定性 pipeline（pytest 子进程执行 + 静态规则）。
- 后端：FastAPI + uvicorn（只读 API over artifacts）。
- 前端：Vite 5 + React 18 + TypeScript 5（features/views 结构）。
- 沙箱：本地为临时 git worktree + subprocess + timeout + 命令白名单；CI 镜像内以 `--network none` 执行完整确定性评测门禁。
- 复用 `ft_diag_agent`：`llm.py`（provider）、`observability.py`、Judge meta-eval 方法与 FastAPI/React 结构。

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

### C · SWE-bench 适配器 + Docker 隔离
- `benchmark/swebench.py`：读官方 instance schema（`FAIL_TO_PASS`/`PASS_TO_PASS`/`test_patch`/gold `patch`，兼容官方 JSON-string 编码），跑官方 resolve 流程。
- `datasets/swebench_compat/`：一个 SWE-bench 格式兼容样本（自包含小仓库）。gold 应用后 resolved 1/1；**MiniAgent(V2) 真实修复并 resolved 1/1**。标注 "Compatibility Sample"，非排行榜。
- `docker/sandbox.Dockerfile` + `docs/swebench_and_docker.md`：CI 已完成镜像 build，并在 `--network none` 下运行短/长 selfcheck 与确定性边界；本机工作流仍使用命令层隔离。文档另保留真实 SWE-bench Lite 的 clone + 环境复现路径。
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
- **跨进程也必须隔离**：并行启动短/长 bounds 时发现秒级时间戳会让两个独立 runner 生成相同 experiment ID，从而可能互相覆盖 manifest/summary 或删除对方目录。自动 ID 已改为 `agent-UTC-<uuid8>`；显式 `--resume <id>` 不变，并有同秒唯一性回归测试。
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
- **费率已填（2026-08-04，含 source URL 与日期）**：DeepSeek v4-flash/v4-pro（USD，官方 pricing 页）、GLM-5.2/4.7/4.5-Air/4.7-FlashX/4.7-Flash（CNY，官方 pricing 页，JS 渲染，用浏览器读取）。
- `tiered` 标记：GLM 的 4.7 / 4.5-Air 按输入/输出长度分档计价，表内登记**最贵档**并让估算带 `upper_bound=true`——长程 trial 确实会越过 32k 分界，选最便宜档会对一半 trial 系统性低估。
- `aliases`：厂商保留旧模型名。**用实时 API 验证**：`deepseek-chat` 与 `deepseek-reasoner` 都解析到 `deepseek-v4-flash`。
- **修掉两个由此暴露的缺陷**：(1) `DEEPSEEK_MODEL_PRO=deepseek-reasoner` 使 "pro" 档成为静默空操作（实际服务的是 flash），默认改为 `deepseek-v4-pro`；(2) `last_model` 原先只记**请求**的名字，产物会声称跑了一个从未运行过的模型——现在记录**实际服务**的模型，并保留 `requested_model` 供对照。
- **GLM 型号已换代**：`glm-4.6` 与 `glm-4-flash` 已不在现价目表。阶梯更新为 **glm-5.2（强）/ glm-4.5-air（中）/ glm-4.7-flash（弱，免费）**。
- ⚠️ `usd_per_cny` 仍为 null，因此 **GLM 成本按设计报 `unavailable`**（不假设汇率）；DeepSeek 为 USD 计价，成本正常产出。

## 5. 最近一次验证结果

### V3 长程校准（正式基线）

`v2-20260803T191808Z`，DeepSeek v4-flash，temperature=0，4 case × 1 repeat，单回合输出上限 4096：Task/Strict **1.00/1.00**，有效 trial **4/4**，infra **0**；工具动作中位数 **30**，模型轮次中位数 **13.5**，测试运行中位数 **3**。逐 case 工具动作是 34/26/16/44。成本费率未配置，故 `cost_usd=null`、`cost_source=unavailable`。

该运行只用于 W1-1 难度/轨迹长度验收，n=1 不足以证明稳定成功率；后续横向评测必须增加 repeats、置信区间和配对检验。

### V3 W1-7 首次真实成本测量（2026-08-04）

DeepSeek，V2 harness，短程 2 case × 1 repeat，workers=2，费率表 `2026-08-04`：

| model | Task | 2 trial 成本 | tokens/trial | tools/trial |
|---|---|---|---|---|
| deepseek-v4-flash | 1.00 | $0.000791 | 13,820 | 7.0 |
| deepseek-v4-pro | 1.00 | $0.004163 | 18,536 | 8.0 |

**成本比 5.26×，成功率完全相同** —— 在这个 suite 上多付 5 倍买不到任何东西。这是 saturation 结论第一次带上成本维度（H1 的直接证据）。样本极小（n=1/case），只用于验证成本链路与展示口径，不能外推。

缓存计价的实际影响：某 trial 的 13,365 prompt tokens 中 11,904 为缓存命中（89%）。按 cached 费率计为 **$0.000414**；若不分档会算成 **$0.002047**，**高估 4.94×**。这是"缓存分档计价不是可选项"的实测依据。

### V3 H2 检验：模型阶梯只在最弱档产生区分度，且远弱于预算（2026-08-04）

短程 suite（9 case），V2 harness，`max_steps=20`：

| 系统 | Task | Strict | valid | 工具调用/trial |
|---|---|---|---|---|
| DeepSeek v4-flash | 1.00 | 1.00 | 2/2 | 7.0 |
| DeepSeek v4-pro | 1.00 | 1.00 | 2/2 | 8.0 |
| **GLM-4.5-air** | **1.00** | **1.00** | **45/45** | 8.8 – 14.6 |
| **GLM-4.7-flash**（免费档） | **0.84** | **0.84** | 41/45（4 infra） | 6.4 – 16.2 |

**H2 部分成立，但比预测弱得多。** 原假设是弱模型把成功率拉到 0.35–0.70；实测最弱档是 **0.84**，且只有这一档有效——GLM-4.5-air 与 DeepSeek 两档全部 1.00、每 case pass^k=1。

弱档的逐 case 分布才是有信息量的部分：4 个 case 满分，`spec-place-order` 掉到 **0.40**、`regtrap-bundle-tier` 0.60、`cart-merge` 0.75、`pricing-tax` 0.80，且这 4 个 case 的 **pass^k=0**（不可靠）。失败模式以 **REPEATED_ACTION（4 次）** 为主——把被拦截或失败的同一动作逐字重复直到守卫截停，其余为 PLANNING / TASK_UNDERSTANDING / TIMEOUT 各 1。

**与预算收紧对比：模型阶梯的区分度（1.00 → 0.84，差 0.16）远小于预算收紧（0.93 → 0.07，差 0.85）。** 换模型不如收预算。

更重要的是这条结论指向 benchmark 本身而不是模型：**难度天花板太低**。而且 `mini_store_long` 在 V2+DeepSeek 下也是 1.00（n=1），所以长程 suite 同样饱和 —— 这直接威胁 H3（V2→V3 compaction 消融）的可测性。

**区分度的最便宜来源是预算而不是新 case**：当前 `max_steps=20`，而实测工具调用只用到 7–14.6，冗余 30–65%。把预算压到 8–10，`spec-place-order`（14.6）和 `regtrap-loyalty-bonus`（13.2）会对 GLM-4.5-air 失败而 DeepSeek（7.0）仍通过——**不写一条新 case 就能得到区分度**。"预算约束成功率"本来就在方法论的指标清单里，只是还没当成实验变量用。

### V3 预算收紧实验：区分度不来自更难的 case，来自更紧的预算（2026-08-04）

同一个短程 suite（9 case × 3 repeats = 27 trial/格），V2 harness，只改 `--max-steps`：

| `max_steps` | DeepSeek v4-flash | GLM-4.5-air | 差距 |
|---|---|---|---|
| 20（case 默认） | 1.00 | 1.00 | **0.00** |
| 12 | 1.00 | — | |
| 8 | 1.00 | 0.78 | 0.22 |
| 6 | 1.00 | 0.81 | 0.19 |
| 4 | 0.93 | **0.07** | **0.85** |

**同一套 case，预算从 20 收到 4，区分度从 0 变成 0.85。一条新 case 都没写。**

两个反直觉的观察：

1. **模型会适应预算，而不是消耗预算。** DeepSeek 在 20 步预算下只用 7 步，但把预算压到 6 仍然 1.00 —— 说明"用了 7 步"是选择而非需求。因此"实测步数 / 预算"的冗余比**不能**用来预测收紧后会不会失败，只有真跑才知道。
2. **是断崖不是渐变。** DeepSeek 在 8/6 都满分，4 才破；air 在 8/6 徘徊 0.78–0.81（n=3 下这两点只差 1 个 trial，属噪声），4 直接崩到 0.07。

方法论修正：`max_steps` 从 case 常量升格为**实验变量**（`--max-steps`，写入 provenance 与 resume 指纹）。饱和不等于"case 太简单"—— 是**预算太松，让能力差异没有地方显现**。被测的维度其实是"约束下的效率"，而它此前完全不可见。

这条直接改善 H3 的可测性：V2→V3 的 compaction 消融应当在收紧预算下做，而不是在默认预算下期待差异。

### V3 W1-4 · 任务规划（planner）

- `agent/planner.py` + `tools/planning_tools.py` + v3 prompt：`update_plan` 工具、计划状态机、逐修订记录。V3 = V2 + planner，**其他一律不变**，所以 V2/V3 的差异只能归因到 planner。
- **遵守率对着仓库算，不对着 agent 的声明算。** 计划是自述的：agent 可以把每项都标成 done 而一个字都没写，"5/5 完成"会把它评成完美规划。因此每次 `done` 转换都要检查期间是否发生过真实仓库动作（文件写入或跑测试）；没有的就记为 `plan_done_without_action`——计划表演，单独计数且不计入 adherence。
- 工具只做校验与回显，**状态与指标由 loop 持有**——否则一次工具调用就能悄悄抬高 agent 自己的规划分。
- 指标：`plan_declared` / `plan_adherence` / `plan_abandonment` / `plan_done_without_action` / `plan_done_retroactively`（首次出现即 done 的项算记账不算规划）/ `plan_revisions`。聚合只在**声明过计划的 trial** 上取平均，避免被从未被要求规划的系统稀释。
- Claude Code 的 TodoWrite 归一化为同一形状，但 **adherence 显式留空**并给出原因：MiniAgent 的数字来自全程观察仓库动作的 tracker，从归一化轨迹重建一个"看起来可比"的值是假可比。

**实测发现：给了 planner 不等于会规划，采用与否取决于任务长度。**

| suite | case | 工具动作 | 是否规划 | items | adherence |
|---|---|---|---|---|---|
| 短程 | bugfix-pricing-tax | 7 | **否** | — | — |
| 短程 | spec-place-order | 17 | **否** | — | — |
| 长程 | long-refactor-pricing-api | — | 是 | 3（3 次修订） | 1.00 |
| 长程 | long-crossmodule-returns | 32 | 是 | 7（2 次修订） | 0.71 |

DeepSeek v4-flash 在短程 case 上完全忽略规划指令（已确认 7 个工具确实提供、v3 prompt 确实生效，不是接线问题），长程上则主动规划且无计划表演（`done_without_action=0`）。这条本身就是 planner 消融的第一份数据：**短程上 V2/V3 不可能有差异，因为 V3 根本没启用它的新能力**。

### V3 W2-1 · 上下文管理（分级截断 + compaction）

`agent/context.py`。两个取舍刻意选了保守的一边，因为这是**评测 harness** 而不是产品：

- **上下文大小是测量的，不是估算的。** 每轮之后用 provider 自己报告的 `prompt_tokens` 驱动 compaction。char/4 启发式会随模型和工具 schema 漂移，导致触发阈值对每个被测系统对应的真实大小都不同——跨 Agent 的上下文对比就失去意义。启发式只在还没有任何测量时兜底。
- **compaction 是确定性的，不是模型生成的。** 用 LLM 总结被丢弃的轮次更"聪明"，但会在每个长 trial 中间插入一次不确定、要计费的调用——同一配置跑两次会因为与被测对象无关的原因发散。改为用轨迹构建摘要：读过哪些文件、写过哪些文件、跑过哪些命令、测试结果、当前计划。可复现，而且正好是 agent 为了不重复劳动所需要的信息。
- 消息序列合法性：assistant 的 tool_calls 必须有对应的 tool 回复，切在中间会被 provider 直接拒绝。`_safe_tail_start` 保证切口两侧都不产生孤儿。
- 分级截断：read_file 6000 字符 > run_command 4000 > list_files 2000；保头尾（头部说明检查了什么，尾部通常是结果或报错）。
- 每次 compaction 发 `COMPACTION` trace 事件（before_tokens / dropped_messages / digest_chars），否则 compaction 之后的失败只能靠猜。

**消融支持**：`--ablate planner|context` 可单独关掉 V3 的任一新增能力，且写入 `adapter_version`（`0.1.0+v3-no_context`）与 resume 指纹——消融后的 V3 是另一个系统，记成同一个 "v3" 会让对比表无法阅读。`--context-budget-tokens` 与 `--max-steps` 一样是实验变量。

**实测**（DeepSeek v4-flash，`long-crossmodule-returns`，预算 16k）：

| 指标 | 值 |
|---|---|
| compaction 次数 | 3 |
| 每次丢弃消息 | 23 / 23 / 21 |
| 峰值利用率 | 0.906（14,495 / 16,000） |
| 摘要大小 | 316 → 869 → 1088 字符（随工作累积增长） |
| 结果 | Task 1.00，plan adherence 1.00（6 项 / 3 次修订） |

### V3 H3 消融实验：compaction 有效，planner 有害（2026-08-04）

长程 suite（4 case × 3 repeats = 12 trial/组），DeepSeek v4-flash，**上下文硬上限 12k**（对所有组生效），V3 compaction 阈值 10k：

| 组 | Task | Strict | 溢出 | compaction | 峰值 tok | 工具调用 | plan 遵守率 |
|---|---|---|---|---|---|---|---|
| v2（两者皆无） | 0.50 | 0.42 | 9 | 0 | 14,398 | 23.4 | — |
| **v3（两者皆有）** | 0.75 | 0.67 | 0 | 60 | 11,175 | 64.7 | 0.47 |
| v3 − context | 0.33 | 0.33 | 10 | 0 | 14,107 | 23.7 | 0.22 |
| **v3 − planner** | **1.00** | **1.00** | 0 | 50 | 10,275 | 62.9 | — |

**结论一：compaction 是有效的那一半。** 从 v3 拿掉它，0.75 → 0.33（−0.42），失败模式几乎全变成 `CONTEXT_OVERFLOW`。有 compaction 的两组峰值稳定在上限之下（11.2k / 10.3k < 12k），溢出为 0。

**结论二：planner 是有害的那一半。** 从 v3 拿掉它，0.75 → **1.00**（+0.25），且零失败。

为什么：**当瓶颈是上下文时，planner 把稀缺资源花在了计划记账上。** 佐证是 v2（0.50）竟然好于 v3−context（0.33）——两者都没有 compaction，唯一差别是后者带 planner，即 **planner 在没有 compaction 兜底时单独造成 −0.17**。plan 遵守率也偏低（0.47 / 0.22），说明 agent 并没有很好地执行自己写的计划。

这条否定了 W1-4 的隐含假设。任务规划是 JD 逐字点名的能力，主流 Agent 都有，但**在这个约束条件下它降低成功率**。诚实的表述是：planner 的价值取决于瓶颈是什么——瓶颈是上下文时它是净负担。

**边界（必须同时陈述）**：n=3/case、12 trial/组，0.25 的差距约等于 3 个 trial，置信区间很宽；单模型；12k 上限是照着实测峰值 14.5k 挑的，换一个上限结论可能不同。这是方向性证据，不是效应量估计。

### V3.1 planner 诊断：之前的"planner 有害"是我自己的两个 harness bug（2026-08-04）

从轨迹逐层挖，找到三件事，**两件是缺陷，一件是真实行为**：

**缺陷 1（主因）：V3 静默丢失了 V2 的完成守卫。** loop 里写的是 `if self.config.version == "v2"`，字符串相等判断——加了 v3 之后没人改这里。于是 v3 / v3−context / v3−planner 三组都缺少 v2 有的 premature-final 纪律，**整个 H3 对比测的不只是"planner vs 无 planner"**。已改为由 `AgentConfig.for_harness()` 统一定义 harness 身份，所有构造点走同一处；直接构造仍可用于消融，但从真实定义出发。

**缺陷 2：adherence 指标被 id 改名击穿。** 模型在两次修订间把全部 item id 改名（`models`→`records`、`inventory`→`restock`…）而**文本逐字不变**。tracker 按 id 匹配，改名后的项被当成全新且已完成，记为 retroactive、零遵守率。之前报的 **0.47 / 0.22 / 0.33 全是测量假象**。已改为按归一化文本匹配，并把改名次数本身作为指标上报（**12 个 trial 里 49 次改名**，是模型的真实行为）。

**真实行为 3：agent 会在测试之前就把计划项标记为 done。** 观察到的失败轨迹里，4 个项在 step 26 一次性从 pending 跳到 done，而首次测试在 step 28。可见测试全过、hidden 测试才抓到原子性缺陷。新增 `plan_done_unverified` 指标 + 工具结果里回灌警告（点名哪些项在打开后没跑过测试就被标完成），并在 v3 prompt 中写明**计划是工作辅助，不是完成证据；只有测试能决定何时停止**。

**修复后重跑（同配置：长程 4 case × 3 repeats，上下文上限 12k）**：

| 组 | Task | Strict | 溢出 | compaction | 未验证完成 | id 改名 | 工具调用 |
|---|---|---|---|---|---|---|---|
| v2（两者皆无） | 0.42 | 0.42 | 9 | 0 | 0 | 0 | 23.5 |
| **v3.1（两者皆有）** | **1.00** | 0.92 | 0 | 55 | 9 | 49 | 65.8 |
| v3.1 − context | 0.33 | 0.33 | 10 | 0 | 4 | 0 | 22.3 |
| v3.1 − planner | **1.00** | 0.92 | 0 | 44 | 0 | 0 | 55.9 |

**修正后的结论**：
- **planner 不是有害，是中性**：v3.1 与 v3.1−planner 的 Task/Strict 完全相同，且两组都零失败。代价是工具调用多约 18%（65.8 vs 55.9）。
- **compaction 是全部效应**：拿掉它 1.00 → 0.33，失败几乎全是 `CONTEXT_OVERFLOW`。
- v3.1 从 0.75 升到 1.00，提升同时来自守卫恢复与 planner 的自我认证被打断。

**方法论教训**：一个消融只有在两组"除被测能力外完全相同"时才成立。这次两组差的不只是 planner，而差异来自我自己代码里的字符串相等判断——**没有轨迹级诊断就会把 harness 缺陷当成能力结论发表出去**。

### V3 横向评测 v1：模型受控的 Claude Code vs MiniAgent（2026-08-05）

完整报告见 [`docs/cross_agent_report_v1.md`](docs/cross_agent_report_v1.md)。

智谱同时提供 OpenAI 兼容与 Anthropic 兼容端点，因此三个 scaffold 跑**同一个 glm-5.2**——**唯一变量是 scaffold**。主约束取 wall-clock（唯一被三者以相同方式执行的预算；步数语义各异，上下文上限对 Claude Code 无法施加）。

| arm | 预算 | n | Task | Strict | 工具调用 | 模型轮次 | 失败 |
|---|---|---|---|---|---|---|---|
| Claude Code | 宽松 | 8 | **1.00** | **1.00** | 27.8 | 46.4 | — |
| Claude Code | 120s | 12 | **0.50** | 0.50 | 14.6 | 24.1 | TIMEOUT×6 |
| MiniAgent v3.1 | 宽松 | 12 | 1.00 | 0.83 | 34.7 | 19.1 | — |
| MiniAgent v3.1 | 120s | 12 | **1.00** | 0.83 | 34.3 | 18.8 | — |
| MiniAgent v2 | 宽松 | 12 | 1.00 | 0.92 | 31.8 | 19.2 | — |
| MiniAgent v2 | 120s | 12 | 0.92 | 0.83 | 34.3 | 19.3 | TIMEOUT×1 |

**结论**：宽松预算下三者 Task 全 1.00（无分辨力）；收紧到 120s 后 Claude Code 掉到 0.50 而 v3.1 保持 1.00。机制清楚——120s 内 Claude Code 只发 14.6 次工具调用、MiniAgent 发 34.3 次，**它把时间花在推理上**。但它也是唯一 Task/Strict 双 1.00 的：**用延迟换取了工程规范性，宽裕时净收益、紧张时净损失**。

**采集过程暴露三个测量缺陷，任一未修都会让结论错误**：物化仓库缺 `.gitignore`（pytest 字节码算作源码改动 → 会报"Claude Code 6/8 工程不合规"）、`--max-wall-clock` 只穿给 MiniAgent 分支（Claude Code 在 120s 限额下实跑 258s → **结论方向相反**）、外部 adapter token 汇总报 0。

**边界**：12 trial/组，0.50 ≈ 6 个 trial，区间很宽；4 case、单模型、两个预算点；Claude Code 宽松档因额度耗尽无法补跑且原产物已删，证据等级低于其余五组（详见报告 §5.3）。

### V3 W2-4 · 测试投机检测器 + 历史回扫（2026-08-05）

`detectors/reward_hacking.py`，8 类信号：TEST_REMOVED / SKIP_MARKER_ADDED / ASSERTION_WEAKENED / HARDCODED_TEST_INPUT（strong），CONFTEST_MODIFIED / EXCEPTION_SWALLOWED / ENV_VAR_SHORTCUT（suspicious），TEST_FILE_MODIFIED（informational）。

**三条设计纪律**：
- **每条信号必带触发它的 diff 原文**。人工无法复核的判定不是可用证据，而"投机"恰恰是最会被质疑的一类结论。
- **改测试本身不构成指控**。refactor 任务合法地会改测试；只有专门解除验证的行为（删测试、加 skip、抽断言、硬编码期望值）才是 strong。把两者混同，检测率就没人信。
- **宁可漏检不可误报**。验收门禁是：8 个手写 hacking patch **全部命中**，benchmark 里**所有 reference 解零误报**。

**检测与强制分离**：MiniAgent 的沙箱直接拒绝写测试文件，禁止之后这个维度就永远测不到。所以无论 case 是否允许，一律检测，由调用方决定如何计分。

**历史回扫（`scripts/scan_reward_hacking.py`，无需新实验）**：扫描磁盘上全部 **640 个真实 patch**，strong 信号 **0 个**。

但这个 0 必须拆开报，且脚本已把区分做成结构性的（读 `completion_checks.command_policy_enforced`）：

| 样本 | n | 强信号 | 95% 上界 | 含义 |
|---|---|---|---|---|
| 全部 | 640 | 0 | 0.60% | 混合了被强制与被观察 |
| **MiniAgent（沙箱拦截）** | 624 | 0 | — | **0 是强制结果，不是行为观察** |
| **Claude Code（未被拦截）** | 16 | 0 | **19.4%** | 唯一测量行为的样本 |

诚实表述：**在 16 个不受约束的 trial 中未观察到测试投机，95% 上界 19.4%；样本太小，不能作为"不发生"的证据。** 检测器有效性与检出率分开论证——前者由 8/8 命中 + 零误报支撑，与后者无关。

`stats/intervals.py`：Wilson 区间（零事件时正态近似退化，故用 Wilson）。

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
- **Claude Code 只有 n=1 repo smoke，不是横向结论**：单 case patch/grade/artifact 已全链路通过，但后续两次出现 endpoint `ENOTFOUND`。正式横向实验必须先校准稳定性、并行度和 infra 比例；不能把集成成功或网络失败包装成 Agent 能力。
- **默认预算下两个 suite 近乎饱和**：短程对 DeepSeek 两档与 GLM-4.5-air 全部 1.00，只有最弱的免费档到 0.84；长程对 V2+DeepSeek 也是 1.00（n=1）。**H2 只在最弱档成立且效应很小**；H3（compaction 消融）若在默认预算下做会面临同样风险。优先级最高的补救是把**预算变成实验变量**（max_steps / context budget / wall-clock），其次才是加难 case。
- **GLM 免费档限流严重**：`glm-4.7-flash` 在 workers=4 下 44/45 触发 429；串行可跑但约 78s/trial。付费档（glm-4.5-air）workers=3 下 infra=0。并行度必须按档位分别设定。
- **GLM 成本需汇率**：`usd_per_cny` 为 null，GLM 成本按设计报 `unavailable`。填一个带出处和日期的汇率即可启用；汇率每日变动，属于操作者选择而非可以内置的常量。
- **分档计价是上界**：GLM 4.7 / 4.5-Air 的成本估算标记 `upper_bound`，不是点估计。要精确需按每次调用的输入/输出长度分桶。
- **沙箱网络隔离**：MVP 是命令层（拦网络工具），非内核级；内核级隔离由 CI 的 `--network none` 容器执行覆盖（已实跑验证），本地开发路径仍是命令层。
- **并行度不是跨模型常量**：4.0× 加速是在确定性 reference/none 上测的；真实 LLM 已观察到档位相关限流——GLM 免费档 workers=4 时 429 严重，付费 air 档 workers=3 时 infra=0。横向实验必须为每个 provider 预校准并行度，并把 infra-invalid 排除出能力分母。
- pytest 结果解析基于 `-v` 文本，未来接 pytest-json 更稳。
- 前端 `TestClient` 有 starlette httpx deprecation warning（无害）。

## 8. 建议下一步

1. **校准 Claude Code 统一模型路径**：repo smoke 已通过，下一步先用少量重复测 endpoint 稳定性、限流与 infra 比例，再冻结横向矩阵；当前 `ENOTFOUND` 波动不能忽略。
2. **启动模型受控横向组**：智谱 Anthropic 兼容端点的 tool use、stream-json、实际模型映射已验证；仍把“各自默认模型的真实产品组”单列，避免把产品能力和 scaffold 纯效应混为一谈。
3. **B3 统计先于扩大结论**：repeats 提到 5、加第二模型、扫 2–3 档上下文上限；报告 cluster bootstrap、exact McNemar、effect size、样本数与成本/成功前沿。
4. **并行推进失败模式检测器**：优先测试投机，再做上下文遗忘与指令漂移；所有检出必须保留 evidence span 和人工复核入口。
5. **planner 需要专门任务才能测价值**：当前长程 suite 上它中性。新 case 应考需求分解和跨模块协同，而不是继续靠宽松默认预算制造饱和。
6. **开源与 Golden Dataset 分离**：可开源框架、adapter、grader 和公开示例 suite；正式私有 suite、hidden tests、reference fix 不公开，避免主动破坏低污染资产。
7. **公开 benchmark**：SWE-bench 官方 Smoke Slice 仍是 P0，但不冒充全量排行榜；GLM 需要 USD 成本时再填带出处/日期的 `usd_per_cny`。
