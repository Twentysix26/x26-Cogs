import json
from .sbansync import Sbansync
from pathlib import Path

with open(Path(__file__).parent / "info.json") as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]

async def setup(bot):
    await bot.add_cog(Sbansync(bot))
