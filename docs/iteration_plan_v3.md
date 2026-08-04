# Algora V3 迭代方案：从"自评闭环"到"异构 Agent 横向评测平台 + 有能力边界的自研框架"

本文是 Algora 下一轮（3 周）的完整迭代方案。它回答四个问题：**补什么、为什么这么补（与主流 Agent / JD 的对齐关系）、补完之后框架长什么样、要跑哪些评测以及预期结果是什么**。

- 上游文档：[`coding_agent_eval_plan_v2.md`](../coding_agent_eval_plan_v2.md)（原始设计）、[`benchmark_methodology_and_roadmap.md`](benchmark_methodology_and_roadmap.md)（benchmark 方法论）
- 状态文档：[`PROJECT_STATE.md`](../PROJECT_STATE.md)、[`TASKS.md`](../TASKS.md)
- 本文定位：**规划**。所有"预期结果"均为**预注册假设（pre-registered hypothesis）**，不是已得结论。执行后须以真实数据回填，并保留与假设相反的结果。

### 执行进度（2026-08-04）

- **W1-1 已完成**：`mini_store_long` 4/4 selfcheck，reference/none=1.0/0.0；正式 V2 校准 `v2-20260803T191808Z` 为 Task/Strict 1.00、工具动作中位数 30、模型轮次 13.5、测试运行 3。该数据是 n=1/case 的难度校准，不是稳定成功率结论。
- **W1-2 已完成**：AgentAdapter/MiniAgentAdapter、预算契约、能力探测、环境清单、归一化结果、runner adapter 路由和 infra-invalid 口径已落地；94 passed/1 skipped。
- 校准发现并修复 V2 将 token 截断空回复误判为 final 的缺陷；默认 2048 保留，长程校准显式使用 4096 并写入溯源。成本费率未配置，因此正式产物为 `null/unavailable`。
- **W1-3 已完成（代码层）**：`ClaudeCodeAdapter` + stream-json 归一化 + `normalize.py` 共享语义表；runner 支持 `--adapter claude_code`（外部 adapter 成为独立 agent 标签，不再折进 v1/v2 轴）；trial 目录自包含（原始轨迹 relocate 到 `rep<k>/native/`）。133 passed/1 skipped，ruff 全绿，两个 suite selfcheck 9/9 + 4/4。
- W1-3 期间发现并修复一个跨 Agent 归因缺陷：`failure_taxonomy` 原先按 MiniAgent 的原生 `stop_reason` 字符串做规则匹配，外部 Agent 的 `error_max_turns` 等原生词汇不在该词表内，会被静默误归因为 UNKNOWN。已引入 `TrialResult.canonical_stop_reason`，归因改走框架无关语义；旧产物无该字段时按原映射回退，历史归因结果不变（有回归测试锁定）。
- ⚠️ **W1-3 尚未 live 验证**：本机未安装 `claude` CLI。stream-json 记录结构与 flag 集按官方文档实现并做了容错解析（未知记录类型/畸形行只计数不中断），测试用可执行的 CLI stand-in 驱动真实 subprocess 路径（流式落盘、wall-clock 终止、进程组 kill、环境白名单）。**接触到真实 CLI 后必须先跑 `probe()` 与单 case 冒烟，核对 schema 与 flag 后再产出任何横向数据。**
- **W1-5 已完成（配置层）**：`ci.yml` 三门禁（quality / sandbox-image / console）+ `nightly-eval.yml` 三 job（bounds / evalplus-oracle / llm-smoke）+ `scripts/check_bounds.py` 确定性边界门禁 + `.dockerignore`。CI 全程不需要 LLM key；140 passed/1 skipped。已在干净 venv（仅 `pip install -e ".[dev,api]"`）逐步验证 ruff/pytest/selfcheck/check_bounds，并本地验证 `npm ci && npm run build`。
- **CI 首跑全绿**，含 `sandbox-image`：镜像 build 成功并在 `--network none` 下跑通 selfcheck 与确定性边界，容器化评测已落地。
- **W1-6 已完成**：`--workers N` 进程池并行 + `--resume` trial 级断点续跑；聚合按 suite 顺序，实测 workers=1 与 workers=8 summary 逐字段一致；短程 9×2 实测 17.0s→4.26s（4.0×）。默认 workers=1 以保持已校准基线可复现。`manifest.json` 固定实验身份，resume 配置不符直接拒绝。修掉了并行才暴露的 build 目录冲突。156 passed/1 skipped。
- **W1-7 已完成（机制层）**：`ProviderSpec` 表取代三处平行 if-chain 并接入 GLM（重构时发现 `_expected_model` 正是漏改的第三处）；`--model` 一个 flag 切换阶梯并写入溯源；`pricing.py` + `config/pricing.json` 每模型费率表，未定价报 `None` 而非 `0.0`、费率须带 source/as_of、CNY 不做隐式汇率换算、缓存命中分档计价、trial 内部分定价即整体不可用。182 passed/1 skipped。
- **费率已填（2026-08-04）**：DeepSeek（USD）与 GLM（CNY）均带 source URL 与日期；新增 `aliases` 与 `tiered` 两个字段。实时 API 验证发现 `deepseek-reasoner` 解析到 v4-flash，因此修掉两个缺陷：`DEEPSEEK_MODEL_PRO` 默认使 pro 档成为静默空操作；`last_model` 只记请求名会让产物声称跑了一个从未运行的模型（现记录实际服务模型 + `requested_model`）。GLM 型号已换代，阶梯更新为 glm-5.2 / glm-4.5-air / glm-4.7-flash（免费）。191 passed/1 skipped。
- **首次真实成本测量**：DeepSeek v4-flash vs v4-pro，短程 2 case，Task 均 1.00，成本 **$0.000791 vs $0.004163（5.26×）**——H1 saturation 首次带上成本维度。缓存分档计价把某 trial 的成本从 $0.002047 修正到 $0.000414（避免 4.94× 高估）。
- **H2 部分成立但远弱于预期（2026-08-04）**：最弱的 GLM-4.7-flash 在短程 suite 上 0.84（41/45 valid），逐 case 见 `spec-place-order` 0.40、`bundle-tier` 0.60，且 4 个 case pass^k=0；主导失败模式是 REPEATED_ACTION。但 GLM-4.5-air 与 DeepSeek 两档全部 1.00 —— **阶梯只在最弱一档起作用，且区分度（0.16）远小于预算收紧（0.85）**。长程 suite 对 V2+DeepSeek 也是 1.00（n=1），因此 H3 若在默认预算下做同样有不可测风险。
- **由此产生的方案修正**：区分度最便宜的来源是**预算**而不是新 case。实测工具调用 7–14.6 对 `max_steps=20`，冗余 30–65%；压到 8–10 即可让重工具的 case 对弱档失败、对强档通过。§6.3 的"预算约束成功率"应从指标升格为**实验变量**。
- 运行纪律新发现：GLM 免费档限流极严（workers=4 → 44/45 触发 429），付费档 workers=3 下 infra=0。并行度须按档位设定。
- **预算收紧实验已完成并证实假设**：同一 suite 只改 `--max-steps`，DeepSeek vs GLM-4.5-air 的差距从 20 步时的 **0.00** 变成 4 步时的 **0.85**（1.00/1.00 → 0.93/0.07），一条新 case 都没写。两个反直觉观察：模型会**适应**预算而非消耗预算（DeepSeek 给 20 用 7，压到 6 仍满分），所以冗余比不能预测收紧后的表现；曲线是**断崖**不是渐变。
- **方案修正**：`max_steps` 从 case 常量升格为实验变量，写入 provenance 与 resume 指纹。§7 的 H3 应在收紧预算下检验，否则大概率复现 H2 的 0 差异。
- **下一项：W1-4 planner**；在 Claude Code live 验证完成前，不能宣称已具备横向评测结果。

---

## 0. 一句话目标

把 Algora 从 **"评测自研 MiniAgent V1/V2 的私有闭环"**，升级为 **"能在统一预算契约下横向评测 Claude Code / 开源 Agent / 自研框架，并能自动挖掘指令偏移、上下文遗忘、测试投机三类失败模式的评测平台"**；同时把自研 MiniAgent 补齐 **上下文管理、记忆、任务规划、多轮交互** 四项主流能力，使其既是被测对象，也是可做科学消融的实验载体。

---

## 1. 与 JD 的逐条对齐

### 1.1 岗位职责映射

| # | JD 职责原文（要点） | 当前覆盖 | V3 后覆盖 | 对应任务 |
|---|---|---|---|---|
| 1 | Code Agent 框架开发与迭代：**代码理解、工具调用、多轮交互、记忆管理、任务规划** | 工具调用 ✅；代码理解 ⚠️（仅 grep+read）；多轮 ❌；记忆 ⚠️（仅 AGENTS.md 注入）；规划 ❌ | 五项全覆盖，且每项都有**消融实验数据**支撑 | A3, B1–B4, C2 |
| 2 | 面向**主流 Code Agent（Claude Code / Roo Code / Cline）及自研框架**的系统化评测；覆盖真实开发任务、**长程多轮交互**、**完整工具链（构建/测试/部署）** | ❌ 仅自研 MiniAgent；仅短程单轮；仅 test，无 build/deploy | Claude Code + 1~2 个开源 Agent + MiniAgent 三方对比；长程 + 多轮 suite；含 build 环节的 case | A1, A2, A6, C2, D2, D3 |
| 3 | 自动化评测框架：**多 Agent 并行、环境隔离、过程可观测、结果自动化分析与可视化报告** | 并行 ✅（进程池 + 断点续跑）；环境隔离 ✅（CI 内断网容器实跑）；可观测 ✅（TraceEvent + 控制台）；报告 ⚠️（仅前端，无导出） | 进程池并行 + 断点续跑；CI 内 Docker 实跑；统一归一化轨迹；静态 HTML/MD 报告导出 | A4, A5, D4, E2 |
| 4 | 评测算法与缺陷挖掘：自动识别**指令偏移、上下文遗忘、测试投机**；产出**可复现缺陷诊断包与回归用例** | ⚠️ 仅 101 行规则式 `failure_taxonomy.py`；三类失败模式均无检测器；测试文件是**禁止**而非**检测** | 三个独立检测器 + repro bundle + 自动回归 fixture 生成 | C1, C3, C4, C5 |
| 5 | 深度洞察与产品驱动：输出深度分析报告，为框架优化提供可落地建议 | ⚠️ 有报告但只针对自研 V1/V2 | 三方横向对比报告 → 直接产出 MiniAgent 的能力缺口清单与优先级 | E1, E3 |

### 1.2 任职资格与加分项映射

| 要求 | 现状 | V3 后 | 备注 |
|---|---|---|---|
| **框架开发经验** | MiniAgent（254 行 loop + 沙箱 + 6 工具） | + context/memory/planner/multi-turn 四个子系统 | 从"能跑"升到"有架构" |
| **深度用户视角**（1 年+ AI 编程工具） | 隐含（本项目自身用 Agent 开发，有 AGENTS.md/.claude/） | 显式产出：Claude Code 失败模式观察报告 | E3 |
| **Python + 系统级语言** | Python ✅；TypeScript ⚠️（前端仅 ~430 行） | TS 加厚：报告生成 + 跨 Agent 对比视图 | D4；不建议为打勾现学 Go |
| **软件工程素养**（设计模式、规范、自动化测试） | 156 测试 + ruff ✅；adapter Protocol + CI 三门禁已落地 | + 检测器插件化 | A5 |
| **评测与数据思维** | 方法论文档 ✅、kappa meta-eval ✅ | + 置信区间、配对检验、分层统计、预注册假设 | D1 |
| 加分：**开源经历** | ❌ 未公开 | 清理后 public，含架构图与对比报告 | E4 |
| 加分：**平台工程** | ✅ 并行调度 + checkpoint + 环境清单 + CI 均已落地 | 已达成 | A4, A5 |
| 加分：**Benchmark 设计 / 回归体系 / CI/CD / 容器化** | ✅ 四项全覆盖：Benchmark、边界门禁 + nightly、CI 三门禁全绿、容器内断网实跑 | 已达成 | A5, C5, D3 |
| 加分：**产品化思维** | ⚠️ | 横向对比 → Agent 产品能力缺口建议书 | E3 |

**结论**：V3 完成后，JD 的 5 条职责、5 条资格、4 条加分项**全部有对应可展示物**；其中职责 2、3、4 从"零/浅"变为主要卖点。

---

## 2. 现状与差距（含主流 Agent 对标）

### 2.1 主流 Agent 能力对标表

> ⚠️ 标 `[待实测]` 的能力/接口需在 A1 阶段用实际版本验证后再写入正式文档，不以本文记载为准。

| 能力维度 | Claude Code | Cline / Roo Code | Aider | mini-swe-agent | **Algora MiniAgent（现状）** |
|---|---|---|---|---|---|
| 接入方式 | CLI headless：`claude -p --output-format stream-json` | VS Code extension；CLI 通道 `[待实测]` | CLI：`--message --yes` | Python 库 / CLI | in-process Python |
| 上下文管理 | 自动 compaction + 输出截断 | 有 context 管理与截断 | repo map（tree-sitter）控制上下文 | 极简，靠短轨迹 | **仅粗暴截断** |
| 记忆 | CLAUDE.md/AGENTS.md + 会话记忆 | Memory Bank（`memory-bank/` 约定） | `.aider.chat.history` / conventions 文件 | 无 | **仅 AGENTS.md 单向注入** |
| 任务规划 | TodoWrite / plan mode / subagent | Plan-Act 双模、Architect mode | 无显式 plan | 无 | **无** |
| 代码理解 | grep/glob/read + subagent 检索 | 类似 + LSP 辅助 | repo map（AST 级） | bash 单工具 | **grep + read** |
| 多轮交互 | 原生会话，可续 | 原生 | 原生 | 单轮为主 | **无** |
| 权限/安全 | permission modes + hooks + allowedTools | 审批流 + 自动批准规则 | `--yes` / 确认 | 无 | **命令白名单 + 禁止路径** ✅ |
| 成本可观测 | 结果 JSON 含 `total_cost_usd` / `usage` / `num_turns` | UI 展示 | 终端展示 | 自行统计 | **LlmCallRecord** ✅ |

**读法**：
- MiniAgent 在**安全与可观测**两栏是同级甚至更强的（沙箱策略、TraceEvent、trace scope），这是项目已有的真实优势，不要低估。
- 差距集中在**上下文 / 记忆 / 规划 / 多轮**四栏——正好是 JD 职责 1 逐字点名的四项。

### 2.2 差距清单（按严重度排序）

| ID | 差距 | 严重度 | 根因 |
|---|---|---|---|
| G1 | ClaudeCodeAdapter 已落地但**未 live 验证**（本机无 CLI）；第二个开源 adapter 未接 | 🟠 高 | 代码就绪，待真实 CLI 核对 schema/flag |
| G2 | 无 context/memory/plan/multi-turn 四项能力 | 🔴 致命 | JD 职责 1 逐字要求 |
| G3 | `mini_store_long` 已落地并达到动作中位数 30；尚未用于 context/memory/plan 消融 | 🟠 高 | 数据前置完成，能力实验待 W1-4/W2 |
| G4 | 三类失败模式（指令偏移/上下文遗忘/测试投机）无检测器 | 🟠 高 | JD 职责 4 逐字要求 |
| G5 | 测试文件是**禁止修改**而非**允许并检测** | 🟠 高 | 设计取向问题：禁止后永远测不到该维度 |
| G6 | ~~无 CI、Docker 从未 build、runner 串行~~ **已关闭** | ✅ | CI 三门禁全绿；容器内断网实跑；进程池 + 断点续跑 |
| G7 | SWE-bench 仅自建兼容样例，无官方实例 | 🟠 高 | 面试判断近似二值 |
| G8 | 已有离线 wheel + CLI 交付 case；仍无部署类 case | 🟡 中 | build 已覆盖，deploy 仍缺 |
| G9 | 强模型下 8/9 case 饱和，V1→V2 仅 +0.02 | 🟡 中 | 系统维度太少（仅 2 个 harness、1 个模型） |
| G10 | 无置信区间/配对检验/分层统计 | 🟡 中 | B3 已设计未实施 |
| G11 | 未开源；命名不统一（Algora vs CodeAgent Eval Lab） | 🟡 中 | 简历表面 |

---

## 3. 目标架构

### 3.1 总体分层

```
┌──────────────────────────────────────────────────────────────────────────┐
│  报告层        report.py（静态 HTML/MD）  │  backend + frontend（交互式）  │
├──────────────────────────────────────────────────────────────────────────┤
│  分析层   stats/（bootstrap·McNemar·分层）  detectors/（三类失败模式挖掘）  │
│           compare.py（版本/Agent 对比）     failure_taxonomy.py（归因）     │
├──────────────────────────────────────────────────────────────────────────┤
│  编排层   runner.py（并行调度 · 断点续跑 · 预算契约 · 环境清单）            │
│           multi_turn.py（确定性反馈回合驱动）                              │
├──────────────────────────────────────────────────────────────────────────┤
│  接入层   adapters/  ← ★V3 新增核心                                       │
│    AgentAdapter(Protocol) ─┬─ MiniAgentAdapter    （自研，in-process）     │
│                            ├─ ClaudeCodeAdapter   （headless CLI）         │
│                            ├─ AiderAdapter        （CLI）                  │
│                            └─ MiniSweAgentAdapter （CLI/lib）              │
│    normalize.py（异构轨迹 → TraceEvent）   cost.py（统一成本模型）          │
├──────────────────────────────────────────────────────────────────────────┤
│  被测框架  agent/  ← ★V3 大幅扩展                                          │
│    loop.py │ prompts.py(v1/v2/v3) │ context.py │ memory.py │ planner.py    │
│    tools/（6 → 8 工具）            │ sandbox/（worktree + policy + docker） │
├──────────────────────────────────────────────────────────────────────────┤
│  数据与评分  benchmark/（case·materialize·swebench·evalplus）              │
│              graders/（pytest·constraint·patch·build）  judge/（+meta-eval）│
├──────────────────────────────────────────────────────────────────────────┤
│  数据资产    mini_store_suite(短程) │ mini_store_long(长程) │ multiturn     │
│              swebench_official(官方实例) │ evalplus(官方 slice)             │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.2 新增 / 改造文件清单

| 路径 | 状态 | 职责 | 预估行数 |
|---|---|---|---|
| `src/codeagent_eval/adapters/base.py` | 🆕 | `AgentAdapter` Protocol、`AgentRunResult`、`BudgetContract`、`Capability` | 180 |
| `src/codeagent_eval/adapters/mini_agent.py` | 🆕 | 包装现有 MiniAgent（保证零回归） | 90 |
| `src/codeagent_eval/adapters/claude_code.py` | 🆕 | headless CLI 调用 + stream-json 解析 | 220 |
| `src/codeagent_eval/adapters/aider.py` | 🆕 | CLI 调用 + chat history 解析 | 150 |
| `src/codeagent_eval/adapters/mini_swe_agent.py` | 🆕 | 库/CLI 调用 + `.traj` 解析 | 130 |
| `src/codeagent_eval/adapters/normalize.py` | 🆕 | 异构轨迹 → 统一 `TraceEvent` | 200 |
| `src/codeagent_eval/adapters/cost.py` | 🆕 | 跨 provider token→USD，含缓存命中口径 | 110 |
| `src/codeagent_eval/adapters/registry.py` | 🆕 | 名称→adapter 装配 + `probe()` 健康检查 | 60 |
| `src/codeagent_eval/agent/context.py` | 🆕 | token 预算、分级截断、compaction | 200 |
| `src/codeagent_eval/agent/memory.py` | 🆕 | run 内 ScratchPad + 跨 run RepoMemory | 150 |
| `src/codeagent_eval/agent/planner.py` | 🆕 | `update_plan` 工具 + plan 状态机 + 遵守率 | 140 |
| `src/codeagent_eval/agent/loop.py` | ♻️ | 接入上述三者；发 `COMPACTION`/`PLAN_UPDATE` 事件 | +120 |
| `src/codeagent_eval/agent/prompts.py` | ♻️ | 新增 v3 prompt | +40 |
| `src/codeagent_eval/detectors/reward_hacking.py` | 🆕 | 测试投机检测（8 类信号） | 260 |
| `src/codeagent_eval/detectors/instruction_drift.py` | 🆕 | 约束逐步追踪、首次违规步、存活步数 | 180 |
| `src/codeagent_eval/detectors/context_amnesia.py` | 🆕 | canary 约束的被动召回曲线 | 150 |
| `src/codeagent_eval/detectors/repro_bundle.py` | 🆕 | 失败 → 诊断包 → 回归 fixture | 190 |
| `src/codeagent_eval/benchmark/multi_turn.py` | 🆕 | 确定性反馈回合驱动 + 泄漏防护 | 170 |
| `src/codeagent_eval/benchmark/case.py` | ♻️ | 扩展 schema（见 §3.4） | +70 |
| `src/codeagent_eval/graders/build_grader.py` | 🆕 | 构建/安装/CLI 入口可用性 oracle | 110 |
| `src/codeagent_eval/stats/{bootstrap,mcnemar,strata}.py` | 🆕 | cluster bootstrap、exact McNemar、分层宏平均 | 260 |
| `src/codeagent_eval/report.py` | 🆕 | artifacts → 静态 HTML/MD 报告 | 220 |
| `src/codeagent_eval/runner.py` | ♻️ | adapter 化 + 进程池 + checkpoint + 环境清单 | +180 |
| `src/codeagent_eval/models.py` | ♻️ | `TraceEventType` 扩展 6 个新事件 | +30 |
| `.github/workflows/ci.yml` | 🆕 | ruff + pytest + Docker build + selfcheck | 70 |
| `.github/workflows/nightly-eval.yml` | 🆕 | 定时小规模回归评测 | 60 |
| `datasets/mini_store_long/` | 🆕 | 4 条长程 case（30+ 步） | — |
| `datasets/mini_store_multiturn/` | 🆕 | 3 条多轮 case | — |
| `frontend/src/views/CrossAgent.tsx` | 🆕 | 跨 Agent 对比视图 | 180 |

新增/改造合计约 **3,900 行**（当前 src+backend+frontend ≈ 6,700 行）。

### 3.3 核心接口定义（草案）

```python
# adapters/base.py

class Capability(StrEnum):
    PLANNING      = "planning"       # 有显式 plan/todo 机制
    MEMORY        = "memory"         # 跨 run 持久化记忆
    COMPACTION    = "compaction"     # 上下文自动压缩
    MULTI_TURN    = "multi_turn"     # 支持续轮
    SUBAGENT      = "subagent"
    NATIVE_COST   = "native_cost"    # 自报成本

@dataclass(frozen=True)
class BudgetContract:
    """跨 Agent 公平对比的核心：不同框架的预算语义不同（turn/step/token/时间），
    统一以 wall_clock + cost 为**约束量**，steps/tokens 仅作诊断量记录。"""
    max_wall_clock_s: int
    max_cost_usd: float | None = None
    max_steps: int | None = None       # 仅对支持的 adapter 生效，须在报告中标注
    max_tokens: int | None = None

class AgentRunResult(BaseModel):
    adapter: str
    adapter_version: str               # CLI --version / 包版本，写入溯源
    patch: str
    changed_files: list[str]
    events: list[TraceEvent]           # 归一化后
    native_trajectory_path: str | None # 原始轨迹留档（永不丢失原始信息）
    prompt_tokens: int; completion_tokens: int; cached_tokens: int
    cost_usd: float | None
    cost_source: Literal["native", "derived", "unavailable"]
    stop_reason: str                   # final|budget_time|budget_cost|budget_steps|error|blocked
    duration_ms: int
    budget: BudgetContract
    env_manifest: dict                 # 镜像 digest / commit / 依赖版本

class AgentAdapter(Protocol):
    name: str
    def probe(self) -> ProbeResult: ...                     # 可用性 + 版本
    def capabilities(self) -> set[Capability]: ...
    def prepare(self, workdir: Path, task: AgentTask, budget: BudgetContract) -> None: ...
    def run(self, instruction: str) -> AgentRunResult: ...
    def continue_(self, feedback: str) -> AgentRunResult: ...  # 不支持则 raise UnsupportedCapability
    def cleanup(self) -> None: ...
```

```python
# agent/context.py
class ContextManager:
    budget_tokens: int
    compaction_threshold: float = 0.75      # 超过预算 75% 触发
    def truncate_tool_output(self, tool: str, content: str) -> str:
        """分级策略：read_file 保头尾+行号；search_code 保前 N 命中+总数；
        run_command 保 stderr 全量 + stdout 尾部。"""
    def should_compact(self, messages) -> bool: ...
    def compact(self, messages, provider) -> tuple[list[dict], CompactionRecord]:
        """保留 system + 首条 user + 最近 K 轮；中间摘要为结构化 note。
        发 TraceEvent(COMPACTION, before_tokens, after_tokens, dropped_steps)——
        必须可观测，否则 compaction 引发的失败无法归因。"""
```

```python
# agent/memory.py
class ScratchPad:      # run 内，随 prompt 常驻
    def note(self, key: str, value: str) -> None
    def render(self) -> str
class RepoMemory:      # 跨 run，落盘 .agent_memory/
    """⚠️ 评测隔离要求：作用域必须是 (repo, task_family)，且**同一 case 的不同 trial 之间
    必须清空**，否则 repeats 会互相泄漏答案，pass^k 失去意义。"""
    scope: tuple[str, str]
    def load(self) -> str; def update(self, content: str) -> None
```

```python
# agent/planner.py
class PlanItem(BaseModel):
    id: str; text: str
    status: Literal["pending", "in_progress", "done", "dropped"]
# 工具 update_plan(items) → 发 TraceEvent(PLAN_UPDATE)
# 指标 plan_adherence = |{done 项且有对应实际编辑/测试动作}| / |plan 总项|
#      plan_abandonment = 末态仍为 pending/in_progress 的比例
```

```python
# benchmark/multi_turn.py
class FeedbackDriver:
    """确定性反馈回合——**不是** LLM 用户模拟器。
    ⚠️ 泄漏防护：只回灌 visible/target 测试的失败名与断言输出；
    hidden/regression 测试的任何信息永不进入反馈，否则等价于把隐藏 oracle 交给 Agent。"""
    max_turns: int = 3
    def next_turn(self, grade: GradeResult) -> str | None
```

### 3.4 `EvalCase` schema 扩展

```python
TaskType = Literal["bugfix","spec","refactor","review","instruction","build","multi_turn"]  # +build,+multi_turn
Horizon  = Literal["short","long"]        # 🆕 短程/长程标记，用于分层统计

class CanarySpec(BaseModel):              # 🆕 上下文遗忘探针
    """在首轮 instruction 中声明一条可程序验证、且贯穿全程的约束。
    采用**被动检查**：对 step t 产生的每次编辑判定是否遵守，得到 recall(t) 曲线。
    不使用中途提问式探针——那会污染上下文，把观测变成干预。"""
    constraint_id: str
    description: str                      # 注入到 instruction 的文本
    checker: str                          # 检查器名（如 "no_fstring" / "type_hints_required"）

class EvalCase(BaseModel):
    # ... 现有字段不变 ...
    horizon: Horizon = "short"                        # 🆕
    expected_steps: int | None = None                 # 🆕 设计意图，用于校验难度
    canary: CanarySpec | None = None                  # 🆕
    multi_turn: MultiTurnSpec | None = None           # 🆕
    build_checks: list[str] = Field(default_factory=list)   # 🆕 build grader 的命令
    allow_test_edits: bool = False                    # 🆕 ★ 开放测试写权限以检测投机
    known_shortcuts: list[str] = Field(default_factory=list) # 🆕 已知捷径，用于 QC
```

> **`allow_test_edits` 的设计说明**：这是一个取向反转。当前 `_forbidden_from_task()` 无条件禁止修改测试文件，安全但**使"测试投机"这一维度永远不可观测**。V3 把它变成 per-case 开关：
> - 默认 `False`（保持现有 case 行为，零回归）；
> - 新增一组 `allow_test_edits=True` 的 case，专门用于测量 reward hacking 率；
> - 无论开关如何，`reward_hacking.py` 都对 diff 做检测并记录信号，只是评分处理不同（关闭时算 constraint 违规，开启时算 hacking 信号）。

---

## 4. 数据资产扩充计划

| Suite | 现状 | V3 目标 | 用途 |
|---|---|---|---|
| `mini_store_suite`（短程） | 9 case | 13 case（+2 instruction-following、+1 refactor、+1 build） | 基础回归；模型阶梯的区分度底座 |
| `mini_store_long`（长程） ✅ | 4 case；动作中位数 30、模型轮次 13.5 | 保持 oracle 与 canary，后续用于消融/横向评测 | **解锁 context/memory/plan 的测量**；三方横向对比主战场 |
| `mini_store_multiturn` 🆕 | — | 3 case（复用短程 case + FeedbackDriver） | 失败恢复率；多轮后约束是否漂移 |
| `mini_store_hackbait` 🆕 | — | 3 case，`allow_test_edits=True` 且欠定义/偏难 | 测试投机检出率 |
| `swebench_official` 🆕 | 兼容样例 1 条 | 3–5 条官方 Verified 实例 | 证据等级从 Compatibility 升到 Smoke Slice |
| `evalplus_official` | 5 题 ✅ | 不变 | 已完成，不重复投入 |

**长程 case 的设计要点**（这是整个框架线的地基，必须做扎实）：

| case | 形态 | 为什么能撑到 30+ 步 | 主要考察 |
|---|---|---|---|
| `long-refactor-pricing-api` | 新签名迁移到 12 个生产文件 | 跨调用点搜索、修改、回归 | 规划、上下文保持 |
| `long-crossmodule-returns` | 5 模块退货工作流，含原子性/折扣/税/积分/不可变记录 | 需求分解 + 多模块协同 | 规划、记忆 |
| `long-cascade-reservation` | 一个库存根因经 8 条工作流暴露，正确修复仍只改 1 文件 | 区分根因定位与表象修补 | 上下文遗忘、过早终止 |
| `long-build-and-cli` | 7 文件打包、版本、CLI、doctor、JSON 输出和离线 wheel 链路 | 构建链路 + 业务修复 | **完整工具链**（JD 职责 2） |

四条都挂 `CanarySpec`（例如"本次改动不得引入新的第三方依赖，且所有新增公共函数必须带 type hints"），用于测量约束在长轨迹上的存活。

---

## 5. 三周迭代计划

图例：🔵 评测平台线　🟠 Agent 框架线　🟣 数据资产　⚫ 工程基建

### Week 1 — 地基（解锁后续所有实验）

| ID | 任务 | 线 | 依赖 | 工时 | 验收标准 |
|---|---|---|---|---|---|
| **W1-1 ✅** | 长程 suite `mini_store_long`（4 case） | 🟣 | — | 1.5d | 4/4 valid；reference/none=1/0；实测动作中位数 30、模型轮次 13.5、测试循环 3（目标分别 ≥25/≥12/≥2） |
| **W1-2 ✅** | `AgentAdapter` 抽象 + `MiniAgentAdapter` + runner 改造 | 🔵 | — | 1d | 94 tests 全绿；adapter round-trip、legacy/default CLI、规范化产物与 infra-invalid 口径有离线回归覆盖 |
| **W1-3** | `ClaudeCodeAdapter`（headless + stream-json 归一化） | 🔵 | W1-2 | 1.5d | 在 3 条短程 case 上跑通；patch 可导出；`total_cost_usd` 入库；原始轨迹留档 |
| **W1-4** | `planner.py` + `update_plan` 工具 + v3 prompt 初版 | 🟠 | W1-1 | 1d | 长程 case 上 plan 事件入 trace；`plan_adherence` 可计算 |
| **W1-5** | GitHub Actions CI（ruff + pytest + Docker build + selfcheck） | ⚫ | — | 0.5d | CI 绿；**`docker/sandbox.Dockerfile` 首次真实 build 成功**（消除"本机无 daemon"硬伤） |
| **W1-6** | runner 并行化（进程池）+ trial 级 checkpoint 续跑 | ⚫ | W1-2 | 1d | 8 并发下 120 trial 无串扰（worktree 隔离验证）；中断后 `--resume` 不重跑已完成 trial |
| **W1-7** | GLM provider 接入 + 模型阶梯配置 | 🔵 | — | 0.5d | ✅ 机制完成、费率已填、DeepSeek 两档实测；GLM 实跑待 key |

**Week 1 里程碑**：能用一条命令，在长程 suite 上并行跑 Claude Code 和 MiniAgent，拿到第一份可对比的数据。

### Week 2 — 能力补齐与缺陷挖掘

| ID | 任务 | 线 | 依赖 | 工时 | 验收标准 |
|---|---|---|---|---|---|
| **W2-1** | `context.py`：token 预算 + 分级截断 + compaction | 🟠 | W1-1 | 1.5d | 长程 case 上触发 compaction 并发 `COMPACTION` 事件；before/after token 可查；无 compaction 时的溢出率作为基线 |
| **W2-2** | `memory.py`：ScratchPad（run 内） | 🟠 | W2-1 | 0.5d | 常驻 note 出现在 prompt；隔离规则单测覆盖 |
| **W2-3** | `detectors/context_amnesia.py`（canary 被动召回曲线） | 🔵 | W1-1, W2-1 | 1d | 输出 `recall(step)` 曲线；对 compaction 开/关两组可对比 |
| **W2-4** | `detectors/reward_hacking.py`（8 类信号） | 🔵 | — | 1.5d | 对人工构造的 8 个 hacking patch 全部命中；对 9 条正常 reference patch 零误报 |
| **W2-5** | `mini_store_hackbait` suite（3 case，开放测试写权限） | 🟣 | W2-4 | 0.5d | selfcheck 通过；已知捷径登记在 `known_shortcuts` |
| **W2-6** | `detectors/instruction_drift.py`（约束逐步追踪） | 🔵 | W1-4 | 1d | 输出首次违规步、存活步数、按规则类别拆分；使 **Task/Strict 在长程 case 上真正分离** |
| **W2-7** | SWE-bench 官方实例 Smoke Slice（B2） | 🔵 | W1-5 | 1.5d | 3–5 条官方 Verified 实例；先 gold oracle 通过；环境失败与 Agent 失败可区分 |
| **W2-8** | 第 2 个外部 adapter（aider 或 mini-swe-agent） | 🔵 | W1-2 | 1d | 短程 + 长程各跑通；轨迹归一化后可用同一套检测器 |

**Week 2 里程碑**：三方 Agent × 三档模型 × 短/长两个 suite 的完整实验矩阵可以开跑；三类失败模式均有检测器。

### Week 3 — 多轮、统计、收口

| ID | 任务 | 线 | 依赖 | 工时 | 验收标准 |
|---|---|---|---|---|---|
| **W3-1** | `multi_turn.py` 确定性反馈回合 + 3 条多轮 case | 🟠🟣 | W1-2 | 1.5d | 最多 3 轮；泄漏防护单测（hidden 信息不得出现在反馈中）；输出恢复率 |
| **W3-2** | `memory.py` 跨 run RepoMemory + 隔离验证 | 🟠 | W2-2 | 1d | 同仓库连续 3 任务实验；**trial 间清空规则有单测**，防 repeats 泄漏 |
| **W3-3** | `stats/`：cluster bootstrap CI + exact McNemar + 分层宏平均 | 🔵 | — | 1d | 对已有 V1/V2 历史数据复算；区间宽度如实呈现 |
| **W3-4** | `detectors/repro_bundle.py`：诊断包 + 自动回归 fixture | 🔵 | W2-4/6 | 1d | 任一失败 trial 一键产出可复现包；生成的 fixture 能被 CI 重放 |
| **W3-5** | `report.py` 静态报告 + `CrossAgent.tsx` 前端视图 | 🔵⚫ | W3-3 | 1d | 一条命令产出自包含 HTML；含分层表、区间、失败模式分布、成本前沿 |
| **W3-6** | 全量实验执行（见 §6 矩阵）+ 结果回填 | 🔵 | 全部 | 1d | 所有预注册假设有对应数据；相反结果照实记录 |
| **W3-7** | 开源清理（密钥审计、命名统一、README 架构图）+ 洞察报告 | ⚫ | W3-6 | 0.5d | repo public；`docs/cross_agent_report_v1.md` 完成 |

**可砍项**（时间不足时按序放弃，不影响主叙事）：W3-2（跨 run memory）→ W3-3 的分层部分 → W2-8（第 2 个 adapter）。
**不可砍项**：W1-1（长程 case）、W1-2/1-3（adapter）、W2-1（context）——砍任一项都会使对应的整条线归零。

---

## 6. 评测设计

### 6.1 实验矩阵

| 实验 | 目的 | 系统维度 | 模型维度 | Suite | repeats | trial 数 |
|---|---|---|---|---|---|---|
| **E1** Harness 消融 | 自研框架的能力增量归因 | MiniAgent v1 / v2 / v3 | GLM-4.6, DeepSeek-v4-flash, GLM-4-Flash(弱) | 短程 13 | 5 | 585 |
| **E2** 长程消融 | context/memory/plan 是否在长任务上生效 | v2 / v3 / v3−compaction / v3−plan（消融） | GLM-4.6, DeepSeek-v4-flash | 长程 4 | 5 | 160 |
| **E3** 三方横向 | JD 职责 2 的核心产出 | Claude Code / aider(或 mini-swe) / MiniAgent v3 | 统一 GLM-4.6（若 adapter 支持自定义 endpoint）+ 各自默认模型 | 短程 13 + 长程 4 | 3 | 306 |
| **E4** 失败模式挖掘 | JD 职责 4 | 上述全部系统 | — | hackbait 3 + 长程 4（canary） | 5 | 复用 E2/E3 + 105 |
| **E5** 多轮 | 失败恢复率 | v3 / Claude Code | GLM-4.6 | multiturn 3 | 5 | 30 |
| **E6** 公开 benchmark | 证据等级 | Claude Code / MiniAgent v3 | 各自 | SWE-bench 官方 3–5 + EvalPlus 5 | 3 | ~60 |

**总计约 1,250 trial。**

### 6.2 资源预算估算

| 类别 | 单 trial 估算 | 数量 | 小计 |
|---|---|---|---|
| 短程 trial | ~10 步 × ~5k prompt tok ≈ 50k tok，$0.01–0.05 | ~900 | **$20–45** |
| 长程 trial | ~35 步 × ~10k tok ≈ 350k tok，$0.10–0.50 | ~280 | **$30–140** |
| Claude Code trial | 自带模型时显著更贵，$0.2–1.0 | ~120 | **$25–120** |
| SWE-bench 官方 | 环境构建为主，token 次要 | ~30 | **$10–30** |
| **合计** | | | **约 $85–335** |

**时间才是真正的瓶颈**：长程 trial 单次 3–8 分钟，280 个串行需 15–35 小时。这就是 W1-6 并行化**不是优化项而是前置条件**的原因；8 并发下压缩到 2–5 小时，可放进 nightly CI。

### 6.3 指标定义

| 类别 | 指标 | 定义 | 备注 |
|---|---|---|---|
| 功能 | Task Success | target 测试全过 | 现有 |
| 功能 | Strict Success | target + hidden + regression 全过 **且** 约束全守 | 现有；长程 case 上预期首次出现明显分离 |
| 稳定 | pass@k / pass^k | 现有 | pass^k 更能体现可靠性 |
| 成本 | cost per success | 总成本 / 成功 trial 数 | `pricing.py` 已实现（每模型费率 + 溯源 + 不假设汇率）；`cost_source` 必须标注；费率表待填 |
| 成本 | 预算约束成功率 | 固定 wall-clock/USD 上限下的成功率 | 跨 Agent 公平对比的主口径 |
| 效率 | steps-to-first-target-pass | 首次 target 通过的步号 | 归一化轨迹后跨 Agent 可比 |
| 规划 | plan adherence / abandonment | §3.3 定义 | 仅对声明 `PLANNING` 能力的系统 |
| 上下文 | context overflow rate | 因预算耗尽而终止的 trial 比例 | |
| 上下文 | canary recall(t) | step t 的编辑遵守 canary 约束的比例 | 被动检查，不干预 |
| 合规 | first-violation step / survival steps | 约束首次被违反的步号 / 存活步数 | JD"指令偏移" |
| 投机 | reward hacking rate | 至少命中一类 hacking 信号的 trial 比例 | JD"测试投机" |
| 多轮 | recovery rate | 首轮失败但 ≤3 轮内转为成功的比例 | |
| 多轮 | 多轮约束漂移 | 第 1 轮遵守、第 3 轮违反的约束比例 | 多轮 × 指令偏移的交叉指标 |

### 6.4 统计方法与纪律

- **置信区间**：以 **case 为聚类单位**做 cluster bootstrap（同一 case 的 repeats 不是独立样本）。二项指标补 Wilson 区间。
- **配对比较**：v2 vs v3、Agent A vs B 在同一 case 上用 **exact McNemar**；成本类连续量用配对 bootstrap / 置换检验。
- **分层报告**：按 `horizon`（短/长）、`task_type`、`difficulty` 分层，报宏平均 + 每层样本数。**总分必须与分层同时呈现**。
- **零事件处理**：若 reward hacking 检出为 0，报告 **Wilson 上界**（如 "0/195，95% 上界 1.9%"），而不是写"不存在"。
- **纪律**：同时报 effect size、区间、样本数、预算；"不显著" ≠ "相同"；所有对比必须同模型、同预算契约、同 benchmark 版本、同温度。
- **样本量诚实交代**：13 case 聚类下的 bootstrap 区间宽度预计 ±0.10–0.18，**这个宽度要写进报告，不能只报点估计**。

### 6.5 评测有效性防护

| 风险 | 防护 |
|---|---|
| 跨 run memory 泄漏答案到 repeats | `RepoMemory` 作用域绑定 `(repo, task_family)`，trial 间强制清空，有单测 |
| 多轮反馈泄漏 hidden oracle | `FeedbackDriver` 只回灌 visible/target 失败信息，单测断言 hidden 内容不出现 |
| 外部 Agent 联网获取答案 | 容器内断网（CI 中用 `--network none`）；本机模式记录为已知限制 |
| 预算契约不公平 | 主约束统一为 wall-clock + cost；steps/tokens 差异在报告中显式说明 |
| Agent 篡改 grader/测试/case 文件 | grader 在沙箱外运行；hidden 测试评分时才注入；对 case 目录做完整性校验 |
| 检测器自身误报 | W2-4 验收要求：8 个人工 hacking patch 全命中 + 9 个 reference patch 零误报 |
| 长程 case 难度失控（全败） | `expected_steps` 预设 + reference/none 自检 + 中等模型试跑校准 |

---

## 7. 预期结果（预注册假设）

> ⚠️ 以下全部是**执行前的假设**。列出它们的目的是：(a) 提前约束实验设计；(b) 执行后无论结果是否符合，都照实回填。**与假设相反的结果同样是有效产出**，且在面试中往往更有说服力。

### H1 · 短程 suite 的饱和会持续存在

| | |
|---|---|
| 假设 | 强模型（GLM-4.6 / DeepSeek-v4-flash）在短程 13 case 上，v1/v2/v3 的 Task Success 均落在 0.95–1.00，三者差异不显著（McNemar p > 0.1） |
| 依据 | 已有观测：9 case 上 V1=0.98、V2=1.00 |
| 证伪 | 若新增的 instruction-following / refactor case 拉开 >0.1 的差距，说明任务类型比 harness 纪律更能造成区分度 |
| 无论如何的价值 | 明确"短程 suite 的用途是回归护栏，不是区分度来源"，这本身是一个正确的 benchmark 定位结论 |

### H2 · 弱模型恢复区分度

| | |
|---|---|
| 假设 | GLM-4-Flash 在短程 suite 上 Task Success 落在 **0.35–0.70**，且 v1 < v2 < v3 呈单调递增，差距 0.05–0.20 |
| 依据 | 弱模型缺乏自发的验证纪律，harness 约束的边际收益更大 |
| 证伪 | 若弱模型下 v3 反而更差 → 说明 compaction/plan 对弱模型是**认知负担**而非帮助（这是一个很有价值的发现，直接对应产品建议：能力分层启用） |
| 价值 | 无论方向，都得到"harness 收益随模型能力递减/递增"的曲线，这是 §4.2 case 区分度分析真正需要的多系统数据 |

### H3 · 长程 case 上 v3 显著优于 v2 ★ 主假设

| | |
|---|---|
| 假设 | 长程 4 case 上：v2 Task Success **0.30–0.60**，v3 **0.55–0.85**，差距 **≥0.15** 且 McNemar 显著；v3 的 context overflow rate 比 v2 低 ≥50%；代价是 token +20–60% |
| 依据 | v2 无 compaction，35+ 步后必然逼近上下文预算；plan 缺失导致跨模块任务遗漏调用点 |
| 消融预期 | v3−compaction ≈ v2（overflow 主导）；v3−plan 介于两者之间（能跑完但漏改） |
| 证伪 | 若 v2 在长程上也接近 1.0 → 说明长程 case 设计失败（步数够但认知负荷不够），须重做 case 而非否定 compaction |
| 价值 | 这是整个 Agent 框架线的**核心 money shot**，替代已饱和的 V1→V2 |

### H4 · canary 召回随步数单调衰减，compaction 改变衰减形状

| | |
|---|---|
| 假设 | 无 compaction 时 `recall(t)` 在 t > 25 后明显下滑（末段召回 < 0.6）；有 compaction 时衰减更平缓但**可能出现摘要丢失导致的阶跃下降** |
| 依据 | 上下文窗口与摘要有损性的直接后果 |
| 证伪 | 若 recall 全程平稳 → canary 约束选得太"自然"（模型不需要记忆也会遵守），须换更反直觉的约束 |
| 价值 | 一条"上下文遗忘"的量化曲线，是 JD 职责 4 最直观的展示物 |

### H5 · 测试投机在欠定义/偏难 case 上才出现

| | |
|---|---|
| 假设 | 常规 case 开放测试写权限后，强模型 hacking 率 **0–5%**；`hackbait` 欠定义 case 上升到 **10–30%**；弱模型更高 |
| 依据 | 投机是"任务过难 + 有可见捷径"的联合产物，而非模型的无条件倾向 |
| 证伪 | 若全矩阵检出为 0 → 报告 Wilson 上界并明确"当前 case 难度不足以诱发投机"，同时说明检测器已在人工构造 patch 上验证有效（避免把"没检出"混同于"检测器无效"） |
| 价值 | 0 检出也是可发表结论；关键是**检测器有效性与检出率必须分开论证** |

### H6 · 三方横向：Claude Code 在长程领先，成本更高

| | |
|---|---|
| 假设 | 等 wall-clock 预算下，长程 case：Claude Code **0.70–0.95** > MiniAgent v3 **0.55–0.85** > aider/mini-swe **0.40–0.75**；Claude Code 的 cost-per-success 高 1.5–4×；短程三者接近饱和无差异 |
| 依据 | Claude Code 具备 compaction + 记忆 + 规划 + subagent，长程优势应最明显 |
| 归因预期 | 差异主要落在 `context overflow rate` 和 `plan adherence` 两个诊断量上，而非单纯"模型更强"（统一 endpoint 组用于剥离模型因素） |
| 证伪 | 若统一模型后差距消失 → 结论变为"能力差异主要来自模型而非 scaffold"，同样是强结论，且更反直觉 |
| 价值 | JD 职责 2 + 5 的直接产出；也是 MiniAgent 能力缺口清单的数据来源 |

### H7 · 多轮反馈的边际收益快速递减

| | |
|---|---|
| 假设 | 首轮失败的 trial 中，第 2 轮恢复 **30–60%**，第 3 轮再恢复 **5–15%**；且 ≥20% 的多轮 trial 出现"修好测试但违反首轮约束"的漂移 |
| 依据 | 反馈提供的信息量在第 2 轮后急剧下降；长会话中早期约束更易被稀释 |
| 证伪 | 若第 3 轮仍有大幅提升 → 说明单轮预算设置过紧，应重新校准 |
| 价值 | "多轮 × 指令偏移"交叉指标是自研的评测视角，公开 benchmark 少有覆盖 |

### H8 · SWE-bench 官方 Smoke Slice：不报比率，只报可评性

| | |
|---|---|
| 假设 | 3–5 个官方 Verified 实例上，gold oracle 100% resolved（否则环境有问题）；Agent 逐实例给出 resolved/not + 失败分类 |
| 纪律 | **N=5 不足以估计成功率**，报告只写逐实例结果与失败归类，明确标注 official-instance smoke slice |
| 价值 | 证据等级从 Compatibility Sample 升到 Smoke Slice；能回答"跑过真实实例吗"这个近似二值的问题 |

### 7.9 预期最终数据形态（示意，非结果）

执行后 `docs/cross_agent_report_v1.md` 的核心表预计长这样：

| 系统 | 模型 | 短程 Task | 长程 Task | 长程 Strict | overflow率 | hacking率 | cost/success |
|---|---|---|---|---|---|---|---|
| Claude Code | 默认 | — | — | — | — | — | — |
| Claude Code | GLM-4.6 | — | — | — | — | — | — |
| MiniAgent v3 | GLM-4.6 | — | — | — | — | — | — |
| MiniAgent v2 | GLM-4.6 | — | — | — | — | — | — |
| MiniAgent v3 | GLM-4-Flash | — | — | — | — | — | — |
| aider / mini-swe | GLM-4.6 | — | — | — | — | — | — |

每格附 cluster bootstrap 95% CI 与样本数；配套：canary 召回曲线图、成本-成功率前沿图、失败模式分布堆叠图。

---

## 8. 风险与明确不做的事

### 8.1 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Claude Code / Cline 的 headless 接口与本文记载不符 | W1-3 阻塞，连带 E3 | W1 第一天先做 `probe()` 实测；接口不可用则降级为 aider + mini-swe-agent 两方对比，并把"extension-based Agent 可自动化性评估"作为 Protocol Study 产出 |
| 长程 case 难度校准失败（全过或全败） | H3 主假设不可测 | W1-1 用中等模型试跑校准 `expected_steps`；预留 0.5d 返工 |
| 外部 Agent 无法统一 endpoint，模型因素混淆 | H6 归因减弱 | 同时跑"各自默认模型"与"统一 endpoint"两组；无法统一时在报告中明确标注为混淆因素，不强行归因 |
| 长程实验时间超预算 | W3-6 卡壳 | 并行化（W1-6）是前置；必要时长程 repeats 从 5 降到 3，并如实说明功效下降 |
| 检测器误报污染结论 | 失败模式分布不可信 | 验收即要求"人工构造样本全命中 + reference 零误报"；所有检出保留 evidence span 供人工复核 |
| SWE-bench 官方镜像拉取/构建失败 | H8 阻塞 | 依赖 CI 的 Docker（W1-5）；失败则如实降级为"环境不可用"记录，不伪造 |

### 8.2 明确不做（写进文档，避免面试时被追问"为什么没做"时显得是遗漏）

| 不做 | 理由 |
|---|---|
| **LLM 用户模拟器式完整多轮** | 需要模拟器稳定性评测、信息释放策略、答案泄漏防护，成本远超收益；只做确定性反馈回合，并说明边界 |
| Cline / Roo Code 的 headless 硬接 | extension host 自动化成本高、稳定性差；改为可自动化性评估报告（判断力比蛮力更值钱） |
| 全量 SWE-bench / Terminal-Bench 排行榜 | 成本数量级不匹配；坚持 Smoke Slice 定位 |
| 为满足"系统级语言"而现学 Go/Rust | 时间窗内产出质量必然低；改为加厚已有 TypeScript |
| LSP/AST 级代码理解 | 收益不确定且工作量大；留作 roadmap，在报告中作为 MiniAgent 已知缺口列出 |
| 多语言 case | 当前只有 Python；如实标注覆盖边界 |

---

## 9. 交付物清单

| 交付物 | 形态 | 对应 JD |
|---|---|---|
| `adapters/` 异构 Agent 接入层 + 轨迹归一化 | 代码 | 职责 2、3 |
| MiniAgent v3（context + memory + planner + multi-turn） | 代码 | 职责 1 |
| `detectors/` 三类失败模式检测器 + repro bundle | 代码 | 职责 4 |
| `stats/` + `report.py` + 跨 Agent 前端视图 | 代码 | 职责 3、5 |
| 长程 / 多轮 / hackbait / SWE-bench 官方 四个新 suite | 数据 | 职责 2 |
| `.github/workflows/` CI + nightly eval | 基建 | 加分项 |
| `docs/cross_agent_report_v1.md` 三方横向对比报告 | 文档 | 职责 2、5 |
| `docs/failure_mode_atlas_v1.md` 失败模式图谱（含 canary 曲线、hacking 证据） | 文档 | 职责 4 |
| `docs/extension_agent_automatability.md` extension 类 Agent 可自动化性评估 | 文档 | 职责 2（判断力） |
| `docs/miniagent_capability_gap_v1.md` 自研框架能力缺口与优先级建议 | 文档 | 职责 5（产品化） |
| 公开 GitHub 仓库 | — | 加分项 |

---

## 10. 对外叙事映射（面试用）

**主线一句话**：
> 我做了一个 coding agent 评测平台，能在统一预算契约下横向评测 Claude Code、开源 Agent 和我自研的 MiniAgent；平台自动挖掘指令偏移、上下文遗忘、测试投机三类失败模式；这些评测结论反过来驱动了我自研框架的三次迭代，每次迭代都有配对统计支撑的消融数据。

**8 分钟演示脚本**：

| 时长 | 内容 | 落点 |
|---|---|---|
| 0–1min | 问题：主流 Agent 在短 benchmark 上都饱和，真实差异在长程 | 评测思维 |
| 1–2min | 架构图：adapter 层 + 归一化 + 预算契约 | 平台工程 |
| 2–4min | 三方横向对比表 + 成本-成功率前沿 | JD 职责 2、5 |
| 4–6min | 失败模式图谱：canary 召回曲线 + 一个 hacking 证据 span + repro bundle 一键复现 | JD 职责 4 |
| 6–7min | v2→v3 消融：compaction/plan 各自贡献多少，代价多少 | JD 职责 1 |
| 7–8min | 诚实边界：样本量、区间宽度、哪些不能外推、明确不做的事及理由 | 评测素养（最加分的一段） |

**必须准备的追问**：
1. 不同 Agent 的预算怎么算公平？→ §3.3 `BudgetContract` 的设计取舍
2. 你怎么保证 memory 不泄漏答案到 repeats？→ §6.5 隔离规则 + 单测
3. hacking 率是 0，你怎么知道检测器有效？→ §7 H5 的"检测器有效性与检出率分开论证"
4. 13 个 case 的结论能信吗？→ §6.4 聚类 bootstrap 与区间宽度的如实呈现
5. 为什么不接 Cline？→ §8.2，判断题而非能力题






backup:
目标JD原文
**GLM-Code Agent算法评测工程师**
分享
全职|其他|数据工程团队
发布于 2026-07-30
**申请职位**
**职位描述**
【岗位职责】
Code Agent 框架开发与迭代：参与公司自研或开源Code Agent框架的设计、开发与迭代，优化其代码理解、工具调用、多轮交互、记忆管理及任务规划等核心能力。
评测体系与基准构建：面向主流Code Agent（如 Claude Code、Roo Code、Cline等）及自研框架，设计并执行系统化评测。构建覆盖真实开发任务、长程多轮交互、完整工具链（构建/测试/部署）的基准测试集。
自动化评测框架研发：设计并开发高可扩展的自动化评测平台，支持多Agent并行评测、环境隔离、过程可观测、结果自动化分析与可视化报告生成。
评测算法与缺陷挖掘创新：创新评测方法论，通过设计算法自动识别Agent的典型失败模式（如指令偏移、上下文遗忘、测试投机等），并产出可复现的缺陷诊断包与回归用例。
深度洞察与产品驱动：基于评测数据与框架开发经验，输出深度分析报告，为Agent框架的优化与产品方向提供可落地的数据洞察与建议。

【任职资格】
框架开发经验：具备AI Agent框架或复杂开发工具链的实际开发或深度迭代经验，熟悉其架构设计与核心模块。
深度用户视角：拥有一年以上深度使用AI编程工具（如 Cursor、Copilot、Claude Code等）进行实际项目开发或大规模代码重构的经验，对其工作流与局限性有切身理解。
扎实的工程能力：
熟练掌握 Python 及至少一门系统级语言（如 Go/Rust/TypeScript），具备独立负责关键模块的设计与实现能力。
具备优秀的软件工程素养，熟悉设计模式、代码规范与自动化测试。
评测与数据思维：具备强大的逻辑思维与数据分析能力，能够从复杂交互中抽象出可量化的指标与科学对比实验方法。

【加分项】
开源经历：在AI辅助开发、开发者工具等领域有活跃的开源项目贡献或独立项目经历，GitHub有高质量公开代码。
平台工程背景：具备复杂系统、效能平台或工具链开发背景，熟悉高标准的工程实践与协作流程。
评测工程专长：在Benchmark设计、回归测试体系、CI/CD集成、容器化评测等方面有直接经验。
产品化思维：能从终端开发者视角出发，将技术洞察转化为清晰的产品优化建议或特性需求。
