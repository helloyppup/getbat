import streamlit as st
import os
import sys
import tempfile
import pandas as pd

from src.models import ProjectModel
# from web_app import tmp_excel_path

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

try:
    # 1. 导入业务核心 (Model & Logic)
    from src.excel_loader import ExcelLoader
    from src.compiler import StressCompiler
    from src.launcher_generator import LauncherGenerator

    # 2. 导入 UI 辅助工具 (View & Helper)
    from utils.styles import setup_page, apply_global_styles
    from utils.ui_helper import (
        generate_template_excel,
        get_readme_content,
        package_files_to_zip,
        format_plans_for_ui, load_and_parse_project,
        get_bat_content
)

    # 3. 尝试导入日志分析模块 (可选)
    try:
        from analyze_log import StressLogAnalyzer

        HAS_ANALYZER = True
    except ImportError:
        HAS_ANALYZER = False

except ImportError as e:
    st.error(f"关键模块缺失！请检查目录结构。\n错误详情: {e}")
    st.stop()


# 页面初始化
setup_page()
apply_global_styles()

# 侧边栏
with st.sidebar:
    st.header("📘 使用指南")
    # 调用 ui_helper.py 获取文案
    st.markdown(get_readme_content())


st.markdown('<div class="main-header">Dognoise 压测自助平台</div>', unsafe_allow_html=True)
st.markdown("---")

tab1, tab2 = st.tabs(["🛠️ **脚本生成**", "📊 **日志分析**"])

with tab1:
    col_left, col_right = st.columns([1, 1.2])

    # === 左栏：准备工作 ===
    with col_left:
        st.markdown('<div class="sub-header">1. 获取模板</div>', unsafe_allow_html=True)
        st.write("如果你还没有测试计划，请先下载标准模板：")

        template_data = generate_template_excel()
        st.download_button(
            label="📥 下载标准 Excel 模板 (test_plan_template.xlsx)",
            data=template_data,
            file_name="test_plan_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.markdown('<div class="sub-header">2. 上传计划</div>', unsafe_allow_html=True)
        uploaded_excel = st.file_uploader("上传填写好的 test plan.xlsx", type=["xlsx"],
                                          help="请确保包含 Config Sheet 和对应的任务 Sheet")

        st.markdown('<div class="sub-header">3. 预览与编译</div>', unsafe_allow_html=True)

        if uploaded_excel :
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
                    tmp_file.write(uploaded_excel.getvalue())
                    tmp_excel_path = tmp_file.name

                with st.spinner("正在解析 Excel..."):
                    project = load_and_parse_project(tmp_excel_path)


                if not project.plans:
                    st.error("❌ 格式错误：在 Config Sheet 中未找到执行计划，请检查 Excel 配置。")
                else:
                    with st.expander("✅ 解析成功！点击查看详细配置", expanded=True):
                        c_info1, c_info2 = st.columns(2)
                        c_info1.info(f"**目标包名**: `{project.config.target_pkg}`")
                        c_info2.info(f"**测试时长**: `{project.config.duration_sec}` 秒")

                        st.markdown("#### 📋 完整配置参数")
                        config_df,plan_df = format_plans_for_ui(project)
                        st.dataframe(config_df, use_container_width=True, hide_index=True)

                        st.markdown("---")
                        st.markdown("#### 🔄 执行计划预览")
                        st.dataframe(plan_df, use_container_width=True, hide_index=True)

                if st.button("🚀 立即编译并打包下载"):
                    compiler = StressCompiler(project)
                    sh_content = compiler.compile()
                    bat_start,bat_stop=get_bat_content("stress_core.sh")
                    zip_bytes = package_files_to_zip(sh_content, bat_start,bat_stop)
                    st.balloons()
                    st.success("🎉 编译完成！")

                    st.download_button(
                        label="⬇️ 下载工具包 (Dognoise_Tools.zip)",
                        data=zip_bytes,  # 直接把 helper 返回的 bytes 填在这里
                        file_name="Dognoise_Tools.zip",
                        mime="application/zip",
                        type="primary"
                    )

                os.unlink(tmp_excel_path)

            except Exception as e:
                st.error(f"❌ 发生错误: {e}")
                st.exception(e)
        else:
            st.info("请先在上传配置文件")


with tab2:
    if not HAS_ANALYZER:
        st.warning("⚠️ 日志分析模块未安装 (analyze_log.py)，功能已禁用。")
    else:
        st.markdown('<div class="sub-header">上传 event.log 生成报告</div>', unsafe_allow_html=True)
        uploaded_log = st.file_uploader("请上传压测产生的 event.log 文件", type=["log", "txt"])

        if uploaded_log:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as tmp_log:
                tmp_log.write(uploaded_log.getvalue())
                tmp_log_path = tmp_log.name

            if st.button("📈 开始分析", type="primary"):
                analyzer = StressLogAnalyzer(tmp_log_path)
                if analyzer.parse():
                    d = analyzer.data

                    # 1. 关键指标展示
                    st.markdown("### 📊 测试概览")

                    # [新增] 计算网络平均延迟
                    avg_ping = 0
                    valid_pings = [x[1] for x in d['net_records'] if x[1] < 1000]  # 排除超时(1000)
                    if valid_pings:
                        avg_ping = int(sum(valid_pings) / len(valid_pings))

                    c1, c2, c3, c4, c5 = st.columns(5)  # 改为5列
                    c1.metric("总执行动作", f"{d['total_actions']} Steps")

                    mem_vals = [m[1] for m in d['mem_records']]
                    max_mem = max(mem_vals) if mem_vals else 0
                    c2.metric("内存峰值", f"{max_mem} MB")

                    c3.metric("平均 Ping", f"{avg_ping} ms")
                    c4.metric("网络超时", f"{d['net_failures']} 次", delta_color="inverse")
                    c5.metric("严重错误", sum(d['errors'].values()), delta_color="inverse")

                    # 2. 图表区域
                    st.markdown("#### 📉 趋势分析")
                    tab_mem, tab_net, tab_cpu, tab_temp = st.tabs(["内存", "网络", "CPU", "温度"])

                    with tab_mem:
                        if d['mem_records']:
                            mem_df = pd.DataFrame(d['mem_records'], columns=["Time", "Memory(MB)"])
                            st.line_chart(mem_df.set_index("Time"))
                        else:
                            st.caption("暂无内存数据")

                    with tab_net:
                        if d['net_records']:
                            # [新增] 网络图表
                            net_df = pd.DataFrame(d['net_records'], columns=["Time", "Latency(ms)"])
                            st.line_chart(net_df.set_index("Time"))
                        else:
                            st.caption("暂无网络数据 (请确保脚本运行超过 1 分钟)")

                    with tab_cpu:
                        if d.get('cpu_records'):
                            cpu_df = pd.DataFrame(d['cpu_records'], columns=["Time", "CPU(%)"])
                            st.line_chart(cpu_df.set_index("Time"))
                            avg_cpu = sum([x[1] for x in d['cpu_records']]) / len(d['cpu_records'])
                            st.info(f"平均 CPU 占用: {avg_cpu:.1f}% (注: 多核可能超过100%)")
                        else:
                            st.caption("暂无 CPU 数据")

                    with tab_temp:
                        if d.get('temp_records'):
                            temp_df = pd.DataFrame(d['temp_records'], columns=["Time", "Temp(°C)"])
                            st.line_chart(temp_df.set_index("Time"))
                            max_temp = max([x[1] for x in d['temp_records']])
                            if max_temp > 80:
                                st.error(f"🔥 历史最高温: {max_temp}°C")
                            else:
                                st.success(f"🌡️ 历史最高温: {max_temp}°C (散热良好)")
                        else:
                            st.caption("暂无温度数据")

                    # 3. 异常分布
                    st.markdown("#### 🚫 异常分布")
                    if d['errors']:
                        err_df = pd.DataFrame(list(d['errors'].items()), columns=["类型", "次数"])
                        st.dataframe(err_df, hide_index=True, use_container_width=True)
                    else:
                        st.success("🎉 太棒了！日志中未发现严重错误。")

                    # 4. HTML 报告下载
                    report_path = os.path.join(tempfile.gettempdir(), "stress_report.html")
                    analyzer.generate_html(report_path)
                    with open(report_path, "rb") as f:
                        st.download_button(
                            label="📄 下载完整 HTML 报告 (含交互图表)",
                            data=f,
                            file_name=f"Report_{d.get('target_pkg', 'stress')}.html",
                            mime="text/html"
                        )
                else:
                    st.error("日志解析失败，请确认文件格式正确。")
            os.unlink(tmp_log_path)


