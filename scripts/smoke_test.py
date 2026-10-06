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
                    (9, "灵宠挑战 青岚林", "秘境获胜"),
                    (9, "灵宠挑战 青岚林", "秘境获胜"),
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
                    ws.send_json({"status": "ok", "retcode": 0, "data": {"message_id": message_id + 100}, "echo": request["echo"]})
        with closing(sqlite3.connect(database)) as conn:
            user_id, stones = conn.execute("SELECT user_id, stones FROM players").fetchone()
            assert user_id == "12345" and 230 <= stones <= 270
            assert conn.execute("SELECT COUNT(*) FROM pets").fetchone()[0] == 2
            assert conn.execute("SELECT layer, energy FROM pets WHERE pet_id=1").fetchone() == (2, 65)
        print("PASS: plugin load, WS authentication, summon, switch, cultivation, breakthrough, PVE and redelivery")


if __name__ == "__main__":
    main()
