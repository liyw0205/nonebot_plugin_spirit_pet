# 发布资产与更新约定

- 稳定发布 tag 固定为 `vMAJOR.MINOR.PATCH`，正式 Release 资产固定为 `project.tar.gz`。
- Release 安装从
  `https://github.com/liyw0205/nonebot_plugin_spirit_pet/releases/latest/download/project.tar.gz`
  获取资产；先尝试 `gh-proxy.com`，失败或归档无效后直连 GitHub 官方地址。
- 归档必须包含项目文件；代理和官方地址均无法下载或校验归档时，安装器停止，不回退到分支归档。
- 代理候选必须下载成功并通过归档内容校验后才能使用。
- Release workflow 从 tag 内容生成并上传 `project.tar.gz`；安装器保留已存在的项目源码、
  `.env`、SQLite 存档和运行数据。
- `xiupet update` 只更新来源标记为 Release 的受管理安装：停止实例后下载并校验资产，替换
  `src/`、`scripts/`、`pyproject.toml` 和 `requirements.txt`，在现有 `.venv` 中安装依赖，不自动启动。
- `.env`、`data/`、`.xiupet/`、`.venv` 目录、用户日志、来源标记和命令链接不被替换；源码替换或依赖安装失败会尝试恢复旧源码。
- checkout、来源不明或缺少来源标记的目录会拒绝更新。旧安装目录需要先人工核实来源，不会推测为 Release 管理。
