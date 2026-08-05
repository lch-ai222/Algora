# 横向评测报告 v2：四个 scaffold，同一个 glm-5.2，紧预算档

**日期**：2026-08-05　**实施等级**：私有 benchmark，非公开排行榜
**规模**：4 arm × 8 case × 2 repeats = 64 trial，wall-clock 120s，infra 失败 0

**一句话结论**：这一版**没有得出四个 scaffold 之间的可靠排序**。唯一达到显著的比较全部指向 Cline，而 Cline 在这个预算下 16/16 被杀、只有 1 条动过文件——那是**下限效应，不是能力测量**。三个真正跑起来的 arm 之间差距为 0.13–0.31，本设计对它们的功效只有 1–32%。

这一版买到的不是结论，是**真实效应量**——以及据此算出的、下一版需要多大样本。

---

## 1. 设计

| 项 | 取值 |
|---|---|
| 模型 | glm-5.2，四个 arm 全部相同 |
| Claude Code 2.1.220 | Anthropic 兼容端点 `open.bigmodel.cn/api/anthropic` |
| Cline 3.0.49 | OpenAI 兼容端点 `open.bigmodel.cn/api/paas/v4` |
| MiniAgent v3.1 / v2 | 同上 |
| 预算 | wall-clock 120s（唯一被四者以相同方式执行的预算） |
| 样本 | 8 case × 2 repeats/arm |

只跑紧档，因为此前实测**宽松预算下所有 arm 都是 1.00，没有分辨力**；且 120s 对四个 arm 都已有定义，而宽松档需要为 Cline 重新标定。

---

## 2. 结果

| arm | Task 95% CI | Strict 95% CI | 工具调用 | 模型轮次 | 耗时中位 | token/trial |
|---|---|---|---|---|---|---|
| Claude Code | **0.812** ［0.562, 1.000］ | **0.750** ［0.500, 0.938］ | 21.0 | 38.0 | 115s | 22k |
| MiniAgent v2 | 0.625 ［0.312, 0.875］ | 0.500 ［0.188, 0.812］ | 28.0 | 21.5 | 126s | 148k |
| MiniAgent v3.1 | 0.500 ［0.250, 0.750］ | 0.438 ［0.188, 0.688］ | 28.0 | 15.5 | 125s | 112k |
| Cline | 0.000 ［0.000, 0.000］ | 0.000 | 7.0 | 6.0 | 125s | 95k |

区间为 case 聚类 bootstrap（8 簇，**不再携带"聚类数不足"警告**）。成本四个 arm 全部 `unavailable`——都走第三方端点，各自 CLI 的价目表不描述该端点。

### 2.1 逐 case

| case | Claude Code | v2 | v3.1 | Cline |
|---|---|---|---|---|
| long-refactor-pricing-api | 0.50 | 0.50 | 0.50 | 0.00 |
| long-crossmodule-returns | 1.00 | 1.00 | 0.50 | 0.00 |
| long-cascade-reservation | 1.00 | 1.00 | 0.00 | 0.00 |
| long-build-and-cli | 1.00 | 1.00 | 0.50 | 0.00 |
| **long-discount-rounding** | **0.00** | **0.00** | **0.00** | **0.00** |
| long-tax-single-source | 1.00 | 1.00 | 1.00 | 0.00 |
| long-release-accounting | 1.00 | 0.50 | 1.00 | 0.00 |
| long-order-snapshot | 1.00 | 0.00 | 0.50 | 0.00 |

`long-discount-rounding` 在 120s 下**四个 arm 全零**，对本档的区分度贡献为零。

### 2.2 配对检验（exact McNemar + Holm 校正）

四个 arm 产生 **6 个配对检验**。未校正地各按 α=0.05 读，全局零假设下族错误率是 1−0.95⁶ ≈ **26.5%**。因此每个 p 值都配一个 Holm 校正值，**族层面的声明应当读校正值**。

| 比较 | Task 差值 | raw p | **Holm p** | Strict 差值 | raw p | **Holm p** |
|---|---|---|---|---|---|---|
| Claude Code − Cline | +0.812 | 0.0002 | **0.0015** ✓ | +0.750 | 0.0005 | **0.0029** ✓ |
| v2 − Cline | +0.625 | 0.0020 | **0.0098** ✓ | +0.500 | 0.0078 | **0.0391** ✓ |
| v3.1 − Cline | +0.500 | 0.0078 | **0.0312** ✓ | +0.438 | 0.0156 | **0.0625** ✗ |
| Claude Code − v3.1 | +0.312 | 0.1250 | 0.3750 ✗ | +0.312 | 0.1250 | 0.3750 ✗ |
| Claude Code − v2 | +0.188 | 0.2500 | 0.5000 ✗ | +0.250 | 0.1250 | 0.3750 ✗ |
| v2 − v3.1 | +0.125 | 0.7266 | 0.7266 ✗ | +0.062 | 1.0000 | 1.0000 ✗ |

**校正当场改变了一个结论**：`v3.1 − Cline` 的 Strict 未校正 p=0.0156 会被读成显著，Holm 后是 0.0625，**不显著**。多重比较校正是在这次跑之前几小时才补的，随即就改了一条结论。

---

## 3. 为什么这一版不给排序

### 3.1 唯一显著的比较，对手是没跑起来的 arm

Cline 的 16 个 trial **全部被 wall-clock 杀掉**，工具调用中位数 7（它在 400s 下是 11–14），**16 条里只有 1 条动过任何文件**。它不是答错，是没来得及开始。

所以"Claude Code 显著优于 Cline"这句话的信息量约等于"120s 不够 Cline 启动"。三个真正产出工作的 arm 之间，**没有任何一对达到显著**。

### 3.2 这是我的一个标定失误

120s 这个紧档是在**只有三个 arm 时**按它们的中位数（138–156s）标定的。加入 Cline 后我测了它的 glm-5.2 耗时（完成 1 条 188s，其余撞满 400s），据此提醒了**宽松档**需要重标——却没有回头检查 120s 对四臂矩阵是否还成立。

120s 是另外三个 arm 中位数的约 0.85 倍，却不到 Cline 的 0.3 倍。**它对四个 arm 不是同一个约束**。

### 3.3 功效：设计对真实差距严重不足

跑之前我用旧 4-case 数据的效应量（0.50 vs 1.00）做过功效模拟，得到"8 case × 2 repeats = 87%"。8-case 套件更难，把差距压到了 0.13–0.31。按**实测**效应量重算：

| 比较 | 真实差距 | repeats=2 | =4 | =6 | =10 |
|---|---|---|---|---|---|
| Claude Code − v3.1 | +0.312 | **32%** | 90% | 99% | 100% |
| Claude Code − v2 | +0.188 | **2%** | 43% | 77% | 98% |
| v2 − v3.1 | +0.125 | **1%** | 4% | 11% | 27% |

`v2 − v3.1` 即使跑到 10 repeats（80 trial/arm）也只有 27%——**加 repeats 解决不了，那需要加 case**。这与项目一贯的结论一致：repeats 买"有没有差异"，cases 买"差异有多大"。

**试点的作用正是如此**：它买的不是结论，是让下一版可以按真实效应量定样本，而不是按猜测。

---

## 4. 可以说的机制观察（描述性，非检验）

**Claude Code 的形状与 MiniAgent 相反**：38 个模型轮次、21 次工具调用——**轮次多、动作少**，把时间花在推理上；MiniAgent 是 15–22 轮次、28 次调用。这与 v1 报告的方向一致。

**token 差一个数量级**：Claude Code 22k/trial，MiniAgent 112–148k。同样 120s、同样模型。Claude Code 的上下文管理明显更省——但这是描述，不是受控比较。

**v3.1 低于 v2（0.500 vs 0.625）**，与此前 4-case 上的方向相反。p=0.73，**不构成任何声明**，但值得单独查：v3 相对 v2 多了 planner、context 管理与 scratchpad，此前消融显示 context 管理是正效应。8-case 上是否反转，需要专门的消融实验回答。

---

## 5. 有效性与边界

- **样本**：16 trial/arm，8 簇。区间已不携带聚类不足警告，但对 0.13–0.31 的差距功效不足。
- **唯一显著的比较全部涉及 Cline**，而那是下限效应。
- **120s 对 Cline 不是可比约束**，见 §3.2。
- **成本四臂均不可得**：全部走第三方端点，各 CLI 自报成本按错误价目表计算，记为 `unavailable` 而非伪造数值。
- **单一预算点、单一模型。** 换预算可能重排。
- **`long-discount-rounding` 在本档无分辨力**（四臂全零）。

---

## 6. 下一版怎么设计

1. **给 Cline 一个能跑起来的预算点**。要么把紧档提到它的下限之上（实测 >400s），要么改用**相对预算**（各 arm 自身中位数的固定比例），后者测的是 scaffold 效率而非绝对速度。两者回答不同问题，都合法，但必须选定并声明。
2. **Claude Code vs v3.1 用 repeats=4**（90% 功效，约 +64 trial）。
3. **v2 vs v3.1 需要更多 case**，不是更多 repeats——或者改为直接消融（去掉 planner / context / scratchpad），那是比黑盒比较更直接的问法。
4. 补宽松档，让"预算宽裕时无差别"这一条在 8 case 上也成立。

---

## 7. 可复现信息

```bash
# MiniAgent v3.1（OpenAI 兼容端点）
LLM_PROVIDER=zhipu python -m codeagent_eval.runner --adapter mini_agent --harness v3 \
  --model glm-5.2 --max-completion-tokens 4096 \
  --suite datasets/mini_store_long --repeats 2 --workers 3 --max-wall-clock 120

# Cline（OpenAI 兼容端点）
python -m codeagent_eval.runner --adapter cline --cline-model glm-5.2 \
  --suite datasets/mini_store_long --repeats 2 --workers 3 --max-wall-clock 120

# Claude Code（Anthropic 兼容端点）
ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic ANTHROPIC_AUTH_TOKEN=... \
python -m codeagent_eval.runner --adapter claude_code --claude-model glm-5.2 \
  --suite datasets/mini_store_long --repeats 2 --workers 3 --max-wall-clock 120
```

矩阵总消耗 **6.03M token**，耗时约 50 分钟（`--workers 3`）。每个 trial 落盘完整溯源、归一化轨迹、原生轨迹、patch、评分与失败归因。
