"""
现代番茄时钟（PySide6 / Qt 版本）

功能概览：
  1. 倒计时番茄钟：专注 -> 短休息 -> 专注 ... 每完成 N 轮专注进入一次长休息。
  2. 正向计时秒表：自由记录专注时长，按标准番茄时长折算成完成的番茄个数。
  3. 背景颜色随当前阶段平滑渐变（动画过渡）。
  4. 阶段结束时任务栏闪烁提醒并弹出对话框。
  5. 配置（专注时长等）与统计（每日完成番茄数）持久化到本地 JSON 文件。

运行方式（需先安装依赖）：
    pip install PySide6
    python pomodoro.py
"""

import json   # 读写配置 / 统计的 JSON 文件
import os     # 拼接文件路径、判断文件是否存在
import sys     # 获取命令行参数并传给 QApplication，退出时返回事件循环结果
from datetime import date  # 取当天日期作为统计字典的键（每天一个 key）

# 从 PySide6 导入所需的 Qt 类，按模块分组：
# QtCore：核心非 GUI 类
from PySide6.QtCore import Qt, QTimer, QVariantAnimation, QTime, Slot
#   Qt               —— 各种枚举常量（对齐方式、鼠标光标等）
#   QTimer           —— 定时器，每隔固定毫秒触发一次，用于秒级计时
#   QVariantAnimation—— 通用数值动画，这里用于背景色的平滑渐变
#   QTime            —— 时间类型（当前代码保留导入，备用）
#   Slot             —— 装饰器，把方法标记为 Qt 槽函数（响应信号）

# QtGui：图形相关类
from PySide6.QtGui import QColor, QFont, QPalette
#   QColor   —— 颜色对象（阶段背景色、渐变插值）
#   QFont    —— 字体设置（字号、加粗）
#   QPalette —— 调色板（保留导入，备用）

# QtWidgets：所有可见的界面控件
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QStackedWidget, QInputDialog, QMessageBox)
#   QApplication   —— 每个 Qt 程序有且仅有一个，管理事件循环
#   QWidget        —— 所有控件的基类，也用作窗口/面板容器
#   QVBoxLayout    —— 垂直布局（控件从上到下排列）
#   QHBoxLayout    —— 水平布局（控件从左到右排列）
#   QPushButton    —— 按钮
#   QLabel         —— 文本标签
#   QStackedWidget —— 堆叠容器，多页面叠放只显示其中一页，用于切换两种计时模式
#   QInputDialog   —— 简单输入对话框（设置专注时长时弹出）
#   QMessageBox    —— 消息提示框

# ---------------------- 文件路径与默认配置 ----------------------
# BASE：本脚本所在目录的绝对路径。__file__ 是当前文件路径，
# abspath 转为绝对路径，dirname 取其所在文件夹，保证无论从哪运行都能定位到同目录。
BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "pomodoro_config.json")  # 配置文件：保存各阶段时长等
STATS_FILE = os.path.join(BASE, "pomodoro_stats.json")    # 统计文件：保存每日完成番茄数

# 默认配置：专注 25 分钟，短休 5 分钟，长休 15 分钟，每 4 轮专注后进入长休息。
DEFAULT_CONFIG = {"focus": 25, "short": 5, "long": 15, "rounds": 4}

# 三个阶段的内部标识字符串，作为字典的键统一使用，避免到处写字符串拼错。
FOCUS, SHORT, LONG = "focus", "short", "long"
# 阶段标识 -> 中文显示名，用于界面展示。
PHASE_LABEL = {FOCUS: "专注", SHORT: "短休息", LONG: "长休息"}
# 阶段标识 -> 对应的背景主题色（QColor 对象，供渐变动画使用）。
PHASE_COLOR = {FOCUS: QColor("#d95550"), SHORT: QColor("#4c9195"), LONG: QColor("#457ca3")}


def load_json(path, default):
    """读取 JSON 文件并返回字典。

    参数:
        path    -- JSON 文件路径
        default -- 默认值字典；非空时会把读到的内容合并到默认值上，
                   这样即便旧配置缺字段也能用默认值补全。
    返回:
        读取成功返回合并后的字典；文件不存在或解析失败返回默认值的副本。
    """
    if os.path.exists(path):            # 文件存在才尝试读取
        try:
            with open(path, "r", encoding="utf-8") as f:  # 以 UTF-8 打开，支持中文
                # 有默认值时用 {**default, **读到的内容} 合并：读到的覆盖默认；
                # 没有默认值（如统计文件）时直接返回原始内容。
                return {**default, **json.load(f)} if default else json.load(f)
        except (json.JSONDecodeError, OSError):
            # 文件损坏（非合法 JSON）或读取出错时，忽略错误走下面的默认返回。
            pass
    # 文件不存在或上面出错：有默认值就返回它的副本（dict() 拷贝，避免外部改到原字典），
    # 否则返回空字典。
    return dict(default) if default else {}


def save_json(path, data):
    """把字典 data 写入 path 指向的 JSON 文件。

    ensure_ascii=False 让中文原样保存而非转成 \\uXXXX；indent=2 美化缩进便于人工查看。
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------- 主窗口类 ----------------------
class ModernPomodoro(QWidget):
    """番茄时钟主窗口。继承 QWidget，本身既是窗口也是所有控件的容器。"""

    def __init__(self):
        super().__init__()                       # 调用父类 QWidget 的初始化
        self.setWindowTitle("现代番茄时钟")        # 窗口标题栏文字
        self.setFixedSize(380, 480)              # 固定窗口大小，禁止用户拉伸

        # --- 加载持久化数据 ---
        # 读取配置；若文件不存在则用 DEFAULT_CONFIG，缺字段也会被默认值补全。
        self.config_data = load_json(CONFIG_FILE, DEFAULT_CONFIG)
        # 读取统计；统计无默认结构，传空字典即可（格式为 {"2026-05-31": 3, ...}）。
        self.stats = load_json(STATS_FILE, {})

        # --- 运行时状态变量 ---
        self.phase = FOCUS                            # 当前阶段，启动时为「专注」
        self.completed_focus = 0                      # 已完成的专注轮数，用于判定何时长休息
        self.remaining = self.config_data["focus"] * 60  # 倒计时剩余秒数（分钟×60）
        self.countup_seconds = 0                      # 正向计时（秒表）已累计的秒数
        self.is_running = False                       # 倒计时是否正在运行的标志

        # 当前背景色，初始为专注阶段的主题色；渐变动画会从这个值开始过渡。
        self.current_bg_color = PHASE_COLOR[FOCUS]
        self.set_background_color(self.current_bg_color)  # 立即把窗口背景刷成该色

        # --- 初始化界面与定时器 ---
        self._build_ui()             # 构建所有控件与布局
        self._init_timers()          # 创建两个 QTimer 和颜色渐变动画
        self._refresh_stats_label()  # 刷新底部「今日/累计」统计文字
        self._update_display()       # 刷新时间、阶段、按钮文字的初始显示


    def _build_ui(self):
        """构建整个界面：顶部模式切换导航 + 中部堆叠面板（番茄/秒表）+ 底部统计。"""
        layout = QVBoxLayout(self)               # 主垂直布局，挂在窗口自身上
        layout.setContentsMargins(20, 20, 20, 20)  # 四周留 20px 内边距
        layout.setAlignment(Qt.AlignCenter)      # 内容整体居中

        # ----- 顶部：两个模式切换按钮（番茄倒计时 / 秒表正计时）-----
        nav_layout = QHBoxLayout()               # 水平排列两个导航按钮
        self.btn_mode_pomodoro = QPushButton("倒计时 (番茄)")
        self.btn_mode_countup = QPushButton("正向计时 (秒表)")
        for btn in (self.btn_mode_pomodoro, self.btn_mode_countup):
            btn.setCursor(Qt.PointingHandCursor)  # 鼠标悬停时变成手型，提示可点击
            btn.setStyleSheet(self._nav_btn_style())  # 应用导航按钮样式
            nav_layout.addWidget(btn)            # 加入水平布局
        layout.addLayout(nav_layout)             # 把导航栏放进主布局顶部

        # ----- 中部：堆叠容器，叠放两个面板，同一时刻只显示一个 -----
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # --- 面板 0：倒计时（番茄钟）---
        pomo_widget = QWidget()                  # 该面板的容器控件
        pomo_layout = QVBoxLayout(pomo_widget)   # 面板内垂直布局
        pomo_layout.setAlignment(Qt.AlignCenter)

        # 阶段名称标签（专注/短休息/长休息）
        self.phase_label = QLabel(PHASE_LABEL[FOCUS])
        self.phase_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self.phase_label.setStyleSheet("color: white;")
        self.phase_label.setAlignment(Qt.AlignCenter)
        pomo_layout.addWidget(self.phase_label)

        # 大号倒计时时间标签，初始显示 25:00
        self.time_label = QLabel("25:00")
        self.time_label.setFont(QFont("Segoe UI", 64, QFont.Bold))
        self.time_label.setStyleSheet("color: white;")
        self.time_label.setAlignment(Qt.AlignCenter)
        pomo_layout.addWidget(self.time_label)

        # 倒计时操作按钮区：开始/重置/跳过/设置
        btns_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始")     # 用 self 保存：文字要在「开始/暂停」间切换
        reset_btn = QPushButton("重置")
        skip_btn = QPushButton("跳过")
        set_btn = QPushButton("设置")

        for btn in (self.start_btn, reset_btn, skip_btn, set_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._btn_style())  # 应用通用按钮样式
            btns_layout.addWidget(btn)

        # 把按钮的「点击」信号连接到对应的处理方法（槽）
        self.start_btn.clicked.connect(self.toggle)   # 开始/暂停
        reset_btn.clicked.connect(self.reset)         # 重置当前阶段
        skip_btn.clicked.connect(self.skip)           # 跳过当前阶段
        set_btn.clicked.connect(self.open_settings)   # 打开设置
        pomo_layout.addLayout(btns_layout)
        self.stack.addWidget(pomo_widget)             # 作为堆叠的第 0 页加入


        # --- 面板 1：正向计时（秒表）---
        countup_widget = QWidget()
        countup_layout = QVBoxLayout(countup_widget)
        countup_layout.setAlignment(Qt.AlignCenter)

        # 面板标题
        cu_title = QLabel("专注记录 (正向计时)")
        cu_title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        cu_title.setStyleSheet("color: white;")
        cu_title.setAlignment(Qt.AlignCenter)
        countup_layout.addWidget(cu_title)

        # 秒表时间标签，从 00:00 开始往上累加
        self.countup_label = QLabel("00:00")
        self.countup_label.setFont(QFont("Segoe UI", 64, QFont.Bold))
        self.countup_label.setStyleSheet("color: white;")
        self.countup_label.setAlignment(Qt.AlignCenter)
        countup_layout.addWidget(self.countup_label)

        # 秒表按钮区：开始/暂停 与 停止并记录
        cu_btns_layout = QHBoxLayout()
        self.cu_start_btn = QPushButton("开始")        # 文字在 开始/暂停/继续 间切换
        self.cu_stop_btn = QPushButton("停止并记录")
        for btn in (self.cu_start_btn, self.cu_stop_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._btn_style())
            cu_btns_layout.addWidget(btn)

        self.cu_start_btn.clicked.connect(self.toggle_countup)          # 开始/暂停秒表
        self.cu_stop_btn.clicked.connect(self.stop_and_record_countup)  # 停止并写入统计
        countup_layout.addLayout(cu_btns_layout)
        self.stack.addWidget(countup_widget)            # 作为堆叠的第 1 页加入

        # ----- 底部：统计信息标签（今日完成 / 累计）-----
        self.stats_label = QLabel("")
        self.stats_label.setFont(QFont("Segoe UI", 11))
        self.stats_label.setStyleSheet("color: #e0e0e0;")
        self.stats_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.stats_label)

        # 绑定模式切换：点导航按钮切换堆叠页（0=番茄，1=秒表）
        self.btn_mode_pomodoro.clicked.connect(lambda: self.switch_mode(0))
        self.btn_mode_countup.clicked.connect(lambda: self.switch_mode(1))


    def _init_timers(self):
        """创建两个秒级定时器和一个背景色渐变动画。"""
        # 倒计时定时器：每 1000ms（1 秒）触发一次 _tick，递减剩余时间。
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        # 正向计时定时器：每 1 秒触发 _cu_tick，秒表 +1。
        self.cu_timer = QTimer(self)
        self.cu_timer.timeout.connect(self._cu_tick)

        # 背景色渐变动画：在两个颜色间做插值，valueChanged 每帧回调更新背景。
        self.color_anim = QVariantAnimation(self)
        self.color_anim.setDuration(800)  # 整个过渡持续 800 毫秒
        self.color_anim.valueChanged.connect(self.set_background_color)

    def switch_mode(self, index):
        """切换显示的面板，并把背景色动画到对应主题色。

        index=0 番茄面板（用当前阶段色）；index=1 秒表面板（用专属深蓝灰色）。
        """
        self.stack.setCurrentIndex(index)
        if index == 1:
            self.animate_color_change(QColor("#34495e"))   # 秒表模式专属背景色
        else:
            self.animate_color_change(PHASE_COLOR[self.phase])  # 回到当前阶段色

    def animate_color_change(self, target_color):
        """从当前背景色平滑过渡到 target_color。"""
        self.color_anim.setStartValue(self.current_bg_color)  # 动画起点 = 现在的颜色
        self.color_anim.setEndValue(target_color)             # 动画终点 = 目标颜色
        self.color_anim.start()                               # 启动动画（异步逐帧回调）
        self.current_bg_color = target_color                  # 记下目标，作为下次起点

    def set_background_color(self, color):
        """把窗口背景设为指定颜色。被动画每帧调用，也在初始化时直接调用一次。"""
        if isinstance(color, QColor):  # 动画插值出的中间值是 QColor，做个类型保护
            # 用样式表设置背景；限定 ModernPomodoro 选择器，避免影响子控件。
            self.setStyleSheet(f"ModernPomodoro {{ background-color: {color.name()}; }}")


    def _btn_style(self):
        """返回通用操作按钮的样式表（半透明白底、圆角、悬停/按下变色）。"""
        return """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.2);
                color: white; border: none; border-radius: 8px;
                padding: 8px 12px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.3); }
            QPushButton:pressed { background-color: rgba(255, 255, 255, 0.1); }
        """

    def _nav_btn_style(self):
        """返回顶部模式切换按钮的样式表（透明描边按钮，悬停高亮）。"""
        return """
            QPushButton {
                background-color: transparent; color: rgba(255, 255, 255, 0.7);
                border: 2px solid rgba(255, 255, 255, 0.3); border-radius: 12px;
                padding: 6px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.1); color: white; }
        """

    def _update_display(self):
        """根据当前状态刷新倒计时面板的文字显示。"""
        m, s = divmod(self.remaining, 60)                  # 把剩余总秒数拆成分和秒
        self.time_label.setText(f"{m:02d}:{s:02d}")        # 格式化成 MM:SS（不足两位补 0）
        self.phase_label.setText(PHASE_LABEL[self.phase])  # 更新阶段名称
        # 运行中按钮显示「暂停」，否则显示「开始」
        self.start_btn.setText("暂停" if self.is_running else "开始")

    def _refresh_stats_label(self):
        """刷新底部统计：今日完成数 + 历史累计数。"""
        today = self.stats.get(date.today().isoformat(), 0)  # 今天的 key 取不到则为 0
        total = sum(self.stats.values())                     # 所有日期的值求和 = 累计
        self.stats_label.setText(f"今日完成 {today} 个专注  |  累计 {total} 个")


    # ---------------------- 倒计时（番茄钟）逻辑 ----------------------
    @Slot()
    def toggle(self):
        """开始 / 暂停 倒计时。点击「开始」按钮触发。"""
        self.is_running = not self.is_running   # 翻转运行状态
        if self.is_running:
            self.timer.start(1000)              # 启动：每 1 秒触发一次 _tick
        else:
            self.timer.stop()                   # 暂停：停掉定时器
        self._update_display()                  # 同步按钮文字（开始<->暂停）

    @Slot()
    def _tick(self):
        """定时器每秒回调：剩余时间减 1；归零则进入阶段结束处理。"""
        if self.remaining > 0:
            self.remaining -= 1                 # 还有时间，秒数 -1
            self._update_display()              # 刷新显示
        else:
            self._phase_done()                  # 时间到，处理阶段切换

    @Slot()
    def reset(self):
        """重置当前阶段：停止计时并把剩余时间恢复为该阶段的完整时长。"""
        self.is_running = False
        self.timer.stop()
        self.remaining = self.config_data[self.phase] * 60  # 当前阶段时长（分钟）×60
        self._update_display()

    @Slot()
    def skip(self):
        """跳过当前阶段，直接进入下一阶段（skip=True 表示不计入统计、不弹提醒）。"""
        self.timer.stop()
        self.is_running = False
        self._phase_done(skip=True)

    def _phase_done(self, skip=False):
        """阶段结束的统一处理：决定下一阶段、切换颜色、必要时记录并提醒。

        参数 skip：True 表示用户主动跳过，不记录番茄、不弹提醒。
        """
        self.is_running = False
        if self.phase == FOCUS:                 # 刚结束的是专注阶段
            if not skip:
                self._record_focus()            # 自然完成才记一个番茄
            self.completed_focus += 1           # 已完成专注轮数 +1
            # 每满 rounds 轮进入长休息，否则短休息（取余为 0 即达到长休条件）。
            nxt = LONG if self.completed_focus % self.config_data["rounds"] == 0 else SHORT
        else:                                   # 刚结束的是休息阶段
            nxt = FOCUS                          # 休息后回到专注

        self.phase = nxt                         # 更新当前阶段
        self.remaining = self.config_data[nxt] * 60  # 设为新阶段的完整时长

        # 仅当停留在番茄面板（第 0 页）时才播放背景渐变，避免覆盖秒表面板的颜色。
        if self.stack.currentIndex() == 0:
            self.animate_color_change(PHASE_COLOR[nxt])

        self._update_display()                   # 刷新时间/阶段/按钮
        self._refresh_stats_label()              # 刷新统计文字

        if not skip:                             # 自然结束才提醒
            QApplication.alert(self)             # 任务栏图标闪烁（窗口在后台时尤其有用）
            QMessageBox.information(self, "番茄时钟", f"{PHASE_LABEL[self.phase]}时间到了！")

    def _record_focus(self, amount=1):
        """把 amount 个番茄计入今天的统计并存盘。

        amount 默认 1（一次完整专注）；秒表模式会传入小数（按时长折算）。
        """
        key = date.today().isoformat()           # 今天日期作为键，如 "2026-05-31"
        self.stats[key] = self.stats.get(key, 0) + amount  # 累加到今天
        save_json(STATS_FILE, self.stats)        # 立即写入磁盘，防止丢失
        self._refresh_stats_label()              # 更新界面统计


    # ---------------------- 正向计时（秒表）逻辑 ----------------------
    @Slot()
    def toggle_countup(self):
        """开始 / 暂停 / 继续 秒表。根据定时器当前是否活动来切换。"""
        if self.cu_timer.isActive():
            self.cu_timer.stop()                 # 正在走 -> 暂停
            self.cu_start_btn.setText("继续")
        else:
            self.cu_timer.start(1000)            # 已停 -> 开始/继续，每秒 +1
            self.cu_start_btn.setText("暂停")

    @Slot()
    def _cu_tick(self):
        """秒表定时器每秒回调：累计秒数 +1 并刷新显示。"""
        self.countup_seconds += 1
        m, s = divmod(self.countup_seconds, 60)  # 拆成分:秒
        self.countup_label.setText(f"{m:02d}:{s:02d}")

    @Slot()
    def stop_and_record_countup(self):
        """停止秒表，把专注时长按标准番茄时长折算成番茄数记入统计，然后归零。"""
        self.cu_timer.stop()
        minutes = self.countup_seconds // 60     # 取整到分钟（不足 1 分钟的秒数舍去）
        if minutes >= 1:
            focus_unit = self.config_data["focus"]      # 一个标准番茄的分钟数
            earned = round(minutes / focus_unit, 2)     # 折算番茄数，保留两位小数
            self._record_focus(amount=earned)           # 计入统计
            QMessageBox.information(self, "记录成功",
                                    f"你专注了 {minutes} 分钟！\n折合记录了 {earned} 个番茄。")
        else:
            QMessageBox.information(self, "提示", "专注时间不足1分钟，未记录。")

        # 不论是否记录，都把秒表归零、按钮文字复位为「开始」。
        self.countup_seconds = 0
        self.countup_label.setText("00:00")
        self.cu_start_btn.setText("开始")

    @Slot()
    def open_settings(self):
        """弹出输入框修改专注时长（分钟），保存后重置当前阶段使其立即生效。"""
        # 返回 (输入值, 是否点了确定)；范围限定 1~120 分钟。
        new_focus, ok = QInputDialog.getInt(self, "设置", "专注时长(分钟):",
                                            self.config_data["focus"], 1, 120)
        if ok:                                   # 用户点了「确定」才保存
            self.config_data["focus"] = new_focus
            save_json(CONFIG_FILE, self.config_data)
            self.reset()                         # 让新时长立刻反映到倒计时


# ---------------------- 程序入口 ----------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)   # 创建应用对象，sys.argv 传入命令行参数
    app.setStyle("Fusion")         # 使用 Fusion 风格，跨平台外观统一
    window = ModernPomodoro()      # 创建主窗口
    window.show()                  # 显示窗口
    sys.exit(app.exec())           # 进入事件循环；退出时把返回码交给 sys.exit
