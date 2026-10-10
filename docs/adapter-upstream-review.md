# 适配器上游审查

审查日期：2026-10-10。只读核对运行时加载路径、当前解析版本与对应官方 tag；未修改代码、依赖或测试，未连接真实平台。

## 结论与版本来源

项目实际加载 `.venv` 中的外部 pip 分发，不是内置 vendor。`pyproject.toml` 将 OneBot V11、QQ 分别注册为 `nonebot.adapters.onebot.v11`、`nonebot.adapters.qq`；插件内 `src/plugins/nonebot_plugin_spirit_pet/adapters/` 是应用接线与消息包装。

| 分发 | 实际导入文件 | 当前解析版本 | 上游仓库与匹配 tag commit | 逐文件核对 |
| --- | --- | --- | --- |
| `nonebot-adapter-onebot` | `.venv/lib/python3.11/site-packages/nonebot/adapters/onebot/v11/__init__.py` | `2.4.6` | [nonebot/adapter-onebot](https://github.com/nonebot/adapter-onebot), `v2.4.6` `7194dbb9d363d152230ecb9a7225125999a0e6af` | 安装的 24 个 Python 文件均与 tag 一致 |
| `nonebot-adapter-qq` | `.venv/lib/python3.11/site-packages/nonebot/adapters/qq/__init__.py` | `1.7.3` | [nonebot/adapter-qq](https://github.com/nonebot/adapter-qq), `v1.7.3` `9bf584471e4fa658f276903481b99373c43016fd` | 安装的 15 个 Python 文件均与 tag 一致 |

版本取自当前 `.venv` 的分发元数据，并与 [交付依赖快照](reports/development-dependencies.txt) 一致。`requirements.txt` 只声明 `onebot>=2.4.6`、`qq>=1.7.1`，没有精确 pin 或上限；因此 QQ `1.7.3` 是已记录的解析结果，高于声明下限，但现有材料不能追溯该环境具体由谁或通过哪次操作升级。`direct_url.json` 缺失，包的 `RECORD` 与 tag 源文件匹配也只能证明已安装文件内容，不能证明 wheel 的构建来源或发布者。

核查 pin/兼容性时，应将启动注册模块、已安装元数据与依赖快照对照，再将实际导入路径和安装文件映射到候选官方 tag；最后按插件真正调用的事件身份、消息字段、发送接口运行短合同测试。下限不是锁定版本，快照也只描述该环境。现有运行证据为 Python 3.11.2，不证明 Python 3.10 或所有允许解析版本均兼容。

## 修复与本地差异

安装文件与上述 tag 逐文件一致。QQ #233 的 Gateway 长连接读取超时修复（`Timeout(connect=30.0, read=None, close=30.0)`），以及已核查的群聊回复命令识别、可空回复字段、回复元素检查、空群聊 at 与非 dict DISPATCH 处理均已包含。OneBot `v2.4.6` 中已核查的回复检查和 Pydantic v2 URL 转换也已包含；从该 tag 到本次查询的 `master` 未见适配器运行逻辑差异。此结论限于所列版本和修复，不是对所有历史提交的穷举。

未发现当前加载实现缺少已核实修复，也没有可复制到本项目的 vendor 补丁。无需复制上游源码：运行时已经从外部包加载包含修复的实现，仓库没有平台适配器副本；本地 `handlers.py`、`messaging.py` 是有独立业务语义的接入包装，不能用上游传输或发送实现替代。尤其 QQ 明确拒绝时的文本降级与超时不重发规则应保留。

本次无法给出“用户对上游 fork 的具体改动”：没有项目内 vendor/fork 基线，当前安装文件与官方 tag 相同。若以后遇到可证实的私有基线，先取得共同基线 `B`、本地实现 `L`、目标上游实现 `U`，在隔离 worktree 用 diff3/`git merge-file -p L B U` 形成候选；逐项保留与目标修复无关的本地行为并审阅冲突，再分别为上游修复和本地合同加回归。基线未知或文件无法映射时先确认构建来源，不猜测基线、不覆盖原实现。

## 验证范围

按接入差异选择短合同：OneBot WS 是共享业务链唯一完整适配器验收；QQ 只核对格式、Markdown、蓝字、按钮 payload、回调 ACK 与明确拒绝降级，另以 `tests/test_commands.py`、`tests/test_messaging.py` 核对解析、事件身份、事件键和发送边界。若未来升级改变 Gateway timeout 行为，只需增加/运行对应 Adapter timeout 单测；只有 OneBot 运输/鉴权行为变化时才补必要 WS 验证。共享业务长链在同一运行状态只验一份。

本轮已把 `tests/test_lineup_protocol.py` 的 QQ 群/私聊 × text/native/template 六例改为短接入合同，不再每例执行完整多宠链；QQ 合同范围是格式、Markdown、蓝字、按钮 payload、回调 ACK 与降级，完整共享链仍由 OneBot WS 冒烟代表一次，并由 `tests/test_runtime.py` 在全量 pytest 中调用。此次只运行六个 QQ 聚焦用例，未重新全量、WS 或仿真；`1450 passed`、真实 OneBot ASGI/WS、compileall 和 `81,400` 场仿真是去重前相同运行代码/内容状态的既有证据，不能表述成当前测试树重跑全量。无真机时 QQ 官方呈现与权限均未实测；OneBot 通过不能声称 QQ 真机通过。Termux 真机和正式发布仍是外部待办，本地 mock 不代表平台通过。
