import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import pomodoro as p

results = []
app = QApplication([])
w = p.ModernPomodoro()
w.show()
results.append(("init_phase", w.phase == p.FOCUS))
results.append(("init_remaining", w.remaining == w.config_data["focus"] * 60))
w.toggle()
results.append(("running", w.is_running))
w._tick()
results.append(("tick_dec", w.remaining == w.config_data["focus"] * 60 - 1))
w.phase = p.FOCUS; w.completed_focus = 0; w.remaining = 0
w._phase_done(skip=True)
results.append(("focus_to_short", w.phase == p.SHORT))
w.phase = p.FOCUS; w.completed_focus = 3
w._phase_done(skip=True)
results.append(("fourth_to_long", w.phase == p.LONG))
w.countup_seconds = 50 * 60
before = sum(w.stats.values())
w.stop_and_record_countup()
expected = before + round(50 / w.config_data["focus"], 2)
results.append(("countup_record", abs(sum(w.stats.values()) - expected) < 1e-6))
QTimer.singleShot(150, app.quit)
app.exec()
results.append(("event_loop", True))

with open(os.path.join(os.path.dirname(__file__), "test_result.txt"), "w", encoding="utf-8") as f:
    allpass = all(ok for _, ok in results)
    for name, ok in results:
        f.write(f"{'PASS' if ok else 'FAIL'} {name}\n")
    f.write("ALL PASS\n" if allpass else "SOME FAILED\n")
