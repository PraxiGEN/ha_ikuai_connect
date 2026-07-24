"""iKuai Connect 按钮传感器平台."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Final

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import translation
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import IkuaiCoordinator

@dataclass(frozen=True, kw_only=True)
class IkuaiButtonEntityDescription(ButtonEntityDescription):
    """描述按钮动作."""
    action_type: str 

# 按钮实体定义
BUTTON_TYPES: Final[tuple[IkuaiButtonEntityDescription, ...]] = (
    IkuaiButtonEntityDescription(
        key="reboot",
        name="Reboot Router",
        translation_key="reboot",
        icon="mdi:restart",
        device_class=ButtonDeviceClass.RESTART,
        action_type="reboot_main",
    ),
    IkuaiButtonEntityDescription(
        key="check_upgrade",
        name="Check Firmware Update",
        translation_key="check_update",
        icon="mdi:update",
        action_type="check_upgrade",
    ),
    IkuaiButtonEntityDescription(
        key="start_upgrade",
        name="Start Firmware Upgrade",
        translation_key="start_upgrade",
        icon="mdi:cloud-download",
        action_type="start_upgrade",
    ),
    IkuaiButtonEntityDescription(
        key="create_backup",
        name="Backup System Configuration",
        translation_key="create_backup",
        icon="mdi:database-export",
        action_type="backup",
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai Connect buttons from a config entry."""
    coordinator: IkuaiCoordinator = entry.runtime_data

    # 使用描述符批量注册
    async_add_entities(
        IkuaiButton(coordinator, description)
        for description in BUTTON_TYPES
    )

class IkuaiButton(CoordinatorEntity[IkuaiCoordinator], ButtonEntity):
    """iKuai 统一按钮实现 (支持主设备与维护子设备)."""

    entity_description: IkuaiButtonEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self, 
        coordinator: IkuaiCoordinator, 
        description: IkuaiButtonEntityDescription
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gwid}_ctrl_{description.key}"
        if description.action_type == "reboot_main":
            self._attr_device_info = coordinator.device_info
        else:
            self._attr_device_info = coordinator.maintenance_device_info

    async def async_press(self) -> None:
        """根据 action_type 执行 API 动作并发送通知."""
        action = self.entity_description.action_type
        api = self.coordinator.api

        LOGGER.debug("执行 iKuai 动作: %s", action)

        try:
            # 1. 调用 API 执行动作
            if action == "reboot_main":
                await api.trigger_immediate_reboot()
            elif action == "check_upgrade":
                await api.check_upgrade()
            elif action == "start_upgrade":
                await api.start_upgrade()
            elif action == "backup":
                await api.trigger_backup()

            # 发送翻译后的系统通知
            await self._send_notification(action)
            # 针对异步耗时操作，延迟刷新数据
            if action in ["start_upgrade", "backup", "check_upgrade"]:
                await asyncio.sleep(2)
                await self.coordinator.async_request_refresh()

        except Exception as err:
            LOGGER.error("iKuai 按钮动作 [%s] 执行失败: %s", action, err)

    async def _send_notification(self, action: str) -> None:
        """从翻译文件动态抓取消息并发送."""
        lang = self.hass.config.language
        # 抓取当前集成的所有通知类翻译
        translations = await translation.async_get_translations(
            self.hass, lang, "notification", [DOMAIN]
        )
        
        msg_key = f"component.{DOMAIN}.notification.{action}_msg"
        message = translations.get(msg_key, f"Action {action} completed.")

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "iKuai Connect",
                "message": message,
                "notification_id": f"ikuai_{action}",
            },
            blocking=False
        )