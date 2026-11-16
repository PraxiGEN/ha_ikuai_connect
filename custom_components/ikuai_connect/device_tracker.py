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
    added_unique_ids: set[str] = set()

    @callback
    def _async_manage_entities() -> None:
        """动态管理追踪实体：增量添加，孤儿实体降级为禁用."""
        tracker_config = entry.options.get(CONF_TRACKER_CONFIG) or entry.data.get(CONF_TRACKER_CONFIG, {})
        ent_reg = er.async_get(hass)
        # 注：此处不能提前 return——已禁用的实体仍需在 MAC 回到配置时被重新启用
        current_configured_uids = set()
        new_entities = []
        for mac, conf in tracker_config.items():
            mac_clean = normalize_mac(mac).replace(":", "")
            uid = f"{coordinator.gwid}_track_{mac_clean}"
            current_configured_uids.add(uid)

            if uid not in added_unique_ids:
                new_entities.append(IkuaiTracker(coordinator, normalize_mac(mac), conf, uid))
                added_unique_ids.add(uid)

        if new_entities:
            async_add_entities(new_entities, True)

        # 配置为空时无法区分「用户清空」与「读取失败」，一律不动注册表
        if not current_configured_uids:
            LOGGER.debug("追踪配置为空，跳过孤立实体清理")
            return

        for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if entity.domain != "device_tracker" or "_track_" not in entity.unique_id:
                continue
            # 已被用户手动禁用/删除的，尊重用户选择，不做任何处理
            if entity.disabled_by not in (None, er.RegistryEntryDisabler.INTEGRATION):
                continue
            if entity.unique_id in current_configured_uids:
                # 重新出现在配置中：撤销此前的自动禁用
                if entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                    ent_reg.async_update_entity(entity.entity_id, disabled_by=None)
                continue
            LOGGER.warning(
                "追踪实体 %s 已不在配置中，改为禁用（不删除，可随时恢复）", entity.entity_id
            )
            ent_reg.async_update_entity(
                entity.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
            )
            added_unique_ids.discard(entity.unique_id)

    _async_manage_entities()
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