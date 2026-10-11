from nonebot.plugin import PluginMetadata

from .core.config import Config

__plugin_meta__ = PluginMetadata(
    name="灵宠",
    description="文字灵宠养成与修仙，共享数据的 OneBot V11 / QQ 双适配器插件",
    usage="灵宠帮助 · 灵宠领养 青鸾 · 我的灵宠 · 灵宠签到",
    type="application",
    homepage="https://github.com/liyw0205/nonebot_plugin_spirit_pet",
    config=Config,
    supported_adapters={"~onebot.v11", "~qq"},
)

from .adapters import handlers as handlers  # noqa: E402
