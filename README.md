# CiteLens for agents（citlens-agent）

> **English** — CiteLens as an MCP server for AI agents (Claude Code, Codex CLI, zcode, Cursor, etc.): multi-source literature search, relevance triage, open-access full-text fetching, BibTeX/RIS export and coverage audits, with one shared literature pool across agents. The agent plans the queries and writes; this repo provides the reproducible retrieval machinery. Adding the free keys of the open scholarly indexes (Semantic Scholar / OpenAlex / Crossref / Serper) is recommended; it lifts rate limits and recall.
>
> ```bash
> git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
> python -m venv .venv && .venv/Scripts/python -m pip install -e .   # macOS/Linux: bin/python
> .venv/Scripts/python install.py apply
> ```

citlens-agent 把 CiteLens 的文献检索能力做成一个 MCP 工具服务器，装进各类 AI agent 客户端。装好之后，agent 找文献、查覆盖、写综述时会直接调这套工具，不再拿自带的网页搜索凑数。

## 设计

文献工作分两类。拆概念块、拟英文检索词、判断一篇论文切不切题、组织综述论证，这些要判断力，agent 自己做得来。多源检索扇出、结果融合去重、引文网络扩展、开放获取全文抓取、引文格式化导出，这些要的是稳定可复现的执行，靠每次现写的提示词做不稳，也没法复查。

citlens-agent 只承担第二类。agent 把拟好的英文检索词传给 `search`，拿回一个按固定方法构建的候选池；切题判断、排序、综述写法都留给 agent。同样的输入永远得到同样的池子，方法在代码里，事后查得到。

写综述时，工具只提供证据材料。`fetch` 抓单篇全文，取不到就退回摘要并标注"仅摘要级"；排除记录进 PRISMA 日志；`audit` 审池子对综述参考文献的覆盖；`export` 出 BibTeX/RIS。写作归 agent，按 SKILL.md 的流程来：编号引用，每条主张对照原文给判定（supported / partial / background / contradictory / unsupported / unverifiable 六级）并引用原文 span。初稿写完交给 `verify` 做机械核验：每个 `[n]` 要能解析到参考文献，每条参考文献要能解析到池内记录，每个 span 要在被引原文里逐字出现，解析不到或对不上就算编造；引用精度、不可验证率、全文 grounding 比例由工具算好返回。对抗性复查和改写仍是 agent 的活，改完再跑一次 `verify`。这条验证链在引擎仓库实测过，初稿引用精度 73%，改写复验后 98%。

## 安装

```bash
git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS/Linux: .venv/bin/python
.venv/Scripts/python install.py init            # 建议录入开源文献库的 key 提升效果
.venv/Scripts/python install.py apply           # 检测本机已装的 agent 并注册
```

**建议配上开源文献库的免费 key**。Semantic Scholar、OpenAlex、Crossref 留个邮箱就能进各自的礼貌池，web 桥接的 Serper 也有免费档，都在官网申请。带 key 走正式配额，推荐和引文扩展更稳，召回更全。不配也能跑，个别源在匿名配额下会限流降级，`doctor` 会照实报出来。

重启 agent，让它运行 `doctor` 工具验收。完整流程（代理设置、数据目录布局、卸载回滚、故障排查）见 [INSTALL.md](INSTALL.md)；`.env` 各键的含义见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 工具

| 工具 | 作用 |
|---|---|
| `search` | 七家族召回，RRF 融合；接受 agent 拟的检索词、标题探针与 web 查询，返回逐查询命中数，弱查询一目了然 |
| `pool` | 读取并过滤既有文献池，不发起检索 |
| `screen` | 相关性分带（core / uncertain / likely_off）：本地嵌入、BM25、家族投票三通道打分；只分流，不自动剔除任何记录 |
| `expand` | 拿你判过的论文当种子，做前向/后向引文链和相似推荐扩展；词汇对不上也能顺着引文找到（漏检金标里 71% 与问题只共享 ≤2 个内容词） |
| `fetch` | 抓取单篇开放获取全文，无全文时返回摘要 |
| `export` | 将文献池导出为 BibTeX / RIS |
| `audit` | 计算文献池对主题内高被引综述参考文献的覆盖率 |
| `verify` | 机械核验综述：[n]→参考文献→池内记录逐层可解析，span 在被引原文逐字出现，最后算引用精度等诚实数字 |
| `status` | 查询后台检索任务的进度 |
| `doctor` | 健康检查：路径、检索源配置、池数量、任务状态 |

## 检索方法

`search` 移植的是引擎在 LitSearch 基准上表现最好的 adaptive 形态。引擎原版九个家族加两阶段盲级联排序；这里删掉三个用 LLM 造查询的家族（planned/HyDE/pivot）和级联排序，查询规划交还 agent，留下七个：

1. agent 检索词：调用方按概念块拟定的英文查询，逐源深度检索
2. 主题原句：题目原文在 arXiv、Semantic Scholar、OpenAlex、Crossref 四源检索
3. 标题探针：agent 拟的假想论文标题或已知标题，走 OpenAlex 标题索引
4. 相似推荐：以池头文献的 DOI 取 Semantic Scholar 推荐
5. 引文扩展：对池内锚点文献做被引与引用双向的一跳扩展
6. web 桥接：Google SERP 检索，结果锚定回论文记录
7. 综述收割：找到主题综述后收割其参考文献

各家族结果按 Reciprocal Rank Fusion 融合，每家族保底 30 席，常数沿用引擎在 LitSearch 上的测量值（RRF k=60，每源深度 20）。每条记录都带 `found_by`，记下哪些家族召回了它；一篇论文被多个家族独立命中，本身就是很强的切题信号。

返回的顺序只是融合序，切题与否要另判。`target` 默认 60，截断按融合序来，而 agent 检索词加主题原句两族就能填满 60 席，所以扩展家族（s2_rec/snowball/web/survey）常被先截掉。要广度就传 `target: 0`（写综述的流程里已这么要求），或者先 `search` 再对累积池跑 `screen`。

screen 用三个通道给每条记录打分：本地嵌入（可选 extra）算语义相似度，BM25 算词面重叠，`found_by` 算家族投票，然后分成 core / uncertain / likely_off 三带写进 `screening.jsonl`。agent 逐篇读 core 和 uncertain 的标题摘要做终审，likely_off 批量过一眼，最终排除连同原因记入 `exclusions.jsonl`（PRISMA）。两个阈值（0.5 / 0.32）是启发式默认值，还没在金标上校准，报告分带时要把阈值一起报。

## 基准

完整数字和复现命令在 `bench/README.md`，这里给结论和最关键的几个数。

597 题 LitSearch 全量（2026-10-24，四源当天全程健康、零失败；只用自然语言问题本身当检索词，这是召回的下界）：

| 排序方式 | R@5 | R@20 | MRR@100 |
|---|---|---|---|
| 融合序（基线） | 0.069 | 0.118 | 0.046 |
| screen 重排，配额池 | 0.132 | 0.141 | 0.117 |
| screen 重排，全并集 | 0.147 | 0.161 | 0.124 |

配对检验很干净：配额池同池对比 b=14、c=0（p=0.0001），全并集 b=27、c=0。27 道题靠 screen 把金标拉进前 20，没有一道因此掉出去。

排序的极限在哪，这次也量出来了。只有 16.8% 的金标论文进得了全并集，剩下的 83% 得靠 agent 换词重搜和 `expand` 种子扩展去拿，roadmap 里那两项就是冲这个来的。

15 题冻结样本（引擎 planner 缓存覆盖的那批）上，全并集只换排序，screen R@20 33.3%、R@5 26.7%、MRR 0.178，对照全局 RRF 的 6.7%、0%、0.013（McNemar p=0.125，样本太小，不显著）；配额池形状上 R@20 从 6.7% 提到 13.3%。0.2.0 曾把配额池基线和全并集 screen 放在一起比出 6.7→33.3，0.3.0 起按池分开写。引擎 adaptive 腿在同一样本上 R@5/R@20 持平，MRR 更高（≈0.273 对 0.178），命中的题也不完全相同（R@5 重叠 2/4，R@20 重叠 3/5）。这批 15 题是 10-18 跑的，当天 OpenAlex 对所有查询返回 200 空结果还被缓存了下来，等效三源；同池内的排序对比仍然成立，绝对召回偏低，后来加了空源重试护栏。

每次检索落盘三份产物：`pool.jsonl`（结构化记录）、`search_report.md`（家族入池数、逐源健康表、逐查询命中）、`exclusions.jsonl`（被裁记录及原因，分家族配额、合并去重、目标截断三类）。源失败单独计数、照实上报，web 桥接同样有 ok/empty/failed 三桶。

## 支持的客户端

安装器通过声明式注册表（`agents.json`）支持 21 个客户端，自动检测本机已安装的并写入配置；写前备份，只增改 `citlens` 一项。其中 12 个是可直接写入的方言，9 个是"只打印/snippet"型（Zed、Continue 等手工粘贴；aider 走 CLI）。已实测：Claude Code、Codex CLI、zcode、aider（CLI 通道）、DSH。新客户端只需在 `~/.citlens/agents.d/` 放一个同格式的 JSON 文件。

> 装过别的 CiteLens 实现的话注意：本安装器用固定命名空间（server 名 `citlens`、`~/.citlens/config.json`、shim、`~/.agents/skills/citlens`、DSH bundle 名），两个实现会互相覆盖。要么卸掉一个，要么改用不同的 server 名和独立数据家。

## 数据与共享

所有客户端共用一个数据家（默认 `~/.citlens/home`，安装时可用 `--home` 指定）。文献池按主题累积在 `data/litdb/`，一个 agent 搜到的文献，其他 agent 直接可用。检索任务以后台进程运行，独立于发起它的会话：客户端关闭后任务继续，任何 agent 都能查询进度并读取结果。

## 与 CiteLens 引擎的关系

引擎仓库 [citens](https://github.com/yfxiao123/citens) 是自带 LLM 的完整版本：CLI、Web 控制台、桌面 exe，以及从查询规划到写作验证的完整流水线，适合"给一个题目、自动出综述"的独立用法。citlens-agent 面向已经在用 agent 的用户，只保留检索与证据工具。

两边共享搜索原语和数据格式：per-source cells、RRF、配额、snowball/survey/oa-title、`pool.jsonl` 互认。流水线各自独立，引擎生产路径是 planner→search→LLM filter→rank，这里是七家族召回加 agent 判断。`verify` 实现的是引擎验证链里不依赖 LLM 的那半段，可核验的部分不再靠散文纪律。

## Roadmap

- 文献管理增强：去重报告、阅读笔记、更多导出格式（EndNote XML、CSL JSON）
- 更多客户端进入已实测列表
- `screen` 阈值在 LitSearch 金标上校准，uncertain 带加 cross-encoder 精排
- ASReview 式反馈环：agent 的 PRISMA 判定回流为下一轮 pool 读取的优先级

## 许可证

MIT。
