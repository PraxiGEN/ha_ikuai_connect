"""iKuai Connect 传感器平台."""
from __future__ import annotations

import re
from typing import Final, Callable, Any
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTime,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .coordinator import IkuaiCoordinator

@dataclass(frozen=True, kw_only=True)
class IkuaiSensorEntityDescription(SensorEntityDescription):
    """自定义描述符：增加数据提取和属性提取函数."""
    value_fn: Callable[[dict[str, Any]], Any] | None = None
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None

def _short_version(raw: Any) -> Any:
    """从版本串中提取短版本号。

    例如 '4.0.307-beta x64 Build202608051709' -> '4.0.307'；
    若已是纯短版本（如 '4.0.307'）则原样返回；空值返回 None。
    """
    if not raw:
        return None
    m = re.search(r"\d+(?:\.\d+){1,3}", str(raw))
    return m.group(0) if m else str(raw)

# 主设备 (Router Core) 传感器定义
SYSTEM_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="cpu_load",
        name="CPU Load",
        translation_key="cpu_load",
        icon="mdi:cpu-64-bit",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("cpu_load"),
    ),
    IkuaiSensorEntityDescription(
        key="memory_usage",
        name="Memory Usage",
        translation_key="memory_usage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("memory_usage"),
        attr_fn=lambda d: d.get("system", {}).get("memory_detail", {}),
    ),
    IkuaiSensorEntityDescription(
        key="online_users",
        name="Total Online Devices",
        translation_key="online_users",
        icon="mdi:account-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("online_users"),
        attr_fn=lambda d: d.get("system", {}).get("online_user_detail", {}),
    ),
    IkuaiSensorEntityDescription(
        key="connection_count",
        name="Total Connection Count",
        translation_key="connection_count",
        icon="mdi:lan-connect",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("connection_count"),
        attr_fn=lambda d: {
            "tcp": d.get("system", {}).get("connect_detail", {}).get("tcp"),
            "udp": d.get("system", {}).get("connect_detail", {}).get("udp"),
            "icmp": d.get("system", {}).get("connect_detail", {}).get("icmp"),
            "ipv6": d.get("system", {}).get("connect_detail", {}).get("ipv6"),
        },
    ),
    IkuaiSensorEntityDescription(
        key="sys_upload",
        name="System Upload Speed",
        translation_key="sys_upload_speed",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("upload"),
        attr_fn=lambda d: {"ipv6_upload_speed": d.get("system", {}).get("v6_stats", {}).get("upload_speed_v6")},
    ),
    IkuaiSensorEntityDescription(
        key="sys_download",
        name="System Download Speed",
        translation_key="sys_download_speed",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("download"),
        attr_fn=lambda d: {"ipv6_download_speed": d.get("system", {}).get("v6_stats", {}).get("download_speed_v6")},
    ),
    IkuaiSensorEntityDescription(
        key="sys_total_up",
        name="System Total Upload",
        translation_key="sys_total_up",
        icon="mdi:upload",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.get("system", {}).get("total_up"),
        attr_fn=lambda d: {"ipv6_total_upload": d.get("system", {}).get("v6_stats", {}).get("total_upload_v6")},
    ),
    IkuaiSensorEntityDescription(
        key="sys_total_down",
        name="System Total Download",
        translation_key="sys_total_down",
        icon="mdi:download",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.get("system", {}).get("total_down"),
        attr_fn=lambda d: {"ipv6_total_download": d.get("system", {}).get("v6_stats", {}).get("total_download_v6")},
    ),
    IkuaiSensorEntityDescription(
        key="uptime",
        name="System Uptime",
        translation_key="uptime",
        icon="mdi:clock-time-eight",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda d: d.get("system", {}).get("uptime"),
    ),
    IkuaiSensorEntityDescription(
        key="temperature",
        name="System Temperature",
        translation_key="temperature",
        icon="mdi:thermometer",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("temperature"),
    ),
    IkuaiSensorEntityDescription(
        key="ap_online",
        name="Wireless AP Online",
        translation_key="ap_online",
        icon="mdi:access-point-check",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("ap_online"),
        attr_fn=lambda d: d.get("system", {}).get("wireless_detail", {}),
    )
)

# 网口级传感器 (Interface) 模板
INTERFACE_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="upload_speed",
        name="Upload Speed",
        translation_key="upload_speed",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="download_speed",
        name="Download Speed",
        translation_key="download_speed",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="total_up",
        name="Total Upload",
        translation_key="total_up",
        icon="mdi:upload",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    IkuaiSensorEntityDescription(
        key="total_down",
        name="Total Download",
        icon="mdi:download",
        translation_key="total_down",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)

# WAN 口专属传感器（连接状态 / IPv4 地址），挂接口监控子设备
# 归为诊断类：默认不出现在概览，仅在实体注册表/诊断页可见
WAN_STATUS_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="connection_status",
        name="WAN Connection Status",
        translation_key="wan_connection_status",
        icon="mdi:wan",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: "online" if d.get("connected") else "offline",
        attr_fn=lambda d: {
            "protocol": d.get("protocol"),
            "ipv4": d.get("ip"),
            "gateway": d.get("gateway"),
            "auto_switch": d.get("auto_switch"),
            "errmsg": d.get("errmsg"),
            "parent_interface": d.get("parent_interface"),
        },
    ),
    IkuaiSensorEntityDescription(
        key="ipv4_addr",
        name="WAN IPv4 Address",
        translation_key="wan_ipv4_addr",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.get("ip") or "—",
    ),
)

# WAN 口 IPv6 流量传感器（分口），挂接口监控子设备
WAN_V6_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="v6_upload_speed", name="IPv6 Upload Speed", translation_key="wan_v6_upload_speed",
        icon="mdi:upload-network", device_class=SensorDeviceClass.DATA_RATE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2, state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="v6_download_speed", name="IPv6 Download Speed", translation_key="wan_v6_download_speed",
        icon="mdi:download-network", device_class=SensorDeviceClass.DATA_RATE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2, state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="v6_total_up", name="IPv6 Total Upload", translation_key="wan_v6_total_up",
        icon="mdi:upload", device_class=SensorDeviceClass.DATA_SIZE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2, state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    IkuaiSensorEntityDescription(
        key="v6_total_down", name="IPv6 Total Download", translation_key="wan_v6_total_down",
        icon="mdi:download", device_class=SensorDeviceClass.DATA_SIZE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2, state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    IkuaiSensorEntityDescription(
        key="v6_conn", name="IPv6 Connection Count", translation_key="wan_v6_conn",
        icon="mdi:ip-network", state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
)

# 多 WAN 负载均衡快照（只读诊断），挂接口监控子设备
WAN_BALANCE_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="balance_snapshot", name="WAN Load Balance Snapshot",
        translation_key="wan_balance_snapshot", icon="mdi:scale-balance",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.get("wan_balance", {}).get("_state"),
        attr_fn=lambda d: d.get("wan_balance", {}).get("lines", {}),
    ),
)

# 维护管理 (Maintenance) 定义
MAINTENANCE_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="firmware_version",
        name="Firmware Version",
        translation_key="firmware_version",
        icon="mdi:chip",
        # 状态取「当前版本」短号（如 4.0.111），来源为 /api/v4.0/monitoring/system 的
        # sysinfo.verinfo.version；该字段本就是干净短版本号，缺失时回退用 _short_version
        # 从 verinfo.verstring 中提取（如 '4.0.111-beta x64 ...' -> '4.0.111'）。
        value_fn=lambda d: (d.get("system", {}).get("verinfo", {}) or {}).get("version") \
            or _short_version((d.get("system", {}).get("verinfo", {}) or {}).get("verstring")),
        # 属性：版本全部信息（来自 verinfo，扁平化为顶层属性，便于翻译显示中文名）
        attr_fn=lambda d: {
            "version": (vi := d.get("system", {}).get("verinfo", {}) or {}).get("version"),
            "verstring": vi.get("verstring"),
            "modelname": vi.get("modelname"),
            "build_date": vi.get("build_date"),
            "arch": vi.get("arch"),
            "sysbit": vi.get("sysbit"),
        },
    ),
    IkuaiSensorEntityDescription(
        key="upgrade_status",
        name="Firmware Upgrade Status",
        translation_key="upgrade_status",
        icon="mdi:update",
        value_fn=lambda d: d.get("maintenance", {}).get("upgrade_display_state"),
        attr_fn=lambda d: d.get("maintenance", {}).get("upgrade_detail", {}),
    ),
    IkuaiSensorEntityDescription(
        key="backup_status",
        name="Latest Backup File",
        translation_key="latest_backup",
        icon="mdi:database-check",
        value_fn=lambda d: d.get("backup", {}).get("latest_filename"),
        attr_fn=lambda d: d.get("backup", {}).get("detail", {}),
    ),
)

# 存储硬盘 (Storage) 模板
DISK_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="disk_physical_size",
        name="Total Disk Capacity",
        translation_key="disk_total_capacity",
        icon="mdi:database",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="disk_usage_rate",
        name="Overall Usage Rate",
        translation_key="disk_usage_rate",
        icon="mdi:chart-arc",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="disk_used_capacity",
        name="Used Disk Capacity",
        translation_key="disk_used_capacity",
        icon="mdi:database-minus",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai Connect sensors."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    # 处理【主设备】
    for description in SYSTEM_SENSORS:
        entities.append(IkuaiSystemSensor(coordinator, description))

    # 处理【接口监控管理】子设备
    interfaces = coordinator.data.get("interfaces", {})
    for iface_name, iface_data in interfaces.items():
        for description in INTERFACE_SENSORS:
            entities.append(IkuaiIfaceSensor(coordinator, description, iface_name))

    # 仅对 WAN 拨号线路（含聚合父口 wan* 与 adsl/vwan 子线路）生成，跳过 lan 等
    wan_ifaces = [k for k, v in interfaces.items() if v.get("is_wan_line")]
    for iface_name in wan_ifaces:
        iface_data = interfaces[iface_name]
        # WAN 连接状态 / IPv4 地址：每个 WAN 线路都生成（断线时仍有诊断价值）
        for description in WAN_STATUS_SENSORS:
            entities.append(IkuaiIfaceSensor(coordinator, description, iface_name))
        if iface_data.get("has_v6"):
            for description in WAN_V6_SENSORS:
                entities.append(IkuaiIfaceSensor(coordinator, description, iface_name))
    # 多 WAN 负载均衡快照（诊断实体）
    for description in WAN_BALANCE_SENSORS:
        entities.append(IkuaiWanBalanceSensor(coordinator, description))

    # 处理【升级与备份管理】子设备
    for description in MAINTENANCE_SENSORS:
        entities.append(IkuaiMaintenanceSensor(coordinator, description))

    # 处理【存储管理】子设备 (基于物理磁盘型号)
    disks_data = coordinator.data.get("disks", {})
    for disk_id in disks_data:
        for description in DISK_SENSORS:
            entities.append(IkuaiDiskSensor(coordinator, description, disk_id))

    async_add_entities(entities, True)

class IkuaiSystemSensor(CoordinatorEntity[IkuaiCoordinator], SensorEntity):
    """主设备负载传感器."""
    entity_description: IkuaiSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gwid}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self):
        if not self.coordinator.data: return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data or not self.entity_description.attr_fn:
            return {}
        return self.entity_description.attr_fn(self.coordinator.data)

class IkuaiIfaceSensor(CoordinatorEntity[IkuaiCoordinator], SensorEntity):
    """网络接口监控传感器 (子设备)."""
    entity_description: IkuaiSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator, description, iface_name):
        super().__init__(coordinator)
        self.entity_description = description
        self._iface_name = iface_name
        self._attr_translation_placeholders = {"iface": iface_name}
        self._attr_unique_id = f"{coordinator.gwid}_iface_{iface_name}_{description.key}"
        self._attr_device_info = coordinator.iface_mgmt_device_info

    @property
    def native_value(self):
        if not self.coordinator.data: return None
        iface_data = self.coordinator.data.get("interfaces", {}).get(self._iface_name, {})
        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(iface_data)
        return iface_data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data or not self.entity_description.attr_fn:
            return {}
        iface_data = self.coordinator.data.get("interfaces", {}).get(self._iface_name, {})
        return self.entity_description.attr_fn(iface_data)

class IkuaiWanBalanceSensor(CoordinatorEntity[IkuaiCoordinator], SensorEntity):
    """多 WAN 负载均衡快照（接口监控子设备，诊断类）."""
    entity_description: IkuaiSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gwid}_wan_balance_{description.key}"
        self._attr_device_info = coordinator.iface_mgmt_device_info

    @property
    def native_value(self):
        if not self.coordinator.data: return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data or not self.entity_description.attr_fn:
            return {}
        return self.entity_description.attr_fn(self.coordinator.data)

class IkuaiMaintenanceSensor(CoordinatorEntity[IkuaiCoordinator], SensorEntity):
    """升级与备份管理 (子设备)."""
    entity_description: IkuaiSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gwid}_maint_{description.key}"
        self._attr_device_info = coordinator.maintenance_device_info

    @property
    def native_value(self):
        if not self.coordinator.data: return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data or not self.entity_description.attr_fn:
            return {}
        return self.entity_description.attr_fn(self.coordinator.data)

class IkuaiDiskSensor(CoordinatorEntity[IkuaiCoordinator], SensorEntity):
    """磁盘管理传感器."""
    entity_description: IkuaiSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: IkuaiCoordinator, description: IkuaiSensorEntityDescription, disk_id: str) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._disk_id = disk_id
        
        disk_data = coordinator.data["disks"].get(disk_id, {})
        model = disk_data.get("base_info", {}).get("model", disk_id)
        
        self._attr_unique_id = f"{coordinator.gwid}_disk_{disk_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.host}_disk_{disk_id}")},
            name=f"存储: {model}",
            manufacturer="iKuai",
            model=model,
            via_device=(DOMAIN, coordinator.host),
        )

    @property
    def native_value(self):
        if not self.coordinator.data: return None
        disk_data = self.coordinator.data["disks"].get(self._disk_id, {}).get("state", {})
        return disk_data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data: return {}
        disk_data = self.coordinator.data["disks"].get(self._disk_id, {})
        if self.entity_description.key == "disk_physical_size":
            return disk_data.get("base_info", {})
        if self.entity_description.key == "disk_used_capacity":
            return {"partitions": disk_data.get("partitions", [])}
        return {}