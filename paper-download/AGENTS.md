# paper-download

给一个 DOI / 链接 / 题名,解析成 DOI,从开放获取源或出版商下载全文 PDF,并核验是不是这篇(页数、首两页的 DOI 或题名+作者、页数对得上出版社登记的页码范围);核不过不交付。单机运行,本地目录当论文库。

## 入口与参数
`python3 paper_download.py <DOI|URL|题名> [--out DIR] [--no-oa] [--no-library] [--min-confidence high|medium|low]`
- stdout 一行 JSON:`ok`、`doi`、`source`(library / open_access / publisher)、`file`(PDF 路径)、`checks`(核验明细)、`error`、`resolved`(DOI 怎么来的、把握 exact/high/medium/low)、`timing`。
- rc:0 已交付;2 没拿到(`no_module` 无对应模块 / 出版商无权限或拦截 / `verify_failed` 核验不过);3 解析不出 DOI 或把握低于 `--min-confidence`(候选在 `resolved.candidates`,拿给用户挑);1 用法错误。
- 流程:本地库(命中也重新核验,不过就重下,旧件改名 `.rejected.<时间>` 保留)→ 开放获取层(OpenAlex/Unpaywall/Semantic Scholar 候选,逐个核验)→ 出版商模块 → 若拿到的是 XML 全文则用 headless Chrome 排成 PDF(首页标明非出版社 PDF 与缺项)→ 核验 → 入库 → 复制到 `--out`。
- 出版商模块(按 DOI 前缀选):Elsevier 10.1016(API)、IEEE 10.1109、Springer 10.1007/10.1023、Nature 10.1038、APS 10.1103、PLOS 10.1371、Cambridge 10.1017、Frontiers 10.3389、MDPI 10.3390、arXiv 10.48550 —— 纯 HTTP;Wiley 10.1002/10.1111/10.1049/10.1155、IOP 10.1088、ACS 10.1021、ACM 10.1145、De Gruyter 10.1515、知网(DOI 含 /j.cnki.)、万方 10.3969 —— 要桌面浏览器;其余前缀走通用落地页(`citation_pdf_url`)。

## 依赖与安装
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo apt install poppler-utils          # pdfinfo / pdftotext,核验必需
# 可选:Chrome 或 Chromium(仅 Elsevier XML→PDF);找不到设 X2P_CHROME
```
Python ≥ 3.9(Debian/Ubuntu 上 `python3 -m venv` 报 ensurepip 缺失时先 `sudo apt install python3-venv`)。环境变量见 `.env.example`(全部可选),工具不自动读 .env,用 `export` 或 `set -a; . ./.env; set +a`。

## 缺资源清单
| 资源 | 必需/可选 | 去哪拿 | 写进哪个变量 | 缺了的表现 |
|---|---|---|---|---|
| poppler-utils | 必需 | 系统包管理器 | — | 核验全部不过,一律不交付;自检报 SKIP 并 rc=1 |
| 机构订阅网络(校园网/VPN) | 可选 | 用户所在机构 | — | 付费论文 `no_access` / 落地页被拦,只能拿到开放获取版 |
| 联系邮箱 | 可选 | 用户本人 | `PAPERDL_EMAIL` | 元数据与开放层变慢、Unpaywall 候选可能缺 |
| Elsevier API key | 可选 | https://dev.elsevier.com/apikey/manage | `ELSEVIER_API_KEY` | 10.1016 报 `no_key`(开放版仍可经开放层) |
| Serper key | 可选 | https://serper.dev | `SERPER_API_KEY` | 题名/引文输入把握常不足 high,rc=3 |
| HTTP 代理 | 可选 | 用户自有 | `PAPERDL_PROXY` | 开放层/arXiv 直连失败时无回退 |
| 桌面操作脚本 | 可选 | 用户自备(契约见下) | `DESK_ACT` | 浏览器类出版商报 `DESK_ACT not set` |
| Chrome/Chromium | 可选 | 官方安装包 | `X2P_CHROME`(找不到时) | Elsevier XML 全文报 `not_pdf_and_render_failed` |

**给 agent 的规矩**:缺就问用户,不编造 key、不借别人的;拿不到就如实报拿不到,不换任何灰色来源(盗版镜像站之类),也不拿别的论文顶替;key 只进环境变量,不写进代码、提交或回复。

**`DESK_ACT` 契约**(浏览器类出版商用):一个 Python 脚本,`python3 $DESK_ACT <步骤> -- <步骤> ...` 在**已登录机构账号、正在显示的 Chrome 窗口**上按序执行,成功 rc=0。步骤只有四种:`key <组合键>`(如 `ctrl+l`、`Return`、`Escape`、`ctrl+s`)、`type <文本>`、`sleep <秒>`、`click <x> <y>`。环境变量 `DESK_TYPE_PAUSE` 是打字间隔秒数。同目录可放 `desk_shot.py`(截屏并打印路径,失败时留证,可没有)。Linux X11 下用 `xdotool` 二十行即可实现;Chrome 要设成"PDF 直接下载不预览",下载目录设进 `PAPERDL_BROWSER_DOWNLOADS`。这套会占用屏幕键鼠,用户在用电脑时别跑。

## 验收
- 离线自检(不联网、不花钱、不要 key):`python3 -I selftest.py`,rc=0 即代码完整(断网桩下跑完路由、解析、核验与整条主线的假出版商演练)。
- 真实下载(联网,开放论文,无需任何 key):
  `python3 paper_download.py 10.48550/arXiv.1706.03762 --out /tmp/pd` → rc=0,`/tmp/pd/10_48550_arxiv_1706_03762.pdf` 15 页。
  另可试 `10.3390/s21010001`(MDPI)、`10.1371/journal.pone.0000308`(PLOS)、`10.1038/s41586-021-03819-2`(Nature 开放文章)。

## 验证状态
- **已验证(2026-10-23,本包,普通家宽、无机构订阅、无 key)**:离线自检 rc=0;arXiv(14–18s)、MDPI(2–4s)、PLOS(约 4s)、Nature 开放文章(9–11s)端到端交付且核验通过;无 Serper key 时题名输入"Attention is all you need"把握只到 medium,默认闸门如实拒交(rc=3)。
- **取决于资源**:付费论文(需机构网络);Elsevier(需 key + 订阅网络);题名解析质量(Serper key);浏览器类出版商(DESK_ACT + 已登录 Chrome);知网首次使用常需人工过一次滑块验证。
- **未验证(本包形态)**:浏览器类七家、Elsevier XML→PDF、IEEE/Springer/APS/Cambridge/Frontiers 付费文章、代理回退。同一份模块代码在作者的内部部署(机构网络)上日常在跑,但本包剥离后的形态没在那些条件下复测。

## 已知限制
- 只按 DOI 前缀选模块;未列出的出版商只走通用落地页,多数付费站会 `no_access`。未覆盖:Oxford、RSC、AIP、Taylor & Francis、SAGE、SSRN、INFORMS、World Scientific、Optica、Springer 订阅书章。
- 出版商改版会让模块失效,表现为 `no_access_or_not_pdf` / `saved_page_not_pdf`;核验兜住不会交错件,但需要改模块。
- XML→PDF 转换版不是出版社 PDF,图表与参考文献尽量保留,缺项在首页注明。
- 遵守出版商条款与机构授权范围,别批量爬取;浏览器模块对同一出版商有最小间隔限速。
- 许可证待定。
