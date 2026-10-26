# pdf2md

批量 PDF 转 Markdown(公式/表格保留),底层 MinerU 官方 API;本地目录缓存,相同 PDF 不重复花配额。

## 入口与参数
`python3 pdf2md.py a.pdf [b.pdf ...] [--mode vlm|pipeline] [--language en] [--out DIR] [--no-cache] [--multi]`
- 输出:`<out>/<pdf名>/full.md`(及图片);stdout 为 JSON 结果列表;rc 0=全成功,1=配置/调用错误,2=部分失败。
- vlm(默认,公式表格准)/pipeline(更快);单次提交按 45 个/批自动分批防限流。
- `--multi`:`MINERU_TOKENS` 多 key 并行。缓存键=PDF 内容 sha256+模式;`--no-cache` 不读不写。

## 依赖与安装
Python>=3.8 与系统 `curl`(用于预签名 PUT 上传)。无需 pip 安装(`requirements.txt` 仅作说明)。

## 缺资源清单
| 资源 | 必需/可选 | 去哪拿 | 写进哪个变量 | 缺了的表现 |
|---|---|---|---|---|
| MinerU API key | 必需 | https://mineru.net/apiManage(用户自行注册) | `MINERU_TOKEN`(环境变量或同目录 `.env`) | 报「缺 MINERU_TOKEN」,rc=1 |
| 多个 key | 可选 | 同上,多账号 | `MINERU_TOKENS` | `--multi` 退化为单 key |
| 缓存目录 | 可选 | 自定 | `PDF2MD_CACHE` | 默认 `~/.cache/pdf2md` |

给 agent 的规矩:缺 key 就问用户要,不编造,不去用来路不明的 key 或灰色来源;不要把 key 写进代码、提交或回复。

## 验收
- 离线自检(不联网、不花钱、不需 key):`python3 -I selftest.py`,rc=0 即代码完整。
- 真实转换(耗配额,需 key):`python3 pdf2md.py some.pdf --out /tmp/o`,查 `/tmp/o/some/full.md`。

## 验证状态
- 离线自检:已验证(2026-10-23,rc=0)。
- 真实端到端转换:已验证(2026-10-23):公开 arXiv 论文 1706.03762 单篇 vlm 约 27s 出 full.md;同文件二次运行命中本地缓存、不需 key。多 key `--multi` 与 pipeline 模式未实跑。
- 其余取决于资源:用户自备 MinerU key 与其配额。

## 已知限制
- 依赖 MinerU 官方服务可达,数据会上传到 MinerU(涉密 PDF 勿用)。
- 限流约 50 文件/分钟;超时 900s 抛错,可用 batch_id 手动查询。
- 未含 DOI/标题识别与论文库索引等内部能力。
