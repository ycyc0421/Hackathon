# 官方规则来源动态监测机制

系统通过独立的后台定时服务定期巡检目的国规则所引用的官方法规与指南来源，自动保存不可变原文快照、计算 SHA-256 指纹并生成待复核变更记录。

---

## 1. 监测范围

首批纳入监测的 5 个官方法规来源（定义于 `backend/app/rules/source_catalog.json`）：

1. **欧盟委员会（European Commission）**：食品接触材料（Food Contact Materials）法规概览页
2. **EUR-Lex（通过官方 CELLAR REST 接口）**：陶瓷制品指令 `84/500/EEC`（2005-05-20 合并正文 PDF）
3. **欧盟委员会**：食品接触材料规则修订进展页面
4. **美国食品药品监督管理局（FDA）**：进口陶瓷制品铅污染合规政策指引（CPG）
5. **英国政府网（GOV.UK）**：食品接触材料与包装合规指南

---

## 2. 抓取与更新策略

- **礼貌条件请求**：携带本地保存的 `ETag` 与 `Last-Modified` 发起 HTTPS 请求；站点返回 `304 Not Modified` 时直接校验本地快照哈希并复用。
- **内容变更留痕**：当响应正文 SHA-256 发生变化时，同时保留旧版与新版快照文件，并在 `pending_review.json` 中生成一条 `PENDING_REVIEW`（来源有变更待复核）记录；相同哈希变化不会重复生成记录。
- **故障安全降级**：遇到站点临时不可达或验证拦截时，记录失败原因与连续失败次数，保留最近一次成功快照，等待下一周期重试。
- **人工复核隔离**：**来源监测仅更新快照与待复核队列，绝不自动改写或激活线上运行规则**。官方法规是否正式生效、适用商品范围及具体申报要求，均需人工逐条核实。

---

## 3. 运行目录与服务管理

生产环境中，监测服务由独立的 `systemd --user` 定时器（`hackathon-rule-monitor.timer`）每小时触发一次：

| 路径 | 用途 |
|---|---|
| `backend/tools/crawl_rule_sources.py` | 官方来源抓取与快照校验脚本 |
| `~/app/shared/rule-sources/manifest.json` | 各来源最新抓取状态、时间戳与 SHA-256 清单 |
| `~/app/shared/rule-sources/pending_review.json` | 检测到内容变化的待人工复核列表 |
| `~/app/shared/rule-sources/history.jsonl` | 历次巡检审计日志 |
| `~/app/shared/rule-sources/snapshots/` | 历次抓取的不可变原始响应快照 |

常用运维与测试命令：

```sh
# 本地运行一次抓取（默认输出至 backend/.out/rule-sources/）
python backend/tools/crawl_rule_sources.py

# 运行规则监测单元测试
python -m pytest backend/tests/test_rule_monitor.py

# 生产服务器查看定时器与服务日志
systemctl --user list-timers hackathon-rule-monitor.timer --no-pager
journalctl --user -u hackathon-rule-monitor.service -n 30 --no-pager
```

---

## 4. API 与报告集成

- `GET /api/v1/rules/sources`：返回当前来源目录、各来源监测状态（`UNCHANGED` / `CHANGED` / `PENDING_REVIEW` / `NOT_CHECKED`）、最后检查时间及待复核更新列表。
- **结构化报告追溯**：导出报告（ReportContent v2）的 `provenance` 区块会自动附带本票命中规则所关联的官方来源机构名称、原始链接与当前监测状态。未配置 `RULE_SOURCE_DIR` 时，接口返回 `mode="bundled_static"` 且各来源状态如实标为 `NOT_CHECKED`（来源更新未检查）。
