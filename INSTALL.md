# 安装与配置

目标：把 CiteLens 装进你的 AI agent。全程不需要任何 LLM API key。

## 前置条件

- Python ≥ 3.10（`python --version` 可执行）
- git
- 你至少有一个 MCP 客户端（Claude Code / Codex CLI / zcode / DSH / Cursor / ...），或用 CLI 通道
- 网络可达 arxiv.org / api.semanticscholar.org / api.openalex.org / api.crossref.org

> **代理注意（Windows 常见坑）**：若 git 报 `Failed to connect to 127.0.0.1:7897`，说明全局配了
> 一个没在监听的代理。临时绕过：`git -c http.proxy= -c https.proxy= clone ...`。
> pip 同理可加 `--proxy=""`。

## 1. 克隆并安装

```bash
git clone https://github.com/yfxao123/citlens-agent
cd citlens-agent
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS/Linux: .venv/bin/python -m pip install -e .
```

依赖极小且无 LLM SDK：pydantic、httpx、arxiv、markitdown[pdf]（PDF 转文本；缺失时
`fetch` 自动降级为摘要兜底并明说）。

## 2.（可选）录入检索源 key

```bash
.venv/Scripts/python install.py init
```

**没有任何必填项**——不配 key 也能跑（各源匿名访问，限速）。推荐的免费 key：
Serper（web 桥接家族）、Semantic Scholar（限速提升）、OpenAlex（key 或邮箱二选一）。
逐键说明见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 3. 注册进 agent

```bash
.venv/Scripts/python install.py plan     # 干跑：将检测到哪些客户端、会写什么
.venv/Scripts/python install.py apply    # 实际写入（写前自动备份，只动 citlens 一个键）
.venv/Scripts/python install.py list     # 查看全部 21 个已声明客户端
```

- 只装指定客户端：`apply --only zcode,claude`
- 没被检测到的客户端也强制生成配置：`apply --all`
- 手工粘贴型客户端：`install.py snippet zed` 打印即贴

注册内容是标准的 stdio MCP 条目（command = 本仓库 venv 的 python，args =
`<repo>/citlens_mcp.py serve --config ~/.citlens/config.json`）。skill 会同时安装到
`~/.agents/skills/citlens`（跨客户端约定）与各客户端自己的 skill 目录。

**重启你的 agent** 使 MCP 注册生效。

## 4. 验收

对 agent 说：

> run the citlens doctor tool

期望 `doctor.ok: true`，七工具（search/pool/fetch/export/audit/status/doctor）可见。
命令行直接验收：

```bash
.venv/Scripts/python citlens_mcp.py selftest
%USERPROFILE%\.citlens\bin\citlens.cmd doctor
```

再让它真跑一次（可选）：

> use citlens search for "diffusion models for time series forecasting" —
> craft the English queries yourself first

## 数据家布局

默认 `~/.citlens/home`（`install.py apply --home <路径>` 可改；已有旧安装会沿用其家）：

```
<home>/citlens-runs/<主题>-<时间戳>/   每次 search 的产物（pool.jsonl / search_report.md / exclusions.jsonl）
<home>/data/litdb/<主题>.jsonl         跨 run 累积的共享文献池（append_pool 落盘处）
<home>/fulltext/                       fetch 取回的全文文本
<home>/exports/                        export 产物（references.bib / .ris）
<home>/.env                            检索源 key（init 写入）
<home>/.cache/                         检索与全文缓存
~/.citlens/jobs/                       后台任务状态（脱离 agent 会话存活）
~/.citlens/config.json                 所有 agent 共享的本机配置
```

## 卸载 / 回滚

```bash
.venv/Scripts/python install.py uninstall    # 只移除本安装器写的东西；每个改动文件都有 .citlens-backup-<ts> 副本
```

## 故障排查

| 症状 | 处置 |
|---|---|
| git/pip 连不上 127.0.0.1:7897 | 死代理；`git -c http.proxy= -c https.proxy=`（pip `--proxy=""`） |
| doctor: python 不存在 | venv 没建成或换了位置；`apply --python <新路径>` 重写配置 |
| S2 大量 429 | 匿名池限速；配 `SEMANTIC_SCHOLAR_API_KEY`，或等滚动窗口（约 1 分钟）。健康桶会如实报 failed，不会假装零命中 |
| OpenAlex 配额 | works 搜索每次 10 credits、免费 1 万/天；不配 key 走匿名/邮箱礼貌池也可用。预算护栏见引擎仓库文档 |
| arXiv 偶发 ConnectError | 源不稳，驱动内建重试 ×2；仍失败会记入健康桶 |
| fetch 全是摘要兜底 | 缺 markitdown：`.venv/Scripts/python -m pip install "markitdown[pdf]"`；或该论文确实无 OA 版本（此时只能摘要级引用） |
| agent 看不到工具 | 重启 agent；确认其 MCP 配置里 `citlens` 的 command 指向本仓库 venv python |
| 中文控制台乱码/崩 | 环境变量 `PYTHONUTF8=1`（安装器写注册表/shim 时已带） |

## 引擎切换语义

本仓库自带 `citens` 检索核心（LLM-free 子集），不需要外部引擎。`--engine` 旗标仍受支持，
用于把已配置机器指回另一个 citlens-agent 检出（显式切换时驱动路径一并跟随新树，避免混合配置）。
