# Changelog

## 0.2.0 — 2026-10-18

切题判断的三层增强——仍然零 LLM key，agent 仍是裁判，工具拿到的是可解释的分流。

### 新增

- **`screen` 工具（相关性三分带）**：对池子逐条打分并分带 core / uncertain /
  likely_off，写 `screening.jsonl`。三个机械可解释通道，逐条优雅降级：
  - **semantic**（可选 extra `citlens-agent[embedding]`，本地
    sentence-transformers，默认 BAAI/bge-base-en-v1.5，永不触碰 LLM key）：
    title+abstract 对每个概念块查询的 cosine 取 MAX——命中一个概念块即切题；
  - **lexical**：BM25（IDF、CJK bigram）对全池归一化——精确术语压过 paraphrase；
  - **consensus**：`found_by` 家族投票（见下），4 家族饱和。
  权重逐条按"该记录实际拥有的通道"重归一（缺元数据不惩罚）。**分流不是判决**：
  绝不自动剔除，agent 终审并把最终排除记入 exclusions（PRISMA）。阈值默认
  0.5 / 0.32（启发式，尚未在 LitSearch 金标上校准，报告必须带阈值与通道）。
- **`found_by` 家族投票**：recall 驱动记录每条记录被哪些召回家族命中
  （agent/raw/oa_title/s2_rec/snowball/web/survey），写入 pool 记录与
  exclusions 日志；search_report 新增"≥2/≥3 家族共识"统计。跨家族独立命中
  是免费的切题信号——`screen` 的 consensus 通道消费它。
- `doctor` 新增 `screen_embedding_runtime` 探针（本地嵌入可用性，缺 extra 时
  明示 lexical+consensus 仍可用）。

### 修复

- **snowball 相关性准入**：词集重叠 → BM25（IDF 加权）。原实现让共享泛词
  （"method/analysis"）的高被引论文压过精确命中的小论文；且 `[a-z]{4,}` 分词
  对中文主题恒为 0 分。现在走共享 `_terms` 分词器（CJK bigram），引用数只在
  BM25 同分时决胜（分数决胜，不是名次决胜）。

## 0.1.0 — 2026-10-17

首个独立版本：从 CiteLens 引擎仓库（yfxiao123/citens，portable 层）拆出，重塑为
**面向 agent 安装、零 LLM key** 的独立仓库。

### 变革

- **零 LLM key 设计**：`citens` 核心只保留 LLM-free 子图（sources / snowball /
  survey_seed / websearch 抓取半段 / fulltext / citations / collect 池层 / litsearch
  纯函数）；Settings 移除全部 LLM 字段；`doctor` 无必填键。
- **agent 即规划器**：九召回家族 → 七家族。planned/HyDE/pivot（用 LLM 生成查询的
  三族）由调用方 agent 的 `queries` / `title_probes` / `web_queries` 参数替代；
  LLM 级联排序移除，相关性判断交还 agent（SKILL.md 明文）。
- **工具面**：search / pool / **fetch**（OA 全文，摘要兜底）/ **export**（BibTeX/RIS）/
  **audit**（综述参考文献覆盖锚点核验）/ status / doctor；移除 plan/questions/review
  （其纪律全部写入 SKILL.md 由 agent 亲自执行：编号主张、四级判定、蜜罐、辩护律师、
  重写重验、诚实数字块、PRISMA 排除、收工协议）。
- **安装器**：仓库根布局（无 portable 子目录）；init 向导全可选项；驱动复用范围化
  （显式 engine 切换时驱动跟随新树）；apply 自动创建数据家。

### 检索方法（与引擎逐字一致）

RRF 融合 k=60、每家族 30 席、每源 20 深、agent 查询腿 40 深；OpenAlex title.search
5 词硬截断；S2 推荐 1rps 节流；arXiv 断连重试 ×2；诚实健康桶（源失败 ≠ 零命中）。
