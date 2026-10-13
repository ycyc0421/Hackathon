# 官方规则来源动态监测

## 已运行的范围

新服务器 `<deployment-host>` 的独立用户定时服务每小时检查一次（随机延迟最多 5 分钟），无需保持 SSH 会话。它是定期轮询，并非秒级推送，也不是完整全球法规库。

首批 5 个来源：欧盟委员会食品接触材料法规概览、陶瓷指令合并正文、FDA 陶瓷铅污染指引、GOV.UK 食品包装概览、欧盟食品接触材料规则修订进度页面。修订进度中提案不等于已生效法规；固定日期合并正文也不能独自发现未来的新版本，因此同时检查官方法规概览与修订页面。其他国家实施规定和新法规目录发现尚需扩展。

EUR-Lex 网页验证挑战未绕过；采用官方 CELLAR REST 文档接口。成功返回的正文经 PDF 文件头、指令编号及版本年份校验：`84/500/EEC`，2005-05-20 合并版本，8 页。CELLAR 返回的 HTTP 资源标识仅请求其 HTTPS 等价地址。

## 更新机制

- ETag / Last-Modified 条件请求；304 时核验本地快照哈希后复用。
- 新内容 SHA-256 不同：保留旧、新快照，创建 `PENDING_REVIEW` 记录。同一版本变化不重复创建记录。
- 网站故障、拒绝访问或返回错误页面：记录失败和连续失败次数，保留上一次成功版本，下一小时重试。
- 原子写入清单，进程锁避免同时检查；专用 Python 环境和资源上限，与业务服务分离。
- **只有来源库自动更新，执行规则不会自动替换。** 官网页面导航、时间戳等也可能改变哈希，所以变更只是复核线索。当前仍保持未经核实标记；法规是否生效、适用商品/地区/贸易方式及阈值需要逐条复核。

## 文件与状态

- 程序：`~/app/rule-monitor/backend/tools/crawl_rule_sources.py`
- 当前清单：`~/app/shared/rule-sources/manifest.json`
- 待复核记录：`~/app/shared/rule-sources/pending_review.json`
- 历史检查：`~/app/shared/rule-sources/history.jsonl`
- 不可变版本：`~/app/shared/rule-sources/snapshots/`
- 定时单元：`hackathon-rule-monitor.timer`、`hackathon-rule-monitor.service`

```bash
systemctl --user list-timers hackathon-rule-monitor.timer --no-pager
journalctl --user -u hackathon-rule-monitor.service -n 30 --no-pager
systemctl --user start hackathon-rule-monitor.service
```

仓库安装脚本：`bash deploy/install_rule_monitor.sh`，需要 `~/app/venv/bin/python` 已有 pip；不会重启业务后端。首次抓取失败也保留 timer，后续重试。

2026-10-12 实测：5 个来源全部成功；定时触发后的第二轮已执行，其中陶瓷正文、FDA 和 GOV.UK 返回 304。用户 `Linger=yes`，退出 SSH 后定时服务继续运行。监测逻辑测试 10 项通过，候选 API 已读取真实运行清单与待复核记录；业务服务保持 active。

## 后端接入（本分支，尚未部署到业务服务）

`GET /api/v1/rules/sources` 返回来源状态、最后检查时间和待复核变更；报告也携带当前监测状态。部署时将 `RULE_SOURCE_DIR` 设置为监测程序的实际输出目录；开发环境默认输出到 `backend/.out/rule-sources/`。清单、快照、复核记录和检查历史仅保存在运行目录，不提交源码。

未设置 `RULE_SOURCE_DIR` 时，`mode=bundled_static` 仅表示内置来源目录：各来源为 `NOT_CHECKED`，检查时间为空，空待复核列表不代表没有变更。接口不把来源变化或抓取成功当作法规适用核实通过。

## 官方接口说明

- [EUR-Lex 数据重用](https://eur-lex.europa.eu/content/help/data-reuse/webservice.html)：文件下载可使用 CELLAR；检索 Webservice 需要注册。
- [CELLAR 文档下载](https://op.europa.eu/en/web/cellar/cellar-data/publications)。
- [CELLAR RSS/ATOM 更新通知](https://op.europa.eu/en/web/cellar/cellar-data/rss-and-atom-feeds)：以后可扩展新文档发现；本版尚未实现对整个订阅的分页扫描与相关性筛选。
