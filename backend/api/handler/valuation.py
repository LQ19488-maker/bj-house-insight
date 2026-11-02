"""估价参考。"""

from __future__ import annotations

from backend.dto import params
from backend.service import valuation_service


def estimate(ctx):
    req = params.valuation(ctx)
    user_id = ctx.user_id if ctx.user else None
    return valuation_service.estimate(req, user_id)
