# Ant Design Vue 组件交互模式

通过 Playwright Python API 操作 Ant Design Vue 组件（Vue 3），需要特殊处理。
此文件补充 elementui-patterns.md，专注于 Ant Design Vue 特有的交互模式。

## 🚨🚨 最高优先级：跨域 iframe 完全绕开 Frame 对象 🚨🚨

**2026-06-01 重大发现：Playwright 的 Frame 对象对跨域 iframe 完全不可靠！**

### 问题表现

```
frame.evaluate("() => document.querySelectorAll('.event-type').length")  # → 0
frame.locator("button.event-type").count()                                # → 0
```

即使 `frame.url` 正确指向 iframe URL，`evaluate()` 返回的是顶层页面上下文，`locator()` 找不到 iframe 内元素。

### 唯一有效方案

```python
IFRAME_DOC = 'document.querySelector("#myiframe").contentDocument'
IFRAME_EL  = 'document.querySelector("#myiframe")'

# 访问 iframe DOM：用 page.evaluate + 显式穿越 contentDocument
page.evaluate("()=>{var d=" + IFRAME_DOC + ";return d.querySelectorAll('.event-type').length;}")

# 在 iframe 内点击：计算 iframe 内坐标 + iframe offset → page.mouse.click
c = page.evaluate("()=>{var d=" + IFRAME_DOC + ";...getBoundingClientRect();return{x:,y:};}")
off = page.evaluate("()=>{var r=" + IFRAME_EL + ".getBoundingClientRect();return{x:r.left,y:r.top};}")
page.mouse.click(c["x"] + off["x"], c["y"] + off["y"])
```

**绝不要再用 frame.evaluate() 或 frame.locator() — 永远用 page + iframe contentDocument。**

## 🚨 核心发现：Ant Design Vue 的所有 @click 绑定 MUST 用 page.mouse.click()

**这与 ElementUI MessageBox 确认按钮的问题完全一致，但影响范围更广。**

### 受影响组件列表

| 组件 | 问题表现 | JS .click() 结果 | page.mouse.click() 结果 |
|------|----------|-----------------|------------------------|
| 占道信息箭头 (li) | DOM icon 切换但表单验证不过 | 假成功 | ✅ 真成功 |
| 表单确认按钮 | 关闭抽屉但不发 API | 假成功 | ✅ 真成功 |
| 表单取消按钮 | JS 可正常关闭 | ✅ | ✅ |

### 问题根因

Vue 3 的 `@click` 指令使用浏览器原生事件系统监听，程序化的 `.click()` 和 `dispatchEvent()` 虽然能在 DOM 层触发视觉效果（如 CSS class 切换），但**不会经过完整的事件捕获/冒泡链**，因此：
- Vue 的 `v-model` / `formState` **不会更新**
- Ant Design Form 的 `validateFields()` 永远报告字段未填写
- 确认按钮只是关闭了 drawer，没有调用 API

### 正确实现：`page.mouse.click(x, y)`

```python
def mouse_click_element(page: Page, selector: str, index: int = 0):
    """通过真实鼠标坐标点击 Ant Design Vue 组件（唯一可靠方式）。"""
    coords = page.evaluate(
        """({selector, index}) => {
            const els = document.querySelectorAll(selector);
            if (index >= els.length) return {found: false};
            const rect = els[index].getBoundingClientRect();
            return {
                found: true,
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2
            };
        }""",
        {"selector": selector, "index": index}
    )
    assert coords.get("found"), f"No element matching '{selector}' at index {index}"
    page.mouse.click(coords["x"], coords["y"])
```

### iframe 内的坐标修正（⚠️ Frame 对象不可靠！必须用 page.evaluate）

**绝不用 frame.evaluate()！** 所有操作通过 `page.evaluate` + 显式 `#myiframe.contentDocument`：

```python
IFRAME_DOC = 'document.querySelector("#myiframe").contentDocument'
IFRAME_EL  = 'document.querySelector("#myiframe")'

def iframe_click(page, target_js):
    """在 iframe 内找到元素并通过 page.mouse.click(x,y) 点击。
    target_js: 在 iframe 文档内运行，返回 {found, x, y}（坐标相对于 iframe 视口）"""
    c = page.evaluate("()=>{var d=" + IFRAME_DOC + ";" + target_js + "}")
    assert c.get("found"), f"Element not found: {c}"
    off = page.evaluate("()=>{var r=" + IFRAME_EL + ".getBoundingClientRect();return{x:r.left,y:r.top};}")
    page.mouse.click(c["x"] + off["x"], c["y"] + off["y"])
```

**千万不要**：
- ❌ `frame.evaluate(...)` — 跨域 iframe 返回空
- ❌ `frame.locator(...)` — 找不到 iframe 内元素
- ❌ `document.documentElement.getBoundingClientRect()` 作为 offset — 应该用 iframe 元素本身的位置

## 事件抽屉表单操作模式

### 系统结构

事件处理页面包含两种表单：

1. **主表单** - 页面打开即有，显示已选事件详情
2. **抽屉表单** - 点击 + 图标打开，用于新增事件

### 占道信息组件

每条道路方向下有多条 `li.event-road-item`，每条代表一个车道。

```html
<div class="event-road-half">
  <div class="event-road-text">北京-上海</div>
  <div class="event-road-main">
    <ul>
      <li class="event-road-item">
        <i class="icon icon-open"></i>  <!-- 绿色箭头 = 畅通 -->
      </li>
      <li class="event-road-item">
        <i class="icon icon-close"></i> <!-- 红色 X = 占道 -->
      </li>
      ...
    </ul>
  </div>
</div>
```

**定位策略**：`event-road-half` 元素在 DOM 中的位置：

| DOM 索引 | 所属表单 | 方向 | 说明 |
|----------|----------|------|------|
| `half[0]` | 主表单 | 北京-上海 | 始终可见 |
| `half[1]` | 主表单 | 上海-北京 | 始终可见 |
| `half[2]` | 抽屉表单 | 北京-上海 | 点击+打开后可见 |
| `half[3]` | 抽屉表单 | 上海-北京 | 点击+打开后可见 |

**注意**：如果通过 `offsetParent` 检查可见性来找 "可见的 北京-上海"，会先匹配到 `half[0]`（主表单）。操作抽屉表单时**必须直接按索引定位 `half[2]`/`half[3]`**。

### 操作流程（page.evaluate 版本 — 绕开 Frame 对象）

```python
import time
from playwright.sync_api import Page

IFRAME_DOC = 'document.querySelector("#myiframe").contentDocument'
IFRAME_EL  = 'document.querySelector("#myiframe")'

def iframe_click(page, target_js):
    c = page.evaluate("()=>{var d=" + IFRAME_DOC + ";" + target_js + "}")
    assert c.get("found")
    off = page.evaluate("()=>{var r=" + IFRAME_EL + ".getBoundingClientRect();return{x:r.left,y:r.top};}")
    page.mouse.click(c["x"] + off["x"], c["y"] + off["y"])

def create_vehicle_fault_event(page: Page, km_pile: str, m_pile: str):
    # 1. 打开车辆故障抽屉表单
    iframe_click(page,
        "var btn=d.querySelector('.event-type.is-active .event-type__action');"
        "if(btn){var r=btn.getBoundingClientRect();return{found:true,x:r.left+r.width/2,y:r.top+r.height/2};}"
        "return{found:false};"
    )
    time.sleep(2)

    # 2. 占道信息 - page.mouse.click（Vue @click 唯一触发方式）
    iframe_click(page,
        "var h=d.querySelectorAll('.event-road-half');"
        "for(var i=h.length-1;i>=0;i--){var t=h[i].querySelector('.event-road-text');"
        "if(t&&t.textContent.indexOf('\u5317\u4eac')>=0&&h[i].offsetParent){"
        "var items=h[i].querySelectorAll('.event-road-item');if(items.length>0){"
        "var icon=items[0].querySelector('i');if(icon){"
        "var r=icon.getBoundingClientRect();return{found:true,x:r.left+r.width/2,y:r.top+r.height/2};}}}}"
        "return{found:false};"
    )
    time.sleep(0.5)

    # 3. 确认提交 - page.mouse.click
    iframe_click(page,
        "var btns=d.querySelectorAll('button');for(var i=0;i<btns.length;i++){"
        "if(btns[i].textContent.indexOf('\u786e')>=0&&btns[i].textContent.indexOf('\u8ba4')>=0){"
        "var r=btns[i].getBoundingClientRect();return{found:true,x:r.left+r.width/2,y:r.top+r.height/2};}}"
        "return{found:false};"
    )
    time.sleep(2.5)
```

## Ant Design DatePicker（日期时间选择器）

### 核心约束
- **JS value 赋值不触发 Vue formState 更新**，必须走完整 UI 点击流程
- DatePicker 面板渲染在 iframe 内，所有操作必须通过 `page.evaluate` + `#myiframe.contentDocument`
- **必须**：click picker input → click day cell → click time cell → click OK button

### CSS 选择器速查

| 作用 | 选择器 | 说明 |
|------|--------|------|
| picker 输入框 | `.ant-picker-input input` | 点击展开面板 |
| 日历 day cell | `.ant-picker-cell-inner` | 天数文本（如 "1"） |
| 时间列 cell | `.ant-picker-time-panel-cell-inner` | 时分秒值（如 "14"） |
| OK 确认按钮 | `.ant-picker-ok button` | 关闭面板并提交值 |

### 完整流程示例（iframe 内）

```python
def select_date_time(page, form_item_index, hour):
    """在 iframe 内选择日期（当月1号）和时间。
    form_item_index: .ant-form-item 索引（如 15=开始, 16=结束）
    hour: 小时值（如 "14", "18"）"""
    IFRAME_DOC = 'document.querySelector("#myiframe").contentDocument'
    IFRAME_EL  = 'document.querySelector("#myiframe")'

    def iclick(js_selector):
        c = page.evaluate("()=>{var d=" + IFRAME_DOC + ";" + js_selector + "}")
        assert c.get("found"), f"Not found"
        off = page.evaluate("()=>{var r=" + IFRAME_EL + ".getBoundingClientRect();"
                           "return{x:r.left,y:r.top};}")
        page.mouse.click(c["x"] + off["x"], c["y"] + off["y"])

    # 1. 点击 picker 打开面板
    iclick("var items=d.querySelectorAll('.ant-form-item');var f=items[" + str(form_item_index) + "];"
           "var pk=f.querySelector('.ant-picker-input input');"
           "if(pk){var b=pk.getBoundingClientRect();"
           "return{found:true,x:b.left+b.width/2,y:b.top+b.height/2};}return{found:false};")
    time.sleep(1.5)

    # 2. 点击天数 "1"（当月1号）
    iclick("var cells=d.querySelectorAll('.ant-picker-cell-inner');"
           "for(var i=0;i<cells.length;i++)"
           "{if(cells[i].offsetParent&&cells[i].textContent.trim()==='1')"
           "{var b=cells[i].getBoundingClientRect();"
           "return{found:true,x:b.left+b.width/2,y:b.top+b.height/2};}}return{found:false};")
    time.sleep(0.5)

    # 3. 点击时间列 cell
    iclick("var cells=d.querySelectorAll('.ant-picker-time-panel-cell-inner');"
           "for(var i=0;i<cells.length;i++)"
           "{if(cells[i].offsetParent&&cells[i].textContent.trim()==='" + hour + "')"
           "{var b=cells[i].getBoundingClientRect();"
           "return{found:true,x:b.left+b.width/2,y:b.top+b.height/2};}}return{found:false};")
    time.sleep(0.3)

    # 4. 点击 OK 按钮
    iclick("var btns=d.querySelectorAll('.ant-picker-ok button');"
           "for(var i=0;i<btns.length;i++)"
           "{if(btns[i].offsetParent)"
           "{var b=btns[i].getBoundingClientRect();"
           "return{found:true,x:b.left+b.width/2,y:b.top+b.height/2};}}return{found:false};")
    time.sleep(0.5)

# 使用示例：施工养护表单
select_date_time(page, 15, "14")  # 开始时间 → 2026-06-01 14:00
select_date_time(page, 16, "18")  # 结束时间 → 2026-06-01 18:00
```

### 施工养护表单日期字段索引

施工养护使用**内联自定义 modal**（`mask-dialog-style-component`），非 ant-drawer。

展开表单项编号（`.ant-form-item` 全局索引）：

| 索引 | 标签 | 组件 | 说明 |
|------|------|------|------|
| 14 | 计划时间 | label only | 日期范围标签 |
| **15** | N/A | **ant-picker start** | 开始日期时间 |
| **16** | N/A | **ant-picker end** | 结束日期时间 |
| 17 | 施工类型 | radio group | 主线施工/etc. |
| 18 | 路线路段 | label | G2 京沪高速（预填） |
| **19** | 桩号 | **4×input-number** | K起点桩,m起点,K终点桩,m终点 |
| 22 | 占道信息 | road-half | 车道图标切换 |

### JS 赋值陷阱

```python
# ❌ 不可行 — Vue 不更新 formState
page.evaluate("()=>{var d=...;document.querySelector('.ant-picker-input input').value='2026-06-01 14:00:00';}")

# ✅ 必须走 UI 点击流程
select_date_time(page, 15, "14")
```

## Ant Design InputNumber

与 ElementUI 的 `el-input-number` 不同，Ant Design 使用 `<a-input-number>`：

```python
# 填写数值 — JS evaluate 赋值 + dispatchEvent('input') + dispatchEvent('change')
page.evaluate("""
    () => {
        var d = document.querySelector('#myiframe').contentDocument;
        var items = d.querySelectorAll('.ant-form-item');
        var f = items[19];  // 施工养护桩号字段
        var inps = f.querySelectorAll('.ant-input-number-input');
        var vals = ['789', '26', '859', '999'];
        for (var i = 0; i < Math.min(inps.length, vals.length); i++) {
            inps[i].focus();
            inps[i].value = vals[i];
            inps[i].dispatchEvent(new Event('input', {bubbles: true}));
            inps[i].dispatchEvent(new Event('change', {bubbles: true}));
        }
    }
""")

# 施工养护桩号关键点：item[19] 有 4 个 input-number
# [K起点桩, m起点, K终点桩, m终点] = ['789','26','859','999']
# ⚠️ 必须全部填充 4 个，漏填会报 "请输入千米桩"
```

## 验证断言模式

```python
# 验证 badge 数量增加
def test_event_count_increased(frame):
    count = frame.evaluate("""() => {
        const labels = document.querySelectorAll('.event-type__label');
        const badges = document.querySelectorAll('.event-type__badge');
        for (let i = 0; i < labels.length; i++)
            if (labels[i].textContent.includes('车辆故障'))
                return badges[i] ? badges[i].textContent : '?';
        return 'NA';
    }""")
    assert count == "2", f"Expected event count 2, got {count}"

# 验证新增事件出现在列表中
def test_new_event_in_list(frame, event_id: str):
    body = frame.locator("body").inner_text()
    assert event_id in body, f"New event {event_id} not found on page"
```

## 通用交互模式总结

| 组件 | 定位方式 | 交互方式 | 注意事项 |
|------|----------|----------|----------|
| **event-road-item** | `.event-road-half[n] li` | **page.mouse.click(x,y)** | JS click 只改 CSS，不更新 Vue formState |
| **ant-btn/确认** | button text '确 认' | **page.mouse.click(x,y)** | 与 MessageBox 确认按钮相同 |
| ant-input-number | `.ant-input-number-input` | `fill()` 或 `type()` | fill 通常可用 |
| event-type__action | `.event-type.is-active` 内按钮 | **page.mouse.click(x,y)** | 跨域 iframe 不能用 locator |
| 表单抽屉标识 | half[n] 索引 | half[0/1]=主表单, half[2/3]=抽屉 | 不能用 offsetParent 检查可见性 |

## 🐛 Windows 编码陷阱：中文在 JS 字符串中必须用 \uXXXX

Windows 终端是 GBK 编码，pytest 输出中文会被乱码。但更隐蔽的问题是：

**Python 脚本中的中文文字传递给 `page.evaluate()` 时，在某些环境下会被 GBK 二度编码破坏**，
导致 `textContent.indexOf('北京')` 永远返回 -1。

```python
# ❌ 不可靠 — 中文字面量在 GBK 环境下败坏
iframe_click(page, "...textContent.indexOf('北京')...")  # 用 \u 转义

# ✅ 永远可靠 — unicode 转义不受终端编码影响
iframe_click(page, "...textContent.indexOf('\u5317\u4eac')...")
#                                          ^^^^^^^
#                                          \u5317 = 北, \u4eac = 京
```

**规则**：所有传给 page.evaluate/frame.evaluate 的 JS 字符串内，中文文字一律用 `\uXXXX` 转义。

常用转义速查：
| 中文 | \u 转义 |
|------|---------|
| 北京 | \u5317\u4eac |
| 上海 | \u4e0a\u6d77 |
| 车辆故障 | \u8f66\u8f86\u6545\u969c |
| 交通事故 | \u4ea4\u901a\u4e8b\u6545 |
| 施工养护 | \u65bd\u5de5\u517b\u62a4 |
| 确认 | \u786e\u8ba4 |
| 取消 | \u53d6\u6d88 |
| 添加 | \u6dfb\u52a0 |
| 开始时间 | \u5f00\u59cb\u65f6\u95f4 |
| 结束时间 | \u7ed3\u675f\u65f6\u95f4 |
| 桩号 | \u6869\u53f7 |
| 占道信息 | \u5360\u9053\u4fe1\u606f |
| 施工说明 | \u65bd\u5de5\u8bf4\u660e |
| 主线施工 | \u4e3b\u7ebf\u65bd\u5de5 |
| 不在管辖范围 | \u4e0d\u5728\u7ba1\u8f96\u8303\u56f4 |
| 请输入千米桩 | \u8bf7\u8f93\u5165\u5343\u7c73\u6869 |

## 新增概念：真实坐标点击作为默认策略

**优先规则**：遇到任何 Vue 框架（ElementUI / Ant Design Vue / etc.）的交互组件，**先尝试 page.mouse.click(x, y) 再尝试 locator.click()**。

判断是否需要 mouse.click 的经验法则：
- ✅ 直接可用 locator.click()：原生 HTML button、a 标签、普通 div click
- ⚠️ 通常需要 mouse.click()：Vue @click 绑定的按钮、表单字段组件、图标切换

不确定时，mouse.click() 是安全的退路——它不会比 locator.click() 更差。