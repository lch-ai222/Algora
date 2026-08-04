# 横向评测报告 v1：模型受控下的 Claude Code vs 自研 MiniAgent

**日期**：2026-08-05　**实施等级**：私有 benchmark，非公开排行榜
**一句话结论**：预算宽裕时三个 scaffold 的功能成功率无差别；把 wall-clock 收到 120s，Claude Code 掉到 0.50 而 MiniAgent v3.1 保持 1.00。差异只能归因于 scaffold —— 三者用的是同一个模型。

---

## 1. 为什么这个对比与常见的横向评测不同

通常的 Agent 横向对比是"Claude Code 用 Claude、我的 agent 用别的模型"。赢了也说不清是 **scaffold 强**还是**模型强**。

智谱同时提供 OpenAI 兼容与 Anthropic 兼容端点，因此可以让三个 scaffold 跑**同一个 glm-5.2**：

| 系统 | 接入方式 | 端点 |
|---|---|---|
| Claude Code 2.1.220 | headless CLI，`--output-format stream-json` | `open.bigmodel.cn/api/anthropic` |
| MiniAgent v3.1 | in-process，planner + context 管理 | `open.bigmodel.cn/api/paas/v4` |
| MiniAgent v2 | in-process，仅 V2 纪律 | 同上 |

模型、温度、benchmark、预算契约全部相同，**唯一变量是 scaffold**。

---

## 2. 预算契约

三个框架的"步"不是一回事：Claude Code 的 `--max-turns` 数的是 agentic turn，MiniAgent 数的是模型轮次；上下文上限对 Claude Code 无法施加（其 adapter 只能拿到 usage 总量，拿不到逐轮 `prompt_tokens`）。

因此**主约束取 wall-clock —— 唯一被三者以相同方式执行的预算**。步数与 token 只作诊断量记录。

两档取值由无约束实测标定（4 case × 2 repeats/arm）：

| arm | min | median | max |
|---|---|---|---|
| Claude Code | 51s | 156s | 267s |
| MiniAgent v3.1 | 92s | 138s | 237s |
| MiniAgent v2 | 71s | 138s | 209s |

- **宽松档**：无约束 / 400s。实测最长 267s，两者等价。
- **收紧档 120s**：低于三者的共同中位数（138–156s）、高于各自最快 case（51/92/71s）。对三个 arm 的中位数近似等距，不偏袒任何一方。

---

## 3. 结果

长程 suite `mini_store_long`（4 case），glm-5.2，temperature=0。

| arm | 预算 | n | **Task** | **Strict** | 中位耗时 | 工具调用 | 模型轮次 | 失败模式 |
|---|---|---|---|---|---|---|---|---|
| Claude Code | 宽松 | 8 | **1.00** | **1.00** | 156s | 27.8 | 46.4 | — |
| Claude Code | **120s** | 12 | **0.50** | 0.50 | 120s | 14.6 | 24.1 | TIMEOUT ×6 |
| MiniAgent v3.1 | 宽松 | 12 | 1.00 | 0.83 | 98s | 34.7 | 19.1 | — |
| MiniAgent v3.1 | **120s** | 12 | **1.00** | 0.83 | 79s | 34.3 | 18.8 | — |
| MiniAgent v2 | 宽松 | 12 | 1.00 | 0.92 | 108s | 31.8 | 19.2 | — |
| MiniAgent v2 | **120s** | 12 | 0.92 | 0.83 | 76s | 34.3 | 19.3 | TIMEOUT ×1 |

**收紧档逐 case**：

| case | Claude Code | v3.1 | v2 |
|---|---|---|---|
| long-refactor-pricing-api | 0.33 | 1.00 | 1.00 |
| long-crossmodule-returns | 0.33 | 1.00 | 0.67 |
| long-cascade-reservation | 1.00 | 1.00 | 1.00 |
| long-build-and-cli | 0.33 | 1.00 | 1.00 |

### 3.1 区间与配对检验（B3）

`scripts/compare_experiments.py`，收紧档（120s）：

| 指标 | Claude Code | MiniAgent v3.1 | 差值 | 不一致 trial | exact McNemar |
|---|---|---|---|---|---|
| Task | 0.500 ［0.333, 0.833］ | 1.000 ［1.000, 1.000］ | −0.500 | 6/12（全部同向） | **p = 0.0312，显著** |
| Strict | 0.500 ［0.333, 0.833］ | 0.833 ［0.500, 1.000］ | −0.333 | 4/12 | p = 0.1250，不显著 |

区间为 case 聚类的 bootstrap（同一 case 的 repeats 相关，按独立处理会把区间收窄约 √repeats 倍）。

**两者回答的是不同问题，都要报**：4 个聚类的区间很宽（Claude Code 的 Task 落在 0.33–0.83），说明**这个样本钉不住具体数值**；但配对检验能给出显著结果，因为 **6 个不一致 trial 全部指向同一方向** —— 一致的 trial 不携带任何关于"谁更好"的信息，两样本检验会把这个结构丢掉。

"不显著"（Strict）**不等于"两者相同"**，只是样本不足以排除偶然。

---

## 4. 解读

### 4.1 宽松预算下没有区分度

三个 scaffold 的 Task 全是 1.00。**这个 suite 在时间充裕时对三者都太容易** —— 与本项目此前在短程 suite 上的发现一致（模型阶梯换到 GLM-4.5-air 仍是 1.00，只有免费的最弱档到 0.84）。

结论不是"三者一样强"，而是**这个测量在这个预算下没有分辨力**。

### 4.2 收紧后差异来自"单位时间的产出"，不是能力

120s 内：

- Claude Code 发出 **14.6** 次工具调用、24.1 个模型轮次
- MiniAgent 发出 **34.3** 次工具调用、18.8 个模型轮次

**Claude Code 的模型轮次更多、工具调用更少** —— 它把时间花在推理上。宽松时这不影响结果（最终 Task/Strict 双 1.00），时间一紧就交不出东西：6 次 TIMEOUT，全部集中在三个较重的 case 上。

### 4.3 但 Claude Code 是唯一 Strict 满分的

宽松档下它是三者中唯一 **Task 与 Strict 同为 1.00** 的。MiniAgent 两个版本的 Strict 是 0.83 / 0.92 —— 功能对了，但改动范围或工程约束上有瑕疵。

所以完整的表述是：

> **在这个任务分布上，Claude Code 的 scaffold 用延迟换取了工程规范性。预算宽裕时是净收益（唯一双满分），预算紧张时是净损失（Task 掉一半）。**

因为模型受控，这个权衡只能归因于 scaffold 设计。

### 4.4 v3.1 vs v2：compaction 在收紧下体现价值

v2 在 120s 下掉到 0.92（`crossmodule-returns` 0.67 + 1 次 TIMEOUT），v3.1 保持 1.00。与此前 H3 消融的结论方向一致：**context 管理是自研框架里真正起作用的那一块**。

---

## 5. 有效性与边界

### 5.1 必须同时陈述的限制

- **样本量**：12 trial/组（Claude Code 宽松档 8）。Task 的方向由配对检验支持（p=0.0312），但**具体数值钉不住**：bootstrap 区间 ［0.333, 0.833］。Strict 的差值不显著。
- **4 个聚类**是统计声明的约束点。以 case 为聚类单位时，**加 case 才能收窄区间，加 repeats 不能** —— 脚本在聚类数不足时会主动警告，而不是给出一个看起来比设计更精确的数字。
- **4 个 case、单一模型、两个预算点。** 以 case 为聚类单位时区间宽度主要由 case 数决定，4 个聚类不足以支持效应量声明。
- **收紧档取值影响结论。** 120s 是照三者共同中位数选的；换一个值可能重排。
- **Claude Code 宽松档的产物已丢失。** 见 §5.3。
- **成本不可比。** 走第三方端点，CLI 自报的 `total_cost_usd` 按 Anthropic 价目表计算，语义错误，因此记为 `unavailable`。token 数可比。

### 5.2 已识别并修复的测量缺陷

本次对比在采集过程中暴露了三个缺陷，任何一个未修都会让报告结论错误：

| 缺陷 | 若不修，报告会说 |
|---|---|
| 物化仓库缺 `.gitignore`，pytest 字节码被算作源码改动 | "Claude Code 在 8 个 trial 里 6 个工程不合规"（实际 Strict=1.00） |
| `--max-wall-clock` 只穿给 MiniAgent 分支，Claude Code 在 120s 限额下实跑到 258s | "Claude Code 在收紧预算下毫发无损"（**结论方向相反**） |
| 外部 adapter 无逐调用记录，token 汇总报 0 | "Claude Code 零 token 消耗" |

第二个尤其关键：它记录的 `timeout_seconds=120` 是对的，**只有执行路径没接上** —— 产物看起来完全正常。

### 5.3 Claude Code 宽松档的证据等级

补跑该 arm 时智谱 glm-5.2 额度耗尽（429 `余额不足`），补跑前已删除原目录，**原始产物丢失**。现有两个一致的独立来源：

1. **`cal2/cc` 完整产物存在**：8 trial，无约束，Task 1.00 / Strict 1.00，最长 267s。因 267s < 400s，"无约束"与"400s 限额"在经验上等价。本报告表格用的是这份。
2. **运行日志保留了原 cc_400 的逐 case 聚合**：12 trial，4 个 case 全部 Task 1.00 / Strict 1.00。产物不可复现，仅作佐证。

两者一致，但该 arm 的证据等级低于其余五组，**不应与它们等同看待**。

---

## 6. 可复现信息

```bash
# Claude Code（Anthropic 兼容端点）
ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic ANTHROPIC_AUTH_TOKEN=... \
python -m codeagent_eval.runner --adapter claude_code --claude-model glm-5.2 \
  --max-wall-clock 120 --suite datasets/mini_store_long --repeats 3 --workers 3

# MiniAgent（OpenAI 兼容端点）
LLM_PROVIDER=zhipu python -m codeagent_eval.runner --adapter mini_agent --harness v3 \
  --model glm-5.2 --max-completion-tokens 4096 \
  --max-wall-clock 120 --suite datasets/mini_store_long --repeats 3 --workers 3
```

每个 trial 落盘 `config.json`（含完整溯源：模型、预算、adapter 版本、费率表版本）、`trajectory.jsonl`（归一化轨迹）、`native/`（Claude Code 原始 stream-json）、`patch.diff`、`grader-results.json`、`failure-tags.json`。

---

## 7. 下一步

1. ~~**扩 case**~~ **已完成（2026-08-05）**：长程 suite 由 4 条扩到 8 条，达到 `MIN_USEFUL_CLUSTERS` 门槛，bootstrap 不再携带警告。**本报告表内数值仍是 4 簇下测得的**，未重跑，因此 §5.1 的区间宽度限制对本版结论依然成立；重跑矩阵是下一步。新增的 4 条中 `long-order-snapshot` 与 `long-release-accounting` 在 Task / Strict 上都有明确区分度，预期能实质收窄区间。
2. **补第三方开源 adapter**（aider / mini-swe-agent）：三个 arm 里两个是自研，第三方样本只有 Claude Code 一个。
3. ~~**补上下文遗忘检测器**~~ **已完成（2026-08-05）**：三类检测器均已进入 `scripts/scan_failure_modes.py`。历史 artifacts 上 canary 遵守率 1.000、decay +0.000；新增 `long-release-accounting` 后出现首个 early→late 衰减正例，但成因仍只能表述为“遗忘或策略改变”的推断，不能越过可观察证据。
4. **补齐 Claude Code 宽松档**：待额度恢复后按修复后的预算链路重跑，把 §5.3 的证据等级拉平。
5. ~~**补 repro 交付链**~~ **已完成（2026-08-05）**：失败 trial 可生成脱敏诊断包与自动 replay fixture；重放无需模型，并通过 suite 指纹与 grader signature 防止 oracle 漂移被误报成回归。仍缺第二外部 adapter、静态报告/跨 Agent UI 和官方 SWE-bench 实例。
