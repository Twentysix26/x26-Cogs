import json
from .defender import Defender
from redbot.core import VersionInfo, version_info
from pathlib import Path

with open(Path(__file__).parent / "info.json") as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]


def setup(bot):
    if version_info >= VersionInfo.from_str("3.5.0"):
        raise RuntimeError("Defender needs to be updated to run on Red 3.5.0")

    bot.add_cog(Defender(bot))