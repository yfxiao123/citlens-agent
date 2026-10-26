# 配置参考（.env）

配置文件是数据家里的 `.env`（默认 `~/.citlens/home/.env`；`install.py init` 交互写入，
`--set KEY=VALUE` 脚本写入；已有值永不覆盖，未列出的键永不触碰）。

**本构建没有任何必填键，也不读任何 LLM 键。** 你的 agent 就是模型。下面所有键都只影响
配额与家族覆盖面。

## 检索源 key（全部可选）

| 键 | 作用 | 不配的后果 | 获取 |
|---|---|---|---|
| `SERPER_API_KEY` | web 桥接家族的 Google SERP 引擎 | `web` 家族整体跳过并在报告里如实说明（不是零命中） | serper.dev，免费 2500 次 |
| `SEMANTIC_SCHOLAR_API_KEY` | S2 搜索 / 推荐 / 滚雪球限速提升 | 匿名 ~1 rps 共享池，偶发 429（记入健康桶） | semanticscholar.org，免费 |
| `OPENALEX_API_KEY` | OpenAlex keyed 池（10 万/天） | 匿名池（够用，慢）；滚雪球引用图吞吐下降 | openalex.org，免费 |
| `OPENALEX_EMAIL` | OpenAlex 礼貌池（与 key 二选一） | 同上 | 填邮箱即可 |
| `CROSSREF_EMAIL` | Crossref 礼貌池 | 匿名访问，偶发限速 | 填邮箱即可 |

实测注意（沿用引擎仓库测量）：

- **OpenAlex 计费**：works 搜索每次 10 credits，免费 1 万 credits/天（UTC 重置）。代码内建
  日预算护栏（默认 9000，超支当天自动停用 OA 家族并明说），计数器持久化在缓存目录。
- **S2 推荐端点**限速远比图端点狠（滚动窗口 429），驱动已按 1 rps 节流；失败进健康桶。
- **Serper** 免费额度 2500 次；web 家族每查询深度 16，一次典型检索用 3-5 个查询。

## 访问层（可选，影响 `fetch` 的 PDF 抓取）

| 键 | 作用 |
|---|---|
| `HTTP_PROXY_FOR_CITELENS` | 抓付费墙 PDF/落地页时走此代理（如校园 EZproxy 或本地 SOCKS） |
| `EZPROXY_PREFIX` | EZproxy 前缀，抓取 URL 会被改写为 `{前缀}url=<目标>` 以乘坐你的图书馆会话 |
| `PAPERS_DIR` | 手工投放 PDF 的目录（默认 `papers`），`fetch` 优先读这里 |

## 运行面

| 键 | 默认 | 说明 |
|---|---|---|
| `SEARCH_SOURCES` | `arxiv,semantic_scholar,openalex,crossref` | `search` 扇出的元数据源子集 |
| `CACHE_DIR` / `CACHE_TTL_DAYS` | `.cache` / 30 | 检索与全文缓存位置与寿命 |
| `LITDB_DIR` | `data/litdb` | 共享文献池目录 |
| `OUTPUT_DIR` | `runs` | 产物目录前缀 |
| `PROFILE` | 空（通用） | 域档案（当前内置 `finance`：期刊白名单 + 术语表，影响 collect 与排序） |

## `verify` 综述机械核验（可选；无需任何 key）

`verify` 不调用 LLM，也没有配置项。它读：

- `--review <path>`：综述 markdown（正文 `[n]` + `References/参考文献` 段）；
- `--topic` 或 `--run-dir`：解析参考文献用的文献池（主题必须与检索时逐字相同）；
- `--verdicts <path>`：agent 的判定 JSONL，每行
  `{"claim": "...", "verdict": "supported|partial|background|contradictory|unsupported|unverifiable", "span": "原文逐字引用", "citations": [3]}`；
- `--text-dir`：`fetch` 的全文目录（默认数据家下 `fulltext/`；取不到全文时退到摘要）。

产物写到综述旁的 `verification/`：`verification.jsonl`（逐条 claim 的引用解析与 span
检查）、`honesty.json`（调用精度/不可验证率/grounding 的原始计数）。`clean=false` 表示
存在编造引用、悬空 marker、span 不在原文或判定缺失，必须修完再交付。

## `screen` 三分带（可选；全部可按调用覆盖）

| 键 | 默认 | 说明 |
|---|---|---|
| `SCREEN_EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` | 语义通道的**本地** sentence-transformers 模型（经 HF 缓存，进程内运行，永不触碰 LLM key）。置空串禁用语义通道（lexical+consensus 仍在）。中文主题可换 `paraphrase-multilingual-MiniLM-L12-v2` 或 `BAAI/bge-m3` |
| `SCREEN_CORE_THRESHOLD` | `0.5` | score ≥ 此值入 `core` 带（bge cosine 尺度上的启发式默认，未校准） |
| `SCREEN_OFF_THRESHOLD` | `0.32` | score < 此值入 `likely_off` 带；两值之间为 `uncertain` |

语义通道需要可选依赖：`pip install "citlens-agent[embedding]"`（CPU torch +
sentence-transformers，约 1 GB 磁盘）。首次调用会下载所选模型（bge-base 约
0.4 GB）；`doctor` 的 `screen_embedding_runtime` 字段报告运行时可用性。bge-*-en-v1.5
按模型卡说明无需检索指令前缀。

不存在的键：`LLM_API_KEY` / `LLM_MODEL` / 强弱档位——本构建无 LLM，`doctor` 也不会检查它们。
若你的 `.env` 里有（从引擎时代沿用），会被 `extra="ignore"` 安静忽略，无需清理。

## 数据家布局

见 [INSTALL.md](../INSTALL.md#数据家布局)。机器级配置（家路径、解释器、驱动路径、任务目录）
在 `~/.citlens/config.json`，由安装器维护，环境变量 `CITLENS_HOME` / `CITLENS_PYTHON` /
`CITLENS_CONFIG` 可临时覆盖。
