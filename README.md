# CiteLens for agents（citlens-agent）

> **English** — CiteLens as an MCP server for AI agents (Claude Code, Codex CLI, zcode, Cursor, etc.): multi-source literature search, relevance triage, open-access full-text fetching, BibTeX/RIS export and coverage audits, with one shared literature pool across agents. The agent plans the queries and writes; this repo provides the reproducible retrieval machinery. Adding the free keys of the open scholarly indexes (Semantic Scholar / OpenAlex / Crossref / Serper) is recommended; it lifts rate limits and recall.
>
> ```bash
> git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
> python -m venv .venv && .venv/Scripts/python -m pip install -e .   # macOS/Linux: bin/python
> .venv/Scripts/python install.py apply
> ```

citlens-agent 把 CiteLens 的文献检索能力做成一个 MCP 工具服务器，装进各类 AI agent 客户端。装好之后，agent 找文献、查覆盖、写综述时会直接调这套工具，不再拿自带的网页搜索凑数。

**分工**：拆概念块、拟英文检索词、判断切题与否、组织综述论证——这些要判断力，归 agent。多源检索扇出、融合去重、引文扩展、全文抓取、格式导出、核验算术——这些要稳定可复现的执行，归工具。同样的输入永远得到同样的池子，方法在代码里，事后查得到。

## 实测效果

- **核验链兜住引用质量**：初稿引用精度 73%，跑一遍 `verify` 按判定改写后复验 98%（引擎仓库综述实测）。每个 `[n]` 要能解析到参考文献、每条参考文献要能解析到池内记录、每个 span 要在被引原文逐字出现——解析不到就算编造。
- **排序杠杆在 597 题全量基准上成立**：同池对比 R@5 0.069→0.132、R@20 0.118→0.141（配对 McNemar 显著）。同时测出召回天花板：仅用题面原句检索只能覆盖 16.8% 的金标——所以有了 `expand`（漏检金标里 71% 与问题只共享 ≤2 个内容词，引文链绕开词汇错配）和 `title_probes`。
- **网络不稳不再伪装成"没搜到"**：每个请求过统一重试层（429/5xx/断连按 `Retry-After` 退避重试），连续失败熔断并在健康表写明原因，401 直接提示查哪个环境变量。实测真网一次检索中 S2 的三次断连和一次 429 全被重试层吸收，四源全绿完成。
- **失败源绝不算零命中**：逐源健康表 ok / empty / failed 三桶分开计数，PRISMA 排除日志带原因码。

## 安装

```bash
git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS/Linux: .venv/bin/python
.venv/Scripts/python install.py init            # 可选：录入免费 key 提升效果
.venv/Scripts/python install.py apply           # 检测本机已装的 agent 并注册
```

**零 key 可用，免费 key 更稳更全**。按实测影响力排序：

1. `SEMANTIC_SCHOLAR_API_KEY` — 保 1 req/s，终结共享池的 429 风暴（[免费申请](https://www.semanticscholar.org/product/api)，即申即得）
2. `SERPER_API_KEY` — 撑起 web 桥接家族（[serper.dev](https://serper.dev) 免费 2,500 次）
3. `OPENALEX_API_KEY` — 日预算 ×10（[openalex.org/premium](https://openalex.org/premium)，个人研究者免费）
4. `OPENALEX_EMAIL` / `CROSSREF_EMAIL` — 礼貌池待遇，留个邮箱即可，**无需注册**

装好后重启 agent，跑一次 `doctor`：它逐 key 报告缺失项、效果和注册地址，照着填进数据目录的 `.env` 就行。不配也能跑，限流降级会被如实报出来。代理设置、数据目录布局、卸载回滚、故障排查见 [INSTALL.md](INSTALL.md)；`.env` 各键含义见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 工具

| 工具 | 作用 |
|---|---|
| `search` | 七个学术家族召回，RRF 融合；接受 agent 拟的检索词、标题探针、web 查询（另有可选的宏观政策语料家族），返回逐查询命中数，弱查询一目了然 |
| `pool` | 读取并过滤既有文献池，不发起检索 |
| `screen` | 相关性分带（core / uncertain / likely_off）：本地嵌入、BM25、家族投票三通道打分；只分流，不自动剔除任何记录 |
| `gaps` | 「找空白」的机械基底：概念块×年代覆盖矩阵（空格是结构性 gap 候选）、全文自陈局限原句挖掘（带 span 可核验）、gap 陈述对池 novelty check（最近邻即机械反驳） |
| `expand` | 拿你判过的论文当种子，做前向/后向引文链和相似推荐扩展；词汇对不上也能顺着引文找到 |
| `notes` | 阅读笔记：逐篇判定（core / uncertain / off）加一句话理由落盘，是判断记忆，`expand` 可直接取 core 笔记当种子 |
| `dedup` | 去重报告：doi / arXiv / 题名+共作者三信号找嫌疑组（预印本与正式版是典型），--merge 合并（仅主题池，先写 .bak） |
| `fetch` | 抓取单篇开放获取全文，无全文时返回摘要并标注"仅摘要级" |
| `export` | 将文献池导出为 BibTeX / RIS / EndNote XML / CSL JSON |
| `audit` | 计算文献池对主题内高被引综述参考文献的覆盖率 |
| `verify` | 机械核验综述：[n]→参考文献→池内记录逐层可解析，span 在被引原文逐字出现，最后算引用精度等诚实数字 |
| `status` | 查询后台检索任务的进度 |
| `doctor` | 健康检查：路径、检索源、逐 key 引导（缺什么、去哪注册、写进哪个 .env）、池数量、任务状态 |

## 检索方法

`search` 移植的是引擎在 LitSearch 基准上表现最好的 adaptive 形态：删掉三个用 LLM 造查询的家族和级联排序，查询规划交还 agent，留下七个学术家族：

1. **agent 检索词**：调用方按概念块拟定的英文查询，逐源深度检索
2. **主题原句**：题目原文在 arXiv、Semantic Scholar、OpenAlex、Crossref 四源检索
3. **标题探针**：agent 拟的假想论文标题或已知标题，走 OpenAlex 标题索引
4. **相似推荐**：以池头文献的 DOI 取 Semantic Scholar 推荐
5. **引文扩展**：对池内锚点文献做被引与引用双向的一跳扩展
6. **web 桥接**：Google SERP 检索，结果锚定回论文记录
7. **综述收割**：找到主题综述后收割其参考文献

（另有一个可选的政策语料家族，面向宏观经济学的 NBER/Fed/IMF 检索，通用文献检索可忽略。）

各家族结果按 Reciprocal Rank Fusion 融合，每家族保底 30 席，常数沿用引擎在 LitSearch 上的测量值（RRF k=60，每源深度 20）。每条记录都带 `found_by`，记下哪些家族召回了它；一篇论文被多个家族独立命中，本身就是很强的切题信号。

返回的顺序只是融合序，切题与否要另判。`target` 默认 60，截断按融合序来，而 agent 检索词加主题原句两族就能填满 60 席，所以扩展家族（s2_rec/snowball/web/survey）常被先截掉。要广度就传 `target: 0`（写综述的流程里已这么要求），或者先 `search` 再对累积池跑 `screen`。

screen 用三个通道给每条记录打分：本地嵌入（可选 extra）算语义相似度，BM25 算词面重叠，`found_by` 算家族投票，然后分成 core / uncertain / likely_off 三带写进 `screening.jsonl`。agent 逐篇读 core 和 uncertain 的标题摘要做终审，likely_off 批量过一眼，最终排除连同原因记入 `exclusions.jsonl`（PRISMA）。两个阈值（0.5 / 0.32）是启发式默认值，还没在金标上校准，报告分带时要把阈值一起报。

## 支持的客户端

安装器通过声明式注册表（`agents.json`）支持 21 个客户端，自动检测本机已装的并写入配置；写前备份，只增改 `citlens` 一项。其中 12 个是可直接写入的方言，9 个是"只打印/snippet"型（Zed、Continue 等手工粘贴；aider 走 CLI）。已实测：Claude Code、Codex CLI、zcode、aider（CLI 通道）、DSH。新客户端只需在 `~/.citlens/agents.d/` 放一个同格式的 JSON 文件。

> 装过别的 CiteLens 实现的话注意：本安装器用固定命名空间（server 名 `citlens`、`~/.citlens/config.json`、shim、`~/.agents/skills/citlens`、DSH bundle 名），两个实现会互相覆盖。要么卸掉一个，要么改用不同的 server 名和独立数据家。

## 数据与共享

所有客户端共用一个数据家（默认 `~/.citlens/home`，安装时可用 `--home` 指定）。文献池按主题累积在 `data/litdb/`，一个 agent 搜到的文献，其他 agent 直接可用。检索任务以后台进程运行，独立于发起它的会话：客户端关闭后任务继续，任何 agent 都能查询进度并读取结果。

## 与 CiteLens 引擎的关系

引擎仓库 [citens](https://github.com/yfxiao123/citens) 是自带 LLM 的完整版本：CLI、Web 控制台、桌面 exe，以及从查询规划到写作验证的完整流水线，适合"给一个题目、自动出综述"的独立用法。citlens-agent 面向已经在用 agent 的用户，只保留检索与证据工具。

两边共享搜索原语和数据格式：per-source cells、RRF、配额、snowball/survey/oa-title、`pool.jsonl` 互认。流水线各自独立，引擎生产路径是 planner→search→LLM filter→rank，这里是多家族召回加 agent 判断。`verify` 实现的是引擎验证链里不依赖 LLM 的那半段，可核验的部分不再靠散文纪律。

## Roadmap

- 更多客户端进入已实测列表
- `screen` 阈值在 LitSearch 金标上校准，uncertain 带加 cross-encoder 精排
- ASReview 式反馈环：agent 的 PRISMA 判定回流为下一轮 pool 读取的优先级

## 许可证

MIT。
