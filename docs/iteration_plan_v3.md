# Algora V3 迭代方案：从"自评闭环"到"异构 Agent 横向评测平台 + 有能力边界的自研框架"

本文是 Algora 下一轮（3 周）的完整迭代方案。它回答四个问题：**补什么、为什么这么补（与主流 Agent / JD 的对齐关系）、补完之后框架长什么样、要跑哪些评测以及预期结果是什么**。

- 上游文档：[`coding_agent_eval_plan_v2.md`](../coding_agent_eval_plan_v2.md)（原始设计）、[`benchmark_methodology_and_roadmap.md`](benchmark_methodology_and_roadmap.md)（benchmark 方法论）
- 状态文档：[`PROJECT_STATE.md`](../PROJECT_STATE.md)、[`TASKS.md`](../TASKS.md)
- 本文定位：**规划**。所有"预期结果"均为**预注册假设（pre-registered hypothesis）**，不是已得结论。执行后须以真实数据回填，并保留与假设相反的结果。

### 执行进度（2026-08-05）

| 周 | 已完成 | 部分完成 | 未完成 |
|---|---|---|---|
| **W1** | W1-1～W1-7（7/7）；长程 suite 后续从 4 扩到 8 case | — | — |
| **W2** | W2-1 context、W2-3 context amnesia、W2-4 reward hacking、W2-6 instruction drift（4/8） | — | W2-2 ScratchPad、W2-5 hackbait、W2-7 官方 SWE-bench、W2-8 第二外部 adapter |
| **W3** | W3-4 repro bundle | W3-3 统计核心、W3-6 部分实验、W3-7 README/横向报告 | W3-1 multi-turn、W3-2 RepoMemory、W3-5 静态报告/跨 Agent UI |

当前门禁：**360 passed / 1 skipped，Ruff 全绿，短/长 selfcheck 9/9 + 8/8；长程干净仓库 83 passed**。模型受控横向报告与 H3 消融仍基于原 4-case 矩阵；扩到 8 case 只提升了下一轮实验的统计设计，尚未自动提升既有结论的证据等级。

**执行约束更新（2026-08-05）**：W3-6 的 8-case 受控矩阵拆为 **W3-6a**，因 GLM API 无可用额度标记为外部阻塞。既有 4-case 结果不作废，也不以其他模型替跑后混入同一比较；原 GLM 端点恢复、preflight 通过且额度覆盖固定矩阵后继续。W3-4 repro bundle 已沿离线路径完成；后续顺序为 W3-5/W3-3 报告统计 → W3-1/W2-2 multi-turn 与 ScratchPad → W2-5 hackbait 基础设施。

#### 详细执行记录（保留历史时间点与假设修正）

- **W1-1 已完成**：`mini_store_long` 4/4 selfcheck，reference/none=1.0/0.0；正式 V2 校准 `v2-20260803T191808Z` 为 Task/Strict 1.00、工具动作中位数 30、模型轮次 13.5、测试运行 3。该数据是 n=1/case 的难度校准，不是稳定成功率结论。
- **W1-2 已完成**：AgentAdapter/MiniAgentAdapter、预算契约、能力探测、环境清单、归一化结果、runner adapter 路由和 infra-invalid 口径已落地；94 passed/1 skipped。
- 校准发现并修复 V2 将 token 截断空回复误判为 final 的缺陷；默认 2048 保留，长程校准显式使用 4096 并写入溯源。成本费率未配置，因此正式产物为 `null/unavailable`。
- **W1-3 已完成（代码层）**：`ClaudeCodeAdapter` + stream-json 归一化 + `normalize.py` 共享语义表；runner 支持 `--adapter claude_code`（外部 adapter 成为独立 agent 标签，不再折进 v1/v2 轴）；trial 目录自包含（原始轨迹 relocate 到 `rep<k>/native/`）。133 passed/1 skipped，ruff 全绿，两个 suite selfcheck 9/9 + 4/4。
- W1-3 期间发现并修复一个跨 Agent 归因缺陷：`failure_taxonomy` 原先按 MiniAgent 的原生 `stop_reason` 字符串做规则匹配，外部 Agent 的 `error_max_turns` 等原生词汇不在该词表内，会被静默误归因为 UNKNOWN。已引入 `TrialResult.canonical_stop_reason`，归因改走框架无关语义；旧产物无该字段时按原映射回退，历史归因结果不变（有回归测试锁定）。
- ✅ **W1-3 protocol + repo live 已完成**：Homebrew stable Claude Code 2.1.220 的真实 `probe()`、无认证 stream-json、智谱 GLM-5.2 协议流和获授权的 `bugfix-pricing-tax` repo smoke 均通过；后者 Task/Strict 1.00、6 tools / 8 model turns。该 n=1 只验证集成，不是横向能力结论。live 还暴露并修复了实验级 adapter 版本和外部 token 汇总丢失；后续两次 `ENOTFOUND` 正确落为 infra-invalid，正式矩阵前需校准 endpoint 稳定性。
- **W1-5 已完成（配置层）**：`ci.yml` 三门禁（quality / sandbox-image / console）+ `nightly-eval.yml` 三 job（bounds / evalplus-oracle / llm-smoke）+ `scripts/check_bounds.py` 确定性边界门禁 + `.dockerignore`。CI 全程不需要 LLM key；140 passed/1 skipped。已在干净 venv（仅 `pip install -e ".[dev,api]"`）逐步验证 ruff/pytest/selfcheck/check_bounds，并本地验证 `npm ci && npm run build`。
- **CI 首跑全绿**，含 `sandbox-image`：镜像 build 成功并在 `--network none` 下跑通 selfcheck 与确定性边界，容器化评测已落地。
- **W1-6 已完成**：`--workers N` 进程池并行 + `--resume` trial 级断点续跑；聚合按 suite 顺序，实测 workers=1 与 workers=8 summary 逐字段一致；短程 9×2 实测 17.0s→4.26s（4.0×）。默认 workers=1 以保持已校准基线可复现。`manifest.json` 固定实验身份，resume 配置不符直接拒绝。先后修掉并行 build 目录冲突，以及两个独立 runner 同秒启动时 experiment ID 冲突（现为 UTC + UUID 后缀）。
- **W1-7 已完成（机制层）**：`ProviderSpec` 表取代三处平行 if-chain 并接入 GLM（重构时发现 `_expected_model` 正是漏改的第三处）；`--model` 一个 flag 切换阶梯并写入溯源；`pricing.py` + `config/pricing.json` 每模型费率表，未定价报 `None` 而非 `0.0`、费率须带 source/as_of、CNY 不做隐式汇率换算、缓存命中分档计价、trial 内部分定价即整体不可用。182 passed/1 skipped。
- **费率已填（2026-08-04）**：DeepSeek（USD）与 GLM（CNY）均带 source URL 与日期；新增 `aliases` 与 `tiered` 两个字段。实时 API 验证发现 `deepseek-reasoner` 解析到 v4-flash，因此修掉两个缺陷：`DEEPSEEK_MODEL_PRO` 默认使 pro 档成为静默空操作；`last_model` 只记请求名会让产物声称跑了一个从未运行的模型（现记录实际服务模型 + `requested_model`）。GLM 型号已换代，阶梯更新为 glm-5.2 / glm-4.5-air / glm-4.7-flash（免费）。191 passed/1 skipped。
- **首次真实成本测量**：DeepSeek v4-flash vs v4-pro，短程 2 case，Task 均 1.00，成本 **$0.000791 vs $0.004163（5.26×）**——H1 saturation 首次带上成本维度。缓存分档计价把某 trial 的成本从 $0.002047 修正到 $0.000414（避免 4.94× 高估）。
- **H2 部分成立但远弱于预期（2026-08-04）**：最弱的 GLM-4.7-flash 在短程 suite 上 0.84（41/45 valid），逐 case 见 `spec-place-order` 0.40、`bundle-tier` 0.60，且 4 个 case pass^k=0；主导失败模式是 REPEATED_ACTION。但 GLM-4.5-air 与 DeepSeek 两档全部 1.00 —— **阶梯只在最弱一档起作用，且区分度（0.16）远小于预算收紧（0.85）**。长程 suite 对 V2+DeepSeek 也是 1.00（n=1），因此 H3 若在默认预算下做同样有不可测风险。
- **由此产生的方案修正**：区分度最便宜的来源是**预算**而不是新 case。实测工具调用 7–14.6 对 `max_steps=20`，冗余 30–65%；压到 8–10 即可让重工具的 case 对弱档失败、对强档通过。§6.3 的"预算约束成功率"应从指标升格为**实验变量**。
- 运行纪律新发现：GLM 免费档限流极严（workers=4 → 44/45 触发 429），付费档 workers=3 下 infra=0。并行度须按档位设定。
- **预算收紧实验已完成并证实假设**：同一 suite 只改 `--max-steps`，DeepSeek vs GLM-4.5-air 的差距从 20 步时的 **0.00** 变成 4 步时的 **0.85**（1.00/1.00 → 0.93/0.07），一条新 case 都没写。两个反直觉观察：模型会**适应**预算而非消耗预算（DeepSeek 给 20 用 7，压到 6 仍满分），所以冗余比不能预测收紧后的表现；曲线是**断崖**不是渐变。
- **方案修正**：`max_steps` 从 case 常量升格为实验变量，写入 provenance 与 resume 指纹。§7 的 H3 应在收紧预算下检验，否则大概率复现 H2 的 0 差异。
- **W1-4 已完成**：`update_plan` 工具 + PlanTracker + v3 prompt（V3 = V2 + planner，其余不变）。遵守率对着仓库动作核验而非 agent 自述——标 done 但期间无文件写入/测试运行的项记为 `plan_done_without_action` 并排除出 adherence。219 passed/1 skipped。
- **实测：给了 planner 不等于会规划。** DeepSeek v4-flash 在短程 case（7–17 动作）上完全不调用 `update_plan`；长程 case 上主动规划（3 项/3 修订 adherence 1.00；7 项/2 修订 adherence 0.71），且无计划表演。**推论：planner 的消融只能在长程上做**，短程上 V2/V3 必然无差异。
- **W2-1 已完成**：`context.py` 分级截断 + 确定性 compaction。两条纪律——上下文大小取 provider 报告的 `prompt_tokens` 而非 char/4 估算（否则触发阈值对每个被测系统的真实大小都不同）；摘要由轨迹确定性构建而非 LLM 生成（评测 harness 不能在每个长 trial 中间插入不确定、计费的调用）。`--ablate planner|context` 可单独消融并写入 adapter_version 与 resume 指纹。239 passed/1 skipped。
- **实测**（DeepSeek，`long-crossmodule-returns`，预算 16k）：compaction 触发 3 次、每次丢 21–23 条消息、峰值利用率 0.906，trial 仍 Task 1.00、plan adherence 1.00。
- **H3 已完成，结果一半证实一半推翻（2026-08-04）**。先补了一个前置缺陷：`--context-budget-tokens` 只是 V3 的旋钮，v2 从不承受上下文压力（峰值 14.5k vs 窗口 128k），所以 v2/v3 对比根本测不出 compaction 有没有用。改为实现 `BudgetContract.max_tokens` 为**对所有 harness 生效的硬上下文上限**（`--context-ceiling-tokens`），约束才对每一组都成立。
- 长程 4 case × 3 repeats，上限 12k：**v2 0.50 / v3 0.75 / v3−context 0.33 / v3−planner 1.00**。
  - **compaction 有效**：拿掉它 −0.42，失败几乎全是 `CONTEXT_OVERFLOW`；有它的两组峰值稳定在上限下、溢出为 0。
  - **planner 有害**：拿掉它 +0.25 且零失败。v2（0.50）好于 v3−context（0.33）进一步佐证 planner 单独造成 −0.17——**瓶颈是上下文时，规划把稀缺资源花在了记账上**。
  - 这否定了 W1-4 的隐含假设：JD 点名、主流 Agent 都有的能力，在这个约束下降低成功率。
- 边界：12 trial/组，0.25 ≈ 3 个 trial，区间很宽；单模型；上限值是照着实测峰值挑的。**方向性证据，不是效应量估计。**
- **planner 诊断完成，结论被推翻（2026-08-04）**。"planner 有害"源自我自己的两个 harness 缺陷：(1) loop 用 `version == "v2"` 字符串相等判断门控完成守卫，**V3 静默丢失了 V2 的纪律**，导致消融两组差的不只是 planner；(2) adherence 指标按模型给的 id 匹配，而模型在修订间把全部 id 改名（文本逐字不变），之前报的 0.47/0.22/0.33 全是测量假象。另有一个真实行为：agent 会在跑测试之前就把计划项标记 done（失败轨迹中 4 项在 step 26 跳到 done，首测在 step 28）。
- 修复：`AgentConfig.for_harness()` 统一定义 harness 身份；adherence 按归一化文本匹配并上报改名次数（12 trial 共 49 次）；新增 `plan_done_unverified` + 工具结果回灌警告；v3 prompt 写明计划不是完成证据。
- **重跑后**：v2 0.42 / **v3.1 1.00** / v3.1−context 0.33 / **v3.1−planner 1.00**。**planner 中性（成本 +18% 工具调用），compaction 是全部效应（+0.67）**。
- 方法论教训：消融只有在两组除被测能力外完全相同时才成立；没有轨迹级诊断就会把 harness 缺陷当成能力结论发表。
- **截至 2026-08-04 的阶段快照**：255 passed / 1 skipped，短/长 selfcheck 9/9 + 4/4。当前总门禁见本节开头。
- **该时间点的下一项**是 Claude endpoint 校准与横向组；此后已完成原 4-case 的模型受控横向实验，结果见 `cross_agent_report_v1.md`。

> 状态口径：本节“执行进度”与根目录 `PROJECT_STATE.md`/`TASKS.md` 是当前事实；下文三周计划、资源预算和假设表保留为预注册设计记录。凡与本节冲突，以当前事实为准，不得把历史预期当成已完成结果。

---

## 0. 一句话目标

把 Algora 从 **"评测自研 MiniAgent V1/V2 的私有闭环"**，升级为 **"能在统一预算契约下横向评测 Claude Code / 开源 Agent / 自研框架，并能自动挖掘指令偏移、上下文遗忘、测试投机三类失败模式的评测平台"**；同时把自研 MiniAgent 补齐 **上下文管理、记忆、任务规划、多轮交互** 四项主流能力，使其既是被测对象，也是可做科学消融的实验载体。

---

## 1. 与 JD 的逐条对齐

### 1.1 岗位职责映射

| # | JD 职责原文（要点） | 当前覆盖（2026-08-05） | 仍缺证据 | 状态 |
|---|---|---|---|---|
| 1 | Code Agent 框架开发与迭代：**代码理解、工具调用、多轮交互、记忆管理、任务规划** | 6 个 coding 工具、planner、确定性 compaction、完成守卫均已落地并做过消融 | 代码理解仍是 grep/read；ScratchPad、跨 run memory、multi-turn、subagent 均未实现 | 🟨 部分覆盖 |
| 2 | 面向**主流 Code Agent及自研框架**的系统化评测；覆盖真实开发任务、**长程多轮交互**、**完整工具链（构建/测试/部署）** | Claude Code + MiniAgent 的同模型横向实验；9 短程 + 8 长程；build/CLI case | 第二外部 Agent、multi-turn、deploy、官方 SWE-bench、多语言均缺；headline 尚未在 8-case 重跑 | 🟨 部分覆盖 |
| 3 | 自动化评测框架：**多 Agent 并行、环境隔离、过程可观测、结果自动化分析与可视化报告** | 进程池、trial 续跑、容器断网门禁、统一 TraceEvent、只读控制台、统计脚本均完成 | 静态 HTML/MD 导出和专用跨 Agent UI 未实现；“并行 trial”不等于 Agent 内多智能体协作 | ✅ 主体完成 |
| 4 | 自动识别**指令偏移、上下文遗忘、测试投机**；产出**可复现缺陷诊断包与回归用例** | 三个独立检测器均已实现并回扫真实 artifacts；repro bundle + 无模型 replay 已完成 | hackbait suite 未实现；不受约束的投机样本仅 16 个 | ✅ 工程闭环完成，行为样本待扩 |
| 5 | 深度洞察与产品驱动：输出分析报告，为框架优化提供建议 | 已有模型受控横向报告、预算/成本/上下文消融，并据此纠正 planner 结论 | 8-case 复验、第二模型/第二外部 Agent、独立 capability-gap 与 failure-atlas 报告尚缺 | 🟨 部分覆盖 |

### 1.2 任职资格与加分项映射

| 要求 | 当前证据 | 判断 |
|---|---|---|
| **框架开发经验** | MiniAgent loop、工具、sandbox、planner、context、adapter 契约和真实消融 | ✅ 有直接代码与数据 |
| **深度用户视角**（1 年+ AI 编程工具） | 仓库只能证明实际接入并分析过 Claude Code，不能证明一年时长 | ⚠️ 需由履历和案例补证，不应由项目文档代替 |
| **Python + 系统级语言** | Python 主体扎实；TypeScript 控制台规模仍小 | 🟨 Python 强，第二语言深度证据弱 |
| **软件工程素养** | 349 tests、Ruff、Protocol、CI/nightly、容器门禁、测量缺陷回归 | ✅ 强覆盖 |
| **评测与数据思维** | 私有 benchmark、kappa、cluster bootstrap、Wilson、McNemar、预注册与变量控制 | ✅ 强覆盖；分层/成本统计待补 |
| 加分：**开源经历** | 当前仓库是否公开及外部采用情况不由代码内容证明 | ❌/待外部证据 |
| 加分：**平台工程** | 并行调度、checkpoint、manifest 指纹、环境清单、CI | ✅ 强覆盖 |
| 加分：**Benchmark / 回归 / CI/CD / 容器化** | 四项均有可执行证据 | ✅ 强覆盖 |
| 加分：**产品化思维** | 有横向报告和预算权衡，但静态报告、capability-gap 产品建议书未完成 | 🟨 部分覆盖 |

**结论**：当前最强卖点是 JD 职责 3、职责 4 的检测部分，以及评测/平台工程加分项；职责 1、2、5 只完成了可展示的主体，不能写成“全部覆盖”。

---

## 2. 现状与差距（含主流 Agent 对标）

### 2.1 主流 Agent 能力对标表

本表仅记录截至 2026-08-05 由官方文档或本项目 live probe 支撑的能力，不把计划猜测写成事实。Claude Code 参考官方 [memory](https://code.claude.com/docs/en/memory) 与 [agents](https://code.claude.com/docs/en/agents)；Cline 参考 [Plan/Act](https://docs.cline.bot/core-workflows/plan-and-act)、[checkpoints](https://docs.cline.bot/core-workflows/checkpoints) 与 [subagents](https://docs.cline.bot/features/subagents)；Aider 参考 [repo map](https://aider.chat/docs/repomap.html) 与 [lint/test](https://aider.chat/docs/usage/lint-test.html)。Roo Code 未在本轮重新 probe，不对其当前能力作无证据断言。

| 能力维度 | 主流产品可验证基线 | **Algora MiniAgent 当前** | 差距判断 |
|---|---|---|---|
| 上下文 | Claude Code 自动 compact；Cline 可拆新 task；Aider 按 token 预算裁剪 repo map | 分级截断 + 确定性 compaction + 全 harness ceiling | ✅ 核心机制已补，策略丰富度仍低 |
| 记忆 | Claude Code 有 CLAUDE.md + auto memory；Cline 可恢复 task | AGENTS.md 注入；无 ScratchPad/跨 run memory | ❌ 明显缺口 |
| 规划 | Claude/Cline 有 plan 工作流；Aider 有 architect/editor 双阶段 | `update_plan` + 动作验证，成功率中性、工具成本 +18% | 🟨 已实现但价值边界明确 |
| 代码理解 | Claude/Cline 有并行只读探索；Aider 有 tree-sitter/图排序 repo map | `rg`/read/list，无 AST/LSP/repo map | ❌ 主要产品能力缺口 |
| 多轮/恢复 | 主流产品均支持会话续接；Cline 有 checkpoint 回滚 | 单任务 loop；无用户反馈回合、无 checkpoint | ❌ JD 硬缺口 |
| 多 Agent | Claude Code 有 subagents/agent teams/worktrees；Cline 有只读并行 subagents | runner 可并行 trial，但 Agent 内无委派协作 | ❌ 不应把两类并行混为一谈 |
| 工具扩展 | Claude/Cline 支持 MCP，Cline 另有 browser | 固定 6 coding 工具 + planner | 🟨 对评测足够，对产品型 Agent 不足 |
| 安全/可观测 | 主流产品有权限、checkpoint、usage 展示 | deny-by-default policy、worktree、TraceEvent、成本/环境溯源 | ✅ 项目优势，且更适合受控实验 |

因此近期不应以“复刻主流 Agent 全功能”为目标。repro bundle 已完成；剩余对 JD 产出价值最高的是 multi-turn、第二外部 adapter、报告导出和官方实例。repo map/AST 可作为下一阶段 Agent 能力增强，MCP/browser 只有在形成可评测假设后再做。

### 2.2 差距清单（按严重度排序）

| ID | 差距 | 严重度 | 根因 |
|---|---|---|---|
| G1 | Claude Code 横向已完成；第二外部 adapter 未接，8-case 矩阵未重跑 | 🟠 高 | 现有 headline 仍是 4 case、单模型；无法形成三方结论 |
| G2 | context 与 planner 已落地；memory/multi-turn 未做 | 🟠 高 | W1-4/W2-1 已关闭一半差距；后两项仍需独立 oracle 与隔离设计 |
| G3 | 长程 suite 已扩到 8 case，但主要矩阵仍只跑过旧 4 case | 🟠 高 | 数据扩充与结论升级之间还差一次同配置复验 |
| G4 | ~~三类检测器之后缺 repro bundle/回归 fixture~~ **已关闭** | ✅ | 脱敏 bundle、checksum/suite 指纹、无模型 grader replay 已完成 |
| G5 | reward hacking 行为样本不足；无 hackbait suite | 🟡 中 | 640 patch 中只有 16 个不受沙箱强制，零事件上界仍为 19.4% |
| G6 | ~~无 CI、Docker 从未 build、runner 串行~~ **已关闭** | ✅ | CI 三门禁全绿；容器内断网实跑；进程池 + 断点续跑 |
| G7 | SWE-bench 仅自建兼容样例，无官方实例 | 🟠 高 | 面试判断近似二值 |
| G8 | 已有离线 wheel + CLI 交付 case；仍无部署类 case | 🟡 中 | build 已覆盖，deploy 仍缺 |
| G9 | 默认预算下短/长 suite 均易饱和 | 🟡 中 | 模型阶梯差异仅 0.16；预算收紧可把差距放大到 0.85，但不能代替更难任务 |
| G10 | bootstrap/McNemar/Wilson 已完成；分层宏平均、成本统计未做 | 🟡 中 | W3-3 只完成统计核心 |
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
| `mini_store_long`（长程） ✅ | 8 case；原 4-case 校准动作中位数 30、模型轮次 13.5 | 在 8 case 上重跑消融/横向评测 | **解锁 context/memory/plan 的测量**；三方横向对比主战场 |
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
| `long-discount-rounding` | 折扣原语缺陷级联到 4 个消费者 | 31–36 次工具调用 | 边界理解、hidden 完整性 |
| `long-tax-single-source` | 税率单一真源重构，错误依赖方向会循环导入 | 多调用点 + 结构约束 | 架构理解、行为保持 |
| `long-release-accounting` | 池级库存检查 + 调用方幂等的双层修复 | 跨 3 个消费者且有局部修复陷阱 | Task/Strict 分离、指令偏移 |
| `long-order-snapshot` | 订单症状、购物车根因、hidden 定位 oracle | 可见测试允许症状层修补 | 根因定位、上下文 canary |

八条都挂 `CanarySpec`，用于测量约束在长轨迹上的存活。新增四条已经产生 Task、Strict 和 canary 的真实区分，但尚未纳入完整横向矩阵。

---

## 5. 三周迭代计划

图例：🔵 评测平台线　🟠 Agent 框架线　🟣 数据资产　⚫ 工程基建

### Week 1 — 地基（解锁后续所有实验）

| ID | 任务 | 线 | 依赖 | 工时 | 验收标准 |
|---|---|---|---|---|---|
| **W1-1 ✅** | 长程 suite `mini_store_long`（地基 4 case，现扩到 8） | 🟣 | — | 1.5d | 当前 8/8 valid；reference/none=1/0；原 4-case 校准动作中位数 30、模型轮次 13.5、测试循环 3 |
| **W1-2 ✅** | `AgentAdapter` 抽象 + `MiniAgentAdapter` + runner 改造 | 🔵 | — | 1d | 94 tests 全绿；adapter round-trip、legacy/default CLI、规范化产物与 infra-invalid 口径有离线回归覆盖 |
| **W1-3 ✅** | `ClaudeCodeAdapter`（headless + stream-json 归一化） | 🔵 | W1-2 | 1.5d | 39 条 CLI stand-in 回归；2.1.220 + GLM-5.2 protocol/repo live；版本/token 溯源修复 |
| **W1-4 ✅** | `planner.py` + `update_plan` 工具 + v3 prompt | 🟠 | W1-1 | 1d | 仓库动作验证 adherence；修复 id 改名假象；H3 中成功率中性、工具调用 +18% |
| **W1-5 ✅** | GitHub Actions CI（ruff + pytest + Docker build + selfcheck） | ⚫ | — | 0.5d | 三门禁首跑全绿；镜像内 `--network none` 跑通 selfcheck 与 bounds |
| **W1-6 ✅** | runner 并行化（进程池）+ trial 级 checkpoint 续跑 | ⚫ | W1-2 | 1d | 9×2 实测 4.0×；manifest 指纹、完整标记、infra 重试与独立 build 目录均覆盖 |
| **W1-7 ✅** | GLM provider 接入 + 模型阶梯配置 | 🔵 | — | 0.5d | GLM 已实跑；费率/alias/tier/cache/实际服务模型溯源就绪；CNY→USD 仍需显式汇率 |

**Week 1 实际里程碑**：平台侧地基全部完成；MiniAgent 可并行/续跑且已有模型、预算和成本实验。Claude Code 后续已完成具备重复数的 4-case 模型受控横向实验。

### Week 2 — 能力补齐与缺陷挖掘

| ID | 任务 | 线 | 依赖 | 工时 | 验收标准 |
|---|---|---|---|---|---|
| **W2-1 ✅** | `context.py`：token 预算 + 分级截断 + compaction | 🟠 | W1-1 | 1.5d | H3 修正后 V3.1=1.00、V3.1−context=0.33；硬 ceiling 对所有 harness 生效 |
| **W2-2 ⬜** | `memory.py`：ScratchPad（run 内） | 🟠 | W2-1 | 0.5d | 未开始；常驻 note 与隔离规则仍待实现 |
| **W2-3 ✅** | `detectors/context_amnesia.py`（canary 被动召回曲线） | 🔵 | W1-1, W2-1 | 1d | checker、early/late decay、路径归一化和真实正例均已完成；正式曲线报告待 W3-5 |
| **W2-4 ✅** | `detectors/reward_hacking.py`（8 类信号） | 🔵 | — | 1.5d | 8 类构造样本命中、reference 零误报；640 patch 回扫，行为样本仅 16 |
| **W2-5 ⬜** | `mini_store_hackbait` suite（3 case，开放测试写权限） | 🟣 | W2-4 | 0.5d | 未开始 |
| **W2-6 ✅** | `detectors/instruction_drift.py`（约束逐步追踪） | 🔵 | W1-4 | 1d | first breach、obedience ratio、self-corrected/persisted 和跨 adapter 写路径已完成 |
| **W2-7 ⬜** | SWE-bench 官方实例 Smoke Slice（B2） | 🔵 | W1-5 | 1.5d | 未开始；仍为 Compatibility Sample |
| **W2-8 ⬜** | 第 2 个外部 adapter（aider 或 mini-swe-agent） | 🔵 | W1-2 | 1d | 未开始 |

**Week 2 实际里程碑**：三类失败模式检测器已经齐全，但缺第二外部 adapter、hackbait 与官方 SWE-bench，因此“三方完整矩阵可以开跑”尚未达成。

### Week 3 — 多轮、统计、收口

| ID | 任务 | 线 | 依赖 | 工时 | 验收标准 |
|---|---|---|---|---|---|
| **W3-1 ⬜** | `multi_turn.py` 确定性反馈回合 + 3 条多轮 case | 🟠🟣 | W1-2 | 1.5d | 未开始 |
| **W3-2 ⬜** | `memory.py` 跨 run RepoMemory + 隔离验证 | 🟠 | W2-2 | 1d | 未开始；不得绕过 repeats 泄漏防护 |
| **W3-3 🟨** | `stats/`：cluster bootstrap CI + exact McNemar + 分层宏平均 | 🔵 | — | 1d | bootstrap、McNemar、Wilson 已完成；分层宏平均和成本统计待补 |
| **W3-4 ✅** | `detectors/repro_bundle.py`：诊断包 + 自动回归 fixture | 🔵 | W2-4/6 | 1d | 空/非空失败 patch 离线 replay；hidden/凭据/篡改/oracle 漂移/legacy 边界均有测试 |
| **W3-5 ⬜** | `report.py` 静态报告 + `CrossAgent.tsx` 前端视图 | 🔵⚫ | W3-3 | 1d | 未开始；现有控制台仍为通用 artifacts 只读视图 |
| **W3-6 🟨** | 全量实验执行（见 §6 矩阵）+ 结果回填 | 🔵 | 全部 | 1d | 4-case 横向、H2/H3 和检测器回扫完成；三方/多轮/官方实例未完成 |
| **W3-6a ⏸️** | 8-case Claude Code / MiniAgent 模型受控矩阵 | 🔵 | GLM 额度 + endpoint preflight | 1d | 外部额度阻塞；恢复后严格沿用冻结模型与配对配置，不接受替代模型混算 |
| **W3-7 🟨** | 框架开源清理（密钥审计、命名统一、README 架构图）+ 洞察报告 | ⚫ | W3-6 | 0.5d | README 与横向报告已完成；开源核验、命名统一和独立洞察文档未闭环 |

**当前可后置项**：W3-2（跨 run memory）→ W2-5（hackbait 专用 suite）→ W3-3 的分层部分。跨 run memory 风险高且不应只为“打勾”实现。
**当前不可后置项**：W3-1 multi-turn、W3-5 报告导出、W2-8 第二外部 adapter、W2-7 官方实例；它们直接对应尚未闭环的 JD 证据。W3-6a 同属高优先级，但在外部额度恢复前暂停，不以改变模型换取表面进度。

---

## 6. 评测设计

### 6.1 实验矩阵

| 实验 | 目的 | 系统维度 | 模型维度 | Suite | repeats | trial 数 |
|---|---|---|---|---|---|---|
| **E1** Harness 消融 | 自研框架的能力增量归因 | MiniAgent v1 / v2 / v3 | GLM-4.5-air、DeepSeek-v4-flash、GLM-4.7-flash(弱) | 短程 9 | 5 | 135 |
| **E2** 长程消融 | context/plan 是否在长任务上生效 | v2 / v3 / v3−context / v3−planner | GLM-4.5-air、DeepSeek-v4-flash | 长程 4 | 5 | 160 |
| **E3** 三方横向 | JD 职责 2 的核心产出 | Claude Code / aider(或 mini-swe) / MiniAgent v3 | 统一模型（仅在 endpoint 能力确认后）+ 各自默认模型独立组 | 短程 9 + 长程 4 | 3 | 234 |
| **E4** 失败模式挖掘 | JD 职责 4 | 上述全部系统 | — | hackbait 3 + 长程 4（canary） | 5 | 复用 E2/E3 + 105 |
| **E5** 多轮 | 失败恢复率 | v3 / Claude Code | GLM-4.5-air（仅在 endpoint 兼容确认后） | multiturn 3 | 5 | 30 |
| **E6** 公开 benchmark | 证据等级 | Claude Code / MiniAgent v3 | 各自 | SWE-bench 官方 3–5 + EvalPlus 5 | 3 | ~60 |

**更新后的实验上限约 724 trial（E4 主要复用 E1/E2/E3）；Claude live preflight 与 provider 限流校准后再冻结最终矩阵。**

### 6.2 资源预算估算

| 类别 | 单 trial 估算 | 数量 | 小计 |
|---|---|---|---|
| 短程 trial | ~10 步 × ~5k prompt tok ≈ 50k tok，按实际费率表计 | ~300–400 | **待最终模型矩阵** |
| 长程 trial | ~35 步 × ~10k tok ≈ 350k tok，按实际费率表计 | ~200–250 | **待最终模型矩阵** |
| Claude Code trial | native/第三方 endpoint 成本语义分开 | ~40–80 | **repo smoke 后待稳定性校准** |
| SWE-bench 官方 | 环境构建为主，token 次要 | ~30 | **$10–30** |
| **合计** | | | **preflight 后按 provider/model/cache 实测重算，不沿用旧粗估** |

**时间才是真正的瓶颈**：长程 trial 单次 3–8 分钟，280 个串行需 15–35 小时。这就是 W1-6 并行化**不是优化项而是前置条件**的原因；8 并发下压缩到 2–5 小时，可放进 nightly CI。

### 6.3 指标定义

| 类别 | 指标 | 定义 | 备注 |
|---|---|---|---|
| 功能 | Task Success | target 测试全过 | 现有 |
| 功能 | Strict Success | target + hidden + regression 全过 **且** 约束全守 | 现有；长程 case 上预期首次出现明显分离 |
| 稳定 | pass@k / pass^k | 现有 | pass^k 更能体现可靠性 |
| 成本 | cost per success | 总成本 / 成功 trial 数 | `pricing.py` 费率已填并带 source/as_of；`cost_source` 必须标注；GLM USD 仍缺显式汇率 |
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
| 假设 | 强模型在短程 suite 上，v1/v2/v3 的 Task Success 均落在 0.95–1.00，三者差异很小 |
| 依据 | 已有观测：9 case 上 V1=0.98、V2=1.00 |
| 当前结果 | 默认预算下 DeepSeek 两档与 GLM-4.5-air 均 1.00，饱和成立；但 `max_steps=4` 后 DeepSeek 0.93、air 0.07，说明饱和取决于约束而非只取决于 case。 |
| 证伪 | 若新增的 instruction-following / refactor case 拉开 >0.1 的差距，说明任务类型比 harness 纪律更能造成区分度 |
| 无论如何的价值 | 明确"短程 suite 的用途是回归护栏，不是区分度来源"，这本身是一个正确的 benchmark 定位结论 |

### H2 · 弱模型恢复区分度

| | |
|---|---|
| 假设 | 弱模型在短程 suite 上 Task Success 落在 **0.35–0.70**，且 harness 产生可测差异 |
| 依据 | 弱模型缺乏自发的验证纪律，harness 约束的边际收益更大 |
| 当前结果 | **部分成立但远弱于预期**：glm-4.7-flash 为 0.84，只有最弱档产生 0.16 区分度；GLM-4.5-air 与 DeepSeek 均 1.00。相比之下预算收紧产生 0.85 差距。 |
| 证伪 | 若弱模型下 v3 反而更差 → 说明 compaction/plan 对弱模型是**认知负担**而非帮助（这是一个很有价值的发现，直接对应产品建议：能力分层启用） |
| 价值 | 无论方向，都得到"harness 收益随模型能力递减/递增"的曲线，这是 §4.2 case 区分度分析真正需要的多系统数据 |

### H3 · 长程 case 上 v3 显著优于 v2 ★ 主假设

| | |
|---|---|
| 假设 | 长程 4 case 上：v2 Task Success **0.30–0.60**，v3 **0.55–0.85**，差距 **≥0.15** 且 McNemar 显著；v3 的 context overflow rate 比 v2 低 ≥50%；代价是 token +20–60% |
| 依据 | v2 无 compaction，35+ 步后必然逼近上下文预算；plan 缺失导致跨模块任务遗漏调用点 |
| 消融预期 | v3−compaction ≈ v2（overflow 主导）；v3−plan 介于两者之间（能跑完但漏改） |
| 修正后结果 | 12k ceiling、4 case×3 repeats：v2 0.42 / V3.1 1.00 / V3.1−context 0.33 / V3.1−planner 1.00。compaction 是全部成功效应；planner 成功率中性、工具调用约 +18%。 |
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
| Claude Code | 统一模型（待 endpoint probe） | — | — | — | — | — | — |
| MiniAgent v3 | GLM-4.5-air | — | — | — | — | — | — |
| MiniAgent v2 | GLM-4.5-air | — | — | — | — | — | — |
| MiniAgent v3 | GLM-4.7-flash | — | — | — | — | — | — |
| aider / mini-swe | GLM-4.5-air | — | — | — | — | — | — |

每格附 cluster bootstrap 95% CI 与样本数；配套：canary 召回曲线图、成本-成功率前沿图、失败模式分布堆叠图。

---

## 8. 风险与明确不做的事

### 8.1 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Claude/第三方 endpoint 不稳定或限流 | E3 阻塞、infra 比例过高 | protocol/repo smoke 已过；正式矩阵前做少量重复校准，infra-invalid 排除分母并用 resume 重试，持续不稳则转 aider |
| 默认预算下 suite 饱和 | 模型/Harness 区分度不足 | 把 `max_steps` 与 context ceiling 设为实验变量；同时补真正更难的任务，预算效率不能替代能力上限 |
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

| 交付物 | 当前状态 | 对应 JD |
|---|---|---|
| `adapters/` 异构 Agent 接入层 + 轨迹归一化 | ✅ MiniAgent + Claude Code；第二外部 Agent 未接 | 职责 2、3 |
| MiniAgent v3（context + memory + planner + multi-turn） | 🟨 context/planner 完成；memory/multi-turn 未做 | 职责 1 |
| `detectors/` 三类失败模式检测器 + repro bundle | ✅ 检测、脱敏诊断、自动 fixture、无模型 replay 完成 | 职责 4 |
| `stats/` + `report.py` + 跨 Agent 前端视图 | 🟨 统计核心完成；report/UI 未做 | 职责 3、5 |
| 长程 / 多轮 / hackbait / SWE-bench 官方四类 suite | 🟨 长程 8-case 完成；其余三类未做 | 职责 2 |
| `.github/workflows/` CI + nightly eval | ✅ 完成 | 加分项 |
| `docs/cross_agent_report_v1.md` 横向对比报告 | ✅ 双 Agent/三 scaffold、原 4-case；非三方外部 Agent | 职责 2、5 |
| `docs/failure_mode_atlas_v1.md` | ⬜ 未创建 | 职责 4 |
| `docs/extension_agent_automatability.md` | ⬜ 未创建 | 职责 2（判断力） |
| `docs/miniagent_capability_gap_v1.md` | ⬜ 未创建 | 职责 5（产品化） |
| 公开 GitHub 仓库 | ⚠️ 本地代码无法证明公开状态与外部采用 | 加分项 |

---

## 10. 对外叙事映射（面试用）

**主线一句话**：
> 我做了一个 coding agent 评测平台，已在统一模型和 wall-clock 预算下比较 Claude Code 与自研 MiniAgent，并自动检测指令偏移、上下文遗忘和测试投机，再把失败转成无需模型即可重放的脱敏诊断包；这些评测反过来驱动了完成守卫、规划和上下文管理的可归因迭代。第二外部 Agent与 multi-turn 仍是下一阶段。

**8 分钟演示脚本**：

| 时长 | 内容 | 落点 |
|---|---|---|
| 0–1min | 问题：主流 Agent 在短 benchmark 上都饱和，真实差异在长程 | 评测思维 |
| 1–2min | 架构图：adapter 层 + 归一化 + 预算契约 | 平台工程 |
| 2–4min | Claude Code / MiniAgent 三 scaffold 横向表 + wall-clock 权衡 | JD 职责 2、5 |
| 4–6min | 三个检测器 + repro bundle：展示 evidence span、hidden 不入包、无模型 replay | JD 职责 4 |
| 6–7min | v2→v3 消融：compaction/plan 各自贡献多少，代价多少 | JD 职责 1 |
| 7–8min | 诚实边界：样本量、区间宽度、哪些不能外推、明确不做的事及理由 | 评测素养（最加分的一段） |

**必须准备的追问**：
1. 不同 Agent 的预算怎么算公平？→ §3.3 `BudgetContract` 的设计取舍
2. 为什么还没做跨 run memory？→ 它会直接威胁 repeats 独立性；必须先有作用域、清空和泄漏单测，当前未实现
3. hacking 率是 0，你怎么知道检测器有效？→ §7 H5 的"检测器有效性与检出率分开论证"
4. 17 个 case 的结论能信吗？→ 现有 headline 实际只跑了其中旧 4 个；§6.4 聚类 bootstrap 与 8-case 重跑计划
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
