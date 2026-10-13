# B 独立增量验收材料（脱敏发布版）

实际测试提交：`1c5924338e21caaed0f5ea5c76a33048bbce98dc`；当前PR37脱敏头：`bb40043fe402a77d49dd48c4f2b6e9b3301a5da9`，相关代码blob一致，未在新头重跑。

- [独立报告](INDEPENDENT_REVIEW.md)
- [完整独立证据ZIP](backend-independent-1c592433-incremental.zip)

| 文件 | SHA256 |
|---|---|
| INDEPENDENT_REVIEW.md | `770ad52b69b35503781e0129cb8a5696937648a4155d545c44b9ae024e446d5d` |
| backend-independent-1c592433-incremental.zip | `5f0196c9d6c963ebfa1edc7ab8acc00f5a389adef503daeb39ac11d3e7d1f732` |

ZIP含131份字节未改的旧原件、完整请求／返回／报告、原始新模型输出和日志及复验脚本；170份业务payload逐结构不变。路径和部署标识已脱敏，详见ZIP内PUBLICATION_REDACTION.json；成员哈希已重新生成。原始本地ZIP SHA256为 `d42225fd61acb99ff084e737ac80247b8f449d7462530142804f099cececccc5`，不能与公开版哈希混用。

仅发布B的材料，不包含业务实现、模型、运行数据库、凭据或F的重启脚本。本PR保持draft，不自动关闭#38，不合并或部署。环境／未覆盖范围见报告。
