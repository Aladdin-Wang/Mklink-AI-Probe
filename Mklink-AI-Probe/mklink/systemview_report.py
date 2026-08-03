"""
SEGGER SystemView 分析可视化报告生成器。

把一次 SystemView 采集的解码事件 + 分析报告渲染成一个**自包含 HTML** 文件
（内联 CSS，无外部依赖，浏览器直接打开），包含：
  * 概要卡片（事件数 / 切换 / 秒率 / 空闲率 / ISR 占用）
  * 异常提示横幅
  * 每任务 CPU% 条形图（带名）
  * 任务明细表（切换 / 均片 / 最长片）
  * ISR 统计
  * 任务切换甘特时间轴（按任务泳道 × 着色执行区间）

供 CLI ``systemview-report`` / MCP 调用，产出可分享、可存档的 RTOS 运行态报告。
"""

from __future__ import annotations

import html
from typing import Any


_PALETTE = [
    "#5b8cff", "#21c7a8", "#f5a623", "#e056fd", "#ff7675", "#fdcb6e",
    "#00cec9", "#a29bfe", "#55efc4", "#fab1a0", "#74b9ff", "#fd79a8",
]


def _filter_continuous(intervals: list[dict]) -> list[dict]:
    """缓冲溢出丢包会在时间轴上留下巨大假缺口（abs_time 跳变），把真实活动压到
    一小撮。检测最大 gap，若是离群（>> 中位区间时长）则在最密连续段里取数据。"""
    if len(intervals) < 8:
        return intervals
    gaps = [(intervals[i + 1]["start"] - intervals[i]["end"], i) for i in range(len(intervals) - 1)]
    max_gap, idx = max(gaps, key=lambda g: g[0])
    durs = sorted(it["end"] - it["start"] for it in intervals)
    med = durs[len(durs) // 2] or 1.0
    if max_gap <= med * 200:
        return intervals  # 无离群缺口
    left, right = intervals[:idx + 1], intervals[idx + 1:]
    cand = left if len(left) >= len(right) else right
    return _filter_continuous(cand)  # 递归处理多个缺口


def _t(e: dict) -> float:
    if isinstance(e.get("t_us"), (int, float)):
        return float(e["t_us"])
    return float(e.get("t_ticks") or 0)


def compute_intervals(events: list[dict]) -> list[dict]:
    """从事件流算出任务执行区间 [{tid, name, start, end}]。

    key 用 ``tid``（与 svTimeline.js 的 SvTimeline.setData 一致；Vue 侧也产出 tid）。
    """
    pending: dict[int, float] = {}
    names: dict[int, str] = {}
    intervals: list[dict] = []
    for e in events:
        k = e.get("kind")
        t = _t(e)
        if k == "task_start_exec" and isinstance(e.get("task_id"), int):
            pending[e["task_id"]] = t
            if e.get("task_name"):
                names[e["task_id"]] = e["task_name"]
        elif k == "task_stop_exec" and isinstance(e.get("task_id"), int):
            st = pending.pop(e["task_id"], None)
            if st is not None and t >= st:
                intervals.append({
                    "tid": e["task_id"],
                    "name": names.get(e["task_id"], f"0x{e['task_id']:X}"),
                    "start": st, "end": t,
                })
    return intervals


def generate_html_report(
    report: dict,
    events: list[dict],
    meta: dict | None = None,
    title: str = "SystemView RTOS 运行态报告",
) -> str:
    """生成自包含 HTML 报告字符串。"""
    meta = meta or {}
    s = report.get("summary", {})
    tasks = report.get("tasks", []) or []
    isr = report.get("isr", {}) or {}
    anomalies = report.get("anomalies", []) or []
    unit = s.get("unit", "us")
    usuf = "µs" if unit == "us" else "tk"

    # 甘特区间（交互式 canvas 渲染）：先剔除缓冲丢包造成的假时间缺口，再取最近 6000
    intervals = _filter_continuous(compute_intervals(events))[-6000:]
    import json
    from pathlib import Path
    sv_js_path = Path(__file__).parent.parent / "gui" / "src" / "lib" / "svTimeline.js"
    sv_js = sv_js_path.read_text(encoding="utf-8") if sv_js_path.exists() else ""
    # 内联进经典 <script> 时去掉 ES module 的 export 关键字（否则 SyntaxError）。
    # Vue 侧以 ESM import 使用，保留 export；这里只在报告里剥离。
    sv_js = sv_js.replace("export class SvTimeline", "class SvTimeline")
    # <script> 内容是字面文本（HTML 实体不被解码），故不能用 html.escape；
    # 只把 < 转义成 < 防 </script> 注入，JSON.parse 能正常还原。
    intervals_json = json.dumps({"intervals": intervals, "unit": unit}).replace("<", "\\u003c")

    # 概要卡片（空闲率/ISR 现为比率，与单位无关，始终显示）
    obs = s.get("observed_us") or s.get("observed_ticks")
    cards = [
        ("事件", str(s.get("event_count", 0))),
        ("任务", str(s.get("task_count", 0))),
        ("切换", str(s.get("switch_count", 0))),
        ("空闲率", f"{s.get('idle_pct', 0)}%"),
        ("ISR 占用", f"{s.get('isr_cpu_pct', 0)}%"),
    ]
    if unit == "us":
        cards.append(("切换/秒", str(s.get("switches_per_sec"))))
    cards_html = "".join(
        f'<div class="card"><div class="card-v">{html.escape(v)}</div>'
        f'<div class="card-k">{html.escape(k)}</div></div>'
        for k, v in cards
    )

    # 异常横幅
    anom_html = ""
    if anomalies:
        items = "".join(
            f'<li class="anom a-{a["severity"]}"><span class="anom-tag">'
            f'{"⛔" if a["severity"]=="high" else "⚠"}</span>'
            f'<b>[{html.escape(a["kind"])}]</b> {html.escape(a["detail"])}</li>'
            for a in anomalies
        )
        anom_html = f'<div class="anom-box"><h3>异常 / 风险</h3><ul>{items}</ul></div>'

    # CPU 条
    bars_html = ""
    for t in tasks:
        name = html.escape(t.get("name") or t.get("id_hex") or "")
        pct = t.get("cpu_pct", 0)
        color = _PALETTE[tasks.index(t) % len(_PALETTE)] if False else _PALETTE[hash(t.get("id", 0)) % len(_PALETTE)]
        bars_html += (
            f'<div class="cpu-row"><span class="cpu-name" title="{name}">{name}</span>'
            f'<div class="cpu-bg"><div class="cpu-bar" style="width:{max(0.2,pct):.2f}%;background:{color}"></div></div>'
            f'<span class="cpu-pct">{pct}%</span></div>'
        )

    # 任务表
    rows = "".join(
        f"<tr><td>{html.escape(t.get('name') or t.get('id_hex',''))}</td>"
        f"<td>{t.get('cpu_pct')}</td><td>{t.get('run_us')}</td>"
        f"<td>{t.get('switches')}</td><td>{t.get('avg_slice_us')}</td>"
        f"<td>{t.get('max_slice_us')}</td></tr>"
        for t in tasks
    )

    isr_html = ""
    if isr.get("count"):
        isr_html = (
            '<div class="isr-box"><h3>中断 (ISR)</h3>'
            f'<div>次数 <b>{isr["count"]}</b> · 总时长 <b>{isr["total_us"]}{usuf}</b> · '
            f'占用 <b>{isr.get("cpu_pct")}%</b> · 最长 <b>{isr["max_duration_us"]}{usuf}</b>'
            f'{" <i>(长 ISR 提示中断延迟风险)</i>" if isr.get("max_duration_us",0)>100 else ""}</div></div>'
        )

    obs_txt = f"{obs:,.1f} {usuf}" if obs else "—"
    meta_txt = " · ".join(
        f"{k}={v}" for k, v in meta.items()
        if k in ("cpu_freq", "synced", "dropped") and v not in (None, "", 0)
    )

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
*{{box-sizing:border-box}}
body{{background:#f5f4ed;color:#141413;font-family:-apple-system,Segoe UI,Roboto,'Microsoft YaHei',sans-serif;margin:0;padding:24px;line-height:1.5}}
h1{{color:#141413;font-size:22px;margin:0 0 4px}}
h3{{color:#5e5d59;font-size:13px;margin:14px 0 8px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}}
.meta{{color:#87867f;font-size:12px;margin-bottom:18px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px}}
.card{{background:#ffffff;border:1px solid #e8e6dc;border-radius:8px;padding:12px 18px;min-width:90px;text-align:center}}
.card-v{{font-size:22px;font-weight:700;color:#c96442}}
.card-k{{font-size:11px;color:#5e5d59;margin-top:2px}}
.anom-box{{background:#f5f0e1;border:1px solid #b58a1b;border-radius:8px;padding:12px 16px;margin:14px 0}}
.anom{{list-style:none;padding:4px 0;font-size:13px}}
.anom-tag{{margin-right:6px}}
.a-high{{color:#b53333}}.a-warn{{color:#b58a1b}}
.cpu-row{{display:flex;align-items:center;gap:10px;margin:3px 0;font-size:13px}}
.cpu-name{{width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:right;color:#141413}}
.cpu-bg{{flex:1;height:16px;background:#2a2a2a;border-radius:8px;overflow:hidden}}
.cpu-bar{{height:100%;border-radius:8px;transition:width .3s}}
.cpu-pct{{width:54px;text-align:right;font-variant-numeric:tabular-nums;color:#141413}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}
th,td{{padding:6px 10px;text-align:left;border-bottom:1px solid #e8e6dc}}
th{{color:#5e5d59;font-weight:600;font-size:12px}}td{{color:#141413}}
.tl-sub{{color:#87867f;font-size:11px;font-weight:400;text-transform:none;letter-spacing:0;margin-left:6px}}
.tl-top{{display:flex;align-items:center;gap:10px;margin:6px 0;flex-wrap:wrap}}
.tl-btn{{background:#ffffff;border:1px solid #e8e6dc;color:#141413;border-radius:6px;padding:4px 12px;cursor:pointer;font-size:12px}}
.tl-btn:hover{{border-color:#c96442;color:#c96442}}
.tl-legend{{display:flex;gap:6px;flex-wrap:wrap}}
.sv-lg{{display:inline-flex;align-items:center;gap:4px;background:#ffffff;border:1px solid #e8e6dc;border-radius:12px;padding:2px 9px;font-size:11px;color:#141413;cursor:pointer;user-select:none}}
.sv-lg i{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.sv-lg em{{color:#5e5d59;font-style:normal;font-variant-numeric:tabular-nums}}
.sv-lg-off{{opacity:.4;text-decoration:line-through}}
.tl-canvas-wrap{{position:relative;background:#0d1117;border:1px solid #e8e6dc;border-radius:8px;margin-top:6px;overflow:hidden}}
.tl-canvas-wrap canvas{{display:block;width:100%;cursor:crosshair}}
.tl-tip{{position:fixed;display:none;background:#ffffff;border:1px solid #e8e6dc;border-radius:6px;padding:6px 10px;font-size:11px;color:#141413;pointer-events:none;z-index:99;box-shadow:0 4px 12px rgba(0,0,0,.15);font-family:monospace;white-space:nowrap}}
.isr-box{{background:#ffffff;border:1px solid #e8e6dc;border-radius:8px;padding:10px 14px;margin-top:6px;font-size:13px;color:#141413}}
.empty{{color:#87867f;font-style:italic;padding:8px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="meta">观测时长 {obs_txt}{(" · "+html.escape(meta_txt)) if meta_txt else ""}</div>
<div class="cards">{cards_html}</div>
{anom_html}
<div class="grid">
<div><h3>任务 CPU 占用</h3><div>{bars_html or '<div class="empty">无任务执行区间</div>'}</div>{isr_html}</div>
<div><h3>任务明细</h3><table><thead><tr><th>任务</th><th>CPU%</th><th>运行{usuf}</th><th>切换</th><th>均片{usuf}</th><th>最长{usuf}</th></tr></thead><tbody>{rows}</tbody></table></div>
</div>
<h3>任务切换时间轴<span class="tl-sub">滚轮缩放 · 拖拽平移 · hover 详情 · 点图例隐藏任务</span></h3>
<div class="tl-top">
  <button class="tl-btn" id="sv-reset">⟲ 缩放全览</button>
  <div class="tl-legend" id="sv-legend"></div>
</div>
<div class="tl-canvas-wrap"><canvas id="sv-canvas"></canvas></div>
<div class="tl-tip" id="sv-tip"></div>
<script id="sv-data" type="application/json">{intervals_json}</script>
<script>{sv_js}
(function(){{try{{var d=JSON.parse(document.getElementById('sv-data').textContent);
new SvTimeline({{canvas:document.getElementById('sv-canvas'),tooltip:document.getElementById('sv-tip'),
legend:document.getElementById('sv-legend'),
resetBtn:document.getElementById('sv-reset')}},{{intervals:d.intervals,unit:d.unit}});}}catch(e){{console.error(e);}}}})();
</script>
</body></html>"""

