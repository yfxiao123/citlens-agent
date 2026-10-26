# Testing

三层验证，全部离线（不发检索请求、不碰真实 agent 配置）：

## 1. 核心包 import 检查

```bash
.venv/Scripts/python -c "import citens, citens.search, citens.eval.litsearch, \
citens.collect, citens.grounding, citens.grounding.fulltext, \
citens.grounding.citations, citens.grounding.verify, citens.screening; \
print('ok', citens.__version__)"
```

零残留耦合断言（应无输出）：

```bash
grep -rn "citens\.llm\|citens\.agents\|citens\.orchestration\|citens\.harness" citens/
```

## 2. 测试套（全部零网络、零 LLM）

```bash
.venv/Scripts/python tests/test_portable.py      # MCP 协议 + 安装器 + CLI
.venv/Scripts/python tests/test_screening.py     # screen 通道 + snowball 准入 + found_by 合并
.venv/Scripts/python tests/test_verify.py        # 综述机械核验（蜜罐/span/判定/诚实数字）
```

覆盖：MCP 协议（握手/协商/九工具/错误路径/stdout 纯度/干净退出）、安装器六方言
（sandbox HOME 下的 plan/apply/幂等/uninstall/自定义 agents.d/坏 JSON 防护/--all/
九家族配置迁移）、引擎覆盖与驱动范围化、init 向导、CLI 通道、selftest；screen 的
BM25/分带/CJK/共识重归一；`verify` 的引用解析（DOI/标题）、编造引用与悬空 marker、
span 逐字匹配、六类判定、precision/grounding 算术与产物。

> 注意：`test_selftest` 假设本机已经 `install.py apply` 过（`~/.citlens` 存在）。
> 在全新 HOME 下运行它会报 home 不存在——那是环境问题，不是代码回归。

## 3. 干跑与冒烟

```bash
.venv/Scripts/python install.py plan                      # 不写用户目录
.venv/Scripts/python citlens_mcp.py selftest              # 工具列表 + doctor
.venv/Scripts/python drivers/citlens_recall.py --topic "x" --dry-run
.venv/Scripts/python drivers/citlens_tools.py verify --review <review.md> --topic "x"  # 只做引用解析
```

真网冒烟（花少量配额）：`search` 一个小主题 + `pool` + `audit` + `fetch` 一篇已知
OA 论文，确认七家族健康桶（含 web 的 ok/empty/failed）与 PRISMA 排除日志落盘，再用
`verify` 跑一遍综述（无 verdicts 时先验证引用真实性）。

## 4. bench（可选，离线需引擎缓存）

```bash
.venv/Scripts/python bench/bench_screen.py \
  --data <engine>/bench_data/litsearch --gen <engine>/bench_results/gen_cache.json
```

0.3.0 起输出包含 Wilson 95% 区间、配对 McNemar/bootstrap、`manifest_latest.json`；
`--driver-arm` 接入仓库自己的七家族 recall leg（live），`--all-questions` 跑全量
LitSearch 题目（只有 raw 家族——冻结 planner cache 仅覆盖 15 题）。
