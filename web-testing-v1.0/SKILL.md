---
name: browser-automation
description: |
  通过 Playwright 连接本地浏览器，自动执行用户描述的操作步骤，并生成可复用的 pytest 脚本。
  触发词：操作浏览器、自动化网页操作、录制浏览器操作、生成自动化脚本、网页自动化、browser automation、操作页面、点击网页、填写表单、网页测试脚本。
  当用户想要在浏览器上执行一系列操作步骤并生成 pytest 自动化脚本时使用此 skill。
  执行前必读 references 目录下的模式文档！
---

# Browser Automation Skill

通过 Playwright 连接本地浏览器执行用户描述的操作步骤，操作成功后生成可复用的测试脚本。

## 核心原理

**CDP (Chrome DevTools Protocol)** 方式连接已有浏览器，而非启动新浏览器：
```bash
chrome --remote-debugging-port=9222
```

```python
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
page = browser.contexts[0].pages[0]
```

## 目录规范

```
D:\test-project\{项目名}\
├── scripts\         ← 测试脚本放这里
├── input\           ← Excel用例文件
├── results\          ← 报告输出（Excel + HTML）
└── screenshots\      ← 截图
```

## 工作流程

| 模式 | 触发 | 脚本位置 |
|------|------|---------|
| **执行已有** | 用户说"执行xxx" | `D:\test-project\{xxx}\scripts\test_*.py` |
| **新建生成** | 新项目无脚本 | 参考 `template/test_script_template.py` 生成 |

### 执行步骤

1. 用户说「执行xxx项目」
2. 去 `D:\test-project\{xxx}\scripts\` 找脚本
3. 找到 → 直接执行
4. 未找到 → 生成脚本到该目录，然后执行
5. 报告输出到 `D:\test-project\{xxx}\results\`

## P0 必知规则

| 规则 | 说明 |
|------|------|
| **iframe 内操作** | 用 `page.evaluate()` + `contentDocument`，不能用 Playwright frame API |
| **iframe 坐标必须加偏移** | `getBoundingClientRect` 相对于 iframe，要加 `iframe.left/top` |
| **Vue @click 必须用真实坐标** | `page.mouse.click(x, y)`，JS 的 `.click()` 不触发 Vue 事件 |
| **input 值必须用 keyboard.type** | JS 赋值 `input.value = 'xxx'` 不触发 Vue 双向绑定，要 `mouse.click()` + `keyboard.type()` |
| **中文 JS 字符串** | 直接写，文件 utf-8 编码即可 |
| **表单验证检查** | 检查 `.ant-form-item-explain-error` 是否为空 |
| **日期选择器** | 必须走 UI 点击流程：click picker → click day cell |
| **表单数据跨用例残留** | 每个 case 开头必须 reset_form() |
| **引号冲突** | f-string 中 `role='spinbutton'` 单引号会冲突，改双引号 `role="spinbutton"` |

## iframe 内元素操作

```python
# 获取元素坐标（iframe偏移必须加）
result = page.evaluate("""
    () => {
        const d = document.querySelector('#myiframe').contentDocument;
        const btn = d.querySelector('.target-button');
        if (!btn) return { found: false };
        const r = btn.getBoundingClientRect();
        const iframe = document.querySelector('#myiframe').getBoundingClientRect();
        return {
            found: true,
            x: r.left + r.width/2 + iframe.left,
            y: r.top + r.height/2 + iframe.top
        };
    }
""")
if result.get("found"):
    page.mouse.click(result["x"], result["y"])
```

## 填写表单字段（Vue 双向绑定）

```python
# 错误：JS 赋值不触发 Vue
page.evaluate("() => { input.value = '999'; }")  # ❌ 无效

# 正确：鼠标点击 + keyboard.type
page.mouse.click(input_x, input_y)
page.keyboard.type('999')  # ✅ Vue 接收到了
```

## 标准脚本结构

参考 `template/test_script_template.py`，每个项目脚本包含：

```python
# 配置区
CDP_URL = "http://127.0.0.1:9222"
TARGET_URL = "{页面URL}"
USERNAME = "{账号}"
PASSWORD = "{密码}"
BASE_INPUT = r"D:\test-project\{项目}\input"
BASE_OUTPUT = r"D:\test-project\{项目}\results"
BASE_SCREENSHOTS = r"D:\test-project\{项目}\screenshots"

# 浏览器操作函数
def open_modal(page): ...
def get_form_state(page): ...
def click_confirm(page): ...

# 用例执行
def run_test(page, case_info):
    if case_id == 'XXX-001':
        open_modal(page)
        return 'PASS', '备注', screenshot_path
    ...

# 主流程
def main():
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp(CDP_URL)
    page = browser.contexts[0].pages[0]
    try:
        # 执行用例 → 生成报告
    finally:
        browser.close()
        p.stop()
```

## 常见操作速查

| 操作 | 代码 |
|------|------|
| 打开弹窗 | `open_create_modal(page)` — 点击事件类型的按钮 |
| 切换影响位置 | `switch_location(page, '收费站')` |
| 填写桩号 | `fill_pile_number(page, '789', '55')` |
| 切换占道 | `toggle_road_block(page, 0, 0)` |
| 点击确定 | `click_confirm(page)` |
| 获取表单状态 | `get_form_state(page)` → `{modal, errors}` |
| 关闭弹窗 | `page.evaluate(...)` 点击取消或 X 图标 |

## 报告规范

- **Excel**：复制模板到 results，写入第9列（结果）、第10列（备注）、第11列（截图）
- **HTML**：相对路径 `../screenshots/xxx.png`，截图可点击放大
- **颜色**：PASS=`C6EFCE`，FAIL=`FFC7CE`

## 文档索引

| 文档 | 内容 |
|------|------|
| `references/vue-patterns.md` | iframe操作、DatePicker、input-number 等 Vue 组件交互模式 |
| `references/elementui-patterns.md` | ElementUI 组件交互模式 |
| `references/lessons-learned.md` | 踩坑经验速查、交通事故表单操作函数 |
| `scripts/templates/test_script_template.py` | 可复制的脚本模板 |
