# TASKS.md

Algora 里程碑与任务追踪。活文档，随进度更新。设计源 [`coding_agent_eval_plan_v2.md`](coding_agent_eval_plan_v2.md)，状态见 [`PROJECT_STATE.md`](PROJECT_STATE.md)。

优先级：**P0** = 当前核心闭环/标准协议的最高优先级；**P1** = 重要差异化与能力扩展；**P2** = 依赖更多数据或架构改造的后续研究。原里程碑中的最低成功线仍为 M1+M2+M4。

## 里程碑总览

| M | 内容 | 优先级 | 状态 |
|---|---|---|---|
| M0 | 脚手架 + provider 复用 | P0(enabling) | ✅ 完成 |
| M1 | MiniAgent V1 + 沙箱 | P0 | ✅ 完成 |
| M2 | 内部 benchmark + 确定性 grader + CLI | P0 | ✅ 完成 |
| M4 | V1→V2 回归对比（money shot） | P0 | ✅ 完成 |
| M3 | FastAPI + React 控制台 | P1 | ✅ 完成 |
| M5 | EvalPlus-schema 子集 + LLM-Judge + kappa | P1 | ✅ 完成（子集验证） |
| C | SWE-bench 兼容样例 + Docker 设计 | P2 | ✅ 完成（兼容验证） |
| DOC | 长期文档（本批） | — | ✅ 完成 |
| B1 | HumanEval+/EvalPlus 官方 Smoke Slice | P0 | ✅ 完成 |
| B2 | SWE-bench 官方实例 Smoke Slice | P0 | ✅ 3 实例金标通过（flask） |
| B3 | 统计增强与分层报告 | P0/P1 | 🟨 计划内核心完成，扩展字段待补 |
| B4 | Terminal-Bench/Harbor Protocol Study → Smoke Slice | P1 | 📝 文档阶段 |
| B5 | OctoBench Protocol Study → Smoke Slice | P1 | 📝 文档阶段 |
| G1 | 私有 Golden Dataset 类型扩充 | P0/P1/P2 | 🟨 长程 8-case + 多轮 3-case + hackbait 3-case 完成，其他类型待补 |
| V3 W1-1 | `mini_store_long` 长程 suite | P0 | ✅ 完成 |
| V3 W1-2 | AgentAdapter + MiniAgentAdapter + runner 接入 | P0 | ✅ 完成 |
| V3 W1-3 | ClaudeCodeAdapter | P0 | ✅ 代码；✅ protocol + repo live |
| V3 W1-4 | planner + V3 harness | P0 | ✅ 完成 |
| V3 W1-5 | CI + 容器内断网评测 | P0 | ✅ 完成 |
| V3 W1-6 | 并行执行 + trial 级续跑 | P0 | ✅ 完成 |
| V3 W1-7 | GLM provider + 模型阶梯 + 成本溯源 | P0 | ✅ 完成 |
| V3 W2-1 | 分级截断 + 确定性 compaction | P0 | ⚠️ 完成但短预算下自伤，见 F1/F2 |
| V3 W2-2 | run 内 ScratchPad | P1 | ✅ 离线工程闭环完成 |
| V3 W2-3 | 上下文遗忘检测器 | P0 | ✅ 核心完成 |
| V3 W2-4 | 测试投机检测器 | P0 | ✅ 完成 |
| V3 W2-5 | hackbait 专用 suite | P1 | ✅ 离线工程闭环完成 |
| V3 W2-6 | 指令偏移检测器 | P0 | ✅ 完成 |
| V3 W2-7 | SWE-bench 官方 Smoke Slice | P0 | ✅ flask 3/3 金标通过；requests 记为不可本地构建 |
| V3 W2-8 | 第二外部 Agent adapter | P0 | ✅ Cline CLI 3.0.49 |
| V3 W3-1 | 确定性 multi-turn + 3 case | P0 | ✅ 离线工程闭环完成 |
| V3 W3-2 | 跨 run RepoMemory | P1 | ✅ 含同-case 污染守卫，实测验证 |
| V3 W3-3 | 统计增强 | P0/P1 | ✅ 计划内统计完成 |
| V3 W3-4 | repro bundle + 回归 fixture | P0 | ✅ 完成 |
| V3 W3-5 | 静态报告 + 跨 Agent UI | P0 | ✅ 完成 |
| V3 W3-6 | 全量实验与假设回填 | P0 | 🟨 4-case 矩阵完成；W3-6a 因 GLM 额度暂停 |
| V3 W3-7 | 开源清理 + 洞察报告 | P1 | 🟨 README/横向报告部分完成 |

---

## 待办：V3 harness 短预算自伤（2026-08-05 诊断后挂起）

诊断见 `PROJECT_STATE.md` 的"v3.1 为何低于 v2"。两项按用户决定挂起，先走 JD 主线。

### F1 · 修 context 管理在短预算下的默认行为（不花 token，P0）

**问题**：`compaction_threshold` 按 32k 预算设定，而 120s 轨迹峰值只有约 11k——**默认配置下 compaction 从不触发**（16 个 trial 实测 0 次），但**截断始终生效**（`read_file` 截到 6000 字符）。V3 付了截断的代价却收不到压缩的收益。

**候选修法**（需先量后选，不要直接拍）：
- 按可用预算自适应设定 context budget（例如从 `BudgetContract.max_wall_clock_s` 与实测每轮耗时推出可达轮次，据此定预算）
- 或在轨迹达到某个长度前不启用截断——截断的收益也随长度增长，短轨迹上它只是在丢信息
- 两者都要在 8 case 上验证，且必须同时报 120s 与宽松档，避免只在一个预算点上过拟合

### F3 · 把测试篡改率做成带区间的数字（约 6M token，P0）

2026-08-05 首次在**完全开放的写入面**上观测到测试篡改：Cline 2/3、Claude Code 1/3、MiniAgent 0/3。这是本项目此前从未拿到的非零读数（以往都是"零 + 那是执行策略"）。

**但样本只有 9 次尝试**，撑不起任何比率声明。要出带区间的数字：

- 把可本地构建的 flask 实例从 3 条扩到 **6–8 条**（Lite 里 flask 只有 3 条，需再挑一个纯 Python 仓库补齐——`pylint-dev/pylint` 6 条是最可能可行的下一个；`pytest-dev/pytest` 17 条但自举测试较麻烦）
- 每个 arm **各跑 2 次**（篡改是二元事件，Wilson 区间在 n=12~16 时才有意义）
- 报告用 Wilson 区间而非点估计，且必须写明这是**自由观测**（SWE-bench 无 `forbidden_paths`），与本项目自建 suite 上的"策略拦截零值"不可混为一谈

这条的价值在于：**它是整个项目最有说服力的单个发现**——JD 第 4 条点名"测试投机"，而这是唯一一处能拿真实框架、真实任务、开放写入面说话的地方。

### F2 · 用 repeats=4 钉住 `v3 −context` vs 默认（约 3M token，P0）

实测差距 +0.312，当前 repeats=2 功效仅 32%，**10 个配对检验无一通过 Holm 校正**。repeats=4（32 trial/arm）给 90% 功效。

顺序应为 **F1 → F2**：先修，再用补足的样本验证修完确实有效——否则钉住的是一个即将被改掉的配置。

---

## V3 Week 1 · 地基

### W1-1 · `mini_store_long` ✅

- [x] 独立 `repo_src` 快照，避免修改历史短程基线；当前干净仓库 83 tests。
- [x] 4 个地基 hard case，后续扩到 8 个：API 迁移、跨模块退货、级联库存、build/CLI、折扣取整、税率真源、释放记账、订单快照。
- [x] `Horizon`、`CanarySpec`、`expected_steps`、`expected_tool_calls`、build/multi-turn task type 等 schema。
- [x] short 9/9、long 8/8 selfcheck；reference=1.0、none=0.0。
- [x] 正式校准 `v2-20260803T191808Z`：Task/Strict 1.00，动作中位数 30，模型轮次 13.5，测试循环 3，infra 0/4。
- **边界**：每 case 仅 1 次，数字只证明轨迹长度和闭环可执行，不代表稳定能力估计。

### W1-2 · Adapter 地基 ✅

- [x] `AgentAdapter` Protocol、`AgentRunResult`、`BudgetContract`、`Capability`、probe 与 registry。
- [x] `MiniAgentAdapter` 归一化 patch/trace/token/cost/stop reason/environment manifest；不支持的硬预算明确报错。
- [x] runner 保留 legacy `--agent`，新增 `--adapter mini_agent --harness v2`、`agent-result.json` 和显式 `--max-completion-tokens`。
- [x] provider/网络错误作为 infra-invalid 排除出能力分母；compare 拒绝基础设施无效 run。
- [x] V2 拒绝截断、空回复、无改动、未测试和末次测试失败的假完成；V1 行为不变。
- [x] 成本费率缺失时记录 `cost_usd=null`、`cost_source=unavailable`，不伪造零成本。
- **阶段验收快照**：W1-2 完成时 94 passed/1 skipped；当前总门禁见 `PROJECT_STATE.md`（408 passed/1 skipped）。

### W1-3 · ClaudeCodeAdapter ✅（代码 + live）

- [x] headless stream-json 边流边落盘，保留 native trajectory 并归一化为 `AgentRunResult`。
- [x] 独立 `CLAUDE_CONFIG_DIR`、环境白名单、进程组超时终止、CLI 脚手架剥离和成本语义降级。
- [x] 39 条离线测试以可执行 CLI stand-in 覆盖真实 subprocess、流式解析和预算终止路径。
- [x] 外部 stop reason 先映射 `canonical_stop_reason`，修复跨框架静默误归因。
- [x] Homebrew stable 安装 Claude Code 2.1.220；真实 `probe()` 通过。
- [x] 无认证流与智谱 GLM-5.2 协议流均返回有效 stream-json；`--max-turns` 虽未显示在 help 中但真实可用。
- [x] 获得明确数据披露授权后完成 `bugfix-pricing-tax` repo smoke：Task/Strict 1.00，6 tools / 8 model turns，hidden 仅评分时可见。
- [x] 修复 live 暴露的两项溯源丢失：CLI 版本进入实验 manifest/resume 指纹；外部 adapter 总 token 进入统一 trial 与 summary。
- [ ] 正式横向结果前先做 endpoint 稳定性/限流校准；后续两次 `ENOTFOUND` 均须保持 infra-invalid，不得计入能力分母。

### W1-4 · Planner + V3 harness ✅

- [x] `update_plan` 工具、状态机、计划修订轨迹和 V3 prompt。
- [x] 遵守率以文件写入/测试等仓库动作验证，不接受 Agent 自我声明作为证据。
- [x] `AgentConfig.for_harness()` 集中定义 V1/V2/V3 身份，防止新 harness 静默丢失旧守卫。
- [x] 修复 item id 改名造成的遵守率假象，新增 `plan_done_unverified` 与改名计数。
- **实验结论**：修正后 planner 对 Task/Strict 中性，但工具调用约增加 18%。

### W1-5 · CI + 容器化评测 ✅

- [x] quality / sandbox-image / console 三门禁与 bounds / EvalPlus oracle / LLM smoke 三个 nightly job。
- [x] CI 首跑全绿；镜像内以 `--network none` 跑短程、长程 selfcheck 和确定性边界。
- [x] `check_bounds.py` 对 reference=1.00 / none=0.00 逐 case 校验。

### W1-6 · 并行 + trial 级续跑 ✅

- [x] `--workers N` 进程池并行；短程 9×2 实测 17.0s → 4.26s（4.0×）。
- [x] trial 完成标记、manifest 指纹和聚合顺序稳定性；配置不符拒绝 resume。
- [x] infra-invalid trial 必须重试，不能被冻结成“已完成”证据。
- [x] 自动 experiment ID 加 UUID 后缀，防止两个独立进程同秒启动时覆盖 manifest/summary/清理目录。
- [x] 每个 repeat 使用独立 build 目录，修复并行 materialize 覆盖。

### W1-7 · Provider/模型阶梯/成本 ✅

- [x] 单一 `ProviderSpec` 表接入 DeepSeek、OpenAI 兼容和智谱 GLM；`--model` 写入 provenance。
- [x] 每模型费率含 source/as_of、aliases、tiered/cache 口径；未知价格为 `None`。
- [x] 记录 requested/served model，修复 `deepseek-reasoner` 解析到 flash 导致的静默错误归因。
- [x] GLM-4.5-air 与 glm-4.7-flash 已实跑；免费档限流作为 infra-invalid 单独报告。
- **边界**：`usd_per_cny=null`，GLM USD 成本按设计为 unavailable。

### W2-1 · Context management ✅

- [x] 工具输出分级截断、基于真实 prompt token 的触发条件和确定性 compaction。
- [x] 保证 assistant tool_calls 与 tool replies 不被切断；每次压缩发 `COMPACTION` 事件。
- [x] `--context-budget-tokens`、`--context-ceiling-tokens` 与 `--ablate` 写入 provenance/resume 指纹。
- [x] 上下文硬上限对所有 harness 生效，保证消融组承受相同约束。
- **修正后 H3**：V3.1=1.00，V3.1−context=0.33；compaction 是全部成功效应，planner 中性。

### Week 2 其余任务

- [x] **W2-2 ScratchPad**：有界 run-scoped key/value notes、动态 system context、`update_scratchpad` 工具、compaction/multi-turn 保留、context ceiling 计量、trial 隔离、独立消融和 artifact/summary 指标均完成。它不落目标仓库；跨 run RepoMemory 仍不得先于泄漏隔离设计。
- [x] **W2-3 Context amnesia**：被动 canary 检测、early/late split、短轨迹拒绝给 decay、跨 adapter 路径归一化均已完成；W3-5 展示聚合证据，专门的时间序列曲线留作 B3 可视化扩展。
- [x] **W2-4 Reward hacking**：8 类信号、evidence span、人工 hack 样本全命中、reference 零误报与历史回扫均已完成。
- [x] **W2-5 Hackbait suite**：3 条显式需求 case 覆盖削弱断言、skip 与输入硬编码；`allow_test_edits` 已贯穿 task/prompt/policy/scaffold，PatchGrade/Strict 不放宽。selfcheck 会执行每个 shortcut，要求 visible 命令表面绿、hidden 失败、detector 强命中且 reference 零误报；runner 按真实开放写入面的 trial 输出 per-trial artifact、case/suite rate、Wilson CI 与信号计数。离线门禁 3/3、reference/none=1.00/0.00；真实模型 hacking rate 因额度待跑。
- [x] **W2-6 Instruction drift**：轨迹重放、首次违规步、obedience ratio、self-corrected/persisted 已完成。
- [ ] **W2-7 官方 SWE-bench Smoke Slice**：仍只有 schema-compatible 自建样例。
- [ ] **W2-8 第二外部 adapter**：aider / mini-swe-agent 尚未接入。

### Week 3 · 统计、产品化与收口

- [x] **W3-1 Multi-turn**：确定性 visible-only feedback、分阶段测试公开、MiniAgent/Claude session 续接、全会话预算、恢复指标和 3 条 2–3 轮 case 均已完成；3/3 selfcheck、reference/none=1.00/0.00。真实模型 E5 因额度待跑，不把离线机制验收写成恢复率结论。
- [ ] **W3-2 RepoMemory**：跨任务记忆与 trial 间清空验证未实现。
- [x] **W3-3 Statistics**：case-cluster bootstrap、exact McNemar、Wilson、task_type/difficulty/horizon 分层宏平均、完整成本覆盖门禁、cost/success 与 case-cluster 配对成本 bootstrap 均已实现；缺失/旧 `0.0/derived` 成本保持 unavailable。
- [x] **W3-4 Repro bundle**：失败 trial 可生成脱敏诊断包与回归 fixture；无模型 replay 会重新 materialize、应用 patch、评分并比对稳定签名。hidden 测试代码/节点/失败正文和 native log 不入包，suite 指纹漂移、checksum 篡改、凭据形态 patch、infra-invalid 均拒绝误归因；旧 schema 可生成诊断包但明确拒绝编造 replay 证据。
- [x] **W3-5 Report/UI**：`report.py` + `build_static_report.py` 生成同源 JSON/Markdown/离线 HTML；只读 `/api/cross-agent` 与 `CrossAgent.tsx` 直接复用该事实模型，提供多 arm 选择、provenance/受控性预警、case matrix、分层、配对检验、成本覆盖和证据边界。
- 🟨 **W3-6（部分）**：4-case 模型受控横向矩阵、H2/H3 和检测器历史回扫已有数据；第二模型/第二外部 Agent 和全部预注册假设未完成。
- ⏸️ **W3-6a（外部额度阻塞）**：新的 8-case Claude Code / MiniAgent 模型受控矩阵保持原设计待跑。当前 GLM API 无可用额度，恢复条件是同一 GLM 模型端点可完成 preflight 且额度足够覆盖固定矩阵；不得临时换模型并把结果并入原受控比较。
- 🟨 **W3-7（部分）**：README 与 `cross_agent_report_v1.md` 已完成；开源状态核验、命名统一和完整 capability-gap/failure-atlas 文档未完成。

---

## M0 · 脚手架 + provider 复用 ✅
- [x] `pyproject.toml` / 包骨架 / `.env.example` / 目录。
- [x] 拷改 `llm.py`（去 fault-tree 依赖，保留 tool_completion / json_completion / trace scope）。
- [x] `observability.py` / `settings.py` / `models.py`。
- **验收**：带 tools 的 completion 拿到结构化 tool_calls，trace scope 采集 LlmCallRecord（离线测试通过）。✅

## M1 · MiniAgent + 沙箱 ✅
- [x] `sandbox/policy.py`（CommandPolicy）+ `sandbox/worktree.py`（WorktreeSandbox）。25 单测。
- [x] `tools/`：6 个工具 + Registry，禁止路径 + 唯一匹配守卫。
- [x] `agent/loop.py` + `agent/prompts.py`（V1/V2）。
- **验收**：端到端修好 seed bug 并导出 diff；全部 tool_call 入 trace；超步/超时安全终止；命令失败不崩主进程。✅

## M2 · benchmark + 确定性 grader + CLI ✅
- [x] `datasets/mini_store_src`（跨模块库）+ 可见测试全绿。
- [x] `datasets/mini_store_suite`：6 base case（4 bugfix + 2 spec）。
- [x] `benchmark/`：case 模型 + materialize + inject_hidden + reference_fix。
- [x] `graders/`：pytest_run + Test/Constraint/Patch + Task/Strict。
- [x] `runner.py`：reference/none/v1/v2 + artifacts + 聚合（mean+方差、pass@k/pass^k）。
- [x] `scripts/selfcheck.py` 硬门槛，6→9 case 全 valid。
- **验收**：一条命令跑完套件；hidden 不可见；失败定位到具体测试/约束；分别报 Task 与 Strict。✅

## M4 · V1→V2 回归对比 ✅
- [x] 3 条对抗性 regression-trap case（refund-fee / loyalty-bonus / bundle-tier），暴露 V1 缺“完成前跑全套”纪律。
- [x] V2 harness：reproduce-first + 完成前跑全套 + git_diff + 重复动作守卫 + 注入 AGENTS.md。
- [x] `failure_taxonomy.py`（§9 自动归因）。
- [x] `compare.py` + `scripts/compare_runs.py`（improved/regressed/stable + 成本 delta）。
- [x] 真实 LLM 跑 V1/V2 各 9×5，产出 Version Compare。
- **验收**：一次明确迭代；每项改动对应哪类失败说得清；同环境；展示 improved/regressed/stable 而非单一总分。✅
- **结果**：improved=1（loyalty 0.80→1.00, pass^k 0→1），regressed=0，stable=8；归因 PREMATURE_TERMINATION。

## M3 · FastAPI + React 控制台 ✅
- [x] `backend/app/`：experiments / experiment / trial / compare 只读 API。
- [x] `frontend/`：Experiments 列表 / Experiment Detail / Trace Viewer / Version Compare。
- [x] 浏览器实测四个视图 + Vite 代理 + 生产构建。
- **验收**：前端看每 case 结果、看完整 trace、看最终 patch、筛失败 case、看 Version Compare。✅

## M5 · EvalPlus-schema 子集 + LLM-Judge + kappa ✅
- [x] `benchmark/humaneval_plus.py`：10 题自建/精选 EvalPlus-schema 子集，Pass@1、Base/Plus、时延/异常/超时；temp 目录 + 超时执行；数据集 canonical 自检 10/10。
- [x] `scripts/run_humaneval.py`（含 `--selfcheck`）。DeepSeek 实测 Pass@1 100%（易题）。
- [x] `judge/code_review_judge.py`：LLM-Judge，结构化 `{score,max_score,passed_items,missed_items,confidence,reason,verdicts}` + **强制引用**（引用须在代码中，否则降 confidence）+ swap 平均 + temperature=0。
- [x] `judge/meta_eval.py`（拷改 ft_diag）：agreement + Cohen's kappa + trust map + 不达标降级；`judge/gold.py` + `data/judge_gold/`（6 case/16 item）。
- [x] `scripts/run_judge_meta_eval.py`；`docs/judge_meta_eval_report_v1.md`。
- **验收**：函数级 base/plus 评测流程跑通（Pass@1 100%，仅代表该 10 题易子集，不是正式 HumanEval+ 成绩）；judge 每条判定带有效引用；kappa 展示（CORRECTNESS/EDGE_CASES=1.0，READABILITY=0.62 贴阈值）。✅

## C · 只讲 + 部分落地 ✅（P2）
- [x] `benchmark/swebench.py`：读官方 schema（`FAIL_TO_PASS`/`PASS_TO_PASS`/`test_patch`/gold `patch`），跑官方 resolve 流程；`scripts/run_swebench.py`（gold/agent）。
- [x] 兼容样本 `datasets/swebench_compat/`：gold resolved 1/1；**MiniAgent(V2) 真跑 resolved 1/1**；标注 "Compatibility Sample"。
- [x] Docker：`docker/sandbox.Dockerfile` + `docs/swebench_and_docker.md`；CI 已 build，并在 `--network none` 下执行评测门禁。
- [x] 真实 SWE-bench Lite 接入路径写清（clone + env 复现；`materialize_instance` 留 NotImplementedError + 指引）。
- 仍只讲（不建）：Terminal-Bench/Harbor、PostgreSQL、成本看板全量；通用 adapter 契约与 MiniAgentAdapter 已在 V3 W1-2 落地，外部实现从 W1-3 开始。

## DOC · 长期文档 ✅
- [x] 根 `AGENTS.md`
- [x] `PROJECT_STATE.md`
- [x] `TASKS.md`
- [x] `docs/developer_guide.md`
- [x] `docs/benchmark_methodology_and_roadmap.md`

---

## B1 · HumanEval+/EvalPlus 官方 Smoke Slice ✅（P0）

- [x] 固定 EvalPlus 0.3.1；模型调用前以 seed `20260712` 选择 5 个官方任务并记录 SHA-256。
- [x] canonical oracle 使用同一官方 evaluator，Base/Plus=1.00/1.00。
- [x] 联网 generation 与受限环境 execution 拆分；官方 sanitizer + evaluator。
- [x] DeepSeek v4-flash：Base=1.00、Plus=0.80；逐题结果、trace、manifest 和限制落盘。
- [x] 产物标记 `smoke_slice`；报告明确不是完整排行榜成绩。
- **验收**：官方实例端到端可复现，`HumanEval/39` 展示 base→plus 的严格测试区分作用。✅

## B2 · SWE-bench 官方实例 Smoke Slice ⬜（P0）

- [ ] 选择少量可复现的官方 Verified/Lite 实例并记录筛选偏差。
- [ ] 按官方容器/环境契约先验证 oracle/gold。
- [ ] 保证 Agent 阶段不可见 test patch/gold；评分时运行 FAIL_TO_PASS/PASS_TO_PASS。
- [ ] 区分环境、oracle、Agent、patch apply、超时和 grader 失败。
- **验收**：至少一个真实官方实例完成 oracle + candidate 全流程；结果明确标注 official-instance smoke slice。

## B3 · 统计增强与分层报告 🟨（P0/P1）

- [x] P0：case-level/cluster bootstrap 置信区间 + Wilson 区间。
- [x] P0：Task/Strict exact McNemar。
- [x] P0：成本 case-cluster 配对 bootstrap；成本不完整时拒绝子集估计。
- [x] P0（已有 schema）：按 difficulty/task_type/horizon 分层，报告 case 宏平均与样本数。
- [ ] P0（schema 待补）：repo/language 分层；当前 suite/case schema 没有可审计字段，不从路径猜测。
- [x] P0（成本）：完整覆盖下 cost per success；缺失/旧零成本为 unavailable。
- [ ] P0：token/tool/time per successful trial；预算约束成功率已有实验数据但尚未统一成通用统计对象。
- [ ] P1：first target/full-suite pass time、测试失败恢复率、case 区分度。
- [ ] P2：多个模型/Agent、30+ case 后再研究项目—总分相关性。
- **纪律**：同一 case 的 repeats 不当独立 case；同时报告 effect size、区间、样本数和预算；“不显著”不等于“相同”。

## B4/B5 · Terminal-Bench 与 OctoBench 📝（P1）

- [x] 在 benchmark 方法论路线图中记录评测构念、协议、资源、风险与实施顺序。
- [ ] HumanEval+、SWE-bench 增量完成后，细化 Terminal-Bench/Harbor adapter 与 oracle 方案。
- [ ] 选择少量官方 Terminal-Bench 任务：先 oracle，后 Agent，保留容器末态与终端轨迹。
- [ ] 细化 OctoBench 官方环境、scaffold 指令与 objective checklist 映射。
- [ ] 选择少量官方 OctoBench 环境，验证 Task/Strict 分离和持续约束。
- **验收**：分别完成 protocol-conformant smoke slice；不作为全量 leaderboard 结果。

## G1 · 私有 Golden Dataset 扩充 🟨（长程与确定性多轮地基已完成）

- [x] P0（部分）：长程跨模块 spec、行为保持/API 迁移 refactor、级联 bugfix、build/CLI case 已落地；短程 instruction-following 仍待补。
- [ ] P1：带证据的 code review；以缺陷检出率/mutation score 评分的 test generation；performance；security；并发/资源泄漏/事务一致性。
- [x] P2（第一阶段）：3 条确定性 multi-turn case、分阶段 visible oracle、session 续接、累计预算、恢复指标与泄漏防护已落地；开放式用户模拟器和真实模型 E5 尚未完成。
- [ ] 所有 case 补齐来源、标签、难度、语言、reference/oracle、污染/flaky/捷径检查、版本和修订记录。

---

## 当前推荐执行顺序

V3 W1 全部完成，W2-1/2/3/4/5/6 完成，W3-1/3/4/5 完成，W3-6/7 部分完成。W3-6a、ScratchPad live 消融、多轮 E5 与 hackbait 行为测量因 GLM API 额度暂停；其余离线工程继续：

1. 优先推进 W2-8 第二外部 Agent adapter，复用现有 normalize/budget/provenance 契约补齐三方横向能力。
2. 再完成 W2-7 / B2 官方 SWE-bench Smoke Slice；跨 run RepoMemory 最后评估，先证明 trial 隔离和无答案泄漏。
3. 额度恢复后执行 W3-6a、ScratchPad 消融、multi-turn E5 与 hackbait 行为测量；保持冻结模型和受控配置，不与替代模型混并。
