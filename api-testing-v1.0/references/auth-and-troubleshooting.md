# 鉴权与排错

> 本文档定义鉴权方式配置、常见响应问题排查。配置 `config.ini` 的 `[auth]` 段或测试遇到响应异常时参考。

---

## 一、鉴权方式

### 1.1 配置位置

所有鉴权信息统一配置在 `config.ini` 的 `[auth]` 段：

```ini
[auth]
auth_type = mobile      ; 必填：appcode / mobile / token / none
mobile    = 152XXXXXXXX ; mobile 鉴权时填写
app_code  =             ; appcode 鉴权时填写
```

**禁止**在测试脚本或用例参数中硬编码鉴权信息。

### 1.2 鉴权类型说明

| auth_type | 请求头 | 适用场景 |
|-----------|--------|----------|
| `appcode` | `appCode: xxx` 或 Query | 通用 SaaS 接口 |
| `mobile` | `mobile: 手机号` | 移动端接口，后端按手机号识别用户 |
| `token` | `Authorization: Bearer xxx` | OAuth2 / JWT 认证 |
| `none` | 无鉴权头 | 内网/已脱鉴环境 |

### 1.3 auth_type 选择规则

| 特征 | auth_type |
|------|-----------|
| 后端按手机号识别用户 | `mobile` |
| 需要 appCode / appId | `appcode` |
| 返回 JWT / Bearer token | `token` |
| 内网/无鉴权 | `none` |

---

## 二、常见问题排查

| 问题现象 | 可能原因 | 处理方式 |
|----------|----------|----------|
| HTTP 401 | 鉴权信息无效或过期 | 确认 config.ini 中 auth_type 和鉴权值正确 |
| HTTP 403 | 无权限访问 | 确认账户权限或更换测试账号 |
| HTTP 500 | 服务端异常 | 查看 biz_msg 定位问题，或联系后端 |
| biz 500 | 业务校验失败 | 检查必填字段、参数格式、业务规则 |
| biz 501 | 业务功能未实现 | 接口尚未开发，跳过此类用例 |
| 返回空数据 | 查询条件无匹配 | 调整参数或确认测试数据存在 |
| 缺少字段 | 期望与实际响应不一致 | 用实际响应修正用例期望值 |

---

## 三、响应状态码说明

| biz 值 | 含义 | 通过判定 |
|--------|------|----------|
| biz 200 | 业务处理成功 | ✅ expect_ok |
| biz 500 | 业务处理失败 | ❌ expect_ok 会失败 |
| biz 501 | 功能未实现 | ❌ 接口未开发完成 |

**判定函数使用建议**：

| 用例类型 | expect_fn | 说明 |
|----------|------------|------|
| 正向测试 | 不填（默认 exp_ok） | 期望 biz 200 |
| 逆向测试 | `exp_biz_fail` | 期望 biz 500 或有业务错误提示 |
| 安全测试 | `exp_biz_fail` | 期望攻击被拦截返回 biz 500 |
| 边界测试 | `exp_biz_fail` | 期望参数校验失败返回 biz 500 |
| 自定义 | `exp_contains:关键字` | 期望响应包含特定关键字 |

---

## 四、配置文件参考

```ini
# 项目配置
[project]
name = 项目名称
description = 项目接口测试

# API 配置
[api]
base_url = http://xxx.xxx.xxx:端口/服务路径
apifox_url = https://xxx.apifox.cn

# 鉴权配置
[auth]
auth_type = mobile
mobile = 152XXXXXXXX

# 可选配置
[options]
timeout = 30
```
