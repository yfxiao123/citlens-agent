# CiteLens for agents（citlens-agent）

> **English** — CiteLens as an MCP server for AI agents (Claude Code, Codex CLI, zcode, Cursor, etc.): multi-source literature search, open-access full-text fetching, BibTeX/RIS export and coverage audits, with one shared literature pool across agents. No LLM API key is needed; the agent plans the queries and writes, this repo provides the reproducible retrieval machinery. Free keys (Serper / Semantic Scholar / OpenAlex) are optional and only raise rate limits.
>
> ```bash
> git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
> python -m venv .venv && .venv/Scripts/python -m pip install -e .   # macOS/Linux: bin/python
> .venv/Scripts/python install.py apply
> ```

citlens-agent 把 CiteLens 的文献检索能力做成一个 MCP 工具服务器，装进各类 AI agent 客户端。装好之后，agent 处理找文献、查覆盖、写综述这类请求时会调用这些工具，而不是靠它自己的网页搜索。

## 设计

文献工作可以分成两类。一类需要判断力：把研究问题拆成概念块、写出合适的英文检索词、判断一篇论文是否切题、组织综述的论证。这类工作 agent 自己就能做好。另一类需要稳定、可复现的执行：多源检索扇出、结果融合去重、引文网络扩展、开放获取全文抓取、引文格式化导出。这类工作不适合靠每次现写的提示词完成，因为结果既不稳定，也无法复现。

citlens-agent 只承担第二类，因此它不调用任何 LLM，也不需要配置任何 LLM key。agent 把自己拟好的英文检索词传给 `search`，得到一个按固定方法构建的候选池；判断哪些论文切题、如何排序、综述怎么写，是 agent 的事。同样的输入总是得到同样的池子，检索方法写在代码里而不是提示词里，事后可以复查。

写综述时，工具提供证据材料：单篇全文抓取（取不到全文时退回摘要，并明确标注只能摘要级引用）、PRISMA 式排除日志、综述参考文献覆盖审计、BibTeX/RIS 导出。写作与逐条主张核验由 agent 按 SKILL.md 的流程执行：编号引用，每条主张对照原文给出四级判定（支持、部分支持、不支持、不可验证），写完后做引用真实性检查（每条引用必须能回溯到池内文献）和对抗性复查（以反驳的立场复核已判支持的主张），不支持的主张改写后复验，最后报告引用精度、不可验证率、全文 grounding 比例。这套流程沿用引擎仓库实测过的验证链：初稿引用精度 73%，改写复验后 98%。

## 安装

```bash
git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS/Linux: .venv/bin/python
.venv/Scripts/python install.py init            # 可选：录入检索源 key（全部可不配）
.venv/Scripts/python install.py apply           # 检测本机已装的 agent 并注册
```

重启 agent，让它运行 `doctor` 工具验收。完整流程（代理设置、数据目录布局、卸载回滚、故障排查）见 [INSTALL.md](INSTALL.md)；`.env` 各键的含义见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 工具

| 工具 | 作用 |
|---|---|
| `search` | 七家族召回，RRF 融合；接受 agent 拟定的检索词、标题探针与 web 查询 |
| `pool` | 读取并过滤既有文献池，不发起检索 |
| `fetch` | 抓取单篇开放获取全文，无全文时返回摘要 |
| `export` | 将文献池导出为 BibTeX / RIS |
| `audit` | 计算文献池对主题内高被引综述参考文献的覆盖率 |
| `status` | 查询后台检索任务的进度 |
| `doctor` | 健康检查：路径、key 名称、池数量、任务状态 |

## 检索方法

检索不依赖单一来源或单一查询词。`search` 执行七个家族：

1. agent 检索词：调用方按概念块拟定的英文查询，逐源深度检索
2. 主题原句：题目原文在 arXiv、Semantic Scholar、OpenAlex、Crossref 四源检索
3. 标题探针：agent 提供的已知论文标题，走 OpenAlex 标题索引
4. 相似推荐：以池头文献的 DOI 取 Semantic Scholar 推荐
5. 引文扩展：对池内锚点文献做被引与引用双向的一跳扩展
6. web 桥接：Google SERP 检索，结果锚定回论文记录
7. 综述收割：找到主题综述后收割其参考文献

各家族结果按 Reciprocal Rank Fusion 融合，每家族保底 30 席。常数沿用引擎仓库在 LitSearch 基准上的测量值（RRF k=60，每源深度 20）。在该基准上，这套方法的 recall@20 为 33.3%；作为对照，单组关键词查询为 6.7%，单一来源为 0%。

返回顺序是融合序，不是相关性排序，切题判断由 agent 完成。每次检索落盘三份产物：`pool.jsonl`（结构化文献记录）、`search_report.md`（各家族入池数与逐源健康表）、`exclusions.jsonl`（被裁剪的记录及原因）。检索源的失败单独计数并如实上报，不把失败的源报告成零命中。

## 支持的客户端

安装器通过声明式注册表（`agents.json`）支持 21 个客户端，自动检测本机已安装的并写入配置；写前备份，只增改 `citlens` 一项。已实测：Claude Code、Codex CLI、zcode、aider（CLI 通道）、DSH。声明式适配覆盖 Cursor、Windsurf、Gemini CLI、Qwen Code、Cline、OpenCode 等常见客户端；Zed、Continue 等手工粘贴型客户端用 `install.py snippet <name>` 生成配置。新客户端只需在 `~/.citlens/agents.d/` 放一个同格式的 JSON 文件。

## 数据与共享

所有客户端共用一个数据家（默认 `~/.citlens/home`，安装时可用 `--home` 指定）。文献池按主题累积在 `data/litdb/`，一个 agent 搜到的文献，其他 agent 直接可用。检索任务以后台进程运行，独立于发起它的会话：客户端关闭后任务继续，任何 agent 都能查询进度并读取结果。

## 与 CiteLens 引擎的关系

引擎仓库 [citens](https://github.com/yfxiao123/citens) 是自带 LLM 的完整版本：CLI、Web 控制台、桌面 exe，以及从查询规划到写作验证的完整流水线，适合"给一个题目、自动出综述"的独立用法。citlens-agent 面向已经在用 agent 的用户，只保留检索与证据工具。两者使用同一套检索方法和数据格式，`pool.jsonl` 可以互认。

## Roadmap

- 文献管理增强：去重报告、阅读笔记、更多导出格式（EndNote XML、CSL JSON）
- 更多客户端进入已实测列表
- 题面语义（embedding）检索通道，缓解检索词与论文用词不一致造成的召回缺口

## 许可证

MIT。
