#!/usr/bin/env bash
# 把自定义表盘 zip 推进 App 私有目录，让 App 重新转换并发送。
#
# usage: send_to_watch.sh <template-id> <watchface.zip>
#
# 注意：执行前必须先 adb root（google_apis 镜像支持）。
# 注意：目标表盘如果是当前表盘，按钮会变灰，需要先在 App 里发别的表盘。
set -euo pipefail

ID="${1:?需要 template id}"
ZIP="${2:?需要表盘 zip}"
S="${ADB_SERIAL:-emulator-5556}"
D=/data/data/com.yf.smart.coros.dist/files/coros/template

adb -s "$S" push "$ZIP" "$D/$ID.zip"
adb -s "$S" shell "chown u0_a169:u0_a169 $D/$ID.zip; rm -rf $D/${ID}_unzip $D/${ID}_out"

echo '已替换。现在在 App 里对该表盘点 SEND TO WATCH。'
echo '发送成功的日志特征：'
echo '  I WatchFaceHelper: sendWatchTransaction size = N, sent = N'
echo '  E WatchFaceHelper: sendWatchTransaction stopCode = [0, 1, 0x7808000001]'
echo '  I CorosWatchfaceDetailActivity: SyncStatus.ST_FINISHED'
