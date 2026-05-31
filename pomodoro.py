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
from PySide6.QtGui import QColor, QFont, QPainter, QPen
#   QColor   —— 颜色对象（阶段背景色、渐变插值）
#   QFont    —— 字体设置（字号、加粗）
#   QPainter / QPen —— 自绘圆形进度环

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
# 现代扁平配色：低饱和、柔和的主色，作为背景渐变的基准色。
PHASE_COLOR = {
    FOCUS: QColor("#e06c75"),   # 专注：暖珊瑚红
    SHORT: QColor("#56b6c2"),   # 短休息：青绿
    LONG:  QColor("#61afef"),   # 长休息：天蓝
}
# 秒表模式的专属背景色（深石板蓝）。
COUNTUP_COLOR = QColor("#5c6bc0")


def _shade(color, factor):
    """返回 color 的明暗变体，factor>1 提亮、<1 压暗，用于构造背景渐变的两端。"""
    h, s, v, a = color.getHsvF()
    v = max(0.0, min(1.0, v * factor))
    out = QColor()
    out.setHsvF(h, s, v, a)
    return out


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


# ---------------------- 圆形进度环控件 ----------------------
class RingTimer(QWidget):
    """自绘的圆形进度环，环中央叠加阶段名与时间文字。

    通过 set_progress(0~1) 控制弧线填充比例；颜色随阶段背景同步。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 240)
        self._progress = 1.0          # 进度比例：1=满，0=空
        self._phase_text = ""         # 环内上方小字（阶段名）
        self._time_text = "25:00"     # 环内中央大字（时间）
        self._ring_color = QColor("white")

    def set_progress(self, ratio):
        self._progress = max(0.0, min(1.0, ratio))
        self.update()

    def set_texts(self, phase_text, time_text):
        self._phase_text, self._time_text = phase_text, time_text
        self.update()

    def set_ring_color(self, color):
        self._ring_color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        thickness = 12
        margin = thickness + 6
        rect = self.rect().adjusted(margin, margin, -margin, -margin)

        # 底环：半透明白色轨道。
        track = QPen(QColor(255, 255, 255, 55), thickness)
        track.setCapStyle(Qt.RoundCap)
        p.setPen(track)
        p.drawArc(rect, 0, 360 * 16)

        # 进度弧：从正上方 (90°) 顺时针绘制。
        pen = QPen(self._ring_color, thickness)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        span = int(-360 * 16 * self._progress)
        p.drawArc(rect, 90 * 16, span)

        # 环内文字。
        p.setPen(QColor("white"))
        p.setFont(QFont("Segoe UI", 12, QFont.DemiBold))
        top = rect.adjusted(0, int(side * 0.22), 0, 0)
        p.drawText(top, Qt.AlignHCenter | Qt.AlignTop, self._phase_text)
        p.setFont(QFont("Segoe UI", 46, QFont.Bold))
        p.drawText(rect, Qt.AlignCenter, self._time_text)


# ---------------------- 主窗口类 ----------------------
class ModernPomodoro(QWidget):
    """番茄时钟主窗口。继承 QWidget，本身既是窗口也是所有控件的容器。"""

    def __init__(self):
        super().__init__()                       # 调用父类 QWidget 的初始化
        self.setWindowTitle("现代番茄时钟")        # 窗口标题栏文字
        self.setFixedSize(420, 560)              # 固定窗口大小，禁止用户拉伸

        # --- 加载持久化数据 ---
        # 读取配置；若文件不存在则用 DEFAULT_CONFIG，缺字段也会被默认值补全。
        self.config_data = load_json(CONFIG_FILE, DEFAULT_CONFIG)
        # 读取统计；统计无默认结构，传空字典即可（格式为 {"2026-05-31": 3, ...}）。
        self.stats = load_json(STATS_FILE, {})

        # --- 运行时状态变量 ---
        self.phase = FOCUS                            # 当前阶段，启动时为「专注」
        self.completed_focus = 0                      # 已完成的专注轮数，用于判定何时长休息
        self.remaining = self.config_data["focus"] * 60  # 倒计时剩余秒数（分钟×60）
        self.phase_total = self.remaining             # 当前阶段总秒数，用于算进度环比例
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
        """构建整个界面：顶部分段导航 + 中部堆叠面板（番茄环/秒表）+ 底部统计卡片。"""
        layout = QVBoxLayout(self)               # 主垂直布局，挂在窗口自身上
        layout.setContentsMargins(28, 24, 28, 24)  # 四周内边距
        layout.setSpacing(18)

        # ----- 顶部：分段式模式切换（两个按钮拼成一个胶囊）-----
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(0)
        self.btn_mode_pomodoro = QPushButton("番茄钟")
        self.btn_mode_countup = QPushButton("秒表")
        for btn in (self.btn_mode_pomodoro, self.btn_mode_countup):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)               # 可选中，用选中态高亮当前模式
            btn.setMinimumHeight(38)
            nav_layout.addWidget(btn)
        self.btn_mode_pomodoro.setChecked(True)
        self._style_nav()                        # 应用分段按钮样式
        layout.addLayout(nav_layout)

        # ----- 中部：堆叠容器，叠放两个面板，同一时刻只显示一个 -----
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        # --- 面板 0：倒计时（番茄钟）---
        pomo_widget = QWidget()
        pomo_layout = QVBoxLayout(pomo_widget)
        pomo_layout.setAlignment(Qt.AlignCenter)
        pomo_layout.setSpacing(24)

        # 圆形进度环（环内自带阶段名 + 时间文字）。
        self.ring = RingTimer()
        pomo_layout.addWidget(self.ring, 0, Qt.AlignCenter)

        # 倒计时操作按钮区：开始/重置/跳过/设置
        btns_layout = QHBoxLayout()
        btns_layout.setSpacing(10)
        self.start_btn = QPushButton("开始")     # 文字在「开始/暂停」间切换，作主按钮
        reset_btn = QPushButton("重置")
        skip_btn = QPushButton("跳过")
        set_btn = QPushButton("设置")

        self.start_btn.setStyleSheet(self._primary_btn_style())
        for btn in (reset_btn, skip_btn, set_btn):
            btn.setStyleSheet(self._btn_style())
        for btn in (self.start_btn, reset_btn, skip_btn, set_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(42)
            btns_layout.addWidget(btn)

        self.start_btn.clicked.connect(self.toggle)
        reset_btn.clicked.connect(self.reset)
        skip_btn.clicked.connect(self.skip)
        set_btn.clicked.connect(self.open_settings)
        pomo_layout.addLayout(btns_layout)
        self.stack.addWidget(pomo_widget)


        # --- 面板 1：正向计时（秒表）---
        countup_widget = QWidget()
        countup_layout = QVBoxLayout(countup_widget)
        countup_layout.setAlignment(Qt.AlignCenter)
        countup_layout.setSpacing(24)

        # 秒表环（无进度，纯展示时间，套用同款圆环视觉）。
        self.cu_ring = RingTimer()
        self.cu_ring.set_progress(0)
        self.cu_ring.set_texts("正向计时", "00:00")
        countup_layout.addWidget(self.cu_ring, 0, Qt.AlignCenter)

        # 秒表按钮区：开始/暂停 与 停止并记录
        cu_btns_layout = QHBoxLayout()
        cu_btns_layout.setSpacing(10)
        self.cu_start_btn = QPushButton("开始")        # 文字在 开始/暂停/继续 间切换
        self.cu_stop_btn = QPushButton("停止并记录")
        self.cu_start_btn.setStyleSheet(self._primary_btn_style())
        self.cu_stop_btn.setStyleSheet(self._btn_style())
        for btn in (self.cu_start_btn, self.cu_stop_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(42)
            cu_btns_layout.addWidget(btn)

        self.cu_start_btn.clicked.connect(self.toggle_countup)
        self.cu_stop_btn.clicked.connect(self.stop_and_record_countup)
        countup_layout.addLayout(cu_btns_layout)
        self.stack.addWidget(countup_widget)

        # ----- 底部：统计信息卡片（今日完成 / 累计）-----
        self.stats_label = QLabel("")
        self.stats_label.setFont(QFont("Segoe UI", 11, QFont.DemiBold))
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.stats_label.setMinimumHeight(46)
        self.stats_label.setStyleSheet(
            "color: white; background-color: rgba(255,255,255,0.14);"
            "border-radius: 14px; padding: 6px;")
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
        self.btn_mode_pomodoro.setChecked(index == 0)
        self.btn_mode_countup.setChecked(index == 1)
        if index == 1:
            self.animate_color_change(COUNTUP_COLOR)        # 秒表模式专属背景色
            self.cu_ring.set_ring_color(QColor("white"))
        else:
            self.animate_color_change(PHASE_COLOR[self.phase])  # 回到当前阶段色

    def animate_color_change(self, target_color):
        """从当前背景色平滑过渡到 target_color。"""
        self.color_anim.setStartValue(self.current_bg_color)  # 动画起点 = 现在的颜色
        self.color_anim.setEndValue(target_color)             # 动画终点 = 目标颜色
        self.color_anim.start()                               # 启动动画（异步逐帧回调）
        self.current_bg_color = target_color                  # 记下目标，作为下次起点

    def set_background_color(self, color):
        """把窗口背景设为指定颜色的对角线渐变。被动画每帧调用，也在初始化时直接调用。"""
        if isinstance(color, QColor):  # 动画插值出的中间值是 QColor，做个类型保护
            top = _shade(color, 1.12).name()      # 渐变上端：略提亮
            bottom = _shade(color, 0.78).name()   # 渐变下端：压暗，营造纵深
            self.setStyleSheet(
                "ModernPomodoro { background-color: qlineargradient("
                f"x1:0, y1:0, x2:0, y2:1, stop:0 {top}, stop:1 {bottom}); }}")


    def _btn_style(self):
        """次级操作按钮：玻璃质感半透明白底、圆角、悬停/按下变色。"""
        return """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.16);
                color: white; border: none; border-radius: 12px;
                padding: 8px 12px; font-size: 14px; font-weight: 600;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.28); }
            QPushButton:pressed { background-color: rgba(255, 255, 255, 0.10); }
        """

    def _primary_btn_style(self):
        """主按钮（开始/暂停）：不透明白底、深色文字，视觉更突出。"""
        return """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.92);
                color: #2c2c34; border: none; border-radius: 12px;
                padding: 8px 12px; font-size: 14px; font-weight: 700;
            }
            QPushButton:hover { background-color: white; }
            QPushButton:pressed { background-color: rgba(255, 255, 255, 0.80); }
        """

    def _style_nav(self):
        """分段导航按钮：选中态实心高亮，未选中半透明，拼成一个胶囊。"""
        style = """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.10);
                color: rgba(255, 255, 255, 0.75); border: none;
                font-size: 13px; font-weight: 700;
            }
            QPushButton:checked {
                background-color: rgba(255, 255, 255, 0.92); color: #2c2c34;
            }
        """
        # 左右两个按钮分别只圆化外侧角，拼合成完整胶囊。
        left = style + "QPushButton { border-top-left-radius: 19px; border-bottom-left-radius: 19px; }"
        right = style + "QPushButton { border-top-right-radius: 19px; border-bottom-right-radius: 19px; }"
        self.btn_mode_pomodoro.setStyleSheet(left)
        self.btn_mode_countup.setStyleSheet(right)

    def _update_display(self):
        """根据当前状态刷新进度环与主按钮文字。"""
        m, s = divmod(self.remaining, 60)                  # 把剩余总秒数拆成分和秒
        ratio = self.remaining / self.phase_total if self.phase_total else 0
        self.ring.set_ring_color(QColor("white"))
        self.ring.set_progress(ratio)
        self.ring.set_texts(PHASE_LABEL[self.phase], f"{m:02d}:{s:02d}")
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
        self.phase_total = self.remaining
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
        self.phase_total = self.remaining

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
        self.cu_ring.set_texts("正向计时", f"{m:02d}:{s:02d}")

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
        self.cu_ring.set_texts("正向计时", "00:00")
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
