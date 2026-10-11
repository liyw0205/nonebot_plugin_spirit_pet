# 发布资产与回退约定

- 稳定发布 tag 固定为 `vMAJOR.MINOR.PATCH`，正式 Release 资产固定为 `project.tar.gz`。
- 默认安装从
  `https://github.com/liyw0205/nonebot_plugin_spirit_pet/releases/latest/download/project.tar.gz`
  获取资产；先尝试已核验的 `gh-proxy.com`，失败或归档无效后直连 GitHub 官方地址。
- 本次核验时本仓库尚无正式 Release asset。资产缺失或直连失败时安装停止，不回退到
  `main` 分支；安装本地开发版需显式使用 `--source checkout`。
- 代理候选必须通过真实 GitHub Release 资产下载，并与官方公布的 SHA-256 一致后才能保留。
- `gh-proxy.com` 已通过 xiu2 `v1.0.0` 的 `project.tar.gz` 验证，下载 SHA-256
  `3592480f7618a289b29fa57b13ac6b2b198cedaf16952a05114b5d57e2c2c5e5` 与 GitHub Release API
  摘要一致；pet 自身资产发布后仍需核验其实际响应。
- Release workflow 从 tag 内容生成并上传 `project.tar.gz`；安装器保留已存在的项目源码、
  `.env`、SQLite 存档和运行数据。
- `xiupet update` 只更新来源标记为 Release 的受管理安装：停止实例后下载并校验资产，替换
  `src/`、`scripts/`、`pyproject.toml` 和 `requirements.txt`，在现有 `.venv` 中安装依赖，不自动启动。
- `.env`、`data/`、`.xiupet/`、`.venv` 目录、用户日志、来源标记和命令链接不被替换；源码替换或依赖安装失败会尝试恢复旧源码。
- checkout、来源不明或缺少来源标记的目录会拒绝更新。旧安装目录需要先人工核实来源，不会推测为 Release 管理。
