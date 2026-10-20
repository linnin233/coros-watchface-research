#!/usr/bin/env bash
# 把宿主机真实蓝牙适配器桥接给 Android 模拟器。
#
# 需要 root（HCI_CHANNEL_USER 要求 CAP_NET_ADMIN）。
# 注意：桥接期间系统蓝牙（bluetoothctl / 蓝牙耳机）不可用，Ctrl+C 退出后恢复。
#
# usage: sudo ./bridge_bluetooth.sh [端口] [hci编号]
set -euo pipefail

PORT="${1:-8877}"
HCI="${2:-0}"
BUMBLE="${BUMBLE_BIN:-bumble-hci-bridge}"

if [ "$(id -u)" -ne 0 ]; then
    echo '必须以 root 运行：sudo ./bridge_bluetooth.sh' >&2
    exit 1
fi

echo '== 停止内核蓝牙栈'
systemctl stop bluetooth 2>/dev/null || true
sleep 1

echo '== 关闭适配器（否则 HCI_CHANNEL_USER 报 EBUSY）'
btmgmt power off >/dev/null 2>&1 || true
sleep 1

echo "== 启动桥接 端口=$PORT hci=$HCI"
echo '现在另开一个终端启动模拟器：'
echo "  emulator -avd <AVD> -packet-streamer-endpoint 127.0.0.1:$PORT \\"
echo '           -feature -WiFiPacketStream,-Uwb'
echo
echo '退出后如需恢复系统蓝牙：sudo systemctl start bluetooth'
echo

exec "$BUMBLE" "android-netsim:127.0.0.1:$PORT,mode=controller" "hci-socket:$HCI"
