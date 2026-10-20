# COROS 自定义表盘研究

在 Linux 上把自制的 COROS 表盘写进手表的完整方法记录。

不需要 root 手机，不需要逆向 A5 握手，不需要手工构造 bin。

## 适用范围

- 设备：COROS PACE 4（GATT Model `COROS R4`，圆屏 390x390）
- 固件：`V 3.2106.0`
- App：`com.yf.smart.coros.dist` 4.11.6
- 宿主：Linux x86_64 + Android Emulator + Bumble

其他型号/固件未验证。

## 原理

COROS 的自定义表盘在手表侧是一份 `export.bin`，由 App 内部的
`libw4-watchface.so` 从模板 zip 转换而来。上传前 App 会做一次 A5 握手，
算法在加密的 dex 里，外部无法复现。

关键洞察是：**让 App 自己在 Android 模拟器里跑，同时把模拟器的蓝牙接到宿主机真实适配器**。
这样 App 完成全部工作，我们只替换它的输入文件。

```
自定义表盘 zip
  -> 塞进 App 私有目录 template/<id>.zip
  -> App 解压、调 libw4-watchface.so 转换、生成 export.bin
  -> App 自己做 A5 握手 + BLE 分块上传
  -> 手表
```

蓝牙桥的做法：

```
Android Emulator (guest)
    |  gRPC PacketStreamer (hci_packet)
Bumble hci_bridge  (mode=controller)
    |  HCI_CHANNEL_USER
宿主机真实蓝牙适配器
    |  BLE
手表
```

## 前置条件

- Linux，能跑 KVM 加速的 Android Emulator
- 一个蓝牙适配器（BLE 必须支持）
- 一次 `sudo`（`HCI_CHANNEL_USER` 需要 `CAP_NET_ADMIN`）
- Python 3.10+

## 快速开始

```bash
# 1. 安装 Bumble
python3 -m venv .venv-bumble
.venv-bumble/bin/pip install 'bumble[android]'

# 2. 让内核蓝牙栈释放适配器
sudo systemctl stop bluetooth
sudo btmgmt power off

# 3. 起桥接
sudo .venv-bumble/bin/bumble-hci-bridge \
     android-netsim:127.0.0.1:8877,mode=controller hci-socket:0

# 4. 启动模拟器，连到桥
emulator -avd <AVD> \
         -packet-streamer-endpoint 127.0.0.1:8877 \
         -feature -WiFiPacketStream,-Uwb

# 5. 在 guest 里装 COROS App、登录、配对手表
adb install coros.apk
adb shell cmd bluetooth_manager enable

# 6. 在 App 里创建任意一个自定义表盘，然后点一次 SEND TO WATCH
#    让它把模板下载到本地

# 7. 替换模板 zip 并重发
sudo adb root
./tools/send_to_watch.sh <template-id> my_watchface.zip
```

## 两个必须知道的坑

**proto 字段**

模拟器的 `PacketRequest` 里有两个并列字段：`hci_packet` 是蓝牙，`packet` 是 WiFi。
回包必须用 `hci_packet`。用错的话 guest 内核会报
`Bluetooth: hci0: Opcode 0x0c03 failed: -110`（HCI_RESET 超时），每 5 秒重试。

**WiFiPacketStream 必须关闭**

`-packet-streamer-endpoint` 是全局的，WiFi 也会连过来。
Bumble 拒绝非 BLUETOOTH 的 chip 后，模拟器会直接 abort。
必须加 `-feature -WiFiPacketStream,-Uwb`。

## 目录结构

```
docs/REPORT.md          完整研究记录（1757 行，41 节）
tools/render_background.py   把中文标签画进背景图
tools/build_watchface.py     从模板生成自定义表盘 zip
tools/send_to_watch.sh       推送到 App 并触发发送
tools/bridge_bluetooth.sh    一键起蓝牙桥
```

## 免责声明

本项目仅用于个人研究与自用设备。不包含 COROS 的任何专有代码、固件或密钥。

- 替换表盘可能影响设备保修，风险自负
- 请遵守 COROS 的服务条款
- 不要把从官方模板提取的图片、字体等素材重新分发
- 不要在设备上做任何固件层面的修改

## 致谢

- [Bumble](https://github.com/google/bumble) —— 蓝牙协议栈与 Android netsim transport
- [Meetoul/coros-watchface](https://github.com/Meetoul/coros-watchface) —— 早期的表盘格式记录
