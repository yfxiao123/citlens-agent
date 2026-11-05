# Changelog

## Unreleased — reliability: one retrying transport, honest failures

起因：检索"看起来不稳定"。审计发现它不是容易失败，而是**失败之后伪装成
空结果**——429/超时被吞成 `[]`，健康表把失败计成 empty；而所谓的整源重试
是死代码（没有任何源会把异常抛到那一层）。

### 新增

- **screen 阈值首次金标校准（`tools/calibrate_screen.py` + 默认值上调）**：
  离线 harness 对 LitSearch ranklab 金标池（15 题、每题 ~137 候选、带 gold
  标注）用**生产同款通道代码**（BM25 + 本地 bge，同权重同归一化）做
  (core_t, off_t) 网格扫描。15 题中 10 题的 gold 不在池内——那是当年检索腿
  自己的漏召（gold_rank_pool=None，如实跳过），不是分带问题；有效 5 题 7
  gold。发现：**默认 0.5 把 ~77% 的池子标进 core**（分带失去分流意义；当日
  真实 60 篇池同样 72% core 印证），而 core_t=0.65–0.70 在**零金标漏失**下
  core 缩 5 倍（105→21/137）。默认上调 0.5→0.65：试点 n=5 故取中不取边界；
  单抬 core_t 是不对称安全的（gold 只会从 core 滑进同需精读的 uncertain，
  绝不会掉进 likely_off——那是 off_t 管的）；off_t 维持 0.32。多家族池的
  全面校准（consensus 通道会移分布）待更多池子，harness 已入库可随时复跑。

- **池级信号（`citens/signals.py`，零 LLM）——「搜多广/何时停」的机械回答**：
  - **饱和信号（`search` 报告新块 + MCP `saturation` 字段）**：召回家族当独立
    捕捉场，对 `found_by` 做 capture–recapture（Chao1：N̂ = S + f1²/2f2），
    估计池覆盖与未召回量；叠加本轮对主题池的新增占比与弱查询占比，输出
    近饱和 / 建议继续 / 无法判定 + 逐条理由。实测（同主题换措辞复搜）：
    f2=0 覆盖不可估但新增 87%——增长信号独立发声判"继续"，不因估计缺席而
    装聋；判定永远带"agent/raw 同源查询会高估覆盖"的警示，收工仍需 audit。
  - **扩搜建议（`screen` 输出 `expand_advice`，decide 后自动重算）**：
    uncertain 带占比 / 单家族命中占比（召回未经佐证，词汇错配的典型信号）/
    core 太薄，任一越线即建议 `expand --from-notes core`（判定回流为种子的
    反馈环入口）。实测：60 篇池单家族命中 98% → 正确触发并给出确切命令。
  - 修复第三个 CWD 陷阱：`--out` 默认 `citlens-runs` 也是 CWD 相对——手动
    启动会在仓库下 fork 私有 run 目录；现锚定数据家（与前两个陷阱同族：
    .env、litdb）。

- **screen 决策层（`citens/decide.py`，`screen --decide` 可选）**：相关性三分带
  读成三个带括号选项上的 next-token 概率分布（LLM-as-Jev 免训练 readout，
  arXiv:2610.02076）——高置信（0.8）自动定带，与机械通道独立一致时放宽到
  0.6，低置信强制升入 uncertain 等 agent 终审，格式偏离不猜；端点失败保留
  机械分带并如实记因。逐条 `decided_by`/`decision_probs`/`agrees_mechanical`
  溯源。检索核心依旧零 LLM：不配 `LLM_API_*` 端点，行为与从前逐字节相同。
  实测（60 篇真实池，DeepSeek）：60/60 决策、0 失败、47.6s；38 篇手标
  spot-check 一致或保守偏移，字面撞词（核武器项目报告、Z39.50 标准、肺炎
  分诊）全部落入 likely_off。依赖证据：System One 模型分类强校准好但
  relevance gating 打平（arXiv:2610.02267）——所以特征带主题与概念块上下文、
  阈值保守、升级优先；LitSearch 校准待做，阈值全部是显式 setting。
- **CWD 陷阱修复（config）**：`.env` 与文献池此前都按进程 CWD 相对解析——
  任何不从数据家启动的进程会**静默丢掉全部 key**（实测：OpenAlex 全程匿名
  撞进耗尽的匿名池 → 429 风暴；web 家族谎报"SERPER 未配置"而 key 就躺在
  `<home>/.env`），并在仓库里 fork 出私有 `data/litdb` 分裂共享池。现在
  `.env` 按 CWD → `CITLENS_HOME` → config.json home 解析，`litdb_dir` 默认
  锚定数据家。test_health +6 检查。

- **免费 key 引导（`citens/keyguide.py`）**：单一事实源——每个可选 key 的
  作用（缺了具体降级什么，含实测数字）、注册地址（全部免费）、成本、按
  实测影响力排序（S2 key 保可靠性 → Serper 撑起 web 家族 → OpenAlex key
  十倍日预算 → 两个 polite-pool 邮箱免注册）。三个出口共用：
  `doctor` 返回结构化 `key_guide` + 逐 key 可行动 notes（效果 + URL +
  写到哪个 .env）；`install.py init` 向导描述同步增强；skill（两个安装
  副本）指示 agent 在 key 缺失时**一次性**向用户转述引导，不纠缠不阻塞。
  recall driver 的 web 家族在 SERPER_API_KEY 缺位时就地写明退路与注册地址。

- **TLS 走系统证书库（`truststore`）**：SSL 审查代理（校园/企业网关）会给每个
  TLS 握手注入自己的 CA——它装在 Windows 系统证书库里，但 Python 的 certifi
  包里没有，于是被审查的主机全部死于
  `CERTIFICATE_VERIFY_FAILED: self-signed certificate in chain`（实测：
  api.semanticscholar.org 全程连不上、其余源正常——典型的本地拦截特征）。
  客户端工厂在首次建连时 `truststore.inject_into_ssl()`（进程级一次，同时
  覆盖 httpx 与 arxiv 包装器的 urllib）；`TLS_TRUST_SYSTEM_STORE=false`
  回到 certifi 行为。依赖加入 pyproject（`truststore>=0.9; py>=3.10`）。

- **统一网络层（`citens/net.py`）**：所有出站请求改经 `net.async_client` /
  `net.sync_client` 工厂——挂 `RetryTransport`（429 / 408 / 5xx 与连接错误、
  读写超时、连接重置按 `Retry-After`（秒或 HTTP-date，封顶
  `HTTP_BACKOFF_CAP_S`）或等抖动指数退避重试；**其余 4xx 含 401/403 一律
  不重试**，响应带 `extensions["citens_attempts"]`）+ 按名字进程级共享的
  `RateLimiter`（槽位预约制：S2 有 key 1.1s / 无 key 3.0s、OpenAlex 0.12s、
  Crossref 0.1s，async 检索腿与 sync 全文腿共用一个桶）。重试日志走
  stderr，不触碰 driver 的 stdout-JSON 契约。S2 的模块级锁与自带 429 循环
  移除；`_throttled_get/_post` 保留签名，对工厂 client 不再二次限速。
- **熔断器（`citens/search/base.py`）**：`SOURCE_CIRCUIT_FAILURES`（默认 3）
  次连续失败后本进程（= 本次 recall job）跳过该源，health 标
  `failed: circuit open after N consecutive failures (last: …)`，
  `search_report.md` 的 notes 写明原因；**401/403 即刻开路**并点名要检查
  的环境变量（`auth rejected (401) — check SEMANTIC_SCHOLAR_API_KEY`）。
  arXiv 被限流时不再让 15 个串行查询各自空等 90s。
- 新设置（`citens/config.py` Reliability 段）：`HTTP_MAX_ATTEMPTS`=4、
  `HTTP_BACKOFF_BASE_S`=1.0、`HTTP_BACKOFF_CAP_S`=30、`S2_MIN_INTERVAL_S`=0
  （按有无 key 自动）、`OPENALEX_MIN_INTERVAL_S`=0.12、
  `CROSSREF_MIN_INTERVAL_S`=0.1、`SOURCE_CIRCUIT_FAILURES`=3、
  `FULLTEXT_MISS_TTL_DAYS`=1。

### 修复

- **失败不再伪装成空结果**：`SearchSource.search()` 立下契约——全部关键词
  失败则抛出（health=`failed: HTTP 429 after 4 attempts`），部分失败则
  health=`partial: k/n queries failed (<原因>)`，失败查询在 `query_stats`
  中**缺席而非 0**（校准环不会把限流当词汇错配）。四个源（S2 / OpenAlex /
  Crossref / arXiv）共用 `_collect_cells` 实现；此前 6 处
  `gather(return_exceptions=True)` 只收 list、36 处 `except → return 空`。
- **health 键不匹配**：`search_round` 以显示名（"Semantic Scholar"）写
  health，`search_one_query` 却按注册名（"semantic_scholar"）查——failed
  桶在真实路径上**永远不可达**。统一按注册名键入。
- **空 cell 双计**：litsearch 健康桶对空结果同时 +ok 与 +empty，ok 一直
  虚高；三桶改为互斥。
- **失败不再被永久缓存**：`cache.put` 默认拒收空值（`allow_empty=True`
  显式开口，集中化 snowball 里的手写守卫）；fulltext 抓取失败改记
  `fulltext.miss` 短 TTL 负缓存（旧的 `""` 永久条目——TTL=0 命名空间——
  现在自动失效重试，报告写"近期抓取失败，N 天内不重试"）；expand 种子
  解析的传输失败不再缓存 30 天；OpenAlex venue 解析失败不再把 `""` 固化
  成"不存在"；seeds 全失败的 `[]` 不再入缓存。
- `base.py` 的整源重试 `_search_with_retry`（固定 1.5s/3s、一词 429 全部
  重跑、放大请求量）删除——重试下沉到请求级传输层。
- OpenAlex 日预算计数改临时文件 + `os.replace` 原子写。
- arXiv 超时改为抛出 `TimeoutError`（failed）而非返回 `[]`（empty）。
- `collect` 的两处手写 4 次退避循环（与传输层重试叠加会 16 次）改为单次。

### 测试

- 新增 `tests/test_net.py`（46 项，MockTransport 零网络：429→成功、
  Retry-After 秒/日期/封顶、5xx 等抖动区间、400/401/403/404 不重试、
  ConnectError/ReadTimeout 重试与耗尽语义、POST 重试、sync 同策略、
  限流槽位、工厂标记）与 `tests/test_health.py`（44 项：health 三态 +
  partial、`_collect_cells` 契约、熔断开/合/阈值 0、401 即刻开路、
  litsearch 桶互斥、`failure_reason` 花括号消毒、arXiv 超时抛出、
  cache 空值守卫、fulltext 负缓存含旧 `""` 自愈）。全套 11 个文件 398 项绿。

## Unreleased — library management: dedup, reading notes, export formats

- **去重报告（`dedup` 工具）**：`citens/library.py` 的
  `duplicate_groups` / `dedup_pool`，三种信号（精确 DOI、arXiv id、模糊
  题名 + 共享作者——与检索时 dedup 同一套保守规则）找出累积池里的嫌疑
  组；报告默认只读，`--merge`（仅主题池，写 .bak 后合并）把每组折叠成
  DOI 承载的保留记录，pdf_url/摘要/found_by/matched_queries 并入、引用
  数取最大。
- **阅读笔记（`notes` 工具）**：逐篇判定（core / uncertain / off，与
  screen 三带对齐）+ 一句话理由，按主题落盘 `data/notes/<slug>.jsonl`；
  不在池内的 fetch-only 论文也能记。判断记忆落地：`expand --from-notes
  core` 直接把 core 笔记当种子（与 --seeds 合并去重）——ASReview 式
  反馈环的第一段闭环。
- **导出格式**：EndNote XML（ref-type 17/3，DOI 走
  electronic-resource-num）与 CSL JSON（citeproc 兼容，author 按
  family/given 拆分），`export` 的 `--format` 增至 bib/ris/endnote/
  csljson，缺字段照旧留空不编造。
- 测试：`tests/test_library.py` 30 项离线检查（分组信号/合并语义/笔记
  存取/两种导出格式解析/from-notes 种子收集），全套 220+ 绿。


## Unreleased — recall: query feedback, HyDE probes, seed expansion

三项都对着 597 题金标剖析的结论：71% 漏检金标与问题共享 ≤2 个内容词——
召回瓶颈是词汇错配，不是排序。

### 新增

- **`expand` 工具（判断反馈环）**：`citens/search/expand.py` + CLI/MCP。
  以你判定的论文为种子（DOI / arXiv id / 标题，经 S2 解析、arXiv-only
  种子合成 DataCite DOI 供引文方向使用），跑引文链（backward/forward/
  OpenAlex related）+ S2 相似推荐四个方向，新记录带 `found_by=["expand"]`
  入池。扩展不是切题认定，仍走 screen + 人工判断。种子上限 6、逐方向
  解析缓存、unresolved 如实上报。离线 27 检查 + 真网络 smoke（Transformer
  论文种子：2 种子解析 → 16 新记录）。
- **查询级反馈**：`search` 报告新增"查询反馈"表与 `queries.json` 工件，
  MCP 返回带 `query_feedback` / `weak_queries`——每条查询的实际命中数与
  empty/thin/ok 判定。弱查询=词汇错配信号，SKILL 教 agent 换论文侧词汇
  重拟该概念块，而不是原词重试。
- **HyDE 标题探针**：`title_probes` 上限 2→3，语义升级为"假想论文标题"
  ——用论文侧词汇写理想论文的标题，喂 OpenAlex 标题索引；这是词汇错配
  的另一个绕行通道（引擎已实测该形态对金标可返回 rank-1）。

### 修复

- **S2 不解析 arXiv DataCite DOI**（expand 种子解析 404）：路由复用
  snowball 的 `_s2_paper_id`（`DOI:10.48550/*` → `ARXIV:*`）。

## Unreleased — bench

### 全量 597 题基准（2026-10-24，`--all-questions`，仅 raw 家族，零 LLM）

- **排序杠杆在 n=597 上成立**：同配额池 `screen_full` R@20 0.118→0.141、
  R@5 0.069→0.132、MRR 0.046→0.117（McNemar b=14 c=0，p=0.0001）；全并集
  `screen_union` R@20 0.161 / R@5 0.147 / MRR 0.124，对两种基线均 b=27、
  c=0（27 题增益、零倒退，R@5 的 Wilson 区间不再重叠）。
- **召回天花板有了全集数字**：自然语言问题作唯一检索词时，仅 16.8% 的
  金标进入全并集（配额池 14.6%）——排序无法修复另外 83%，广度来自 agent
  造词与种子扩展。分集合：inline_acl 入池 23.5% vs manual_iclr 8.8%。
- **事后更正（影响 0.2.0/0.3.0 的 15 题数字）**：10-18 运行期间 OpenAlex
  全程返回 200 空响应并被缓存固化，15 题结果等效 3 源。同池排序对比内部
  仍有效（缺源对各臂均等），绝对召回偏低；是否在健康源上重跑 15 题待定。
- **bench 加固**：空源（200-with-zero）单次重试后仍空才缓存——不再盲目
  固化瞬时空响应；`cells.json` 改批量落盘（每 10 个 cell + 收尾 flush），
  全量跑不再每个 cell 重写整份几十 MB 的缓存；`--n` 现在也约束
  `--all-questions`；产物 md 的头部与 caveats 按模式生成。

## 0.3.0 — 2026-10-18

把"可核验"从散文纪律变成工具，并修掉 0.2.0 在诚实性/口径上的缺陷。仍然零 LLM key。

### 新增

- **`verify` 工具（综述机械核验，零 LLM）**：`citens/grounding/verify.py` +
  `citlens_tools.py verify` + MCP 工具。检查 (a) 每个 `[n]` → 参考文献条目；
  (b) 每条参考文献 → 池内记录（DOI 或归一化标题），解析不到即"编造/不可溯源
  引用"（蜜罐）；(c) 每条判定的 `span` 必须在被引论文的已抓取全文中逐字出现
  （无全文时退到摘要，并计为 abstract-only）；(d) 六类判定校验（supported /
  partial / background / contradictory / unsupported / unverifiable）；(e) 计算
  引擎同一套诚实块（citation_precision、unverifiable_rate、grounding、
  papers_cited/pool_size），写 `verification.jsonl` + `honesty.json`，返回
  `clean` 门。`clean=false` 不得交付。verdicts 文件格式见 SKILL.md。
- **bench 可复现性与统计**：`--driver-arm` 把仓库自己的七家族 recall leg
  接入为 end-to-end 臂（逐题 live 运行并缓存）；`--all-questions` 支持全量
  LitSearch 问题（仅 raw 家族，因为冻结 planner cache 只覆盖 15 题）；每次
  运行写 `manifest_latest.json`（题目、gen-cache hash、caveats）；汇总与配对
  比较加入 Wilson 95% 区间、exact McNemar、paired bootstrap。

### 修复

- **`found_by` 家族投票不再漏记**：s2_rec / snowball / web / survey 现在按
  各自家族的（配额内）头部投票，而不是只给"最终新增"的文献投票；去重合并
  `_merge_variants` 会累计 `found_by`（此前合并会把票丢掉）。共识通道与
  ≥2/≥3 家族统计因此更接近真实。
- **web 桥接健康桶**：`WebSearchSource` 记录每个查询 ok/empty/failed，driver
  写入健康表；失败不再被吞成 `[]`（keyless 引擎挑战/被限流时此前看起来像
  "零命中"）。
- **排除日志原因码**：`exclusions.jsonl` 现在区分 `family_quota` /
  `duplicate_or_merged` / `ranked_below_target`，不再把所有未保留记录都标成
  "ranked_below_target"；`search_report.md` 与 `report.exclusions` 同步计数。
- **oa_title 空结果显式说明**：预算耗尽/无匹配不再静默消失。
- **配置迁移**：`install.py apply` 会把旧安装（引擎/portable 时代）的九家族
  `families` 迁移为七家族并打印迁移行；`doctor` 新增 `families_invalid`，
  配置含不支持的家族时 `ok=false` 并给出修复提示（此前 doctor 报 ok 而
  `search` 直接拒绝——本机踩过）。
- **docs/口径**：README、CHANGELOG、bench 文档、skill 的"同池只换排序"、
  "33.3% 与九家族+LLM 持平"、"任何地方都无 LLM"、"七工具"等表述按实测改正；
  工具数更新为 9，版本号统一（0.3.0）。

### 测试

- 新增 `tests/test_verify.py`（27 checks）：引用解析、DOI/标题解析、蜜罐、
  dangling marker、span 逐字匹配、六类判定、precision/grounding 算术、产物。
- `tests/test_screening.py` 增加 `_merge_variants` 保留 found_by 的回归检查。

## 0.2.0 — 2026-10-18

切题判断的三层增强——仍然零 LLM key，agent 仍是裁判，工具拿到的是可解释的分流。

### 新增

- **`screen` 工具（相关性三分带）**：对池子逐条打分并分带 core / uncertain /
  likely_off，写 `screening.jsonl`。三个机械可解释通道，逐条优雅降级：
  - **semantic**（可选 extra `citlens-agent[embedding]`，本地
    sentence-transformers，默认 BAAI/bge-base-en-v1.5，永不触碰 LLM key）：
    title+abstract 对每个概念块查询的 cosine 取 MAX——命中一个概念块即切题；
  - **lexical**：BM25（IDF、CJK bigram）对全池归一化——精确术语压过 paraphrase；
  - **consensus**：`found_by` 家族投票（见下），4 家族饱和。
  权重逐条按"该记录实际拥有的通道"重归一（缺元数据不惩罚）。**分流不是判决**：
  绝不自动剔除，agent 终审并把最终排除记入 exclusions（PRISMA）。阈值默认
  0.5 / 0.32（启发式，尚未在 LitSearch 金标上校准，报告必须带阈值与通道）。
- **`found_by` 家族投票**：recall 驱动记录每条记录被哪些召回家族命中
  （agent/raw/oa_title/s2_rec/snowball/web/survey），写入 pool 记录与
  exclusions 日志；search_report 新增"≥2/≥3 家族共识"统计。跨家族独立命中
  是免费的切题信号——`screen` 的 consensus 通道消费它。
- `doctor` 新增 `screen_embedding_runtime` 探针（本地嵌入可用性，缺 extra 时
  明示 lexical+consensus 仍可用）。

### 修复

- **snowball 相关性准入**：词集重叠 → BM25（IDF 加权）。原实现让共享泛词
  （"method/analysis"）的高被引论文压过精确命中的小论文；且 `[a-z]{4,}` 分词
  对中文主题恒为 0 分。现在走共享 `_terms` 分词器（CJK bigram），引用数只在
  BM25 同分时决胜（分数决胜，不是名次决胜）。

### 基准（bench/bench_screen.py，LitSearch 冻结 15 题）

同一候选池只换排序的对照：family-seat 序 R@20 6.7% / MRR 0.020 →
**对完整候选并集跑 screen（本地嵌入）R@20 33.3% / R@5 26.7% / MRR 0.178**——
与引擎九家族+LLM 级联在此样本上的公布成绩持平，而本链路无 LLM。语义通道是
主杠杆（词面+投票单独几乎不动基线）；家族/目标截断会切掉本可被 screen 捞回
的金标（综述工作流建议 `target: 0` 后再筛）。详见 bench/README.md。

## 0.1.0 — 2026-10-17

首个独立版本：从 CiteLens 引擎仓库（yfxiao123/citens，portable 层）拆出，重塑为
**面向 agent 安装、零 LLM key** 的独立仓库。

### 变革

- **零 LLM key 设计**：`citens` 核心只保留 LLM-free 子图（sources / snowball /
  survey_seed / websearch 抓取半段 / fulltext / citations / collect 池层 / litsearch
  纯函数）；Settings 移除全部 LLM 字段；`doctor` 无必填键。
- **agent 即规划器**：九召回家族 → 七家族。planned/HyDE/pivot（用 LLM 生成查询的
  三族）由调用方 agent 的 `queries` / `title_probes` / `web_queries` 参数替代；
  LLM 级联排序移除，相关性判断交还 agent（SKILL.md 明文）。
- **工具面**：search / pool / **fetch**（OA 全文，摘要兜底）/ **export**（BibTeX/RIS）/
  **audit**（综述参考文献覆盖锚点核验）/ status / doctor；移除 plan/questions/review
  （其纪律全部写入 SKILL.md 由 agent 亲自执行：编号主张、四级判定、蜜罐、辩护律师、
  重写重验、诚实数字块、PRISMA 排除、收工协议）。
- **安装器**：仓库根布局（无 portable 子目录）；init 向导全可选项；驱动复用范围化
  （显式 engine 切换时驱动跟随新树）；apply 自动创建数据家。

### 检索方法（与引擎逐字一致）

RRF 融合 k=60、每家族 30 席、每源 20 深、agent 查询腿 40 深；OpenAlex title.search
5 词硬截断；S2 推荐 1rps 节流；arXiv 断连重试 ×2；诚实健康桶（源失败 ≠ 零命中）。
