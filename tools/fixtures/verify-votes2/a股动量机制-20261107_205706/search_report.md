# CiteLens 检索报告 — A股动量机制

生成时间：2026-11-07 20:57:06
检索源：arxiv, semantic_scholar, openalex, openalex_relevance, crossref
启用家族：agent, oa_title, raw, s2_rec, snowball, survey, web

## 结果

- 候选池：172 篇 → 保留 **60** 篇
- 其中综述 0 篇 · 无 DOI 15 篇 · 无 venue 16 篇
- 文献类型：journal 38 · preprint 7 · working_paper 2（政策机构：NBER 1）
  （doc_type/policy_org 已写入每条记录——学术证据与政策端视角分开读，
  二者的分析框架与关心变量并不相同）
- 家族共识：全召回票池 892 条中 ≥2 家族 6 篇 · ≥3 家族 0 篇；
  入池 172 条中 ≥2 家族 4 篇（保留 0 篇）
  （`found_by` 已写入每条 pool 记录，入池口径可直接复算；全召回口径包含未入池记录）
- 排除日志：家族配额 724 · 合并去重 1
  · 目标截断 107（`exclusions.jsonl` 逐条带原因码）
- 顺序为 RRF/家族席位序（无 LLM 级联）：引用前由 agent 逐篇判断相关性，
  可先跑 `screen` 做三分带（core / uncertain / likely_off）分流精读
- 收工信号见「饱和与停止信号」块（机械估计，信号不是结论）；锚点核验
  （`audit` 工具）仍需单独跑——覆盖率高不等于锚点齐全

## 学科层（economics）——检测词命中：policy-corpus records in the pool

> 经济学层已启用：区分统计显著与经济显著——给出效应量级、参照基准与对应的政策取舍含义，显著但量级微小的效应是政策非事件；政策笔记（FEDS Notes 等）明说的数据缺口与未解问题是「找」的直接证据；近一两年的 NBER 工作论文即前沿，开创性工作用前向引文（expand）追踪；「定」须陈述现实利害。完整层见 skill: disciplines/economics.md

## 家族 → 入池条数

| 家族 | 入池 |
|---|---|
| agent | 539 |
| raw | 35 |
| oa_title | 22 |
| s2_rec | 30 |
| snowball | 30 |
| survey | 0 |
| pivot | 152 |

## 逐源健康（ok / empty / failed，按检索 cell 计）

| 源 | ok | empty | failed |
|---|---|---|---|
| arxiv | 8 | 1 | 0 |
| crossref | 9 | 0 | 0 |
| openalex | 9 | 0 | 0 |
| openalex_relevance | 9 | 0 | 0 |
| semantic_scholar | 7 | 1 | 1 |

> failed > 0 时必须显式报告：源失败绝不能写成"零命中"。

## 饱和与停止信号（capture–recapture，机械估计）

建议继续——估计覆盖 5% < 80%（N̂≈3657，还有约 3486 篇未召回）。Chao1 假定家族独立：agent/raw 同源查询会高估覆盖，判定是信号不是结论；收工仍需 `audit` 锚点核验。

- Chao1：S=171 · 单家族 f1=167 · 双家族 f2=4
  → N̂≈3657.1 · 估计覆盖 4%
- 本轮对主题池的新增占比：5%

## 查询反馈（每条查询的实际命中——造词迭代的仪表盘）

| 查询 | 总命中 | 判定 | 逐源 |
|---|---|---|---|
| momentum absence reversal Chinese stock market | 143 | ok | arxiv:40 semantic:2 openalex:37 openalex:37 crossref:27 |
| individual investors turnover momentum China | 149 | ok | arxiv:40 semantic:4 openalex:39 openalex:39 crossref:27 |
| daily price limits momentum Chinese stocks | 147 | ok | arxiv:40 semantic:0 openalex:39 openalex:39 crossref:29 |
| short-sale constraints limits to arbitrage momentum China | 148 | ok | arxiv:40 semantic:0 openalex:40 openalex:40 crossref:28 |
| factor momentum industry momentum Chinese stock market | 174 | ok | arxiv:40 semantic:28 openalex:40 openalex:40 crossref:26 |
| investor sentiment Chinese stock returns momentum | 165 | ok | arxiv:40 semantic:17 openalex:40 openalex:40 crossref:28 |
| A股动量机制 | 78 | isolated | arxiv:0 semantic:19 openalex:20 openalex:20 crossref:19 |

> empty/thin 的概念块是词汇错配的信号：换成论文侧词汇（方法名/数据集名/
> 任务名/术语缩写）重拟后补一轮 search，而不是加大同词重试。

## agent 供查询（家族 1）

- momentum absence reversal Chinese stock market
- individual investors turnover momentum China
- daily price limits momentum Chinese stocks
- short-sale constraints limits to arbitrage momentum China
- factor momentum industry momentum Chinese stock market
- investor sentiment Chinese stock returns momentum

## web 桥接查询（英文 + 中文）

- （无——需显式提供 --web-queries）

## 综述种子（参考文献收割锚点）

- （无）

## 政策语料查询（家族 8：NBER / Fed Board / IMF）

- （未显式提供——复用 agent 查询或主题；政策语料建议用平实的经济学措辞）

> 政策机构命中：NBER 1。政策笔记（FEDS Notes 等）是写给决策者的：
> 读其中的效应量级判断与 stated data gaps——前者是经济显著性的参照系，
> 后者是「找空白」的直接证据。

## 备注与降级

- 查询反馈：1 条查询与他查询结果集零重叠（isolated）——可能是真正的独立概念块，也可能是盲猜词汇；读其返回记录再决定是否保留该块
- web: 未提供 --web-queries（英文逐字跨度 + 中文自然短语），已跳过
- pivot: 机械扩展查询 ['source periods studies three strategy research', 'empirical returns analysis risk momentum trading'] → 152 条
- 排序说明：本构建无 LLM 级联——顺序为 RRF/家族保底席位序，引用前必须由调用方 agent 自行判断相关性（读标题+摘要逐篇过）；record.found_by 记录了召回该篇的家族集合，可用 `screen` 工具做三分带分流
- target=60 截掉了 111 条已融合候选——扩展家族（s2_rec/snowball/web/survey）排在配额头之后，会被优先截掉（policy 家族有 8 席保底穿过截断）；写综述/要广度时用 target: 0

## 下一步（未完成即不算收工）

1. **相关性粗排/精排**：读池内每篇的标题+摘要，逐篇判断与主题的相关性，
   排序并筛除（筛除的写入 `exclusions.jsonl`，带原因码）。
2. **锚点核验**：用 `audit` 工具算池子对 top 综述参考文献的 coverage。
3. **饱和检查**：换一种主题措辞再搜一次，几乎无新记录才算饱和。
4. **全文清单**：对核心论文用 `fetch` 工具取全文；拿不到的标注
   "仅摘要级"并写入 `fetch_list.md`。
