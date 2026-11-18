# 电视上要手动设的几项(都在遥控器上完成)

1. **开发者与调试**:设置 → 关于 → 连按「产品型号」7 次 → 开发者选项里打开 USB 调试、网络调试(ADB)。真正重启后小米会把 ADB 关掉,需要再开一次。
2. **电源键改成息屏**:小米设置 → 通用设置 → 短按开关键 = 息屏。默认的「关机」实际是 STR 待机,会执行 `str kill all third app`,杀掉 WireGuard 和桌面的辅助服务。也可以用 adb:`adb shell settings put system mitv.short.power.action 0`。
3. **WireGuard 始终开启**:系统设置 → 网络 → VPN → WireGuard → 始终开启 VPN(Always-on)。看门狗靠它在重装后自动重连。
4. **Stremio 没声音**:设置 → 播放器 → 默认播放器改成 VLC(ExoPlayer 在这类电视上解不了 EAC3/AC3 杜比音轨)。
5. **自制桌面的主页键接管**:装好 launcher 后,系统设置 → 无障碍 → 打开「家·主页键接管」;或让 watchdog.sh 自动加。
