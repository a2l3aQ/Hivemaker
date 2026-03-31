import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional
from pydantic import BaseModel


class Meta(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    authors: Optional[list[str]] = None
    version: Optional[str] = None
    tags: Optional[list[str]] = None


class BwsV1AlphaCapability(BaseModel):
    api_root: Optional[str] = None          # default: "bws/v1-alpha"
    move_time_limit: bool = False
    evaluation_time_limit: bool = False
    config: Optional[dict] = None           # {} = supported, {"dynamic": True} = dynamic
    free_setup: bool = False
    move_skips: bool = False
    dual_sided: bool = False
    free_move_order: bool = False
    evaluation: bool = False
    resettable_state: bool = False
    interruptible: bool = False


class BasicWebsocketVersions(BaseModel):
    model_config = {"populate_by_name": True}
    v1_alpha: Optional[BwsV1AlphaCapability] = None

    def model_dump(self, **kwargs):
        # Serialize v1_alpha as "v1-alpha" (hyphen, not underscore)
        d = {}
        if self.v1_alpha is not None:
            d["v1-alpha"] = self.v1_alpha.model_dump(exclude_none=True)
        return d


class BasicWebsocketCapability(BaseModel):
    versions: BasicWebsocketVersions


class Capabilities(BaseModel):
    meta: Optional[Meta] = None
    basic_websocket: Optional[BasicWebsocketCapability] = None

    def model_dump(self, **kwargs):
        d: dict = {}
        if self.meta:
            d["meta"] = self.meta.model_dump(exclude_none=True)
        if self.basic_websocket:
            d["basic_websocket"] = {
                "versions": self.basic_websocket.versions.model_dump()
            }
        return d


def default_capabilities(bws: BwsV1AlphaCapability | None = None) -> Capabilities:
    """Build a capabilities object declaring bws v1-alpha support."""
    return Capabilities(
        basic_websocket=BasicWebsocketCapability(
            versions=BasicWebsocketVersions(v1_alpha=bws or BwsV1AlphaCapability())
        )
    )