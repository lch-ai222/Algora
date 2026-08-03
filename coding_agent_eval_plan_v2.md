# CodeAgent Eval Lab — 方案 v2（面试冲刺版）

文档版本：v2.0（在 v1 基础上按"面试前可交付 + 双岗价值"重构）
技术栈：Python、FastAPI、React、TypeScript、SQLite（Docker 后置）
定位：面向仓库级代码任务，走通 Coding Agent 从执行 → 轨迹采集 → 自动评分 → 失败归因 → 版本回归的完整闭环。

---

## 0. 相对 v1 的关键修订

1. **范围砍到"能走通闭环的最小竖切片"**：面试价值 = 闭环是真的，不是页面多/benchmark 多。
2. **Docker 后置**：MVP 用"临时 git worktree + 子进程 + timeout + 命令/路径白名单"做隔离；Docker 当设计讲、时间富余再上。
3. **SWE-bench 降级**：只写 adapter 接口 + 讲设计，最多接 1 条；真接全量极易吃掉数天。
4. **HumanEval+ 保留为公开协议学习入口**：函数级、环境成本相对可控；先用少量官方实例完整走数据、执行、base/plus 与报告协议，不把子集验证包装成完整公开成绩。
5. **LLM-Judge + judge meta-eval（kappa）上调优先级**：网易 JD 点名要"LLM-as-Judge / 对抗性测试 / 人机混合"，且这是我现成的差异化（ft_diag_agent 已实现），必须进 demo，不留 P2。
6. **大量复用 ft_diag_agent 的评测基建**（见 §13），只把有限时间砸在真正全新的三块：agent 本体、沙箱、coding 专属 grader。

## 1. 双岗价值定位

| | 网易（评测方向） | 蚂蚁（coding agent 开发） |
|---|---|---|
| 契合度 | ~90%，主武器 | ~50%，辅助 |
| 打什么 | Coding Agent Benchmark + 自动化 pipeline + golden dataset + 失败归因 + V1/V2 + 可视化 | coding agent 本体 + harness 迭代 + "交付质量可管理"（呼应 JD"过程可追溯、结果可观测、质量可管理"）|
| 补充 | 几乎不缺 | 规划/记忆/上下文/多 agent 用 **ft_diag_agent**（generator-critic 审核 agent）配合讲 |

## 2. 核心原则（面试反复回到这几条）

1. **闭环 > 广度**：可执行任务 → 可复现运行 → 可验证结果 → 可定位失败 → 可驱动优化 → 可回归确认。
2. **确定性优先的分级评分**：程序验证 > 静态规则 > LLM-Judge > 人工。能程序判的绝不用模型。
3. **Task Success vs Strict Success 双指标**：揭示"功能完成但工程不合规"（与 OctoBench 的 task solving / scaffold-aware compliance 分离方向相呼应；JD 中的 OctoCodingBench 命名以实际官方版本为准）。
4. **私有数据集 = 无污染**：自建 mini_store 天然规避 contamination——真实 benchmark 最头疼的问题，这是卖点，要主动说。
5. **诚实标注**：SWE-bench 样本明确标"compatibility sample，非正式排行榜"。

## 3. 系统架构（标注 建/抄/只讲）

```
React + TS UI（只建能演示闭环的页）        [建/抄]
   Experiment Detail · Trial Trace Viewer · Diff · Version Compare
        │ REST + SSE
FastAPI                                    [建/抄]
   Experiment / Trial / Trace / Report
        │
┌───────┴────────┐
Agent Adapter     Grader Engine            [建 + 抄]
 MiniAgent V1/V2   Test / Constraint / Patch / Trajectory / Efficiency（确定性）[建]
 HumanEval+        LLM-Judge + meta-eval（kappa）[抄 ft_diag_agent]
 SWE-bench(接口)   
        │
Sandbox Runtime                            [建：进程隔离；Docker 只讲]
 temp git worktree · subprocess · timeout · 命令/路径白名单
        │
Storage：SQLite（结构化）+ 本地 artifacts（trace/patch/log）  [建/抄]
```

## 4. 范围分层（最重要，照这个执行）

### A. 必建（walking skeleton，到这就能 demo 完整闭环）
- MiniAgent V1：loop + 5 工具 + trace，进程隔离。
- mini_store 仓库 + **6 条内部 case**（4 bugfix + 2 spec）+ hidden/regression 测试 + reference patch + **benchmark 自检**。
- **Test / Constraint / Patch** 三个确定性 grader；Task Success + Strict Success；CLI 一键跑全套出 JSON。
- 最小 FastAPI + 最小 React（Experiment Detail + Trace Viewer + Diff）。
- **V1 → V2 同配置回归 + Version Compare**（哪怕先是对比表）。

### B. 换成"便宜的真 benchmark"
- **HumanEval+**（EvalPlus）：先做少量官方实例的 protocol-conformant smoke slice，掌握 base/plus、隔离执行和 pass@k；不追求高成本全量榜单。
- **最小 LLM-Judge**（只跑 1 条 Code Review case）+ **复用 ft_diag_agent 的 judge meta-eval / kappa 叙事**。

### C. 只讲不建（能画架构、说清取舍即可）
- 完整 Docker 沙箱、SWE-bench 全量（留 adapter 接口 + 可选 1 条）、Terminal-Bench/Harbor、PostgreSQL、外部 agent adapter、成本看板全量。

## 5. Coding Agent 设计

**输入**：`AgentTask{instruction, workspace_path, max_steps, timeout_seconds, allowed_tools, project_instructions}`

**5 个工具**：`list_files` / `search_code`(ripgrep) / `read_file`(分页) / `apply_patch`(拒改禁止目录、存 diff) / `run_command`(白名单+timeout+输出截断) / `git_diff`。（git_diff 算第 6 个但零成本）

**Loop**：build messages → 循环内 `model.generate(tools=...)` → 存事件 → 有 final 则停 → 执行 tool_call 存结果回灌 messages。

**完成时系统额外检查**：是否有改动 / 是否跑过测试 / 未提交 diff / 超步 / 超时 / 触发禁止操作 / 不可恢复错误。

**V1（baseline）**：简单 system prompt，不强制复现、不强制完成前跑全测、无重复动作检测。
**V2（按 V1 失败优化）**：强制先复现 → 完成前查 diff + 跑目标&回归测试 → 工具输出分页截断 → 重复动作检测 → 危险命令限制 → 注入 AGENTS.md → 测试失败要求重规划 → 结构化完成报告。
**归因纪律**：V1/V2 同模型、同 benchmark、同预算、同温度、同步数、同环境，把变化归因到 harness/策略。

## 6. Benchmark 设计

### 6.1 内部 SWE 风格（核心）
- `mini_store/`：10–20 个 Python 文件、1–3k 行、pytest、有跨模块调用；每条任务改 1–3 文件、1–5 分钟可完成。
- **6 条必建**（4 bugfix + 2 spec），有时间再补到 12（+2 refactor +1 review +2 instruction-following）。
- case 结构：`case_id / task_type / instruction / base_commit / visible_tests / hidden_tests / regression_tests / constraints / forbidden_paths / max_steps / timeout / difficulty / tags`。
- **核心指标**：Task Success / Strict Success / Hidden Pass Rate / Regression Pass Rate / Patch Apply / Constraint Pass / Forbidden Action Rate / 工具调用数 / Token / 时延 / 重复运行成功率。

### 6.2 HumanEval+（公开协议 Smoke Slice）
- 先选少量官方实例，固定 EvalPlus 版本、筛选规则和执行协议；指标 Pass@1、Base/Plus Pass Rate、时延、Token、异常率、超时率。
- 用途：校准底层模型基础能力 + 理解严格测试对脆弱解的识别；不作完整排行榜或主要成果。

### 6.3 SWE-bench（仅接口 + 讲设计）
- 写 `SWEBenchAdapter`，能读官方格式、生成兼容 patch；真跑最多 1 条 Lite。
- 前端/README 明确标 "Compatibility Sample / 非正式排行榜"。

## 7. 评分体系

**分级优先级**：确定性程序验证 > 静态规则 > LLM-Judge > 人工。

- **Test Grader**：目标/隐藏/回归测试 + 收集错误 + 超时 → `{passed, failed, errors, pass_rate}`。
- **Constraint Grader**：改禁止文件 / 新依赖 / 改动文件数超限 / 缺类型注解 / 禁止命令 / 完成前是否跑全测 / AGENTS.md 遵循。
- **Patch Grader**：patch 是否存在/可应用 / 改动文件数 / 增删行 / 无关改动 / **是否改测试绕过验证**。
- **Trajectory Grader**：是否读关键文件 / 是否跑过测试 / 首次测试在第几步 / 测试失败后是否继续 / 重复动作 / 提前结束 / 工具调用错误 / 超预算。
- **Efficiency Grader**：时延 / in-out token / 估算成本 / 工具&模型调用数 / 命令耗时 / 最大上下文。
- **LLM-Judge Grader（抄 ft_diag_agent）**：只用于 Code Review 质量 / Spec 覆盖度 / 可维护性等无程序 oracle 的维度；**绝不用于**判测试是否过、文件是否改、是否超时。输出结构化 `{score, max_score, passed_items, missed_items, confidence, reason}`，**强制引用**、temperature=0、位置偏差用 swap 平均。

## 8. 评测维度与统计严谨性

五组维度：Functional Correctness / Agent Execution / Instruction Compliance / Code Quality / Efficiency & Stability（沿用 v1 §10）。

**统计严谨性（评测岗加分，务必能讲）**：
- 每条 case 重复跑（≥3），报**均值 + 方差**，不只看单次。
- 区分 **pass@k**（k 次里至少 1 次过，看能力上限）与 **pass^k**（k 次全过，看可靠性）。
- **区分度检查**：用 V1 / V2 / 直接模型 / 人工 reference 四档跑，全过=过简单、全败=过难或有缺陷、强弱有合理差异=有区分度。
- **judge 可信度（meta-eval）**：小 gold 集量 judge vs 人工的一致率 / **Cohen's kappa**，不达标维度降级——直接复用 ft_diag_agent 的 `judge_meta_eval.py`（参考基线 kappa≈0.62）。

## 9. 失败归因（Taxonomy）

标签（区分主因/次因）：TASK_UNDERSTANDING / REPOSITORY_NAVIGATION / CODE_RETRIEVAL / PLANNING / TOOL_SELECTION / TOOL_ARGUMENT / EDIT / TEST_EXECUTION / RECOVERY / INSTRUCTION_VIOLATION / CONTEXT_LOSS / REPEATED_ACTION / PREMATURE_TERMINATION / TIMEOUT / ENVIRONMENT / JUDGE / UNKNOWN。
自动规则示例：从未读目标模块→CODE_RETRIEVAL；测试失败即结束→RECOVERY；改 tests→INSTRUCTION_VIOLATION；连续同命令 3 次→REPEATED_ACTION。无法自动判的由人工看轨迹补主因。

## 10. 沙箱（进程隔离优先）

MVP：**每 trial 从固定 base commit 起 → 独立临时 git worktree → 子进程执行 → CPU/内存/timeout 限制 → 默认断网 → 命令黑白名单 + 输出截断 → 结束导出 patch/log → 清理**。
禁止/拦截：`rm -rf /`、`sudo`、`shutdown/reboot`、`mount`、`docker`、`kubectl`、访问宿主机路径。
**Docker 只讲设计**：解释它用于跨平台环境一致性与更强隔离（SWE-bench 官方即要求 Docker），时间富余再落。

## 11. 数据与存储（简化）

SQLite（`datasets/dataset_versions/eval_cases/agents/agent_versions/experiments/trials/trace_events/grade_results/failure_tags/artifacts`）+ 本地 artifacts 目录（`config.json / trajectory.jsonl / patch.diff / pytest-*.log / grader-results.json / final-summary.json`）。大日志走文件不进库。TraceEvent 类型：model_request/response、tool_call/result、file_read/write、command_start/finish、test_result、error、final_answer。

## 12. 前端（只建能演示闭环的页）

必建：**Experiment Detail**（顶部指标 + case 表 + 失败/回归筛选）、**Trial Trace Viewer**（左 step 列表、右 模型输出/工具参数/结果/日志/测试、底 diff+grader+tags+cost）、**Diff Viewer**、**Version Compare**（V1 vs V2：总体差异 + improved/regressed/stable + 成本/工具/失败类型变化）。
后延：Dashboard、Dataset 管理页、Create Experiment 表单（先用 API/CLI 触发）。

## 13. 复用 ft_diag_agent 清单（别重造）

| 新项目要的 | 直接迁移 |
|---|---|
| Experiment/Trial 版本化、baseline/current delta、回归检测 | eval run 版本化 + NEW_ERROR/WORSENED/RESOLVED |
| 多维指标聚合、混淆分析 | eval 聚合 + 混淆表 + 趋势图 |
| Trace 事件流 + replay viewer | ReplayEventRecord / 事件流 UI |
| LLM-Judge + meta-eval(kappa) + 不达标降级 | `judge_meta_eval.py`（搬方法与叙事）|
| 分级门禁（确定性优先） | 审核 agent 三层门禁思路 |
| 可观测（trace/token/cost、langfuse exporter） | P0.8 |

**真正全新、必须从零写**：① MiniAgent 本体（loop+工具）② 进程隔离沙箱 ③ coding 专属 grader（test/constraint/patch/trajectory）。

---

## 14. 任务计划（里程碑制，标 建/抄/只讲 + 验收）

### M0 · 骨架与模型调用 [建]
- 项目骨架（backend/frontend/datasets/artifacts）；模型调用接口（复用你熟的 provider 封装）。
- 验收：能发起一次带 tools 的 completion 并拿到结构化 tool_calls。

### M1 · MiniAgent V1 [建] — 闭环的心脏
- Agent loop + 5 工具 + trace JSONL + max_steps/timeout + 命令/路径白名单 + 进程隔离（temp git worktree）。
- 验收：在 mini_store 一个简单 bug 上**端到端修好并导出 git diff**；全部 tool_call 入 trace；超步/超时能安全终止；命令失败不崩主进程。

### M2 · 内部 benchmark + 确定性评测 + CLI 闭环 [建 + 抄]
- mini_store + 6 条 case（4 bugfix + 2 spec）+ hidden/regression + reference patch。
- **benchmark 自检**：base 上目标测试失败、ref patch 后通过、回归通过、hidden 不被 agent 读到。
- Test/Constraint/Patch grader；Task/Strict Success；CLI 一键跑全套出 JSON/CSV（聚合抄 ft_diag_agent）。
- 验收：一条命令跑完 6 条；每条从固定 commit 起、hidden 不可见、有 patch+log+评分；失败能定位到具体测试或约束；能分别报 Task 与 Strict。

### M3 · FastAPI + 最小 React [建 + 抄]
- Experiment/Trial/Trace API + SSE 进度；React：Experiment Detail + Trace Viewer + Diff。
- 验收：前端创建/触发 experiment、实时看进度、看每条 case 结果、看完整 trace、看最终 patch、筛失败 case。

### M4 · V1→V2 回归对比 [建] — 两岗的 money shot
- 分析 V1 失败轨迹 → 定 Failure Taxonomy → 取前 3 类主因 → 改 prompt/工具/完成策略成 V2 → 同配置跑 → Version Compare。
- 验收：一次明确迭代；每项改动对应哪类失败说得清；V1/V2 同环境；展示总体提升 + 局部回归（improved/regressed），不只单一总分。

### M5 · 网易加分：EvalPlus 协议学习 + LLM-Judge + kappa [建 + 抄]
- HumanEvalPlusAdapter（先完成 schema 子集，再增量到少量官方实例 Smoke Slice；Base/Plus、Pass@1）。
- 最小 LLM-Judge grader（跑 1 条 Code Review case）：结构化输出 + 强制引用 + swap 平均 + temperature=0。
- 复用 `judge_meta_eval.py`：给 judge 结果配 kappa 与"不达标降级"叙事。
- 验收：少量官方实例按正式协议可复现，结果明确标注样本规模和不可外推边界；judge 每条判定带引用、能说清偏差处理；能展示 judge 的 kappa。

### 只讲不建（准备口述 + 架构图）
- Docker 全量沙箱；SWE-bench 全量（留 adapter 接口 + 可选 1 条 Lite）；Terminal-Bench/Harbor；PostgreSQL；成本看板全量。

**最低成功线（时间被压缩也要守住）**：M1+M2+M4 = 一个能真实改仓库跑测试的 agent、6 条自检过的 golden case、Task/Strict 双指标、一次 V1→V2 回归。哪怕前端只剩 Trace+Compare 两页，闭环也成立、可 demo。

---

## 15. 面试 Demo（8–10 分钟）+ 双岗话术

1. **抛问题**：Coding Agent 不能只看最终文本，要看仓库末态 / 测试 / 工具轨迹 / 约束遵循 / 稳定性成本。
2. **架构三分**：Coding Agent ≠ Evaluation Pipeline ≠ React Console；评测是**确定性 pipeline，不是又一个评测 agent**。
3. **成功 case**：搜代码 → 跑测试 → 改文件 → 再跑 → hidden 过 → 最终 patch。
4. **失败 case**：没读关键文件 → 重复命令 → 局部测试过就提前结束 → hidden 失败 → Failure Tag。
5. **V1 vs V2**：Task/Strict 提升、约束违规下降、成本/工具变化、新增成功 + 回归 case。
6. **收尾（方法论）**：发现失败模式 → 改 harness → 固定变量回归 → 验证提升 → 查局部回归；**"换 harness 同模型能差很多分"→ scaffold 决定成败**（呼应 WildClawBench）。

**网易话术**：主打"我不只是用评测，我建过评测系统，还评测过评测器本身（judge meta-eval / kappa），评分是确定性门禁 + LLM 评审带引用的混合方式，和 WildClawBench 同源；私有集天然无污染"。
**蚂蚁话术**：主打"把实验能力打磨成过程可追溯、结果可观测、质量可管理的交付；用 eval 驱动 harness 迭代 = 把 AI 用成稳定生产力"；agent 核心（规划/记忆/多 agent）用 ft_diag_agent 的 generator-critic 审核 agent 配合讲。

## 16. 简历/口述表述

**简历**：构建仓库级 Coding Agent 与自动化评测平台，支持代码搜索、文件修改、Shell 执行、测试反馈与多轮错误恢复；设计 SWE-bench 风格无污染内部 Golden Dataset，实现 EvalPlus-schema 子集与 SWE-bench 协议兼容验证；建立覆盖功能正确性、隐藏/回归测试、工具轨迹、指令合规、成本与稳定性的多维指标，含 LLM-as-Judge 与 judge meta-eval（kappa）；通过失败归因与同配置版本回归驱动 Agent Harness 迭代。

**口述**：重点不是复刻 Claude Code，而是走通 Coding Agent 从执行到评测再到优化的闭环。评测系统我做成确定性 pipeline 而非又一个评测 agent，隔离环境跑任务、采集轨迹与 patch，再结合隐藏/回归测试、约束检查与可选 Judge 出多维结果；judge 本身用人工 gold 集量 kappa、不达标降级。之后基于 V1 失败轨迹调工具/prompt/完成条件，用相同数据集完成 V2 回归验证。

---

## 17. 公开 Benchmark 学习目标与实施等级（2026-07 补充）

本项目不以有限资源复刻商业级 Coding Agent 或全量公开排行榜为目标，而以**掌握并实操主流评测的标准数据、环境、执行、oracle、评分、统计和报告协议**为目标。采用三级口径：

1. Protocol Study：研究并文档化官方方法。
2. Compatibility/Smoke Slice：少量官方实例、完整官方流程，用于验证会不会正确评。
3. Benchmark Evaluation：按官方规模与规则运行，才可报告正式 benchmark 结果。

当前事实口径：mini_store 是 9 case 的私有 Golden Dataset；HumanEval 部分是 10 题
EvalPlus-schema 自建/精选子集；SWE-bench 部分是官方 schema + 自建 Compatibility Sample。
三者都不能包装成完整公开排行榜成绩。

实施顺序：

- P0：HumanEval+/EvalPlus 少量官方实例 Smoke Slice。
- P0：SWE-bench 少量真实官方实例 Smoke Slice。
- P1：先完成 Terminal-Bench/Harbor 与 OctoBench 的 Protocol Study 文档。
- P1：前两项完成后，再分别实现少量官方任务/环境的 Smoke Slice。

详见 [`docs/benchmark_methodology_and_roadmap.md`](docs/benchmark_methodology_and_roadmap.md)。

进展（2026-07-12）：HumanEval+/EvalPlus B1 已完成。固定 EvalPlus 0.3.1 和 seed `20260712`，
5 个官方任务 canonical oracle Base/Plus=1.00；DeepSeek v4-flash Base=1.00、Plus=0.80。
该结果只证明协议实操与严格测试的区分作用，不作为完整 benchmark 分数。

## 18. 统计增强路线

- P0：case-level/cluster bootstrap 置信区间；V1/V2 exact McNemar 或配对 bootstrap；按难度、任务类型、仓库、语言分层；每成功任务 token/cost/tool/time。
- P1：首次 target/full-suite 通过时间、测试失败恢复率、case 区分度。
- P2：项目—总分相关性；需多个模型/Agent 和更大 case 集后再实施。

同一 case 的 repeats 不视为独立 case；小样本下“不显著”只表示证据不足。报告同时给 effect size、区间、样本数、预算与选择偏差。

## 19. Golden Dataset 扩充路线

- P0：普通逻辑/缓存/异常恢复 bugfix；单/跨模块和适度欠定义 spec；instruction following；行为保持/API 迁移 refactor。
- P1：带证据的 code review；用缺陷检出率/mutation score 评测的 test generation；performance；security；并发/资源泄漏/事务一致性。
- P2：multi-turn 需求澄清、需求变化与跨轮状态；需要用户模拟器、多轮 oracle、稳定性评测和答案泄漏防护。

优先级以业务价值、确定性 oracle 可行性、实现复杂度和对现有覆盖的增益共同决定，不以 case 数量为唯一目标。
