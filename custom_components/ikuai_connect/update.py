"""iKuai 固件更新平台。"""
from __future__ import annotations

import re
from typing import Any, Final

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import IkuaiConfigEntry
from .const import LOGGER
from .coordinator import IkuaiCoordinator

UPDATE_DESCRIPTIONS: Final[tuple[UpdateEntityDescription, ...]] = (
    UpdateEntityDescription(
        key="firmware_update",
        translation_key="firmware_update",
        device_class=UpdateDeviceClass.FIRMWARE,
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: IkuaiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置 iKuai 固件更新实体。"""
    coordinator = entry.runtime_data
    async_add_entities(
        IkuaiUpdateEntity(coordinator, description)
        for description in UPDATE_DESCRIPTIONS
    )

class IkuaiUpdateEntity(CoordinatorEntity[IkuaiCoordinator], UpdateEntity):
    """iKuai 固件更新实体。"""

    entity_description: UpdateEntityDescription
    _attr_has_entity_name = True
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(
        self,
        coordinator: IkuaiCoordinator,
        description: UpdateEntityDescription,
    ) -> None:
        """初始化固件更新实体。"""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gwid}_{description.key}"
        self._attr_device_info = coordinator.maintenance_device_info
        self._warned_status: int | None = None

    @property
    def _maintenance(self) -> dict[str, Any]:
        return self.coordinator.data.get("maintenance", {})

    @property
    def _upgrade_detail(self) -> dict[str, Any]:
        return self._maintenance.get("upgrade_detail", {})

    @property
    def _status(self) -> int:
        return self._maintenance.get("upgrade_status", 0)

    @property
    def installed_version(self) -> str | None:
        return self._upgrade_detail.get("current_version")

    @property
    def latest_version(self) -> str | None:
        return self._upgrade_detail.get("latest_version") or self.installed_version

    @property
    def has_update(self) -> bool:
        latest_version = self._upgrade_detail.get("latest_version")
        return bool(latest_version and latest_version != self.installed_version)

    @property
    def in_progress(self) -> bool:
        return self._status in (1, 2)

    @property
    def update_percentage(self) -> int | None:
        if self._status != 1:
            return None
        match = re.search(
            r"(\d+)%", self._maintenance.get("upgrade_status_msg", "")
        )
        return int(match.group(1)) if match else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            k: self._upgrade_detail[k]
            for k in ("version_type", "build_date", "last_check")
        }

    async def async_release_notes(self) -> str | None:
        """返回固件更新说明。"""
        return self._upgrade_detail.get("update_content")

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """启动固件升级并刷新状态。"""
        await self.coordinator.api.start_upgrade()
        await self.coordinator.async_request_refresh()

    def _handle_coordinator_update(self) -> None:
        status = self._status
        if status < 0 and status != self._warned_status:
            LOGGER.warning(
                "iKuai 固件升级失败（%s）：%s",
                status,
                self._maintenance.get("upgrade_status_msg", ""),
            )
        self._warned_status = status if status < 0 else None
        super()._handle_coordinator_update()