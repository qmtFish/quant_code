---
name: lark-work-diary
version: 1.0.0
description: "工作日记总结：把当天工作内容整理成简洁编号小结（≤100 字）写入飞书《量化日记》的对应日期格子。当用户说「写工作日记」「记日记」「总结今天的工作」「把工作小结写进日记」或要求把当日工作记录到量化日记文档时使用。"
metadata:
  requires:
    bins: ["lark-cli"]
---

# 工作日记总结（Work Diary）

> **前置条件：** 先阅读 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)（认证、URL 转发、JSON 契约规则）。

## 目标文档

- **量化日记**: `https://my.feishu.cn/wiki/KIUdw4bMqi0VrLkCqrzcfxohnMb`（底层 docx token: `Ngf3dZieXovCcKx6BFEcytA9nOg`）
- **结构**: 标题 + 一张日期表格（第 1 行 = 日期单元格 `YYYYMMDD`，第 2 行 = 当日内容格子，内含 `ul`/`p`/`ol` 块）

## 内容规范（用户无特殊要求时）

- 格子内首行：`<p>今日工作小结：</p>`
- 正文：`<ol>` 有序列表（1. 2. 3. ...），每条一句、动词开头、客观直白
- **总字数 ≤ 100 字**（含标题行），超出需精简
- 日期用当天日期 `YYYY-MM-DD`（用户未给时用系统日期）
- XML 文本需转义 `<` `>` `&`；`<li>` 须放在 `<ol>` 内

## 流程

### Step 1：确定今日内容
- 用户直接给了"今天做了什么" → 直接用
- 未提供 → 从当前对话上下文总结，或询问用户

### Step 2：生成 XML 内容
写入本地临时文件（相对路径，如 `skills/lark-work-diary/_content.xml`）：

```xml
<p>今日工作小结：</p>
<ol>
  <li>第一条...</li>
  <li>第二条...</li>
</ol>
```

### Step 3：定位日期格子（锚点）
1. 获取文档结构（含 block id）：
   ```bash
   lark-cli docs +fetch --as user --doc "KIUdw4bMqi0VrLkCqrzcfxohnMb" --detail with-ids --format json
   ```
2. 在表格第 1 行找到文本 == `YYYYMMDD`（当天）的 `<p id="...">` 单元格，记下列序
3. 同一列第 2 行格子内取**最后一个 block** 的 id 作为插入锚点（示例：`S48JdhA7toj6mpxMPA5crLH4nwc`）

### Step 4：插入
```bash
lark-cli docs +update --as user --doc "KIUdw4bMqi0VrLkCqrzcfxohnMb" \
  --command block_insert_after --block-id <锚点block-id> \
  --content "@./skills/lark-work-diary/_content.xml" --format json
```
- `--content` 用 `@相对路径` 传文件，避免引号转义
- 插入后**原 block id 可能变化**，后续操作需重新 fetch

### Step 5：验证
```bash
lark-cli docs +fetch --as user --doc "KIUdw4bMqi0VrLkCqrzcfxohnMb" \
  --scope keyword --keyword "今日工作小结" --context-before 1 --context-after 1 --format json
```
确认内容出现在**当天日期对应的格子**内（而非别的列/文档末尾）。

### Step 6：清理
删除临时文件 `skills/lark-work-diary/_content.xml`。

## 边界情况

| 情况 | 处理 |
|------|------|
| 表格中没有今天的日期列 | 询问用户：新建列 / 追加到文档末尾（`+update --command append`） |
| 当天格子为空 | 提示用户先手工加列，或改用 append 到文档末尾 |
| 格子内无法确定"最后一个 block" | 用该格子任意已知 block 做锚点（内容会插在其后） |
| 字数超 100 | 精简条目，删除次要项，保留关键动作 |
| 用户指定其他日记文档 | 用用户给的 URL/token 替换默认值 |
| 插入后位置不对（插到表格外） | 重新 fetch 定位正确格子锚点后重试 |

## 权限

| 操作 | 所需 scope |
|------|-----------|
| `docs +fetch` | `docx:document:readonly` |
| `docs +update` | `docx:document:write_only` |
| 认证 | `lark-cli auth login --domain docs`（已配置则跳过） |
