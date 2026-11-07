# 安装与配置

目标：把 CiteLens 装进你的 AI agent（一个 CLI 工具链，任何能跑命令的 agent 都能用）。全程不需要任何 LLM API key。

> 这份文档也是给 agent 看的安装说明书——用户一句"帮我装
> https://github.com/yfxiao123/citlens-agent"就该触发你从上到下按节执行。
> 走完第 4 节后，把验收结果原样转述给用户：装了哪些客户端、doctor 是否
> ok、缺哪些免费 key 及其注册地址（转述一次即可，不纠缠）。

## 前置条件

- Python ≥ 3.10（`python --version` 可执行）
- git
- 你的 agent 能执行 shell 命令（Claude Code / Codex CLI / zcode / Cursor / ... 都可以）
- 网络可达 arxiv.org / api.semanticscholar.org / api.openalex.org / api.crossref.org

> **代理注意（Windows 常见坑）**：若 git 报 `Failed to connect to 127.0.0.1:7897`，说明全局配了
> 一个没在监听的代理。临时绕过：`git -c http.proxy= -c https.proxy= clone ...`。
> pip 同理可加 `--proxy=""`。

## 1. 克隆并安装

```bash
git clone https://github.com/yfxiao123/citlens-agent
cd citlens-agent
python -m venv .venv
.venv/Scripts/python -m pip install -e .        # macOS/Linux: .venv/bin/python -m pip install -e .
```

依赖极小且无 LLM SDK：pydantic、httpx、arxiv、markitdown[pdf]（PDF 转文本；缺失时
`fetch` 自动降级为摘要兜底并明说）。

> wheel 只含 `citens` 包与 `citlens_cli`（库形态）；`drivers/`、`skill/`、
> `install.py` 只随仓库分发——可用的 CLI 安装路径是**克隆 + `pip install -e .`**
> （上面的方式），从 wheel 直接装会得到一个找不到 drivers 的 `citlens-agent` 入口。

## 2.（可选）录入检索源 key

```bash
.venv/Scripts/python install.py init
```

**没有任何必填项**——不配 key 也能跑（各源匿名访问，限速）。推荐的免费 key：
Serper（web 桥接家族）、Semantic Scholar（限速提升）、OpenAlex（key 或邮箱二选一）。
逐键说明见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## 3. 装进 agent

```bash
.venv/Scripts/python install.py plan     # 干跑：将写什么、会清理哪些旧注册
.venv/Scripts/python install.py apply    # 写 shim + 共享配置 + skill；清理 1.x 的 MCP 注册
.venv/Scripts/python install.py list     # 查看全部 21 个已声明客户端
.venv/Scripts/python install.py status   # CLI 资产状态 + 残留旧注册
```

apply 写四样东西：

- `~/.citlens/bin/citlens.cmd` —— CLI 入口（`citlens.cmd <tool> ...`）
- `~/.citlens/config.json` —— 所有 agent 共享的本机配置（数据家路径、venv 解释器）
- `~/.agents/skills/citlens` —— 跨客户端约定的 skill（教学 agent 怎么用这套工具）
- 各被检测客户端自己的 skill 目录（声明在 `agents.json`，可用 `--only` 限定、`--all` 全覆盖）

同时它会**清理 1.x 安装留下的 MCP 注册**（旧条目指向的 server 文件已不存在）。一个客户端
都没检测到时照样写上面四样（不会 exit 1）——任何能跑命令的 agent 都能直接用 `citlens.cmd`。

## 4. 验收

对 agent 说：

> run `citlens.cmd doctor` and show me the result

期望 `doctor.ok: true`（配置里的 families 不含本构建不支持的旧家族名），十三个工具
（search / pool / fetch / export / audit / screen / gaps / verify / expand / notes /
dedup / status / doctor）可用。命令行直接验收：

```bash
.venv/Scripts/python citlens_cli.py selftest
%USERPROFILE%\.citlens\bin\citlens.cmd doctor
%USERPROFILE%\.citlens\bin\citlens.cmd tools
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
<home>/<review 所在目录>/verification/ verify 产物（verification.jsonl / honesty.json）
<home>/.env                            检索源 key（init 写入）
<home>/.cache/                         检索与全文缓存
~/.citlens/jobs/                       后台任务状态（脱离 agent 会话存活）
~/.citlens/config.json                 所有 agent 共享的本机配置
```

## 卸载 / 回滚

```bash
.venv/Scripts/python install.py uninstall
```

`uninstall` 移除本安装器装的 skill 副本并清理任何 citlens 注册残留，保留
`~/.citlens/config.json` / shim / 数据家。客户端配置文件只在**移除**旧注册时被改写，改写前会写
`.citlens-backup-<ts>` 副本；shim 与 skill 目录是**受管重建**（不是用户手写内容），因此没有
逐文件备份——需要回滚时用 `install.py apply` 重新指向目标实现即可。

## 故障排查

| 症状 | 处置 |
|---|---|
| git/pip 连不上 127.0.0.1:7897 | 死代理；`git -c http.proxy= -c https.proxy=`（pip `--proxy=""`） |
| doctor: python 不存在 | venv 没建成或换了位置；`apply --python <新路径>` 重写配置 |
| S2 大量 429 | 匿名池限速；配 `SEMANTIC_SCHOLAR_API_KEY`，或等滚动窗口（约 1 分钟）。健康桶会如实报 failed，不会假装零命中 |
| OpenAlex 配额 | works 搜索每次 10 credits、免费 1 万/天；不配 key 走匿名/邮箱礼貌池也可用。预算护栏见引擎仓库文档 |
| arXiv 偶发 ConnectError | 源不稳，驱动内建重试 ×2；仍失败会记入健康桶 |
| fetch 全是摘要兜底 | 缺 markitdown：`.venv/Scripts/python -m pip install "markitdown[pdf]"`；或该论文确实无 OA 版本（此时只能摘要级引用） |
| agent 看不到工具 | 确认 skill 已装（`install.py status`）；工具本身直接跑 `citlens.cmd <tool>` 验证 |
| 中文控制台乱码/崩 | 环境变量 `PYTHONUTF8=1`（安装器写注册表/shim 时已带） |

## 引擎切换语义

本仓库自带 `citens` 检索核心（LLM-free 子集），不需要外部引擎。`--engine` 旗标仍受支持，
用于把已配置机器指回另一个 citlens-agent 检出（显式切换时驱动路径一并跟随新树，避免混合配置）。
