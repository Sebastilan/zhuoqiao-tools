#!/usr/bin/env python3
"""从你的 Clash 订阅生成电视出口 mihomo 配置。用法: python3 gen_config.py  (读 .env 或环境变量)"""
import os, re, sys, yaml

def env():
    e = dict(os.environ)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip(): e.setdefault(k.strip(), v.strip())  # 空值不覆盖默认
    return e

def build(src, e):
    proxies = [p for p in src.get("proxies", []) if p.get("type") not in (None, "direct", "reject")]
    if not proxies:
        sys.exit("订阅里没有可用节点(proxies 为空)")
    names = [p["name"] for p in proxies]
    us = [n for n in names if re.search(e.get("US_NODE_REGEX", "^(US|美国)"), n)] or names
    test = {"url": "https://www.gstatic.com/generate_204", "interval": 300, "tolerance": 50}
    server = e.get("WG_SERVER_ADDR") or sys.exit("在 .env 里填 WG_SERVER_ADDR")
    return {
        "mixed-port": 7895, "tproxy-port": int(e.get("TPROXY_PORT", 7896)),
        "allow-lan": False, "bind-address": "127.0.0.1", "mode": "rule", "log-level": "warning",
        "external-controller": "127.0.0.1:%s" % e.get("API_PORT", 9097),
        "proxies": proxies,
        "proxy-groups": [dict(name="AUTO", type="url-test", proxies=names, **test),
                         dict(name="US", type="url-test", proxies=us, **test)],
        # 透明代理只拿到 IP:嗅探 SNI/Host 还原域名,才能按域名分流
        "sniffer": {"enable": True, "sniff": {"TLS": {"ports": [443, 8443]}, "HTTP": {"ports": [80, 8080], "override-destination": False}}},
        "dns": {"enable": True, "listen": "%s:%s" % (server, e.get("DNS_PORT", 1054)), "ipv6": False,
                "enhanced-mode": "redir-host",
                "nameserver": ["https://dns.google/dns-query#AUTO", "https://cloudflare-dns.com/dns-query#AUTO"],
                # 节点自身域名用国内 DNS 解析,否则 DoH 经节点、节点又靠 DoH,死循环
                "proxy-server-nameserver": ["https://dns.alidns.com/dns-query", "https://doh.pub/dns-query"],
                "default-nameserver": ["system"]},  # 用系统 DNS 解析上面几个 DoH 域名
        # QUIC 经代理易丢包:直接拒,App 立刻回落 TCP
        "rules": ["AND,((NETWORK,UDP),(DST-PORT,443)),REJECT"]
                 + ["DOMAIN-SUFFIX,%s,US" % d.strip() for d in e.get("US_DOMAINS", "pluto.tv,plutotv.net,tubi.tv,tubitv.com,tubi.io,tubi.video").split(",") if d.strip()]
                 + ["MATCH,AUTO"],
    }

if __name__ == "__main__":
    e = env()
    src = yaml.safe_load(open(sys.argv[1] if len(sys.argv) > 1 else e["SUBSCRIPTION_FILE"], encoding="utf-8"))
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(e.get("WORK_DIR", "."), "egress.yaml")
    cfg = build(src, e)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    os.chmod(out, 0o600)
    print("写出 %s:节点 %d 个,美国组 %d 个" % (out, len(cfg["proxies"]), len(cfg["proxy-groups"][1]["proxies"])))
