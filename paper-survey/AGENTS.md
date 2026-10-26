# paper-survey

一段模糊的调研需求 → 本地一页摘要级文献调研(最相关 + 近两年新进展,各一段综述式总结 + GB/T 7714-2015 文献列表),可在页面上勾选、批注,按勾选批量下载。

只依据标题和摘要判断,不下载全文(下载交给另一个工具,见下)。

## 做法(一句话)
大模型写边界与 1–3 个搜索词 → 种子(谷歌学术经 Serper + OpenAlex + 经核对的奠基论文)→ 逐篇并发评分 → 选 8 篇"关键文献"当门 → 取门的参考文献与近两年施引 → 同口径评分 → 排序成文(中英摘要、[n] 可点、作者/刊名/卷期页/可选中科院分区)。

## 入口与参数
```
python3 survey.py "调研需求" [--out 目录] [--draws 6] [--verbose]
python3 survey.py --download <输出目录> [--picks 3,5,8 | --review review.json]
python3 survey.py --check-config     # 列出哪些资源已配/缺(只报变量名,不显示值)
python3 survey.py --selftest         # 离线自检
```
- 输出默认 `./surveys/<时间>/`:`index.html`(打开即看)、`result.json`、`all.json`(全部评分池)、`papers.json`(篇号索引)。
- `--draws 0` = 不用谷歌学术。
- 页面上勾选「下载这篇」并写批注,点「导出勾选与批注」得 `review.json`;再 `--download <输出目录> --review review.json` 批量下载,成功超过 3 篇另打 zip。
- 返回码:0 成功;2 缺配置/参数;3 结果结构异常(原始页仍在);4 页面里检出 key 值,已删除输出。

## 依赖与安装
只用 Python 标准库,**Python ≥ 3.12**,无需 pip。
```
cp .env.example .env   # 填变量;或直接设环境变量(优先)
python3 survey.py --check-config
```

## 缺资源清单
| 资源 | 必需/可选 | 去哪拿 | 写进哪个变量 | 缺了的表现 |
|---|---|---|---|---|
| OpenAI 兼容大模型接口 | 必需 | 任一兼容服务(OpenAI、DeepSeek、本地 vLLM/Ollama…) | `LLM_BASE_URL`(到 /v1)、`LLM_MODEL`、`LLM_API_KEY` | 退出码 2,提示缺配置 |
| Serper key(谷歌学术) | 可选,强烈建议 | https://serper.dev | `SERPER_API_KEY`(逗号分隔多个) | 只用 OpenAlex 种子,召回明显降低 |
| OpenAlex key | 可选 | https://openalex.org/settings/api | `OPENALEX_API_KEY` | 走免费额度,大批量时可能限流变慢 |
| 联系邮箱 | 可选 | 用户自己的邮箱 | `OPENALEX_MAILTO` | 不进 OpenAlex 礼貌池,稍慢 |
| Semantic Scholar key | 可选 | https://www.semanticscholar.org/product/api#api-key-form | `S2_API_KEY` | 缺摘要兜底与参考文献兜底更易被限流 |
| 中科院分区表 | 可选 | 用户自有(授权不明,本包不分发) | `CAS_TABLE_CSV`(本地 CSV 路径) | 页面不显示分区 |
| 论文下载工具 | 可选 | 开源工具 `paper-download`(同仓库),或用户自有工具 | `PAPER_DOWNLOAD_CMD`(模板,`{input}` `{out}`) | `--download` 退出码 2 |

分区 CSV 表头(大小写不敏感):`journal, issn, eissn, zone, top, if, jcr_zone`,至少 `journal` 与 `zone`。

**给 agent 的规矩**:缺资源就问用户要,不编造 key、地址或数据;不换成灰色来源(镜像站、盗版库等);key 只写进 `.env` 或环境变量,不打印、不提交。

## 验收
```
python3 survey.py --selftest                      # rc=0 即代码完整(不联网、不花钱、不需 key)
python3 survey.py --check-config                  # 必需项都「已配」才 rc=0
python3 survey.py "联邦学习中的拜占庭鲁棒聚合" --out /tmp/ps-check   # 约 1–2 分钟,rc=0,打开 /tmp/ps-check/index.html
```

## 验证状态
- **已验证**(2026-10-23,原作者环境):离线自检 rc=0;端到端「联邦学习中的拜占庭鲁棒聚合」rc=0,111 秒,105 篇(必读 65),作者与中文摘要 105/105;配置为 OpenAI 兼容接口(关思考的快模型)+ Serper + OpenAlex key + S2 key。
- **取决于资源**:召回与速度取决于是否有 Serper、OpenAlex/S2 限流额度、大模型并发;中科院分区取决于用户自备表;批量下载取决于 `PAPER_DOWNLOAD_CMD` 指向的工具(自检只用假下载器验证了调用、打包与报告)。
- **未验证**:Windows / macOS;Python 3.12 以外版本(作者环境 3.14);非 DeepSeek 系模型的评分口径;不配 Serper 时的召回数值。

## 已知限制
- 摘要级:只看标题与摘要;中文为机器翻译,仅供参考。
- 自测基准(BCP 求解 CVRP,出处综述不当起点):全池召回约 59–61%,必读召回 35–43%;核心论文约一半被评为可能/圈外,评分口径仍待调。
- OpenAlex 响应时快时慢,耗时 30–120 秒波动;无本地缓存。
- 作者先取 OpenAlex,缺时从谷歌学术 byline 拆;拆不出人名就留空,不编。刊名被截断时留空。
- 大模型调用量:一次约 300–600 次,按你的接口计价。
