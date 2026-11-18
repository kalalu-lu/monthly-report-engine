# 账墨 · 经营月报自动生成系统

把一份经营明细表，自动变成一份能直接发给老板的图文月报（A4 三页 PDF）。

**核心主张**：一份月报的难点不在画图，而在**选对图、讲清事、排好看**。
所以系统把这件事拆成两段：

- **Stage A 数据 → 洞察**：全部由程序确定性计算，结果可复现（校验 → 指标 → 差异分解 → 异常检测 → 事实包）
- **Stage B 洞察 → 成稿**：选图由算法打分决定，措辞由大模型在约束下生成，版面由约束求解器给出毫米级坐标

一句话原则：**数字全由程序算，结论由大模型在约束下写，写错由校验拦下。**

---

## 两种使用方式

### 方式一：下载便携包（不需要装 Python）

到 [Releases](../../releases) 下载 `便携版_账墨_v1.0.zip`，解压后双击 `run.bat`。

- 包内自带 Python 3.12 运行时和依赖库，解压即用，不写注册表
- **全程不产生任何 .exe**，因此不会触发 SmartScreen / Smart App Control 对未签名程序的拦截
- 首次运行会在 `outputs\` 下生成结果；示例成品见包内 `示例月报_2025-10.pdf`

> 若解压路径含中文字符，`run.bat` 会自动把运行时复制到 `%LOCALAPPDATA%\LedgerInk\py` 再启动
> （Chromium 无法由位于非 ASCII 路径下的 Python 启动，会静默挂住）。

### 方式二：从源码运行（开发者）

```bash
git clone <本仓库地址>
cd ledgerink
pip install -r requirements.txt          # 只有 pandas / numpy / openpyxl 三个
python -m src.gui                        # 桌面界面
```

命令行方式：

```bash
python run_pipeline.py 2025-10           # Stage A：校验→指标→分解→异常→事实包
python tools/build_report.py 2025-10     # Stage B：图表→版面→文案→PDF
python tools/eval_report.py 2025-10      # 出稿评测（12 项硬性检查）
```

仓库自带演示数据（`data/raw`：6 门店 × 8 品类 × 24 个月），克隆下来直接能跑出报告。

---

## 配置大模型密钥（可选）

程序默认调用 DeepSeek 生成"结论与建议"。不配置也能运行（复用已校验文案或程序模板）。

```bash
cp .env.example .env        # Windows 也可双击 set_key.bat 粘贴密钥
```

在 `.env` 里填：

```
DEEPSEEK_API_KEY=sk-你的密钥
```

> **本仓库不包含任何密钥**。`.env` 已在 `.gitignore` 中排除，请勿把自己的密钥提交上来。

成本参考：一次完整生成约 0.02 元。

---

## 用自己的数据

1. 界面里点「下载数据模板（Excel）」
2. 按 5 个 sheet 填数：`sales` / `budget` / `expenses` / `dim_store` / `dim_category`
3. 把 5 张表放进同一个文件夹，界面里选它 → 选月份 → 点「生成月报」

**数据要求**：至少 13 个月（同比要用去年同月），门店 ≥ 2，品类 ≥ 3。
只有 1 个月也能出报告，但同比/趋势类指标为空。

进入计算前会过 7 条校验（V01–V07），被拦下的行不参与计算，清单落在 `outputs/logs/quarantine.csv`。

---

## 目录结构

```
run_pipeline.py        Stage A 流水线
app_main.py            统一入口（源码 / 打包都走它）
src/
  ingest.py            7 条数据校验
  metrics.py           26 项指标
  variance.py          预算差异分解（三项精确配平）
  detect.py            8 条异常规则（阈值外置 data/ref/rules.json）
  factpack.py          事实包（Stage A 唯一出口）
  chart_rec.py         图表推荐（候选 + 5 维打分）
  svg.py               手写 SVG 图表渲染
  dsl.py / layout.py   版面 DSL 与约束求解（最短路分页）
  narrative.py         文案生成（提示词 v1/v2/v3 + 四道闸）
  render_html.py       出稿 HTML（绝对定位）
  render_pdf.py        Edge 无头打印 → PDF
  gui.py               桌面客户端
  paths.py             读写路径分流（源码 / 打包两种形态）
tools/                 取数、出稿、评测、打包等脚本
tests/                 单元测试（核心 28 项 + 版面 32 项）
docs/                  版面 DSL 设计说明
```

---

## 几个可验证的性质

| 性质 | 怎么验 |
|---|---|
| 数字可回查 | 报告正文每个数字都能在 `outputs/factpack_*.json` 找到同值字段（评测 N） |
| 分解可验算 | 量差 + 价差 + 混合差 = 总差异，误差 0.00e+00 |
| 版面可复现 | 同一份 DSL 再解一次，结果逐字节相同（评测 R） |
| 产出可质检 | 12 项硬性检查：几何 / 溢出 / 图表失真 / 数字出处 / PDF 页数字体 |

```
$ python tests/test_core.py      # 通过 28 项
$ python tests/test_layout.py    # 通过 32 项
$ python tools/eval_report.py 2025-10
硬性   : 12/12 通过
```

---

## 已知限制

- **需要本机有 Edge 或 Chrome**：PDF 由 Chromium 打印内核生成（不引入 WeasyPrint，因为它在 Windows 需要 GTK）
- **不支持非 ASCII 的 Python 安装路径**：见上文便携包的自动重定位说明
- **单机单企业**：没有数据库、多用户与权限体系，定位是课程级原型
- **只支持纵向流式版面**：块按文档顺序从上往下排，不支持任意坐标摆放

---

## 许可

MIT，见 [LICENSE](LICENSE)。内置演示数据由脚本生成，不含任何真实企业数据。
