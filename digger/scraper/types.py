"""Pydantic v2 models for data parsed from Discogs marketplace pages.

These are pure data containers; no DB logic here. They are consumed by
listing_parser.py, seller_parser.py, and ultimately by the ScrapeExecutor.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Condition = Literal["M", "NM", "VG+", "VG", "G+", "G", "F", "P"]
SleeveCondition = Literal[
    "M", "NM", "VG+", "VG", "G+", "G", "F", "P", "generic", "no_cover"
]


class ParsedListing(BaseModel):
    """A single marketplace listing row extracted from a Discogs release sale page."""

    listing_id: int
    release_id: int
    seller_username: str
    seller_id: int | None = None
    price_value: Decimal = Field(ge=0)
    price_currency: str = Field(min_length=3, max_length=3)
    media_condition: Condition
    sleeve_condition: SleeveCondition
    comments: str | None = None
    posted_at: datetime | None = None


class ParsedSeller(BaseModel):
    """Seller profile data extracted from a Discogs seller page."""

    seller_id: int
    username: str
    country_code: str | None = None
    feedback_count: int | None = None
    feedback_score: Decimal | None = None
    ships_internationally: bool = False
    shipping_policy: dict[str, dict[str, object]] | None = None
