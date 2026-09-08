# MEFKT loss 下界分析

## 结论

当前 Full MEFKT 的 validation loss 约 `0.4696`，不能简单判定为欠拟合。基于同一预处理数据的可部署基线如下：

| 方法 | validation loss | test loss | 说明 |
| --- | ---: | ---: | --- |
| 全局正例率 | 0.6036 | 0.6008 | 只预测总体答对率 |
| 学科正例率 | 0.6020 | 0.5990 | 只预测学科先验 |
| 平滑题目难度 | 0.5177 | 0.5204 | 使用训练集题目答对率 |
| 题目难度 + 在线能力 | 0.4824 | 0.4844 | 简单 Rasch/Elo 风格状态更新 |
| MEFKT v2 最佳 loss | 0.4696 | 0.4725 | epoch 160 |

MEFKT 相对全局先验有约 `22.2%` 的 BCE 改善，但相对简单在线能力模型只改善约 `0.0128`。因此现在的主要瓶颈是有效信息量和目标噪声，不是模型层数不足。

## 数据中已经观察到的限制

- 训练目标约 86.98 万，validation 约 10.28 万，test 约 10.82 万。
- 训练集正例率约 `0.7077`，validation 正例率约 `0.7083`。
- 训练中有 713 道题在训练切分没有出现；纯题目 ID 记忆对这些题没有帮助。
- 数学域的题目先验 loss 约 `0.6106`，语言域约 `0.4917`；两个领域的标签噪声和难度结构不同。
- MEFKT v2 的 train loss 在停止时约 `0.4409`，validation loss 约 `0.4761`，差距约 `0.0352`。这是后期轻度过拟合，不是训练集和验证集都无法下降的严重欠拟合。

## 下一版真正值得做的改动

### 1. 加入显式 IRT/Rasch 分解

将预测头改为：

```text
logit(correct) = student_ability(skill, subject, time) - item_difficulty(content, skill, subject) + residual
```

其中 `item_difficulty` 主要由内容、知识点和数值特征生成，题目 ID 仅作为弱增强分支；`student_ability` 使用按知识点寻址的状态更新。这样模型不需要用 384 维隐状态间接学习“学生能力减题目难度”这一低维关系。

### 2. 使用 skill-aware 状态，而不是单一全局状态

目前模型只有一个学习者 recurrent state。下一版建议增加小型 skill memory：每个 skill 保存 16–32 维 mastery，当前题目只读写相关 skill，再用全局 GRU/Transformer 捕捉跨技能迁移。这样对数学域通常比盲目增加 Transformer 层更有效，也能保持 CPU Lite 的规模约束。

### 3. 增加在线可获得的历史统计

优先补充：

- 当前 skill 的历史作答次数和近期正确率；
- 距离上次同 skill / 同题的时间；
- 当前 session 内的题数、连续答对/答错长度；
- 当前题目的尝试次数、历史错误次数；
- 如果业务有记录，再加入 hint、skip、answer type 等行为。

这些特征比继续增加静态 embedding 维度更可能降低 validation loss。

### 4. 改成按领域平衡的多任务训练

共享主干保留通用性，但增加轻量 subject/course calibration head。训练时对数学和语言分别记录 loss，并使用温和的领域平衡权重；新课程没有 head 时回退到共享 head，收集少量数据后只微调校准参数。

### 5. 调整学习率曲线

v2 在第 17 轮降到 `3e-5`，第 22 轮降到 `1e-5`，这对稳定性有帮助，但可能过早限制了主干继续学习。下一次建议：

- 3–5 epoch warmup；
- `1e-4` 保持到约第 10–15 轮；
- `3e-5` 保持至少 10–20 轮；
- 之后再降到 `1e-5` 或 `3e-6`；
- 以 validation loss 为主，最多训练 150–250 epoch；
- 同时保存 `best_loss.pt` 和 `best_auc.pt`。

## 不建议的做法

- 不建议把 Full 模型从 15M 参数直接扩到 50M。
- 不建议继续把最大 epoch 从 1000 提高到更大。
- 不建议使用第 356 轮或任何最后一轮 checkpoint 部署。
- 不建议为了追求更低 train loss 而减弱正则化。

## 推荐决策

如果目标是“当前两个课程的最低 loss”，下一轮应优先做 IRT + skill memory + 领域校准的 v3 小规模对照；如果目标是“新课程直接可用”，则应优先做 skill/content 主干、题目 ID dropout 和完整课程留出测试。两者都不应只通过扩大 Transformer 完成。
