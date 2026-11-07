# Recorded pipeline-evidence fixture (H4)

`verify_harness.py` 的 H 组（H1–H3）验证的是**投票机制的可见性**——票池报告里
"≥2 家族" 数字与双分母、pivot 波次、pool 里逐条 `found_by` 家族戳——不是某个历史
数字的复现（佐证数随上游源漂移，同一代码同一查询一天 48 篇、一天 6 篇，A/B 已证）。

此前该组只能对作者真机上一场 live run 的产物跑，第三方 clone 恒 2 skips。本目录把
那场 run 的三个证据文件**原样录制**入库，harness 在数据家里找不到 live
`verify-votes2/` 时回退到这里——第三方也能跑 H1–H3。

- 来源：live `--topic "A股动量机制"` run（`--pivot 2`，六查询 + 三标题探测，
  agent,raw,oa_title,s2_rec,snowball,web,survey 七路家族），2026-11-07 20:57，
  commit 024b4c0 时代的驱动产出；`exclusions.jsonl`（180KB）未收录，H 组不读它。
- 数字是**冻结的录制值**：`入池 172 条中 ≥2 家族 4 篇`、pool 60 条逐条带
  `found_by`。它们与今天重跑同主题得到的数字不同属预期（源漂移），不构成回归。
- 想看 live 证据：在真机数据家重新生成
  `drivers/citlens_recall.py --topic "A股动量机制" --target 60 --pivot 2 ... --out
  <home>/citlens-runs/verify-votes2/`，harness 会优先用 live 产物。
