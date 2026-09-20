from timeslips_local_api.errors import NotImplementedCapability
from timeslips_local_api.models import SlipCreate, SlipPatch


class TsimportSlipWriter:
    """TSImport is a GUI importer and must not target a live production database."""

    def create(self, cur, payload: SlipCreate, con) -> int:
        raise NotImplementedCapability("write-backend tsimport")

    def update(self, cur, slip_id: int, patch: SlipPatch, con) -> int:
        raise NotImplementedCapability("write-backend tsimport")

    def delete(self, cur, slip_id: int, con) -> None:
        raise NotImplementedCapability("write-backend tsimport")
