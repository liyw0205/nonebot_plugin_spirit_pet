# 开发指南

本页只记录仓库执行规则。玩家安装、配置和玩法请分别阅读[安装与启动](INSTALLATION.md)、[配置与排错](CONFIGURATION.md)和[玩法说明](GAMEPLAY.md)；静态 JSON 的字段与校验见[静态内容规范](CONTENT.md)。

## 唯一执行入口

日常工作从[开发路线](ROADMAP.md)的“当前唯一进度”开始。路线图只维护当前活动阶段、实际验证范围和下一项有限任务；历史交付记录仅用于回溯，不作为新的任务清单。

`develop` 是唯一活动开发分支，`main` 是公开安装入口和正式 Release 分支。新功能从与 `main` 同步的 `develop` 开始，完成聚焦验证后使用普通提交推送 `develop`；需要集成时再普通快进合入 `main`。禁止 force push、reset、移动既有 tag 或删除历史 worktree。

## 修改边界

- 先阅读实际运行入口、内容模型、持久化边界和受影响测试，再修改最小范围。
- 用户存档位于 `SPIRIT_PET_DB` 指定的 SQLite 文件。测试使用临时库，不连接真实存档。
- 保留 `.env`、`data/`、运行配置和既有备份；部署更新只替换程序文件，不改玩家进度。
- `schema.sql`、`data/` 和规则模型必须同步校验。需要迁移时先做一致性备份，失败保持原库并回滚。
- 操作涉及资源、冷却、出战占用或奖励时，检查并发、重复消息、缓存过期和进程重启后的行为。
- 源码注释只解释安全约束、业务不变量和难懂算法，不记录个人进度、提交号或临时调试过程。

## 内容与回复

静态内容使用严格 JSON 和 Pydantic 模型校验。新增条目时同步更新目录校验、帮助、玩法说明和数量断言；不要用默认值掩盖未知 ID、坏奖励或不完整引用。

玩家入口必须从实际命令注册表可达。只读页面不得写存档；需要参数的操作应提供可填写的命令。QQ native 的蓝字与按钮各自保留适合的动作，最多四个按钮，不能重复或遮挡行内蓝字；text、template、OneBot 没有富消息能力时仍提供可读命令。

OneBot 和 QQ 共用同一业务事务。适配器层只负责身份、消息键、解析和呈现；不要在平台分支中复制奖励或战斗逻辑。QQ mock、OneBot 冒烟和单元测试不能代替 QQ 客户端权限与真机呈现记录。

## 验证

运行与变更直接相关的测试。以下为静态内容检查示例，按实际影响替换测试文件：

```bash
flock -w 600 /tmp/nonebot-project-validation.lock timeout 180 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_content.py
PYTHONPYCACHEPREFIX=/tmp/spirit-pet-compile .venv/bin/python -m compileall -q src tests scripts
git diff --check
```

内容或战斗公式变化时，额外运行对应的内容校验和固定种子场景；适配器变化时只补必要的解析、消息结构或 OneBot 运输合同。不要把未运行的全量、仿真、WS、QQ 真机或 Termux 验收写成已通过。

安装、重启和测试共用 `/tmp/nonebot-project-validation.lock`，只在实际操作期间使用 `flock -w 600` 持锁，不修改其他项目或共享虚拟环境。

## 发布与部署

正式 Release 使用 `vMAJOR.MINOR.PATCH` tag 和 `project.tar.gz`。发布前确认实例身份、实际加载 SHA、`.env` 与 SQLite 一致备份；发布资产核验通过后再更新路线图当前进度。未授权时不部署、不重启、不访问真实玩家库、不发送真实 QQ 消息。

README 与用户安装文档始终面向 `main` 和正式 Release。旧托管目录只有在显式下载 Release、替换并验证程序文件后才能转为 Release 管理；禁止手工伪造来源标记。`.env`、凭据、数据库、缓存、虚拟环境和本地辅助 goal 不暂存、不提交、不推送。
