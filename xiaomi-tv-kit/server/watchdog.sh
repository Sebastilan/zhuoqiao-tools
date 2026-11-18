#!/bin/sh
# 每 10 秒跑一次(见 systemd/tv-watchdog.service)。小米会杀第三方 App、待机清掉辅助服务:
# 1) WireGuard 掉了 → 原地重装,触发系统 Always-on VPN 后台重连;2) 自制桌面的主页键接管被清 → 加回;3) 给桌面写网络灯状态
DIR=$(cd "$(dirname "$0")/.." && pwd); [ -f "$DIR/.env" ] && . "$DIR/.env"
: "${TV_ADB:?在 .env 里填 TV_ADB}" "${API_PORT:=9097}"
A="adb -s $TV_ADB"
adb connect "$TV_ADB" >/dev/null 2>&1
[ "$($A get-state 2>/dev/null)" = "device" ] || exit 0   # 电视关机或 ADB 关闭:不处理
pid=$($A shell pidof com.wireguard.android </dev/null 2>/dev/null)
rules=$($A shell ip rule show </dev/null 2>/dev/null | grep -c uidrange)
if [ -n "$LAUNCHER_PKG" ]; then
  svc="$LAUNCHER_PKG/.HomeGuard"
  acc=$($A shell settings get secure enabled_accessibility_services </dev/null | tr -d '\r')
  case "$acc" in *"$svc"*) ;; *)
    case "$acc" in null|"") new=$svc;; *) new="$acc:$svc";; esac
    $A shell settings put secure enabled_accessibility_services "$new" </dev/null
    $A shell settings put secure accessibility_enabled 1 </dev/null
    echo "$(date '+%F %T') 主页键接管被清,已加回";; esac
  ST=/tmp/tvkit_net.ts
  if [ ! -f $ST ] || [ $(( $(date +%s) - $(stat -c %Y $ST) )) -ge 60 ]; then touch $ST
    if [ -n "$pid" ] && [ "$rules" -gt 0 ]; then
      now=$(curl -s -m 3 127.0.0.1:$API_PORT/proxies/AUTO | python3 -c 'import sys,json;print(json.load(sys.stdin)["now"].replace("|","/").replace(chr(39),""))' 2>/dev/null)
      v="ok|${now:-?}|"
    else v=down; fi
    $A shell "settings put global tvkit_net '$v'" </dev/null
  fi
fi
[ -n "$pid" ] && [ "$rules" -gt 0 ] && exit 0
echo "$(date '+%F %T') WireGuard 掉线(pid=${pid:-无} 规则=$rules),原地重装触发 Always-on"
P=$($A shell pm path com.wireguard.android </dev/null | head -1 | cut -d: -f2 | tr -d '\r')
$A shell cp "$P" /data/local/tmp/wg.apk </dev/null && $A shell pm install -r /data/local/tmp/wg.apk </dev/null >/dev/null 2>&1
