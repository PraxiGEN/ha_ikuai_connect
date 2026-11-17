"""iKuai Connect 开关传感器平台"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import translation
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IkuaiCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai MAC switches."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    # 记录当前已经在内存中运行的 Unique ID，防止重复实例化
    added_unique_ids: set[str] = set()

    @callback
    def _async_manage_entities() -> None:
        """增量添加：路由器上出现新 MAC 规则时创建对应实体.

        实体注册后恒定：规则被删除后实体转为 unavailable（见 available），
        规则重新出现即自动恢复。此处不做任何删除——API 降级返回空数据时
        仅表现为实体暂不可用，绝不因数据抖动误删实体。
        """
        security_data = coordinator.data.get("security", {})
        rules_data = security_data.get("mac_rules", {})
        new_entities = []
        for rid in rules_data:
            # 统一使用 gwid 构造 UID
            uid = f"{coordinator.gwid}_sec_macrule_{rid}"
            if uid not in added_unique_ids:
                new_entities.append(IkuaiMacRuleSwitch(coordinator, rid, uid))
                added_unique_ids.add(uid)

        if new_entities:
            async_add_entities(new_entities)

    # 初次加载执行一次管理
    _async_manage_entities()
    # 绑定监听：每当协调器数据更新时，增量添加新规则实体
    entry.async_on_unload(coordinator.async_add_listener(_async_manage_entities))

class IkuaiMacRuleSwitch(CoordinatorEntity[IkuaiCoordinator], SwitchEntity):
    """动态 MAC 规则开关类."""

    _attr_has_entity_name = True
    _attr_translation_key = "mac_rule"

    def __init__(self, coordinator: IkuaiCoordinator, rule_id: str, uid: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._rule_id = str(rule_id)
        self._attr_unique_id = uid
        self._attr_device_info = coordinator.security_device_info

        self._labels = {
            "every_week": "Every {weekdays}",
            "specific_date": "Specific Date",
            "all_day": "All Day",
            "permanent": "Permanent"
        }

    async def async_added_to_hass(self) -> None:
        """当实体被添加至系统时加载本地化语言."""
        await super().async_added_to_hass()
        
        lang = self.hass.config.language
        translations = await translation.async_get_translations(self.hass, lang, "entity", [DOMAIN])
        
        base_path = f"component.{DOMAIN}.entity.switch.mac_rule.state_attributes"
        mapping = {
            "every_week": f"{base_path}.schedule.state.every_week",
            "specific_date": f"{base_path}.schedule.state.specific_date",
            "all_day": f"{base_path}.schedule.state.all_day",
            "permanent": f"{base_path}.expires.state.permanent",
        }
        
        for key, path in mapping.items():
            if path in translations:
                self._labels[key] = translations[path]

    @property
    def available(self) -> bool:
        """规则仍在路由器上时可用；规则被删除后实体转为 unavailable."""
        if not self.coordinator.data:
            return False
        rules = self.coordinator.data.get("security", {}).get("mac_rules", {})
        return self._rule_id in rules

    @property
    def name(self) -> str | None:
        """从数据中获取规则名称 (tagname)."""
        rule = self.coordinator.data.get("security", {}).get("mac_rules", {}).get(self._rule_id, {})
        return rule.get("tagname")

    @property
    def is_on(self) -> bool:
        """获取当前规则状态."""
        rule = self.coordinator.data.get("security", {}).get("mac_rules", {}).get(self._rule_id, {})
        return rule.get("enabled") == "yes"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """开启规则."""
        await self.coordinator.api.toggle_mac_rule(int(self._rule_id), True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """关闭规则."""
        await self.coordinator.api.toggle_mac_rule(int(self._rule_id), False)
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """返回详细属性."""
        rule = self.coordinator.data.get("security", {}).get("mac_rules", {}).get(self._rule_id, {})
        if not rule:
            return {}

        # 处理时间计划描述
        time_rules = rule.get("time", {}).get("custom", [])
        formatted_times = []
        for t in time_rules:
            if t.get("type") == "weekly":
                # 在 Python 中手动拼接： "每周" + "12345"
                prefix = self._labels.get("every_week", "Weekly")
                formatted_times.append(f"{prefix}{t.get('weekdays')}")
            else:
                prefix = self._labels.get("specific_date", "Date")
                formatted_times.append(f"{prefix} {t.get('start_time')}-{t.get('end_time')}")

        # 处理过期时间
        expires_val = rule.get("expires", 0)
        expires_label = self._labels["permanent"] if expires_val == 0 else expires_val

        return {
            "mac_address": rule.get("mac"),
            "terminal_name": rule.get("termname"),
            "comment": rule.get("comment"),
            "schedule": "; ".join(formatted_times) if formatted_times else self._labels["all_day"],
            "expires": expires_label,
            "rule_id": self._rule_id
        }