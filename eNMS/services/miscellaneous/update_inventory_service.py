from sqlalchemy import Column, ForeignKey, Integer, PickleType
from sqlalchemy.ext.mutable import MutableDict

from eNMS.forms import service_metaform
from eNMS.forms.automation import ServiceForm
from eNMS.forms.fields import DictField
from eNMS.models import register_class
from eNMS.models.automation import Service
from eNMS.models.inventory import Device


class UpdateInventoryService(Service, metaclass=register_class):

    __tablename__ = "UpdateInventoryService"

    id = Column(Integer, ForeignKey("Service.id"), primary_key=True)
    has_targets = True
    update_dictionary = Column(MutableDict.as_mutable(PickleType), default={})

    __mapper_args__ = {"polymorphic_identity": "UpdateInventoryService"}

    def job(self, payload: dict, device: Device) -> dict:
        for property, value in self.update_dictionary.items():
            setattr(device, property, value)
        return {"success": True, "result": "properties updated"}


class UpdateInventoryForm(ServiceForm, metaclass=service_metaform):
    service_class = "UpdateInventoryService"
    update_dictionary = DictField()
