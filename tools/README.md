# tools/ — 一次性测量装置与证据产物

这些不是产品代码（产品在 `citens/` 与 `drivers/`），是一次性的**测量
harness**：每个对应一次具体诊断，结论都写进了对应提交信息与 CHANGELOG。
重跑需要真实网络与各家配额；离线测试套件在 `tests/`，勿混。

**例外：`verify_harness.py` 是长期验收套件**（不是一次性测量）。它用
真实数据家与真实 CLI/MCP 入口跑 34 项检查，覆盖调用面（工具表、退出
码、参数解析）、CLI 同步语义、MCP 默认后台、产物契约（真 JSONL）、
作业生命周期与死任务回收、并发护栏、共享数据家一致性、stdout 压缩
视图、断网下的 embedding 回退、以及 pipeline 修复在产物上的证据。
改动 citlens_cli.py / drivers / screening 后跑它：

```
.venv/Scripts/python.exe tools/verify_harness.py
```

（离线可跑；临时产物写到 gitignored 的 `.verify/`。）

**`verify_online.py` 是联网补充验收**：覆盖离线套件够不到的两项——
真实并发竞争（3 个真搜索作业同时跑 + 第 4 个被拒，不是假状态文件）
与在线端到端（经代理的真实 search → 池/报告落盘 → OpenAlex related
方向的真实 expand）。需要网络（可走 `HTTPS_PROXY` 环境变量）：

```
HTTPS_PROXY=http://127.0.0.1:7897 .venv/Scripts/python.exe tools/verify_online.py
```

（首轮实测 2026-11-06：并发 4/4、三搜索 45 条入池、expand 并入 5 条。
脚本自身一处种子路径错误被诊断修正——记录在 CHANGELOG。）

## 代码（按诊断时间线）

| 脚本 | 回答的问题 | 结论（见提交信息） |
|---|---|---|
| `calibrate_screen.py` | screen 三分带阈值该定在哪 | 0.5 会把 ~77% 池子标进 core；0.65 保持全部金标在 core∪uncertain 的同时 core 缩 5 倍 → 默认值上调 |
| `retest_missed_gold.py` | 八月 ranklab 漏掉的 10 个金标今天还漏吗（raw/标题两臂） | 漏；标题索引臂区分“检索问题 vs 索引覆盖问题” |
| `ablate_vocab.py` | 词汇错配的六臂消融（raw/计划/HyDE×2/阶梯/阶梯+pivot） | raw 0/10，阶梯+pivot 3/10；pivot 独有救回 q4/q10 |
| `measure_candidate_fixes.py` | 候选修复各自的贡献（探针停用词/S2 备胎/relevance 源） | relevance 源 q7/q8/q10@5、q12@12；进生产波后三题复活 |
| `diagnose_missed7.py` | 剩余 7 题逐题验尸 | 四类病因：S2-only 覆盖/近 miss/词汇对但端点拒收/误读 |
| `retest_full_bench.py` | 全 15 题端到端复测（出厂形态：裸题@20 + 阶梯@40 + pivot 臂） | 晴天口径：q3/q8/q12 复活（q12 真 driver #3/173）；S2 配额风暴是下限口径 |

## 产物（results/）

| 文件 | 内容 |
|---|---|
| `ablation_ladder_queries.json` | 10 道漏题的寄存器阶梯变体（后续 harness 复用为“agent 查询”替身） |
| `ablation_vocab.json` | 六臂消融的逐题排名与汇总 |
| `calibration_screen.json` | screen 阈值网格扫描全表 |
| `full_bench_retest.json` | 全 15 题复测终值（晴天、出厂深度） |
| `full_bench_retest_s2down.json` | 同上，S2 配额风暴中的下限口径（36/72 槽被饿死） |
| `full_bench_retest_d20.json` | 同上，全 @20 深度的过严变体（证明 driver 的 agent 腿 @40 是承重设计） |
