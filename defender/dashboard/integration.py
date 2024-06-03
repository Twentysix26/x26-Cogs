from redbot.core import commands
from redbot.core.bot import Red

from .status import StatusIntegration
from .settings import SettingsIntegration
from .warden import WardenIntegration


class DashboardIntegration(StatusIntegration, SettingsIntegration, WardenIntegration):
    bot: Red

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        dashboard_cog.rpc.third_parties_handler.add_third_party(self)
