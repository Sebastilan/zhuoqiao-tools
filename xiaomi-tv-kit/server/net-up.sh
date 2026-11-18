#!/bin/sh
# 透明代理网络规则(幂等,需 root):wg-tv 进来的流量 tproxy 给 mihomo;电视的 DNS(53) 转给 mihomo DNS
set -e
DIR=$(cd "$(dirname "$0")/.." && pwd); [ -f "$DIR/.env" ] && . "$DIR/.env"
: "${WG_SERVER_ADDR:?在 .env 里填 WG_SERVER_ADDR}" "${TPROXY_PORT:=7896}" "${DNS_PORT:=1054}"
NET=$(echo "$WG_SERVER_ADDR" | cut -d. -f1-3).0/24
ip rule show | grep -q "fwmark 0x1 lookup 100" || ip rule add fwmark 0x1 lookup 100 pref 100
ip route replace local 0.0.0.0/0 dev lo table 100
nft delete table ip tvkit 2>/dev/null || true
nft -f - <<NFT
table ip tvkit {
  chain pre {
    type filter hook prerouting priority mangle; policy accept;
    iifname "wg-tv" th dport 53 accept
    iifname "wg-tv" ip daddr != $NET meta l4proto { tcp, udp } tproxy to 127.0.0.1:$TPROXY_PORT meta mark set 0x1 accept
  }
  chain dns {
    type nat hook prerouting priority dstnat; policy accept;
    iifname "wg-tv" meta l4proto { tcp, udp } th dport 53 dnat to $WG_SERVER_ADDR:$DNS_PORT
  }
}
NFT
echo "net-up ok"
