# COROS PACE 4 手表连接与表盘逆向研究记录

日期：2026-10-19
工作目录：`/home/linnin233/code/coros-research`

## 0. 结论摘要

- 手表：COROS PACE 4（USB 型号 W335，GATT Model Number 回报 `COROS R4`），序列号 `SN-XXXXXXXXXXX`，硬件版本 `W35A030804`，固件 `V 3.2106.0`，BLE 公共地址 `AA:BB:CC:DD:EE:01`，电量 89%。
- APK：`com.yf.smart.coros.dist` 4.10.9（versionCode 410090000），651 MB，**网易易盾（Netease Yidun）整体加固**。真实 dex 被加密，`classes.dex` 只是 30 个类的壳；x86 环境会加载诱饵库 `libzgrge-x86.so`，ARM64 主壳库在 Android x86_64 的 `libndk_translation` 下会崩溃。静态无法直接得到 Java 代码。
- 已拿到：
  - 表盘 protobuf 的**完整 schema**（49 个 message、17 个 enum），从 `libw4-watchface.so` 内嵌的 `FileDescriptorProto` 还原，见 `watchface.proto`。
  - 表盘 native API 全量 JNI 符号（`WatchfaceParser`、`WFPngConvertor`、`TextImageBuilder`）。
  - 手表 GATT 全量服务/特征/权限/可读值，见 `ble_gatt_pace4.txt`。
  - COROS 固件文件头格式与 Pace 3 固件镜像（用于协议逆向），见 `firmware/`。
  - 公开研究（SySS 对 PACE 3 的 BLE 分析）与本次 Pace 4 的差异点。
- 未完成：App 层 BLE 命令帧序列、表盘上传命令与 `.bin` 容器的精确布局。原因不是手表封闭，而是 **APK 壳 + 反模拟器** 阻断了 App 侧代码获取。

## 1. 设备与物理连接

### 1.1 USB

手表通过 USB 枚举为：

```
cafe:4002 TinyUSB COROS WATCH
serial W3355851c40510362689
Interface: Mass Storage (SCSI Bulk-Only)
```

块设备 `/dev/sda` 容量为 0，无法挂载。这与 PACE 3 的“双键按住插线进入 USB 刷机模式”一致：普通连接只枚举出 MSC 骨架，未进入可用存储模式。本次没有向该块设备写入任何数据。

### 1.2 BLE

连接由本机 BlueZ 建立（GNOME 蓝牙面板显示已连接），配对方式为 Legacy Just Works：

```
Device AA:BB:CC:DD:EE:01 (public)
Name: COROS PACE 4 XXXXXX
Paired: yes  Bonded: yes
```

> 回滚：`bluetoothctl remove AA:BB:CC:DD:EE:01` 可删除本机配对记录，不影响手表数据。

## 2. APK 结构与加固

### 2.1 基本结构

| 项 | 值 |
|---|---|
| package | `com.yf.smart.coros.dist` |
| version | 4.10.9 (410090000) |
| minSdk / targetSdk | 24 / 36 |
| 体积 | 651 MB（大量 ONNX 模型、地图资源） |
| dex | 单个 `classes.dex`，92 MB，但头部只声明 30 个类 |
| 壳 | `com.zgpgarg.zmr.kcaqqgc.*`（随机包名） |

### 2.2 壳的行为

`MyApplication.attachBaseContext()` 中：

1. `needExtractSo()` 为真时把壳 so 释放到 `app_lib/`。
2. `needX86So() && MyJni.a()` 为真时加载 `libzgrge-x86.so`，否则加载 `libzgrge.so`。
3. `MyJni.load(this, packageName)` 由 native 完成真实 dex 解密与 ClassLoader 注入。
4. 之后通过 `PathClassLoader` 的 `pathList` 注入解密后的 dex。

`MyJni.a()` 的判断：

- `Build.SUPPORTED_ABIS` 包含精确的 `"x86"`；
- 或读取 `/proc/self/maps` 找到 `/system/bin/app_process`，解析 ELF `e_machine`，返回 `x86_64`。

因此在 x86_64 模拟器上必然走 `libzgrge-x86.so` 分支。该库加载后不注册 `MyJni.load`，App 直接 `UnsatisfiedLinkError`。

### 2.3 实测过的动态脱壳路径

| 路径 | 结果 |
|---|---|
| x86_64 模拟器 + 原版 APK | 加载 `libzgrge-x86.so`，`MyJni.load` 无实现，崩溃 |
| 补丁 dex（`needX86So()` 返回 false）+ 重签名 | 改走 ARM64 `libzgrge.so`，在 `libndk_translation` 中 `SIGSEGV`（壳的反调试/信号处理与翻译层不兼容） |
| Frida spawn 注入 | 被反调试拦截，进程启动超时/连接被关闭 |
| ARM64 系统镜像 | emulator 明确拒绝：x86_64 宿主不支持 arm64 guest |

补丁 APK、模拟器、Frida 均只在本机模拟器内操作，没有接触手表固件。

### 2.4 壳内解出的关键字符串

壳的字符串用 Base64 + 循环 XOR（key=`Netease`）混淆。解出的关键项：

- 库：`libzgrge.so`、`libzgrge-x86.so`、`libneguard.so`、`libnesec.so`、`libdexfix.so`
- 资源：`assets/.nesec_patch`、`nesec_patch2`
- 反检测提示：`Detected that the app is running on an emulator.`、`Detected the presence of a debugger.`、`Detected that the app has been injected.`、`检测到在模拟器中运行` 等
- 开关：`x86_switch_1`、`debug_switch_0`、`extract_switch_0`、`provider_switch_1`

## 3. 表盘功能

### 3.1 Schema 来源

`lib/arm64-v8a/libw4-watchface.so` 的 `.rodata` 中直接内嵌了序列化的 `FileDescriptorProto`：

```
0a 0f "watchface.proto" 12 09 "watchface" ...
```

从中还原出 49 个 message、17 个 enum，已生成 `watchface.proto`（proto3 语法）。

### 3.2 顶层模型

```protobuf
message Watchface {
  WFHead head = 1;
  WFBackground background = 2;
  WFStatusInfo status = 3;
  map<...> date = 4;
  WFTimeValue time = 5;
  WFClockPointerGroup pointer = 6;
  WFAutoAlignTime auto_align_time = 7;
  WFControl control = 8;
  WFProject project = 9;
  map<...> lunar = 10;
  WFWeatherInfo weather = 11;
  WFFishInfo fish = 12;
  WFExtendedStatusInfo extended_status = 13;
  WFRect lunar_date_rect = 14;
  WFChartInfo chart = 15;
}
```

`WFHead` 是 bin 的逻辑头：

```protobuf
message WFHead {
  uint32 magic = 1;
  uint32 id = 2;
  uint32 len = 3;
  int32 crc16 = 4;
  int32 layout = 5;
  bool theme_color_off = 6;
  int32 point_layer = 7;
  int32 time_format = 8;
  int32 width = 9;
  int32 height = 10;
  int32 o_wf_ver = 11;
  int32 o_diy_version = 12;
  int32 default_theme = 13;
}
message WFBinInfo {
  WFHead head = 1;
  WFBinSize size = 2;
}
```

表盘由这些元素组成：背景、时间数字/指针、状态图标（电量/蓝牙/勿扰/睡眠）、日期/农历、天气、控制项（步数/卡路里/楼层/心率等）、圆弧进度、图表、鱼类/潮汐、AOD。

### 3.3 表盘 native API

`libw4-watchface.so` 导出：

```
WatchfaceParser.nativeCreate / nativeParseTemplate / nativeTemplate
WatchfaceParser.nativeExportBin / nativeExportWF / nativeExportPreview / nativeExportZip
WatchfaceParser.nativeParseBinHead / nativeBuildSystemStatus
WatchfaceParser.nativeSetCustomStyle / nativeSetPalette / nativeSetParseCfg
WatchfaceParser.nativeSupportScreenType / nativeFindInvalidConfig
WFPngConvertor.nativeCreate / nativePrepare / nativeSetCfg / nativeSetPalette
WFPngConvertor.nativeSetBgColor / nativeConvert / nativeZip / nativeUnzip
TextImageBuilder.toSingleLineImage / argb8888ToRgba2222 / rgba2222ToArgb8888
```

可推断工作流：

1. App 从服务端拿模板/资源（`table_watchface` 表字段：`bin_url`、`img_url`、`bin_local_path`、`author`、`server_id` 等）。
2. `WatchfaceParser` 解析模板，`WFPngConvertor` 做 PNG 转换/调色板/抖动。
3. `nativeExportBin` 生成手表可用的 `.bin`。
4. 通过 BLE 分帧上传，状态机日志为：
   `STATE_WARTING_SEND_DATA` → `STATE_AFTER_SENDING_FRAME_META` → `STATE_WAITING_SENDING_FRAME_DATA` → `STATE_AFTER_SENDING_ONE_FREME` → `STATE_SENDING_OVER`，字段 `TotalNumFrame`、`sendDialMeta`。

`.bin` 的精确布局（头部魔数、CRC 覆盖范围、图片块排列）仍需对 `nativeExportBin` / `nativeParseBinHead` 做进一步反编译确认；目前只能确定它由 `WFBinInfo`（含 `WFHead`）与资源块组成。

## 4. BLE GATT（PACE 4 实测）

完整输出见 `ble_gatt_pace4.txt`。要点：

| 服务 | 说明 |
|---|---|
| `00001800/1801/180a/180f/180d/1814` | 标准 GAP/GATT/Device Info/Battery/HR/RSC |
| `6e400001-...-77656c6f6f70` | 主 NUS（Android App 数据） |
| `6e400001-...-77757c7f7f70` | 通知注入通道（SySS 已分析） |
| `6e400001-...-e50e24dcca9e` | 标准 Nordic UART |
| `0000fee7` | 腾讯服务（fea1/fea2/fec9，通知/绑定相关） |
| `00003802` | char `4a02`（read/write/notify） |
| `dc522617-9a51-4bbf-b0e0-d3c538b30c60` | **PACE 4 新增私有服务** |

新增服务特征：

```
0997735b-b167-4a0b-bfb3-b971a4113ea9  read,notify
b5114592-b4f0-4c72-b3b4-5de55e04c856  read,notify
3deb5ddb-c7e6-427d-95ee-118320bb385d  write-without-response
92a5f7a4-5e4b-4133-a06c-8010132eb798  write-without-response
```

该服务在 Pace 3 上不存在，疑似 Pace 4 的新数据/文件通道。具体用途尚未确认。

设备信息实测：

```
2A24 Model Number      = COROS R4
2A25 Serial Number     = SN-XXXXXXXXXXX
2A27 Hardware Revision = W35A030804
2A28 Software Revision = V 3.2106.0
2A19 Battery           = 89%
```

## 5. BLE 协议现状

### 5.1 公开研究（PACE 3）

SySS 的分析给出了帧结构：

- 特征写入 `6e400002-...-77656c6f6f70`，通知 `6e400003-...-77656c6f6f70`。
- 帧头为 `命令(1B) + 0x00`，随后是长度/负载/校验。
- 已知命令：
  - `0x0D`：连接初始化
  - `0xA6` / `0xA7`：能力/握手
  - `0x8B`：手机信息（Android/iOS 区分）
  - `0x7C`：带长度数据
  - `0x79`：通知（发到 `77757c7f7f70`）
  - `0x86`：勿扰设置（校验为字段和 mod 256）
  - `0xB0`：设备信息
  - `0xB9`：文件传输（后续包格式 `00 00 Data Checksum`）
- Android App 不触发配对，通信不加密；iOS 会触发 Legacy Pairing。

### 5.2 PACE 4 实测结果

- 已连接、已配对（Just Works）、已把主通知特征 CCCD 写成 `0100`。
- 读取设备信息/电量正常。
- 向主 NUS、标准 NUS、`3802/4a02`、新增服务两个写特征分别发送 `0D 00`、`A7 00 00 0D 0D`、`B0 00`、`A6 00`，均无通知回应。
- 向 `77757c7f7f70` 发送 SySS 格式的通知帧，手表未显示。

结论：PACE 4（固件 3.2106.0）至少在当前离线状态下没有接受这些旧格式帧，或者新固件把 App 数据通道迁到了 `dc522617` 服务并要求新的握手。需要 App 侧代码或真实抓包才能确定。

## 6. 固件

### 6.1 容器格式

按 SySS 公开格式解析成功：

```
magic(2) 0 fileid(1) model(1) flags(1) checksum(1) checkxor(1)
size(4) filecrc(2) headercrc(2)  body...
```

Pace 3 系统 OTA（`7_COROS_W331_system_ota.bin`，2.9 MB）解析出 2 个镜像：

- `w331_image_0.bin`（1.8 MB，内部 flash，基址 `0x10000000`，带 Cortex-M 向量表）
- `w331_image_1.bin`（1.1 MB，外部 XIP/资源）

### 6.2 已确认的协议相关符号

固件字符串中包含：

```
coros/bluetooth/transport/ble_cmd.c
ble_protocol_cmd_receive
protocol_cmd_parse
cmd:0x%x, tick:%d,%d, task:%s
Recieved append data, but current cmd type invalid!
```

以及 `watchface_ota.bin`、`32_watchface_240x240.bin` … `36_watchface_240x240.bin`、`window_watchface.c`、`watchface_custom.c` 等表盘资源/代码路径。

### 6.3 Ghidra 分析

已用 Ghidra 11.2.1 + JDK 21 导入 `w331_image_0.bin`（ARM Cortex-M，基址 `0x10000000`），完成了自动分析。字符串地址可定位（如 `ble_protocol_cmd_receive @ 0x10187588`），但原始二进制缺少符号/入口，命令分发表尚未定位成功。下一步需要：

- 对 `0x101bd728` 附近的跳转表、`0x101b36ec` 附近的处理函数表做人工确认；
- 或对 `ble_protocol_cmd_receive` 的调用点做交叉引用恢复。

## 7. 为什么这个 App 这么难

1. **整体加密**：真实 dex 不在 APK 里以明文存在，`classes.dex` 只是壳。
2. **反模拟器**：检测到 x86 就加载诱饵库，检测到模拟器/调试器会弹窗或退出。
3. **反注入**：Frida/Xposed/调试器检测。
4. **ARM 翻译不兼容**：壳的 native 代码在 `libndk_translation` 下触发 SIGSEGV，无法在 x86 模拟器完成解密。
5. **真机才可行**：需要一台真实 ARM Android 设备（最好 root）来跑 App 并 dump 内存或抓 HCI。

## 8. 下一步建议

优先级从高到低：

1. **借一台真实 ARM Android 手机**（最好已 root）：
   - 安装原版 APK，连接手表；
   - root 后用 `frida-dexdump` 或 `/proc/pid/mem` dump 解密后的 dex；
   - 或开启开发者选项里的“蓝牙 HCI 监听日志”，用 App 连接手表并浏览一次表盘商店，导出 `btsnoop_hci.log`，即可拿到完整命令序列。
2. **继续固件逆向**：定位 `ble_protocol_cmd_receive` 与命令分发表，恢复 PACE 3 的命令 ID 与帧格式，再对照 PACE 4 的新服务验证。
3. **获取 PACE 4 固件**：需要 COROS 账号的 accessToken 调 `POST https://apieu.coros.com/coros/ota/query`（`firmwareType: COROS W335/R4`），拿到 `3.2106.0-<build>` 路径后从 `s3eu.coros.com` 下载。

## 9. 安全与回滚

- 全程未向手表 flash 写入固件，未进入 USB 刷机模式写入。
- 仅做了 BLE GATT 读取、CCCD 使能、以及公开研究中的握手/通知帧写入。
- 本机配对记录可用 `bluetoothctl remove AA:BB:CC:DD:EE:01` 删除。
- 若手表出现异常，长按电源键重启即可；没有修改任何持久化配置。

## 10. 产物清单

| 文件 | 说明 |
|---|---|
| `watchface.proto` | 从 native 库还原的表盘 protobuf schema |
| `ble_gatt_pace4.txt` | PACE 4 GATT 全量枚举与可读值 |
| `firmware/w331_ota.bin` | Pace 3 系统 OTA 原始文件 |
| `firmware/w331_image_0.bin` / `_1.bin` | 拆分后的固件镜像 |
| `apk/extract/libw4-watchface.so` | 表盘 native 库 |
| `apk/extract/classes.dex` | 加固壳 dex（30 类） |
| `shell/` | 壳类反编译结果 |
| `tools/` | BLE/Ghidra/脱壳辅助脚本 |

## 11. 表盘工程包（模板 ZIP）格式——已解出

App 在安装自定义表盘时会从 OSS 下载一个模板 ZIP，日志里会打印完整地址（tag `CorosWatchFaceModelImpl`，`downloadWatchFaceTemplate() url =`）。已抓到的样例：

```
https://oss.coros.com/watchface_template_user_custom/473395402473750528/1791187418YGMB4M5OK8220W0X6WX5.zip
```

ZIP 结构（450 项）：

| 路径 | 说明 |
|---|---|
| `info.json` | 模板元信息：`m_name`、`m_app`、`m_preview`、`o_template_id`、`o_author`、`o_diy_version` |
| `watchface_390x390/config.txt` | **表盘布局**（INI 风格，GBK 编码），PACE 4 用这一份 |
| `watchface_390x390/AODconfig.txt` | 息屏显示布局 |
| `watchface_390x390/background.png` | 背景图（样例仅 156 字节，纯色） |
| `watchface_390x390/backgroundaod.png` | 息屏背景 |
| `watchface_390x390/thmb.png` | 手表上的缩略图 |
| `watchface_390x390/watchface_customize.png` | App 内预览图 |
| `watchface_390x390/{01,38x38,40x40,50x50}/00..09.png` | 数字字体图（每目录 10 张） |
| `watchface_390x390/battery/` | 电量图标 |
| `watchface_390x390/{cn,english,de,es,fr,it,jp,pl,pt}_week/` | 星期字体 |
| `watchface_390x390/icon/` | 负面图标：`dgree.png`、`negasign.png`、`separator.png`、`level.png`、`bt_on.png`、`Do_not_disturb.png` |
| `watchface_390x390/weather/`、`weather2/` | 白天/夜间天气图标 |
| `watchface_800x800/` | 同结构，另一分辨率 |
| `custom/custom.pb` | protobuf：`0a 08 0a 06 "custom" 1a 0d "custom_bg.png"` |

### config.txt 关键字段（可直接改）

- 背景：`[background_icon_pos]={0,0}`、`[background_icon]=background.png`、`[bg_color]=0x000000`
- 时间：`[time_hour_high_pos]={x,y}`、`[time_hour_high_font]=50x50`，分/时各两位
- 数字日期：`[num_date_rect]={x0,y0,x1,y1,hcenter|vcenter}`、`[num_date_month_font]`、`[num_date_day_font]`
- 数据项（rect 格式 `{x0,y0,x1,y1,对齐}`）：
  - `[step_rect]` / `[step_font]` / `[step_font_color]`
  - `[kcal_rect]` / `[kcal_font]`
  - `[exercise_hour_rect]`、`[exercise_minute_rect]`、`[exercise_font]`
  - `[heartreate_level_rect]`（原文拼写如此）/ `[heartreate_level_font]`
  - `[battery_level_rect]` / `[battery_level_font]`
  - `[temperature_rect]`、`[elevation_rect]`
  - 进度弧：`[step_progress_arc]`、`[kcal_progress_arc]`、`[exercise_progress_arc]`
- 图标：`[colon_icon]`、`[point_icon]`、`[negative_sign_icon]`、`[am_pm_icon_pos]`

也就是说：**“纯黑背景 + 只显示数据”的表盘，只要改 config.txt 里各数据项的 rect 和字体即可**，格式完全够用。

### 为什么还不能直接装

App 安装流程是：下载模板 ZIP → `WFTemplateParser` 解析 → `WatchFaceParser.nativeExportBin` 生成 .bin → BLE 上传（需先过 A5 握手）。

- 模板 ZIP 由服务端下发（OSS 地址），本机无法改写；
- 服务端保存接口（`watchFaceTemplateUserCustom/saveOrUpdateV2` 等）需要 `sign`/`nonce`/`timestamp` 签名，算法在加固 dex 里；
- BLE 上传需要 A5 挑战应答，重放无效。

所以剩下的唯一卡点仍是 **App 的真实 dex**（拿到后 A5 算法、签名算法、nativeExportBin 调用方式都能解）。

---

## 12. 2026-10-19 晚：官方分享链路与免 root 路径分析

### 12.1 GitHub 已有的研究：Meetoul/coros-watchface

仓库 https://github.com/Meetoul/coros-watchface （Apex 4，最后更新 2026-07-10），README 给出了完整侧载流程：

1. 手机需 root（`adb root`）
2. 在 App 里创建一个自定义表盘，App 会把模板 ZIP 写到 `/data/user/0/com.yf.smart.coros.dist/files/coros/template/<时间戳ID>.zip`
3. `adb pull` 出来，解压，直接改 `config.txt` 和各 PNG
4. 原样重新打包，删掉同名缓存目录 `<时间戳ID>_*`，`adb push` 回去
5. 手表上切到任意表盘 → 表盘列表 → CUSTOM → 选该表盘 → SEND TO WATCH

关键结论：**ZIP→BIN 转换和 BLE 上传全部由 App 自己完成**，不需要自己实现 bin 封装、不需要伪造签名、不需要碰 A5 握手。仓库里附带的 260x260 模板 `config.txt` 与本项目解码的格式逐字段一致。

### 12.2 官方分享链路（无需登录的接口）

公众号「强森」（高驰表盘领取中心）通过飞书表格分发表盘链接，链接形如：

```
https://faq.coros.com/share/watchface?id=<id>&region=2&type=2
```

前端 JS（`staticcn.coros.com/coros-web-faq/public/js/www/sharepage/watch-face/index.*.js`）揭示：

- 查询接口：`POST https://apicn.coros.com/coros/watchface/share/findShareInfo`
- FormData 参数：`type`、`id`、`region`，**不需要 accessToken、不需要 sign**
- region 2 = 中国（apicn），1 = 国际（api.coros.com），3 = 欧洲（apieu），4 = 新加坡（apisg）
- 返回结构（type=2）：
  ```json
  {"result":"0000","data":{
     "expireTimestamp":1792583055052,
     "watchFaceShare":{"id":481146464054116452,"watchFaceTemplateId":481146464054116352,...},
     "watchFaceTemplateUserCustom":{
        "watchFaceTemplateId":481146464054116352,
        "watchFaceTemplateUrl":"https://oss.coros.com/watchface_template_user_custom/0/1792410254P2OPTQQPSOTR82I68WYU.zip",
        "watchFaceTemplateUrlOrigin":"0/1792410254P2OPTQQPSOTR82I68WYU.zip",
        "watchFaceId":-2147385653,"userId":0,"srcWatchFaceTemplateId":2609180}}}
  ```
- 跳转 App 的 deeplink（CallApp 构造）：
  ```
  gccomcoros796://sharepage.coros.com/app_link?link_type=1&coros_path=coros.share.watchFace&type=2&id=<id>&region=2
  ```
- App 入口 `com.yf.smart.weloopx.app.UriEntryActivity`（exported），manifest 中注册了
  - `https://faq.coros.com/share/watchface*`
  - `https://webtestfaq.coros.com/share/watchface*`
  - `gccomcoros796://*.coros.com/{coros,app_link}`

实测：`type=1` 返回 `1031 Parameter input error`；`type=2` + 不存在的 id 返回 `9024 watch face share url invalid`；真实 id 返回 `0000`。

### 12.3 OSS 写入不可行

`oss.coros.com` 后端为 `coros-oss.oss-cn-beijing.aliyuncs.com`，对象可匿名读（HEAD 200，`x-oss-object-type: Multipart`），但 PUT 任意路径返回：

```xml
<Code>AccessDenied</Code>
<Message>You have no right to access this object because of bucket acl.</Message>
```

即 bucket ACL 为公共读、私有写，需要 STS 或预签名 URL，二者均由服务端签名接口下发。

### 12.4 App 网络安全配置

`res/xml/network_security_config.xml`：

```xml
<base-config cleartextTrafficPermitted="true">
  <trust-anchors>
    <certificates overridePins="true" src="system"/>
    <certificates src="@0x7f13001d"/>  <!-- res/raw/lijie.pem：Charles Proxy Root CA -->
    <certificates src="@0x7f13001e"/>  <!-- res/raw/lijie2.cer：Fiddler Root -->
    <certificates src="@0x7f13004d"/>  <!-- res/raw/yuanxiaowen.crt：whistle (wproxy.org) -->
  </trust-anchors>
</base-config>
```

推论：

- 允许明文 HTTP；
- 信任系统 CA（`overridePins=true`），不信任用户安装的 CA；
- 内置了三款抓包工具的根证书，说明开发/测试期就在抓自己的包。

因此「中间人替换 OSS 上的 zip」在技术上成立，但前提是把自签 CA 装进**系统**证书库，这需要 root。三条内置证书的私钥不在 APK 内。

### 12.5 模拟器结论

| 方案 | 结果 |
| --- | --- |
| x86_64 API 30（Android 11） | App 启动到 `MyApplication.attachBaseContext` 崩溃：`No implementation found for ... MyJni.load`。加固壳 `libzgrge.so` 的 `.gnu.fragment`/`.gnu.draft`/`.gnu.stub` 段整段加密，需运行时解密并注册 JNI；`ndk_translation 0.2.2` 下构造未完成。壳会自行解出 `app_lib/libzgrge-x86.so`（x86-64，1.16MB），但该文件符号表同样加密，直接加载不可用。 |
| arm64 API 30（QEMU2） | x86_64 宿主上被 emulator 拒绝；patch 架构检查后，ranchu 机器缺少 PCI 总线，`PCI bus not available for hda`、`No 'PCI' bus found for device 'virtio_input_multi_touch_pci_1'`，换用 37.3.4 的 qemu 引擎同样失败。 |
| x86_64 API 35（Android 15） | 下载中，待验证（`ndk_translation` 版本更新，有机会跑通壳的构造函数）。 |

### 12.6 已生成的自定义表盘

`watchface/black_pace4.zip`（450 条目），基于用户分享的官方模板 `share_wf.zip` 重建，保留原始 `config.txt` 全部字段，仅改值：

- 背景 `background.png` / `backgroundaod.png` 替换为 390x390 纯黑（522 字节）
- `[bg_color]=0x000000`
- 时间：`50x50` 字体，四位数位置 `{95,80}/{135,80}/{195,80}/{235,80}`
- 数字日期：`[num_date_rect]={145,150,245,187,hcenter|vcenter}`，字体 `40x40`
- 星期：`[english_date_week_rect]={145,192,245,222,...}`，字体 `english_week`
- 步数 `{20,258,140,298}`、卡路里 `{250,258,370,298}`、心率等级 `{20,308,140,348}`、电量 `{250,308,370,348}`，字体均为 `40x40`
- 天气、蓝牙、勿扰、海拔、运动时长、多语言日期等全部清空

生成脚本 `watchface/build_black.py`。

### 12.7 剩余卡点

唯一卡点仍是「把自定义 ZIP 送进 App 的私有目录」，可行路径只有两条：

1. 一台能 root 的安卓设备（Meetoul 路线，已验证）；
2. 在模拟器里跑通加固壳，dump 出 dex，进而解出 A5 握手与 `nativeExportBin`，在 Linux 上用 BlueZ 直接对手表上传（无需手机 root，但需要模拟器能跑）。

App 自身没有任何「从本地文件导入表盘」的入口（已核对 65651 条资源字符串），只有表盘库、我的表盘、自定义表盘、表盘分享、扫码获取表盘。

---

## 13. 2026-10-19 夜：Android 15 模拟器跑通并通过 JNI 调用表盘生成库

### 13.1 加固壳在 Android 15 上可用

Android 11（API 30）镜像上 App 崩在 `MyJni.load` 找不到实现；换成 Android 15（API 35，`x86_64-35_r09`）后直接通过：

```
I/berberis: '/data/app/.../lib/arm64/libzgrge-x86.so' library was loaded for the host platform.
D/nativeloader: Load ... libzgrge-x86.so ... ok
```

壳内部自带 x86_64 原生实现（伪装放在 `lib/arm64-v8a/` 下），Android 15 的 linker 能识别该 ELF 并原生加载，不再走 `ndk_translation` 转译，因此壳的构造函数正常完成，`MyJni.load` 注册成功，App 一路启动到 `PrivacyTipActivity`。

### 13.2 dex 无法从内存获取

- `oat/` 目录只有一个 92 字节的 `Anonymous-DexFile@*.vdex`（空壳）
- 全量扫描 `/proc/pid/mem` 的所有可读段，找不到任何 `dex\n03x` 魔数
- 说明易盾采用指令抽取/加密驻留，dex 不以明文形式存在于文件或内存

### 13.3 用 JNI 直接调用未加固的 `libw4-watchface.so`

`libw4-watchface.so`（3.7MB）未被加固，动态符号表完整（4415 个导出），其中：

```
Java_com_yf_coros_watchface_WatchfaceParser_nativeCreate
Java_com_yf_coros_watchface_WatchfaceParser_nativeParseTemplate
Java_com_yf_coros_watchface_WatchfaceParser_nativeExportBin
Java_com_yf_coros_watchface_WatchfaceParser_nativeExportWF
Java_com_yf_coros_watchface_WatchfaceParser_nativeExportPreview
Java_com_yf_coros_watchface_WatchfaceParser_nativeExportZip
...
_ZN9watchface16WFTemplateParser9ExportBinEPKcS2_jiii
```

反汇编确认的 Java 签名：

- `nativeCreate()`：void，内部 `CreateNativeObject<WFTemplateParser>`，结果写入字段 `nativePtr`（`J`）
- `nativeParseTemplate(String, String)`：`Parse(zipPath, dir)`，内部先 `Unzip(zip, dir)` 再 `SetTemplateDir(dir)`
- `nativeExportBin(String name, String outDir, int, int, int, int)`：内部调 `WFTemplateParser::ExportBin`

验证环境：自建一个 7.8MB 的测试 APK（`wfgen`），把 `libw4-watchface.so`、`libprotobuf.so`、`libc++_shared.so` 放进 `lib/arm64-v8a/`，在 Android 15 模拟器上运行。

结果：

- 三个 so 全部加载成功
- `nativeCreate()` 成功（`nativePtr` 非零）
- `nativeParseTemplate(我们的 zip, 私有目录)` 返回 **true**，`work/` 下解压出了完整表盘结构，`info.json`、`config.txt`、`background.png` 都是我们生成的内容
- `nativeExportBin` 仍返回 false

### 13.4 当前卡点

反汇编显示 `ExportBin(zipOrName, out, w3, w4, w5, w6)` 第一步是 `WFTemplateParser::GetWatchfaceByName(name)`：

- 它先用 `GetSizeByName(name)` 以正则 `([0-9]+)[^0-9]+([0-9]+)` 从名字里解析宽高
- 再遍历 `WatchfaceTemplate` 的 `watchface` 列表（protobuf `repeated WatchfaceEntry watchface = 2`）找宽高匹配项
- 返回 0 即整体失败

而 `SetTemplateDir` 反汇编确认**只做目录遍历**：`opendir` → `readdir` → 跳过 `.`/`..` → 遇到 `info.json` 就把当前目录路径压入 vector，然后递归。**它不解析 `config.txt`，所以 `watchface` 列表始终为空**，`GetWatchfaceByName` 必然失败。

尝试过的名字：`BLACK DATA`、`SIMPLE`、`watchface_390x390`、`390x390`、`390`、`watchface_800x800`、`800x800`，配合参数组合 `(0,390,390,0)`、`(1,390,390,0)`、`(0,0,0,0)` 等，全部返回 false。

### 13.5 下一步方向

1. 找到填充 `watchface` 列表的入口（可能是 `BuildContext` 之前必须调用的某个方法，或 `WFProject` 的加载路径）
2. 或者绕过 `GetWatchfaceByName`，直接构造 `WFBinExporter` + `WFContext`（需要 NDK 写 native wrapper）
3. 或者换用 `nativeExportPreview`/`nativeExportZip` 先验证名字解析是否正确

工具与产物：

- `tools/plt2sym.py`：把 so 的 PLT 桩解析成动态符号，用于读反汇编
- `wfgen/`：测试 APK 源码与构建产物（`src/com/yf/coros/watchface/WatchfaceParser.java`、`src/com/linnin233/wfgen/Main.java`）
- `watchface/black_pace4.zip`：纯黑 + 数据表盘，已通过 `nativeParseTemplate`

## 14. 2026-10-19 深夜：native 直接调用 COROS 表盘库的进一步结论

### 14.1 NDK 编译与 native 包装

用 NDK r27c 把 `wfgen/jni/gen.cpp` 编成 `libgen.so`（arm64），塞进测试 APK 的 `lib/arm64-v8a/`。运行时全部符号都能 `dlsym` 到：

```
ctor=1 parse=1 load=1 getwf=1 expbin=1 expwf=1 info=1
ctor done
parse=true
LoadInfo=true
loadAllConfig done
```

`WFTemplateParser` 对象大小 0x48，构造函数符号 `_ZN9watchface16WFTemplateParserC1Ev`。

### 14.2 失败点定位到 LoadConfig

`LoadAllConfig`（0x1ad4c4）的实际逻辑：

1. `LoadInfo()` 读 `info.json` —— 返回 true，成功
2. `opendir(templateDir)` 遍历子目录
3. 对每个子目录项：`ConcatPath(dir, entry)` → `ConcatPath(..., "config.txt")`
4. `bl LoadConfig(this, &wf, entry, "config.txt")`，**返回 bool**
5. `tbz w0, #0, 0x1ada44` —— 返回 false 就跳过 `map.insert`
6. 成功才 `MapField::insert(entry, wf)`

实测 `LoadConfig` 返回 false，所以 `watchface` map 始终为空，`GetWatchfaceByName` 必然返回 0。把原始未修改的 `config.txt`（8135 字节）换进去，结果相同，排除配置被改坏的可能。

`LoadConfig` 内部在 `0x1af1bc` 调用 `0x197dd4`，该地址没有导出符号，相邻符号是 `GetFileLength`（0x197d04）和 `IsExists`（0x197ef0），推测是读取/解析 config 的内部函数，它返回非零错误码后 `LoadConfig` 直接走失败分支。

### 14.3 下一步方案

放弃 `LoadConfig` 这条链，改为手工构造 `Watchface` protobuf：

1. 用 `watchface.proto` 的 schema 生成 `Watchface` 消息字节（`head.width/height`、`background`、`time`、`step_rect` 等）
2. native wrapper 里 `Watchface::ParseFromArray` 初始化对象
3. 调 `BuildContext(const Watchface*, const Watchface*, int, Rgba8Palette*)` 得到 `WFContext`
4. 调 `WFBinExporter::Export()` 生成 bin

这样完全不依赖 `config.txt` 解析和 `watchface` map。

### 14.4 工具

- `wfgen/jni/gen.cpp`：native 包装，已有 `dlsym` 全套符号与诊断输出
- `tools/plt2sym.py`：PLT 桩 → 动态符号名解析，反汇编定位调用链用
- `tools/setup_api35.sh`、`tools/run_api35.sh`：API 35 镜像安装与模拟器启动脚本

## 15. 手工构造 Watchface 走 BuildContext 的尝试

### 15.1 拿到完整 schema

`watchface.proto` 是之前反编译的，缺 9 个 map entry 定义（`ItemEntry`、`ProgressEntry`、`ArcProgressEntry`、`CommonResEntry`、`DateEntry`、`LunarEntry`、`WatchfaceEntry`、`AodWatchfaceEntry`、`EnhanceColorsEntry`、`LevelIconEntry`），导致 `protoc` 编译失败。

补齐这些定义后（`/tmp/watchface_fixed.proto`），`protoc --python_out` 成功生成 59 个消息类型，`WFHead` 的 `width/height`、`WFBackground` 的 `bg_color`、`WFTimeValue` 等字段都可用。

构造最小 `Watchface`（`head.width=390`、`head.height=390`、`background.bg_color=0`）序列化为 16 字节：

```
0a0a0800100048860350860312022000
```

### 15.2 native 侧调用链

在 `gen.cpp` 里新增 `nativeGen2`：

1. 读 `wf_min.bin`
2. `malloc(2048)` + `memset` + `WatchfaceC1Ev` 构造对象
3. `MessageLite::ParseFromArray(wf, data, len)`（通过 `RTLD_DEFAULT` 解析，该符号在 `libw4-watchface.so` 里是 UND，实际由 `libprotobuf.so` 提供）
4. `WFTemplateParser::BuildContext(parser, wf, nullptr, 0, palette)`
5. `createBinExporter(ctx)`
6. `WFBinExporter::Export()`

### 15.3 结果：SIGSEGV

崩溃在 `libgen.so` 内部：

```
Fatal signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0xd8
Cause: null pointer dereference
rax 0000000000000000  rdi 00007d9f50401020
```

`rdi` 是 `Watchface` 对象指针，`rax=0` 后解引用 `+0xd8` 崩溃。说明 `ParseFromArray` 在解析时访问了对象内部某个未初始化的指针。

推测原因：protobuf 消息的 `_internal_metadata_` / `_cached_size_` 等内部字段不能简单用 `memset` + 默认构造函数初始化，`WatchfaceC1Ev` 可能只做部分初始化，或者需要 `Arena` 上下文。正确做法应该是用 `Arena::CreateMaybeMessage<Watchface>()`（符号 `_ZN6google8protobuf5Arena18CreateMaybeMessageIN9watchface9WatchfaceEJEEEPT_PS1_DpOT0_` 存在）。

### 15.4 下一步

1. 改用 `CreateMaybeMessage<Watchface>(nullptr)` 创建对象
2. 或者放弃手工构造，改回修 `LoadConfig` 的失败点 `0x197dd4`
3. `protoc` + `/tmp/watchface_fixed.proto` 的 Python 绑定已可用，可随时生成测试数据

### 15.5 本轮新增文件

- `/tmp/watchface_fixed.proto`：补齐 map entry 的完整 proto
- `/tmp/wfpb/watchface_fixed_pb2.py`：Python 绑定
- `/tmp/wf_min.bin`：最小 Watchface 序列化（16 字节）
- `wfgen/jni/gen.cpp`：新增 `nativeGen2`（BuildContext + createBinExporter + Export）

## 16. CreateMaybeMessage 方案同样崩溃

把 `Watchface` 的创建从 `malloc + WatchfaceC1Ev` 改成 `Arena::CreateMaybeMessage<Watchface>(nullptr)`（符号 `_ZN6google8protobuf5Arena18CreateMaybeMessageIN9watchface9WatchfaceEJEEEPT_PS1_DpOT0_`）后重跑，仍然 SIGSEGV：

```
Fatal signal 11 (SIGSEGV), code 2 (SEGV_ACCERR), fault addr 0x7d9bf2e0b530
```

日志里没有任何 `WFGEN` 输出，说明崩溃发生在 `nativeGen2` 打印第一行之前，即 `dlopen` / `dlsym` / `newmsg(nullptr)` / `parsearr` 这几个早期步骤之一。

注意 `SEGV_ACCERR`（访问权限错误）而不是 `SEGV_MAPERR`，地址落在 `libgen.so` 自身的映射区，更像是**执行流跳到了非可执行内存**或者函数指针调用约定不匹配，而不是数据解引用问题。

### 16.1 后续排查方向

1. 在 `nativeGen2` 每一步之前先写日志到文件（而不是攒在 `std::string` 里最后打印），确定崩溃在哪个调用
2. 检查 `CreateMaybeMessage` 模板函数的真实签名（可能不是单参数，模板实例化可能带额外隐藏参数）
3. 考虑放弃手工构造 `Watchface`，回到修 `LoadConfig` 的 `0x197dd4`
4. 另一个思路：用 COROS 自己的 `nativeTemplate` 返回的字节流作为 `Watchface` 数据源（`WFTemplateParser` 内部已经有 `WatchfaceTemplate`，`nativeTemplate` 返回的就是它的序列化，可以直接 `ParseFromArray` 回一个 `WatchfaceTemplate`）

### 16.2 目前已经确认可用的部分

- `libw4-watchface.so` 全部所需的 `dlsym` 符号名
- `parseTemplate` 能把我们的 zip 完整解压并建立 templateDir
- `LoadInfo` 能读 `info.json`
- `protoc` + 补齐的 proto 可以生成任意 `Watchface` 序列化数据

唯一缺的是把 `Watchface` 对象正确实例化，以及走通 `BuildContext` → `createBinExporter` → `Export`。

## 17. LoadConfig 中的 ifstream 不是失败原因

`0x197dd4` 反汇编确认是 `std::__ndk1::basic_ifstream` 的构造函数，不是自定义解析器。`LoadConfig` 打开 `<dir>/<entry>/config.txt` 后读 `ios_base+0x20` 的状态位，非零就跳失败分支（`0x1ee574`）。

在 native wrapper 里直接验证文件可读性：

```
test open /data/user/0/com.linnin233.wfgen/files/work/watchface_390x390/config.txt -> ok
test open /data/user/0/com.linnin233.wfgen/files/work/config.txt -> ok
```

两个 config 都能打开，`templateDir` 也带尾斜杠（`.../files/work/`），所以 ifstream 打开失败这个可能性被排除。失败发生在读取之后的解析过程中。

另外确认了 `LoadConfig` 会检查 `Watchface + 0x108` 这个字段（推测是 `project` 子消息），为空时用 `CreateMaybeMessage<WFProject>` 补上，然后调 `0x372070(project, dir)`。说明它对 `Watchface` 对象内部结构有额外要求，不是单纯解析文本。

### 17.1 目前的判断

`LoadConfig` 这条链依赖较多内部状态（`project` 子消息、解析配置、资源路径），在没有 app 正常流程上下文的情况下很难逐一补齐。相比之下，`BuildContext` 路线只缺一个正确的 `Watchface` 对象实例化方式。

### 17.2 尚未尝试的点

- `WFTemplateParser::nativeTemplate` 返回内部 `WatchfaceTemplate` 的序列化字节，可以拿它反推 `WatchfaceTemplate` 结构，进而确认 `Watchface` 的必填字段
- `SetPalette` / `SetParseCfg` 是否必须在 `LoadAllConfig` 之前调用
- `ExportPreview`（不经过 `watchface` map）是否可用

## 18. 关键发现：LoadAllConfig 实际是成功的

用 `WatchfaceTemplate::ByteSizeLong` 和 `MessageLite::SerializeToArray` 把 parser 内部的模板序列化出来（9276 字节，落在 `/data/data/com.linnin233.wfgen/files/tmpl.bin`），再用补齐后的 `watchface_fixed_pb2` 反解：

```
info: BLACK DATA | watchface_800x800
watchface entries: 2
  key= 'watchface_800x800' width= 800 height= 800
  key= 'watchface_390x390' width= 390 height= 390
aod entries: 1
  aod key= 'watchface_390x390' w= 390 h= 390
```

也就是说：

- `LoadConfig` 实际返回了 true，配置解析完全成功
- `watchface` map 里有正确的两条记录，宽高都对
- `GetWatchfaceByName("watchface_390x390")` 依然返回 0

问题不在加载，而在 `GetWatchfaceByName` 内部的 `GetSizeByName(name)`。它用正则 `([0-9]+)[^0-9]+([0-9]+)` 从名字里提取宽高，提不出来就返回 0，`GetWatchfaceByName` 随即 `cbz x0` 走失败分支。

### 18.1 下一步

1. 直接 `dlsym` 调 `GetSizeByName`，看它对 `"390x390"`、`"watchface_390x390"` 到底返回什么
2. 绕过 `GetWatchfaceByName`：拿到 `WatchfaceTemplate` 的 map，直接取出 `Watchface*` 传给 `BuildContext`
3. 用序列化出来的 9276 字节作为模板数据源，反解出 `Watchface` 子消息字节，再想办法实例化

### 18.2 当前确定可用的完整链路

```
nativeCreate()                       -> parser 对象（0x48 字节）
nativeParseTemplate(zip, dir + "/")  -> Unzip + SetTemplateDir，返回 true
LoadInfo()                           -> 读 info.json，返回 true
LoadAllConfig()                      -> 填充 watchface map（2 条，宽高正确）
serialize WatchfaceTemplate          -> 9276 字节，结构完整
```

唯一缺的一步是拿到 `Watchface*` 或让 `GetWatchfaceByName` 成功。

## 19. GetSizeByName 的返回值分析

`GetSizeByName`（0x1fa448，1340 字节）反汇编结尾显示正常路径没有明显的 `x0/x1` 返回值设置，异常路径走 `__cxa_throw`（`bl 0x35f9d4`），说明它要么返回一个结构体、要么在正常路径通过 `sret`（x8 指向的隐藏参数）写回。

`GetWatchfaceByName` 里 `bl GetSizeByName` 之后直接 `x19 = x0` 并 `cbz`，说明调用方把 `x0` 当作指针或状态值使用。实测 `getwf("390x390")` 和 `getwf("watchface_390x390")` 都返回 0，而模板序列化确认 map 里确实存在 `watchface_390x390`（390x390）和 `watchface_800x800`（800x800）两条，所以宽高提取这一步对这两个名字都失败了。

正则 `([0-9]+)[^0-9]+([0-9]+)` 对 `390x390` 理论上完全匹配，失败原因可能是：

1. 函数用的是 `regex_match` 但输入被加上了前后缀（比如完整路径）
2. 隐藏的 `sret` 参数约定没被正确满足
3. 该函数对名字的期望格式不是 `WxH`

### 19.1 下一步

放弃通过名字查找，直接从 `WatchfaceTemplate` 的 `watchface` MapField 里取 `Watchface*`：

- `WatchfaceTemplate + 0x68` 是 `MapField`（`GetWatchfaceByName` 里 `ldr x9, [x20, #0x68]` 已确认）
- `MapField<...>::GetMap()` 有导出符号（0x274ddc 附近），返回 `std::map` 引用
- `std::map` 的遍历需要 `_Rb_tree` 内部布局，或者可以尝试用 `Map` 的 `begin()`（模板内联，无符号），只能按偏移硬读

### 19.2 备选

既然 9276 字节的 `WatchfaceTemplate` 序列化已经落盘，可以在 Python 侧用 `watchface_fixed_pb2` 提取出 `watchface_390x390` 对应的 `Watchface` 子消息字节，再想办法在 native 侧实例化成对象（需要正确的 protobuf 对象创建路径，前两次尝试都崩了）。

## 20. GetSizeByName 是正常的，问题在 map 遍历的宽高比较

直接 `dlsym` 调用 `GetSizeByName`（符号 `_ZN9watchface13GetSizeByNameERKNSt6__ndk112basic_stringIcNS0_11char_traitsIcEENS0_9allocatorIcEEEE`），结果：

```
GetSizeByName(390x390)=0x18600000186
GetSizeByName(watchface_390x390)=0x18600000186
GetSizeByName(800x800)=0x32000000320
GetSizeByName(watchface_800x800)=0x32000000320
GetSizeByName(390)=0x0
GetSizeByName(x390x390)=0x18600000186
```

返回值不是指针，是**把宽高打包进 64 位**：`width | (height << 32)`。`0x186 = 390`，`0x320 = 800`。所以名字解析完全正常，`GetWatchfaceByName` 里的 `cbz x0` 也不会因此走失败分支。

### 20.1 GetWatchfaceByName 的遍历逻辑

```
x20 = [this+8]                    ; WatchfaceTemplate*
bl SyncMapWithRepeatedField
x9  = [x20+0x68]                  ; MapField*
x8  = [x9+0x18]                   ; size
x11 = [x9+8]                      ; capacity
cmp x11, x8
b.ls 0x1f7e6c                     ; 空则返回 0
x20 = x19 >> 32                   ; height
x12 = [x9+0x20]                   ; 元素数组
x10 = [x12 + x8*8]                ; 第一个元素
...
x8 = [x10+0x18]                   ; Watchface*
x9 = [x8+0xe8]                    ; head 指针（optional 子消息）
csel x9, x21, x9, eq              ; 为空则用默认实例
w10 = [x9+0x30]                   ; width
cmp w10, w19
cmp w9, w20                       ; 与 height 比较
```

也就是说 `Watchface` 的 `head` 是 `optional` 子消息，存在 `+0xe8` 的指针里，宽高在 `head+0x30` / `head+0x34`。如果这个指针为空，就会退回到默认 `WFHead` 实例（宽高都是 0），比较必然失败。

模板序列化反解时 `head.width=390` 是有的，所以要么 `+0x68` 指向的是 `aod_watchface`（字段 5）而不是 `watchface`（字段 2），要么 `head` 指针在 `LoadConfig` 之后仍为空。

### 20.2 下一步

1. 确认 `WatchfaceTemplate + 0x68` 到底是 `watchface` 还是 `aod_watchface` 的 MapField
2. 如果是 aod，那 `GetWatchfaceByName` 查的就是 aod 表盘，而 aod 的 `head` 可能为空，需要换用 `GetAodWatchfaceByName`
3. 或者直接遍历 `MapField` 的数组（`[x9+0x20]` 是元素指针数组，`[x9+0x18]` 是长度），取 `[elem+0x18]` 得到 `Watchface*`，绕过名字查找

## 21. BuildContext 链路已接通，只差定位 390x390 条目

重写 `gen.cpp`，用实时 `__android_log_print` 逐步打点，完整流程确认：

```
start zip=... dir=.../work/
dlopen h=...
syms ctor parse load buildctx palette mkbin export 全部非空
obj=... ctor calling
ctor done
parse calling
parse returned 1
load calling
load done
tmpl=0x...
mf=0x...
buckets=8 arr=0x...
 b=5 entry=0x... wf=0x... w=800 h=800
wf390=0x0 wf800=... target=...
```

也就是说 `BuildContext`、`GetExcludeRedPalette`、`createBinExporter`、`Export` 四个符号都拿到了，流程已经走到「选表盘对象」这一步。

### 21.1 当前问题

按 `[tmpl+0x68]` 取到 MapField 后，`[mf+8]=8`、`[mf+0x20]=arr`，遍历 `arr[0..7]` 只有 `arr[5]` 非空，它的 `[entry+0x18]` 是 800x800 的 `Watchface*`。390x390 那条没有出现在这 8 个槽位里。

之前反汇编 `GetWatchfaceByName` 时看到它遍历后还有一层链表（`[x10]` 取 next），说明 `arr` 更可能是**哈希桶数组**，每个桶挂一条 `__hash_node` 链。直接按 `arr[b]` 当单元素处理只能拿到每个桶的头一个元素。

尝试沿 `[node]` 取 next 时读到 `0x6166686374617722`（ASCII 字符串），说明节点开头不是 `next` 指针，布局需要重新确认（libc++ 的 `__hash_node` 是 `__next_` + `__hash_` + `value`，但 `InnerMap` 可能用了自己的节点类型）。

### 21.2 下一步

1. 用 `gdb`/`lldb` 或内存 dump 确认 `arr[5]` 指向对象的完整布局
2. 或者继续沿 `arr` 往后读（`arr[8..15]`），确认数组真实长度
3. 或者换一个思路：`BuildContext` 接受 `const Watchface*`，而 800x800 那条已经拿到了，可以先用它跑通 `BuildContext` → `createBinExporter` → `Export`，确认整条链路能产出 bin，再回头解决 390 的定位

### 21.3 已确认可用

- `WFTemplateParser` 构造 + `Parse`（解压 zip）+ `LoadAllConfig`（填 map）
- `GetExcludeRedPalette`、`BuildContext`、`createBinExporter`、`Export` 四个符号全部可 `dlsym`
- map 内确实存在 800x800 的 `Watchface*`

## 22. BuildContext 调用约定修正，Export 内部崩溃

`BuildContext`（0x1f8520）第一条指令是 `mov x19, x8`，说明它返回的是**结构体**（`WFContext`），通过 ARM64 的 sret 隐藏参数 `x8` 写回，真正的参数是 `x0=this`、`x1=main`、`x2=aod`、`w3=int`、`x4=palette`。

之前把返回值当指针用，`ctx=0x...759` 是奇数（明显不是指针）。改成 C++ 结构体返回：

```cpp
struct WFContext { char pad[0x400]; };
typedef WFContext (*buildctx_t)(void *, const void *, const void *, int, void *);
...
WFContext ctx = buildctx(obj, target, nullptr, 0, pal);
void *bin = mkbin(&ctx);
```

重跑后：

```
wf390=0x0 wf800=0x7d9cfe0c32d0 target=0x7d9cfe0c32d0
pal=0x7d9d8e0e81c0
ctx done
bin=0x7d9dee0df620
```

`BuildContext` 不再崩，`createBinExporter` 也返回了对象指针。但 `Export(bin)` 崩在内部。

`Export`（0x17b438）本身很短：

```
bl 0x3710e0    ; BuildNormalWatchface
bl 0x3710f0    ; BuildAodWatchface
bl 0x371100    ; SetControl
bl 0x371110    ; ?
mov w0, #1
ret
```

崩塌在第一个 `BuildNormalWatchface` 里，说明 `WFContext` 的内容还不完整（可能是 palette 引用、`main`/`aod` 指针，或者 `WFContext` 结构体大小不够 `0x400`）。

### 22.1 现状

```
nativeCreate                 OK
Parse(zip, dir + "/")        OK (true)
LoadAllConfig                OK
watchface map 遍历            拿到 800x800 的 Watchface*
GetExcludeRedPalette         OK
BuildContext                 OK (sret 结构体)
createBinExporter            OK (返回 WFBinExporter*)
Export                       SIGSEGV in BuildNormalWatchface
```

### 22.2 下一步

1. 确认 `WFContext` 的真实大小（`BuildContext` 里写到了 `[x19+0xb4]`、`[x19+0xac]` 等，至少 0xb8，但可能更大）
2. 确认 `BuildNormalWatchface` 依赖 `WFContext` 的哪些字段
3. 390x390 的定位仍然没解决（现在用的是 800x800 的 Watchface 在跑链路）

## 23. SetHead 崩溃在 WFHead 拷贝构造

`BuildNormalWatchface` 依次调 13 个 `SetXxx` 方法，按顺序手动调用定位到**第一个** `SetHead` 就崩：

```
headId=0
（SetHead 之后无日志）
```

`SetHead`（0x17bb60）的代码：

```
ldp x22, x8, [x0, #0x28]   ; x22 = [exporter+0x28] 缓冲区, x8 = [exporter+0x30] = ctx->main
ldr x8, [x8, #0xd0]        ; main + 0xd0
cmp x8, 0
csel x1, x9, x8, eq        ; 为空时用默认实例 x9
bl 0x371210                ; WFHead::WFHead(const WFHead&)  拷贝构造
```

`0x371210` 解析出来是 `_ZN9watchface6WFHeadC1ERKS0_`。

问题在于 `[main + 0xd0]` 到底是什么。之前确认 `head` 指针在 `Watchface + 0xe8`（`GetWatchfaceByName` 里 `ldr x9, [x8, #0xe8]` 后读 `+0x30` 得到 width），而 `SetHead` 用的是 `+0xd0`。两者不一致，说明 `+0xd0` 要么是别的字段，要么 `ctx->main` 并不是我以为的那个 `Watchface*`。

如果 `+0xd0` 不是 `WFHead*`，传给拷贝构造的就是一个非法指针，直接 SIGSEGV。

### 23.1 下一步

1. 确认 `Watchface` 各字段的真实偏移（`head`、`background`、`status`、`time` 等）
2. 检查 `ctx->main` 是否真的指向 `target`（可以在 `BuildContext` 之后读 `*(void**)((char*)&ctx + 0)`)
3. 如果 `+0xd0` 确实是 head 的位置，那 `+0xe8` 就是别的字段，之前找到 800x800 的那个 `wf` 可能不是 `Watchface*`

### 23.2 已确认

- `BuildContext` sret 调用约定正确，不崩
- `createBinExporter` 返回有效 `WFBinExporter*`
- 13 个 `SetXxx` 符号全部能 `dlsym` 到
- 崩溃点从 `Export` 缩小到 `SetHead`，再缩小到 `WFHead` 拷贝构造

## 24. map 条目布局的两次假设都被排除

### 24.1 假设一：`arr[b]` 是元素，`[arr[b]+0x18]` 是 `Watchface*`（指针）

之前按这个读，得到 `wf=0x7d9cfe0c32d0`，`[wf+0xe8]` 读出了 `head`（宽高 800）。但继续读 `wf+0xc0`、`+0xc8`、`+0xd0` 全是 0，读 `wf+0xd8` 直接 SIGSEGV。

同一个对象不可能 `+0xe8` 可读而 `+0xd8` 不可读，说明 `0x7d9cfe0c32d0` 指向的并非一个完整 `Watchface` 对象，之前读到的「800」可能是相邻内存里的巧合。

### 24.2 假设二：`arr[b]+0x18` 是内联的 `Watchface` 对象

改成把 `arr[b]+0x18` 当地址用（不取指针），然后读 `+0xd0` 当 `head`，结果在遍历阶段直接崩，说明 `arr[b]+0x18` 也不是 `Watchface` 对象的起始。

### 24.3 结论

`MapField` 内部结构比预期复杂。`[mf+8]=8`、`[mf+0x20]=arr` 可能是 `InnerMap` 的桶数组，`arr[b]` 是 `__hash_node*`，节点里同时有 `__next_`、`__hash_` 和 `key/value`，而 key 是 `std::string`（24 字节 SSO），value 是 `Watchface`（内联或指针）。之前读 `[node]` 读到 ASCII 字符串（`0x6166686374617722`）也印证了节点开头不是 `next`。

### 24.4 下一步

用 `WatchfaceTemplate::SerializeToArray` 导出的 9276 字节作为唯一可信数据源：

1. Python 侧用 `watchface_fixed_pb2` 精确解析出 `watchface_390x390` 的 `Watchface` 子消息字节
2. native 侧用 `WatchfaceTemplate::ParseFromArray` 反序列化到一个**新建的 `WatchfaceTemplate` 对象**（protobuf 自己建对象、自己填 map，不碰手工布局）
3. 再通过已知的 `WatchfaceTemplate` 访问路径取 `Watchface*`

这条路的优势是完全不依赖 `InnerMap` 的内部布局，全部交给 protobuf 运行时处理。

### 24.5 备注

当前 `Export` 链路本身已经验证到 `SetHead`，崩溃只发生在「取哪个 Watchface 对象」这一步，与 `BuildContext`/`createBinExporter`/`SetXxx` 无关。

## 25. 关键怀疑：+0x68 可能指向 aod_watchface 而不是 watchface

回看 `GetWatchfaceByName` 的遍历代码，它从 `[x20+0x68]` 取 MapField，而这个 `x20` 是 `[this+8]`（`WatchfaceTemplate*`）。

`WatchfaceTemplate` 的字段定义：

```proto
message WatchfaceTemplate {
  optional WFTemplateInfo info = 1;
  repeated WatchfaceEntry watchface = 2;      // map<string, Watchface>
  optional WFProject project = 3;
  optional WFStyle custom_style = 4;
  repeated AodWatchfaceEntry aod_watchface = 5; // map<string, Watchface>
}
```

序列化数据反解结果是 `watchface` 有 2 条（`watchface_390x390` 390x390、`watchface_800x800` 800x800），`aod_watchface` 有 1 条（`watchface_390x390` 390x390）。

但 protobuf 生成代码里，两个 map 字段在对象内的偏移是编译器决定的。`+0x68` 到底是 `watchface` 还是 `aod_watchface`，仅从反汇编无法确定。

如果 `+0x68` 指向的是 `aod_watchface`，那么：

- `GetWatchfaceByName` 查的是 aod 表盘
- aod 表盘的 `head` 可能为空（AOD 通常只保留时间和电量）
- 宽高比较必然失败

这就能解释为什么 map 里明明有 390x390 却查不到。

### 25.1 验证方法

1. 在 native 里分别读 `[tmpl+0x68]` 和后面几个可能的偏移，打印各自的 `buckets`、`arr`、以及第一个条目的 `watchface` 宽高
2. 或者直接反汇编 `WatchfaceTemplate::ByteSizeLong`（0x251bb4）和 `SerializeToArray` 相关代码，确认 `watchface` 字段在序列化时的字段号，再对照内存偏移

### 25.2 如果确认是 aod

那正确做法是：

- 找到 `watchface`（字段 2）对应的 MapField 偏移
- 用 `GetWatchfaceByName` 之外的方式取 `Watchface*`
- 或者直接调 `GetAodWatchfaceByName` 的姊妹方法

### 25.3 备注

`SetHead` 用的 `[main+0xd0]` 和 `GetWatchfaceByName` 用的 `[wf+0xe8]` 不一致，同样可能是「取错了对象」导致的连锁现象。根源可能都在同一处：`+0x68` 指向错误的 map。

## 26. 模板对象字段偏移实测

读取 `WatchfaceTemplate` 对象从 `+0x58` 到 `+0x90` 的指针槽：

```
tmpl+0x58 = 0x0
tmpl+0x60 = 0x0
tmpl+0x68 = 0x7d9dae0de050   <- 堆上分配的 MapField，有数据
tmpl+0x70 = 0x7d9bf25daf58   <- lib 静态区地址，空默认实例
tmpl+0x78 = 0x0
tmpl+0x80 = 0x0
tmpl+0x88 = 0x0
tmpl+0x90 = 0x0
```

结论：

- `+0x68` 是唯一一个**堆分配且包含数据**的 MapField
- `+0x70` 指向库的静态区，是空 map 的共享默认实例

这与序列化结果（`watchface` 2 条、`aod_watchface` 1 条）对不上——按理两个 map 都该有数据，但只有一个被分配了。

可能的解释：

1. `+0x68` 是 `watchface`（2 条），`aod_watchface` 因为数据为空或被合并，指向默认实例
2. `+0x68` 是 `aod_watchface`（1 条），`watchface` 没被正确解析
3. protobuf 的 map 字段在对象内还有一层间接（比如 `MapFieldBase` 的 `repeated_field_` 指针），`+0x68` 指向的不是最终 map

之前读 `[entry+0x18]` 得到的对象宽高都是 0（这次 `wf390=0 wf800=0`），说明这个偏移处的数据不是 `Watchface*`。

### 26.1 结论

`MapField` 的 `buckets=8`、`arr` 有效，但条目解析方式始终不对。继续靠偏移猜下去效率很低。

### 26.2 建议的收尾方向

1. **放弃手工遍历**，改用 `WFTemplateParser::ExportPreview`（不依赖 `watchface` map 的宽高匹配）
2. 或者在 Python 侧把 9276 字节里 `watchface_390x390` 的 `Watchface` 子消息完整提取并手工构造成 C++ 可用的数据，绕过整个 map
3. 或者回到最初那条已被验证的路：**一台能 root 的安卓设备 + GitHub 上 Meetoul 的方法**，把 zip 放进 App 私有目录，让 App 自己完成 zip→bin→BLE 上传

第 3 条是唯一被第三方验证过、成功率明确的路，只是需要一台能 root 的设备。

## 27. 突破：成功生成 bin 文件

改用独立消息字节 + protobuf 正规对象创建路径，完整链路第一次跑通：

```
nativeCreate                          OK
Parse(zip, dir + "/")                 true
LoadAllConfig                         OK
wfNew() + ParseFromArray(wf390.bin)   成功
GetExcludeRedPalette                  OK
BuildContext                          OK（sret 结构体）
createBinExporter                     OK
Setup                                 OK
BuildNormalWatchface                  OK
BuildAodWatchface                     OK
```

关键突破点：

1. 之前从 map 里取 `Watchface*` 一直失败，改用「Python 侧从 9276 字节模板里抽取 `watchface_390x390` 的 `Watchface` 子消息（6999 字节），native 侧用 `Watchface::New()` + `MessageLite::ParseFromArray` 重建对象」——protobuf 自己建对象，完全绕开 map 内部布局
2. `BuildNormalWatchface` 会分配 0x1202（4610）字节缓冲区，数据指针存在 `[exporter+0x60]`，在 `Finish` 之前有效
3. 跳过 `Export`（内部含 `Finish`，会清掉缓冲区），改为手动调 `Setup` → `BuildNormalWatchface` → 读缓冲区 → `BuildAodWatchface`

产物：`watchface/watchface_normal.bin`（4610 字节）

```
head: 30393352 00000000 00000000 00000000 00000000 00000000 0000ffff ffffffff
非零字节: 385
```

开头 `30393352` 是 ASCII `"093R"`，之后大量 0，只有 385 个非零字节。

### 27.1 判断

4610 字节是**布局数据**，不含字体/背景资源。`BuildNormalWatchface` 分配的就是 0x1202 字节缓冲区，说明设计上这一层只存布局；资源可能由 `Finish` 或 `WriteAt` 写入。

`Finish` 会清空 `[exporter+0x60]`，且没有在文件系统留下新文件，说明它依赖 `Setup` 设置的输出路径，而该路径来自 `WFContext` 的某个字段，`BuildContext` 并没有填。

### 27.2 下一步

1. 找到 `WFContext` 里存输出路径的字段偏移，在 `Setup` 之前填上 `out` 目录
2. 或者继续调 `Finish` 并在它写文件时观察目标路径
3. 对比真实表盘 bin（401421 字节）的结构，确认 4610 字节的布局段是否是其前缀

### 27.3 本轮产物

- `watchface/watchface_normal.bin`：4610 字节，COROS 自己的导出器生成
- `/tmp/wf390.bin`：6999 字节的 `Watchface` protobuf 子消息

## 28. Finish 的输出路径探索

`Finish`（0x17b784，720 字节）确实会写文件，调用链里有：

```
WriteAt(int, const char*, int)   x3
std::filebuf::close()
std::ios_base::clear()
watchface::file_crc(const char*, unsigned, int)
std::ostream::sentry
```

所以 bin 的最终落盘发生在 `Finish` 里。但直接调用 `Finish` 之后文件系统没有任何新文件，说明它打开的 `ofstream` 路径为空或无效，写入失败。

尝试在 `bin+0x18` 处写入 SSO 格式的 `"out.bin"` 字符串再调 `Setup`，结果 `Setup` 直接崩。说明 `[bin+0x18]` 不是 `std::string` 对象（大概率是个裸 `char*` 或者别的结构），按 SSO 布局写会破坏它。

### 28.1 当前状态

| 产物 | 大小 | 状态 |
| --- | --- | --- |
| `watchface/watchface_normal.bin` | 4610 字节 | 只有布局段，385 个非零字节，头部 `30 39 33 52`（ASCII `093R`） |
| 真实表盘 bin（抓包） | 401421 字节 | 含全部字体和背景资源 |

### 28.2 结论

`BuildNormalWatchface` 只生成布局段（0x1202 字节），资源段由 `Finish` 里的 `WriteAt` + `file_crc` 写入完整文件。要让 `Finish` 正常工作，必须先搞清楚 `Setup` 读的路径到底存在哪个字段，以及它期望 `char*` 还是 `std::string`。

### 28.3 下一步

1. 反汇编 `Setup` 调用的 `0x1967c4`，确认它接受的是 `const char*` 还是 `std::string`
2. 如果接受 `const char*`，直接在 `bin+0x18` 存一个指向合法 C 字符串的指针
3. 确认 `Setup` 是否还需要 `ctx` 里的基础目录（`templateDir`）

### 28.4 本轮总结

从「完全无法生成 bin」到「用 COROS 自己的导出器产出 4610 字节布局数据」，核心障碍（protobuf 对象实例化、map 布局）已经全部绕开。剩下的是 `Finish` 的文件写入路径问题，属于单点问题。

## 29. 成功：完整表盘 bin 生成

### 29.1 关键修正

`Setup` 内部从 `[bin+0x58]` 取 `ctx`，再用 `ctx+0x10` 处的 `std::string` 作为输出路径。`BuildContext` 会把 `ctx+0x10` 清零，所以路径为空，`ofstream` 打开失败。

修正方式：在 `Setup` 之前对 `ctx+0x10` 做 placement new：

```cpp
std::string full = std::string(out) + "watchface.bin";
new ((char*)&ctx + 0x10) std::string(full);
```

### 29.2 完整调用链

```
nativeCreate                          OK
Parse(zip, dir + "/")                 true
LoadAllConfig                         OK
wfNew() + ParseFromArray(wf390.bin)   成功
GetExcludeRedPalette                  OK
BuildContext                          OK
createBinExporter                     OK
设置 ctx+0x10 = 输出路径
Setup                                 OK
BuildNormalWatchface                  OK
BuildAodWatchface                     OK
Finish                                OK
```

### 29.3 产物

`watchface/watchface_pace4.bin`，**169122 字节**

```
head:  30393352 00000000 90940200 a08e0000 ...
ASCII: "093R"
非零字节: 153061
tail:  c23fd9ff c23fc400 c23fd9ff c23fc42a ...
```

对比：

| 文件 | 大小 | 说明 |
| --- | --- | --- |
| 真实表盘 bin（早先抓包） | 401421 字节 | 官方表盘，资源丰富 |
| **本次生成** | **169122 字节** | 纯黑数据表盘，资源精简 |
| 中间布局段 | 4610 字节 | `BuildNormalWatchface` 单独输出 |

169122 字节里 153061 个非零字节，说明资源（字体 PNG、背景）已经完整写入。

### 29.4 意义

至此，「把自定义 zip 转换成手表可接受的 bin」这个核心问题已经完全解决，且**不需要 root 手机、不需要真实设备**，全部在 Android 15 模拟器 + NDK 交叉编译的 native wrapper 里完成。

### 29.5 剩余步骤

1. 验证 bin 格式与官方 bin 的结构一致性（头部字段、crc、资源段布局）
2. 解决 BLE 上传：A5 握手 + 分块写入
3. 或者间接路线：把生成的 bin 通过某种方式交给 App 上传

### 29.6 新增文件

- `watchface/watchface_pace4.bin`：169122 字节，完整表盘 bin
- `wfgen/jni/gen.cpp`：完整导出流程（native wrapper）
- `/tmp/wf390.bin`：6999 字节的 `Watchface` protobuf 子消息

## 30. bin 内部结构验证

对生成的 169122 字节 bin 做结构分析：

```
+00: 0x52333930  "093R"        魔数
+04: 0x00000000
+08: 0x00029490  (169104)      数据区长度（文件 169122，差 18 字节头部）
+0c: 0x00008ea0  (36512)       某个段长度（推测背景段）
+10: 0x00000000
+14: 0x00000000
+18: 0x12020000
+1c: 0x85b60000
```

- 全文没有 PNG 魔数（`89 50 4E 47`），说明资源已经被转成调色板/RGB565 位图
- 结尾是典型的 RGB565 像素数据（`c23f d9ff c23f c400 ...`），背景图确认在里面
- `+0x08` 的 169104 与文件大小 169122 正好差 18 字节（头部），自洽

结论：**bin 结构完整，资源段确实写进去了**，不是之前的空壳。

## 31. 上传前的阻塞

`tools/ble_probe2.py` 已写好，逻辑是：连接手表 → 发 `b7 00 00 00`（文件列表查询）→ 收集所有通知通道响应。

连续两次运行都返回：

```
connect error: In Progress
connected = False
```

这是 BlueZ 在手表被其它中心设备占用时的典型表现。手表的 BLE 外设同一时刻只能被一个中心连接，手机连着它时，Linux 侧的连接请求会一直挂起直到超时。

### 31.1 待用户操作

需要把手机蓝牙关闭 3-5 分钟，让手表进入可连接状态。之后运行：

```bash
cd tools && python ble_probe2.py
```

就能验证「不经过 A5 握手能否直接通信」。

### 31.2 如果必须 A5

A5 握手算法目前没有在任何一个 `.so` 里找到符号（扫过全部 52 个原生库，只有 OpenSSL 的 auth 相关符号），大概率在加密的 dex 里。如果验证结果是需要握手，就得另想办法。

## 32. 当前完整产物清单

| 文件 | 大小 | 说明 |
| --- | --- | --- |
| `watchface/black_pace4.zip` | 2.76 MB | 纯黑数据表盘源文件，已通过 COROS 解析器验证 |
| `watchface/watchface_pace4.bin` | 169 KB | 手表格式，结构完整 |
| `watchface/watchface_normal.bin` | 4.6 KB | 仅布局段（中间产物） |
| `wfgen/jni/gen.cpp` | - | zip→bin 转换的 native 实现 |
| `wfgen/wfgen.apk` | 7.9 MB | 测试用转换器 APK |
| `tools/ble_probe2.py` | - | 手表连接探测脚本 |
| `REPORT.md` | 1231+ 行 | 完整技术记录 |

## 33. A5 握手私钥排查

扫描全部 52 个原生库，查找可能的硬编码私钥：

- PEM 私钥头（`BEGIN RSA PRIVATE KEY` / `BEGIN EC PRIVATE KEY` / `BEGIN PRIVATE KEY`）：**无**
- PKCS#8 RSA 私钥 DER 特征（`02 01 00 30 0d 06 09 2a 86 48 86 f7 0d 01 01 01`）：**无**
- SEC1 EC 私钥 DER 特征（`30 77 02 01 01 04 20`）：**无**

结合前面全库符号扫描也没有任何 COROS 自己的 auth/handshake 实现，基本可以判断：

**A5 握手的密钥材料与算法都在加密的 dex 里，或者由服务器下发。**

### 33.1 一个重要的观察

早先抓包时发现过一个关键现象：App 重连手表后**没有重新做 A5 握手**，直接发 `90`、`78` 等命令，手表正常响应。

这说明 A5 握手**不是每次连接都做**，只在首次绑定/配对时执行一次。之后手表记住了绑定关系，后续连接直接放行。

如果这个判断成立，那么 Linux 这边只要连上手表，**可能不需要 A5 就能直接发命令**。这正是 `ble_probe2.py` 要验证的第一件事。

### 33.2 当前唯一阻塞

手表的 BLE 外设被手机占用，Linux 侧连接请求一直 `In Progress`。需要手机蓝牙关闭 3-5 分钟。

### 33.3 无法绕过的部分

如果验证结果是「必须 A5」，那就需要：

- 在能跑 App 的环境（模拟器）里让 App 完成握手，再把会话密钥导出，或者
- 找到 App 与手表之间握手数据的生成逻辑（在加密 dex 里）

前者需要模拟器具备真实蓝牙能力（目前不具备），后者需要脱壳（目前卡在指令抽取）。

## 34. 安装表盘协议帧统计

`captures/frames_install1.txt` 共 164 帧，命令分布：

- `0x78`：160 帧（主体）
- `0xb7`：4 帧（文件列表查询）

### 34.1 0x78 帧结构

典型帧（21 字节）：

```
78 00 46 00 00 00 00 00 30 d8 bc 00 00 22 24 0d 36 b6 01 03 4d
```

后继帧的地址字段按 `0x30` 递增：

```
78 00 46 00 30 00 00 00 30 d8 8c 00 00 e5 55 44 36 b6 01 03 78
78 00 46 00 60 00 00 00 30 d8 5c 00 00 18 61 7d 36 b6 01 03 f0
```

响应固定为 9 字节（`78 00 00 01 f0 1a 01 03 0f`）加 6 字节（`78 00 01 01 46 48`）。

推测 `0x78` 是分块写入命令，块大小 0x30（48 字节），地址字段逐块递增。这正好对应 bin 的 169122 字节需要约 3500 帧。

### 34.2 上传流程草案

1. `b7 00 00 00` 查询文件列表，确认目标槽位和文件名
2. 按 0x30 字节分块发 `78` 帧，逐块递增地址
3. 全部发送完毕后发一条提交/校验命令（可能带 crc）

具体字段含义（`46`、`d8`、`b6`、`03` 等）还需要更多样本对照，但这些都可以在手表空闲时通过实际测试确定。

## 35. 当前阻塞点汇总

唯一阻塞：**手表被手机占用，Linux 侧无法建立 BLE 连接**。

已就绪：

- 完整 bin（169122 字节，结构验证通过）
- 连接探测脚本 `tools/ble_probe2.py`
- 协议帧分析（`0x78` 分块写入，块大小 0x30）

待用户操作：关闭手机蓝牙 3-5 分钟。

## 36. 手表可被扫描到，但拒绝新设备连接

关闭手机蓝牙后重新扫描，手表出现在广播里：

```
[NEW] Device AA:BB:CC:DD:EE:02 COROS PACE 4 XXXXXX
```

但连接仍然失败：

```
bluetoothctl info:  Paired: no  Trusted: no  Connected: no
connect:  Failed to connect: org.bluez.Error.InProgress
pair:     无后续输出（超时）
```

### 36.1 判断

手表已经和手机完成过 BLE 绑定（bonding），固件只接受已绑定中心设备的加密连接。新的中心设备（Linux）发起连接时，因为缺少链路密钥（LTK），握手被拒绝，BlueZ 侧表现为 `InProgress` 后超时。

这种情况下 `pair` 也无法完成，因为手表侧不主动接受新的配对请求。

### 36.2 可选出路

1. **在手表上解除与手机的配对**，然后让 Linux 重新配对
   - 手表端：设置 → 手机 → 解除配对
   - 代价：手机 App 需要重新绑定手表（COROS 的运动数据保存在账号云端，解绑重绑通常不丢数据，但需要重新走一次配对流程）
2. **换一条完全不同的路**：用一台能 root 的安卓设备，把 zip 放进 App 私有目录，让 App 自己完成转换和上传
3. **继续在协议层想办法**：如果能拿到手表的绑定密钥（在手机里），理论上可以复现连接，但手机无 root 拿不到

### 36.3 当前状态

- 完整 bin 已生成并通过结构验证（169122 字节）
- 手表可被扫描，但因绑定关系拒绝新设备
- 手机蓝牙已临时关闭（`cmd bluetooth_manager disable`），需要恢复

## 37. 配对成功，但所有命令无响应 —— 确认需要 A5 握手

关闭手机蓝牙后：

1. 手表恢复广播（`AA:BB:CC:DD:EE:02`）
2. `pair` 触发 passkey 确认，agent 回答 yes 后 **`Pairing successful`、`Paired: yes`、`Connected: yes`**
3. GATT 服务发现完整，找到全部特征

然后依次尝试：

| 操作 | 结果 |
| --- | --- |
| `start_notify`（DBus） | 无错误，但收不到数据 |
| 直接写 CCCD（DBus `WriteValue`） | `org.bluez.Error.NotSupported` / `Write not permitted` |
| `bluetoothctl` 的 `notify on` | **`Notify started` 成功** |
| `bluetoothctl write`（write-without-response 特征） | `org.bluez.Error.NotSupported` |
| `bluetoothctl acquire-write` | **`AcquireWrite success: fd 8 MTU 512`** |
| 用 fd 写 `0xb7 0x00 0x00 0x00` | `Attempting to write fd 8`，无报错 |

五个通知通道（`char0018`、`char001e`、`char0024`、`char0047`、`char0042`）全部 `Notify started`，然后写入 `b7 00 00 00`，**没有任何通道收到数据**。

同样的测试对 `90 00`（版本查询）也无响应。

### 37.1 结论

手表接受了 BLE 连接和配对，但**不响应任何未经 A5 握手的应用层命令**。A5 握手是强制的前置步骤，不是可选项。

A5 握手的算法和密钥材料不在任何一个原生库里（52 个 so 全部扫描过，无 auth/handshake 符号、无硬编码私钥），只能在加密的 dex 里或由服务器下发。

### 37.2 当前唯一可行路线

**一台能 root 的安卓设备**：

1. 安装 COROS App，登录同一账号
2. 在 App 里创建一个自定义表盘（任意内容）
3. App 会把 zip 写到 `/data/user/0/com.yf.smart.coros.dist/files/coros/template/<id>.zip`
4. 用我们做好的 `black_pace4.zip` 替换它，删掉同名缓存目录
5. 在 App 里选择该表盘 → 发送到手表

这条路线不需要逆向 A5、不需要手工构造 bin、不需要解析协议。GitHub 上 Meetoul/coros-watchface 的 README 完整记录了这套流程。

### 37.3 已完成的准备工作

- 纯黑数据表盘 zip（`watchface/black_pace4.zip`，2.76 MB）
- zip→bin 转换链路（备用，一旦拿到绑定密钥可用）
- 完整协议分析（`REPORT.md` 前 37 节）

---

## 38. 模拟器蓝牙桥：不需要 root 手机，也不需要逆向 A5

第 37 节得出的结论是"需要一台能 root 的安卓设备"。这个结论在 2026-10-20 被推翻了：
**Android 模拟器可以接管宿主机真实的蓝牙适配器**，于是 App 自己完成 A5 握手，我们一行协议代码都不用写。

### 38.1 关键事实：模拟器自带蓝牙模拟

Android Emulator 37.3.4.0 启动日志里就有：

```
INFO | Activated packet streamer for bluetooth emulation
```

进入 guest 检查：

```bash
adb shell cmd bluetooth_manager enable
adb shell dumpsys bluetooth_manager
```

```
enabled: true   state: ON   address: XX:XX:XX:XX:BB:BB
feature:android.hardware.bluetooth
feature:android.hardware.bluetooth_le
```

也就是说 guest 里已经有完整的 Android 蓝牙栈，只是背后的控制器是 netsim 里的虚拟 rootcanal，
扫不到任何真实设备。

### 38.2 Bumble 暴露的两条路

Google 的 [Bumble](https://github.com/google/bumble) 通过 `android-netsim` transport 支持两种模式：

- `mode=host`：Bumble 作为 host 栈，连到模拟器的虚拟控制器
- `mode=controller`：Bumble 自己扮演虚拟控制器，让模拟器连它

我们用的是第二种，把真实适配器桥进去：

```bash
bumble-hci-bridge android-netsim:127.0.0.1:8877,mode=controller hci-socket:0
emulator -packet-streamer-endpoint 127.0.0.1:8877 -avd <AVD>
```

参考：[Bumble - Android Platform](https://google.github.io/bumble/platforms/android.html)

### 38.3 完整实测步骤

```bash
# 1. 装 Bumble
python3 -m venv .venv-bumble
.venv-bumble/bin/pip install 'bumble[android]'

# 2. 让内核蓝牙栈放手（否则 HCI_CHANNEL_USER 报 EBUSY）
sudo systemctl stop bluetooth
sudo btmgmt power off

# 3. 起桥接（必须以 root 运行，HCI_CHANNEL_USER 需要 CAP_NET_ADMIN）
sudo .venv-bumble/bin/bumble-hci-bridge \
     android-netsim:127.0.0.1:8877,mode=controller hci-socket:0

# 4. 让模拟器连桥，而不是自己起 netsim
emulator -avd <AVD> -packet-streamer-endpoint 127.0.0.1:8877 \
         -feature -WiFiPacketStream,-Uwb
```

### 38.4 两个致命的坑

**坑一：proto 字段搞反，guest 会静默超时**

模拟器的 gRPC `PacketRequest` 里有两个并列字段：

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `hci_packet` | HCIPacket 消息 | **蓝牙** |
| `packet` | bytes | **WiFi** 的裸包 |

Bumble 0.0.236 的 controller 模式只处理 `hci_packet`，收到 `packet` 会打印
`Unexpected request type: packet`。**回包也必须用 `hci_packet`**——如果回 `packet`，
模拟器不认，guest 内核会表现为：

```
Bluetooth: hci0: Opcode 0x0c03 failed: -110
```

`0x0c03` 就是 HCI_RESET，`-110` 是 ETIMEDOUT，每 5 秒重试一次，蓝牙永远开不起来。

**坑二：WiFiPacketStream 必须关掉**

`-packet-streamer-endpoint` 是全局的，WiFi 的虚拟控制器也会连过来。
Bumble 只接受 `ChipKind.BLUETOOTH`，遇到 WiFi chip 会回 `Unsupported chip type`，
然后模拟器侧报：

```
WARNING | Unexpected packet error: "Unsupported chip type"
WARNING | Netsim Wifi ipv4:127.0.0.1:8877 is gone due to Unexpected <class 'AssertionError'>
```

整个模拟器直接 abort（core dumped）。必须加 `-feature -WiFiPacketStream,-Uwb`。

另外 Bumble 的 `pump_loop` 里原本是 `assert self.sink is not None`，
在 sink 还没分配时收到包会直接抛异常打崩 gRPC 流，需要改成丢弃并记日志。

### 38.5 验证通过

桥接成功后，guest 里看到的蓝牙地址是真实适配器的：

```
Bluetooth Status
  enabled: true
  state: ON
  address: XX:XX:XX:XX:AE:26        <- 与本机适配器尾段一致
```

配对手表时 HCI 层的完整过程（来自 bridge 日志）：

```
HCI_LE_EXTENDED_CREATE_CONNECTION_COMMAND
HCI_LE_ENABLE_ENCRYPTION_COMMAND
HCI_ENCRYPTION_CHANGE_EVENT
```

`dumpsys bluetooth_manager` 里出现：

```
Bonded devices:
  AA:BB:CC:DD:EE:03 [ LE ][ 0x000704 ] COROS PACE 4 XXXXXX
```

**A5 握手由 App 自己完成，我们完全不需要知道算法。**

---

## 39. 表盘写入：替换 App 的模板 zip

### 39.1 App 的真实流程

在 App 里点 `SEND TO WATCH`，观察文件系统变化（毫秒级跟进）：

```
[1] bgPath
[2] <id>.zip  <id>_out  <id>_unzip  bgPath
```

拆开看：

| 路径 | 内容 |
| --- | --- |
| `coros/template/<id>.zip` | 从服务器下载的模板，2,773,314 B |
| `coros/template/<id>_unzip/` | 解压结果：`info.json`、`watchface_390x390/`、`watchface_800x800/`、`custom/` |
| `coros/template/<id>_out/export.bin` | native 转换产物，662,963 B，直接走 BLE |

App 的日志把发送过程暴露得很清楚：

```
I WatchFaceHelper: sendWatchTransaction size = 298765, sent = 298765
E WatchFaceHelper: sendWatchTransaction stopCode = [0, 1, 0x7808000001]
I CorosWatchfaceDetailActivity: SyncStatus.ST_FINISHED
```

`stopCode = [0, 1, 0x7808000001]` 是成功标志。

### 39.2 替换方法

前提：模拟器 `adb root` 可用（google_apis 镜像支持）。

```bash
D=/data/data/com.yf.smart.coros.dist/files/coros/template
ID=<模板 id>

adb root
adb push my_watchface.zip $D/$ID.zip
adb shell "chown u0_a169:u0_a169 $D/$ID.zip; rm -rf $D/${ID}_unzip $D/${ID}_out"
```

关键是**删掉 `_unzip` 和 `_out`**，强制 App 重新解压和重新转换。
实测重发时 App **不会**覆盖已存在的 `<id>.zip`（md5 前后一致），所以替换是安全的。

### 39.3 背景图的真正来源

第一版只改了 `watchface_390x390/background.png`（390x390，1-bit palette），
结果**只有数据层更新，背景还是旧照片**。

真正被合成进表盘的背景源是：

```
custom/custom_bg.png     961x961  8-bit RGBA   833,105 B
```

这个是用户上传的原图，App 转换时拿它重新生成 390/800 的 background。
所以三处都要换：

| 文件 | 尺寸 | 格式 |
| --- | --- | --- |
| `custom/custom_bg.png` | 961x961 | RGBA |
| `watchface_customize.png` | 800x800 | RGBA |
| `watchface_390x390/watchface_customize.png` | 1000x1000 | RGBA |
| `watchface_390x390/background.png` | 390x390 | 1-bit palette |

换成纯黑后，export.bin 从 298,749 B 掉到 130,998 B，可以反推背景数据确实换了。

### 39.4 触发重发的坑

表盘一旦是当前表盘，详情页按钮会变成 `CURRENT` 且 `enabled="false"`，点不动。

绕法是先给另一个表盘点一次 `SEND TO WATCH`，让目标表盘不再是 current，
再回来，按钮就变回 `SEND TO WATCH`。

这一步有个陷阱：发送完成后 UI 会停留在详情页，`KEYCODE_BACK` 有时会被吞掉，
脚本连续操作会点到错误位置。**必须每步 dump 一次 UI 确认位置再点**。

---

## 40. 自定义表盘格式补充

### 40.1 字库真实像素

`config.txt` 里写的字号是目录名，实际像素完全不同：

| 目录 | 真实像素 | 宽/位 |
| --- | --- | --- |
| `01` | 39x69 | 39 |
| `38x38` | 21x46 | 21 |
| `40x40` | 16x34 | 16 |
| `50x50` | 39x69 | 39 |

`40x40` 是最小档，`50x50` 和 `01` 实际一样大。

### 40.2 中文标签只能烧进背景图

`config.txt` 里没有任何"文字标签"字段，214 个段全是数值/图标的位置。
想在表盘上显示"心率"这种文字，唯一办法是**把文字画进 `custom_bg.png`**，
数值矩形右移避开。

生成流程（Pillow + Noto Sans CJK）：

```python
img = Image.new('RGB', (390, 390), (0, 0, 0))
d = ImageDraw.Draw(img)
font = ImageFont.truetype('/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc', 24)
for text, yc in [('心率', 196), ('步数', 156)]:
    d.text((62, yc), text, font=font, fill=(255, 255, 255), anchor='lm')
```

注意 `watchface_390x390/background.png` 必须是 1-bit palette（colortype 3），
用 P 模式 + `putpalette` + `save(bits=1)` 生成。

### 40.3 圆屏对齐

圆形屏幕，390x390 正方形里有效区域是圆。内容纵向排 7 行时，
底部行可用宽度会明显收窄：

```
y=340 -> dy=145 -> dx=130 -> 安全 x 范围 65..325
```

所以底部行的标签起点不能早于 x=62。

纵向 7 行方案（390 坐标）：

| 行 | 内容 | y 范围 |
| --- | --- | --- |
| 时间 | 大字号，水平居中 | 20–89 |
| 日期 | 中文星期 + 月日 | 96–136 |
| 步数 | | 136–176 |
| 心率 | | 176–216 |
| 电量 | | 216–256 |
| 锻炼 | 时/分两块 | 256–296 |
| 消耗 | | 296–336 |

### 40.4 锻炼时分的间距

`exercise_hour_rect` 和 `exercise_minute_rect` 是两个独立矩形，
都是 `left|vcenter`。如果"时"的矩形给宽了（比如 70px），
里面只放 1 位数字（16px），剩下 54px 全是空隙。

收窄到两字符宽即可：

```
[exercise_hour_rect]   = {130,256,162,296}
[exercise_minute_rect] = {165,256,240,296}
```

---

## 41. 结论

到这一节为止，整条链路是：

```
自定义表盘 zip
  -> 塞进 App 私有目录 template/<id>.zip
  -> App 自己解压、调 libw4-watchface.so 转换、生成 export.bin
  -> App 自己走 A5 握手 + BLE 分块上传
  -> 手表
```

**不需要**：root 手机、逆向 A5、手工构造 bin、解析上传协议、碰固件。

**需要**：一台 Linux、一个能跑模拟器的 CPU、一个蓝牙适配器、一次 sudo。

这套方法对 COROS 的自定义表盘格式有效，对其他品牌不通用。
