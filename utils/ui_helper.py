# utils/ui_helper.py
import os

import pandas as pd
import io
import zipfile
from src.launcher_generator import LauncherGenerator
import sys

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
            ["ping_target","www.baidu.com"],
            ["log_whitelist", "BlueToothAdapter:D WifiService:D"],
            ["feishu_webhook","AAAAAA"]
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
        ], columns=["序号（也可以不填这一列）", "指令 (Action)", "p1", "p2", "p3", "p4", "重复", "备注"])
        df_action.to_excel(writer, sheet_name='Login_Test', index=False)

    return output.getvalue()

def package_files_to_zip(shell_content, bat_start, bat_stop, sh_name="stress_core.sh"):
    """打包 ZIP 的逻辑封装起来"""
    # 写入虚拟内存
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        # 写入 Shell 脚本
        zf.writestr(sh_name, shell_content.replace('\r\n', '\n'))
        # 写入 BAT
        # 换行符清洗是必须的，换行符转为linux
        zf.writestr("1_一键启动.bat", bat_start.replace('\n', '\r\n').encode('utf-8'))
        zf.writestr("2_停止并导出日志.bat", bat_stop.replace('\n', '\r\n').encode('utf-8'))
    return zip_buffer.getvalue()

def get_bat_content(sh_filename,remote_log_dir="/sdcard/dognoise_stress"):
    launcher_gen = LauncherGenerator(dist_dir=None)

    return launcher_gen.generate_all_content(sh_filename=sh_filename, remote_log_dir=remote_log_dir)

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.excel_loader import ExcelLoader
from src.models import ProjectModel

def load_and_parse_project(file_path: str) -> ProjectModel:
    """
    封装 ExcelLoader 的调用逻辑
    :param file_path: Excel 文件路径
    :return: ProjectModel 对象
    """
    loader = ExcelLoader(file_path)
    return loader.load_project()


def format_plans_for_ui(project: ProjectModel) :
    """
    把 ProjectModel 转换成 Streamlit 表格能用的 DataFrame
    """
    plan_data = []
    for p in project.plans:
        # 获取首个动作的描述
        first_action = "Empty"
        if p.tasks:
            t = p.tasks[0]
            # 优雅地拼接动作和参数
            first_action = f"{t.action} {t.p1 or ''}".strip()

        plan_data.append({
            "执行阶段": p.name,
            "循环次数": p.loop_count,
            "动作数": len(p.tasks),
            "首个动作": first_action
        })
    plan_df=pd.DataFrame(plan_data)

    try:
        config_data=project.config.model_dump()
    except:
        config_data =project.config.dict()

    items = list(config_data.items())

    config_df=pd.DataFrame(items, columns=["配置项 (Key)", "当前值 (Value)"])


    return config_df,plan_df

