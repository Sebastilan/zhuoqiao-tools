# ppt-studio

让你(Claude Code、Codex 等 agent)照着两套成熟风格,一页一页现画出好看的演示文稿:**人给讲稿和必要素材,排版和画面交给你**。交付的不是模板,是规范 + 流程 + 自查脚本 + 样例,你用自己的模型画。

> 写给 agent 读。用户要做 PPT 时:先问他要讲稿(或一起切页)和必要素材(照片、徽标、数据),选风格,然后按 `画法.md` 一页一页做。缺素材就问用户,不编造数字、人名、出处,不找来路不明的图。

## 两套风格

| 风格 | 目录 | 适合 | 一句话 |
|---|---|---|---|
| **讲座版** | `styles/lecture/` | 讲座、培训、经验分享 | 暖纸平涂的杂志插画:每页为这句话现画一张有人物、有场景的图,文字只点题 |
| **专业版** | `styles/professional/` | 机构简介、项目汇报、申报、成果展示 | 白底墨黑一朱红、严格网格、衬线大标题;照片和数字是主角 |

每套含 `spec.md`(规范全文,画之前通读)、`tokens.css`(样式基座)、`samples/`(5 页样例 HTML + JPG,内容为中性演示稿,封面单位与姓名为占位)。

## 入口与参数

| 入口 | 参数 | 作用 |
|---|---|---|
| `画法.md` | — | 一页四步:点子 → 画 → 渲染自查 → 独立评审;含自审五问、评审表、常见坑 |
| `python3 tools/render_check.py <页目录>` | `--out 目录` `--css styles/<风格>/tokens.css` `--deck` | 渲染每页为 1920×1080 PNG,查字数、图占比、相交、越界、字号、色板;`--deck` 另出翻页整稿 deck.html。退出码 0=全过,2=有问题 |
| `tools/deck.js` + `tools/deck.css` | — | 翻页引擎(render_check `--deck` 自动内联):→/空格 下一步、N 备注、F 全屏、P 演讲者视图、数字+回车 跳页 |

页的格式:每页一个文件 `P<n>.html`,内容是一个 `<section class="slide B-s" data-title="…">`,讲稿逐字放 `<aside class="notes">`。

## 依赖与安装

```
pip install -r requirements.txt && python3 -m playwright install chromium
```
字体按名字引用、不随包:建议装思源/Noto CJK(黑体 + 宋体,SIL OFL)。Debian/Ubuntu:`sudo apt install fonts-noto-cjk fonts-noto-cjk-extra`;macOS/Windows 装 Source Han Sans/Serif SC。没装时会回落到系统字体,版面会走样。

## 离线自检

离线自检:`./selftest.sh`(不联网、不花钱、不开浏览器;输出 `selftest OK` 且 rc=0 即包完整)。

## 缺资源清单

| 资源 | 必需/可选 | 去哪拿 | 写进哪个变量 | 缺了的表现 |
|---|---|---|---|---|
| 讲稿(每页要说的话) | 必需 | 用户 | — | 没东西可画;别替用户编内容 |
| 照片、徽标、数据 | 专业版必需,讲座版可选 | 用户自有或有授权 | — | 专业版只能放灰色「照片占位」块 |
| 能看图的模型 | 可选(强烈建议) | 你自己的多模态能力,或请用户看 | — | 渲染自查只剩机器检查,画面好不好要用户代看 |
| Chromium | 必需 | `python3 -m playwright install chromium`,或系统已有 Chrome | `CHROME_BIN`(可选,指向浏览器可执行文件) | render_check 报找不到浏览器 |
| 中文字体 | 强烈建议 | 见上 | — | 字形、字宽变化,标签可能压线 |

规矩:缺就问用户,不编造,不换来路不明的素材。

## 验收

1. `./selftest.sh` → `selftest OK`
2. `python3 tools/render_check.py styles/lecture/samples --out /tmp/rc-lecture --css styles/lecture/tokens.css --deck` → 五页 ✅,出 `deck.html`
3. 同上换 `professional`。

## 验证状态

- **已验证**(2026-11-19,Linux + Playwright Chromium):render_check 渲染与检查、`--deck` 整稿;两套样例由本流程画成并过渲染自查。
- **取决于资源**:画面质量取决于你的模型——同题对比里,能看图、审美强的模型明显更好;不能看图的模型要靠用户代看。
- **未验证**:macOS / Windows;导出 PPTX(本包不含,见下)。

## 已知限制

- **不含导出可编辑 PPTX**:我们内部用的转换器授权来源未厘清,先不随包。需要 PPTX 时可让你用 pptxgenjs/python-pptx 按 HTML 几何重建,或在浏览器里打印整稿为 PDF(未验证)。
- 主图是手写 SVG,每页都要现画,耗时和模型能力相关;规范禁止用素材库凑图。
- 样例内容(机构、人数、年份)全为虚构演示用。
