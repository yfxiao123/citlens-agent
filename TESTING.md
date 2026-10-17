# Testing

三层验证，全部离线（不发检索请求、不碰真实 agent 配置）：

## 1. 核心包 import 检查

```bash
.venv/Scripts/python -c "import citens, citens.search, citens.eval.litsearch, \
citens.collect, citens.grounding, citens.grounding.fulltext, citens.grounding.citations; \
print('ok', citens.__version__)"
```

零残留耦合断言（应无输出）：

```bash
grep -rn "citens\.llm\|citens\.agents\|citens\.orchestration\|citens\.harness" citens/
```

## 2. portable 测试套（tests/test_portable.py）

```bash
.venv/Scripts/python tests/test_portable.py      # 或 -m pytest tests/test_portable.py
```

覆盖：MCP 协议（握手/协商/七工具/错误路径/stdout 纯度/干净退出）、安装器四方言
（sandbox HOME 下的 plan/apply/幂等/uninstall/自定义 agents.d/坏 JSON 防护/--all）、
引擎覆盖与驱动范围化、init 向导、CLI 通道、selftest。

## 3. 干跑与冒烟

```bash
.venv/Scripts/python install.py plan                      # 不写用户目录
.venv/Scripts/python citlens_mcp.py selftest
.venv/Scripts/python drivers/citlens_recall.py --topic "x" --dry-run
```

真网冒烟（花少量配额）：`search` 一个小主题 + `pool` + `audit` + `fetch` 一篇已知
OA 论文，确认七家族健康桶与 PRISMA 排除日志落盘。
