# CiteLens for agents（citlens-agent）

> **English** — CiteLens as an MCP server for AI agents (Claude Code, Codex CLI, zcode, Cursor, etc.): multi-source literature search, relevance triage, open-access full-text fetching, BibTeX/RIS export and coverage audits, with one shared literature pool across agents. The agent plans the queries and writes; this repo provides the reproducible retrieval machinery. Adding the free keys of the open scholarly indexes (Semantic Scholar / OpenAlex / Crossref / Serper) is recommended; it lifts rate limits and recall.
>
> ```bash
> git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
> python -m venv .venv && .venv/Scripts/python -m pip install -e .   # macOS/Linux: bin/python
> .venv/Scripts/python install.py apply
> ```

citlens-agent 把 CiteLens 的文献检索能力做成一个 MCP 工具服务器，装进各类 AI agent 客户端。装好之后给出指令，agent 找文献、写综述时会直接调这套工具。

**分工**：模型负责拆概念块、拟英文检索词、判断切题与否、组织综述论证。多源检索、融合去重、引文扩展、全文抓取、格式导出、核验——这些要稳定可复现的执行，Citlens通过Tools对检索链进行了增强。

## 安装

建议直接把仓库网址发给你的 Agent，它会完成所有准备工作。可以直接发这句：

> 请帮我安装 CiteLens：克隆 https://github.com/yfxiao123/citlens-agent ，严格按仓库里的 INSTALL.md 完成安装和注册，装好后运行一次 citlens doctor 验收，并告诉我缺哪些免费 key、去哪注册。

如果你想要自己做一些改进，可以 Clone 它：

```bash
git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS/Linux: .venv/bin/python
.venv/Scripts/python install.py init            # 可选：录入免费 key 提升效果
.venv/Scripts/python install.py apply           # 检测本机已装的 agent 并注册
```

**一些开源学术网站的 key**。用于增强检索功能：

1. `SEMANTIC_SCHOLAR_API_KEY` — （[免费申请](https://www.semanticscholar.org/product/api)）
2. `SERPER_API_KEY` — （[serper.dev](https://serper.dev) 免费 2,500 次）
3. `OPENALEX_API_KEY` — 日预算 ×10（[openalex.org/premium](https://openalex.org/premium)，个人研究者免费）
4. `OPENALEX_EMAIL` / `CROSSREF_EMAIL` — 礼貌池待遇，留个邮箱即可，**无需注册**

装好后重启 agent，运行 `doctor`：报告 key 的缺失项、效果和注册地址，照着填进数据目录的 `.env`（也可以让 agent 帮你填）。如果有缺失，限流降级会如实给出。代理设置、数据目录布局、卸载回滚、故障排查见 [INSTALL.md](INSTALL.md)；`.env` 各键含义见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 使用示例

一次真实用法：一篇硕士开题的文献基础。把源论文和 9 个检索方向交给 agent，它用 `search` 跑了 11 个子题、`fetch` 抓了 364 篇开放获取全文，最后汇成一份带引用建议的分类文献库——1072 条总账、9 份方向阅读清单、覆盖审计，没拿到全文的条目也逐条给出获取渠道。过程与产物样例见 [docs/examples/thesis-library](docs/examples/thesis-library/README.md)。

## 工具

| 工具 | 作用 |
|---|---|
| `search` | 多路召回，RRF 融合；接受 agent 拟的检索词、标题检索、web 查询，返回逐查询命中数 |
| `pool` | 读取并过滤既有文献池，不发起检索 |
| `screen` | 相关性分带（core / uncertain / likely_off）：本地嵌入、BM25、家族投票打分；负责分流|
| `gaps` | 「找空白」的机械基底：概念块×年代覆盖矩阵、挖掘原文中提及的局限性内容、novelty check |
| `expand` | 用已有论文，做前向/后向引文链和相似推荐扩展 |
| `notes` | 阅读笔记：逐篇判定（core / uncertain / off），存入记录，`expand` 可直接取 core 笔记中的论文进行扩展检索 |
| `dedup` | 去重报告：doi / arXiv / 题名+共作者寻找重复论文，--merge 合并|
| `fetch` | 抓取单篇开放获取全文，无全文时返回摘要并标注"仅摘要级" |
| `export` | 将文献池导出为 BibTeX / RIS / EndNote XML / CSL JSON |
| `audit` | 计算文献池对主题内高被引综述参考文献的覆盖率 |
| `verify` | 机械核验综述：[n]→参考文献→池内记录逐层核验，span 在被引原文逐字出现，计算引用精度 |
| `status` | 查询后台检索任务的进度 |
| `doctor` | 健康检查：路径、检索源、逐 key 引导、池数量、任务状态 |

## 检索方法

`search` 移植的是引擎在 LitSearch 基准上表现最好的 adaptive 形态：

1. **agent 检索词**：调用方按概念块拟定的英文查询，逐源深度检索
2. **主题原文**：题目原文在 arXiv、Semantic Scholar、OpenAlex、Crossref 检索
3. **标题探索**：agent 拟的假想论文标题或已知标题，走 OpenAlex 标题索引
4. **相似推荐**：以池头文献的 DOI 取 Semantic Scholar 推荐
5. **引文扩展**：对池内锚点文献做被引与引用双向的一跳扩展
6. **web 扩展**：Google SERP 检索，结果锚定回论文记录
7. **综述检索**：找到该领域核心综述后寻找其参考文献，加入检索源

各池结果按 Reciprocal Rank Fusion 融合，每池至少 30 篇，每条记录都带 `found_by`，记下哪些池召回了它；一篇论文被多个家族独立命中，本身就是很强的切题信号。

单独判断切题性。 默认数字设定为 60，即需要60篇文献用于你的综述。如果需要广泛检索，设定 `target: 0`，或者先 `search` 再对累积池跑 `screen`。

screen 用三个通道给每条记录打分：本地嵌入（可选 extra）算语义相似度，BM25 算词面重叠，`found_by` 算各池投票，然后给每篇论文标记 core / uncertain / likely_off 写入 `screening.jsonl`。agent 逐篇读 core 和 uncertain 的标题摘要做终审，likely_off 批量审核，最终排除连同原因记入 `exclusions.jsonl`（PRISMA）。

## 支持的客户端

安装器通过声明式注册表（`agents.json`）支持 21 个客户端，对每个Agent，只增改 `citlens` 一项。

> 本安装器用固定命名空间（server 名 `citlens`、`~/.citlens/config.json`、shim、`~/.agents/skills/citlens`、DSH bundle 名），多个实现会互相覆盖。

## 数据与共享

所有客户端共用一个数据（默认 `~/.citlens/home`，安装时可用 `--home` 指定）。文献池按主题累积在 `data/litdb/`。检索任务以后台进程运行，独立于发起它的会话：客户端关闭后任务继续，任何 agent 都能查询进度并读取结果。

## Roadmap

- 更多客户端进入已实测列表
- `screen` 阈值在 LitSearch 金标上校准，uncertain 带加 cross-encoder 精排
- ASReview 式反馈环：agent 的 PRISMA 判定回流为下一轮 pool 读取的优先级

## 许可证

MIT。
