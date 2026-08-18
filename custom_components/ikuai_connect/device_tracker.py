"""iKuai Connect 设备追踪平台."""
from __future__ import annotations

from homeassistant.components.device_tracker import BaseScannerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER, CONF_TRACKER_CONFIG
from .coordinator import IkuaiCoordinator
from .helpers import normalize_mac

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai trackers."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    # 记录当前已经在内存中运行的实体的 Unique ID
    added_unique_ids: set[str] = set()

    @callback
    def _async_manage_entities() -> None:
        """动态管理追踪实体：增量添加与物理删除."""
        tracker_config = entry.options.get(CONF_TRACKER_CONFIG) or entry.data.get(CONF_TRACKER_CONFIG, {})
        ent_reg = er.async_get(hass)
        new_entities = []
        current_configured_uids = set()
        # 增量添加逻辑
        for mac, conf in tracker_config.items():
            # 统一使用小写无冒号 MAC + gwid
            mac_clean = normalize_mac(mac).replace(":", "")
            uid = f"{coordinator.gwid}_track_{mac_clean}"
            current_configured_uids.add(uid)

            if uid not in added_unique_ids:
                new_entities.append(IkuaiTracker(coordinator, normalize_mac(mac), conf, uid))
                added_unique_ids.add(uid)

        if new_entities:
            async_add_entities(new_entities, True)

        # 自动清理逻辑 (从 HA 注册表中彻底删除已取消勾选的设备)
        entity_entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        for entity in entity_entries:
            if entity.domain == "device_tracker" and "_track_" in entity.unique_id:
                if entity.unique_id not in current_configured_uids:
                    LOGGER.info("正在彻底注销移除的追踪实体: %s", entity.entity_id)
                    ent_reg.async_remove(entity.entity_id)
                    if entity.unique_id in added_unique_ids:
                        added_unique_ids.remove(entity.unique_id)

    # 初次加载执行
    _async_manage_entities()
    # 绑定监听：每当协调器数据更新时，触发动态管理
    entry.async_on_unload(coordinator.async_add_listener(_async_manage_entities))

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