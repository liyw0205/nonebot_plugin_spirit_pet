"""Run the actual ASGI app and a OneBot V11 client without NapCat or QQ credentials."""

import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import nonebot
from fastapi.testclient import TestClient
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter
from nonebot.adapters.qq import Adapter as QQAdapter
from starlette.websockets import WebSocketDisconnect


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "spirit.db"
        nonebot.init(
            _env_file=Path(directory) / "absent.env",
            driver="~fastapi+~httpx+~websockets",
            qq_bots=[],
            onebot_v11_ws_urls=[],
            onebot_v11_access_token="smoke-test-only",
            spirit_pet_db=database,
            spirit_pet_qq_mode="text",
            api_timeout=3,
            log_level="WARNING",
        )
        driver = nonebot.get_driver()
        driver.register_adapter(OneBotAdapter)
        driver.register_adapter(QQAdapter)
        plugins = nonebot.load_from_toml("pyproject.toml")
        assert {plugin.name for plugin in plugins} == {"nonebot_plugin_spirit_pet"}
        plugin_package = next(iter(plugins)).module.__name__

        responses = {}
        before_salvage = None
        expedition_reward = None
        with TestClient(nonebot.get_asgi()) as client:
            try:
                with client.websocket_connect("/onebot/v11/ws", headers={"X-Self-ID": "9000"}):
                    raise AssertionError("Unauthenticated OneBot client was accepted")
            except WebSocketDisconnect as exc:
                assert exc.code == 1008
            headers = {"X-Self-ID": "9000", "Authorization": "Bearer smoke-test-only"}
            with client.websocket_connect("/onebot/v11/ws", headers=headers) as ws:
                def exchange(user_id, message_id, command, expected):
                    ws.send_json({
                        "time": 1800000000, "self_id": 9000, "post_type": "message",
                        "message_type": "group", "sub_type": "normal", "message_id": message_id,
                        "group_id": 8000, "user_id": user_id, "message": command, "raw_message": command,
                        "font": 0, "sender": {"user_id": user_id, "nickname": "tester"},
                    })
                    request = ws.receive_json()
                    assert request["action"] == "send_msg", request
                    text = "".join(segment["data"].get("text", "") for segment in request["params"]["message"])
                    assert expected in text, text
                    if message_id in responses:
                        assert text == responses[message_id]
                    responses[message_id] = text
                    ws.send_json({"status": "ok", "retcode": 0, "data": {"message_id": message_id + 100}, "echo": request["echo"]})

                for message_id, command, expected in [
                    (1, "灵宠领养 青鸾", "灵契初成"),
                    (2, "灵宠签到", "灵石 +200"),
                    (2, "灵宠签到", "灵石 +200"),
                    (3, "我的灵宠", "灵石：300"),
                    (4, "灵宠列表", "灵宠名册"),
                    (5, "灵宠召唤 1", "山海召唤"),
                    (6, "灵宠切换 1", "灵宠出战"),
                    (7, "灵宠修炼", "吐纳修炼"),
                    (8, "灵宠突破", "小境界突破成功"),
                    (10, "灵宠图鉴 毕方", "主属性：火 · 副属性：风"),
                    (11, "灵宠图鉴 2", "万灵图鉴 2/"),
                    (12, "我的灵宠", "天赋神通：岚羽清鸣"),
                    (13, "灵宠购买 风刃术诀", "灵坊购得"),
                    (14, "灵宠学习 风刃术", "领悟灵术"),
                    (15, "灵宠技能", "1级 · 熟练度 0/20"),
                    (9, "灵宠挑战 青岚林", "秘境获胜"),
                    (9, "灵宠挑战 青岚林", "秘境获胜"),
                    (16, "灵宠领奖 斩破迷障", "灵石 +60"),
                    (17, "灵宠工坊 青岚翎", "打造一件 +0：40 灵石、锻灵矿 2"),
                    (18, "灵宠打造 青岚翎", "青岚翎 +0 获得 1 件"),
                    (19, "灵宠分解 青岚翎 +0 1", "回收 锻灵矿 1"),
                    (19, "灵宠分解 青岚翎 +0 1", "回收 锻灵矿 1"),
                    (20, "灵宠血脉 青鸾", "凌风鸾脉"),
                ]:
                    exchange(12345, message_id, command, expected)
                    if message_id == 18:
                        with closing(sqlite3.connect(database)) as conn:
                            before_salvage = conn.execute(
                                "SELECT p.stones, i.quantity FROM players p JOIN inventory i USING(user_id) "
                                "WHERE p.user_id='12345' AND i.item_id='forge_ore'"
                            ).fetchone()
                for user_id, message_id, command, expected in [
                    (12345, 21, "灵宠道号 青云道友", "道号已定"),
                    (67890, 22, "灵宠领养 玄狐", "灵契初成"),
                    (67890, 23, "灵宠道号 归元道友", "道号已定"),
                    (12345, 24, "灵宠组队", "灵契小队"),
                    (67890, 25, "灵宠入队 青云道友", "入队申请已提交"),
                    (67890, 26, "灵宠队伍同意 青云道友", "只能由队长审批"),
                    (12345, 27, "灵宠队务 归元道友", "队务详情"),
                    (12345, 28, "灵宠队伍同意 归元道友", "加入队伍"),
                    (12345, 28, "灵宠队伍同意 归元道友", "加入队伍"),
                    (67890, 29, "灵宠准备", "出征准备"),
                    (12345, 30, "灵宠准备", "出征准备"),
                    (12345, 31, "灵宠转让 归元道友", "队长交接"),
                    (12345, 32, "灵宠队伍", "未准备"),
                    (12345, 33, "灵宠解散", "仅队长"),
                    (67890, 34, "灵宠踢人 青云道友", "移出队伍"),
                    (67890, 35, "灵宠邀请 青云道友", "队伍邀请已发起"),
                    (12345, 36, "灵宠队伍同意 归元道友", "加入队伍"),
                    (67890, 37, "灵宠解散", "小队解散"),
                ]:
                    exchange(user_id, message_id, command, expected)
                    assert "12345" not in responses[message_id] and "67890" not in responses[message_id]
                exchange(12345, 38, "灵宠委托 采灵药", "山海委托")
                exchange(12345, 39, "灵宠派遣 采灵药", "灵宠启程")
                exchange(12345, 39, "灵宠派遣 采灵药", "灵宠启程")
                exchange(12345, 40, "灵宠修炼", "外出")
                with closing(sqlite3.connect(database)) as conn:
                    job_id, finishes_at, snapshot = conn.execute(
                        "SELECT job_id, finishes_at, reward_snapshot FROM expeditions WHERE user_id='12345'"
                    ).fetchone()
                    expedition_reward = json.loads(snapshot)
                    before_exp = conn.execute("SELECT exp FROM pets WHERE pet_id=1").fetchone()[0]
                exchange(67890, 41, f"灵宠归来 {job_id}", "没有属于你的")
                exchange(12345, 42, f"灵宠归来 {job_id}", "尚未完成")
                with patch(f"{plugin_package}.application.game.time.time", return_value=finishes_at):
                    exchange(12345, 43, "灵宠归来", "已完成")
                    exchange(12345, 44, f"灵宠归来 {job_id}", "委托归来")
                    exchange(12345, 44, f"灵宠归来 {job_id}", "委托归来")
                    exchange(12345, 45, f"灵宠归来 {job_id}", "不能重复结算")
                with closing(sqlite3.connect(database)) as conn:
                    user_id, stones = conn.execute("SELECT user_id, stones FROM players WHERE user_id='12345'").fetchone()
                    assert expedition_reward is not None
                    assert user_id == "12345" and 100 <= stones - expedition_reward['stones'] <= 140
                    assert before_salvage is not None and stones == before_salvage[0] + expedition_reward['stones']
                    assert conn.execute(
                        "SELECT quantity FROM inventory WHERE user_id='12345' AND item_id='forge_ore'"
                    ).fetchone()[0] == before_salvage[1] + 1
                    assert conn.execute(
                        "SELECT quantity FROM inventory WHERE user_id='12345' AND item_id='wind_feather'"
                    ).fetchone()[0] == 0
                    assert conn.execute("SELECT COUNT(*) FROM pets").fetchone()[0] == 3
                    assert conn.execute("SELECT layer, energy FROM pets WHERE pet_id=1").fetchone() == (2, 40)
                    assert conn.execute("SELECT exp FROM pets WHERE pet_id=1").fetchone()[0] == before_exp + expedition_reward['exp']
                    assert conn.execute("SELECT state FROM expeditions").fetchall() == [("claimed",)]
                    assert conn.execute("SELECT energy FROM pets WHERE user_id='67890'").fetchone()[0] == 100
                    assert conn.execute("SELECT stones FROM players WHERE user_id='67890'").fetchone()[0] == 100
                    for table in ("teams", "team_members", "team_requests"):
                        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
                    skill = conn.execute("SELECT level, proficiency FROM learned_skills WHERE pet_id=1").fetchone()
                    assert skill and (skill[0] > 1 or skill[1] > 0)
                    before_duel_items = conn.execute("SELECT * FROM inventory ORDER BY user_id, item_id").fetchall()
                with patch(f"{plugin_package}.application.game.time.time", return_value=finishes_at):
                    exchange(12345, 46, "灵宠切磋 归元道友", "切磋结算")
                    exchange(12345, 46, "灵宠切磋 归元道友", "切磋结算")
                    with closing(sqlite3.connect(database)) as conn:
                        before_duel_energy = dict(conn.execute(
                            "SELECT p.user_id, t.energy FROM players p JOIN pets t ON p.active_pet_id=t.pet_id"
                        ))
                        assert before_duel_energy == {"12345": 40, "67890": 100}
                    exchange(67890, 47, "灵宠切磋 归元道友", "自己")
                    exchange(12345, 48, "灵宠论剑 归元道友", "凝气")
                    with closing(sqlite3.connect(database)) as conn:
                        assert dict(conn.execute(
                            "SELECT p.user_id, t.energy FROM players p JOIN pets t ON p.active_pet_id=t.pet_id"
                        )) == before_duel_energy
                        assert conn.execute("SELECT COUNT(*) FROM pvp_results").fetchone()[0] == 0
                        conn.execute("UPDATE pets SET realm=1")
                        conn.commit()
                    exchange(12345, 49, "灵宠匹配", "论剑候选")
                    with closing(sqlite3.connect(database)) as conn:
                        assert conn.execute("SELECT energy FROM pets WHERE pet_id=1").fetchone()[0] == 52
                    exchange(12345, 50, "灵宠论剑 归元道友", "论剑结算")
                    exchange(12345, 50, "灵宠论剑 归元道友", "论剑结算")
                    exchange(12345, 51, "灵宠论剑 归元道友", "调息")
                    exchange(12345, 52, "灵宠赛季", "论剑赛季")
                    exchange(67890, 53, "灵宠论剑", "论剑榜")
                    for message_id in range(46, 54):
                        assert "12345" not in responses[message_id] and "67890" not in responses[message_id]
                with closing(sqlite3.connect(database)) as conn:
                    assert conn.execute("SELECT COUNT(*) FROM pvp_results").fetchone()[0] == 1
                    assert conn.execute("SELECT COUNT(*), SUM(rating) FROM season_entries").fetchone() == (2, 2000)
                    assert conn.execute("SELECT energy FROM pets WHERE pet_id=1").fetchone()[0] == 32
                    assert conn.execute("SELECT energy FROM pets WHERE user_id='67890'").fetchone()[0] == 100
                    assert conn.execute("SELECT last_pvp FROM players WHERE user_id='67890'").fetchone()[0] is None
                    assert conn.execute("SELECT stones FROM players WHERE user_id='12345'").fetchone()[0] == stones
                    assert conn.execute("SELECT stones FROM players WHERE user_id='67890'").fetchone()[0] == 100
                    assert conn.execute("SELECT * FROM inventory ORDER BY user_id, item_id").fetchall() == before_duel_items
        print("PASS: plugin load, WS authentication, collection, skills, PVE, crafting, lineages, teams, offline journeys, direct mirror battles, arena seasons and redelivery")


if __name__ == "__main__":
    main()
