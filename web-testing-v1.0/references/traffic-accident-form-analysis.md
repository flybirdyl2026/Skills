# 交通事故创建表单分析

基于测试用例 CS-F_UC_B_JTSG_XXSB_XJSJ-001 ~ 020

## 表单字段结构

### 必填字段
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| 影响位置 | radio | 主线 | 可选：主线/收费站/服务区/枢纽 |
| 路线名称 | combobox | - | 必填，下拉选择 |
| 桩号 | spinbutton | - | 必填，千米桩+百米桩 |
| 占道信息 | icon-toggle | - | 必选，至少选择一个车道 |
| 事件描述 | textarea | 自动生成 | 必填，自动根据字段生成 |

### 选填字段
| 字段 | 类型 | 说明 |
|------|------|------|
| 信息来源 | combobox | 交通执法 |
| 事发时间 | datetimepicker | 日期时间选择 |
| 报警人电话 | textbox | 电话号码 |
| 桥隧类型 | radio | 普通路段/桥梁段/隧道段 |
| 事故形态 | checkbox+combobox | 多选：2车追尾/撞中央护栏/碰撞/危化品泄露等 |
| 事故等级 | radio | 轻微/一般/较大/重大/特大 |
| 设备 | list | 自动匹配20公里内设备，支持增删 |
| 立即通知 | checkbox | 非必选 |

### 自动填充字段
| 字段 | 值 | 来源 |
|------|-----|------|
| 事件描述 | `[时间]在[路线][桩号]发生交通事故。[方向]占第[车道]车道，请注意现场安全！` | 根据表单字段自动生成 |
| 设备模板 | `前方XX公里第XX车道交通事故，请注意避让` | 根据桩号和车道自动联动 |

## 占道信息结构

```
占道信息
├── 北京-上海
│   ├── [icon] 车道1
│   ├── [icon] 车道2
│   ├── [icon] 车道3
│   ├── [icon] 车道4
│   └── [icon] 车道5
└── 上海-北京
    ├── [icon] 车道1
    ├── [icon] 车道2
    ├── [icon] 车道3
    ├── [icon] 车道4
    └── [icon] 车道5
```

- icon-open (绿色箭头) = 畅通
- icon-close (红色X) = 占道
- 点击图标切换状态

## 设备区域

- 自动带出事件点位后方20公里内的门架和声光报警设备
- 支持单个添加/删除设备
- 设备模板内容联动桩号和车道信息

## 验证规则

| 字段 | 验证规则 | 错误提示 |
|------|----------|----------|
| 影响位置 | 必选 | 影响位置为必填 |
| 路线名称 | 必选 | 路线名称为必填 |
| 桩号 | 必填，4位千米桩+3位百米桩 | 桩号为必填 |
| 桩号 | 不能超出路线管辖范围 | 超出了管辖范围，请重新输入 |
| 占道信息 | 必选 | 占道信息为必选 |
| 桩号格式 | 4位限制 | 系统限制输入长度 |

## 测试用例与操作对照

| 用例ID | 操作 | 验证点 |
|--------|------|--------|
| 001 | 点击【新建】按钮 | 默认选中"交通事故" |
| 002 | 点击【取消】按钮 | 弹窗关闭 |
| 003 | 查看影响位置选项 | 默认"主线" |
| 004 | 点击切换影响位置 | 页面联动更新 |
| 005 | 查看路线名称下拉框 | 默认"请选择" |
| 006 | 查看桩号输入框 | 无默认值 |
| 007 | 输入超长桩号 | 系统限制长度 |
| 008 | 输入超范围桩号 | 提示超出管辖范围 |
| 009 | 不选占道信息点击确定 | 提示必选 |
| 010 | 点击多个车道图标 | 多选高亮 |
| 011 | 查看设备区域 | 自动匹配20公里设备 |
| 012 | 点击【+】添加设备 | 添加最近设备 |
| 013 | 点击设备删除图标 | 移除设备 |
| 014 | 不选立即通知 | 无通知任务 |
| 015 | 选择清障+大队 | 生成清障任务 |
| 016 | 选择清扫/驳载 | 生成对应任务 |
| 017-019 | 必填项为空 | 提示相应字段为必填/必选 |
| 020 | 查看设备模板 | 内容联动正确 |

## 特殊操作技巧

### 占道信息点击
```javascript
// 点击北京-上海第1车道启用占道
page.evaluate("""
    () => {
        const d = document.querySelector('#myiframe').contentDocument;
        const half = d.querySelectorAll('.event-road-half')[0]; // 北京-上海
        const lane = half.querySelectorAll('li')[0]; // 第1车道
        const icon = lane.querySelector('i');
        if (icon.classList.contains('icon-open')) {
            icon.click(); // 切换为icon-close
        }
    }
""")
```

### 事故形态多选
```javascript
// 选择"2车追尾"事故形态
page.evaluate("""
    () => {
        const d = document.querySelector('#myiframe').contentDocument;
        const checkboxes = d.querySelectorAll('.accident-type-checkbox');
        for (const cb of checkboxes) {
            const label = cb.querySelector('.accident-type-label');
            if (label && label.textContent.includes('2车追尾')) {
                cb.querySelector('input').click();
                break;
            }
        }
    }
""")
```

### 设备添加
```javascript
// 点击添加设备按钮
page.evaluate("""
    () => {
        const d = document.querySelector('#myiframe').contentDocument;
        const addBtn = d.querySelector('.device-add-btn');
        if (addBtn) addBtn.click();
    }
""")
```

### 桩号输入
```javascript
// 填写桩号 K789 + 55
page.evaluate("""
    () => {
        const d = document.querySelector('#myiframe').contentDocument;
        const kmInput = d.querySelector('.pile-km-input input');
        const hmInput = d.querySelector('.pile-hm-input input');
        if (kmInput) {
            kmInput.value = '789';
            kmInput.dispatchEvent(new Event('input', {bubbles: true}));
        }
        if (hmInput) {
            hmInput.value = '55';
            hmInput.dispatchEvent(new Event('input', {bubbles: true}));
        }
    }
""")
```
