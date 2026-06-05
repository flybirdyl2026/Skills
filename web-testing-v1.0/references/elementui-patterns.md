# ElementUI 组件交互模式

通过 playwright-cli 和 Playwright Python API 操作 ElementUI 组件时，需要特殊处理。

## 核心发现：aria-label 不是 HTML 属性

ElementUI 组件在无障碍树（accessibility tree）中显示的 `aria-label`（如 `* 路线路段:`）是浏览器根据关联 `<label>` 自动计算生成的虚拟属性，**不是真实的 HTML attribute**。

```
# 无障碍树显示：
combobox "* 路线路段:" [ref=e556]

# 但实际 HTML 中：
<input role="combobox" aria-label=null class="el-select__input">
```

**后果**：`get_attribute("aria-label")` 返回 null，所有基于 aria-label 的定位策略失效。

## 正确定位方式：通过 .el-form-item__label 文本

ElementUI 表单使用 `.el-form-item` 结构，每个字段有 `.el-form-item__label` 标签：

```html
<div class="el-form-item">
  <label class="el-form-item__label">路线路段:</label>
  <div class="el-form-item__content">
    <div class="el-select">...</div>
  </div>
</div>
```

**定位策略**：通过 `.el-form-item__label` 的文本内容找到对应的 `.el-form-item`，再在其中找目标组件。

## el-select 下拉框

### 问题
combobox 外层有 span 覆盖，直接 `click()` 会被拦截。

### 解决方案
用 JS evaluate 点击 `.el-select__wrapper`：

```javascript
// playwright-cli 方式
npx playwright-cli eval "(function(){
  var formItems = document.querySelectorAll('.el-form-item');
  for (var i = 0; i < formItems.length; i++) {
    var label = formItems[i].querySelector('.el-form-item__label');
    if (label && label.textContent.includes('路线路段')) {
      var wrapper = formItems[i].querySelector('.el-select__wrapper');
      if (wrapper) { wrapper.click(); return true; }
    }
  }
  return false;
})()"

// Python Playwright 方式
page.evaluate("""(labelText) => {
    const formItems = document.querySelectorAll('.el-form-item');
    for (const item of formItems) {
        const label = item.querySelector('.el-form-item__label');
        if (label && label.textContent.includes(labelText)) {
            const wrapper = item.querySelector('.el-select__wrapper');
            if (wrapper) { wrapper.click(); return true; }
        }
    }
    return false;
}""", "路线路段")
```

等待选项出现后选择：
```python
page.wait_for_selector(".el-select-dropdown__item:visible", timeout=5000)
option = page.locator(f".el-select-dropdown__item:has-text('{option_text}')").last
option.click()
```

## el-cascader 级联菜单

### 问题
1. 内部 input 的 `role` 为 null（不是 "textbox"），`input[role="textbox"]` 找不到
2. 同样有覆盖层拦截问题

### 实际 HTML 结构
```html
<div class="el-cascader">
  <div class="el-input">
    <div class="el-input__wrapper" tabindex="-1">
      <input type="text" class="el-input__inner" role=null>
    </div>
  </div>
</div>
```

### 解决方案
用 JS evaluate 点击 `.el-cascader .el-input__wrapper`：

```python
page.evaluate("""(labelText) => {
    const formItems = document.querySelectorAll('.el-form-item');
    for (const item of formItems) {
        const label = item.querySelector('.el-form-item__label');
        if (label && label.textContent.includes(labelText)) {
            const cascader = item.querySelector('.el-cascader');
            if (cascader) {
                const wrapper = cascader.querySelector('.el-input__wrapper');
                if (wrapper) { wrapper.click(); return true; }
            }
        }
    }
    return false;
}""", "病害名称")
```

逐级选择菜单项：
```python
for item_text in path_items:
    page.evaluate("""(itemText) => {
        const nodes = document.querySelectorAll('.el-cascader-node');
        for (const node of nodes) {
            if (node.textContent.trim().includes(itemText)) {
                node.click();
                return true;
            }
        }
        return false;
    }""", item_text)
    time.sleep(0.5)
```

## el-upload 文件上传

### 问题
1. `expect_file_chooser()` 对 ElementUI 隐藏 file input 不够可靠
2. 上传缩略图 `el-upload-list__item-thumbnail` 存在但 Playwright 可能判定为 hidden

### 解决方案
直接操作隐藏的 `<input type="file">`：

```python
# Python Playwright
file_input = page.locator(".el-upload input[type='file']").first
file_input.set_input_files(IMAGE_PATH)

# 等待上传完成（state="attached"，不要求 visible）
page.wait_for_selector(".el-upload-list__item", state="attached", timeout=10000)
```

```bash
# playwright-cli 方式
npx playwright-cli upload <ref> <filepath>
```

## spinbutton 数值输入

桩号、数量等使用 spinbutton，通过 `.el-form-item` label 定位：

```python
# 填写所在桩号（K860+0）
group = page.locator(".el-form-item").filter(has_text=re.compile(r"所在桩号"))
spinbuttons = group.locator("input[role='spinbutton']")
spinbuttons.first.fill("860")
spinbuttons.nth(1).fill("0")

# 填写病害数量
group = page.locator(".el-form-item").filter(has_text=re.compile(r"病害数量"))
spin = group.locator("input[role='spinbutton']")
spin.fill("1")
```

## ⚠️ 关键发现：MessageBox 按钮 MUST 用 page.mouse.click()

**ElementUI MessageBox 的"确定"按钮必须用 `page.mouse.click(x, y)` 模拟真实鼠标点击。**

### 原因
ElementUI MessageBox 的按钮使用 Vue `@click` 指令绑定事件处理函数。
程序化的 `.click()` 方法、`dispatchEvent(new MouseEvent(...))` 都**只能关闭弹窗视觉效果**，
**无法触发 Vue 的事件处理逻辑**（不会调用派发 API 等）。

### 验证过程
| 方法 | 弹窗关闭 | Vue事件触发 | 派发API调用 | 结果 |
|------|----------|-------------|-------------|------|
| `.click()` | ✅ | ❌ | ❌ | 假成功 |
| `dispatchEvent(mousedown/mouseup/click)` | ✅ | ❌ | ❌ | 假成功 |
| `page.mouse.click(x, y)` | ✅ | ✅ | ✅ | **真成功** |
| `playwright-cli click ref` | ❓ | ❌ | ❌ | 不触发 |

### 正确实现

```python
def mouse_click_el_message_box_confirm(page: Page):
    """点击 MessageBox 确认弹窗的"确定"按钮（必须用 mouse.click）"""
    btn_info = page.evaluate(
        """() => {
            const btns = document.querySelectorAll('.el-message-box__btns button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '确定') {
                    const rect = btn.getBoundingClientRect();
                    return {
                        found: true,
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2
                    };
                }
            }
            return {found: false};
        }"""
    )
    assert btn_info.get("found"), "MessageBox confirm button not found"
    page.mouse.click(btn_info["x"], btn_info["y"])
```

### 通用 mouse_click_button 辅助函数

适用于所有可能需要真实鼠标点击的按钮场景：

```python
def mouse_click_button(page: Page, button_text: str):
    """通过 page.mouse.click() 模拟真实鼠标点击按钮"""
    btn_info = page.evaluate(
        """(buttonText) => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === buttonText) {
                    const rect = btn.getBoundingClientRect();
                    return {
                        found: true,
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2
                    };
                }
            }
            return {found: false};
        }""",
        button_text,
    )
    assert btn_info.get("found"), f"Button '{button_text}' not found"
    page.mouse.click(btn_info["x"], btn_info["y"])
```

## 通用交互模式

| 组件 | 定位方式 | 交互方式 | 注意事项 |
|------|----------|----------|----------|
| el-select | .el-form-item__label 文本 | JS evaluate 点击 .el-select__wrapper | aria-label 不可用；wrapper 被覆盖 |
| el-cascader | .el-form-item__label 文本 | JS evaluate 点击 .el-input__wrapper | input role=null；逐级点击 .el-cascader-node |
| el-upload | .el-upload input[type=file] | set_input_files() | 缩略图用 state="attached" 等待 |
| el-input-number | .el-form-item label | fill spinbutton | 直接 fill 即可 |
| el-radio | label 文本 | click radio | 直接 click 可用 |
| **el-message-box** | **.el-message-box__btns button** | **page.mouse.click(x,y)** | **JS .click() 无效！必须真实鼠标事件** |
| el-button | get_by_role("button", name=) | click | 直接 click 可用 |

## 提交确认弹窗

ElementUI MessageBox 弹窗（如"附近有相似病害，是否确定继续提交？"）：

```python
try:
    confirm_btn = page.locator(".el-message-box__btns button:has-text('确定')")
    if confirm_btn.is_visible(timeout=3000):
        confirm_btn.click()
except Exception:
    pass  # 没有确认弹窗则跳过
```

## 断言模式

新增记录不一定是表格最后一行，应遍历所有行检查：

```python
all_rows = page.locator(".el-table__body-wrapper tr")
found_match = False
for i in range(all_rows.count()):
    row_text = all_rows.nth(i).text_content()
    if ("目标文本" in row_text and "其他条件" in row_text):
        found_match = True
        break
assert found_match
```

## Windows 兼容

- print 语句避免 emoji 和非 ASCII 特殊字符（Windows GBK 编码不支持）
- 文件路径用 raw string：`r"D:\path\file.ext"`
- PowerShell 执行 pytest：`pytest test_xxx.py -v --tb=short`