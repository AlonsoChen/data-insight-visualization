# data-insight-visualization

把一份陌生数据（CSV、Excel、接口或数据库导出）变成四样东西：

1. **诊断结论** —— 粒度、时间完整性、口径、量级、能回答/不能回答什么
2. **关键发现** —— 3~5 条带数字的结论，反直觉的优先
3. **看板或图表** —— 按「问题类型 → 数据形态」选图，不套模板
4. **结论说明** —— 每图一句结论 + 现象/原因/动作三句式

它不是「图表模板库」，也不是「一键出图工具」。核心是**判断标准**：什么时候该用中位数、什么时候该截 TopN、什么时候一条曲线看起来像趋势但其实是脉冲。

## 安装

```powershell
# 全局（Trae CN），或放到 <项目根>\.trae\skills\ 作为项目级 skill
Copy-Item -Recurse . "$env:USERPROFILE\.trae-cn\skills\data-insight-visualization"
```

## 最短用法

```bash
python scripts/diagnose.py your_data.csv --out ./out
python scripts/render_quickstart.py your_data.csv --diagnosis ./out/diagnosis.json --out ./out/dashboard.html
```

第一条出诊断报告与聚合 JSON，第二条出可直接双击打开的 HTML 骨架。依赖只有 Python 3.9+；读 `.xlsx` 需 `pip install openpyxl`。

---

## 什么时候用

- 「帮我分析这份数据，做成看板」
- 「这份数据有什么问题」
- 「这个月为什么掉了」「增长是谁带来的」
- 「出一版可视化报告」

## 什么时候不用

- 只要求画一张指定类型的图 —— 直接画即可
- 纯代码、环境、部署问题
- 结论已经定好，只需要排版美化
- 复刻某个既有看板 —— 本 skill 不提供模板，只提供判断方法

---

## 目录结构

```
data-insight-visualization/
├── SKILL.md                          # 主流程：诊断 → 分析 → 选型 → 表达 → 自检
├── README.md                         # 本文件
├── references/
│   ├── 01-诊断与判据阈值.md           # 粒度、时间、口径、分布、陷阱、分析阈值
│   ├── 02-图表选型决策表.md           # 问题类型 → 图型，含失效边界、架构、交互
│   ├── 03-反模式清单.md               # 20 条常见错误：错在哪、怎么改
│   ├── 04-视觉规范.md                 # 配色、字体、栅格、数字格式、深浅色
│   └── 05-检查表.md                   # 交付前 20 项逐条核对
├── scripts/
│   ├── diagnose.py                   # 读数据，输出诊断报告 + 聚合 JSON
│   └── render_quickstart.py          # 用聚合 JSON 生成自包含 HTML 骨架
└── examples/
    └── sample_orders.csv             # 示例订单数据（含缺失日、脉冲、退款、重复上报）
```

---

## 安装

这是一个普通文件夹形式的 skill，放在以下任一位置即可被识别：

| 范围 | 目标路径 |
|---|---|
| 当前项目 | `<项目根>/.trae/skills/data-insight-visualization/` |
| 全局（Trae CN） | `~/.trae-cn/skills/data-insight-visualization/` |
| 全局（Trae 国际版） | `~/.trae/skills/data-insight-visualization/` |

Windows 下 `~` 即 `C:\Users\<用户名>`。复制整个 `data-insight-visualization` 目录，保持目录名与 `SKILL.md` 里的 `name` 一致。

不安装也可以直接用：在对话中把本目录的 `SKILL.md` 路径给到助手，让它按流程执行。

---

## 快速开始

依赖：**Python 3.9+**，`diagnose.py` 与 `render_quickstart.py` 只用标准库。
读取 `.xlsx` 需要 `openpyxl`（可选）：

```bash
python -m pip install openpyxl
```

在 `examples/` 目录下试跑：

```bash
# 1. 诊断
python ../scripts/diagnose.py sample_orders.csv --out ./out

# 2. 生成骨架页
python ../scripts/render_quickstart.py sample_orders.csv --out ./out/quickstart.html --diagnosis ./out/diagnosis.json
```

产物：

| 文件 | 内容 |
|---|---|
| `out/diagnosis.md` | 人读报告：时间完整性、分布、主键候选、分类维度、可疑点 |
| `out/diagnosis.json` | 聚合结果：日/月序列、分类 Top12、标记，供下游使用 |
| `out/quickstart.html` | 自包含骨架页：KPI 卡、趋势、Top10 条形、诊断提示 |

也可以用参数指定列（自动识别不准时）：

```bash
python ../scripts/diagnose.py data.xlsx --out ./out --date-col 下单时间 --value-col 实付金额
```

### 示例数据里埋了什么

`sample_orders.csv` 是刻意做脏的订单数据，用来验证诊断能力：

- 5 天完全缺失（2026-04-07、05-01~03、06-18）
- 2026-07-15 一次性批量入库，约为日中位数的 12 倍
- 6 条退款（金额与数量为负）
- 20 条重复上报（`order_id` 重复）
- 部分 `channel` 为空

跑完应能看到：主键重复率 0.9%、负值、脉冲、高度集中的分类等提示。

---

## 典型用法

```
用户：这份 sales_2026.csv 帮我看看有什么问题，然后做成看板

助手（按 SKILL.md）：
1. 跑 diagnose.py，读出 2,223 行、184 天、缺 5 天、order_id 重复 0.9%
2. 按 references/01 判定：粒度是订单行；脉冲需剔除；退款要单列
3. 按 references/02 选图：趋势用折线、结构用堆叠柱、国家用横向条形
4. 按 references/04 定视觉：单主色 + 中性灰 + 异常红，实体固定色
5. 按 references/05 过 20 项检查
6. 输出：诊断段 + 3~5 条发现 + HTML 看板 + 结论说明
```

---

## 设计原则

**三层能力，顺序不可颠倒**

| 层 | 决定什么 | 失败表现 |
|---|---|---|
| 诊断 | 数据是什么、能回答什么 | 图很漂亮，结论是错的 |
| 分析 | 重点在哪、变化由谁造成 | 只有描述，没有判断 |
| 表达 | 用什么图、怎么排、怎么标 | 图很多，读者仍不知道看什么 |

**几条不能破的硬规则**

- 主键重复率 > 0.5%，先查粒度，不聚合
- 缺失日 > 5%，先问原因，不默认补 0
- 不完整周期不与完整周期直接比
- 一图一问，写不出问题句就删
- 柱状图与面积图 y 轴从 0
- 同一实体跨图同色，颜色不随排序变化
- 每个异常都必须给结论，不能只标色

完整阈值见 `references/01-诊断与判据阈值.md`。

---

## 脚本边界

两个脚本只做**客观统计和版式骨架**，不做业务判断：

- 不会替你决定「这个峰值是促销还是补录」
- 不会替你写结论
- 不会自动选出「最好的图」——`render_quickstart.py` 给的是起点，图表类型要按 `references/02` 重选
- 自动识别的日期列/数值列可能不准，用 `--date-col` / `--value-col` 覆盖

已知限制：

- 只读第一个工作表；多 sheet 请先拆分或另存
- 日期仅识别 `YYYY-MM-DD`、`YYYY/MM/DD` 及带时间的写法
- 数值列自动识别为「名称命中 + 取值丰富度」，不保证符合业务口径
- 大文件（> 50 万行）为纯 Python 处理，速度一般，建议先抽样

---

## 版本

0.1.0 —— 首个本地完整包，未发布到任何 registry。
