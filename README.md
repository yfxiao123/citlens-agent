# CiteLens for agents（citlens-agent）

> **English** — CiteLens as an MCP server for AI agents (Claude Code, Codex CLI, zcode, Cursor, etc.): multi-source literature search, relevance triage, open-access full-text fetching, BibTeX/RIS export and coverage audits, with one shared literature pool across agents. The agent plans the queries and writes; this repo provides the reproducible retrieval machinery. Adding the free keys of the open scholarly indexes (Semantic Scholar / OpenAlex / Crossref / Serper) is recommended — it lifts rate limits and recall.
>
> ```bash
> git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
> python -m venv .venv && .venv/Scripts/python -m pip install -e .   # macOS/Linux: bin/python
> .venv/Scripts/python install.py apply
> ```

citlens-agent 把 CiteLens 的文献检索能力做成一个 MCP 工具服务器，装进各类 AI agent 客户端。装好之后，agent 处理找文献、查覆盖、写综述这类请求时会调用这些工具，而不是靠它自己的网页搜索。

## 设计

文献工作可以分成两类。一类需要判断力：把研究问题拆成概念块、写出合适的英文检索词、判断一篇论文是否切题、组织综述的论证。这类工作 agent 自己就能做好。另一类需要稳定、可复现的执行：多源检索扇出、结果融合去重、引文网络扩展、开放获取全文抓取、引文格式化导出。这类工作不适合靠每次现写的提示词完成，因为结果既不稳定，也无法复现。

citlens-agent 只承担第二类：agent 把自己拟好的英文检索词传给 `search`，得到一个按固定方法构建的候选池；判断哪些论文切题、如何排序、综述怎么写，是 agent 的事。同样的输入总是得到同样的池子，检索方法写在代码里而不是提示词里，事后可以复查。

写综述时，工具提供证据材料：单篇全文抓取（取不到全文时退回摘要，并明确标注只能摘要级引用）、PRISMA 式排除日志、综述参考文献覆盖审计、BibTeX/RIS 导出。写作由 agent 按 SKILL.md 的流程执行：编号引用，每条主张对照原文给出引擎的**六类判定**（supported / partial / background / contradictory / unsupported / unverifiable）并引用原文 span；写完后交给 `verify` 做**机械核验**（不调 LLM）：每个 `[n]` 必须解析到参考文献、每条参考文献必须解析到池内文献（蜜罐），每个 span 必须在被引原文中逐字出现，然后工具自己计算并返回诚实数字块（引用精度、不可验证率、全文 grounding、papers_cited/pool_size）。对抗性复查与改写仍由 agent 做，改完再跑一次 `verify`。这套流程沿用引擎仓库实测过的验证链：初稿引用精度 73%，改写复验后 98%。

## 安装

```bash
git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS/Linux: .venv/bin/python
.venv/Scripts/python install.py init            # 建议录入开源文献库的 key 提升效果
.venv/Scripts/python install.py apply           # 检测本机已装的 agent 并注册
```

**建议添加开源文献库的免费 key**（Semantic Scholar、OpenAlex、Crossref 的邮箱礼貌池、web 桥接的 Serper，均可在官网免费申请）：带 key 走各家的正式配额池，推荐/引文扩展和 web 通道更稳、召回更全；不配也能跑，只是匿名配额下个别源会限流降级——`doctor` 会如实报告哪些源可用。

重启 agent，让它运行 `doctor` 工具验收。完整流程（代理设置、数据目录布局、卸载回滚、故障排查）见 [INSTALL.md](INSTALL.md)；`.env` 各键的含义见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 工具

| 工具 | 作用 |
|---|---|
| `search` | 七家族召回，RRF 融合；接受 agent 拟定的检索词、标题探针与 web 查询；返回逐查询命中反馈（weak_queries）供造词迭代 |
| `pool` | 读取并过滤既有文献池，不发起检索 |
| `screen` | 相关性三分带（core / uncertain / likely_off）：本地嵌入 + BM25 + 家族投票的机械打分分流，分流不是判决，绝不自动剔除 |
| `expand` | 判断反馈环：以你判定的论文为种子做引文链（前向/后向）+ 相似推荐扩展——绕开查询词汇错配的召回通道（金标剖析：71% 漏检金标与问题共享 ≤2 个内容词） |
| `fetch` | 抓取单篇开放获取全文，无全文时返回摘要 |
| `export` | 将文献池导出为 BibTeX / RIS |
| `audit` | 计算文献池对主题内高被引综述参考文献的覆盖率 |
| `verify` | 综述机械核验（不调 LLM）：每个 [n] → 参考文献 → 池（蜜罐）、判定 span 必须在被引原文中逐字出现、六类判定校验、诚实数字块 |
| `status` | 查询后台检索任务的进度 |
| `doctor` | 健康检查：路径、检索源配置、池数量、任务状态 |

## 检索方法

`search` 是引擎 **LitSearch bench harness 形态**的七家族移植：引擎那条 adaptive 腿在基准上是九家族 + 两阶段盲级联排序；本仓库删掉三个"用 LLM 生成查询"的家族（planned/HyDE/pivot）和级联排序，把规划交还调用方 agent，保留其余七个家族：

1. agent 检索词：调用方按概念块拟定的英文查询，逐源深度检索
2. 主题原句：题目原文在 arXiv、Semantic Scholar、OpenAlex、Crossref 四源检索
3. 标题探针：agent 提供的已知论文标题，走 OpenAlex 标题索引
4. 相似推荐：以池头文献的 DOI 取 Semantic Scholar 推荐
5. 引文扩展：对池内锚点文献做被引与引用双向的一跳扩展
6. web 桥接：Google SERP 检索，结果锚定回论文记录
7. 综述收割：找到主题综述后收割其参考文献

各家族结果按 Reciprocal Rank Fusion 融合，每家族保底 30 席。常数沿用引擎仓库在 LitSearch 基准上的测量值（RRF k=60，每源深度 20）。每条记录同时落盘 `found_by`——命中它的召回家族集合，跨家族独立命中是免费的切题信号。

**这不是引擎生产流水线的移植**：引擎 production 走 planner → search → LLM filter → rank，本仓库对齐的是它 bench 上测得最好的 adaptive 形态（再去掉 LLM 部分）。输出顺序是家族席位序，不是相关性序；`target` 默认 60 会按席位序截断，而 agent+raw 两族就能填满 60，所以扩展家族（s2_rec/snowball/web/survey）在默认配置下可能被优先截掉——要广度就用 `target: 0`（写综述时 SKILL 已明文要求），或先 `search` 再对累积池跑 `screen`。

返回顺序是融合序，不是相关性排序。切题判断分两层：先用 `screen` 做机械分流——三个可解释通道（本地嵌入语义相似度 [可选 extra]、BM25 词面、`found_by` 家族投票），把池子分成 core / uncertain / likely_off 三带并写 `screening.jsonl`；agent 再对 core+uncertain 逐篇精读终审，likely_off 批量复核，所有最终排除记入 `exclusions.jsonl`（PRISMA）。**分流不是判决，screen 绝不自动剔除。** 阈值是启发式默认（未在金标上校准），报告分带时须同时报告阈值与通道。

基准（`bench/README.md`，LitSearch 冻结 15 题，n=15、每题约 1 篇金标）：在**同一个全并集**上只换排序，screen 达 R@20 33.3% / R@5 26.7% / MRR 0.178，对照全局 RRF 6.7% / 0% / 0.013（配对 McNemar p=0.125，未过 0.05）；在**生产配额池**形状上 `screen_full` 把 R@20 从 6.7% 提到 13.3%。0.2.0 曾把"配额池 firstwins vs 全并集 screen_union"跨池对比写成 6.7→33.3，0.3.0 已改为按池写明；引擎 adaptive 腿在同一样本上 R@5/R@20 相同，但 MRR 更高（≈0.273 vs 0.178）、命中集不同（R@5 重叠 2/4、R@20 重叠 3/5），"持平"只对粗粒度计数成立。（事后发现：10-18 那次运行期间 OpenAlex 全程返回 200 空结果并被缓存固化，等效 3 源——同池排序对比仍内部有效，绝对召回偏低；后续已加空源重试护栏。）**全量 597 题**（2026-10-24，仅 raw 家族：自然语言问题本身作唯一检索词，零 LLM，四源全程健康零失败）：同配额池上 `screen_full` 把 R@20 从 0.118 提到 0.141、R@5 0.069→0.132、MRR 0.046→0.117（配对 McNemar b=14 c=0，p=0.0001）；全并集上 `screen_union` R@20 0.161 / R@5 0.147 / MRR 0.124，对两种基线均 b=27、**c=0**（27 题增益、零倒退）。同次运行量化了召回天花板：**仅 16.8% 的金标进入全并集**——排序无法修复另外 83%，广度必须来自 agent 造词与种子扩展（对应 `expand --seeds` / 判断记忆两项 roadmap）。每次检索落盘三份产物：`pool.jsonl`（结构化文献记录）、`search_report.md`（各家族入池数与逐源健康表）、`exclusions.jsonl`（被裁剪的记录及原因，含家族配额/合并去重/目标截断三类原因）。检索源的失败单独计数并如实上报（web 桥接也有 ok/empty/failed 桶），不把失败的源报告成零命中。

## 支持的客户端

安装器通过声明式注册表（`agents.json`）支持 21 个客户端，自动检测本机已安装的并写入配置；写前备份，只增改 `citlens` 一项。其中 12 个是可直接写入的方言，9 个是"只打印/snippet"型（Zed、Continue 等手工粘贴；aider 走 CLI）。已实测：Claude Code、Codex CLI、zcode、aider（CLI 通道）、DSH。新客户端只需在 `~/.citlens/agents.d/` 放一个同格式的 JSON 文件。

> 与别的 CiteLens 安装共存时注意：本安装器使用固定命名空间（`citlens` server 名、`~/.citlens/config.json`、shim、`~/.agents/skills/citlens`、DSH bundle 名）。如果机器上还有另一个 CiteLens 实现，请先卸载其中一个，或改用不同 server 名与独立数据家——否则会互相覆盖。

## 数据与共享

所有客户端共用一个数据家（默认 `~/.citlens/home`，安装时可用 `--home` 指定）。文献池按主题累积在 `data/litdb/`，一个 agent 搜到的文献，其他 agent 直接可用。检索任务以后台进程运行，独立于发起它的会话：客户端关闭后任务继续，任何 agent 都能查询进度并读取结果。

## 与 CiteLens 引擎的关系

引擎仓库 [citens](https://github.com/yfxiao123/citens) 是自带 LLM 的完整版本：CLI、Web 控制台、桌面 exe，以及从查询规划到写作验证的完整流水线，适合"给一个题目、自动出综述"的独立用法。citlens-agent 面向已经在用 agent 的用户，只保留检索与证据工具。

两者共享的是**搜索原语与数据格式**（per-source cells、RRF、配额、snowball/survey/oa-title、pool schema 与 `pool.jsonl` 互认），不是同一条流水线：引擎生产路径是 planner→search→LLM filter→rank，本仓库是 bench 形态的七家族 + agent 判断。`verify` 实现的正是引擎验证链里不依赖 LLM 的那半段（引用真实性、span 溯源、诚实数字），可核验部分不再靠散文纪律。

## Roadmap

- 文献管理增强：去重报告、阅读笔记、更多导出格式（EndNote XML、CSL JSON）
- 更多客户端进入已实测列表
- `screen` 阈值在 LitSearch 金标上校准 + 精排 reranker（cross-encoder）处理 uncertain 带
- ASReview 式反馈环：agent 的 PRISMA 判定回流为下一轮 pool 读取的优先级

## 许可证

MIT。
