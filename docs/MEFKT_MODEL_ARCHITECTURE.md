<!--
MEFKT / MEFKT-Lite 模型架构与输入输出说明
@Project : adaptive-edu
@File : MEFKT_MODEL_ARCHITECTURE.md
@Author : Qintsg
@Date : 2026-08-25
-->

# MEFKT / MEFKT-Lite 模型架构

## 1. 文档定位

本文档单独记录当前工程中 MEFKT 与 MEFKT-Lite 的模型结构、输入输出契约、时间特征、遗忘机制和跨窗口状态传递方式，供训练、推理和后端接入使用。

当前方案的目标是“足够好用、可训练、可部署”，不要求对某一篇论文做逐层严格复现。更重要的约束是：基础模型训练完成后，新课程可以直接接入；如果有少量新课程交互数据，只允许做小规模参数高效校准，不重新训练整个基础模型。

代码实现位于 [mefkt_models.py](../backend/scripts/mefkt_models.py)、[mefkt_encoders.py](../backend/scripts/mefkt_encoders.py) 和 [mefkt_model_config.py](../backend/scripts/mefkt_model_config.py)，统一训练入口位于 [mefkt_train.py](../backend/scripts/mefkt_train.py)，数据适配说明位于 [MEFKT_TRAINING.md](../backend/scripts/MEFKT_TRAINING.md)。已有 checkpoint 还可以使用 [validate_mefkt_checkpoint.py](../backend/scripts/validate_mefkt_checkpoint.py) 单独执行 CPU/GPU 运行时门禁，无需重新训练。

## 2. 设计目标与边界

### 目标

- 根据学习者历史答题记录，预测下一道题答对的概率。
- 同时利用题目、学科、知识点、难度、答题间隔和真实答题耗时。
- 让新课程、新学科、新题目可以依靠课程内容表示直接接入，而不是依赖训练时固定的题目/学科词表。
- 通过窗口上下文和可序列化状态支持长序列推理。
- 提供 GPU 上效果优先的完整模型，以及少于 4 核 CPU 无 GPU 场景可用的轻量模型。
- 完整模型单次推理显存控制在 8 GiB 以内。

### 边界

模型是知识追踪模型，不是解题模型。它不读取题干并生成答案，而是根据题目元数据和学习者行为预测“答对概率”。

新课程冷启动必须提供可解释的内容元数据：至少是题目文本、课程/学科名称、知识点名称或描述中的一部分，最好还包括难度等结构化属性。模型会在课程发布阶段用固定的多语言句向量编码器生成内容向量，在线 MEFKT 只消费这个固定维度向量，不加载文本编码器，也不为新课程扩充词表。

如果新课程只有全新的题目 ID，没有题干、知识点、难度或其他内容描述，那么不重新训练就无法推断新题难度；这不是模型结构可以弥补的信息缺失。

## 3. 总体架构

MEFKT 与 MEFKT-Lite 共享题目编码、时间编码、遗忘门、GRU 状态更新和预测头。区别是 MEFKT 在 GRU 状态序列上增加了因果 Transformer 和跨窗口 memory；Lite 省略 Transformer，仅保留 GRU 路径。

```text
题目 ID ───────────────┐
学科/知识点 ID ────────┤── 已见 ID 记忆分支 ───────┐
题目文本/课程描述 ────┤── 冻结多语言内容向量 ─────┤
难度等结构化属性 ─────┘── 数值特征分支 ──────────┤  开放世界题目表示
                                                │
答题间隔 gap ── 时间编码 ──────────────────────┤
真实答题耗时 ── 时间编码 ──────────────────────┤
                                                ├─ 自适应遗忘 ── GRUCell ── 学习者状态
答题结果 answer ───────────────────────────────┘                         │
                                                                         │
                                      MEFKT：因果 Transformer + 64 slots ─┤
                                      Lite ：直接使用 GRU 状态              │
                                                                         │
                         当前候选题 + 当前 gap ── 预测头 ── logit / 概率
```

### 3.1 模型类型

| 模型 | 主要结构 | 运行目标 | 当前混合词表参数量（14,732 道题） |
|---|---|---|---:|
| `MEFKT` | 开放世界题目表示 + 自适应遗忘 GRU + 6 层、8 头因果 Transformer + 64 个 memory slots | 正常 GPU 推理 | 15,268,737 |
| `MEFKT-Lite` | 开放世界题目表示 + 自适应遗忘 GRUCell + MLP 预测头 | 少于 4 核 CPU、无 GPU 推理 | 1,160,433 |

参数量随题目词表增长，主要增加项是题目 ID embedding。上表来自当前“SLAM 语言学习 + ASSISTments 数学”混合词表的工程测量值，不是与题目数量无关的常数。

## 4. MEFKT 完整模型

### 4.1 结构

```text
每道交互
  ├─ OpenWorldItemEncoder：已见 ID 记忆 + 固定内容向量 + 统计属性
  ├─ gap 编码：距离上次交互的小时数
  ├─ response-time 编码：当前交互答题耗时（仅用于本次交互后的状态更新）
  ├─ answer embedding：答题结果（仅用于本次交互后的状态更新）
  ├─ AdaptiveForgetGate：逐状态维度衰减上一时刻状态
  └─ GRUCell：得到当前交互后的 recurrent state

整个窗口
  ├─ 拼接上一窗口的最多 64 个 Transformer memory
  ├─ 加正弦位置编码
  ├─ 6 层 TransformerEncoder，8 个 attention heads，FFN 1536
  ├─ 上三角 causal mask，当前时刻不能读取未来交互
  └─ 保留最后 64 个有效上下文作为下一窗口 memory

预测
  └─ 作答前状态 + 候选题表示 + 当前 gap → MLP → 一个 logit
```

Transformer 的输入是每个时间步的 GRU 状态，而不是题干 token。这样可以把题目语义和行为时间信息先压缩到学习者状态，再由注意力建模窗口内较远的学习轨迹。

### 4.2 默认配置

| 组件 | 配置 |
|---|---:|
| 题目 ID embedding | 192 |
| 学科 embedding | 64 |
| 知识点 embedding | 128 |
| 数值特征编码 | 64 |
| 融合后的题目表示 | 384 |
| 答案 embedding | 32 |
| gap 编码 | 32 |
| response-time 编码 | 32 |
| recurrent state | 384 |
| Transformer 层数 | 6 |
| attention heads | 8 |
| Transformer FFN | 1536 |
| 跨窗口 memory | 64 个状态向量 |
| dropout | 0.20（当前 Full 默认；用于抑制题目 ID 记忆） |
| 冻结内容向量输入 | 384 |

## 5. MEFKT-Lite 轻量模型

Lite 使用和完整模型相同的题目、时间、遗忘和 GRU 语义，但不运行 Transformer，不保存 attention memory。它在每道题上只维护一个 128 维 recurrent state，适合低核心 CPU 上作为后端服务的一部分运行。

### 默认配置

| 组件 | 配置 |
|---|---:|
| 题目 ID embedding | 64 |
| 学科 embedding | 16 |
| 知识点 embedding | 32 |
| 数值特征编码 | 32 |
| 融合后的题目表示 | 128 |
| 答案 embedding | 16 |
| gap 编码 | 16 |
| response-time 编码 | 16 |
| recurrent state | 128 |
| Transformer | 不使用 |
| attention memory | 不使用 |
| dropout | 0.10 |
| 冻结内容向量输入 | 384 |

Lite 和 Full 的 `forward()`、`encode_history()`、`predict_next()` 形状保持一致，部署层可以通过 profile 配置切换模型，而不需要改变业务字段。

## 6. 输入契约

### 6.1 序列输入

训练和历史编码使用以下四个等长张量：

| 字段 | 形状 | 类型 | 单位 / 取值 | 含义 |
|---|---|---|---|---|
| `items` | `[B, L]` | `long` | 题目内部索引；`-1` 可表示 padding 或未知题目 | 交互题目 |
| `correct` | `[B, L]` | `long` | `0` 或 `1` | 本次交互是否答对 |
| `gaps` | `[B, L]` | `float` | 小时，最小约 1 秒 | 距离上一道题的时间 |
| `response_times` | `[B, L]` | `float` | 秒，限制在 0.1 至 3600 | 学生完成当前题目的真实耗时 |

其中 `B` 是 batch size，`L` 是窗口长度。padding 位置必须由 `sequence_valid_mask=False` 表示；未提供 mask 时，`items=-1` 按 padding 处理。未知题目可以使用 `items=-1`，但必须由 `sequence_valid_mask=True` 标记，否则不会更新 GRU 状态，也不会进入有效 loss。

### 6.2 题目静态元数据

模型初始化时为每道题提供：

| 元数据 | 进入模型的方式 |
|---|---|
| `item_id` | 题目 embedding |
| `subject_id` | 学科 embedding |
| `skill_ids` | 多个知识点 embedding 后 masked mean pooling |
| 难度 | 归一化数值特征 |
| 交互频率 | `log1p` 后归一化数值特征 |
| 平均交互间隔 | 训练集统计后 `log1p`、归一化 |
| 平均答题耗时 | 训练集统计后 `log1p`、归一化 |
| `part` | 归一化数值特征；数据集没有该字段时可置零 |
| tag 数量 | 归一化数值特征 |
| 发布时间 | 相对基准时间的归一化数值特征 |
| 题目/课程内容向量 | 固定 384 维冻结多语言句向量，经过 MEFKT 内部投影 |

这些统计特征只能使用训练集统计量构造，避免把验证集或测试集标签信息泄漏到训练过程。

### 6.3 通用 canonical CSV

不同学科、不同数据集先适配为统一事件表：

```text
user_id,item_id,timestamp,correct,response_time_seconds,subject_id,skill_ids
```

其中：

- `user_id`：学习者标识；
- `item_id`：全局唯一题目标识，建议使用 `数据集:学科:题目` 前缀；
- `timestamp`：Unix 秒、Unix 毫秒或 ISO-8601；
- `correct`：`0/1`、布尔值或等价文本；也可用 `user_answer` 和 `correct_answer` 替代；
- `response_time_seconds`：答题耗时秒数；也兼容 EdNet 的 `elapsed_time`；
- `subject_id`：稳定的学科/领域标识；
- `skill_ids`：多个知识点，支持分号、逗号或空格分隔；
- 建议额外提供 `course_name`、`item_text`、`subject_name`、`skill_texts`、`language` 和 `difficulty`，供新课程冷启动生成内容向量。

CSV 应按 `user_id`、`timestamp` 排序。不同数据源中同名的题目或知识点不要直接合并，例如使用 `ednet:skill_123`、`assistments:skill_123`，除非已经确认它们语义完全一致。

### 6.4 新课程冷启动接口

新课程不需要加入训练词表。课程发布时执行一次：

```text
课程题目文本/课程名/学科名/知识点描述
        ↓
冻结多语言句向量编码器
        ↓
item_content_embeddings.npz  [题目数, 384]
        ↓
MEFKT / MEFKT-Lite 直接推理
```

当前工具 [prepare_mefkt_content_embeddings.py](../backend/scripts/prepare_mefkt_content_embeddings.py) 使用固定的 `paraphrase-multilingual-MiniLM-L12-v2` 生成内容向量。该编码器只在课程发布或数据预处理阶段运行；低核心 CPU 在线推理只加载 `.npz` 中的向量和 MEFKT-Lite 参数。

开放世界表示由四部分组成：

1. 已见 `item_id` embedding：记忆训练数据中的题目行为，属于增强分支；
2. 已见 `subject_id`、`skill_id` embedding：建模训练数据中稳定出现的类别关系，属于增强分支；
3. 固定内容向量：新题、新课程仍可通过文本和知识描述获得主要题目表示；
4. 难度、题型、标签数量等 7 维数值特征：提供不依赖词表的结构化先验。

因此，已见题目使用“记忆 + 内容”，未见题目使用“OOV 记忆 + 内容 + 结构化特征”。模型不能把新题目塞进旧 embedding 表，而是通过动态元数据输入编码。

## 7. 输出契约

### 7.1 窗口前向

调用：

```python
logits, mask, state = model(
    items,
    correct,
    gaps,
    response_times,
    sequence_features=dynamic_numeric_features,
    sequence_content_features=content_embeddings,
    sequence_valid_mask=valid_mask,
)
```

返回：

| 输出 | 形状 | 含义 |
|---|---|---|
| `logits` | `[B, L]` | 每个时间步的答对 logit |
| `mask` | `[B, L]` | 哪些位置是有效题目 |
| `state` | `SequenceState` | 当前窗口结束后的学习者状态 |

概率使用 `sigmoid(logits)` 得到。训练目标是当前交互的 `correct`，但第 `t` 个 logit 使用的是第 `t` 题作答前的状态；第 `t` 题的答案和答题耗时只会用于更新到第 `t+1` 题可见的状态，因此不会把当前标签泄漏给当前预测。

### 7.2 候选题预测

调用：

```python
probabilities, state = model.predict_next(
    history_items,
    history_correct,
    history_gaps,
    history_response_times,
    candidate_items,
    candidate_gaps,
    candidate_features=candidate_numeric_features,
    candidate_content_features=candidate_content_embeddings,
    history_valid_mask=history_valid_mask,
)
```

返回：

- `probabilities`：形状 `[N]`，每个候选题独立的答对概率；
- `state`：历史编码完成后的 `SequenceState`，可以继续传给下一次窗口编码。

候选题尚未作答，所以预测时不传候选题的 `correct` 和 `response_time`。候选题当前间隔 `candidate_gaps` 可以参与预测；候选题答完以后，再把真实结果和真实耗时追加到历史中更新状态。

新课程中的未知题目使用 `candidate_items=-1`，同时传入：

```text
candidate_features          [N, 7]
candidate_content_features [N, 384]
history_valid_mask          [1, L]
```

历史中出现未知题目时，`forward()` / `encode_history()` 使用对应的 `sequence_features`、`sequence_content_features` 和 `sequence_valid_mask`。`sequence_valid_mask=True` 表示这是有效但可能未知的题目；padding 必须为 False。已知题目可以省略动态特征，模型会从训练时保存的题目目录读取。

### 7.3 新课程小规模校准

基础模型冻结时，新课程可以直接推理。若上线后积累了少量本课程行为，当前已实现课程级 logit 适配器，而不是修改整个模型：

```text
冻结 MEFKT 主干
  └─ 预测 logit 的温度和偏置（共 2 个可训练参数）
```

先使用 [evaluate_mefkt_unseen_course.py](../backend/scripts/evaluate_mefkt_unseen_course.py) 导出冻结基础模型 logits，再用 [fit_mefkt_course_adapter.py](../backend/scripts/fit_mefkt_course_adapter.py) 按学习者切分训练/验证并拟合 [mefkt_course_adapter.py](../backend/scripts/mefkt_course_adapter.py)。适配器只学习新课程整体难度和校准偏差，参数规模固定为 2，并保留基础模型作为回退。默认标注交互不足 200 条时拒绝拟合，直接使用基础模型结果。FiLM 或低秩内容适配器仍是后续可选增强，不属于当前已实现能力。

## 8. 答题耗时如何进入模型

答题耗时不是展示字段，而是行为信号：同样答对的一道题，快速完成和长时间完成通常代表不同的掌握稳定性。

实现上，`response_times` 经过三个稳定变换后送入小型 MLP：

```text
log1p(response_time)
sqrt(log1p(response_time))
1 / (1 + log1p(response_time))
```

耗时有两个用途：

1. 与题目表示、答题结果一起形成当前交互输入，更新 GRU 状态；
2. 按题目聚合成平均耗时静态特征，帮助新题或低频题获得可解释的先验。

预测当前题目时不使用当前题目未来才会产生的耗时。历史题目的真实耗时可以完整使用；缺失值使用保守默认值并限制到合理范围。

## 9. 自适应遗忘机制

### 9.1 动机

只使用一个全局遗忘率会让所有学科、知识点和状态维度以同一种速度衰减。当前实现改为每个状态维度都有基础遗忘速度，并根据当前题目和时间条件调整。

### 9.2 计算方式

设上一时刻状态为 `h`，当前题目的条件向量为 `c`，间隔小时数为 `g`：

```text
r = softplus(base_log_rate + 0.5 * tanh(Wc + b)) + epsilon
h_decay = h * exp(-r * log1p(g))
```

这里的 `r` 是 `[state_dim]` 维向量，不是一个标量。因此不同状态维度可以分别学习短期记忆、长期记忆或学科相关的稳定性。

衰减后的 `h_decay` 作为 GRUCell 的 hidden state；当前题目的题目表示、答题结果、gap 和答题耗时经过投影后作为 GRUCell 输入，产生本次交互后的新状态。

### 9.3 仍需用数据验证的部分

该机制在结构上表达了遗忘，但遗忘是否“更优化”不能只看代码。正式训练后还应按 gap 分桶比较 AUC、Brier 和校准误差，并与普通 GRU、DKT 或固定遗忘率 ablation 对照，确认收益来自遗忘机制而不是数据泄漏或题目 ID 记忆。

## 10. Transformer 与窗口状态

### 10.1 完整模型的因果注意力

MEFKT 将窗口内的 recurrent state 与上一窗口 memory 拼接，加入正弦位置编码，然后经过 6 层 TransformerEncoder。使用上三角 causal mask，位置 `t` 不能读取未来位置 `t+1` 及之后的信息。

当前窗口结束时，保留最后 64 个有效 Transformer 上下文作为下一窗口 memory。padding 位置通过 `memory_mask` 和序列有效 mask 排除。

### 10.2 `SequenceState`

```text
SequenceState.recurrent   [B, state_dim]
SequenceState.context     [B, state_dim]
SequenceState.memory      [B, 64, state_dim]    # 仅 Full
SequenceState.memory_mask [B, 64]               # 仅 Full
```

Lite 的 `memory` 和 `memory_mask` 为 `None`。状态可以调用 `detach()` 截断训练反向图，适合跨窗口或在线服务保存。

### 10.3 重叠窗口与 target mask

训练数据采用“历史上下文重叠、目标不重复”的方式。以窗口长度 200、上下文长度 64 为例：

```text
窗口 1：输入 0..199       目标 0..199
窗口 2：输入 136..335     目标 200..335
窗口 3：输入 272..471     目标 336..471
```

窗口 2 中的 `136..199` 只负责恢复历史状态，不再次计入 loss。`target_mask` 与有效题目 mask 相与后才计算损失。这一规则降低了窗口边界对状态的破坏，也避免重复标签造成训练权重偏移。

## 11. 训练和部署约束

### 11.1 训练输出

统一训练脚本会生成：

```text
best.pt
last.pt
item_vocab.json
subject_vocab.json
skill_vocab.json
runtime_validation.json
run_config.json
training_metrics.jsonl
training_metrics.csv
train.log（集群提交器持久化）
```

checkpoint 中同时保存模型配置、参数量、数据清单、验证集指标和测试集指标。恢复训练时使用 `last.pt`；部署优先使用 `best.pt`。

训练器同时保留 `best_auc.pt` 与 `best_loss.pt`。`best.pt` 是兼容现有部署的 AUC 最优别名；若业务更重视概率校准、期望 loss 或后续阈值决策，可以单独验证并选择 `best_loss.pt`。

v3 训练器默认使用 3 轮线性 warmup，峰值学习率 `6e-5`、中段 `3e-5`、末段 `1e-5`，AdamW weight decay 为 `5e-4`。validation loss 连续 60 轮没有至少 `2e-4` 的实质改善时按平台期停止；显著上升趋势仍作为更快的保护。短程消融确认 v3 在 `6e-5` 时优于 v2，而 `1e-4` 会令 v3 的校准迅速恶化，因此 Full v3 不应沿用 v2 的峰值学习率。

## 11.4 MEFKT v3 显式知识追踪

v3 在保留自适应遗忘 GRU 和 Full 因果 Transformer 的同时，增加三条结构化通道：

```text
logit(correct)
  = domain_scale × (student_ability - item_difficulty)
  + domain_bias
  + 0.25 × bounded_temporal_residual
```

- `student_ability`：全局时序上下文、相关 skill memory 与在线行为统计共同生成；
- `item_difficulty`：题目 ID、学科、知识点、数值属性和内容向量共同生成；
- `domain_scale/domain_bias`：每个训练学科两个轻量校准参数；未知课程回退共享未知槽；
- `bounded_temporal_residual`：只允许提供有限幅度的时序修正，避免黑盒残差吞掉 IRT 主关系。

每名学习者额外维护按 skill 寻址的状态：

```text
skill_memory       [B, known_skills + external_slots, skill_memory_dim]
skill_attempts     [B, slots]
skill_successes    [B, slots]
skill_last_seen    [B, slots]
elapsed_hours      [B]
positive_streak    [B]
negative_streak    [B]
session_steps      [B]
last_items         [B]
```

Full 的 `skill_memory_dim=32`，Lite 为 16。题目只读写自己关联的 skill 槽，未访问槽保持不变。新课程可以为未知题目传入课程内稳定的 `sequence_skill_indices` / `candidate_skill_indices`；这些索引映射到开放课程状态槽，不需要修改基础训练词表。

训练阶段以 35% 概率屏蔽已知题目的 ID embedding，但仍保留内容、skill、subject 和数值属性，迫使共享主干具备对新题目的可迁移能力。推理阶段不随机屏蔽。

为避免语言领域的数据量压制数学领域，训练 loss 默认是普通逐事件 BCE 与等学科 BCE 的 50/50 混合；validation/test 同时保留总体和分学科指标。

### 11.2 质量门槛

- Lite 参数量默认不超过 5,000,000；
- Full 参数量默认不超过 50,000,000；
- 冻结内容编码器版本必须写入 checkpoint 和课程向量 sidecar 元数据；
- CUDA 可用时，运行时检查峰值 allocated/reserved 显存是否不超过 8 GiB；
- CPU 检查输出有限、形状正确且 Lite 参数量低于门槛；
- 训练指标至少记录 AUC、ACC、Brier、ECE、样本数和正例比例；
- 正式上线前必须与多数类 baseline、普通 GRU 或现有 MEFKT 产物进行同一测试集回放。

### 11.3 推理选择

| 场景 | 建议 |
|---|---|
| GPU 推理服务、需要较完整的长窗口建模 | `MEFKT` |
| 少于 4 核 CPU、无 GPU、服务进程还要承担其他工作 | `MEFKT-Lite` |
| 新题目只有题干 ID，没有题目元数据 | 可以 OOV 运行，但质量会下降 |
| 新课程有题干/知识点描述和固定内容向量 | 可以直接接入；有少量交互时可做小适配器校准 |
| 新课程只有 `subject_id`、`skill_ids`，但没有语义描述 | 可以运行，但跨课程零样本质量不应承诺 |

## 12. 当前验证结论

截至 2026-09-08，代码层面已经验证：

- Full 和 Lite 能由同一训练入口构建；
- Full 和 Lite 都包含固定 384 维内容向量适配分支，且不会增加在线文本模型依赖；
- 未知题目可以用 `item=-1` 和外部数值/内容特征完成前向；
- CPU 上的 Lite、Full、canonical CSV 和混合公开数据 smoke 均能完成训练、评估与前向；
- checkpoint 可以保存和加载；
- `SequenceState` 可以跨窗口传递；Full memory 已回归验证不会因 padding 与 causal mask 组合产生 NaN；
- 重叠窗口的 target mask 不会把上下文重复计入 loss；
- Windows 项目环境已通过 CUDA 源锁定 `torch 2.11.0+cu130`，`uv sync` 后 CUDA 可用；
- 现有 Full checkpoint 的 GPU 推理门禁通过，峰值保留显存为 0.1016 GiB，峰值已分配显存为 0.0903 GiB，低于 8 GiB 上限；同时 CPU 2 线程门禁通过；
- Full CUDA 训练 smoke 已完成 1 轮，训练 loss 为 0.44755，验证/测试 AUC 为 0.7172/0.7301，训练后运行时门禁通过，峰值保留显存为 0.3008 GiB。
- v3 Full 参数量约 15.60M，RTX 3050 本机 200 步推理峰值保留显存约 0.316 GiB；Lite 约 0.26M 参数；均满足部署门槛。
- v3 当前答案和当前答题耗时因果性、只更新关联 skill、外部 skill 槽、IRT 单调性、旧 v2 checkpoint 加载、分段学习率和领域平衡 loss 均有自动回归测试。
- 同数据同配置 6 轮短程消融中，v3 第 3 轮 validation loss/AUC 为 `0.50880/0.76686`，优于 v2 同轮的 `0.51408/0.76032`；v3 在 `1e-4` 出现不稳定，默认峰值已修正为 `6e-5`。

本机已完成 1,098,343 条语言与数学混合交互的 Lite 单轮训练，验证/测试 AUC 为 0.7843/0.7785；仅使用语言课程训练后，把数学课程全部题目作为 OOV 的真正课程留出评估中，Lite AUC 为 0.6191。后者说明内容分支具备可测的零样本信号，但距离“任意课程均足够好用”仍有明显差距。最终结论必须等待集群上的多轮 Full/Lite 训练、更多领域数据和业务回放。

## 13. 后续工作

1. 在集群上使用当前混合 canonical 数据和固定内容向量完成 Full/Lite 多轮对照训练。
2. 增加许可证明确的科学等第三领域数据，减少基础模型对语言和数学两个领域的偏置。
3. 继续以“留出完整课程/学科”的方式评估冷启动，并加入实际新建课程业务回放。
4. 做固定遗忘率、无 response-time、无内容向量、无 Transformer memory 等 ablation，确认每个改进确实带来收益。
5. 在两参数校准器收益不足时，再评估课程级 FiLM/低秩内容适配器，并保持基础模型回退策略。
6. 集群训练完成后执行 8 GiB GPU 推理门禁、少核 CPU benchmark、校准与导出验证。
