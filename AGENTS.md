# 项目执行约定

- `main` 是公开安装入口、正式 Release 与集成分支；`develop` 是唯一活动开发分支。新功能从同步到 `main` 的 `develop` 开始，完成聚焦验证后普通提交推送 `develop`，审查后普通合入 `main`。禁止 force push、reset 和移动既有 tag。旧 `work/*`、`refactor/*`、`docs/*` 分支及 worktree 是历史材料，不删除，也不盲合旧改动。
- 唯一进度入口是 [开发路线](docs/ROADMAP.md) 的“当前唯一进度”区；其中记录已完成范围、实际部署源码 SHA/Release、QQ 连接和 QQ 客户端呈现状态、下一有限任务。开发指南只写执行规则，不维护第二份活动任务清单。
- 最新正式 Release 是 `v0.1.0`，tag 指向 `471b3dbf7879a0779bf304cd434e7e94093be975`，资产为 `project.tar.gz`。Release 已存在，不得写成尚未发布或 `blocked`。QQ 机器人连接/鉴权与 QQ 客户端 Markdown、按钮、蓝字呈现是不同验收项；Termux 设备实测另行记录。
- README 与用户安装文档始终面向 `main` 和正式 Release。普通部署用 Release 安装/更新；旧托管目录只有在显式下载 Release、替换并验证程序文件后才能转换为 Release 管理，禁止手工伪造 `.xiupet-source`。
- 部署前确认实例身份和实际加载 SHA。停止服务后对 `.env` 与 SQLite 做一致备份并验证；不得输出凭据，不改玩家存档，不清理既有备份。更新只替换程序文件，保留 `.env`、`data/` 与运行配置。
- 安装、重启和测试共用 `/tmp/nonebot-project-validation.lock`，使用 `flock -w 600` 串行；仅在实际安装/重启/测试期间持锁，不长时间占锁。不得修改其他项目或共享 `/root/myenv`。
- 高境界离线委托内容切片已完成：前三境既有三项不变，金丹、元婴、化神、渡劫各新增一项不同用途委托。保守复用既有物品与经济模型；不新增 schema、离线战斗或第二行程。沿用单行程、出发奖励快照、原宠占用和幂等回复。下一步仅审查并普通合入 `main`，发布前不重启已验收实例。
- 离线委托切片只验证新增内容与受影响短合同，复用未变化的 D1-D3 证据；不跑全量、长 WS 链、仿真、压测或发送真实 QQ 消息。QQ 真机呈现不能由 OneBot 或 mock 结果替代。
- 部署 SHA、Release 和当前切片进度以路线图为准。提交、推送、普通合入和发版按当前用户授权执行；`.env`、凭据、数据库、缓存和虚拟环境不暂存。
- 手工编辑用 `apply_patch`。不得删除 `/tmp/codex-daemon-*`、代理 IPC socket/lock 或其他活跃代理目录；历史 worktree 保留。
- `docs/archive/` 是历史快照，只用于回溯，不是当前执行入口。
