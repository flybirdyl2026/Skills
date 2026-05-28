#!/usr/bin/env python3
"""
generate_html_report.py — Generate a self-contained HTML test report from api_test_report.json

Usage:
    python generate_html_report.py --input api_test_report.json --output api_test_report.html

Arguments:
    --input   Path to api_test_report.json (output of run_tests.py)
    --output  Path to write the HTML report (default: api_test_report.html)
    --title   Optional title prefix for the report (default: "API 测试报告")
"""

import argparse
import json
import os
import sys
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

STATUS_BADGE = {
    "success":    ('<span class="badge success">✅ 成功</span>', "success"),
    "http_error": ('<span class="badge http-error">⚠️ HTTP 错误</span>', "http-error"),
    "error":      ('<span class="badge error">❌ 连接错误</span>', "error"),
}

METHOD_COLOR = {
    "GET": "#1677ff", "POST": "#13c2c2", "PUT": "#fa8c16",
    "DELETE": "#ff4d4f", "PATCH": "#722ed1",
}

DIAG_MAP = {
    "ConnectTimeoutError": (
        "连接超时（Connection Timeout）",
        [
            "<b>网络不可达</b> — 当前机器与目标服务器不在同一局域网，或端口未开放。"
            "请用 <code>ping</code> / <code>telnet &lt;host&gt; &lt;port&gt;</code> 验证连通性。",
            "<b>服务未启动</b> — 目标服务器上的应用可能未运行，请检查服务进程。",
            "<b>防火墙拦截</b> — 请确认服务器防火墙已放行对应端口的入站规则。",
            "<b>IP / 端口有误</b> — 请再次确认 base URL 是否正确。",
            "<b>建议</b> — 在与服务器同一局域网内的机器上运行测试，或通过 VPN 接入后重试。",
        ]
    ),
    "ConnectionRefusedError": (
        "连接被拒绝（Connection Refused）",
        [
            "<b>服务未运行</b> — 目标端口没有进程在监听，请检查服务是否已启动。",
            "<b>端口有误</b> — 请确认端口号是否正确。",
        ]
    ),
    "401": (
        "认证失败（401 Unauthorized）",
        [
            "<b>Token 缺失或过期</b> — 请检查 interfaces.json 中的 Authorization/token header。",
            "<b>Token 格式有误</b> — 确认是否需要 'Bearer ' 前缀。",
        ]
    ),
    "403": (
        "权限不足（403 Forbidden）",
        [
            "<b>账号权限不足</b> — 当前 token 对应账号无权访问该接口。",
        ]
    ),
    "404": (
        "路径不存在（404 Not Found）",
        [
            "<b>Base URL 有误</b> — 请确认服务的根路径是否正确。",
            "<b>接口路径有误</b> — 请比对 Apifox 中的接口路径定义。",
        ]
    ),
}


def get_diagnosis(results: list) -> list:
    """Return a list of (title, points) diagnosis entries based on actual errors."""
    diagnoses = []
    seen = set()

    for r in results:
        if r["status"] == "success":
            continue
        error_str = str(r.get("error") or "")
        http_code = str(r.get("http_status") or "")

        for key, (title, points) in DIAG_MAP.items():
            if key in error_str or key == http_code:
                if title not in seen:
                    diagnoses.append((title, points))
                    seen.add(title)

    return diagnoses


def json_to_html_pre(obj, max_chars=3000) -> str:
    if obj is None:
        return "<i style='color:#aaa'>（无）</i>"
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        s = str(obj)
    if len(s) > max_chars:
        s = s[:max_chars] + "\n... (truncated)"
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_html(report: dict, title: str) -> str:
    summary = report["summary"]
    results = report["results"]
    total = summary["total_interfaces"]
    success = summary["success"]
    http_err = summary["http_error"]
    conn_err = summary["connection_error"]
    pass_rate = summary["pass_rate"]
    start_t = summary["start_time"]
    end_t = summary["end_time"]

    # Rows
    rows_html = ""
    detail_html = ""
    for i, r in enumerate(results):
        badge, row_cls = STATUS_BADGE.get(r["status"], ('', ''))
        method = r["method"]
        mcolor = METHOD_COLOR.get(method, "#666")
        http_code = r["http_status"] or "—"
        ms = f"{r['response_time_ms']} ms" if r["response_time_ms"] is not None else "—"
        name_escaped = str(r["name"]).replace("&", "&amp;").replace("<", "&lt;")
        url_escaped = str(r["url"]).replace("&", "&amp;").replace("<", "&lt;")

        rows_html += f"""
        <tr class="row-{row_cls}">
          <td>{badge}</td>
          <td><span class="method" style="background:{mcolor}22;color:{mcolor}">{method}</span></td>
          <td>{name_escaped}</td>
          <td class="url-cell">{url_escaped}</td>
          <td>{http_code}</td>
          <td>{ms}</td>
        </tr>"""

        # Detail card
        req = r.get("request", {})
        resp_body = json_to_html_pre(r.get("response_body"))
        req_headers = json_to_html_pre(req.get("headers"))
        req_body = json_to_html_pre(req.get("body"))
        error_block = ""
        if r.get("error"):
            err_esc = str(r["error"]).replace("&", "&amp;").replace("<", "&lt;")
            error_block = f"""
            <div class="error-block">
              <div class="block-title">❌ 错误信息</div>
              <pre>{err_esc}</pre>
            </div>"""

        resp_block = ""
        if r.get("response_body") is not None:
            resp_block = f"""
            <div class="resp-block">
              <div class="block-title">📥 响应体</div>
              <pre>{resp_body}</pre>
            </div>"""

        detail_html += f"""
        <div class="detail-card" id="detail-{i}">
          <div class="detail-header">
            <span class="method" style="background:{mcolor}22;color:{mcolor}">{method}</span>
            <span class="detail-name">{name_escaped}</span>
            {badge}
          </div>
          <div class="detail-url">{url_escaped}</div>
          <div class="detail-body">
            <div class="req-block">
              <div class="block-title">📤 请求 Headers</div>
              <pre>{req_headers}</pre>
            </div>
            <div class="req-block">
              <div class="block-title">📤 请求 Body</div>
              <pre>{req_body}</pre>
            </div>
            {resp_block}
            {error_block}
          </div>
        </div>"""

    # Diagnosis
    diagnoses = get_diagnosis(results)
    diag_html = ""
    for dtitle, points in diagnoses:
        pts = "".join(f"<li>{p}</li>" for p in points)
        diag_html += f"""
        <div class="diag-card">
          <div class="diag-title">⚠️ {dtitle}</div>
          <ul>{pts}</ul>
        </div>"""

    if not diag_html:
        if success == total:
            diag_html = '<div class="diag-card ok"><div class="diag-title">🎉 全部接口测试通过！</div></div>'
        else:
            diag_html = '<p style="color:#888;font-size:13px">暂无更多诊断信息。</p>'

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f0f2f5;color:#333}}
.header{{background:linear-gradient(135deg,#1a1a2e,#0f3460);color:#fff;padding:30px 40px}}
.header h1{{font-size:22px;font-weight:600;margin-bottom:5px}}
.header .sub{{font-size:12px;opacity:.65}}
.container{{max-width:1000px;margin:28px auto;padding:0 20px}}
.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:24px}}
.card{{background:#fff;border-radius:10px;padding:18px 12px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.07)}}
.card .val{{font-size:30px;font-weight:700;line-height:1.2}}
.card .lbl{{font-size:11px;color:#888;margin-top:4px}}
.card.total .val{{color:#1677ff}}.card.success .val{{color:#52c41a}}
.card.http-err .val{{color:#fa8c16}}.card.conn-err .val{{color:#ff4d4f}}
.card.pass .val{{color:#722ed1}}
.section{{background:#fff;border-radius:10px;padding:22px;box-shadow:0 2px 8px rgba(0,0,0,.07);margin-bottom:18px}}
.section h2{{font-size:14px;font-weight:600;color:#1a1a2e;border-left:3px solid #1677ff;padding-left:9px;margin-bottom:16px}}
.time-row{{display:flex;gap:24px;font-size:13px;color:#555}}
.time-row span b{{color:#333}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#f5f5f5;text-align:left;padding:10px 12px;font-weight:600;color:#555}}
td{{padding:11px 12px;border-bottom:1px solid #f0f0f0;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
.url-cell{{font-size:11px;color:#1677ff;word-break:break-all}}
.badge{{display:inline-block;padding:2px 9px;border-radius:4px;font-size:11px;font-weight:600}}
.badge.success{{background:#f6ffed;color:#52c41a;border:1px solid #b7eb8f}}
.badge.http-error{{background:#fff7e6;color:#fa8c16;border:1px solid #ffd591}}
.badge.error{{background:#fff1f0;color:#ff4d4f;border:1px solid #ffa39e}}
.method{{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:700}}
.detail-card{{border:1px solid #e8e8e8;border-radius:8px;margin-bottom:14px;overflow:hidden}}
.detail-header{{background:#fafafa;padding:12px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #f0f0f0}}
.detail-name{{font-weight:600;font-size:13px;flex:1}}
.detail-url{{padding:6px 16px;font-size:11px;color:#1677ff;background:#f0f7ff;border-bottom:1px solid #e8e8e8}}
.detail-body{{padding:14px 16px;display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.req-block,.resp-block,.error-block{{background:#f9f9f9;border:1px solid #e8e8e8;border-radius:6px;padding:10px 12px}}
.error-block{{background:#fff1f0;border-color:#ffa39e;grid-column:1/-1}}
.resp-block{{grid-column:1/-1}}
.block-title{{font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px}}
pre{{font-size:11px;color:#333;white-space:pre-wrap;word-break:break-all;line-height:1.7;max-height:300px;overflow-y:auto}}
.diag-card{{background:#fffbe6;border:1px solid #ffe58f;border-radius:8px;padding:14px 18px;margin-bottom:12px}}
.diag-card.ok{{background:#f6ffed;border-color:#b7eb8f}}
.diag-title{{font-size:13px;font-weight:600;color:#d46b08;margin-bottom:10px}}
.diag-card.ok .diag-title{{color:#52c41a}}
.diag-card ul{{padding-left:18px}}
.diag-card li{{font-size:13px;color:#595959;margin-bottom:5px;line-height:1.6}}
footer{{text-align:center;font-size:11px;color:#bbb;padding:20px 0 28px}}
@media(max-width:600px){{
  .cards{{grid-template-columns:repeat(3,1fr)}}
  .detail-body{{grid-template-columns:1fr}}
}}
</style>
</head>
<body>
<div class="header">
  <h1>🔍 {title}</h1>
  <div class="sub">生成时间：{generated_at}</div>
</div>
<div class="container">
  <div class="cards">
    <div class="card total"><div class="val">{total}</div><div class="lbl">总接口数</div></div>
    <div class="card success"><div class="val">{success}</div><div class="lbl">✅ 成功</div></div>
    <div class="card http-err"><div class="val">{http_err}</div><div class="lbl">⚠️ HTTP 错误</div></div>
    <div class="card conn-err"><div class="val">{conn_err}</div><div class="lbl">❌ 连接错误</div></div>
    <div class="card pass"><div class="val">{pass_rate}</div><div class="lbl">通过率</div></div>
  </div>
  <div class="section">
    <h2>执行时间</h2>
    <div class="time-row">
      <span>开始：<b>{start_t}</b></span>
      <span>结束：<b>{end_t}</b></span>
    </div>
  </div>
  <div class="section">
    <h2>测试概览</h2>
    <table>
      <thead><tr><th>状态</th><th>方法</th><th>接口名称</th><th>URL</th><th>HTTP</th><th>耗时</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <div class="section">
    <h2>请求 / 响应详情</h2>
    {detail_html}
  </div>
  <div class="section">
    <h2>🔎 故障诊断</h2>
    {diag_html}
  </div>
</div>
<footer>Apifox API Tester · 自动生成于 {generated_at}</footer>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate HTML report from api_test_report.json")
    parser.add_argument("--input", required=True, help="Path to api_test_report.json")
    parser.add_argument("--output", default="api_test_report.html", help="Output HTML file path")
    parser.add_argument("--title", default="API 测试报告", help="Report title")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        report = json.load(f)

    html = build_html(report, args.title)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    s = report["summary"]
    print(f"Report generated: {args.output}")
    print(f"  Total: {s['total_interfaces']}  |  Success: {s['success']}  |  Pass Rate: {s['pass_rate']}")


if __name__ == "__main__":
    main()
