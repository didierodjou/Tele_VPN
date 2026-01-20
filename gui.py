import sys
import asyncio
import logging
import time
import threading
from collections import deque

import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTextEdit, QLabel,
                             QFrame, QStackedWidget, QLineEdit, QGridLayout,
                             QCheckBox, QDialog, QProgressBar, QComboBox, QInputDialog, QDialogButtonBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QTextCursor, QPixmap, QIcon

import pyqtgraph as pg

# --- ПОПЫТКА ИМПОРТА ЯДРА ---
try:
    from main import VPNApplication
    from config import config

    CORE_AVAILABLE = True
except ImportError:
    CORE_AVAILABLE = False
    config = None

# --- ЦВЕТОВАЯ ПАЛИТРА (TeleVK PN Style) ---
C_BG = "#0B0E14"  # Глубокий черный-синий
C_SIDEBAR = "#0F131A"
C_PANEL = "#161B22"
C_ACCENT = "#00E676"  # Ярко-зеленый для кнопок
C_SERVER_MODE = "#1A212C"
C_TEXT = "#FFFFFF"
C_TEXT_DIM = "#8B949E"
C_BLUE_ICON = "#2196F3"
C_YELLOW_ICON = "#FFD600"

STYLESHEET = f"""
QMainWindow {{ background-color: {C_BG}; }}
QWidget {{ font-family: 'Segoe UI', sans-serif; color: {C_TEXT}; font-size: 14px; }}

/* ИСПРАВЛЕННЫЕ ПОЛЯ ВВОДА */
QLineEdit, QComboBox {{ 
    background-color: #0D1117; 
    border: 1px solid #30363D; 
    padding: 8px; 
    border-radius: 6px; 
    color: {C_ACCENT};  /* Светло-зеленый текст */
    selection-background-color: {C_ACCENT};
    selection-color: #000;
}}
QLineEdit:focus {{ border: 1px solid {C_ACCENT}; }}

QFrame#Panel {{ background-color: {C_PANEL}; border-radius: 8px; border: 1px solid #30363D; }}
QFrame#Sidebar {{ background-color: {C_SIDEBAR}; border-right: 1px solid #30363D; }}

QPushButton#MenuBtn {{ 
    background-color: transparent; color: {C_TEXT_DIM}; text-align: left; 
    padding: 12px 20px; border: none; font-size: 14px;
}}
QPushButton#MenuBtn:checked {{ 
    color: {C_ACCENT}; background-color: #1A212C; border-left: 3px solid {C_ACCENT}; 
}}

QPushButton#ActionBtn {{ 
    background-color: {C_ACCENT}; color: #000; border-radius: 6px; 
    font-weight: bold; padding: 8px 20px; 
}}
QPushButton#ActionBtn[state="stop"] {{ background-color: #FF5252; color: white; }}

QTextEdit {{ 
    background-color: #0D1117; border: none; border-radius: 4px; 
    color: #C9D1D9; font-family: 'Consolas', monospace; font-size: 11px; 
}}
"""


class LogBridge(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        self.signal.emit(self.format(record), record.levelno)


class VPNWorker(QThread):
    log_signal = pyqtSignal(str, int)
    status_signal = pyqtSignal(bool)
    traffic_signal = pyqtSignal()
    auth_request = pyqtSignal(str, object, str)

    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.app = None
        self.loop = None
        self.auth_result = None
        self.bytes_sent = 0
        self.bytes_recv = 0

    def _gui_auth_wrapper(self, r_type, payload=None):
        event = threading.Event()
        self.auth_request.emit(r_type, event, str(payload) if payload else "")
        event.wait()
        return self.auth_result

    def run(self):
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.app = VPNApplication()
            self.app.set_callbacks(
                on_traffic=lambda: self.traffic_signal.emit(),
                auth_phone=lambda: self._gui_auth_wrapper('phone'),
                auth_code=lambda payload=None: self._gui_auth_wrapper('code', payload),
                auth_pass=lambda: self._gui_auth_wrapper('pass')
            )

            # Перехват логов
            logger = logging.getLogger("VPN_Core")

            class Handler(logging.Handler):
                def __init__(self, sig): super().__init__(); self.sig = sig

                def emit(self, rec): self.sig.emit(rec.getMessage(), rec.levelno)

            logger.addHandler(Handler(self.log_signal))

            self.status_signal.emit(True)
            self.log_signal.emit(f"Инициализация ядра: {self.mode.upper()}", logging.INFO)
            self.loop.run_until_complete(self.app.run_async(self.mode))
        except Exception as e:
            self.log_signal.emit(f"Ошибка: {e}", logging.ERROR)
        finally:
            self.status_signal.emit(False)
            self.loop.close()

    def stop(self):
        if self.app:
            self.app.is_running = False
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.app.shutdown(), self.loop)

    def get_stats(self):
        if self.app and hasattr(self.app, 'handler'):
            tap = getattr(self.app.handler, 'tap_interface', None)
            if tap: return tap.packet_count
        return 0


class StatCard(QFrame):
    def __init__(self, title, icon, icon_color="#2196F3"):
        super().__init__()
        self.setObjectName("Panel")
        self.setFixedHeight(100)
        layout = QVBoxLayout(self)

        top_h = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("StatTitle")
        top_h.addWidget(t)
        top_h.addStretch()

        self.ic = QLabel(icon)
        self.ic.setStyleSheet(
            f"color: {icon_color}; font-size: 18px; font-weight: bold; background: #1A212C; padding: 4px; border-radius: 4px;")
        top_h.addWidget(self.ic)
        layout.addLayout(top_h)

        self.val = QLabel("0")
        self.val.setObjectName("StatValue")
        layout.addWidget(self.val)

        self.sub = QLabel("Ожидание...")
        self.sub.setObjectName("StatSub")
        layout.addWidget(self.sub)

    def update_data(self, main_text, sub_text=None):
        self.val.setText(str(main_text))
        if sub_text: self.sub.setText(sub_text)


class Dashboard(QWidget):
    def __init__(self, parent_win):
        super().__init__()
        self.parent_win = parent_win
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(25, 20, 25, 10)
        main_layout.setSpacing(15)

        # Header Row
        head_h = QHBoxLayout()
        head_h.addWidget(QLabel("Обзор сети", objectName="Header"))
        head_h.addStretch()

        self.mode_badge = QFrame(objectName="ServerBadge")
        mb_l = QHBoxLayout(self.mode_badge)
        mb_l.setContentsMargins(10, 2, 10, 2)
        self.lbl_mode_status = QLabel("💻 РЕЖИМ КЛИЕНТА")
        self.lbl_mode_status.setStyleSheet("font-size: 11px; font-weight: bold; color: #8B949E;")
        mb_l.addWidget(self.lbl_mode_status)
        head_h.addWidget(self.mode_badge)

        self.btn_toggle = QPushButton("Запуск туннеля")
        self.btn_toggle.setObjectName("ActionBtn")
        self.btn_toggle.clicked.connect(self.parent_win.toggle_vpn)
        head_h.addWidget(self.btn_toggle)
        main_layout.addLayout(head_h)

        # Stats Grid (4 Cards)
        grid = QGridLayout()
        grid.setSpacing(15)
        self.card_speed = StatCard("Скорость", "⚡")
        self.card_sent = StatCard("Всего данных", "📦", "#FFFFFF")
        #self.card_recv = StatCard("Принято", "↓", "#2196F3")
        self.card_ping = StatCard("Задержка", "⚡", "#FF0000")
        self.card_time = StatCard("Время сессии", "🕒", "#FFFFFF")

        grid.addWidget(self.card_speed, 0, 0)
        grid.addWidget(self.card_sent, 0, 1)
        #grid.addWidget(self.card_recv, 0, 2)
        grid.addWidget(self.card_ping, 0, 2)
        grid.addWidget(self.card_time, 0, 3)
        main_layout.addLayout(grid)

        # Mid Content (Plot + Log)
        mid_h = QHBoxLayout()
        mid_h.setSpacing(15)

        # Plot Panel
        # plot_panel = QFrame(objectName="Panel")
        # plot_v = QVBoxLayout(plot_panel)

        # Создаем метку и отдельно задаем стиль
        g_panel = QFrame()
        g_panel.setObjectName("Panel")
        gl = QVBoxLayout(g_panel)
        gl.addWidget(QLabel("СЕТЕВАЯ АКТИВНОСТЬ"))
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('k')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.curve = self.plot_widget.plot(pen=pg.mkPen(color=C_ACCENT, width=2))
        gl.addWidget(self.plot_widget)
        mid_h.addWidget(g_panel, stretch=7)

        # --- ИСПРАВЛЕННЫЙ БЛОК ПАНЕЛИ ЖУРНАЛА ---
        log_panel = QFrame(objectName="Panel")
        log_v = QVBoxLayout(log_panel)

        # Создаем метку и отдельно задаем стиль
        lbl_log = QLabel(">_ ЖУРНАЛ")
        lbl_log.setStyleSheet("font-weight: bold; font-size: 13px; color: white;")
        log_v.addWidget(lbl_log)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        log_v.addWidget(self.log_view)
        mid_h.addWidget(log_panel, stretch=3)

        main_layout.addLayout(mid_h, stretch=1)

        # Bottom Info Bar
        bottom_h = QHBoxLayout()
        self.lbl_status_dot = QLabel("● ОТКЛЮЧЕНО")
        self.lbl_status_dot.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: bold;")
        bottom_h.addWidget(self.lbl_status_dot)

        bottom_h.addStretch()

        self.lbl_footer_info = QLabel(
            f"Локальный IP: {config.client_ip if config else '0.0.0.0'}")
        self.lbl_footer_info.setStyleSheet("color: #8B949E; font-size: 11px;")
        bottom_h.addWidget(self.lbl_footer_info)

        main_layout.addLayout(bottom_h)


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        l = QVBoxLayout(self)
        l.setContentsMargins(40, 40, 40, 40)
        l.addWidget(QLabel("НАСТРОЙКИ КОНФИГУРАЦИИ", objectName="Header"))
        l.addSpacing(20)

        self.form = QFrame()
        self.form.setObjectName("Panel")
        self.grid = QGridLayout(self.form)
        self.grid.setSpacing(15)
        self.grid.setColumnStretch(1, 1)
        row = 0

        lbl_trans = QLabel("Протокол транспорта")
        lbl_trans.setStyleSheet(f"color: {C_TEXT_DIM}; font-weight: bold;")
        self.combo_trans = QComboBox()
        self.combo_trans.addItems(["telegram", "vk"])
        self.combo_trans.setCurrentText(getattr(config, 'transport_type', 'telegram'))
        self.combo_trans.setStyleSheet("background-color: #333;")
        self.combo_trans.currentTextChanged.connect(self.toggle_fields)

        self.grid.addWidget(lbl_trans, row, 0)
        self.grid.addWidget(self.combo_trans, row, 1, 1, 2)
        row += 1

        self.tg_widgets = []
        self.vk_widgets = []

        # TG Fields
        self.inp_api_id = self.add_secret_field(row, "TG API ID", config.api_id, self.tg_widgets)
        row += 1
        self.inp_api_hash = self.add_secret_field(row, "TG API Hash", config.api_hash, self.tg_widgets)
        row += 1
        self.inp_bot_token = self.add_secret_field(row, "TG Bot Token", config.bot_token, self.tg_widgets)
        row += 1
        self.inp_chat_id = self.add_field(row, "TG Chat ID", config.chat_id, self.tg_widgets)
        row += 1

        # VK Fields
        vk_token_val = getattr(config, 'vk_token', '')

        # lbl_token_info = QLabel(" ИЛИ Токен (Рекомендуется, обходит 2FA/Блок)")
        # lbl_token_info.setStyleSheet("color: #00E676; font-size: 11px;")
        # self.grid.addWidget(lbl_token_info, row, 1, 1, 2)
        # self.vk_widgets.append(lbl_token_info)
        # row += 1

        self.inp_vk_token = self.add_secret_field(row, "VK Access Token", vk_token_val, self.vk_widgets)
        row += 1

        lbl_or = QLabel("--- Логин---")
        lbl_or.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(lbl_or, row, 1, 1, 2)
        self.vk_widgets.append(lbl_or)
        row += 1

        self.inp_vk_login = self.add_secret_field(row, "VK Логин", config.vk_login, self.vk_widgets)
        row += 1
        self.inp_vk_peer = self.add_secret_field(row, "VK Peer ID (второй участник)", config.vk_peer_id,
                                                 self.vk_widgets)
        row += 1
        self.inp_vk_app = self.add_secret_field(row, "VK App ID", config.vk_app_id, self.vk_widgets)
        row += 1

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #333;")
        self.grid.addWidget(sep, row, 0, 1, 3)
        row += 1

        self.inp_tap = self.add_field(row, "TAP Интерфейс", config.tap_interface_name)
        row += 1
        self.inp_key = self.add_secret_field(row, "Ключ", config.encryption_key)
        row += 1

        self.chk_comp = QCheckBox("Включить сжатие GZIP")
        self.chk_comp.setChecked(config.compression_enabled)
        self.chk_comp.setStyleSheet(f"color: {C_TEXT}; font-size: 14px; margin-top: 10px;")
        self.grid.addWidget(self.chk_comp, row, 0, 1, 3)
        row += 1

        btn_save = QPushButton("💾 Сохранить и Применить")
        btn_save.setObjectName("ActionBtn")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self.save)

        l.addWidget(self.form)
        l.addSpacing(10)
        l.addWidget(btn_save)
        l.addStretch()
        self.toggle_fields(self.combo_trans.currentText())

    def add_field(self, row, label_text, value, group_list=None):
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"color: {C_TEXT_DIM}; font-weight: bold;")
        inp = QLineEdit(str(value))
        self.grid.addWidget(lbl, row, 0)
        self.grid.addWidget(inp, row, 1, 1, 2)
        if group_list is not None:
            group_list.append(lbl)
            group_list.append(inp)
        return inp

    def add_secret_field(self, row, label_text, value, group_list=None):
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"color: {C_TEXT_DIM}; font-weight: bold;")
        inp = QLineEdit(str(value))
        inp.setEchoMode(QLineEdit.EchoMode.Password)
        btn_eye = QPushButton("👁")
        btn_eye.setCheckable(True)
        btn_eye.setFixedSize(40, 36)
        btn_eye.setStyleSheet(
            "QPushButton { background-color: #2C2C2C; border: 1px solid #444; } QPushButton:checked { background-color: #00E5FF; color: black; }")

        def toggle(c): inp.setEchoMode(QLineEdit.EchoMode.Normal if c else QLineEdit.EchoMode.Password)

        btn_eye.toggled.connect(toggle)
        self.grid.addWidget(lbl, row, 0)
        self.grid.addWidget(inp, row, 1)
        self.grid.addWidget(btn_eye, row, 2)
        if group_list is not None:
            group_list.append(lbl)
            group_list.append(inp)
            group_list.append(btn_eye)
        return inp

    def toggle_fields(self, text):
        is_vk = (text == 'vk')
        for w in self.tg_widgets: w.setVisible(not is_vk)
        for w in self.vk_widgets: w.setVisible(is_vk)

    def save(self):
        try:
            config.transport_type = self.combo_trans.currentText()
            config.tap_interface_name = self.inp_tap.text()
            config.encryption_key = self.inp_key.text()
            config.compression_enabled = self.chk_comp.isChecked()

            if config.transport_type == 'telegram':
                config.api_id = int(self.inp_api_id.text())
                config.api_hash = self.inp_api_hash.text()
                config.bot_token = self.inp_bot_token.text()
                config.chat_id = self.inp_chat_id.text()
            else:
                config.vk_token = self.inp_vk_token.text()  # Сохраняем токен
                config.vk_login = self.inp_vk_login.text()
                config.vk_peer_id = self.inp_vk_peer.text()
                try:
                    config.vk_app_id = int(self.inp_vk_app.text())
                except:
                    config.vk_app_id = 6121396

            if len(config.encryption_key.encode()) != 32:
                print("⚠️ Ключ должен быть 32 байта!")
                return

            config.save_to_file()

            btn = self.sender()
            if btn:
                btn.setText("✅ Сохранено!")
                QTimer.singleShot(1500, lambda: btn.setText("💾 Сохранить и Применить"))

            print(f"✅ Настройки сохранены. Режим: {config.transport_type}")

        except Exception as e:
            print(f"❌ Ошибка сохранения: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TeleVK VPN")
        self.resize(1100, 750)
        self.setStyleSheet(STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        sidebar = QFrame(objectName="Sidebar")
        sidebar.setFixedWidth(220)
        side_l = QVBoxLayout(sidebar)
        side_l.setContentsMargins(0, 20, 0, 20)

        logo = QLabel("TeleVK VPN")
        logo.setStyleSheet("font-size: 20px; font-weight: 900; color: white; padding: 20px; margin-bottom: 20px;")
        side_l.addWidget(logo)

        self.btn_dash = QPushButton("  📊  Обзор сети")
        self.btn_dash.setObjectName("MenuBtn")
        self.btn_dash.setCheckable(True)
        self.btn_dash.setChecked(True)

        self.btn_sett = QPushButton("  ⚙️  Настройки")
        self.btn_sett.setObjectName("MenuBtn")
        self.btn_sett.setCheckable(True)

        self.btn_mode_switch = QPushButton("  🔄  Сменить режим")
        self.btn_mode_switch.setObjectName("MenuBtn")
        self.btn_mode_switch.setStyleSheet("color: #FFA726;")

        side_l.addWidget(self.btn_dash)
        side_l.addWidget(self.btn_sett)
        side_l.addStretch()
        side_l.addWidget(self.btn_mode_switch)
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.dash = Dashboard(self)
        from gui import SettingsPage
        self.sett = SettingsPage()
        self.stack.addWidget(self.dash)
        self.stack.addWidget(self.sett)
        layout.addWidget(self.stack)

        # Events
        self.btn_dash.clicked.connect(lambda: self.switch_page(0))
        self.btn_sett.clicked.connect(lambda: self.switch_page(1))
        self.btn_mode_switch.clicked.connect(self.switch_mode)

        self.worker = None
        self.is_running = False
        self.current_mode = "client"
        self.start_time = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)
        self.data_history = deque([0] * 60, maxlen=60)
        self.last_pkts = 0
        self.coef = 25

    def switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
        self.btn_dash.setChecked(idx == 0)
        self.btn_sett.setChecked(idx == 1)

    def switch_mode(self):
        if self.is_running: return
        self.current_mode = "server" if self.current_mode == "client" else "client"
        txt = "🖥️ РЕЖИМ СЕРВЕРА" if self.current_mode == "server" else "💻 РЕЖИМ КЛИЕНТА"
        self.dash.lbl_mode_status.setText(txt)
        self.dash.lbl_footer_info.setText(
            f"Локальный IP: {config.get_ip_for_mode(self.current_mode)}")

    def toggle_vpn(self):
        if not self.is_running:
            self.start_vpn()
        else:
            self.stop_vpn()

    def start_vpn(self):
        self.worker = VPNWorker(self.current_mode)
        self.worker.log_signal.connect(self.append_log)
        self.worker.status_signal.connect(self.on_status)
        self.worker.traffic_signal.connect(self.on_traffic)
        self.worker.auth_request.connect(self.handle_auth)
        self.worker.start()

        self.dash.btn_toggle.setText("Остановить")
        self.dash.btn_toggle.setProperty("state", "stop")
        self.dash.btn_toggle.style().polish(self.dash.btn_toggle)
        self.is_running = True
        self.start_time = time.time()
        self.timer.start(1000)

    def stop_vpn(self):
        if self.worker: self.worker.stop()
        self.timer.stop()
        self.dash.btn_toggle.setText("Запуск туннеля")
        self.dash.btn_toggle.setProperty("state", "normal")
        self.dash.btn_toggle.style().polish(self.dash.btn_toggle)
        self.dash.lbl_status_dot.setText("● ОТКЛЮЧЕНО")
        self.dash.lbl_status_dot.setStyleSheet("color: #8B949E; font-size: 11px; font-weight: bold;")
        self.is_running = False

    def on_status(self, run):
        if run:
            self.dash.lbl_status_dot.setText("● ПОДКЛЮЧЕНО")
            self.dash.lbl_status_dot.setStyleSheet(f"color: {C_ACCENT}; font-size: 11px; font-weight: bold;")
        else:
            self.stop_vpn()

    def on_traffic(self):
        pass

    def update_stats(self):
        if not self.is_running: return
        elapsed = int(time.time() - self.start_time)
        m, s = divmod(elapsed, 60)
        h, m = divmod(m, 60)
        self.dash.card_time.update_data(f"{h:02}:{m:02}:{s:02}", "Время сессии")

        pkts = self.worker.get_stats()
        diff = pkts - self.last_pkts
        self.last_pkts = pkts

        # Расчет скорости (примерный, считаем 1 пакет ~ 1 КБ для визуализации)
        speed_kbs = self.coef * diff * 1.2
        total_mb = (pkts * 1.2) / 1024

        self.dash.card_speed.update_data(f"{speed_kbs:.1f} KB/s", "Текущая скорость")

        self.dash.card_sent.update_data(f"{total_mb:.2f} MB", "Сжатых данных")
        #self.dash.card_recv.update_data(int(recv_kb), f"Всего: {pkts * 0.4 / 1024:.1f} MB")
        self.dash.card_ping.update_data(f"{25 + (diff % 10)}", "мс (Latency)")

        self.data_history.append(diff)
        self.dash.curve.setData(list(self.data_history))

    def append_log(self, text, level):
        color = "#FF5252" if level >= logging.ERROR else "#E1E1E1"
        self.dash.log_view.append(
            f'<span style="color:#666">[{time.strftime("%H:%M:%S")}]</span> <span style="color:{color}">{text}</span>')

    def handle_auth(self, r_type, event, payload):
        # ... (Код handle_auth остается таким же, как в вашем gui.py)
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Авторизация", f"Введите {r_type}:")
        self.worker.auth_result = text if ok else None
        event.set()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
