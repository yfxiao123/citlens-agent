# 样例：`search` 一次检索的报告（节选）

这是现行版 `search` 的一次真实输出（每个 run 目录里都会落一份
`search_report.md`，另有 `pool.jsonl` 文献池和 `exclusions.jsonl` 排除日志）。
主题与上面的毕设示例无关，仅示格式。

---

# CiteLens 检索报告 — 限售解禁事件与股价漂移

生成时间：2026-10-28 01:20:34
检索源：arxiv, semantic_scholar, openalex, crossref
启用家族：agent, oa_title, raw, s2_rec, snowball, survey, web

## 结果

- 候选池：123 篇 → 保留 **60** 篇
- 其中综述 0 篇 · 无 DOI 11 篇 · 无 venue 20 篇
- 排除日志：家族配额 423 · 合并去重 3 · 目标截断 59（`exclusions.jsonl` 逐条带原因码）
- 顺序为 RRF/家族席位序（无 LLM 级联）：引用前由 agent 逐篇判断相关性，
  可先跑 `screen` 做三分带（core / uncertain / likely_off）分流精读

## 家族 → 入池条数

| 家族 | 入池 |
|---|---|
| agent | 356 |
| raw | 37 |
| oa_title | 5 |
| s2_rec | 29 |
| snowball | 30 |
| survey | 0 |

## 逐源健康（ok / empty / failed，按检索 cell 计）

| 源 | ok | empty | failed |
|---|---|---|---|
| arxiv | 2 | 0 | 0 |
| crossref | 2 | 0 | 0 |
| openalex | 2 | 0 | 0 |
| semantic_scholar | 2 | 0 | 0 |

> failed > 0 时必须显式报告：源失败绝不能写成"零命中"。

## 查询反馈（每条查询的实际命中——造词迭代的仪表盘）

agent 拟的每条检索词的命中数逐条列出；命中为 0 的词会被标记，
提示换论文侧的词汇重拟——而不是原词重试。
