# QMT 策略回测使用手册（国金QMT交易端 2.1.19）

> 适用策略：`QMT_READ_LOCAL`（读取预测 JSON 自动调仓，源码见 `QMTcode/qmt_read_local.py`）
> 本文档基于 2026-08-01 实际操作 QMT 客户端（自动点击 + 界面识别 + 日志核对）编写，关键步骤均为实测验证。

---

## 0. 本机环境速查

| 项目 | 位置 / 说明 |
|---|---|
| 客户端 | 国金证券 QMT 交易端 2.1.19.0 |
| 安装目录 | `D:\Program Files\国金证券QMT交易端` |
| QMT 实际运行的策略文件 | `D:\Program Files\国金证券QMT交易端\python\QMT_READ_LOCAL.py`（QMT 加密保存，勿直接编辑） |
| 策略输出日志 | `D:\Program Files\国金证券QMT交易端\userdata\log\XtClient_FormulaOutput_YYYYMMDD.log` |
| 工作区策略源码 | `C:\Users\Cat\Desktop\code\QMTcode\qmt_read_local.py` |
| 预测数据文件 | `C:\Users\Cat\Desktop\code\data\results\auto_predictions.json` |
| 备用实盘脚本（miniQMT） | `C:\Users\Cat\Desktop\code\scripts\qmt_trader.py`（`--preview-only` 预览 / `--run` 下单） |

---

## 1. 策略编辑器界面布局

打开方式：QMT 主窗口 →「策略」→「策略交易 / Python策略」→ 打开 `QMT_READ_LOCAL`。
窗口标题为 `QMT_READ_LOCAL-策略编辑器`。

| 区域 | 位置（窗口内相对坐标） | 作用 |
|---|---|---|
| 顶部工具栏 | 左上，y≈110 | 编译、运行、回测等按钮 |
| 策略下拉框 | 顶部 (295, 87) | 切换当前策略 |
| 代码编辑区 | 中部左侧 (x≈0-1080, y≈170-850) | 策略 Python 代码 |
| 回测设置面板 | 右侧 (x≈1080-1484, y≈100-780) | 回测参数配置 |
| 日志输出区 | 底部 (y≈850-1320) | 编译/运行/回测输出；页签为「编译输出｜日志输出」 |
| 状态栏 | 底部 y≈1350 | 「编译成功」、模型交易运行状态等 |

> 坐标以本次会话窗口位于屏幕 (733,10) 时为准；Qt 窗口可拖动，按钮描述以文字为准。

---

## 2. 回测操作步骤（实测验证）

1. **打开策略**：主窗口 → 策略交易 → 双击/打开 `QMT_READ_LOCAL` 策略编辑器。
2. **编译**：点工具栏「编译」按钮，状态栏出现「编译成功」。
3. **打开回测设置**：点工具栏「回测」按钮（窗口内约 (424,111)），右侧出现回测设置面板。
4. **配置回测参数**（见下表）。
5. **开始回测**：点回测设置面板底部的圆形「回」图标按钮（窗口内约 (1358,464)，即「开始回测」）。
   日志出现 `[trade]start simulation mode` 即回测开始。
6. **查看结果**：回测按日线逐日推进，策略每根 K 线打印「调仓全景报告 / 调仓执行汇总」到底部「日志输出」页签，完整内容同步写入
   `userdata\log\XtClient_FormulaOutput_YYYYMMDD.log`。

### 回测设置面板字段

| 字段 | 说明 |
|---|---|
| 开始时间 / 结束时间 | 回测区间（本次实测为 2005-04-01 ~ 2026-07-31，长达 21 年，建议缩短） |
| 回测范围（下拉） | 本次实测显示「沪深300」——**这是买不到目标股的关键，见第 3 节** |
| 初始资金 | 回测启动资金（实测日志显示总资产 -1，需确认该字段生效，见 FAQ） |
| 资金比例 | 单只股票资金占总资产比例 |
| 滑点类型 / 滑点值 | 回测滑点设置 |
| 手续费类型、买入/卖出印花税、最低佣金、买入/卖出佣金 | 回测费率设置 |
| 最大成交比例 | 单笔最大成交比例 |

---

## 3. 本次实测结论（重要）

2026-08-01 我实际驱动客户端跑了一次回测，结果如下：

- ✅ 回测能正常启动并按日线逐日运行（2005-01-04 → 2026-07-31），策略代码（修复版）正常加载，日志显示初始化成功。
- ❌ **全程没有任何买入**：20 只目标股全部显示「现价 0.00 / 价格缺失，无法计算买入数量」。
- ❌ 账户总资产显示 `￥-1.00`，初始资金未正确生效。
- ⚠️ 21 年回测产生约 **228MB** 日志（`XtClient_FormulaOutput_20260801.log`）。

**根因**：QMT 内置策略的 `ContextInfo.get_history_data()` 只能取到**回测股票池**内股票的数据，而回测范围（右侧显示「沪深300」）不包含预测的 Top-20 目标股（多为中小盘/科创板），所以取不到价格。QMT 日志里也明确提示：
`get_history_data接口版本较老，推荐使用get_market_data_ex替代，配合download_history_data补充昨日以前的历史数据`。

---

## 4. 让回测真正买到股票（三种方案）

### 方案 A：调整回测范围（最快，界面操作）
在回测设置面板中，把「沪深300」下拉改为包含全部目标股的选项（如全部A股 / 自选股，并把 20 只目标股加入股票池），重新回测。
> 该下拉的完整选项本次未逐项展开确认，请打开下拉核对。

### 方案 B：改代码用 get_market_data_ex（推荐，不再依赖股票池）
把取价逻辑从 `get_history_data` 换成按代码列表取数 + 下载历史：

```python
from xtquant import xtdata
from xtquant.xttype import StockAccount

# 在 init 中下载目标股历史数据（只下载一次）
for code in target_qmt_codes:
    xtdata.download_history_data(code, '1d', start_time='2020-01-01', end_time='')

# 在 handlebar 中按代码取最新收盘价（返回 {code: {'close': [值]}}）
data = xtdata.get_market_data_ex(
    field_list=['close'], stock_list=all_qmt_codes,
    period='1d', count=1, dividend_type='none')
for qcode in all_qmt_codes:
    closes = data.get(qcode, {}).get('close', [])
    if closes:
        price_dict[_to_numeric(qcode)] = closes[-1]
```

若在策略编辑器内使用，`xtdata` 对应内置版接口 `ContextInfo.get_market_data_ex`，用法相同（部分版本需要先在“模型交易/行情”里下载过数据）。

### 方案 C：先用 miniQMT 预览（不动回测）
`scripts/qmt_trader.py` 是独立的 miniQMT 实盘模块，可先预览订单：

```
python scripts/qmt_trader.py --preview-only
python scripts/qmt_trader.py --pred-file data/results/auto_predictions.json --top-k 20 --preview-only
```

---

## 5. 策略参数说明

策略初始化时读取的参数（QMT 界面「策略参数」未配置时用默认值）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `pred_file` | `C:\Users\Cat\Desktop\code\data\results\auto_predictions.json` | 预测结果 JSON 完整路径 |
| `top_k` | 20 | 最多买入股票数 |
| `cash_pct` | 0.05 | 单只股票占总资产比例 |
| `trade_time` | `093500` | 触发调仓时间 HHMMSS（分钟级 K 线生效） |
| `min_cash` | 2000 | 单只最小分配资金 |

---

## 6. 回测 / 模型交易 / 实盘的区别（安全提醒）

| 模式 | 是否真实下单 | 入口 |
|---|---|---|
| 回测 | 否（模拟成交） | 策略编辑器「回测」按钮 |
| 模型交易 | 模拟盘（虚拟资金） | 策略编辑器「运行」或主窗口「模型交易」 |
| 实盘 | 是 | 策略绑定真实资金账号运行 |

⚠️ **重要**：
- 策略里的 `order_shares()` 是**真实下单函数**。在「模型交易」或实盘模式下运行会真实报单，调试请先回测或小资金模拟盘。
- 本次会话看到状态栏提示「策略正在模型交易中运行」——你的 `QMT_READ_LOCAL` 当前处于模型交易状态，改动代码后需要重启策略才生效。
- 策略文件 `python\QMT_READ_LOCAL.py` 是 QMT 加密保存的，请勿用外部编辑器直接改；修改一律在 QMT 策略编辑器内进行（粘贴后保存，QMT 会自动加密）。

---

## 7. 常见问题（FAQ）

**Q1：回测里所有股票「价格缺失」？**
股票不在回测数据池内。见第 4 节三种方案。

**Q2：回测账户总资产显示 -1？**
初始资金字段未生效的典型表现。检查回测设置里「初始资金」是否填写正确（本次实测该字段显示 1000000 但日志为 -1，需在 QMT 中确认保存后生效）。

**Q3：编译报 `SyntaxError: (unicode error) 'utf-8' codec can't decode`？**
策略文件编码不是 UTF-8（常见于 GBK 保存的旧文件）。在策略编辑器中全选删除后重新粘贴 UTF-8 源码再保存。

**Q4：日志文件巨大（几百 MB）？**
回测区间太长或每天打印太多。缩短回测区间、减少策略内 `print`，并定期清理 `userdata\log` 下旧的 `XtClient_FormulaOutput_*.log`。

**Q5：回测里卖出 / 买入数量不对？**
- T+1：当日买入部分不可卖，策略已按「可卖数量 m_nCanUseVolume」卖出；
- 科创板 688 开头：最低 200 股起买，策略已按此规则计算。

**Q6：回测每天重复调仓？**
策略内置「同一天不重复调仓」（`last_trade_day`）；若当日零委托（如全部价格缺失）会提示「下根K线将重试」。

---

## 8. 本次会话留下的现场资料

- 界面截图：`C:\Users\Cat\Desktop\code\qmt_screens\`（qmt_editor*.png / qmt_main*.png / toolbar.png 等）
- 回测日志（约 228MB）：`D:\Program Files\国金证券QMT交易端\userdata\log\XtClient_FormulaOutput_20260801.log`
  确认无用后可手动删除（QMT 会按日期重新生成）。
