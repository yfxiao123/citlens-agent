# CiteLens for agents (citlens-agent)

> **English quick start** — Install CiteLens into any MCP-speaking AI agent (Claude Code, Codex CLI, zcode, DSH, Cursor, ...). The agent plans queries and writes; this repo does the mechanics: 7 recall families over arXiv/Semantic Scholar/OpenAlex/Crossref/web, RRF fusion, citation snowball, survey harvest, open-access full-text fetch, BibTeX/RIS export, PRISMA logs. **No LLM API key needed** — your agent is the model. Optional free keys (Serper/S2/OpenAlex) raise quotas.
> ```bash
> git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
> python -m venv .venv && .venv/Scripts/python -m pip install -e .   # Windows; macOS/Linux: bin/python
> .venv/Scripts/python install.py apply                               # detects your agents
> # then ask your agent: "run the citlens doctor tool"
> ```

**把文献检索、文献管理、文献综述装进你的 AI agent——零 LLM key。**

你的 agent（Claude、Codex、zcode、DSH……）本身就是模型，所以这个仓库只做它做不好的事：可复现的机械检索。agent 亲拟英文概念块查询传给 `search`，仓库负责七家族召回、RRF 融合、引文滚雪球、综述收割、开放获取全文抓取、BibTeX 导出、PRISMA 排除日志；写作与逐条主张核验由 agent 按 SKILL.md 的验证链亲自执行。一份 `~/.citlens/config.json` 让所有 agent 共享同一个文献池——在这边搜，去那边写。

## 宗旨

| 主线 | 能力 |
|---|---|
| 搜集文献 | 七召回家族 × 四学术源 + web 桥接，RRR 融合与家族席位配额，诚实健康桶（源失败绝不写成零命中） |
| 管理文献 | 跨 agent 共享池 `data/litdb/<主题>.jsonl`，`pool` 工具多维过滤（年份/引用/综述/DOI），BibTeX/RIS 导出 |
| 文献综述 | agent 按 SKILL.md 验证链写作：编号主张 → `fetch` 全文 grounding → 四级判定核验 → 蜜罐/辩护/重写 → 诚实数字块 |

## 三分钟装进 agent

```bash
git clone https://github.com/yfxiao123/citlens-agent && cd citlens-agent
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS/Linux: .venv/bin/python
.venv/Scripts/python install.py init             # 可选：录入 Serper/S2/OA key（全部可省）
.venv/Scripts/python install.py apply            # 检测已装的 agent 并注册；--only zcode 可指定
```

重启 agent，说一句 *"run the citlens doctor tool"* 验收。之后任何文献问题，agent 会自己走：**拟查询 → `search` → 逐篇判相关性 → `pool` 迭代 → `audit` 锚点核验**；要写综述时再走验证链。

完整流程（含代理注意事项、数据家布局、卸载回滚、故障排查）见 **[INSTALL.md](INSTALL.md)**；`.env` 键参考见 **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**。

## 支持的 agent

注册表 `agents.json` 声明 21 个客户端，`install.py apply` 自动检测并写入（写前必备份，只动 `citlens` 一个键）：

- **已实测**：Claude Code、Codex CLI、zcode、aider（CLI 通道）、DSH（bundle 通道）
- **声明式适配**（json-map / json-opencode / toml-block 方言）：Cursor、Windsurf、Gemini CLI、Qwen Code、Cline、Roo、Kilo、OpenCode、Trae、Copilot CLI、Goose、Crush、SST Opencode …
- **手工粘贴**：Zed、Continue、AMP 等（`install.py snippet <name>` 打印即贴配置）
- 新客户端 = 往 `~/.citlens/agents.d/` 丢一个 JSON，零代码

## 七个工具

| 工具 | 职责 |
|---|---|
| `search` | 七家族召回 + RRF 融合 + 席位配额；吃 agent 亲拟的 `queries` / `title_probes` / `web_queries`；写 pool.jsonl + search_report.md + exclusions.jsonl |
| `pool` | 纯磁盘读取过滤文献池；不检索 |
| `fetch` | 单篇开放获取全文（arXiv→S2→OpenAlex→Unpaywall→CORE），摘要兜底 |
| `export` | 池 → BibTeX/RIS（引擎同款 CitationTable，缺字段留空绝不编造） |
| `audit` | 池对 top 综述参考文献的覆盖率（收工协议锚点核验） |
| `status` | 轮询后台检索任务（任务进程脱离会话存活） |
| `doctor` | 健康检查；**没有任何必填 key** |

## 一分钟架构

```
        你（agent，模型在此）                    本仓库（机械，可复现在此）
 ┌───────────────────────────────┐    ┌────────────────────────────────────┐
 │ 读题 → PRESS 概念块拟英文查询   │───▶│ search: 7 家族召回（agent 查询/raw/  │
 │ 判相关性（粗排+精排都是你）     │◀───│   OA标题/S2推荐/滚雪球/web/综述收割） │
 │ 写综述 + 逐条主张四级判定       │───▶│ RRF 融合 + 席位配额 + 诚实健康桶     │
 │ 蜜罐/辩护/重写/诚实数字         │◀───│ fetch 全文 · export 引文 · audit 锚点│
 └───────────────────────────────┘    └────────────────────────────────────┘
            MCP over stdio（21 客户端）      共享数据家 ~/.citlens/home
```

检索家族与融合函数从引擎仓库 **逐字复制**（含测量常数：RRF k=60、每家族 30 席、每源 20 深）——引擎的 LitSearch 金标基准上，自适应腿 recall@20 = 33.3%，单 Planned 关键词 6.7%，单源 0%。三家族（planned/HyDE/pivot）的任务是"用 LLM 生成查询"，在本构建中由你替代，故不搬运。

## 与 CiteLens 引擎的关系

- **citlens-agent（本仓库）**：装进任何 agent 的免 LLM 版。检索/池/导出/全文机械层 + skill 验证链。
- **[citens 引擎](https://github.com/yfxiao123/citens)**：自带 LLM 的全家桶——CLI / Web 控制台 / 桌面 exe / 完整流水线（规划→排序→抽取→写作→验证→反思）。想要"给个题目全自动出综述"、不在乎配 LLM key 时用它。

两者共享同一套检索方法与数据格式（pool.jsonl 可互认）。

## Roadmap

- 管理增强：去重报告、阅读笔记、更多导出格式（EndNote XML、CSL JSON）
- 更多客户端进"已实测"列
- 题面语义 embedding 召回通道（词汇缺口金标的下一个杠杆，见引擎仓库 postmortem）

## License

MIT。
