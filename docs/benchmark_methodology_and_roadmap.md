# Coding Agent Benchmark 方法论与路线图

本文定义 Algora 对 benchmark 的统一认知、对外表述、评测层级、能力覆盖与后续实施顺序。目标不是以有限资源复刻商业级全量排行榜，而是**按照主流 benchmark 的正式数据结构、环境契约、执行协议、评分口径和有效性边界，完成少量官方实例的可复现实操，并能解释每一步为什么这样做**。

## 1. 名词与对外口径

### 1.1 mini_store

`mini_store` 不是业内通用 benchmark，而是 Algora 自建的私有评测集：

- 定位：SWE-bench-style repository benchmark / private Golden Dataset。
- 当前规模：1 个 Python 仓库、9 个 case（4 bugfix、2 spec、3 regression-trap）。
- 价值：无污染、答案和缺陷可控、可定向构造失败模式、适合快速重复回归。
- 边界：不能用于公开排行榜或与外部系统直接横向比较，也不能代表多语言、大仓库或完整软件工程分布。

### 1.2 HumanEval、HumanEval+ 与 EvalPlus

三者不是并列关系：

```text
HumanEval（原始函数级题集）
   └── 增加大量、更严格的测试 → HumanEval+

EvalPlus（数据增强与评测框架）
   ├── HumanEval+
   ├── MBPP+
   └── EvalPerf
```

- HumanEval：函数签名/docstring → 生成函数实现，以隐藏单测和 pass@k 衡量正确性。
- HumanEval+：保留 HumanEval 题目，扩展测试输入和边界条件，用于识别“原始测试能过、严格测试会失败”的脆弱解。
- EvalPlus：承载 HumanEval+、MBPP+、EvalPerf 的数据、执行与报告框架；不仅是一个题集。

Algora 当前 `benchmark/humaneval_plus.py` 是 **EvalPlus-schema 的 10 题自建/精选子集验证**，不是完整官方 HumanEval+ 接入，也不应对外称作正式 HumanEval+ 成绩。

### 1.3 SWE-bench

Algora 已实现官方 instance 字段兼容和 `test_patch → candidate patch → FAIL_TO_PASS/PASS_TO_PASS → resolved` 流程，但当前只在自建小仓库上完成 Compatibility Sample。它证明适配器契约能工作，不等于跑过正式 SWE-bench 实例或获得排行榜成绩。

### 1.4 Terminal-Bench 与 OctoBench

- Terminal-Bench：面向真实终端环境中的长程任务，重点是环境状态、构建/调试、系统操作、长程规划和最终状态验证；2.x 使用 Harbor 作为官方执行框架。
- OctoBench：面向 repository-grounded、scaffold-aware 的指令遵循，重点区分“任务完成”与“持续遵守仓库/脚手架约束”。它与 Algora 的 Task Success / Strict Success 双指标高度互补。

JD 中出现的 “OctoCodingBench” 与公开论文 “OctoBench” 命名可能存在口径差异；实施前以官方论文、仓库和数据版本为准，不在文档中武断混用。

## 2. 三种评测实施等级

所有公开 benchmark 接入必须标明等级，禁止用低等级结果暗示完整排行榜能力。

| 等级 | 定义 | 必须满足 | 可对外声明 |
|---|---|---|---|
| Protocol Study | 阅读并复现数据结构、环境、评分和统计方法 | 方法文档、字段映射、风险与验收标准 | “研究/实现了协议设计” |
| Compatibility / Smoke Slice | 用少量官方实例按官方协议端到端运行 | 官方实例、规定环境、oracle 自检、候选执行、原始结果留档 | “在 N 个官方实例上完成协议一致的样例验证” |
| Benchmark Evaluation | 按官方数据、环境、规模和报告要求运行 | 版本锁定、完整运行、失败重试规则、可复现实验记录 | 在明确版本和规模前提下报告 benchmark 结果 |

Algora 的近期目标是达到 **Smoke Slice**，不是追求全量排行榜：

- 少量不等于随意：实例可以少，但流程、环境、oracle、评分和标注必须尽量符合官方规范。
- 样例结果用于验证“会不会正确评”，不用于估计模型总体能力。
- 报告必须同时写样本规模、筛选规则、资源预算和不可外推边界。

## 3. Benchmark 能力覆盖矩阵

| Benchmark | 主要构念 | 任务粒度 | 主要 oracle | Algora 当前等级 | 主要缺口 |
|---|---|---|---|---|---|
| mini_store | 仓库检索、bugfix/spec、验证纪律、约束遵循 | 小型 Python 仓库 | target/regression/hidden + 静态约束 | 完整私有 benchmark | 单仓库、单语言、case 少、难度偏低 |
| HumanEval+/EvalPlus | 函数正确性、边界稳健性、可选性能 | 单函数 | base/plus tests、pass@k | 自建 schema 子集 | 未用完整官方数据/执行器，题目饱和 |
| SWE-bench | 真实 issue resolution、大仓库、多文件修改 | 真实仓库 issue | FAIL_TO_PASS/PASS_TO_PASS | Compatibility Sample | 未跑官方实例、未完成真实环境复现 |
| Terminal-Bench | 长程终端操作、环境状态、构建/调试 | 容器化端到端任务 | 任务测试脚本/环境末态 | Protocol Study（本文已完成） | 未接 Harbor、未验证 Docker 与 oracle |
| OctoBench | scaffold 指令遵循、持续约束、轨迹检查 | 仓库级任务 | task checks + objective checklist | Protocol Study（本文已完成） | 未接官方环境，Task/Strict 尚缺真实分离案例 |

这张表描述的是 **benchmark taxonomy / capability coverage / construct validity**，不是统计上的“区分度”。

## 4. 有效性概念必须分清

### 4.1 构念与覆盖范围

回答“这个 benchmark 想测什么、有没有测到”：例如 HumanEval+ 测函数级正确性，SWE-bench 测真实 issue resolution，Terminal-Bench 测终端长程任务，OctoBench 测 scaffold 指令遵循。

### 4.2 Case 区分度

回答“某个 case 能否区分强弱系统”。若所有系统都通过，case 可能太易；所有系统都失败，可能太难、环境有问题或 oracle 有缺陷。当前 mini_store 在强模型上 8/9 case 饱和，说明闭环有效但对 V1/V2 的区分度有限。

建议后续按 case 统计：

- 通过率与方差；
- reference/none/弱模型/强模型的单调性；
- 不同 Agent harness 下的稳定性；
- 是否出现环境失败、oracle 失败或非预期捷径。

### 4.3 项目—总分相关性

回答“某个 case 的得分是否与套件总能力同方向变化”。它需要足够多的 case 和多个有能力差异的系统。当前 9 case × 主要 2 个 Agent 版本不足以稳定估计，因此：

- 现在只记录方法与数据需求，不输出正式相关系数；
- 建议至少积累多个模型/Agent 组合和 30+ case 后再分析；
- 相关性低不自动等于坏题：它也可能测到总分未覆盖的独立构念，需要结合标签和人工审查解释。

## 5. 公开 Benchmark 实施顺序

### P0-A · HumanEval+/EvalPlus 官方 Smoke Slice

目标：理解函数级 benchmark 的官方数据、生成、隔离执行、base/plus 判定与 pass@k。

计划：

1. 引入官方、固定版本的 EvalPlus 数据和执行协议，不继续用自建题冒充官方题。
2. 选择少量官方 HumanEval+ 实例，记录选择规则；先运行 canonical solution 验证 oracle。
3. 候选代码在隔离环境执行，分别报告 base/plus；保留超时、异常和原始样本。
4. 样例报告明确 `N`、版本、模型、temperature、采样数和资源预算。
5. 后续可研究 MBPP+ 与 EvalPerf，但不作为首个 Smoke Slice 的阻塞项。

状态：**B1 已完成（2026-07-12）**。EvalPlus 0.3.1、固定 seed 的 5 个官方任务、官方
HumanEvalPlus-Mini、canonical oracle gate 和官方 sanitizer/evaluator 已端到端跑通；DeepSeek
v4-flash Base=1.00、Plus=0.80。详见 [`evalplus_smoke_report_v1.md`](evalplus_smoke_report_v1.md)。

验收：少量官方实例端到端可复现；base/plus 差异能解释；不声称完整 HumanEval+ 排名。✅

### P0-B · SWE-bench 官方 Smoke Slice

目标：理解真实仓库 issue 的 materialization、环境复现、patch 契约和 resolved 判定。

计划：

1. 选择少量官方、可在当前资源内复现的 Verified/Lite 实例，记录筛选偏差。
2. 按官方容器/环境要求运行 oracle/gold，先证明实例在本环境可评。
3. Agent 运行期间隔离 `test_patch` 和 gold patch；捕获候选 patch 后再评分。
4. 保留 FAIL_TO_PASS、PASS_TO_PASS、环境构建、超时和 patch apply 结果。
5. 结果标注为 official-instance smoke slice，不外推为完整 SWE-bench 能力。

验收：至少一个真实官方实例完成 oracle + candidate 全流程；环境失败与 Agent 失败可区分。

### P1-A · Terminal-Bench 文档与后续 Smoke Slice

当前先完成 Protocol Study，待 HumanEval+ 与 SWE-bench 增量开发和评测完成后再实现。

#### 评测方向与重点

- **核心构念**：Agent 能否在真实终端环境中自主完成长程、可执行、可验收的工作，而不只是生成一段代码。
- **重点能力**：任务拆解、命令与工具选择、文件/进程/依赖状态管理、编译和调试、失败恢复、长程上下文保持。
- **任务粒度**：容器内端到端交付，可能包含多文件、依赖安装、构建、服务启动、数据处理或系统配置。
- **评分重点**：以任务测试脚本和环境末态为主，不用模型代判可程序验证的成功；轨迹和效率用于诊断。

#### 标准流程

1. 固定 Terminal-Bench 数据集版本、Harbor 版本、Agent adapter、模型和预算。
2. 获取官方 task package，检查 instruction、容器、资源和测试脚本契约。
3. 先运行 oracle/reference，证明任务和环境在本机可评；oracle 失败的任务不得进入 Agent 比较。
4. 为每个 trial 创建全新容器，按相同初始状态启动 Agent；记录终端输入输出、文件变化、进程状态、时延和资源。
5. Agent 结束后由官方测试脚本/环境检查评分；将 task failure 与 infra/timeout/evaluator failure 分开。
6. 清理容器和产物，只保留脱敏的 config、trajectory、grader、日志摘要与复现信息。

#### 建议指标

- task resolved/reward、oracle validity、timeout/infra failure rate；
- pass@k 与 pass^k、time-to-success、失败后恢复率；
- tool/command/model-call 数、token/cost per success；
- 非法操作、环境逃逸、无关副作用与清理完整性。

#### 主要风险

- Docker、CPU/内存、网络和外部依赖差异造成环境噪声；
- 长任务成本高，少量样例不能外推总体能力；
- oracle 或任务测试脚本本身可能失效；
- Agent 可能利用测试脚本、缓存、残留容器或外部网络走捷径。

后续 Smoke Slice 选择少量官方任务，先跑 oracle，再跑 MiniAgent/外部 Agent adapter。验收重点是 Harbor adapter、容器生命周期、环境失败分类和官方 grader 契约，而不是分数高低。

### P1-B · OctoBench 文档与后续 Smoke Slice

#### 评测方向与重点

- **核心构念**：Agent 在完成仓库任务的同时，能否持续遵守 scaffold、仓库规则和任务约束。
- **重点能力**：多层指令发现与优先级、跨步骤持续遵循、修改范围控制、工具/流程要求、最终交付规范。
- **关键分离**：task solving 与 instruction compliance 分开计分，避免“测试过了”掩盖工程违规。
- **评分重点**：尽量使用客观 checklist、文件/轨迹/环境检查；只有不可程序判断的语义质量才使用经过 meta-eval 的 Judge。

#### 标准流程

1. 固定官方环境、task、scaffold 类型、规则文件、Agent/模型和预算。
2. 在 trial 开始前注入对应 scaffold 指令，记录指令作用域、优先级和持续时间。
3. Agent 运行时捕获完整轨迹、文件变化、命令和测试；保护规则、grader 和测试文件不被篡改。
4. 独立计算 task checks 与 objective checklist，再合并为 Task Success、Compliance/Constraint Success 和 Strict Success。
5. 报告 compliance gap：完成任务但违反规则的比例，以及按规则类别拆分的失败。
6. 对失败进行轨迹归因，区分没发现规则、理解错误、忘记约束、工具越权和主动绕过。

#### 建议指标

- Task Success、Compliance Pass、Strict Success、Task→Strict drop；
- checklist item pass rate、按 scaffold/规则类型的宏平均；
- forbidden action rate、test/rule tampering rate、修改范围违规率；
- 首次违规步骤、持续遵循长度、失败恢复和成本。

#### 主要风险

- 规则写得含糊或相互冲突，导致 oracle 不唯一；
- checklist 过度贴合某个实现，测成“猜标准答案”而非遵循约束；
- Agent 读取或修改 grader/测试/规则获得捷径；
- 只使用 LLM-Judge 会把客观合规问题变成不稳定的主观评分。

当前 Protocol Study 已完成。后续 Smoke Slice 重点验证多层项目指令注入、约束持续时间、客观 checklist、Task/Strict 分离、轨迹检查以及防止 Agent 通过修改测试/规则文件作弊。

## 6. 统计与报告方法路线图

| 方法 | 要解决的问题 | 推荐方法 | 实施优先级 | 当前限制 |
|---|---|---|---|---|
| 置信区间 | 点估计掩盖不确定性 | case-level/cluster bootstrap；二项指标可补 Wilson 区间 | P0 | 9 case 时区间会很宽，应如实呈现 |
| V1/V2 配对检验 | 同一 case 上差异是否稳定 | exact McNemar；连续成本用配对 bootstrap/置换检验 | P0 | 当前只有一个差异 case，统计功效很低 |
| 分层统计 | 总分掩盖结构性短板 | difficulty/task_type/repo/language 分组，宏平均+样本数 | P0 | 当前 repo/language 只有一个层级 |
| 成本归一化 | 提升是否以不成比例成本换取 | token/cost/tool/time per successful trial；预算约束下成功率 | P0 | provider 成本字段需统一 |
| 首次通过时间 | Agent 多快达到可交付末态 | first target pass、first full-suite pass、time-to-success | P1 | trace 需区分测试范围和节点 |
| 测试恢复率 | 失败后能否诊断并恢复 | 有失败测试的 trial 中，后续修复并全过的比例 | P1 | 需定义可恢复失败和环境失败 |
| Case 区分度 | case 是否能区分系统 | 多系统通过率、单调性、方差、异常捷径审查 | P1 | 需要更多 Agent/模型 |
| 项目—总分相关性 | case 是否与套件总体同向 | point-biserial/相关性 + 构念标签解释 | P2 | 当前样本与系统数不足 |

统计纪律：

- 同一 case 的 repeats 不是独立的新 case，置信区间不能把所有 trial 简单当独立样本。
- “不显著”不等于“两版本相同”；小样本通常只是证据不足。
- 同时报 effect size、区间、样本数和资源预算，不只报 p 值。
- V1/V2 必须同模型、同 benchmark 版本、同预算、同温度、同环境。

## 7. 私有 Golden Dataset 任务路线图

优先级综合考虑业务价值、确定性 oracle 可行性、当前架构改造量和对现有能力的增益。

### P0 · 优先扩充

| 类型 | 要解决的问题 | 推荐 oracle | 难度 |
|---|---|---|---|
| Bugfix：普通逻辑/缓存/异常恢复 | 扩大真实缺陷模式，降低当前简单算术题占比 | target + regression + hidden | 中 |
| Spec Coding：单模块/跨模块/适度欠定义 | 测需求理解、模块组合和合理澄清边界 | 行为测试 + 不变量 + 约束 | 中高 |
| Instruction Following | 让 Task Success 与 Strict Success 真正分离 | 功能测试 + 禁止依赖/API/路径 checklist | 中 |
| Refactor：行为保持/接口迁移 | 测结构改造而非只修一行 | 全量回归 + API contract + patch 规则 | 中高 |

### P1 · 第二阶段

| 类型 | 要解决的问题 | 推荐 oracle | 难度 |
|---|---|---|---|
| Code Review | 找真实缺陷、风险分级、引用代码证据 | 人工 gold + 可验证缺陷 + Judge meta-eval | 高 |
| Test Generation | 防止生成空洞或迎合实现的测试 | 已知缺陷检出率 + mutation score + coverage | 高 |
| Performance | 识别“功能正确但不可用” | 正确性门禁 + 稳定性能阈值/复杂度输入 | 高 |
| Security | 路径遍历、命令注入、权限/敏感信息 | exploit/negative tests + 静态规则 | 高 |
| Bugfix：并发/资源泄漏/事务一致性 | 覆盖生产常见但更难稳定复现的缺陷 | 可控调度、资源探针、事务不变量 | 高 |

Test Generation 绝不能只检查“生成的测试能通过”；否则无断言测试也会得分。必须至少结合已知缺陷检出率或 mutation testing。

### P2 · 多轮与长期状态

Multi-turn 覆盖需求澄清、用户变更要求、约束冲突、测试失败后反馈和跨轮状态保持。它需要用户模拟器、信息释放策略、多轮 oracle、模拟器稳定性评测和答案泄露防护，不能在当前 runner 上简单拼接消息冒充多轮 benchmark。

## 8. Golden Dataset 质量控制

每个新增 case 至少记录：

- 来源、能力标签、任务类型、难度与适用语言；
- 缺陷/需求的真实性和唯一性说明；
- reference solution 与 oracle；
- visible/regression/hidden tests；
- 允许和禁止的改动；
- contamination 与历史泄漏检查；
- reference/none 自检；
- flaky/repeatability 检查；
- 预期失败类型和可能捷径；
- 数据版本、修订记录与废弃原因；
- 需要人工标注时的双人复核、冲突仲裁和一致性指标。

## 9. 对外报告模板

每次公开 benchmark 样例报告必须包含：

1. benchmark 名称、官方版本、数据来源与实施等级；
2. 样本数、筛选规则及选择偏差；
3. 模型、Agent/harness、prompt 版本、温度、预算、repeats；
4. 环境、依赖、Docker 镜像或 commit；
5. oracle 自检结果；
6. 功能、严格合规、稳定性、成本和失败分类；
7. 点估计、区间和适用的配对比较；
8. 哪些结论可以外推、哪些不能；
9. 原始 trace、patch、grader 和复现命令位置。

推荐表述：

> 在 N 个官方实例上完成 protocol-conformant smoke evaluation，用于验证评测流程，不作为公开排行榜或总体能力估计。

## 10. 参考入口

- EvalPlus：<https://github.com/evalplus/evalplus>
- SWE-bench：<https://github.com/swe-bench/SWE-bench>
- Terminal-Bench：<https://github.com/harbor-framework/terminal-bench>
- Harbor：<https://www.harborframework.com/docs/tutorials/running-terminal-bench>
- OctoBench 论文：<https://arxiv.org/abs/2601.10343>
