# MEFKT-NG 后端默认模型包

这是四来源训练、续训后按验证 NLL 规则选定的 **epoch 136** 模型。`model.safetensors` 只包含模型参数和冻结题目/知识点目录；不含优化器、随机状态或逐轮 checkpoint。`catalog.json` 保存题目与知识点 ID 的索引映射，`model_metadata.json` 保存配置、来源哈希和适用性说明。

后端 `ai_services.services.mefkt.inference.MEFKTPredictor` 默认加载本目录，通过课程题目和知识点构建新的内容目录；旧 `mefkt_model.pt` 保留作显式回滚。在项目后端 Python 环境中验证独立模型包：

```powershell
python scripts/load_mefkt_ng_bundle.py --bundle models/MEFKT_NG --device cpu
```

独立加载、严格 `state_dict` 校验、CPU 前向检查均已通过；全部 23 个权重张量与原选定 checkpoint **逐项完全一致**。对应的测试摘要是 `evaluation_repeated_test.json`，其中测试集已在第 120 轮查看过，因此第 156 轮结果属于同集复评。

默认使用新模型；`KT_MEFKT_NG_BUNDLE_PATH` 可覆盖新模型包目录。遗留的 `KT_MEFKT_MODEL_PATH` 在新模式下不生效，以免旧 `.env` 悄悄重新加载旧模型；仅设置 `KT_MEFKT_RUNTIME=legacy` 时才使用该变量和旧 `.pt` 回滚。在线新课程内容使用训练时相同的 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，首次调用需要该编码器可用；离线环境可通过 `KT_MEFKT_NG_ENCODER_PATH` 提供本地目录。`KT_MEFKT_NG_DEVICE` 默认 `cpu`，可显式选择可用 CUDA 设备。课程目录按内容修订缓存，知识点级旧历史会映射到课程代表题；无对应题目或编码器不可用时 KT 服务使用统计回退。

**请勿把 `model.safetensors` 改名后覆盖旧 `.pt`。** 当前代码已加入 MEFKT-NG 适配器，但尚未部署到远端服务。上线前仍需以真实课程的独立学习者数据验证迁移效果、冷启动与校准；公开数据的测试集已在续训前查看过，第 156 轮测试只属于同集复评。EdNet 与 Junyi 的非商业许可也应在部署前核对。

在本机 50 道题的实际课程只读烟测中，首次请求（加载编码器并建课程缓存）约 12.4 秒，缓存后同样请求约 0.18 秒；这是单机观察值，部署时需做预热与延迟验收。

141 道题、100 条合成历史、10 个目标知识点的另一次本机测试中，首次约 14.6 秒，缓存后约 0.23 秒；不包含真实学生作答。
