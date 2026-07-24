"""iKuai Connect 配置流实现."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import IkuaiAPI
from .const import (
    CONF_OFFLINE_GRACE_PERIOD,
    CONF_TRACKER_CONFIG,
    DEFAULT_OFFLINE_GRACE_PERIOD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
)
from .helpers import extract_name_from_label

class IkuaiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """处理 iKuai Connect 的初次配置和重新配置."""

    VERSION = 1

    def _get_login_schema(
        self, defaults: dict[str, Any] | None = None, is_reconfigure: bool = False
    ) -> vol.Schema:
        """生成登录表单 Schema."""
        if defaults is None:
            defaults = {}

        schema = {}

        # 只有在初次安装时显示集成标题
        if not is_reconfigure:
            schema[
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "iKuai Connect"))
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))

        schema.update(
            {
                vol.Required(
                    CONF_HOST, default=defaults.get(CONF_HOST, "https://10.10.10.1")
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                vol.Required(CONF_TOKEN, default=defaults.get(CONF_TOKEN)): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return vol.Schema(schema)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """处理初次安装步骤."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].rstrip("/")
            token = user_input[CONF_TOKEN]
            name = user_input[CONF_NAME]

            # 校验名称唯一性，防止 entity_id 冲突出现 _2
            current_entries = self._async_current_entries()
            for entry in current_entries:
                if entry.title == name:
                    errors[CONF_NAME] = "name_exists"
                    break

            if not errors:
                try:
                    api = IkuaiAPI(self.hass, host, token)
                    await api.get_system_info()

                    # 设置物理唯一 ID (基于 Host 地址)
                    await self.async_set_unique_id(host.lower())
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_HOST: host,
                            CONF_TOKEN: token,
                            CONF_TRACKER_CONFIG: {},
                        },
                    )
                except Exception:  # pylint: disable=broad-except
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=self._get_login_schema(user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """处理重新配置流程."""
        errors: dict[str, str] = {}
        reconfig_entry = self._get_reconfigure_entry()

        if user_input is not None:
            host = user_input[CONF_HOST].rstrip("/")
            token = user_input[CONF_TOKEN]

            try:
                api = IkuaiAPI(self.hass, host, token)
                await api.get_system_info()
                return self.async_update_reload_and_abort(
                    reconfig_entry,
                    data={
                        **reconfig_entry.data,
                        CONF_HOST: host,
                        CONF_TOKEN: token,
                    },
                )
            except Exception:  # pylint: disable=broad-except
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._get_login_schema(
                defaults={
                    CONF_HOST: reconfig_entry.data[CONF_HOST],
                    CONF_TOKEN: reconfig_entry.data[CONF_TOKEN],
                },
                is_reconfigure=True,
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> IkuaiOptionsFlowHandler:
        """获取选项流处理器."""
        return IkuaiOptionsFlowHandler()

class IkuaiOptionsFlowHandler(config_entries.OptionsFlow):
    """处理集成选项、终端追踪及高级参数."""

    def __init__(self) -> None:
        """Initialize."""
        self._selected_devices: list[str] = []
        self._discovered_map: dict[str, str] = {}
        self._temp_options: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """配置主菜单."""
        # 确保整个生命周期内 _temp_options 始终包含完整的当前配置
        if not self._temp_options:
            self._temp_options = dict(self.config_entry.options)

        if user_input is not None:
            next_action = user_input.get("manage_action", "none")

            # 合并基础设置到缓存中
            self._temp_options.update(
                {
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    CONF_OFFLINE_GRACE_PERIOD: user_input[CONF_OFFLINE_GRACE_PERIOD],
                }
            )

            if next_action == "add":
                return await self.async_step_scan()
            if next_action == "remove":
                return await self.async_step_remove()

            return self.async_create_entry(title="", data=self._temp_options)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_period = self.config_entry.options.get(
            CONF_OFFLINE_GRACE_PERIOD, DEFAULT_OFFLINE_GRACE_PERIOD
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=300)
                    ),
                    vol.Required(
                        CONF_OFFLINE_GRACE_PERIOD, default=current_period
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=30, max=3600, step=10, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required("manage_action", default="none"): SelectSelector(
                        SelectSelectorConfig(
                            options=["none", "add", "remove"],
                            translation_key="manage_action",
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """从路由器扫描当前在线终端."""
        errors: dict[str, str] = {}
        coordinator = self.config_entry.runtime_data

        if user_input is not None:
            self._selected_devices = user_input.get("devices", [])
            if not self._selected_devices:
                errors["base"] = "no_devices_selected"
            else:
                return await self.async_step_configure_devices()

        try:
            res = await coordinator.api.get_lan_devices()
            lan_list = res.get("data", [])
            # 过滤掉已经在追踪列表中的设备
            existing_trackers = self._temp_options.get(CONF_TRACKER_CONFIG, {})

            self._discovered_map = {}
            for item in lan_list:
                mac = item.get("mac", "").lower()
                if not mac or mac in existing_trackers:
                    continue

                ip = item.get("ip_addr", "")
                # 优先级逻辑：终端名 > 型号 > 备注
                termname = item.get("termname", "")
                model = item.get("client_model", "")
                comment = extract_name_from_label(item.get("comment", ""))
                name_priority = termname or model or comment

                label = (
                    f"{mac} | {ip} ({name_priority})" if name_priority else f"{mac} | {ip}"
                )
                self._discovered_map[mac] = label

            if not self._discovered_map:
                errors["base"] = "no_new_devices_found"
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.error("Scan error: %s", err)
            errors["base"] = "cannot_connect"

        device_options = [
            {"value": mac, "label": label}
            for mac, label in self._discovered_map.items()
        ]

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema({
                vol.Optional("devices"): SelectSelector(
                    SelectSelectorConfig(
                        options=device_options,
                        multiple=True, # 允许多选
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }),
            errors=errors,
        )

    async def async_step_configure_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """循环迭代配置每一个选中的设备."""
        if not self._selected_devices:
            # 所有设备配完，保存
            return self.async_create_entry(title="", data=self._temp_options)

        current_mac = self._selected_devices[0]

        if user_input is not None:
            tracker_config = self._temp_options.setdefault(CONF_TRACKER_CONFIG, {})
            tracker_config[current_mac.lower()] = {
                "name": user_input[CONF_NAME],
                "buffer": user_input[CONF_OFFLINE_GRACE_PERIOD],
            }
            self._temp_options[CONF_TRACKER_CONFIG] = tracker_config
            self._selected_devices.pop(0)
            # 递归调用处理下一个设备，重置 user_input
            return await self.async_step_configure_devices(user_input=None)

        label_info = self._discovered_map.get(current_mac, "")
        # 提取终端名称优先级逻辑 (匹配括号内容)
        name_match = re.search(r"\((.*?)\)", label_info)
        if name_match and name_match.group(1).strip():
            default_name = name_match.group(1).strip()
        else:
            default_name = f"Client {current_mac.replace(':', '')[-4:]}"

        return self.async_show_form(
            step_id="configure_devices",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=default_name): str,
                    vol.Required(
                        CONF_OFFLINE_GRACE_PERIOD, default=600
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=30, max=3600, unit_of_measurement="s", mode=NumberSelectorMode.BOX
                        )
                    ),
                }
            ),
            description_placeholders={
                "device": f"{default_name} ({current_mac})",
                "remaining": str(len(self._selected_devices)),
            },
        )

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """移除现有的追踪终端."""
        tracker_config = dict(self._temp_options.get(CONF_TRACKER_CONFIG, {}))

        if user_input is not None:
            for mac in user_input.get("devices_to_remove", []):
                tracker_config.pop(mac, None)
            self._temp_options[CONF_TRACKER_CONFIG] = tracker_config
            return self.async_create_entry(title="", data=self._temp_options)

        current_options = [
            {"value": mac, "label": f"{conf.get('name', mac)} ({mac})"}
            for mac, conf in tracker_config.items()
        ]

        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema({
                vol.Optional("devices_to_remove"): SelectSelector(
                    SelectSelectorConfig(
                        options=current_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                )
            }),
        )