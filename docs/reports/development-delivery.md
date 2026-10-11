# 本地开发版交付记录

日期：2026-10-09（UTC+8）。D1、D2、D3 均为 `passed`，覆盖既有完整玩法与本轮多宠合同。QQ 与 Termux 真机仍为 `waiting_external`，正式发布为 `blocked`。本记录不代表平台实号验收或发布授权。

## QQ 消息体验补充交付（2026-10-10）

本轮基准为 `develop` 的 `a515ec9`，交付源码由包含本节的提交标识；下方“验证状态”及 D1-D3 章节保留 2026-10-09 的历史运行证据，不代表本轮源码重新全量通过。只读上游审查已完成，D1-D3 仍为 `passed`，当前没有活动的本地开发 goal。

- “我的灵宠”按概况、成长、状态、战斗、进阶分组；原生 Markdown 的改名蓝字在道号行，关闭蓝字时提供单个改名按钮。帮助为总览和八个玩法子页，分类蓝字随分类行展示，键盘使用自然标签；可见用法和提示不写固定斜杠前缀，payload 按配置保留自定义或空前缀。
- 已安装 QQ adapter `1.7.3` 的 `GroupAtMessageCreateEvent`、`GroupMessageCreateEvent` 使用同一会话/消息键；`C2CMsgReceiveEvent`、`GroupMsgReceiveEvent` 为生命周期通知，不执行业务命令。参考 xiu2 的 `qq_compat/context.py`、`lifecycle.py` 与 `adapter_compat.py` 区分消息与生命周期。同键输入只结算一次；既有事务重放仍可再次回复，不承诺消息发送 exactly-once。
- 复用本轮已运行结果：`tests/test_messaging.py` 为 `19 passed`；`tests/test_information.py -k 'status_shows or help or rename_entry or plugin_usage'` 为 `6 passed`；`tests/test_commands.py` 的两类群消息键、重复事务与接收通知排除用例为 `4 passed`。覆盖 Markdown、蓝字、按钮 payload、自定义/空前缀与显式拒绝降级；回调 ACK 路径未改，本轮未新增 ACK 运行结果。没有重复 OneBot 共享业务长链、全量 pytest、WS 或仿真。
- `/root/spirit-pet-qq-test-20261010` 是独立安装副本，没有 Git 元数据；2026-10-10 只读核对其 handler、formatter、帮助源码与 `a515ec9` 一致，尚不含本轮改动。观察到两个以该目录为工作目录的 Python 进程，但未核实它们的入口或内存中的源码版本。未读取凭据、修改配置、部署、重启或发送 QQ 消息，也未操作 xiu2。
- 审阅 `/root/stress_test.py` 后未执行压测：当前文件默认每批 `40` 个用户任务、`60` 秒；按用户要求设为 `50` 时，每个任务最多四条，约五秒最多 `1000` 条，不是每秒仅 `50` 条。服务/数据库隔离、RAM 基线和硬内存上限未确认；脚本原命令集也不代表 pet 工作负载，响应按群 ID 关联，未据此产出 pet 吞吐结论。后续仅在独立临时库和隔离服务、硬内存限制、无 xiu3 并行压测成立后短测并记录 RSS/延迟。

提交与独立远端核验的精确 SHA 另记于本机 `/tmp/pet-progress-20261010.md`。源码交付不等于部署更新或真实 QQ 验收；QQ 官方呈现/权限及 Termux 仍为 `waiting_external`，正式发布为 `blocked`。

## 验证状态

验证对象为 `develop` 工作区，基准 HEAD 为 `4f9b2160859cc9c0f9b9140a424fa9cfa5cb4661`，包含既有未提交改动与本轮新增文件；没有提交、推送、合并或发版。所有运行门禁完成后仅调整文档，运行文件清单再次校验通过。

- [运行文件 SHA-256 清单](development-runtime-files.sha256) 覆盖 `src`、`scripts`、`tests` 的 190 个文件，包含静态 JSON 与新增未跟踪代码；清单哈希为 `eab08e22ba6219e707761a8188b928967311129319566c93237a4e6fe20b9e14`。
- [运行改动 patch](development-runtime.patch) 来自 `git diff -- src scripts tests requirements.txt pyproject.toml .env.example`，哈希为 `dbad386459afa1001ddba0a7a9e812788ae22894f5413b6536fc1156aabe1b40`。它记录已跟踪文件的未提交改动；新增文件以工作区源码和上方清单为准，不能只应用 patch 就声称复现了完整状态。
- [依赖快照](development-dependencies.txt) 来自 `.venv/bin/python -m pip freeze`，哈希为 `bff2b88d6d67f647a413b2c87e6554823e9277d537a8a457910ba3fa63beba89`；门禁后与当前环境再次比对一致。Python 为 `3.11.2`，NoneBot2 `2.5.0`，OneBot `2.4.6`，QQ `1.7.3`，Pydantic `2.13.5`，pytest `9.1.1`。
- 三组完整仿真实际加载的 Catalog 哈希均为 `f9d32d0fb7864e6fa85dc9c15a328de7f2b82e5f0b3ffc1e9e52558498628458`。这是 `TypeAdapter(Catalog).dump_json(content)` 的 SHA-256；原始内容文件另由运行清单标识。

配置和依赖声明文件 SHA-256：

```text
requirements.txt  81f1ed0cc519f82c04b067f8326db1da1be1de185ff52f2aef1cb6689a1c85a1
pyproject.toml    9f90a64e883cb7c1e05f125ee5c78114f6d991e6a537b8e621b34b13e8793541
.env.example      09cc3ae95a32d198a65e4de653ffffbbd3c2bd4296b6bb441d403cb42a285384
```

pytest 使用临时库和默认 `Config()`，协议测试按场景指定消息模式；WS 冒烟使用临时库、测试鉴权 token 和空 QQ/主动 WS 连接配置，不加载真实 `.env`。仿真使用默认配置：PVE 冷却 600 秒、每宠每 300 秒恢复 1 精力，初始每宠 100 精力。所有仿真仅连接临时 SQLite，不连接 `SPIRIT_PET_DB` 或用户存档。

## D1 复现与修复

最小复现：队长设置三只不同种族宠物，队友入队并各自准备；依次指定队长第二或第三宠执行修炼、突破、进化、喂养、互动。原实现只比较 `active_pet_id`，上述十个输入均错误保留队长准备；初始矩阵结果为 `10 failed, 35 passed`。

`Repository.invalidate_pet_ready(user_id, pet_id)` 现在按实际组队角色识别参战宠，五类养成入口共用该判断。队长整份阵容的任一宠变化都会清除本人准备；队友仅首宠参战，备用宠和队友非首宠养成保留准备。准备失效仍在原业务事务内，资源不足等拒绝整体回滚，已扣成本的突破/进化失败则清准备。队伍概览与成员详情也只展示队友实际参战首宠。

保留并验证既有修复：秘境奖励与任务每成员一次、修为归首宠；熟练度归实际施法宠，论剑仅奖励挑战者；双方混合境界论剑拒绝，候选在 SQL 分页前排除混合境界阵容。相关快测先后为 110 项、95 项和补充失败/重投 7 项通过，最终全部纳入 1450 项全量回归。

回归入口：[准备与指定养成](../../tests/test_lineup_readiness.py)、[成员结算与境界](../../tests/test_lineup_settlement.py)、[阵容边界与永久重投](../../tests/test_lineup_coverage.py)、[实际施法熟练度](../../tests/test_mastery.py)。

文档与实现对应：阵容顺序用于展示和首宠选择，行动按速度；单宠切换重置阵容；满亲密互动仍消耗每日次数；切磋不扣资源、不增熟练度。养成重投只在约七日通用缓存存在时返回原回复，不撤销后来重新准备；缓存过期后按新操作检查，养成没有永久凭证。永久战斗重放另由战报/论剑凭证保障。

## D2 命令链与数值结论

[共用多宠协议链](../../scripts/smoke_test.py) 经真实 ASGI 的 `/onebot/v11/ws` 收发，并经命令解析、同一业务事务和回复路径执行。QQ 群聊/私聊分别测试 text、native、template，共 6 项通过；QQ 发送为 mock，不替代真实 AppID 权限验收。

链路包括阵容设置与只读查询、三宠秘境、队长三宠加两队友的五宠战斗、第二宠修炼清准备与未准备开战拒绝、3v3 论剑/切磋、战报查看和越权拒绝。直接核对 SQLite 与真实 `Battle.skill_uses`，验证逐宠精力/熟练度、成员单份材料与灵石、首宠修为、成员一次任务、只读镜像和战前快照。删除通用缓存、推进八天并改变阵容后，四类战斗原消息仍永久重放，资源和战报保持不变。只预置战斗前提，战斗使用真实 `fight`；测试观察包装在退出时恢复。

新增阵容矩阵完整结果：[JSON](development-lineups.json)、[场景与对照表](development-lineups.md)。16 个秘境 × entry/prepared × baseline/multi，共 64 场景、32 对对照；每场景 100 次，种子 `20261007`，共 6400 场。

- 单人一宠对三宠；组队三名玩家各一宠，对队长三宠加两名队友各一宠。固定种族为目录前三种初选：青鸾、玄狐、白泽；成长与配装复用基础矩阵，不选择分支或共鸣。
- 使用生产 `run_dungeon`、装配与 `fight`。每场通过 SAVEPOINT 和新 Repository 重置初始状态，场景结束回滚；不沿用上场的精力、熟练度、收益或内存对象。
- 总计胜/平/败为 `4117/0/2283`，最长 34 回合。精力、非首宠修为、成员奖励、任务进度和快照五类结算违规全部为 0，门禁 `0 issues`。
- prepared 基线和多宠各 16 场景，均为 `1600/0/0`；平均回合从 6.427 降至 2.597。三宠/五宠最低采样胜率均为 100%。entry 基线为 `200/0/1400`，多宠为 `717/0/883`，保留准入失败样本，不要求 entry 必胜。
- 多宠不按宠物数量倍发奖励。自然恢复逐宠并行，持续间隔为 `max(共享 PVE 冷却, 每宠耗能 × 恢复间隔)`；胜率提升会增加个人持续收益。青岚林 prepared 三宠各耗 20 精力，总耗 60，每胜只有一份奖励，持续间隔 6000 秒；每成员小时修为范围 21–36、灵石 24–48。上古灵殿五宠各耗 30，总耗 150，每胜三名成员各一份奖励，持续间隔 9000 秒；每成员小时修为范围 28–40、灵石 36–52。

收益范围是静态奖励上下限乘采样胜率和持续次数，不是置信区间。报告还保留实际随机结算的采样收益与获胜奖励范围。不计开局满精力、药品、任务/成就收益、材料转售、备用宠轮换和获取成本；未穷举全部种族、分支、共鸣、配装、PVP 或关卡首通。协议与既有回归覆盖这些玩法的本地功能合同，有限阵容矩阵不提供全部竞技配装平衡证明。本轮没有在这些场景复现新的结算或 prepared 胜率门禁缺口。

## D3 最终门禁

以下为实际运行的 Python 命令；有输出的门禁经 `tee` 留存，完成后改存 `.txt`，便于版本管理。所有命令退出码均为 0，重型门禁串行运行。

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/smoke_test.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/balance_report.py --runs 100 --seed 20261007 --csv docs/reports/development-balance.csv --check
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/balance_specials.py --runs 100 --seed 20261007 --csv docs/reports/development-specials.csv --check
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/balance_lineups.py --runs 100 --seed 20261007 --check --json docs/reports/development-lineups.json --markdown docs/reports/development-lineups.md
.venv/bin/python -m compileall -q src tests scripts
```

| 门禁 | 最终结果 | 留存证据 |
| --- | --- | --- |
| 全量 pytest | 1450 passed，162.51 秒；1 条第三方 Starlette/httpx 弃用提示 | [输出](development-pytest.txt) |
| 真实 ASGI/OneBot WS | 插件加载、鉴权、既有玩法、多宠协议链与重投均 PASS | [输出](development-smoke.txt) |
| 基础矩阵 | 626 场景 / 62,600 场 / 0 issues；胜/平/败 37832/0/24768，最长 23 回合；化神/渡劫 prepared 最低 90%/98% | [CSV](development-balance.csv)、[输出](development-balance.txt) |
| 分支/效果专项 | 124 场景 / 12,400 场 / 0 issues；54/54 分支、7/7 效果覆盖；最长 40 回合，无非法状态 | [CSV](development-specials.csv)、[输出](development-specials.txt) |
| 三宠/五宠矩阵 | 64 场景 / 6400 场 / 0 issues；五类结算违规为 0 | [JSON](development-lineups.json)、[Markdown](development-lineups.md)、[输出](development-lineups.txt) |
| compileall | `src tests scripts` 编译通过 | 本次命令退出码 0 |

原 [balance.csv](balance.csv) 与 [balance_specials.csv](balance_specials.csv) 保留为历史证据。当前基础有 68 行、专项有 33 行与历史 CSV 不同，当前胜败/回合/实际触发数以上述新文件为准；历史 Catalog 哈希不能用于标识本次运行。

既有完整合同的代表性回归入口如下；表中的文件全部包含在本次全量测试中，并非只验收本轮新功能：

| 合同范围 | 回归文件（均位于 `tests/`） |
| --- | --- |
| 严格静态内容、引用与八类种族/元素 | `test_content.py`、`test_pet_catalog.py`、`test_element_branches.py`、`test_effect_models.py` |
| 双适配器原始 ID、命令、消息权限降级与中文帮助 | `test_commands.py`、`test_messaging.py`、`test_information.py`、`test_runtime.py`、`test_lineup_protocol.py` |
| 道号唯一性、改名、分页与身份隔离 | `test_identity.py`、`test_dao_names.py`、`test_dao_review.py`、`test_pagination.py` |
| 领养/召唤保底、灵卵、名册/封存与阵容 | `test_summon_guarantee.py`、`test_hatching.py`、`test_pet_archive.py`、`test_multi_pet_lineup.py` |
| 七境十层、破境积累、血脉、指定编号养成、同族合修 | `test_progression.py`、`test_lineages.py`、`test_targeted_progression.py`、`test_targeted_training.py`、`test_targeted_care.py`、`test_co_training.py` |
| 日常经济、任务、互动连续陪伴与历练奇闻 | `test_game.py`、`test_companionship.py`、`test_adventure_routes.py`、`test_achievements.py` |
| 装备三槽/套装、强化保留、打造/分解与材料损耗 | `test_loadout.py`、`test_forging.py`、`test_crafting.py` |
| 属性、神通、主动效果期限/群攻与逐宠熟练度 | `test_battles.py`、`test_talents.py`、`test_skill_effects.py`、`test_mastery.py` |
| 秘境/章节、前置进度、成员一次首通和历史战报授权 | `test_pve_stages.py`、`test_stage_content.py`、`test_battle_records.py`、`test_lineup_coverage.py`、`test_lineup_settlement.py` |
| 队伍审批/邀请/管理、TTL、容量和出征并发 | `test_team_requests_contract.py`、`test_team_management.py`、`test_team_concurrency.py`、`test_team_messaging.py`、`test_lineup_readiness.py` |
| 离线委托占用、原宠奖励、冻结快照与终态竞争 | `test_expedition_contract.py`、`test_expedition_occupancy.py`、`test_expedition_storage.py`、`test_expedition_commands.py` |
| 赛季、只读镜像、限额、自然月/时钟回退和一次领奖 | `test_arena_battles.py`、`test_arena_matching.py`、`test_seasons.py`、`test_arena_messaging.py` |
| 成就/收集、永久凭证、共鸣成本/隔离/快照 | `test_achievements.py`、`test_resonance.py` |
| 事务回滚、冷却边界、跨缓存重投与并发 | `test_game.py`、`test_lineup_coverage.py`、上述队伍/行程/赛季/成就/章节测试 |
| schema 18 拒绝不支持的旧库且不改原文件；在线备份/非覆盖恢复 | `test_game.py`、`test_database_admin.py` |
| Bash 安装、无 Python 自举、隔离卸载与 xiupet 启停 | `test_installers.py` |

结果文件 SHA-256：

```text
development-balance.csv   5624f253305bb5b3700e32c3c14067750a6320f5f018f859daac9245f77c178d
development-specials.csv  93f8fd204cabd12fae7f45c4983277e863ef28ea1651d682dcce09be69ef8b0b
development-lineups.json  d57ddfe72b2dc4a063d514cb8c7375c40f41c3a6736c9418421e4a9e9db75c54
development-lineups.md    0a388f5da0a07c3272eea263648919c1de7935a544ccd84e5de5112d42f64da7
```

最终核对包含 `sha256sum -c --quiet docs/reports/development-runtime-files.sha256`、依赖快照比对、`git diff --check` 与文档链接检查。仅文档调整复用上述运行证据，不重复游戏门禁。

## 清理与下一交付

门禁进程均已退出，检查未发现本任务残留 pytest、冒烟、仿真或 compileall 进程。已清理项目 `.pytest_cache`、`src/tests/scripts` 的 14 个 `__pycache__`、本次快测/全量测试临时目录 `pytest-11`、`pytest-12`、`pytest-13`，以及 640 场小验收临时报告 `/tmp/spirit-pet-lineups-d2-EAcuKX`，释放约 353 MiB 磁盘空间。后续其他会话产生的 pytest 目录与 `pytest-current` 保留；交付报告、`.venv`、用户存档、代理 IPC 与其他服务保持原状。清理时系统可用内存约 1.38 GiB；本轮没有运行需要常驻的开发服务。

下一交付为外部验收：QQ 需真实 AppID/账号权限和客户端，检查普通消息、Markdown、键盘、蓝字与权限降级；Termux 需设备，检查安装、更新、启停、卸载与存档保护，并记录环境和实际结果。Python 3.10 的最低支持声明也没有本机运行结果，本次仅证明 Python 3.11.2 环境。外部结果到位后再按 [路线图](../ROADMAP.md#外部验收与正式发布) 冻结版本和准备正式发布；不从本地绿灯推断真机或全部 Python 环境已通过。
