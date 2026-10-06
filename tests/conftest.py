import sys
from pathlib import Path

import nonebot


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "plugins"))
nonebot.init(_env_file=(), driver="~fastapi+~httpx+~websockets", log_level="WARNING")
