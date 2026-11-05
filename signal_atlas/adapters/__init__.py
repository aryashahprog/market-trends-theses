from __future__ import annotations

from ..config import Settings
from .base import Adapter
from .marketwatch import MarketWatchAdapter
from .milkroad import MilkRoadAdapter
from .priceofcompute import PriceOfComputeAdapter
from .ramp import RampAiIndexAdapter
from .sec import SecEdgarAdapter
from .silicondata import SiliconDataAdapter


def default_adapters(settings: Settings) -> list[Adapter]:
    return [
        MilkRoadAdapter(),
        MarketWatchAdapter(),
        SecEdgarAdapter(settings.sec_user_agent),
        PriceOfComputeAdapter(),
        SiliconDataAdapter(),
        RampAiIndexAdapter(),
    ]
