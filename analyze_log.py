import os
import re
import sys
import datetime
from collections import defaultdict


class StressLogAnalyzer:
    def __init__(self, log_path):
        self.log_path = log_path
        self.data = {
            "start_time": None,
            "end_time": None,
            "duration": "N/A",
            "target_pkg": "Unknown",
            "total_actions": 0,
            "mem_records": [],  # List of (time_str, mem_val)
            "errors": defaultdict(int),
            "warnings": 0,
            "snapshots": [],
            "error_timeline": []  # List of {time, type, msg}
        }

    def parse(self):
        if not os.path.exists(self.log_path):
            print(f"❌ 错误: 找不到日志文件 {self.log_path}")
            return False

        print(f"正在分析日志: {self.log_path} ...")

        # 正则表达式预编译
        re_start = re.compile(r"^=== Long-Term Stress Test Start: (.+) ===")
        re_target = re.compile(r"^Target: (.+)")
        re_end = re.compile(r"^=== End: (.+) ===")
        # [12:00:01] [Sheet][#1] ACTION
        re_action = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\] \[.+\]\[#\d+\] (.+)")
        # [STATUS] 12:00:02 | Mem:145MB
        re_mem = re.compile(r"^\[STATUS\]\s+(\d{2}:\d{2}:\d{2})\s+\|\s+Mem:(\d+)MB")
        # [WARN] ...
        re_warn = re.compile(r"^\s+\[WARN\]")
        # !!! [Date] [TYPE] Msg
        re_error = re.compile(r"^!!! \[(.+)\] \[([A-Z_]+)\] (.+)")
        # [SNAPSHOT] Type
        re_snap = re.compile(r"^\s+\[SNAPSHOT\] (.+)")

        with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line: continue

                # 1. 基础信息
                m_start = re_start.match(line)
                if m_start:
                    self.data["start_time"] = m_start.group(1)
                    continue

                m_target = re_target.match(line)
                if m_target:
                    self.data["target_pkg"] = m_target.group(1)
                    continue

                m_end = re_end.match(line)
                if m_end:
                    self.data["end_time"] = m_end.group(1)
                    continue

                # 2. 内存记录
                m_mem = re_mem.match(line)
                if m_mem:
                    t_str = m_mem.group(1)
                    mem_val = int(m_mem.group(2))
                    self.data["mem_records"].append((t_str, mem_val))
                    continue

                # 3. 动作计数
                if re_action.match(line):
                    self.data["total_actions"] += 1
                    continue

                # 4. 警告
                if re_warn.match(line):
                    self.data["warnings"] += 1
                    continue

                # 5. 严重错误 (Critical)
                m_err = re_error.match(line)
                if m_err:
                    err_time = m_err.group(1)
                    err_type = m_err.group(2)
                    err_msg = m_err.group(3)
                    self.data["errors"][err_type] += 1
                    self.data["error_timeline"].append({
                        "time": err_time,
                        "type": err_type,
                        "msg": err_msg
                    })
                    continue

                # 6. 截图记录
                m_snap = re_snap.match(line)
                if m_snap:
                    self.data["snapshots"].append(m_snap.group(1))

        self._calc_duration()
        return True

    def _calc_duration(self):
        # 简单计算时长，仅作为参考
        if self.data["start_time"] and self.data["end_time"]:
            try:
                # 尝试解析 date 格式 Mon Dec 1 ...
                # 这里简化处理，直接用字符串显示
                self.data["duration"] = "Calculated in Report"
            except:
                pass

    def print_summary(self):
        d = self.data
        print("\n" + "=" * 40)
        print("📊 [Dognoise] 压测报告摘要")
        print("=" * 40)
        print(f"目标应用 : {d['target_pkg']}")
        print(f"开始时间 : {d['start_time']}")
        print(f"结束时间 : {d['end_time']}")
        print(f"执行动作 : {d['total_actions']} Steps")
        print("-" * 40)

        mem_vals = [m[1] for m in d['mem_records']]
        if mem_vals:
            avg_mem = sum(mem_vals) / len(mem_vals)
            max_mem = max(mem_vals)
            print(f"内存峰值 : {max_mem} MB")
            print(f"内存均值 : {int(avg_mem)} MB")
        else:
            print("内存数据 : 无记录")

        print("-" * 40)
        print(f"⚠️ 警告 (Warn)  : {d['warnings']}")
        print(f"❌ 错误 (Error) : {sum(d['errors'].values())}")

        if d['errors']:
            for k, v in d['errors'].items():
                print(f"   - {k:<12} : {v}")

        print("=" * 40)
        print(f"截图文件数 : {len(d['snapshots'])}")

    def generate_html(self, output_file="stress_report.html"):
        d = self.data

        # 准备图表数据
        times = [f"'{x[0]}'" for x in d['mem_records']]
        mems = [str(x[1]) for x in d['mem_records']]

        err_labels = list(d['errors'].keys())
        err_values = list(d['errors'].values())

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Dognoise Stress Report</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        body {{ font-family: 'Segoe UI', sans-serif; background: #f4f6f9; margin: 0; padding: 20px; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: #fff; padding: 30px; box-shadow: 0 0 15px rgba(0,0,0,0.1); border-radius: 8px; }}
        h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: #f8f9fa; padding: 15px; border-radius: 6px; text-align: center; border: 1px solid #e9ecef; }}
        .card h3 {{ margin: 0; color: #6c757d; font-size: 14px; }}
        .card p {{ margin: 10px 0 0; font-size: 24px; font-weight: bold; color: #333; }}
        .card.danger p {{ color: #dc3545; }}
        .chart-box {{ height: 400px; margin-bottom: 40px; }}
        .error-list {{ background: #fff3cd; padding: 15px; border-radius: 5px; border: 1px solid #ffeeba; }}
        .error-item {{ border-bottom: 1px solid #fae39d; padding: 8px 0; color: #856404; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Dognoise 压测报告</h1>
        <p>Target: <strong>{d['target_pkg']}</strong> | Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

        <div class="summary-grid">
            <div class="card"><h3>Total Actions</h3><p>{d['total_actions']}</p></div>
            <div class="card"><h3>Peak Memory</h3><p>{max([m[1] for m in d['mem_records']]) if d['mem_records'] else 0} MB</p></div>
            <div class="card"><h3>Warnings</h3><p style="color:#ffc107">{d['warnings']}</p></div>
            <div class="card danger"><h3>Total Errors</h3><p>{sum(d['errors'].values())}</p></div>
        </div>

        <h3>📈 内存趋势 (Memory Usage)</h3>
        <div id="memChart" class="chart-box"></div>

        <h3>🚫 异常分布 (Error Distribution)</h3>
        <div class="summary-grid" style="grid-template-columns: 1fr 1fr;">
            <div id="pieChart" style="height: 300px;"></div>
            <div class="error-list">
                <strong>最近异常记录 (Top 10):</strong>
                {"".join([f'<div class="error-item">[{e["time"]}] <strong>{e["type"]}</strong>: {e["msg"]}</div>' for e in d["error_timeline"][-10:]])}
            </div>
        </div>
    </div>

    <script type="text/javascript">
        // 内存曲线
        var memChart = echarts.init(document.getElementById('memChart'));
        var memOption = {{
            tooltip: {{ trigger: 'axis' }},
            xAxis: {{ type: 'category', data: [{",".join(times)}] }},
            yAxis: {{ type: 'value', name: 'MB', scale: true }},
            series: [{{
                data: [{",".join(mems)}],
                type: 'line',
                smooth: true,
                areaStyle: {{ opacity: 0.2 }},
                itemStyle: {{ color: '#007bff' }},
                markPoint: {{
                    data: [ {{ type: 'max', name: 'Max' }}, {{ type: 'min', name: 'Min' }} ]
                }}
            }}]
        }};
        memChart.setOption(memOption);

        // 饼图
        var pieChart = echarts.init(document.getElementById('pieChart'));
        var pieOption = {{
            tooltip: {{ trigger: 'item' }},
            series: [{{
                name: 'Error Type',
                type: 'pie',
                radius: ['40%', '70%'],
                data: [
                    {",".join([f"{{value: {v}, name: '{k}'}}" for k, v in d['errors'].items()])}
                ],
                emphasis: {{
                    itemStyle: {{ shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' }}
                }}
            }}]
        }};
        pieChart.setOption(pieOption);
    </script>
</body>
</html>
        """

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"\n✅ HTML 报告已生成: {os.path.abspath(output_file)}")


if __name__ == "__main__":
    # 默认读取当前目录下的 dist_stress/event.log，或者是同级目录的 event.log
    possible_paths = [
        os.path.join("dist_stress", "event.log"),
        "event.log"
    ]

    log_file = None
    for p in possible_paths:
        if os.path.exists(p):
            log_file = p
            break

    if len(sys.argv) > 1:
        log_file = sys.argv[1]

    if not log_file:
        print("未找到 event.log。请将脚本放在日志同级目录，或使用: python analyze_log.py <path_to_log>")
    else:
        analyzer = StressLogAnalyzer(log_file)
        if analyzer.parse():
            analyzer.print_summary()
            analyzer.generate_html()