# 队务列表行内详情闭环（pet-team-request-row-actions）

## 缺陷

`gameplay/teams/requests.py::inbox` 每页四条队务，此前把每行详情命令 `灵宠队务 <对方UID>` 全部塞进按钮，再叠加 `灵宠队务 分页 <n>` 导航；`adapters/messaging.py::_action_items` 四条上限截断后，满页时的第四行队务与翻页在 QQ native 键盘不可达（`PAGE_SIZE = 4`，四条行命令已占满按钮位）。

## 范围

- 只改 `gameplay/teams/requests.py::inbox` 列表回复：每条队务行在其所在行挂唯一“查看详情”蓝字（`InlineCommand`，命令 `灵宠队务 <对方UID>`，即既有注册入口，完整、直接执行只读详情）。
- 行命令退出按钮集合（`_action_items` 去重），按钮只剩 `灵宠队务 分页 <n>` 导航；空列表时保留原有 `灵宠队伍`/`灵宠组队` 回退入口。
- 行文本 `_summary`、排序、分页、`_detail` 详情回复（发起人撤回 / 处理人同意与拒绝）、`_require_decider` 授权、过期与上限规则、并发与永久幂等重放、schema 20 全部不动。

## 验收标准

1. 满页（四条）列表：`reply.inline_commands` 恰为四条，`(line, label, command)` 与各行的 `灵宠队务 <对方UID>` 一一对应，且行位校验成立（`reply.lines[link.line]` 含该行对方 UID）。
2. `reply.commands` 恰为分页导航（首页仅 `灵宠队务 分页 2`），不再包含任何行命令。
3. QQ native payload：markdown 蓝字集合与行蓝字一致，键盘按钮集合等于派生分页集合，两者交集为空。
4. 第二页：蓝字覆盖第二页各行，按钮为 `灵宠队务 分页 1` 与 `灵宠队务 分页 3`。
5. 空列表：无蓝字，回退入口 `灵宠队伍`（已在队）/`灵宠组队`（未在队）仍在按钮集合中。
6. 降级（非 native）：文本含可读形式 `查看详情（/灵宠队务 <对方UID>）`，且不含 `mqqapi://`。
7. 详情回复未受影响：处理人仍拿到 `灵宠队伍同意/拒绝 <对方UID>`，发起人仍拿到 `灵宠队伍撤回 <对方UID>`，且详情回复不挂行蓝字。

## 定向测试

- 新增 `tests/test_team_request_interaction.py`（复用 `tests/test_stage_interaction.py` 的 `markdown_links`/`keyboard_buttons` 夹具思路与 conftest `game`/`play`，多用户用 `play(..., user=...)`）。
- 定向命令：`PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' ./.venv/bin/pytest -q tests/test_team_request_interaction.py tests/test_team_requests.py tests/test_team_management.py tests/test_commands.py`。
- 既有合同只按需原地更新，不复制；`test_team_requests.py` 现有断言（分页命令、过期后无行命令、UID 隐私）应保持通过。

## 非目标

- 不改 `gameplay/teams/party.py`（队员名帖与小队页面的按钮堆叠另开切片）。
- 不改 `management.py`、`common.py`、消息层、战斗、奖励、schema 或注册入口。
- 不给行挂可执行审批蓝字（同意/拒绝仍从详情进入）；不改任何游戏规则、授权或过期语义。
- 不部署、不发真实 QQ 消息、不跑全量 pytest、WS 长链、仿真或压测；不重跑其他切片已通过的定向合同。

## 停止条件

- 定向测试通过、路线图与开发指南更新、diff 白名单提交推送 `develop` 且 develop CI 绿、快进合入 `main` 且 main CI 绿，即停止；不部署。
