import os
import datetime


class LauncherGenerator:
    def __init__(self, dist_dir =None):
        self.dist_dir = dist_dir

    def generate_all_and_write(self, sh_filename: str, remote_log_dir: str = "/sdcard/dognoise_stress"):
        """
        一次性生成所有配套的 bat 工具
        :param sh_filename: 手机里运行的脚本名 (如 stress_core.sh)
        :param remote_log_dir: 手机里存放日志的目录 (对应 template 里的 WORKDIR)
        """
        if not self.dist_dir:
            raise ValueError("本地生成模式必须提供 dist_dir！")

            # 1. 调用上面的方法拿内容
        start_content , stop_content= self.generate_all_content(sh_filename, remote_log_dir)

        # 2. 写入硬盘
        self._write_file(os.path.join(self.dist_dir, "1_一键启动.bat"), start_content)
        print(f"✅ 启动脚本已生成: {os.path.basename(self.dist_dir)}")
        self._write_file(os.path.join(self.dist_dir, "2_停止.bat"), stop_content)
        print(f"✅ 结束脚本已生成: {os.path.basename(self.dist_dir)}")

    def generate_all_content(self, sh_filename: str, remote_log_dir: str = "/sdcard/dognoise_stress"):
        start_content = self._create_start_bat(sh_filename)
        stop_content = self._create_stop_pull_bat(sh_filename, remote_log_dir)

        return start_content, stop_content

    def _create_start_bat(self, sh_filename: str):
        """生成 [一键启动.bat]"""
        # file_path = os.path.join(self.dist_dir, "1_一键启动.bat")

        content =  f"""@echo off
title Dognoise Stress Launcher
color 0A
echo.
echo [Dognoise] 初始化...
adb wait-for-device
adb root
adb remount

echo.
echo [1/3] 清理旧的进程...
adb shell "pkill -f stress_core.sh"
adb shell "rm -f /data/local/tmp/dognoise.lock"
adb logcat -c
adb shell "rm -rf /sdcard/dognoise_stress/*"

echo.
echo [2/3] 推送脚本到设备...
adb push stress_core.sh /data/local/tmp/stress_core.sh
adb shell chmod 777 /data/local/tmp/stress_core.sh

echo.
echo [3/3] 开始压测...
echo Log Path: /sdcard/dognoise_stress/event.log
echo ------------------------------------------
adb shell "nohup sh /data/local/tmp/stress_core.sh > /dev/null 2>&1 &"

echo.
echo 开始成功，可以关闭该窗口.
pause
"""

        return content



    def _create_stop_pull_bat(self, sh_filename: str, remote_log_dir: str):
        """生成 [停止并导出日志.bat]"""
        # file_path = os.path.join(self.dist_dir, "2_停止并导出日志.bat")

        # 这里的逻辑是：
        # 1. 杀掉脚本进程 (pkill)
        # 2. 删掉锁文件 (双重保险)
        # 3. adb pull 把手机里的日志拉到电脑当前目录

        content = f"""@echo off
chcp 65001
title Dognoise Stop & Export
echo ==========================================
echo       停止压测 & 导出日志
echo ==========================================

echo [1/2] 正在终止手机进程...
adb wait-for-device

REM 方法1: 杀掉脚本进程名 (最快)
adb shell "pkill -f {sh_filename}"

REM 方法2: 删除锁文件 (触发 trap 逻辑，假如脚本还在跑的话)
adb shell "rm -f /data/local/tmp/dognoise.lock"

echo 进程终止信号已发送。

echo.
echo [2/2] 正在导出日志...
echo 目标目录: {remote_log_dir}

REM 生成带时间戳的文件夹名，防止覆盖
set "CURRENT_DATE=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%"
set "CURRENT_DATE=%CURRENT_DATE: =0%"
set "EXPORT_DIR=logs_%CURRENT_DATE%"

mkdir "%EXPORT_DIR%"
adb pull {remote_log_dir}/. "%EXPORT_DIR%/"

echo.
echo 操作完成！
echo 日志已保存在文件夹: [%EXPORT_DIR%]
echo.
pause
"""
        return content


    def _write_file(self, path, content):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)