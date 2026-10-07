from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


class Platform(str, Enum):
    OLX = "olx"
    PROM = "prom"


class ProductItem(BaseModel):
    id: str = ""
    platform: Platform
    external_id: str
    title: str
    price: float
    currency: str = "UAH"
    url: str
    image_url: Optional[str] = None
    location: Optional[str] = None
    is_promoted: bool = False
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="before")
    @classmethod
    def set_composite_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            platform_val = data.get("platform")
            if isinstance(platform_val, Platform):
                platform_val = platform_val.value
            external_id = data.get("external_id")
            if not data.get("id") and platform_val and external_id:
                data["id"] = f"{platform_val}:{external_id}"
        return data
