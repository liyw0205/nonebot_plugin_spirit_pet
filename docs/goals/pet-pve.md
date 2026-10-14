# 灵宠关卡行内挑战闭环（pet-pve）

## 范围

- `pve_stages.catalog` 列表（`utils/pagination.paginate`，每页五条）：`可挑战/已通关` 行在其所在行挂唯一“前往挑战”蓝字（`InlineCommand`），命令为既有注册入口 `灵宠挑战关卡 <序号>` / `灵宠组队关卡 <序号>`，完整、直接执行；`未解锁/尚未结契` 行不挂任何可执行入口。
- 挑战命令退出按钮集合（`_action_items` 去重），按钮只剩 `灵宠关卡` 分页导航。
- 关卡详情回复、行文本、分页、精力/冷却/境界/前置关卡校验、首通奖励与永久战报幂等重放全部不变；schema 20 不动。

## 测试

- 定向命令：`./.venv/bin/pytest -q tests/test_stage_interaction.py tests/test_pve_stages.py tests/test_stage_content.py`。
- 新增 `tests/test_stage_interaction.py` 断言：新号仅首关挂蓝字且行位正确；已通关与新开行各挂一行、锁定行不挂；未注册玩家无蓝字；第二页仅新开行挂蓝字且分页按钮保留；组队关蓝字命令即注册的 `灵宠组队关卡` 入口，未组队时干净拒绝；QQ native markdown 蓝字 payload 与按钮零重复。

## 排除

- 不改战斗、奖励、解锁规则、schema、消息层；不新增“查看详情”行蓝字或第二套导航；不部署、不发真实 QQ 消息、不跑全量 pytest、WS 长链、仿真或压测；不重跑已通过的其他切片定向合同。

## 停止条件

- 定向测试通过、路线图/开发指南更新、diff 白名单提交推送 `develop` 且 CI 绿、快进合入 `main` 且 main CI 绿，即停止。
