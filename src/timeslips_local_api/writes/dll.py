from timeslips_local_api.errors import NotImplementedCapability
from timeslips_local_api.models import SlipCreate, SlipPatch


class DllSlipWriter:
    """Placeholder for TSDBAP32.DLL. See docs/dll-probe.md."""

    def create(self, cur, payload: SlipCreate, con) -> int:
        raise NotImplementedCapability("write-backend dll")

    def update(self, cur, slip_id: int, patch: SlipPatch, con) -> int:
        raise NotImplementedCapability("write-backend dll")

    def delete(self, cur, slip_id: int, con) -> None:
        raise NotImplementedCapability("write-backend dll")
