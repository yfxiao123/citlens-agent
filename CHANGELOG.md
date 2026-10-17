# Changelog

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
