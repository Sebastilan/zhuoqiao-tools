#!/bin/sh
# 按 debloat.txt 停用小米组件。用法: TV_ADB=ip:5555 sh debloat.sh
DIR=$(cd "$(dirname "$0")/.." && pwd); [ -f "$DIR/.env" ] && . "$DIR/.env"
: "${TV_ADB:?在 .env 里填 TV_ADB}"
adb connect "$TV_ADB" >/dev/null
grep -v '^#' "$(dirname "$0")/debloat.txt" | awk '{print $1}' | while read -r p; do
  [ -n "$p" ] || continue
  if adb -s "$TV_ADB" shell pm path "$p" </dev/null | grep -q package; then
    adb -s "$TV_ADB" shell pm disable-user --user 0 "$p" </dev/null && echo "停用 $p"
  else echo "跳过 $p(不存在)"; fi
done
