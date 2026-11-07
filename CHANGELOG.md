# Changelog

## Unreleased — round-3 retest: R1–R4 (suite hermeticity, pool path parity)

对 `main @ 0c0059a` 的复测（23-fix-round3.md）确认 H1/H2/H3 目标问题全部修复
（530 项全绿、无 P0/P1 回归），新抠出四条 P3 一并清掉；同时复核了上轮
"未独立复核"项：真机 verify_harness 34/34/0 未变，H4/H5/H6 现状未变（留下轮）。

- **R1 · 套件真机污染**：H1 只修了 `test_selftest`——`_temp_config()` 仍经
  `install.discover()` 读真机 `~/.citlens/config.json` 并 mkdir 真机数据家
  （`test_protocol`），`test_config_migration` 的 doctor 调用缺 `jobs_dir`
  兜到默认 `~\.citlens\jobs`（`jobs_root()` mkdir）。现在 `_temp_config`
  直接用本 checkout 路径手写配置（home/jobs 全在 tmp），migration cfg 补
  `jobs_dir` 且 doctor 子进程走沙箱 env。全新 HOME 跑完 17 套后目录树为空。
- **R2 · `pool` 的 `--run-dir` 漏统一**：`_pool_path_for()` 是 CLI 本地读，
  没走 `_caller_path`——同一相对 `run/x`，pool 按数据家、export 按调用者
  cwd 解析。现在与五个转发工具同语义（相对路径锚定调用者 cwd）。
- **R3 · 全仓 lint**：删 `tests/test_verify.py` 既有的 F841（未用 `pool`），
  `ruff check --select F,E9 .` 全仓干净。
- **R4 · GBK 终端**：`test_gaps.py` 两处子进程 `text=True` 不带 `encoding`，
  父进程按 GBK 解码 UTF-8 输出 → reader 线程 UnicodeDecodeError、
  `json.loads(None)`。显式 `encoding="utf-8"`；TESTING.md 补编码前提说明，
  并更新过期的 `test_selftest` 沙箱说明（H1 后不再假设本机 apply 过）。

Tests: test_retest_fixes +2（pool 相对 run_dir 双断言）；test_portable 101
不变；全量 17 套 532 项绿（新 HOME 零污染）；GBK 控制台不加
`PYTHONUTF8=1` 全绿；verify_harness 34/34。

## Unreleased — round-2 retest: H1/H2/H3 (test sandboxing, path semantics)

对 `main @ 9419fcf` 的轻量复测确认上一轮修复全部生效（22-fix-round2.md），
顺手修掉点名的三条隐藏项：

- **H1**：`test_selftest` 沙箱化——旧版直接对真实 HOME 跑 `selftest`，
  全新 clone 未 apply 时 99/100，且测试本身会在测试机上创建
  `~/.citlens` 目录。现在用例内自建 tmp HOME + 配置，任何机器都是
  101/101，TESTING.md "不碰真实配置" 的声明恢复为真。
- **H2**：`--run-dir` 相对路径语义统一——export/screen/gaps/dedup/fetch
  此前只有 verify 侧按调用者 cwd 解析，export 仍按数据家（同一发布两种
  语义）。现在全部经 `_caller_path` 解析后再转发 driver。
- **H3**：`_find_run_dir` 只扫 `citlens-runs/`——非 search 任务此前仍找
  1.x 的 `home/runs/`，2.0 布局下 run_dir 永远 None；1.x 升级机上还可能
  把旧目录错记进 job state。legacy `runs/` 不再扫描。

Tests: test_retest_fixes +7（run_dir 五路解析、legacy 不扫、citlens-runs
可寻）；test_portable selftest 三项沙箱断言。全量 17 套 530 项绿；
verify_harness 34/34。

## Unreleased — 2.0 retest fixes: config propagation, harness reproducibility

第三方对 `main @ 3b59964` 的满血复测（`test-report/21-harness2-full-test.md`）
暴露的 P1/P2 修复，重点是两条 P1：

### P1-1 推送缺口
- 2.0 的两个 commit（2716084 / 3b59964）此前只在本地——第三方 clone 拿到的
  还是 1.x MCP 版。本次随修复一并推送。

### P1-2 显式 --config / 自定义数据家不传播到 driver
- `_run_driver_json` 现在注入 `CITLENS_HOME`：此前同步工具
  （export/audit/screen/gaps/expand/notes/dedup/verify/fetch）的 driver
  各自重读默认 `~/.citlens/config.json`，自定义数据家下 export 报
  "pool 不存在"、audit 静默 0 结果。
- `run-job` 重新拿到全局剥离的 `--config`：此前 runner 加载默认配置，
  在多检出机器上会用默认配置指向的**另一套解释器/driver** 跑任务。

### P2
- `run_job` 失败路径 `run_dir` 未初始化 → UnboundLocalError 掩盖真实失败
  （job 卡 running）。
- `verify --review` / `export --out` 相对路径现在按**调用者 cwd** 解析
  （driver 的 cwd 是数据家，SKILL 示例 `--review review.md` 会撞
  "review not found"）。
- `tool_fetch` 的前端 note 按实际结果分流：fulltext / 仅摘要 / **无摘要
  不可引用**——旧的 blanket "abstract-only" 前缀盖掉了驱动层的诚实说明。
- `tools` 目录里 screen/gaps/expand 的 background 描述改为 CLI 真实契约
  （同步执行、`--background true` exit 2）；fetch 的 background 标明
  DEFAULT FALSE；search 的 wait_seconds "default 45" 笔误改正。

### verify_harness 可复现性（复测 P2-5）
- `OUT.mkdir` 提到所有分支之前——"已 apply 但空家"环境此前在
  `legacy_screening.jsonl` 处直接 FileNotFoundError 崩溃。
- `_usable_config` 现在要求家里有真实数据（池/run/job 任一）：空家 =
  走合成 fixture 分支，与干净 clone 同为 29/0/2（复测场景 B 此前
  6 FAIL + 崩溃）。
- H1-H3 改读 `citlens-runs/`（2.0 布局；旧 `runs/` 路径只能被重命名前的
  历史产物满足）；H1/H3 从硬编码数字（"48 篇"、kept≥3）改为机制断言
  （2plus>0、双分母在场、found_by 全打标）——A/B 实测同代码同查询两天
  分别 48/6 篇，共识数是源端漂移，不该当回归门槛。
- CHANGELOG 数字改为可复现口径：干净/装机空家 29/0/2，真机带新 fixture
  34/34（fixture 由一次真实检索生成，缺失时诚实 skip）。

### 元数据
- pyproject 0.3.0 → 2.0.0，description/keywords 去除 MCP 叙事，
  `citens.__version__` 兜底同步。（wheel 不含 drivers/skill 属已知缺口，
  clone+editable 安装是文档路径，后续单独处理。）

## Unreleased — 2.0: the MCP server is removed; the CLI is the interface

全面拥抱 harness：`citlens_mcp.py` 更名 **`citlens_cli.py`** 并删除整个 MCP
协议层（JSON-RPC stdio server、协议协商、isError 包装）。CLI 一直是主接口，
协议层只是它的转发——第三方实测里 7 个 P1 有 5 个断在"参数翻译"适配层，
正是双路径的维护税。

- **入口**：`citlens.cmd <tool> ...`（裸工具名直接分发；`cli <tool>` 旧形式
  兼容）。`tools` 打印目录 + 检索纪律（原 MCP initialize instructions，
  改名 `DISCIPLINE`）。退出码即契约：0 跑通 / 1 工具报失败 / 2 用法错误。
  `serve` 命令保留一个应答：告知已移除、去跑 `install.py apply` 清理。
- **任务语义不变**：search 与 `fetch --background true` 仍是脱离任务
  （job_id + status 轮询）；screen/gaps/expand 在 CLI 下同步执行。
- **install.py 大裁剪**（1195 → ~910 行）：删除全部 MCP 注册机制
  （json-map/json-opencode/toml-block 写入、DSH bundle、`snippet` 方言）。
  apply 现在写 shim + 共享配置 + skill，并**自动清理 1.x 留下的 MCP 注册**
  （旧条目指向已删除的 server 文件，留着只会是死条目）。`agents.json`
  登记表保留，服务于 skill 目录分发与旧注册清理。
- **测试迁移**：test_portable 的 MCP 协议段重写为 CLI 分发段（100 项全绿，
  新增"清理而非写入"断言）；test_disciplines 检查 `DISCIPLINE`；
  test_report_fixes/test_pid/verify_harness/verify_online 引用更名。
- **文档**：README/INSTALL/SKILL.md 全部改为单接口叙事；shim 不再前置
  `cli`；pyproject 入口点 `citlens-agent = citlens_cli:console_main`。

## Unreleased — third-party test report: 7 P1 / 12 P2 fixed

第三方对 `main @ 473864b` 的完整试运行（`citlens/test-report/`）暴露的
问题逐项修复。核心结论不变：**缺陷几乎全部在"参数接线 / 真实数据契约 /
文档声明"三层，不是算法回归**——所以修复集中在"声明了但没接上"和
"失败被伪装成正常"两类。

### P1-1 policy_queries 断链 + policy 家族默认关闭

- `tool_search` 组装的 payload 现在携带 `policy_queries`；此前 schema/
  instructions/README 都声明该参数，payload 里却没有这个键，驱动永远
  收不到。CLI 的 `_parse_cli_args` 也把 `policy_queries` 加入列表键
  （否则 `--policy-queries a b` 只传第一个词）。
- `install.py` 写出的默认 families 补上 `policy`（此前 7 个，文档称 8 个）。
- **新增学科门控**：未显式提供 `policy_queries` 时，policy 家族只在主题
  被 `detect_discipline` 识别为 economics 时运行，避免向 CRISPR/DPO 等
  主题注入 NBER/Fed/IMF 噪声（第三方实测 CRISPR 主题 29 条 NBER 记录）。
  显式传 `policy_queries` 始终优先。

### P1-2 arXiv PDF 转文本丢空格 → PyMuPDF 主转换器

- **根因**：markitdown 的 pdfminer 路径在大量 arXiv PDF 上丢掉词间空格
  （`Whilelarge-scaleunsupervised…`），逐字 span 回查因此大面积失败
  （第三方实测 37 条 span 中 14 条 mismatch，全部集中在 arXiv 全文），
  `gaps --mine` 也因句子无法分词而 0 命中。
- `_convert_pdf_file` 改为 **PyMuPDF 优先、markitdown 兜底**；PyMuPDF
  加入核心依赖（本地轮子，无需网络）。
- **缓存版本化**：本地转换缓存键与正向 fulltext 缓存键都带
  `_CONVERTER_VERSION`——旧转换器产出的坏文本不会因 TTL=0 永久复用。
- **质量门 + verify 回退**：`text_quality_ok`（长 token 占比与平均 token
  长度）拒绝把丢空格的转换结果当全文：`_convert_pdf_file` 直接判为不可用，
  `verify.ground_text` 对旧 `.txt` 回退到摘要层而不是制造 14/37 条假
  span mismatch。
- 实测：同一篇 arXiv PDF，旧路径 head 为
  `Thisarticleinvestigatessignalestimation…`，新路径为
  `This article investigates signal estimation in wireless…`（87k 字）。

### P1-3 dedup 漏报完全同名重复

- 题名信号此前强制要求"模糊题名相同 + 共作者"，而 oa_title 家族记录
  常带 `authors=[]`，完全同名的对也进不了候选（第三方池中 3 组同名
  重复，`dedup` 报 0 组）。
- 新增纯题名信号：**≥4 个有效词的归一化题名完全一致即可成组**（不要求
  作者）；短/泛题名仍需共作者，保守规则不变。`duplicate_groups` 与
  `dedup_pool` 共用同一个 `_match_reasons`。

### P1-4 audit 永远 reviews_checked=0

- `OpenAlexSearcher.to_paper` 现在读取 OpenAlex `type` 字段
  （`type == "review"` → `is_review=True`），所有 OpenAlex 家族
  （oa_title、相关性、snowball、expand）都受益。
- `looks_like_review()` 增加题名回退：题名含 survey / review /
  overview / meta-analysis / tutorial / 综述 / 述评 / 研究进展 也算锚点
  （仅题名，不扫摘要，避免 "we review the literature" 误报）。
- `audit` 新增 `--queries`：按概念块相关性优先选锚点，缺省才按引用数
  （实测 RL/广告池按引用数会选中公司治理综述；给查询后回到 RL 综述）。
  输出增加 `reviews_available` 与每条锚点的 `anchor: is_review|title`。
- 实测旧池："强化学习与广告算法" 池 180 条，此前 `is_review=0`，
  现在识别出 19 篇综述候选。

### P1-5 verify 的 --run-dir/--text-dir 经 CLI/MCP 传不到

- `tool_verify` 此前拼 `--run_dir`/`--text_dir`（下划线），argparse 只认
  连字符 → 驱动 exit 2，MCP 显示 "driver produced no JSON"。已改为
  `--run-dir`/`--text-dir`。
- 实测：带 `--run-dir --text-dir` 的 CLI verify 正常返回
  `clean=true, refs_in_pool=1, span_ok=1`。

### P1-6 verify 缺 verdicts 时 fail-open

- 旧闸门只在"提供了 verdicts"时检查完整性，于是 37 条 claim、0 条
  verdict 的综述返回 `clean=true`，同时 honesty 里
  `claims_without_verdict=37`、`citation_precision=0.0`——诚实闸门放行了
  它本该拦住的产物。
- `clean` 现在 fail-closed：`claims_without_verdict > 0` 或存在未匹配
  verdict 一律 false。实测无 verdicts 时 `clean=false`，
  problems 列出 `1 claim(s) have no verdict`。

### P1-7 fetch 的 scansci 末棒抛 UnboundLocalError 丢弃已下载全文

- **根因**：`f"{leg} ✓ …"` 里的 `leg` 只在 OA 候选循环中赋值；裸 DOI
  无 OA 候选时循环不执行，scansci 成功路径引用未绑定变量 → 异常被
  `cmd_fetch` 吞掉，最终 `fulltext=false` + "仅摘要级"。
- 现在记录**实际交付的通道**（`source_leg`），初始化清晰；scansci 成功
  时标签为 `scansci(<渠道>)`，不再把末棒记成前置 OA 通道。
- scansci **缓存短路**：CLI 命中自身缓存时不复制文件到 `--output`
  （旧逻辑读作 `no-file`）；现在先查 `~/.scansci-pdf/cache/*.json`，
  标识符匹配且文件存在就直接转换。
- `fetch` 结果新增 `fulltext_source` 与逐腿 `outcomes`（哪条腿、为什么
  失败），`cmd_fetch` 不再在异常后仍报 `ok:true`。
- 新增 `--force`：绕过正向 fulltext 缓存与 1 天失败负缓存（且缓存键带
  转换器版本），网络恢复后无需手工清缓存。

### P2（12 条）

- **诊断/配置**：显式指定但缺失/坏 JSON 的 config 现在让 `doctor.ok=false`
  并给出原因（此前静默回退默认值）；`install.py plan/apply` 在无已检测
  客户端时仍写共享 config + shim + skill（不再 exit 1）；`selftest
  --config X` 打印实际使用的 config 路径。
- **screen**：CLI 别名 `--core/--off` 不再被静默忽略；语义通道缺失时
  报告 `notes` 明确说明"仅 lexical+consensus，core 可能含共享词汇的
  离题项、也会漏掉转述"。
- **gaps**：`matched_to_pool` 现在只数真正在池的记录（旧实现恒等于
  hits 数）；0 命中且文本出现"整段无空格"特征时给出诊断（"用
  `fetch --force` 重取，转换器已换 PyMuPDF"）；novelty 的 lexical 通道
  从"除以池内最大值"改为**陈述词覆盖率**——旧实现只要有任意一个共享词，
  最近邻就恒为 1.0、永远判"高重叠"。
- **pool**：纯空白 topic 不再 slug 成 "" 后匹配任意 run 池（明确报错）。
- **OpenAlex null 题名**：一条 `"title": null` 的记录会让整个源抛
  `ValidationError`、所有关键词一起判 failed（本轮修复时实测复现）。
  `to_paper` 归一为 ""，调用方过滤空题名，源不再被单条坏记录击穿。
- **CLI 逗号列表**：`--families agent,raw,oa_title` 不再被当成一个值
  （enum 型列表同时接受空格分隔与逗号分隔；queries 保持原样）。
- **status**：失败作业的 `run_dir` 不再按 mtime 误指向前一轮成功 run
  （失败即清空；只有 done/lost 才回退扫描）。
- **报告口径**：家族共识同时给出全召回分母（`records_seen`）与入池/
  保留口径（`pool_2plus`/`kept_2plus`），数字可从 `found_by` 复算。
- **fetch 摘要措辞 / 元数据**：无全文且无摘要时不再承诺"仅摘要级"（明确
  "不可作为证据引用"）。`fetch --arxiv` / `fetch --doi` 现在先做一次元数据
  回填（arXiv Atom / Crossref work），标题不再是裸标识符、摘要不再为空
  （第三方实测：`fetch --arxiv 2401.12345` 此前 title=id、abstract=null）。
- **policy 噪声**：见 P1-1 学科门控。
- **S2 预期管理**：README 写明无 key 的缩水范围与"有 key 仍可能有 429
  burst（重试后成功，不等于无 429）"。
- **scansci 重试语义**：缓存命中先查、`--force` 绕过负缓存。
- **AI 生成伪论文 / 附件污染**：`Paper.quality_flag`；recall 结束时机械标记
  自述为 "autonomous synthesis / AI-generated / tribunal consensus" 的记录，
  并在报告 notes 提醒不可当同行评议文献。Crossref 检索现在过滤
  supplementary/attachment 记录（标题 Appendix/Supplemental、DOI 以
  `/mm1`、`/supp-2` 结尾、type=component/dataset 等）——这些曾被当成普通
  论文入池并产出垃圾参考文献。
- **导出污染**：snowball 的 `source` 不再携带 seed DOI；`_bib_venue`
  拒绝把 provenance 串（含内嵌 DOI）渲染成期刊名。

### P3 快修

- INSTALL 工具数 "九个" → 十三个（含完整名单）；`export --format
  bibtex` 接受（此前只认 `bib`）；`wait_seconds` 文档与配置默认（20）一致
  （install.py 也改为 20）；`fetch --title` 接受近似逐字题名（唯一候选且
  token Jaccard ≥0.9，避免标点/大小写导致的失败）；
  snippet 按客户端方言生成（Zed `context_servers`、Goose/Continue YAML、
  Crush `mcp`、Amp `amp.mcpServers`、Copilot `servers`；此前 8 个客户端
  都打印同一份 `mcpServers` JSON）。

### 验证

- 新增 `tests/test_report_fixes.py`（26 项）覆盖以上每条根因：题名去重、
  review 锚点推导、verify fail-closed / 参数接线、policy_queries 转发、
  screen 别名、scansci 零 OA 候选成功、PyMuPDF 空格保留、provenance
  venue、AI 生成标记、config 严格性、空白 topic、mine 计数。
- 全量离线套件：16 个测试文件全绿（`test_portable` 114、`test_health`
  53、`test_net` 51、`test_policy` 40……）；`tools/verify_harness.py`
  34/34 绿。
- 实测：arXiv PDF 87k 字含空格；Jensen 1976 付费 DOI 取回 175k 字；
  verify `--run-dir/--text-dir` 返回 clean=true；无 verdicts 时
  clean=false；stub 驱动的 search 载荷/argv 均含 `--policy-queries`。

## Unreleased — verification closure: the three uncovered gaps, all closed

验收报告里诚实列出的三个未覆盖项，逐项解决：

### POSIX pid 分支（代码审查 + mock 单测，发现一个真 bug）

- **bug**：`_pid_alive` 的 POSIX 分支用 blanket `except Exception` 兜底，
  把 `PermissionError` 也读成"进程已死"——POSIX 上 `kill(pid, 0)` 抛
  PermissionError 恰恰意味着**进程存在**（属于其它 uid）。多用户场景下
  活 runner 会被回收成 lost。修正为标准三段式：ProcessLookupError→死、
  PermissionError→活、其余 OSError→死。
- **tests/test_pid.py（8 项）**：Windows 分支真跑（自身 pid 活/不可能
  pid 死）；POSIX 分支 mock `os.name`+`os.kill`（探测信号必须为 0、
  三种异常语义、falsy pid）。

### 真实并发竞争（tools/verify_online.py 第 I 组）

3 个**真**搜索作业同时运行 + 第 4 个被 `max_concurrent_jobs` 拒绝
（返回体携带在跑清单）——此前只用假状态文件验过护栏算术。4/4 过。

### 联网端到端（tools/verify_online.py 第 II/III 组）

直连全断、代理部分可用的网络下走 `HTTPS_PROXY`（httpx trust_env）：
OpenAlex 键控/相关性端点 + Crossref 真实可用，S2/arXiv 如实降级。三个
真搜索全部 `done`、各 15 条入池（共 45）+ 报告落盘；真实 expand
（OpenAlex related 方向）解析种子 1、在线并入 5 条、产物文件落盘。
脚本自身一处种子路径错误（读共享 litdb 而非 run 池——直调 start_job
未传 append_pool 时记录只写 run 目录）被诊断修正并在脚本中注明。

### 推送

`5175189` 与本提交经代理路由推送成功（直连 GitHub 仍断，git 全局
http.proxy 配置生效）。

## Unreleased — harness-first: the CLI is the primary interface（接下节）

### 验证（tools/verify_harness.py，34 项全绿）

对 harness 框架做了一次**可执行验收**（不是复述结论）：真实数据家 +
真实 CLI/MCP 入口，34 项检查覆盖 8 组。验收过程中**发现并修复 3 个真
缺陷**：

1. **`citlens.cmd tools` 不可达**：shim 恒前置 `cli`，顶层 `tools` 发现
   命令被当成工具名 → `unknown tool 'tools'`。cli 分支现路由它。
2. **CLI 退出码恒为 0**：`ok:false` 也返回 0，harness 语义下自动化无法
   感知失败。改为"显式 false 或裸 error 才算失败"——第一版规则写错
   （`status` 视图无 `ok` 键 → state=done 却 exit 1），被验收套件自己
   的 A9 抓到后收紧；`tool_status` 同时补显式 `ok`（unknown → false）。
3. **文档虚报工具数**：SKILL/README 写 "18 tools"，实际 `TOOL_DEFS` 为
   **13**。已改正。

验收覆盖：A 调用面（tools/doctor/pool/notes/dedup/export/status + 失败
退出码）；B 同步语义（三个长工具拒绝 --background、同步 screen 0.7s 出
带、screening 真 JSONL、legacy 布局兼容读）；C MCP 路由（screen/gaps/
expand 默认脱离任务、background:false 同步）；D 作业（死 runner 回收
落盘、握手宽限、pid 复用静默 45 分钟判死、并发护栏拒绝）；E 共享数据
家（CLI 与 MCP 同池同笔记）；F stdout 压缩视图；G 断网 embedding 缓存
加载；H 产物证据（48 条双家族共识、pivot 点火、run 池多家族 found_by）。

一个**数据与代码的区分**被明确记录：共享 litdb 池里的旧记录仍是修复前
的单家族 found_by（历史数据），修复的效果体现在修复后运行产出的 run 池
（6/20 多家族佐证）——不是代码回归。

## Unreleased — harness-first: the CLI is the primary interface

A股动量机制实跑暴露的工具面缺陷全部收拢后，调用面正式定为主辅两层。

### 架构定位（用户决策：全量 harness 化）

- **Harness CLI 为主**（`citlens.cmd <tool>`，有 shell 的 agent 首选）：
  同步执行——实测从短命 shell 派生的脱离任务会随 shell 进程树一起被
  清理（screen 任务在 embedding 中途随 shell 返回而死），所以 harness
  永不 detach，长操作由 agent 用自己 shell 的后台机制包裹。CLI 显式
  拒绝 `--background` 并给出可操作报错。
- **MCP 为无 shell 客户端的适配层**：长工具（screen/gaps/expand）
  **默认以脱离任务运行**、立即返回 job_id、轮询 `status` 取结果——
  长命 server 才能保住脱离进程；30s 客户端强杀问题按构造消失。
- SKILL.md 改版（499 行，三处同步）：新增 "Two surfaces, one engine"
  节，CLI 升为首选、MCP 降为适配层，写明两侧的时序语义。

### 修复

- **死任务回收统一**：原先三处各自为政（`_running_jobs` 落盘、
  `job_state` 只改内存返回值、`tool_status` 直读不回收）——实测状态
  在 running/lost 间翻转（Windows pid 复用让存活性检查双向说谎）。合并
  为单一 `reap_dead_jobs`：pid 死亡或**静默超 45 分钟**（无 state/log
  触碰）均判 lost 并落盘原因；`job_state` 读取前先回收，所有调用方
  共享一个真相。实测：挂 10 分钟的僵尸 job 被 status 轮询即时回收。
- **embedding 模型加载离线化**：sentence-transformers 在模型已完整缓存时
  仍先打电话给 huggingface.co 解析快照——网络断时**挂死**（实测零 CPU 卡
  10+ 分钟；etag 超时只封顶单个请求，封不住十几连发）。`_load_model` 现在
  检测本地 HF 缓存（refs/main + 非空 snapshots）齐全即设
  `HF_HUB_OFFLINE=1`，零网络秒级加载；未缓存时保持联网（首次下载照常）。
  实测断网：embed_local 7.1s 完成（修复前挂死），整场 CLI 分带 165 篇
  正常出带。

## Unreleased — recall endgame & repo reorg: bench sealed, S2 hardened, skills unified

接上节。剩余 7 个漏召金标的终局处理 + 仓库整体收拢。

### 新增

- **探针家族的 Crossref 第二备胎**：S2 过载时的失败形态比 429 更阴——
  实测（2026-11-06）配额风暴中 36/72 个 S2 槽返回 **200+空数据**，健康表
  上与"真没命中"无法区分。覆盖链升级为 OpenAlex 标题索引 → S2 →
  Crossref（无 key、无配额游戏、礼貌池）。调研结论随提交：S2 没有商业
  中转市场（免费 API 无人中转）；PaperQA2/Undermind 的三件套（实体级
  缓存 / 引文图用法 / 接受延迟）本仓库已具备其二。
- **全 15 题端到端复测（`tools/retest_full_bench.py`）**：首次全套开关
  一起开、按出厂深度（裸题@20 + 阶梯@40）跑整场。晴天口径：**q3/q8/q12
  复活**，其中 q12 用真 driver 封箱——阶梯查询作 agent 查询 + pivot 2，
  160s，金标 SafeDreamer 终池 **#3/173**（此前"被 family_quota 截掉"的
  诊断在 agent 腿 @40 深度下不成立）。金标命中@20：基线 5/15 → 9/15
  稳定，另 2 题在门槛波动。S2 风暴中的下限口径与全 @20 过严变体分别
  归档（`tools/results/full_bench_retest{,_s2down,_d20}.json`）。
- **查询纪律三则入 skill**（仓库版与装机版统一，464 行三处一致）：
  ① **复述自检**（防误读，"languages ≠ quantization"）；② **寄存器阶梯
  爬满**——问句词→行话→方法名→任务名→**社区名**，顶档是 agent 最常
  跳过的（实测：NLP 措辞的问题金标是 CHI 论文 "inspiration for science
  writing"，NLP 寄存器全盲）；③ **侦察先行**——拆块→两块宽查询小搜
  →读标题四桶收词（任务名/方法名/数据集名/社区信号）→带学到的词正式
  搜。实测：宽查询把 q2 金标直接排 #1（7 块长 AND 全源漏），换社区语言
  二次侦察把 q13 的框架兄弟排 #1（金标是其前作，引文一跳）。
- **scansci-pdf 三档实测通过**（代理 + patchright chromium 后）：出版商
  直连档（Nature 2024 新文章 8.6MB→83k 字全文）、Unpaywall 绿色 OA 档、
  Sci-Hub 浏览器档（1976 年零 OA 硬墙论文）。裸 HTTP 镜像全被
  Cloudflare/ALTCHA 挡——该档必须装浏览器 extras，未装时自动缺席不伤
  其它档。

### 修复

- **scansci CLI 解析在生产 PATH 下找不到**：`shutil.which` 单独兜底在
  MCP 任务（cwd=数据家）里必返 cli-absent，通道静默缺失——回退到
  `sys.executable` 同级（同 venv），同一调用从 cli-absent 变 83k 字全文。

### 仓库收拢

- `tools/` 代码与产物分离：六个 JSON 证据产物移入 `tools/results/`，
  五个 harness 的路径同步更新；新增 `tools/README.md`（逐脚本回答的
  问题 + 结论 + 产物对照）。
- `README.md` 重写为当前架构：框架总览图（八家族 × 5 源 → RRF → 分带/
  决策层/信号层 → 全文链含 scansci 末棒 → verify）、实测效果表（金标
  命中 5/15→9/15、决策层 86%/0 硬错、scansci 三档）、Roadmap 去除已完成
  项。
- skill 分叉消除：仓库版（八家族/policy/gaps，411 行）缺本轮查询纪律，
  装机版（299 行）缺新工具——合并为 464 行，三处同步。

## Unreleased — reliability: one retrying transport, honest failures

起因：检索"看起来不稳定"。审计发现它不是容易失败，而是**失败之后伪装成
空结果**——429/超时被吞成 `[]`，健康表把失败计成 empty；而所谓的整源重试
是死代码（没有任何源会把异常抛到那一层）。

### 新增

- **`openalex_relevance` 第五检索源（机制多元）**：同一 OpenAlex 语料走
  `search=` 相关性排序（vs 原源的 `default.search` 词面 AND）。实测
  （2026-11-05，7 个漏召金标）：同一批阶梯变体，default.search 漏掉的题里
  它把 q7/q8/q10 排到 top-5、q12 排到 12；进入生产融合波后 **q7/q8/q10
  三题复活**（rank 5-20，穿过席位与 target 截断）。q12 词汇层已通（记录
  进入候选流）但卡在家族席位（RRF>30）——病因从 A 类（词汇）降级为 B 类
  （排名），可由配额/排序调整收尾。代价 10 credits/查询（default.search
  的 10 倍），预算护栏不变。
- **标题探针的 S2 覆盖备胎**：OpenAlex 标题索引空 cell 时回落 S2 标题
  搜索（救 OpenAlex 未收录的记录——实测 'How to Catch an AI Liar' 在
  OpenAlex by-DOI 为空）。S2 全天配额打穿，代码就绪待复测。
- **scansci-pdf 全文兜底通道**：OA 链末端新增可选 CLI 通道（出版商 API/
  机构通道/中文库/绿色 OA/Sci-Hub 兜底——用户授权启用，`oa_first` 策略，
  `SCANSCI_ENABLED`/`SCANSCI_STRATEGY` 可调）。今日实测：通道与诚实降级
  全链路工作（记录 `scansci:` 原因码），Sci-Hub 下载被本机网络阻断
  （DNS 断 + 代理未开）——梯子开启后设其 `network_proxy` 即通。

- **Agent 长程失败诊断模板（`docs/agent-loop-failure-template.md`）**：把
  当天的漏召事件（10 金标 → 四类病因 → 五修复 → 六臂消融）提炼成可复用
  模板——核心问题模型（开环表征三重缺陷 + 因果距离）、五步诊断流程
  （oracle 上界 → 表征接地 → 通道隔离 → 病因分类 → 修复匹配）、4+2 类
  病因表（每类带判别试验与实测）、闭环四律。文献锚点（MAST/DeFA/
  LongRCA/Reflexion/Self-RAG/QPP）来自新建的 60 篇主题池。
- **MCP 客户端 30s 超时的三层修复**（当天两次实测超时，其一连后台任务
  一起被杀成 lost）：`wait_seconds` 默认 45→20（在客户端击杀前返回
  job_id，轮询成为唯一契约）；`fetch` 增加 `background: true`（全文下载
  走 jobs 框架，立即返回 job_id）；`status` 对 tools 类任务返回完整
  log_tail（结果 JSON 即在日志尾部）。

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
