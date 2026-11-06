# CiteLens for agents（citlens-agent）

> **English** — CiteLens as a CLI tool for AI agents (Claude Code, Codex CLI, zcode, Cursor, …): high-recall multi-source literature search, relevance triage, open-access full-text fetching (with an optional scansci-pdf last-resort channel), reading notes, BibTeX/RIS export, coverage audits and mechanical review verification — one shared literature pool across all your agents. The agent plans the queries and writes; this repo provides the reproducible retrieval machinery. Adding the free keys of the open scholarly indexes (Semantic Scholar / OpenAlex / Crossref / Serper) is recommended; it lifts rate limits and recall.
>
> ```bash
> git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
> python -m venv .venv && .venv/Scripts/python -m pip install -e .   # macOS/Linux: bin/python
> .venv/Scripts/python install.py apply
> ```

citlens-agent 把 CiteLens 的文献检索能力做成一个 CLI 工具链（`citlens.cmd <tool> ...`，每次调用一份 JSON），装进各类 AI agent。装好之后给出指令，agent 找文献、写综述时会直接调这套工具。（2.0 起不再提供 MCP 服务器——CLI 一直是主接口，协议层只是它的转发。）

**分工**：模型负责拆概念块、拟英文检索词、判断切题与否、组织综述论证——查询纪律（复述自检 → 寄存器阶梯 → 侦察先行）见随仓库分发的 skill。多源检索、融合去重、引文扩展、全文抓取、格式导出、核验——这些要稳定可复现的执行，由本仓库的工具链承担。

## 框架总览

```
                      ┌─ 你（agent）：拆块 → 侦察学词 → 拟正式查询 ─┐
                      │                                            ▼
  search ─ 八路召回家族 ─ 每路 5 个元数据源*，RRF 融合，found_by 记票
    │        （agent 查询@40 / 主题原文@20 / 标题探针 / 相似推荐 /
    │         引文雪球 / web 桥 / 综述收割 / 政策语料；可选 pivot 第二波）
    │         *arXiv · Semantic Scholar · OpenAlex(AND) · OpenAlex(相关性) · Crossref
    ▼
  pool ─── 共享文献池（按主题累积；越搜越厚）
    ├─ screen ─ 三通道分带（本地嵌入 + BM25 + 家族投票）core/uncertain/likely_off
    │     └─ 可选决策层 decide：LLM logprobs 读出校准概率，高置信自动定带、
    │        低置信升入 uncertain 等终审（选择性预测，端点可自配）
    ├─ notes ─ 逐篇判定记录（core 笔记可直接当 expand 种子）
    ├─ expand ─ 前向/后向引文链 + 相似推荐（词汇无关通道：框架缺口的兜底）
    ├─ gaps ── 概念块×年代覆盖矩阵 + 原文局限句挖掘 + novelty check
    ├─ fetch ─ OA 链（arXiv→S2→OpenAlex→Unpaywall→CORE）→ 可选 scansci-pdf
    │          末棒（出版商直连/机构通道/中文库/Sci-Hub，用户授权启用）
    ├─ dedup ─ DOI/arXiv/题名+共作者三信号查重，--merge 收拢
    ├─ export ─ BibTeX / RIS / EndNote / CSL JSON
    └─ verify ─ 综述机械核验：[n]→参考文献→池内记录→span 逐字回查
```

**两个机械信号层**（零 LLM，如实降级）：

- **饱和信号**（`search` 报告内）：把召回家族当独立捕捉场做 capture–recapture（Chao1）估计覆盖；本轮新增占比高 = 池在长，弱查询占比高 = 词汇错配未消。
- **扩搜建议**（`screen` 报告内）：uncertain 占比过高 / 单家族命中占比过高 / core 太薄 → 建议 `expand --from-notes core`。

**可靠性层**：统一重试传输（429/5xx/断连按退避重试，尊重 Retry-After）、进程级限速、熔断（连续失败即停用该源并如实报告）、预算护栏（OpenAlex 日计数持久化）、缓存防毒（失败永不进缓存）。S2 的覆盖兜底链：OpenAlex 标题索引 → S2 → Crossref（无 key、无配额游戏）。

**无 key vs 有 key 的真实差别**（第三方满血测试实测）：S2 匿名池在连续取数时更容易 429——如实进 failed 桶、该查询跳过，`expand` 的种子解析与 `survey` 收割会明显缩水。配 key 后 S2 健康桶 `failed=0`，但**仍可能出现 429 burst**：区别是重试后能过，而不是"没有 429"。`web` 家族即使有 Serper，单查询能解析成文献记录的 URL 也很少——瓶颈在 URL→文献解析，不在搜索本身。

## 一个调用面——CLI（2.0 起）

13 个工具、一份共享数据家、一个 JSON 契约、一条进入路径：`citlens.cmd <tool> ...`。每次调用一个子进程、结果单 JSON 打印、全量记录始终落盘在池旁文件里。

命令分两类：

- **`search`（以及 `fetch --background true`）按脱离任务跑**：~20 秒先拿到 job_id（检索真要几分钟，runner 必须活得比你的 shell 长），轮询 `status` 取结果。
- **其余命令同步执行**（screen/expand 1-2 分钟）：要后台就用你 shell 自己的后台机制包裹（实测：从短命 shell 命令派生的脱离任务会随 shell 进程树一起被清理，所以这些不做 detach）。

死任务自愈：任何状态读取都会回收"runner 进程已死或静默超 45 分钟"的任务并落盘 `lost` 与原因——任务永远不会永远挂在 running。

## 实测效果（LitSearch 基准，15 题）

| 指标 | 基线（八月 ranklab） | 现在 |
|---|---|---|
| 金标命中@20 | 5/15 | **9/15 稳定**（q3/q8/q12/q1 复活，q12 真 driver 终池 #3/173），另 2 题在门槛波动 |
| 决策层抽查 | —（未上线） | 36 条人工对照：86% 完全一致，0 硬错，其余保守偏移 |
| 全文链 | OA 链 | + scansci 三档实测通过（出版商直连 Nature 2024 新文 / Unpaywall / Sci-Hub 浏览器档） |

逐臂证据与产物在 [tools/](tools/README.md)；诊断方法论模板在 [docs/agent-loop-failure-template.md](docs/agent-loop-failure-template.md)。

## 安装

建议直接把仓库网址发给你的 Agent，它会完成所有准备工作。可以直接发这句：

> 请帮我安装 CiteLens：克隆 https://github.com/yfxiao123/citlens-agent ，严格按仓库里的 INSTALL.md 完成安装和注册，装好后运行一次 citlens doctor 验收，并告诉我缺哪些免费 key、去哪注册。

自己动手：

```bash
git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS/Linux: .venv/bin/python
.venv/Scripts/python install.py init            # 可选：录入免费 key 提升效果
.venv/Scripts/python install.py apply           # 装 CLI shim + 共享配置 + skill（并清理 1.x 的 MCP 注册）
```

**一些开源学术网站的 key**。用于增强检索功能：

1. `SEMANTIC_SCHOLAR_API_KEY` — （[免费申请](https://www.semanticscholar.org/product/api)）
2. `SERPER_API_KEY` — （[serper.dev](https://serper.dev) 免费 2,500 次）
3. `OPENALEX_API_KEY` — 日预算 ×10（[openalex.org/premium](https://openalex.org/premium)，个人研究者免费）
4. `OPENALEX_EMAIL` / `CROSSREF_EMAIL` — 礼貌池待遇，留个邮箱即可，**无需注册**

装好后运行 `doctor`：报告 key 的缺失项、效果和注册地址，照着填进数据目录的 `.env`（也可以让 agent 帮你填）。如果有缺失，限流降级会如实给出。代理设置、数据目录布局、卸载回滚、故障排查见 [INSTALL.md](INSTALL.md)；`.env` 各键含义见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 工具

| 工具 | 作用 |
|---|---|
| `search` | 八路召回（含可选 pivot 第二波），RRF 融合；接受 agent 检索词、标题探针、web 查询、政策查询，返回逐查询命中数与饱和信号 |
| `pool` | 读取并过滤既有文献池，不发起检索 |
| `screen` | 相关性分带（core / uncertain / likely_off）：本地嵌入、BM25、家族投票；可选决策层（`decide: true`）用校准概率自动定带，低置信自动升级终审；附扩搜建议 |
| `gaps` | 「找空白」的机械基底：概念块×年代覆盖矩阵、挖掘原文局限句、novelty check |
| `expand` | 前向/后向引文链与相似推荐扩展；可直接取 core 笔记当种子 |
| `notes` | 阅读笔记：逐篇判定（core / uncertain / off），存入记录 |
| `dedup` | 去重报告：doi / arXiv / 题名+共作者三信号，`--merge` 合并 |
| `fetch` | 抓取开放获取全文（OA 链 + 可选 scansci-pdf 末棒）；无全文时返回摘要并标注"仅摘要级"；支持后台任务 |
| `export` | 文献池导出 BibTeX / RIS / EndNote XML / CSL JSON |
| `audit` | 计算文献池对主题内高被引综述参考文献的覆盖率 |
| `verify` | 机械核验综述：[n]→参考文献→池内记录逐层核验，span 在被引原文逐字出现，计算引用精度 |
| `status` | 查询后台任务进度（检索与全文下载共用） |
| `doctor` | 健康检查：路径、检索源、逐 key 引导、池数量、任务状态、嵌入运行时 |

## 使用示例

一次真实用法：一篇硕士开题的文献基础。把源论文和 9 个检索方向交给 agent，它用 `search` 跑了 11 个子题、`fetch` 抓了 364 篇开放获取全文，最后汇成一份带引用建议的分类文献库——1072 条总账、9 份方向阅读清单、覆盖审计，没拿到全文的条目也逐条给出获取渠道。介绍与样例见 [docs/examples/thesis-library](docs/examples/thesis-library/README.md)，完整真实产物在独立仓库 [citlens-agent-examples](https://github.com/yfxiao123/citlens-agent-examples)（不随本仓库 clone 下载）。

## 支持的客户端

CLI 对任何能跑命令的 agent 都直接可用。安装器另通过声明式注册表（`agents.json`）认识 21 个客户端——把 skill 装进它们各自的 skill 目录，并在发现 1.x 时代的 MCP 注册时自动清理（指向的 server 文件已不存在，留着只会是死条目）。

> 本安装器用固定命名空间（`~/.citlens/config.json`、shim、`~/.agents/skills/citlens`），多个实现会互相覆盖。

## 数据与共享

所有客户端共用一个数据家（默认 `~/.citlens/home`，安装时可用 `--home` 指定）。文献池按主题累积在 `data/litdb/`。检索任务以后台进程运行，独立于发起它的会话：客户端关闭后任务继续，任何 agent 都能查询进度并读取结果。

## Roadmap

- uncertain 带 cross-encoder 精排
- ASReview 式反馈环：agent 的 PRISMA 判定回流为下一轮 pool 读取的优先级
- 决策层阈值在更大金标集上的全量校准（现试点 n=5）

## 许可证

MIT。
