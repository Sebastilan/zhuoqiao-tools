#!/bin/sh
# 海报不随包分发(版权不明)。需要时自己拉到 assets/poster/,文件名 = IMDb 编号;拉不到的卡片显示纯色
cd "$(dirname "$0")" && mkdir -p assets/poster
for id in $(grep -o '"tt[0-9]*"' Home.java | tr -d '"' | sort -u); do
  [ -s assets/poster/$id.jpg ] || curl -sL -m 20 -o assets/poster/$id.jpg "https://images.metahub.space/poster/medium/$id/img" && echo "$id"
done
