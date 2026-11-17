# 版面 DSL 与约束求解（Stage B2 / B4）

这份文档说明"版面规划"到底做了什么、为什么这么做、以及怎么验。

## 1. 为什么不直接写 HTML

如果直接写 HTML + CSS，断页由浏览器决定。结果是：

- 断点不可解释——同一份内容在不同机器/不同版本上可能断在不同位置；
- 验收无从下手——"这页太空"没法变成一条能自动检查的规则；
- 图和版面互相妥协——要么图被拉伸，要么版面留一条大缝。

所以这里把版面拆成两段：**先声明（DSL）→ 再求解（约束求解）→ 最后渲染（绝对定位）**。
渲染阶段只负责把已经算好的毫米坐标画出来，不再参与决策。

## 2. DSL 结构

`outputs/layout_<月份>.json` 就是实际使用的 DSL（由 `tools/build_report.py` 生成）：

```jsonc
{
  "version": "1.0",
  "meta":  {"title": "…月经营月报"},
  "page":  {"size": "A4", "margin": {"top": 16, "right": 15, "bottom": 14, "left": 15},
            "columns": 12, "gutter": 6, "footer": 9},
  "solver": {"page_cost": 60, "fill_min": 0.80, "fill_max": 1.0,
             "underfill_weight": 1400, "orphan_weight": 260},
  "blocks": [
    {"id": "kpi1_revenue", "kind": "kpi", "span": 2, "height": 27,
     "content": {"label": "营业收入", "value": "119.2", "unit": "万元", "delta": "环比 -9.25%"}},
    {"id": "c_rev", "kind": "chart", "span": 12, "height": 70,
     "content": {"chart": "revenue_trend"}}
  ],
  "constraints": [
    {"type": "same_row", "blocks": ["kpi1_revenue", "kpi2_orders", "…"]},
    {"type": "aspect", "block": "c_rev", "min": 2.2, "max": 3.4},
    {"type": "avoid_orphan", "block": "sec1"},
    {"type": "fill", "min": 0.80, "max": 1.0},
    {"type": "max_pages", "value": 4}
  ]
}
```

块只有 9 种（`title / subtitle / section / kpi / chart / table / text / callout / footer`），
每种有默认高度；实际高度由调用方给，文本块用 `dsl.measure_text_height()` 按"宽度 + 字号 + 行高"估。

**块高度是版面规划唯一的输入假设**，所以文本高度估得准不准，直接决定成品会不会被裁。
评测脚本 O1 会独立重算一遍高度来核对（`measure_text_height` 只用来生成，不用来自证）。

## 3. 约束语义

| 类型 | 级别 | 语义 |
|---|---|---|
| `same_row` | 硬 | 这些块必须横向并排在同一行，行高取最大值，列宽合计不得超过 12 列 |
| `keep_together` | 硬 | 这些块不许被分页切开（要求它们在文档顺序上连续） |
| `avoid_orphan` | 软 | 该块不能是某页最后一行（章节标题掉页底） |
| `aspect` | 硬（校验） | 块的长宽比必须落在区间内（图表被压扁就读不出来） |
| `fill` | 软 | 每页填充率区间，进入目标函数 |
| `max_pages` | 硬 | 总页数上限；超了就抬高每页固定成本重解 |

"硬"= 违反后该分页方案不可行；"软"= 违反计入目标函数；"校验"= 求解器不主动调整，但
`check_plan()` 会把它算作违规。

## 4. 求解算法

三步，全部确定性：

1. **原子化**：把 `same_row` 绑定的块并成不可拆的原子（atom）。
2. **行装箱**：给定一段连续的原子，从左到右往行里塞；列宽合计 ≤ 12 就并排，否则换行。
   行高 = 行内块最大高度（整行一起拉伸，避免高低错落）。
3. **分页（DP）**：把"切分成连续页"建模成最短路：

   ```
   dp[0] = 0
   dp[j] = min{ dp[i] + cost(页 i..j-1) }   （页可行 ⟺ 行高之和 ≤ 内容区高度）
   ```

   ```
   cost(页) = 固定页成本
            + max(0, fill_min − 填充率) × 1400
            + max(0, 填充率 − fill_max) × 3000
            + Σ(章节标题落在页底) × 260
   ```

n 个原子时是 O(n²) 次装箱尝试，每次 O(n)，n≈25 时不到 10ms，且**全局最优**（不是贪心）。
这一点可验：`tests/test_layout.py` 用"枚举所有分页方案"的暴力解对拍，目标值必须一致。

页数超过 `max_pages` 时，把固定页成本乘 2.2 重解（最多 8 轮），把"压页"变成一次可解释的
参数搜索，而不是硬失败。

## 5. 输出：版面计划

`outputs/layout_plan_<月份>.json`：

```jsonc
{"schema": "layout-plan/1",
 "geometry": {"content_w": 180, "content_h": 267, "col_w": 9.5, …},
 "pages": [{"index": 1, "fill": 0.858,
            "rows": [{"y_mm": 16.0, "h_mm": 34.0,
                      "blocks": [{"id": "hero", "x_mm": 15, "y_mm": 16, "w_mm": 180, "h_mm": 34}]}]}],
 "placements": {"hero": {"page": 1, "x_mm": 15.0, "y_mm": 16.0, "w_mm": 180.0, "h_mm": 34.0}},
 "metrics": {"pages": 3, "fill_avg": 0.862, "fill_min": 0.828, "fill_std": 0.029, "objective": 180.0},
 "soft_violations": []}
```

## 6. 出稿链路

```
layout_plan.json ──► render_html（每块 position:absolute + mm）
                 ──► Edge --headless=new --print-to-pdf ──► report.pdf
```

- **为什么绝对定位**：分页已经算好，HTML 必须"不许自作主张"。`@page { margin: 0 }`，
  一页一个 210×297mm 的 div，`page-break-after: always`。
- **为什么图要重画**：图表 SVG 的宽高在求解后才确定（块的槽位尺寸），所以 `chart_svgs()`
  在求解之后按槽位像素尺寸重新生成 SVG，保证 1:1、不拉伸（评测 G1 校验）。
- **为什么用 Edge 而不是 WeasyPrint**：WeasyPrint 在 Windows 要 GTK，装不上；
  Edge 自带 Chromium 打印内核，字体/颜色/@page 都支持，并且不用装任何东西。
- **框住黑盒**：出稿后立刻回读 PDF 二进制，核对页数、纸张尺寸、字体嵌入（评测 P1–P4），
  不合格直接报错，不允许"生成成功但其实是空白页"。

## 7. 评测口径

`tools/eval_report.py` 跑 7 组检查，并给贪心装箱做对照：

| 组 | 检查 | 级别 |
|---|---|---|
| C | 几何合法：不越界、不重叠、阅读顺序不乱、同排等高 | 硬 |
| O | 内容溢出：按字号重算每块所需高度，超出槽位即报 | 硬 |
| G | 图表适配：SVG 宽高比 = 槽位宽高比（2% 容差） | 硬 |
| T | 章节标题不落页底 | 硬 |
| N | 数字回查：正文每个数字都能在事实包找到同值字段 | 硬 |
| P | PDF：页数=计划、A4、字体内嵌、非空白 | 硬 |
| R | 可复现：同一 DSL 再解一次，计划逐字节相同 | 硬 |

对照组的结论（2025-10，24 个块）：

| 指标 | 约束求解 | 贪心装箱 |
|---|---|---|
| 页数 | 3 | 3 |
| 最低填充率 | 82.8% | 60.4% |
| 填充率 σ | 2.9% | 18.2% |
| 目标值 | 180.0 | 454.2 |

页数一样，但贪心会把最后一页填成 60%，因为它是"填不下就翻页"——不会为了全局平衡
把后面的块提前。这正是要做求解器的原因。

## 8. 已知边界

- **只做纵向流式版面**：块按文档顺序从上往下排，不支持任意坐标摆放（真实月报不需要）。
- **`keep_together` / `same_row` 的块必须在文档顺序上连续**，否则 DSL 校验直接报错。
- **高度是声明值**：文本高度靠估算，估小了会被裁；对策是 O1 独立复核 + 1mm 容差。
- **PDF 纸张尺寸**读的是 MediaBox，Chromium 会写成 209.9×297mm（差 0.1mm 是它自己的浮点误差）。
