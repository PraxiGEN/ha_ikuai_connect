"""iKuai Connect 设备追踪平台."""
from __future__ import annotations

from homeassistant.components.device_tracker import BaseScannerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_TRACKER_CONFIG
from .coordinator import IkuaiCoordinator
from .helpers import normalize_mac

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai trackers."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    tracker_config = entry.options.get(CONF_TRACKER_CONFIG) or entry.data.get(CONF_TRACKER_CONFIG, {})

    # 纯增量：删除只在选项流 remove 步骤内事件驱动执行，此处不清理也不监听协调器。
    new_entities = []
    for mac, conf in tracker_config.items():
        mac_clean = normalize_mac(mac).replace(":", "")
        uid = f"{coordinator.gwid}_track_{mac_clean}"
        new_entities.append(IkuaiTracker(coordinator, normalize_mac(mac), conf, uid))

    async_add_entities(new_entities, True)

class IkuaiTracker(CoordinatorEntity[IkuaiCoordinator], BaseScannerEntity):
    """iKuai 终端追踪实体（连接型：state 由 is_connected 推导 home/not_home）."""

    _attr_has_entity_name = True
    _attr_translation_key = "ikuai_tracker" 

    def __init__(self, coordinator: IkuaiCoordinator, mac: str, config: dict, uid: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._mac = normalize_mac(mac)
        self._attr_name = config.get("name")
        self._attr_unique_id = uid
        self._attr_device_info = coordinator.device_info

    @property
    def is_connected(self) -> bool:
        """判断在线状态."""
        if not self.coordinator.data:
            return False
        return self._mac in self.coordinator.data.get("clients", {})

    @property
    def source_type(self) -> SourceType:
        """指定追踪来源."""
        return SourceType.ROUTER

    @property
    def extra_state_attributes(self) -> dict:
        """返回精简后的物理属性."""
        if not self.coordinator.data:
            return {}
        
        client = self.coordinator.data.get("clients", {}).get(self._mac, {})
        if not client:
            return {"mac_address": self._mac}

        return {
            "mac_address": self._mac,
            "ip_address": client.get("ip_addr"),
            "ap_mac": client.get("apmac"),
            "uplink_addr": client.get("uplink_addr"),
        }
