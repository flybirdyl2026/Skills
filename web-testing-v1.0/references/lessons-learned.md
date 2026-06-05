# 经验教训总结

本文档记录 browser-automation 技能包在实际使用中发现的问题和解决方案。

---

## 速查索引

| 操作 | 方法 |
|------|------|
| 连接浏览器 | `p.chromium.connect_over_cdp("http://127.0.0.1:9222")` |
| iframe 内点击 | `page.evaluate()` + `contentDocument` + `page.mouse.click(x,y)` |
| Vue @click 触发 | 只能用真实鼠标坐标，`element.click()` 无效 |
| 检查表单验证 | `querySelectorAll('.ant-form-item-explain-error')` |
| 日期选择 | click picker → click day cell，不能 JS 赋值 |
| 打开弹窗 | `open_create_modal(page)` — 见第11节 |
| 关闭弹窗 | 点击"取消"按钮 或 `.anticon-close` 图标 |
| 获取表单状态 | `get_form_state(page)` → `{modal, errors}` |

---

## 1. playwright-cli 命令权限问题

### 问题
在 Claude Code 环境中，每次执行 `npx playwright-cli` 或 `npx @playwright/cli` 命令都会触发权限确认提示，需要用户点击"允许"。

### 解决方案
- 使用 `npx --yes @playwright/cli` 尝试跳过确认（部分有效）
- 长期解决：运行 `/fewer-permission-prompts` 扫描并添加信任命令
- 或者：直接使用 Python Playwright 脚本绕过 CLI 工具

### 教训
在自动化浏览器操作任务时，应优先考虑使用 Python Playwright 脚本直接执行，而非通过 CLI 中转。

---

## 2. 包名混淆：playwright-cli vs @playwright/cli

### 问题
npm 上有两个相关包：
- `playwright-cli` - 实际入口是 `@playwright/cli`，依赖 `playwright-core`
- `@playwright/cli` - 真正的 Playwright CLI

### 正确安装
```bash
npm install -g playwright-cli  # 安装后实际运行的是 @playwright/cli
```

### 教训
遇到 "could not determine executable to run" 错误时，检查包的实际入口点。

---

## 3. 浏览器连接与 headed 模式

### 问题
playwright-cli 启动的浏览器默认是 headless（无界面），用户看不到操作过程。

### 解决方案
需要用户手动启动带调试端口的 Chrome：
```bash
chrome --remote-debugging-port=9222
```
然后 Claude Code 连接到这个已打开的浏览器：
```bash
npx @playwright/cli attach --cdp=http://127.0.0.1:9222 --json
```

### 教训
操作浏览器时必须确保用户能看到浏览器界面，否则无法确认操作是否正确执行。

---

## 4. iframe 内坐标计算

### 问题
iframe 内元素的 `getBoundingClientRect()` 返回的是相对于 iframe 视口的坐标，需要加上 iframe 元素的偏移量才能得到页面绝对坐标。

### 正确方法
```javascript
// 获取 iframe 内元素的相对坐标
var r = element.getBoundingClientRect();
var x = r.left + r.width / 2;
var y = r.top + r.height / 2;

// 获取 iframe 元素在页面中的偏移
var iframeEl = document.querySelector('#myiframe');
var iframeRect = iframeEl.getBoundingClientRect();

// 绝对坐标 = 相对坐标 + iframe偏移
var absoluteX = x + iframeRect.left;
var absoluteY = y + iframeRect.top;
```

### 教训
跨 iframe 操作时，必须计算 iframe 元素本身的偏移量，不能直接使用元素相对坐标。

---

## 5. 表单验证状态检查

### 问题
执行操作后（如点击、填写），需要确认表单验证状态是否更新，否则提交会失败。

### 解决方案
每次关键操作后检查验证错误：
```javascript
var errors = modal.querySelectorAll('.ant-form-item-explain-error');
// 如果有错误，列表长度 > 0
```

### 教训
对于 Vue 框架的表单组件，DOM 状态的改变不等于 Vue formState 的更新。必须通过验证错误来确认操作是否真正成功。

---

## 6. ant-picker 日期选择器操作

### 问题
施工养护表单中有两个日期选择器（开始时间、结束时间）。点击 picker 输入框会打开日期面板，需要在面板中选择具体日期。

### 操作流程
1. 点击 picker 输入框打开面板
2. 在面板中点击对应的日期单元格（如 "4" 或 "5"）
3. 等待面板关闭或自动选择时间

### 关键选择器
- picker 输入框：`input[placeholder="开始时间"]`
- 日期单元格：`.ant-picker-cell-inner`（需检查 `offsetParent` 确保可见）
- 关闭状态的面板：`display:none`，需要用 `:not([style*="display:none"])` 筛选

### 教训
ant-picker 的日期选择必须走完整 UI 点击流程，JS 赋值无效。

---

## 7. 占道信息图标切换

### 问题
施工养护表单中的占道信息需要点击车道图标来启用/禁用。图标有三种状态：
- `icon icon-open` - 畅通（绿色箭头）
- `icon icon-close` - 占道（红色X）
- `icon icon-open is-disabled` - 禁用状态

### 操作要点
- 点击 `i.icon-open` 可以启用占道（变为 `icon-close`）
- 已禁用的图标（`is-disabled`）无法点击
- 需要点击图标元素本身，而非 li 父元素

### 验证方法
点击后检查 className 是否包含 `icon-close` 或 `icon-open`。

### 教训
占道信息必须点击图标来启用，仅修改 DOM class 不触发 Vue 事件。

---

## 8. 施工养护表单特殊结构

### 表单组成
施工养护使用 `mask-dialog-style-component` class 的自定义模态框，包含：

| 字段 | 组件类型 | 填写方式 |
|------|----------|----------|
| 计划时间 | 2个 ant-picker | 鼠标点击选择 |
| 施工类型 | group-item 单选 | 默认主线施工 |
| 路线名称 | ant-select | 预填 G2 京沪高速 |
| 桩号 | 4个 input-number | JS 赋值 + dispatchEvent |
| 占道信息 | event-road-half | 点击图标切换 |
| 施工内容 | checkbox 组 | 默认日常养护 |
| 施工说明 | textarea | 自动生成或手动 |

### 桩号字段索引
表单内有 4 个 input-number，排列顺序：
1. 起点千米桩（如 800）
2. 起点百米桩（如 0）
3. 终点千米桩（如 815）
4. 终点百米桩（如 0）

### 教训
施工养护表单结构复杂，需要按顺序处理每个字段，验证错误会阻止提交。

---

## 9. 确认按钮点击

### 问题
点击"确认"按钮后，模态框应该关闭。如果不关闭，说明表单验证未通过。

### 解决方案
1. 先检查 `ant-form-item-explain-error` 确认无验证错误
2. 用 `page.mouse.click(x, y)` 点击确认按钮
3. 点击后等待并检查 `.mask-dialog-style-component` 是否仍存在

### 教训
确认按钮点击后必须验证模态框是否关闭，这是判断操作成功的最直接方式。

---

## 10. 操作日志与调试

### 关键日志点
- 每次操作前：记录目标元素和坐标
- 每次操作后：检查验证状态
- 提交后：检查模态框是否关闭
- 最终验证：检查事件数量是否增加

### 调试技巧
```javascript
// 在浏览器控制台执行，查看实时状态
document.querySelector('#myiframe').contentDocument.querySelectorAll('.ant-form-item-explain-error')
```

### 教训
详细的操作日志能快速定位问题，避免重复调试。

---

## 经验速查表

| 场景 | 操作方式 | 验证方法 |
|------|----------|----------|
| 账号登录 | fill + click | 页面跳转到目标URL |
| 展开事件类型 | click button | badge数量变化 |
| 打开创建表单 | click +图标 | modal出现 |
| 填写桩号 | JS赋值+dispatchEvent | input值变化 |
| 选择日期 | 鼠标点击picker+cell | input显示日期值 |
| 启用占道 | 鼠标点击icon | className变化 |
| 表单提交 | 鼠标点击确认 | modal关闭 |
| 验证成功 | - | 无.ant-form-item-explain-error |

---

## 项目笔记

### 2026-06-04 施工养护事件创建（自动化执行）

**网站**: zhdd3.ry.gd 事件处置系统

| 发现 | 说明 |
|------|------|
| playwright-cli 每次执行都需用户授权确认 | 优先用 Python Playwright 脚本 |
| 用户需要能看见浏览器界面才能配合调试 | 必须用 headed 模式 Chrome |
| 施工养护表单占道信息需点击 i.icon-open 图标 | 不是点击 li，是里面的 i 元素 |
| 日期选择器必须走完整UI点击流程 | click picker → click day cell |
| iframe内 mousemove+mousedown+mouseup 才生效 | 不能用 click ref |
| 确认后要检查 .mask-dialog-style-component 是否为0 | >0 说明验证失败 |

**自动化执行新发现**:
| 发现 | 说明 |
|------|------|
| CDP连接browser.contexts[0].pages[0] | 使用已存在的页面，不是新建 |
| page.evaluate 中文JS字符串正常 | Python文件编码utf-8时没问题 |
| iframe内按钮需用真实鼠标坐标点击 | page.mouse.click(x,y) 而非 JS .click() |
| 表单验证errors:[]为空不等于验证通过 | 需检查input的实际value值 |
| dispatchEvent('input')+('change')后value可能有残留 | 验证状态要查values数组 |

**注意事项**:
- 表单验证状态和DOM状态是两回事
- icon-close 已有的不需要再点击
- 施工养护表单默认主线施工、日常养护
- JS赋值后要检查validation_result.values确认实际值

### 2026-06-05 交通事故表单（47用例完整执行）

**脚本**: `D:\test-project\调度3.0\scripts\test_traffic_accident_full.py`

| 发现 | 说明 |
|------|------|
| 直接用 Playwright Page API 最稳定 | 不要加 BrowserHelper 封装层 |
| iframe 内元素查找用 `contentDocument` | 绝对不能用 Playwright frame API |
| f-string 中引号冲突会报 SyntaxError | 检查 JS 字符串嵌套引号 |
| page.mouse.click(x,y) 是必须的 | 对于 Vue @click 组件，JS .click() 只改 DOM 不触发事件 |

### 2026-06-05 车辆故障表单（176用例调试过程）

**脚本**: `D:\test-project\调度3.0\scripts\test_vehicle_fault.py`

#### 核心发现

| 发现 | 说明 | 解决方案 |
|------|------|---------|
| JS `.click()` 在 action 按钮上不触发 Vue 事件 | action 是 `<img>` 不是 `<button>`，无 DOM click 事件 | 必须用 `page.mouse.click(x, y)` 真实坐标 |
| 打开弹窗需要两步 | 先 `item.click()` 激活，再 `mouse.click` action 按钮 | 完整的 `open_create_modal` 需要两步 |
| JS 赋值 `input.value = 'xxx'` 不触发 Vue 双向绑定 | Vue 的 `v-model` 不响应直接 DOM 赋值 | 必须 `mouse.click(input)` 聚焦，再用 `keyboard.type()` |
| 表单数据跨用例残留 | 前一个 case 填写的数据会保留到下一个 case | 每个 case 开头必须 `reset_form()` |
| iframe 内坐标要加偏移 | `getBoundingClientRect` 相对于 iframe，需加 iframe 的 left/top | `x = elementRect.left + elementRect.width/2 + iframeRect.left` |
| f-string 中 `role='spinbutton'` 单引号冲突 | `querySelectorAll('input[role='spinbutton']')` 语法错误 | 改用双引号 `role="spinbutton"` |
| `reset_form` 在弹窗关闭时找不到 modal | 返回 null 而非报错 | 在 `reset_form` 中先检查 modal 是否存在 |

#### 正确的 open_create_modal（通用，所有事件类型）

**根据是否有事件，分两种方式打开创建弹窗：**

**有事件时（badge > 0）：** 先点击事件类型按钮展开，再点击出现的"+"图标
```python
def open_create_modal(page, event_name):
    # Step 1: 点击事件类型按钮（如"交通事故"）展开列表
    page.evaluate(f"""
        () => {{
            const d = document.querySelector('#myiframe').contentDocument;
            const items = d.querySelectorAll('.event-type');
            for (const item of items) {{
                const label = item.querySelector('.event-type__label');
                if (label && label.textContent.includes('{event_name}')) {{
                    item.click();  // 点击展开
                    return;
                }}
            }}
        }}
    """)
    time.sleep(0.5)

    # Step 2: 点击展开后出现的"+"号图标
    result = page.evaluate(f"""
        () => {{
            const d = document.querySelector('#myiframe').contentDocument;
            const items = d.querySelectorAll('.event-type');
            for (const item of items) {{
                const label = item.querySelector('.event-type__label');
                if (label && label.textContent.includes('{event_name}')) {{
                    const btn = item.querySelector('.event-type__action');
                    if (!btn) return {{ found: false }};
                    const r = btn.getBoundingClientRect();
                    const iframe = document.querySelector('#myiframe').getBoundingClientRect();
                    return {{
                        found: true,
                        x: r.left + r.width / 2 + iframe.left,
                        y: r.top + r.height / 2 + iframe.top
                    }};
                }}
            }}
            return {{ found: false }};
        }}
    """)
    if result.get("found"):
        page.mouse.click(result["x"], result["y"])
    time.sleep(2)
```

**无事件时（badge = 0）：** 页面中间会出现"创建事件"按钮，点击中间按钮
```python
def open_create_modal_when_empty(page):
    page.evaluate("""
        () => {
            const d = document.querySelector('#myiframe').contentDocument;
            const btns = d.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.includes('创建事件')) {
                    btn.click();
                    return;
                }
            }
        }
    """)
    time.sleep(2)
```

#### 正确的 fill_pile_number（鼠标点击 + keyboard.type）

```python
def fill_pile_number(page, km='800', hm='50'):
    for attempt in range(3):
        result = page.evaluate("""
            () => {
                const d = document.querySelector('#myiframe').contentDocument;
                const modal = d.querySelector('.mask-dialog-style-component');
                if (!modal) return null;
                const spins = modal.querySelectorAll('input[role="spinbutton"]');
                if (spins.length < 2) return null;
                const iframe = document.querySelector('#myiframe').getBoundingClientRect();
                return {
                    kmX: spins[0].getBoundingClientRect().left + spins[0].getBoundingClientRect().width / 2 + iframe.left,
                    kmY: spins[0].getBoundingClientRect().top + spins[0].getBoundingClientRect().height / 2 + iframe.top,
                    hmX: spins[1].getBoundingClientRect().left + spins[1].getBoundingClientRect().width / 2 + iframe.left,
                    hmY: spins[1].getBoundingClientRect().top + spins[1].getBoundingClientRect().height / 2 + iframe.top,
                };
            }
        """)
        if result:
            break
        time.sleep(0.5)

    if not result:
        return

    # 先点击输入框聚焦，再用键盘输入
    page.mouse.click(result["kmX"], result["kmY"])
    time.sleep(0.2)
    page.keyboard.type(str(km))
    time.sleep(0.2)
    page.mouse.click(result["hmX"], result["hmY"])
    time.sleep(0.2)
    page.keyboard.type(str(hm))
    time.sleep(0.5)
```

#### reset_form（在弹窗存在时清空字段）

```python
def reset_form(page):
    page.evaluate("""
        () => {
            const d = document.querySelector('#myiframe').contentDocument;
            const modal = d.querySelector('.mask-dialog-style-component');
            if (!modal) return;  // 弹窗不存在时跳过
            // 清空桩号
            const inputs = modal.querySelectorAll('input[role="spinbutton"]');
            for (const inp of inputs) {
                inp.value = '';
                inp.dispatchEvent(new Event('input', {bubbles: true}));
                inp.dispatchEvent(new Event('change', {bubbles: true}));
            }
            // 重置影响位置
            const locs = modal.querySelectorAll('.location-option, .location-item');
            for (const loc of locs) {
                loc.classList.remove('checked', 'active');
                const inp = loc.querySelector('input');
                if (inp) inp.checked = false;
            }
            // 重置占道信息
            const halves = modal.querySelectorAll('.event-road-half');
            for (const half of halves) {
                const openIcons = half.querySelectorAll('i.icon-close');
                for (const icon of openIcons) icon.click();
            }
        }
    """)
    time.sleep(0.5)
```

#### 踩坑速查表

| 问题 | 原因 | 解决 |
|------|------|------|
| `SyntaxError: missing ) after argument` | f-string 中 `role='spinbutton'` 单引号嵌套 | 改 `role="spinbutton"` 双引号 |
| `page.mouse.click()` 无反应 | iframe 偏移没加 | 坐标 + iframe.getBoundingClientRect().left/top |
| JS 赋值 input.value 无效 | Vue 不响应直接 DOM 赋值 | `mouse.click()` + `keyboard.type()` |
| `.click()` 不触发 Vue @click | action 元素是 `<img>` 不是可点击元素 | 用 `page.mouse.click(x,y)` |
| 表单数据跨用例残留 | 没有重置 | 每 case 开头 `reset_form()` |
| `reset_form` 找不到 modal | 弹窗已关闭 | 先检查 modal 是否存在再操作 |
| 交通事故脚本能跑但车辆故障不行 | 两步点击流程不同 | 车辆故障需要：激活 + action 坐标点击 |

---

### 待补充

- [ ] 车辆故障组件操作要点
- [ ] 其他项目经验

---

## 11. 交通事故表单操作要点（已验证）

### 打开弹窗
```python
page.evaluate("""
    () => {
        const d = document.querySelector('#myiframe').contentDocument;
        const items = d.querySelectorAll('.event-type');
        for (const item of items) {
            const label = item.querySelector('.event-type__label');
            if (label && label.textContent.includes('交通事故')) {
                const btn = item.querySelector('.event-type__action');
                if (btn) btn.click();
                return;
            }
        }
    }
""")
time.sleep(2)
```

### 切换影响位置
```python
def switch_location(page, loc):
    loc_map = {'主线': 0, '收费站': 1, '服务区': 2, '枢纽': 3}
    idx = loc_map.get(loc, 0)
    page.evaluate(f"""
        () => {{
            const d = document.querySelector('#myiframe').contentDocument;
            const options = d.querySelectorAll('.location-option, .location-item');
            if (options.length > {idx}) {{
                options[{idx}].click();
            }}
        }}
    """)
    time.sleep(0.5)
```

### 填写桩号
```python
def fill_pile_number(page, km='800', hm='50'):
    page.evaluate(f"""
        () => {{
            const d = document.querySelector('#myiframe').contentDocument;
            const inputs = d.querySelectorAll('input[role='spinbutton']');
            if (inputs.length >= 2) {{
                inputs[0].value = '{km}';
                inputs[0].dispatchEvent(new Event('input', {{bubbles: true}}));
                inputs[1].value = '{hm}';
                inputs[1].dispatchEvent(new Event('input', {{bubbles: true}}));
            }}
        }}
    """)
    time.sleep(0.5)
```

### 切换占道信息
```python
def toggle_road_block(page, direction=0, lane=0):
    page.evaluate(f"""
        () => {{
            const d = document.querySelector('#myiframe').contentDocument;
            const halves = d.querySelectorAll('.event-road-half');
            if (halves.length > {direction}) {{
                const icons = halves[{direction}].querySelectorAll('i.icon-open');
                if (icons.length > {lane}) {{
                    icons[{lane}].click();
                }}
            }}
        }}
    """)
    time.sleep(0.5)
```

### 关闭弹窗（点击取消）
```python
def close_modal(page):
    page.evaluate("""
        () => {
            const d = document.querySelector('#myiframe').contentDocument;
            const btns = d.querySelectorAll('button');
            for (const btn of btns) {
                if (btn.textContent.trim() === '取消') {
                    btn.click();
                    return;
                }
            }
        }
    """)
    time.sleep(1)
```

### 用 X 点击关闭图标
```python
page.evaluate("""
    () => {
        const d = document.querySelector('#myiframe').contentDocument;
        const closeBtn = d.querySelector('.anticon-close');
        if (closeBtn) closeBtn.click();
    }
""")
```

### 获取表单状态
```python
def get_form_state(page):
    return page.evaluate("""
        () => {
            const d = document.querySelector('#myiframe').contentDocument;
            if (!d) return { modal: null, errors: [] };
            const modal = d.querySelector('.mask-dialog-style-component');
            const errs = d.querySelectorAll('.ant-form-item-explain-error');
            const errMsgs = [];
            for (const e of errs) errMsgs.push(e.textContent);
            return { modal: !!modal, errors: errMsgs };
        }
    """)
```

### 常见验证规则
| 字段 | 验证失败提示 |
|------|-------------|
| 影响位置未选 | 影响位置为必填 |
| 路线名称未选 | 路线名称为必填 |
| 桩号超范围 | 超出了管辖范围，请重新输入 |
| 桩号超长 | 系统限制输入长度 |
| 占道信息未选 | 占道信息为必选 |

---

## 12. 车辆故障创建全流程测试（2026-06-05）

**项目**: 协同指挥调度系统 - 调度3.0
**用例**: CS-F_UC_B_CLGZ_XXSB-001 完整创建流程 - 新建车辆故障并保存成功

### 踩坑记录

#### 问题1：影响位置选择器错误
- **错误选择器**: `.location-option, .location-item`
- **正确选择器**: `.group-item`（位于 `.impact-location-options` 容器内）
- **现象**: 切换影响位置时无反应
- **调试方法**: 检查 modal HTML 发现影响位置选项使用 `.group-item` class

```javascript
// 错误 ❌
const options = d.querySelectorAll('.location-option, .location-item');

// 正确 ✅
const modal = d.querySelector('.mask-dialog-style-component');
const options = modal.querySelectorAll('.group-item');
```

#### 问题2：占道图标点击无效（JS .click() 不触发 Vue 事件）
- **现象**: 点击 `.icon-open` 后 class 不变，验证仍报"占道信息为必选"
- **原因**: `icon.click()` 只触发 DOM 事件，不触发 Vue @click 事件处理器
- **解决**: 必须用 `page.mouse.click(x, y)` 真实鼠标点击

```python
# 错误 ❌ - icon.click() 不触发 Vue
page.evaluate("""
    () => {
        const icons = modal.querySelectorAll('i.icon-open');
        icons[0].click();  // 只改 DOM，Vue 不知道
    }
""")

# 正确 ✅ - mouse.click 触发 Vue 事件
result = page.evaluate("""
    () => {
        const icon = document.querySelector('i.icon-open');
        const r = icon.getBoundingClientRect();
        const iframe = document.querySelector('#myiframe').getBoundingClientRect();
        return {
            x: r.left + r.width/2 + iframe.left,
            y: r.top + r.height/2 + iframe.top
        };
    }
""")
page.mouse.click(result["x"], result["y"])  # 触发 Vue @click
```

#### 问题3：占道信息需要先选影响位置才能操作
- **现象**: 直接点击占道图标无效
- **原因**: 占道选项依赖于影响位置的选择
- **解决**: 必须先 `switch_location('主线')` 再点击占道图标

### 完整执行步骤（车辆故障全流程）

1. `open_create_modal(page, '车辆故障')` - 打开创建弹窗
2. `switch_location(page, '主线')` - 选择影响位置
3. `fill_pile_number(page, '800', '50')` - 填写桩号
4. `select_road_block(page, 0)` - 选择占道信息（用 mouse.click）
5. `click_confirm(page)` - 点击确认

### 调试技巧

- 用 `page.evaluate()` 在浏览器中实时检查元素状态
- 检查 `icon.className` 从 `icon-open` 变为 `icon-close` 来验证点击成功
- 表单验证错误列表可通过 `querySelectorAll('.ant-form-item-explain-error')` 获取
