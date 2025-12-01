import streamlit as st
import pandas as pd
import os
import shutil
import tempfile
import zipfile
import io
import time


try:
    from getbat import StressCompiler, load_project_config, parse_tasks_from_sheet, DEFAULT_CONFIG
    from analyze_log import StressLogAnalyzer
except ImportError:
    st.error("❌ 缺少依赖文件！请确保 `getbat.py` 和 `analyze_log.py` 与本脚本在同一目录下。")
    st.stop()

# ==========================================
# 页面配置与样式
# ==========================================
st.set_page_config(
    page_title="压测自助平台",
    page_icon="🐕",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义 CSS 美化
st.markdown("""
<style>
    .main-header {font-size: 2.5rem; color: #4F8BF9; font-weight: 700;}
    .sub-header {font-size: 1.5rem; color: #333; margin-top: 20px;}
    .info-box {background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin-bottom: 20px;}
    .stButton>button {width: 100%; border-radius: 5px; height: 3em; font-weight: bold;}
    /* 调整 Tab 样式 */
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
        font-size: 1.2rem;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# 辅助函数
# ==========================================

def get_readme_content():
    """读取同目录下的 README.md，如果不存在则显示默认提示"""
    readme_path = os.path.join(os.path.dirname(__file__), "README.md")
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        return """
        ### 👋 欢迎使用 Dognoise 压测平台

        **请管理员在同级目录下创建 `README.md` 以展示详细的使用说明。**
        """


def generate_template_excel():
    """在内存中生成一个标准的 Excel 模板文件"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # 1. Config Sheet
        df_config_kv = pd.DataFrame([
            ["target_pkg", "cn.net.cloudthink.smartmirror"],
            ["start_activity", ".MainActivity"],
            ["duration_value", "3"],
            ["duration_unit", "day (支持 day, hour, min, sec,实际使用的时候不要带其他文字！)"],
        ], columns=["配置项 (Key)", "配置值 (Value)"])

        df_config_plan = pd.DataFrame([
            ["Login_Test", 1],
            ["Video_Loop", 100],
            ["Settings_Check", 50],
        ], columns=["执行顺序 (Sheet Name)", "本轮循环 (Loop)"])

        # 写入 Config，分两块区域
        df_config_kv.to_excel(writer, sheet_name='Config', startcol=0, index=False)
        df_config_plan.to_excel(writer, sheet_name='Config', startcol=3, index=False)

        # 添加说明注释
        worksheet = writer.sheets['Config']
        worksheet.write(0, 6, "执行顺序，执行顺序是指每个表跑几遍，务必保证Sheet Name和编写的脚本对的上，同一表格可以重复使用")

        # 2. 示例 Sheet: Login_Test
        df_action = pd.DataFrame([
            [1, "WAIT", 2, "", "", "", 1, "等待启动"],
            [2, "CLICK", 500, 1000, "", "", 1, "点击按钮"],
            [3, "SWIPE", 500, 1500, 500, 500, 1, "上滑一下"],
        ], columns=["序号（也可以不填这一列）", "指令 (Action)", "参数1", "参数2", "参数3", "参数4", "重复", "备注"])
        df_action.to_excel(writer, sheet_name='Login_Test', index=False)

    return output.getvalue()


# ==========================================
# 主界面逻辑
# ==========================================

st.markdown('<div class="main-header">压测自助平台</div>', unsafe_allow_html=True)
st.markdown("---")

# 侧边栏：放置说明书
with st.sidebar:
    st.header("📘 使用指南")
    # st.info("")
    readme_content = get_readme_content()
    st.markdown(readme_content)

# 主 Tab 区域
tab1, tab2 = st.tabs(["🛠️ **第一步：生成压测脚本**", "📊 **第二步：分析测试日志**"])

# --- Tab 1: 脚本生成 ---
with tab1:
    col_left, col_right = st.columns([1, 1])

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

        if uploaded_excel:
            try:
                # 临时保存上传的文件
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
                    tmp_file.write(uploaded_excel.getvalue())
                    tmp_excel_path = tmp_file.name

                # 解析配置
                with st.spinner("正在解析 Excel..."):
                    final_config, seq_plan = load_project_config(tmp_excel_path)

                    # 容错处理
                    if not seq_plan:
                        xl = pd.ExcelFile(tmp_excel_path)
                        for s in xl.sheet_names:
                            if s.lower().startswith("round") or s.lower() == "main":
                                seq_plan.append({"name": s, "loop": 1})

                if not seq_plan:
                    st.error("❌ 格式错误：在 Config Sheet 中未找到执行计划，也未扫描到 Main Sheet。")
                else:
                    # 显示配置摘要
                    with st.expander("✅ 解析成功！点击查看详细配置", expanded=True):
                        st.write(f"**目标包名**: `{final_config['target_pkg']}`")
                        st.write(f"**测试时长**: `{final_config['duration_sec']} 秒`")

                        # 解析详细步骤用于预览
                        preview_list = []
                        full_execution_plan = []
                        global_seq = 0

                        for stage in seq_plan:
                            s_name = stage['name']
                            tasks, new_seq = parse_tasks_from_sheet(tmp_excel_path, s_name, global_seq)
                            global_seq = new_seq
                            if tasks:
                                full_execution_plan.append({"name": s_name, "loop": stage['loop'], "tasks": tasks})
                                preview_list.append({
                                    "阶段名称": s_name,
                                    "循环次数": stage['loop'],
                                    "动作数量": len(tasks)
                                })

                        st.table(pd.DataFrame(preview_list))

                    # 编译按钮
                    if st.button("🚀 立即编译并打包下载"):
                        compiler = StressCompiler(
                            target_pkg=final_config['target_pkg'],
                            duration=final_config['duration_sec'],
                            start_uri=final_config['start_activity']
                        )
                        shell_code = compiler.compile_sequence(full_execution_plan)

                        # 生成 BAT 内容
                        bat_content = f"""@echo off
                        title Dognoise Stress Launcher
                        color 0A
                        echo.
                        echo [Dognoise] 正在初始化环境...
                        adb wait-for-device
                        adb root
                        adb remount
                        echo.
                        echo [1/3] 正在清理旧的压测进程 (防止冲突)...
                        adb shell "pkill -f stress_core.sh"
                        adb shell "killall stress_core.sh >/dev/null 2>&1"
                        adb shell "rm -f /data/local/tmp/dognoise.lock"
                        adb logcat -c && adb shell "rm -rf /sdcard/dognoise_stress/*"
                        echo.
                        echo [2/3] 推送新脚本...
                        adb push stress_core.sh /data/local/tmp/stress_core.sh
                        adb shell chmod 777 /data/local/tmp/stress_core.sh
                        echo.
                        echo [3/3] 启动压测任务...
                        adb shell "nohup sh /data/local/tmp/stress_core.sh > /dev/null 2>&1 &"
                        echo 启动成功！日志路径: /sdcard/dognoise_stress/event.log
                        pause
                        """

                        # 🛠️【关键修复】强制转换换行符为 Windows 格式 (\r\n)
                        bat_content = bat_content.replace('\n', '\r\n')
                        # 打包 ZIP
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w") as zf:
                            zf.writestr("stress_core.sh", shell_code)
                            zf.writestr("一键开始压测.bat", bat_content.encode("gbk"))

                        st.balloons()
                        st.success("编译完成！请下载压缩包，解压后双击 BAT 即可开始测试。")
                        st.download_button(
                            label="⬇️ 下载脚本包 (Dognoise_Script.zip)",
                            data=zip_buffer.getvalue(),
                            file_name="Dognoise_Script.zip",
                            mime="application/zip",
                            type="primary"
                        )

                os.unlink(tmp_excel_path)
            except Exception as e:
                st.error(f"解析失败: {e}")
        else:
            st.info("👈 请先在左侧上传 Excel 文件")

# --- Tab 2: 日志分析 ---
with tab2:
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

                # 关键指标展示
                st.markdown("### 📊 测试概览")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("总执行动作", f"{d['total_actions']} Steps")

                mem_vals = [m[1] for m in d['mem_records']]
                max_mem = max(mem_vals) if mem_vals else 0
                c2.metric("内存峰值", f"{max_mem} MB")

                c3.metric("警告 (Warn)", d['warnings'])
                c4.metric("严重错误 (Error)", sum(d['errors'].values()), delta_color="inverse")

                # 图表区域
                col_chart1, col_chart2 = st.columns([2, 1])

                with col_chart1:
                    st.markdown("#### 📉 内存趋势图")
                    if d['mem_records']:
                        mem_df = pd.DataFrame(d['mem_records'], columns=["Time", "Memory(MB)"])
                        st.line_chart(mem_df.set_index("Time"))
                    else:
                        st.caption("暂无内存数据")

                with col_chart2:
                    st.markdown("#### 🚫 异常分布")
                    if d['errors']:
                        err_df = pd.DataFrame(list(d['errors'].items()), columns=["类型", "次数"])
                        st.dataframe(err_df, hide_index=True, use_container_width=True)
                    else:
                        st.success("无异常")

                # HTML 报告下载
                report_path = os.path.join(tempfile.gettempdir(), "stress_report.html")
                analyzer.generate_html(report_path)
                with open(report_path, "rb") as f:
                    st.download_button(
                        label="📄 下载完整 HTML 报告 (含交互图表)",
                        data=f,
                        file_name=f"Report_{d['target_pkg']}.html",
                        mime="text/html"
                    )
            else:
                st.error("日志解析失败，请确认文件格式正确。")
        os.unlink(tmp_log_path)