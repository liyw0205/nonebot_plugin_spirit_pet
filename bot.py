import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from nonebot.adapters.qq import Adapter as QQAdapter


nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)
driver.register_adapter(QQAdapter)
loaded = nonebot.load_from_toml("pyproject.toml")
if not any(plugin.name == "nonebot_plugin_spirit_pet" for plugin in loaded):
    raise RuntimeError("Spirit Pet failed to load; check the error above")

if __name__ == "__main__":
    nonebot.run()
