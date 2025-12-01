编写EXCEL文件
test plan.xlsx ，文件放在py文件同目录下，不要改名字
单个事件编写
单个事件套件编写，一套动作一个sheet
[图片]
- 所有的表头不要动
- 文件名称（test plan.xlsx）不要动
指令对照表
暂时无法在飞书文档外展示此内容
Config配置文件
[图片]
- 文件名称不要动！！
- 表头不要动！
配置说明
暂时无法在飞书文档外展示此内容
生成bat文件
YACE
│  getbat.py
│  test plan.xlsx
│
├─dist_stress
│      stress_core.sh
│      一键开始压测.bat
│
└─report_logs
        crash_stack.log
        event.log
1. 确认电脑有python环境
2. 进入cmd  python getbat.py 此时会生成dist_stress文件
3. 双击  一键开始压测.bat  运行即可
验收与分析
测试结束后（比如跑了一周），将设备连回电脑，运行以下命令拉取日志：
adb pull /sdcard/dognoise_stress ./TestReport
有三个文件
- anr_history  出现卡死anr时候的日志
- crash_stack   就是logcat的log
- event  运行日志，如果软件挂掉能在这里看出来
[DIED]---闪退
[ANR]---Application Not Responding" 弹窗（应用卡死）
[SYSTEM_CRASH]--- 表示检测到 SystemUI 重启（通常伴随着短暂的黑屏或回到锁屏）
每一行的Up
- 正常情况：1000s -> 1030s -> 1060s (递增)
- 异常情况（系统彻底自动重启）：... -> 25000s -> (突然断掉) -> 10s (变成了很小的数字)
