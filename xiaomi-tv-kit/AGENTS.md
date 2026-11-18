# xiaomi-tv-kit

让国内的小米电视(Android TV 9)稳定看 YouTube、Stremio、Pluto、Tubi:家里一台 Linux 服务器做翻墙出口,电视只让指定 App 走隧道,国内 App 直连;看门狗对抗小米杀后台;可选一个干净的电视桌面。

> 写给 agent(Claude Code、Codex 等)读,由你在用户的机器上部署。缺资源就问用户,不编造,不换灰色来源。

## 架构

```
电视 WireGuard App(只勾选的 App 走隧道)
   │  局域网 UDP 51821
   ▼
Linux 服务器 wg-tv ──nft tproxy──► mihomo(出口)──► 用户自己的代理节点
                    └─DNS 53 → mihomo DNS(独占端口)
   └─ watchdog.sh 每 10 秒经 adb 查电视:隧道被杀就重拉,桌面接管被清就加回
```

- 出口用 mihomo `url-test` 自动选最快节点;只认美国 IP 的服务(Pluto、Tubi)单独走美国节点组。
- 拒绝 QUIC(UDP 443),App 立刻回落 TCP,经代理更稳。
- IPv6 在隧道里一律拒绝,逼 App 走 IPv4。

## 入口与参数

| 入口 | 参数 | 作用 |
|---|---|---|
| `python3 server/gen_config.py [订阅文件] [输出文件]` | 省略时读 .env 的 `SUBSCRIPTION_FILE`、`WORK_DIR` | 生成出口配置 |
| `sudo server/net-up.sh` | 读 .env | 装 nft 规则 |
| `server/watchdog.sh` | 读 .env 的 `TV_ADB`、`LAUNCHER_PKG`、`API_PORT` | 看门狗跑一轮 |
| `sh tv/debloat.sh` | 读 .env 的 `TV_ADB` | 停用小米组件 |
| `launcher/build.sh` | 环境变量 `JAVA_HOME`、`ANDROID_HOME` | 编译桌面 APK |

全部参数见 `.env.example`(每项带用途和例值)。

## 依赖与安装

- 服务器(Debian/Ubuntu):`sudo apt install -y wireguard-tools nftables adb python3-yaml curl dnsutils && pip install -r requirements.txt`
- mihomo:https://github.com/MetaCubeX/mihomo/releases ,放到 `/usr/local/bin/mihomo`
- 桌面(可选):JDK 17(https://adoptium.net)+ Android 命令行工具,`sdkmanager "platforms;android-28" "build-tools;34.0.0"`

## 离线自检

离线自检:`./selftest.sh`(不联网、不花钱、不碰电视,输出 `selftest OK` 且 rc=0 即代码完整)。

## 目录

| 路径 | 作用 |
|---|---|
| `server/gen_config.py` | 读用户的 Clash 订阅,生成 `$WORK_DIR/egress.yaml` |
| `server/net-up.sh` | nft 透明代理与 DNS 转发(root,幂等) |
| `server/watchdog.sh` | 电视看门狗(adb) |
| `server/wg-tv.conf.example` | 服务器端 WireGuard 配置模板 |
| `server/tvkit-*.service` | 两个服务模板,`@DIR@ @WORK_DIR@ @USER@` 替换成实际值 |
| `tv/wireguard-tv.conf.example` | 电视端 WireGuard 配置模板 |
| `tv/debloat.txt` + `debloat.sh` | 停用小米广告与杀后台组件 |
| `tv/settings.md` | 必须在电视上手动设的几项 |
| `launcher/` | 可选:干净桌面(纯 Java,无 gradle) |

## 部署步骤

1. **服务器依赖**(Debian/Ubuntu):`sudo apt install wireguard-tools nftables adb python3-yaml curl`;mihomo 从 https://github.com/MetaCubeX/mihomo/releases 下载放到 `/usr/local/bin/mihomo`。
2. `cp .env.example .env`,按注释逐项填写(要问用户:电视 IP、服务器局域网 IP、订阅文件路径)。
3. `python3 server/gen_config.py`,生成出口配置。
4. 生成两对 WireGuard 密钥,填好 `server/wg-tv.conf.example` → `/etc/wireguard/wg-tv.conf`,然后 `sudo systemctl enable --now wg-quick@wg-tv`。
5. 替换 systemd 模板里的占位符,装到 `/etc/systemd/system/`,`sudo systemctl enable --now tvkit-egress tvkit-watchdog`。
6. 电视:装 WireGuard(F-Droid / 官方 APK)、YouTube 客户端(如 SmartTube)、Stremio 等;导入 `tv/wireguard-tv.conf.example` 填好后的配置,在隧道里只勾选要翻墙的 App;按 `tv/settings.md` 设好;`sh tv/debloat.sh`。
7. 可选桌面:装好 JDK 17 与 Android SDK(platforms;android-28、build-tools;34.0.0),`launcher/fetch_posters.sh && launcher/build.sh`,`adb install -r launcher/out/tvhome.apk`;在 .env 里填 `LAUNCHER_PKG=io.github.tvkit.home`。入口卡片的 App 列表在 `launcher/Home.java` 的 `APPS` / `SHOWS` 里改。

## 缺资源清单

| 资源 | 必需/可选 | 去哪拿 | 写进哪个变量 | 缺了的表现 |
|---|---|---|---|---|
| 代理节点订阅(Clash/mihomo 格式) | 必需 | 用户自己的代理服务商后台 | `SUBSCRIPTION_FILE` | gen_config 报「没有可用节点」 |
| 含美国节点 | 可选 | 同上 | 节点名匹配 `US_NODE_REGEX` | Pluto/Tubi 提示地区不可用 |
| 常开的 Linux 服务器(与电视同一局域网) | 必需 | 用户自备 | `SERVER_LAN_IP` | 电视无处可连 |
| 电视开启 ADB | 必需(看门狗) | 电视开发者选项 | `TV_ADB` | 看门狗静默跳过,隧道被杀后不会自愈 |
| JDK 17 + Android SDK | 可选(桌面) | Adoptium / Google 命令行工具 | `JAVA_HOME` `ANDROID_HOME` | 编不出桌面 |

## 验收

- 离线:`./selftest.sh` → `selftest OK`
- 服务器:`dig +short @<WG_SERVER_ADDR> -p <DNS_PORT> www.youtube.com` 返回真实 IP(不是 198.18.x);`curl -x http://127.0.0.1:7895 -s -o /dev/null -w %{http_code} https://www.google.com/generate_204` 返回 204
- 电视:`adb shell pidof com.wireguard.android` 有值;`adb shell ip rule | grep uidrange` 有规则;打开 YouTube、Pluto 能加载首页

## 验证状态

- **已验证**(2026-11-17,小米电视 A75 竞技版,Android 9):隧道分流、出口、DNS、美国组分流、看门狗重拉、桌面与主页键接管、停用清单;SmartTube、Stremio、Pluto、Tubi 首页加载正常。作者环境的选线用的是自写测速脚本,DNS 用的是国内/海外 DNS 的 IP 直连;本包换成了 mihomo `url-test` 和域名形式的 DoH(引导用 `system`),这两处**未在作者环境端到端跑过**。
- **取决于资源**:节点质量决定画质与卡顿;有没有美国节点决定 Pluto/Tubi 能否使用。
- **未验证**:其他小米型号、非小米 Android TV。

## 已知限制

- 小米只认预装桌面为默认桌面。自制桌面靠无障碍服务在小米桌面出现时切回;adb 注入的 HOME 键不走这条路,要用真遥控器验收。
- 电视真正重启后,小米会关闭 ADB,需要在电视上重新打开,之前看门狗不起作用。
- 电视版 Stremio 只认电影详情深链 `stremio:///detail/movie/<imdb>`;剧集详情深链会报找不到。
- BT 类流量经代理节点,可能违反部分服务商条款,风险由用户判断。

## 坑(现象 → 根因 → 认法)

1. **国外 App 全部转圈** → mihomo DNS 端口被本机另一个代理占用,电视拿到 198.18.x 假 IP → mihomo 日志有 `bind: address already in use`。换一个独占的 `DNS_PORT`。
2. **看一会儿就断** → 小米 PeriodicCleaner / STR 待机杀掉 WireGuard → 看门狗加 Always-on 解决;电源键设为息屏。
3. **DNS 死循环、断网约 1 分钟** → DoH 经节点出去,而节点域名又要靠 DoH 解析 → 设 `proxy-server-nameserver` 为国内 DNS(已内置)。
4. **按域名分流无效** → tproxy 只拿到 IP → 需开 sniffer(已内置)。
5. **Stremio 有画面没声音** → 改用 VLC 播放器。
6. adb 写在 shell 循环里要加 `</dev/null`,否则会吞掉 stdin;电视 shell 里带空格的参数外层要再套一层引号。
