"""iKuai Connect 常量."""
from __future__ import annotations

import logging
from typing import Final
from homeassistant.const import Platform

DOMAIN: Final = "ikuai_connect"
LOGGER = logging.getLogger(__package__)
# 定义受支持的平台
PLATFORMS: Final = [
    Platform.SENSOR, 
    Platform.DEVICE_TRACKER, 
    Platform.BUTTON, 
    Platform.EVENT, 
    Platform.SELECT,
    Platform.SWITCH
]

CONF_TRACKER_CONFIG: Final = "tracker_config"
CONF_OFFLINE_GRACE_PERIOD: Final = "offline_grace_period"

DEFAULT_SCAN_INTERVAL = 15
DEFAULT_OFFLINE_GRACE_PERIOD = 1 # 全局离线判定缓冲时间，默认 1（分钟单位）

# MAC 访问控制模式映射
MAC_ACL_MODES = {0: "blacklist", 1: "whitelist"}
MAC_ACL_MODES_REVERSE = {v: k for k, v in MAC_ACL_MODES.items()}