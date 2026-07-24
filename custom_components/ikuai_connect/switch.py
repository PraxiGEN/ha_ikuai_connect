"""iKuai Connect 开关传感器平台"""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, translation
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
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
        """动态管理实体的回调函数：增量添加与物理删除."""
        # 从安全数据块获取规则
        security_data = coordinator.data.get("security", {})
        rules_data = security_data.get("mac_rules", {})
        ent_reg = er.async_get(hass)
        new_entities = []
        # 增量添加逻辑
        for rid in rules_data:
            # 统一使用 gwid 构造 UID
            uid = f"{coordinator.gwid}_sec_macrule_{rid}"
            if uid not in added_unique_ids:
                # 直接创建对象，并将生成的 uid 传入类中
                new_entities.append(IkuaiMacRuleSwitch(coordinator, rid, uid))
                added_unique_ids.add(uid)
        
        if new_entities:
            async_add_entities(new_entities)

        # 获取当前集成实例名下的所有实体记录
        entity_entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        # 计算当前 API 返回的所有合法 UID 集合
        current_valid_uids = {f"{coordinator.gwid}_sec_macrule_{rid}" for rid in rules_data}
        
        for entity in entity_entries:
            # 只处理本平台(switch)且符合特定格式的实体
            if entity.domain == "switch" and "_sec_macrule_" in entity.unique_id:
                if entity.unique_id not in current_valid_uids:
                    LOGGER.info("注销已移除的 MAC 规则实体: %s", entity.entity_id)
                    ent_reg.async_remove(entity.entity_id)
                    if entity.unique_id in added_unique_ids:
                        added_unique_ids.remove(entity.unique_id)

    # 初次加载执行一次管理
    _async_manage_entities()
    # 绑定监听：每当协调器数据更新时，触发动态管理
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
                formatted_times.append(self._labels["every_week"].format(weekdays=t.get('weekdays')))
            else:
                formatted_times.append(f"{self._labels['specific_date']} {t.get('start_time')}-{t.get('end_time')}")

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