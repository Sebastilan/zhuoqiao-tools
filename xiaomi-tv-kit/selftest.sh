#!/bin/sh
# 离线自检:不联网、不花钱、不碰电视。rc=0 即代码完整
set -e
cd "$(dirname "$0")"
for f in server/*.sh tv/*.sh launcher/*.sh; do sh -n "$f"; done
python3 -m py_compile server/gen_config.py
T=$(mktemp -d)
WG_SERVER_ADDR=tvkit.test python3 server/gen_config.py 测试/sample-subscription.yaml "$T/egress.yaml" >/dev/null
python3 - "$T/egress.yaml" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
g = {x["name"]: x for x in c["proxy-groups"]}
assert g["US"]["proxies"] == ["US-Node-1"], g["US"]
assert c["rules"][-1] == "MATCH,AUTO" and any(",US" in r for r in c["rules"])
assert c["dns"]["proxy-server-nameserver"] and c["sniffer"]["enable"]
PY
rm -rf "$T"
for f in AndroidManifest.xml res/xml/guard.xml Home.java HomeGuard.java; do test -s "launcher/$f"; done
echo "selftest OK"
