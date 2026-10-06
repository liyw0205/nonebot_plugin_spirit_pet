"""Run the actual ASGI app and a OneBot V11 client without NapCat or QQ credentials."""

import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

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

        responses = {}
        before_salvage = None
        with TestClient(nonebot.get_asgi()) as client:
            try:
                with client.websocket_connect("/onebot/v11/ws", headers={"X-Self-ID": "9000"}):
                    raise AssertionError("Unauthenticated OneBot client was accepted")
            except WebSocketDisconnect as exc:
                assert exc.code == 1008
            headers = {"X-Self-ID": "9000", "Authorization": "Bearer smoke-test-only"}
            with client.websocket_connect("/onebot/v11/ws", headers=headers) as ws:
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
                    ws.send_json({
                        "time": 1800000000, "self_id": 9000, "post_type": "message",
                        "message_type": "group", "sub_type": "normal", "message_id": message_id,
                        "group_id": 8000, "user_id": 12345, "message": command, "raw_message": command,
                        "font": 0, "sender": {"user_id": 12345, "nickname": "tester"},
                    })
                    request = ws.receive_json()
                    assert request["action"] == "send_msg", request
                    text = "".join(segment["data"].get("text", "") for segment in request["params"]["message"])
                    assert expected in text, text
                    if message_id in responses:
                        assert text == responses[message_id]
                    responses[message_id] = text
                    ws.send_json({"status": "ok", "retcode": 0, "data": {"message_id": message_id + 100}, "echo": request["echo"]})
                    if message_id == 18:
                        with closing(sqlite3.connect(database)) as conn:
                            before_salvage = conn.execute(
                                "SELECT p.stones, i.quantity FROM players p JOIN inventory i USING(user_id) "
                                "WHERE p.user_id='12345' AND i.item_id='forge_ore'"
                            ).fetchone()
        with closing(sqlite3.connect(database)) as conn:
            user_id, stones = conn.execute("SELECT user_id, stones FROM players").fetchone()
            assert user_id == "12345" and 100 <= stones <= 140
            assert before_salvage is not None and stones == before_salvage[0]
            assert conn.execute(
                "SELECT quantity FROM inventory WHERE user_id='12345' AND item_id='forge_ore'"
            ).fetchone()[0] == before_salvage[1] + 1
            assert conn.execute(
                "SELECT quantity FROM inventory WHERE user_id='12345' AND item_id='wind_feather'"
            ).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM pets").fetchone()[0] == 2
            assert conn.execute("SELECT layer, energy FROM pets WHERE pet_id=1").fetchone() == (2, 65)
            skill = conn.execute("SELECT level, proficiency FROM learned_skills WHERE pet_id=1").fetchone()
            assert skill and (skill[0] > 1 or skill[1] > 0)
        print("PASS: plugin load, WS authentication, collection, skills, PVE, workshop, crafting, salvage, lineages and redelivery")


if __name__ == "__main__":
    main()
