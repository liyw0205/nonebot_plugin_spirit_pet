# 山海秘境行内详情闭环（pet-dungeon-list）

## 范围

- `gameplay/adventure.dungeons` 秘境列表（每页五条）：每条秘境行在其所在行挂唯一“查看详情”蓝字（`InlineCommand`），命令为既有注册入口 `灵宠秘境 <秘境名>`（只读详情，任何玩家可执行，与万灵图鉴“查看详情”同一约定），完整、直接执行。
- 行命令退出按钮集合（`_action_items` 去重后本就自动离开），按钮只剩 `灵宠秘境` 分页导航，第五行与翻页在 QQ native 键盘可达。
- 秘境详情回复、行文本、排序、分页、`灵宠挑战`/`灵宠组队挑战` 校验、精力/冷却/境界检查、掉落与永久战报幂等重放全部不变；schema 20 不动。

## 测试

- 定向命令：`PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' ./.venv/bin/pytest -q tests/test_dungeon_interaction.py tests/test_balance.py tests/test_adventure_routes.py tests/test_commands.py`。
- 新增 `tests/test_dungeon_interaction.py` 断言：首页五行各挂一条“查看详情”蓝字且行号/命令逐行对应；`reply.commands` 恰为分页导航；native markdown payload 蓝字解析结果与行蓝字一致、按钮集合与派生分页集合相等且零重复；第二页蓝字覆盖第二页秘境、上一页/下一页按钮保留；详情回复首命令仍是挑战入口（详情未被改动）；OneBot/降级文本含 `（/灵宠秘境 <名>）` 可读形式且无 `mqqapi://`。
- 复用 `tests/test_stage_interaction.py` 的 `markdown_links`/`keyboard_buttons` 夹具与 conftest `game`/`play`。

## 排除

- 不改战斗、奖励、解锁、详情内容、schema、消息层；不给未解锁境界行做可执行挑战蓝字（挑战仍从详情进入，与论剑历史行不同——列表行只挂只读详情入口）；不部署、不发真实 QQ 消息、不跑全量 pytest、WS 长链、仿真或压测；不重跑已通过的其他切片定向合同。

## 停止条件

- 定向测试通过、路线图/开发指南更新、diff 白名单提交推送 `develop` 且 CI 绿、快进合入 `main` 且 main CI 绿，即停止。
