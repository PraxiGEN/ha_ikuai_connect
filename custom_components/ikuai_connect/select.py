"""iKuai Connect 选择器平台."""
from __future__ import annotations

from typing import Final

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER, MAC_ACL_MODES, MAC_ACL_MODES_REVERSE
from .coordinator import IkuaiCoordinator

SELECT_TYPES: Final[tuple[SelectEntityDescription, ...]] = (
    SelectEntityDescription(
        key="mac_acl_mode",
        name="Global Access Control Mode",
        translation_key="mac_acl_mode",
        icon="mdi:shield-check",
        options=list(MAC_ACL_MODES.values()), # ["blacklist", "whitelist"]
        entity_category=EntityCategory.CONFIG, # 归类为配置项
    ),
)

async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up iKuai Connect select entities."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    
    async_add_entities(
        IkuaiMacModeSelect(coordinator, description) 
        for description in SELECT_TYPES
    )


class IkuaiMacModeSelect(CoordinatorEntity[IkuaiCoordinator], SelectEntity):
    """MAC 访问控制模式选择器实现."""

    entity_description: SelectEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self, 
        coordinator: IkuaiCoordinator, 
        description: SelectEntityDescription
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gwid}_mac_mode_{description.key}"
        self._attr_device_info = coordinator.security_device_info

    @property
    def current_option(self) -> str | None:
        """从协调器数据中获取当前模式字符串."""
        security_data = self.coordinator.data.get("security", {})
        mode_code = security_data.get("mac_mode_code", 0)
        return MAC_ACL_MODES.get(mode_code, "blacklist")

    async def async_select_option(self, option: str) -> None:
        """更改路由器模式并执行乐观更新."""
        mode_code = MAC_ACL_MODES_REVERSE.get(option, 0)
        LOGGER.debug("正在切换 iKuai 访问控制模式至: %s (code: %s)", option, mode_code)
        await self.coordinator.api.set_mac_mode(mode_code)
        if "security" in self.coordinator.data:
            self.coordinator.data["security"]["mac_mode_code"] = mode_code
        await self.coordinator.async_request_refresh()