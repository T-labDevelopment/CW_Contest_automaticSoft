"""Windows-first two-window GUI. All RF transmission is intentionally disabled."""
from __future__ import annotations

from datetime import datetime
import os
import sqlite3
from queue import Empty, Queue
from threading import Thread
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import ALLOWED_BANDS, JST, LogValidationError, QSO
from .desktop_data import DesktopSettings, DesktopStorage, summarize_live_log
from .contest_radio import RadioState
from .radio_monitor import RadioMonitor, RadioUpdate
from .icom_models import MODELS, BY_NAME
from .receive_monitor import AudioDecodeMonitor, CandidateTracker, ReceiveUpdate, decode_file
from .candidate_selection import evaluate_candidates

CONTEST_LABELS = {"ALL_JA": "ALL JA", "ACAG": "全市全郡"}
LABEL_TO_CONTEST = {v: k for k, v in CONTEST_LABELS.items()}


class DesktopApp:
    def __init__(self, root: tk.Tk, storage: DesktopStorage | None = None):
        self.root = root
        self.storage = storage or DesktopStorage()
        self.settings: DesktopSettings | None = None
        self.log_window: tk.Toplevel | None = None
        self.tree: ttk.Treeview | None = None
        self.log_summary_var = tk.StringVar(value="ログ待機中")
        self.notice_var = tk.StringVar(value="送信禁止 / 単一トーン受信は実験版。QSOは手動確定のみ")
        self._log_stamp: tuple | None = None
        self._closing = False
        self.radio_state: RadioState | None = None
        self.radio_monitor: RadioMonitor | None = None
        self.radio_events: Queue[RadioUpdate] = Queue()
        self.selected_station: str | None = None  # stale candidates invalidated on band changes
        self.candidate_tracker = CandidateTracker()
        self.rx_monitor: AudioDecodeMonitor | None = None
        self.rx_events: Queue[ReceiveUpdate] = Queue()
        self.rx_var = tk.StringVar(value="USB CW受信停止中（送信禁止）")
        self.rx_text_var = tk.StringVar(value="最後の復号: --")
        self.audio_device_var = tk.StringVar(value="")
        self.audio_tone_var = tk.StringVar(value="700")
        self.candidate_tree: ttk.Treeview | None = None
        self._audio_devices: dict[str, int] = {}
        self.radio_var = tk.StringVar(value="CI-V未接続（受信状態不明）")
        self.worked_var = tk.StringVar(value="交信済み局判定: コンテスト期間未設定")
        self.civ_var = tk.StringVar()
        self.radio_model_var = tk.StringVar(value="IC-7300")
        self.civ_transport_var = tk.StringVar(value="USB")
        self.address_override_var = tk.StringVar()
        self.radio_ident_var = tk.StringVar(value="無線機未確認（送信禁止）")
        self.verified_radio_model: str | None = None
        self.start_var = tk.StringVar()
        self.end_var = tk.StringVar()
        self.call_var = tk.StringVar()
        self.contest_var = tk.StringVar(value=CONTEST_LABELS["ALL_JA"])
        self.nr_var = tk.StringVar()
        self.band_var = tk.StringVar(value="7")
        self.other_call_var = tk.StringVar()
        self.other_nr_var = tk.StringVar()
        self.other_rst_var = tk.StringVar(value="599")
        self._configure_root()
        self._create_settings_ui()
        try:
            loaded = self.storage.load_settings()
            # An empty form is intentional for new users; it must not invent a callsign.
            if loaded.station_callsign:
                self.settings = loaded
                self.call_var.set(loaded.station_callsign)
                self.contest_var.set(CONTEST_LABELS[loaded.contest_id])
                self.nr_var.set(loaded.sent_nr)
                self.band_var.set(loaded.band)
                self.start_var.set(loaded.contest_start_jst)
                self.end_var.set(loaded.contest_end_jst)
                self.civ_var.set(loaded.civ_port)
                self.radio_model_var.set(loaded.radio_model)
                self.civ_transport_var.set(loaded.civ_transport)
                self.address_override_var.set(loaded.civ_address_override)
                self.audio_tone_var.set(str(loaded.cw_tone_hz))
                self.audio_device_var.set(str(loaded.audio_device) if loaded.audio_device >= 0 else "")
        except LogValidationError as exc:
            messagebox.showwarning("設定読み込み", str(exc), parent=self.root)
        self._refresh_band_choices()
        self._update_transport_buttons()
        self.open_log_window()
        self.root.after(1000, self._poll_log)
        self.root.after(200, self._poll_radio_events)
        self.root.after(300, self._poll_rx_events)

    def _configure_root(self):
        self.root.title("ICOM CWコンテスト - 設定")
        self.root.geometry("680x875+60+70")
        self.root.minsize(610, 795)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            ttk.Style(self.root).theme_use("vista" if os.name == "nt" else "clam")
        except tk.TclError:
            pass

    def _create_settings_ui(self):
        wrapper = ttk.Frame(self.root, padding=16)
        wrapper.pack(fill="both", expand=True)
        ttk.Label(wrapper, text="ICOM / CWコンテスト", font=("Yu Gothic UI" if os.name == "nt" else "TkDefaultFont", 15, "bold")).pack(anchor="w")
        ttk.Label(wrapper, text="自局設定（設定値は次回起動時も保持）").pack(anchor="w", pady=(3, 10))
        form = ttk.LabelFrame(wrapper, text="送信局・コンテスト情報", padding=12)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        for i, title in enumerate(("自局コールサイン", "コンテスト", "送信ナンバー", "手動バンド (MHz)",
                                    "開催開始 (JST)", "開催終了 (JST)")):
            ttk.Label(form, text=title).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Entry(form, textvariable=self.call_var).grid(row=0, column=1, sticky="ew", pady=6)
        self.contest_box = ttk.Combobox(form, textvariable=self.contest_var, state="readonly", values=list(LABEL_TO_CONTEST))
        self.contest_box.grid(row=1, column=1, sticky="ew", pady=6)
        self.contest_box.bind("<<ComboboxSelected>>", lambda event: self._refresh_band_choices())
        ttk.Entry(form, textvariable=self.nr_var).grid(row=2, column=1, sticky="ew", pady=6)
        self.band_box = ttk.Combobox(form, textvariable=self.band_var, state="readonly")
        self.band_box.grid(row=3, column=1, sticky="ew", pady=6)
        ttk.Entry(form, textvariable=self.start_var).grid(row=4, column=1, sticky="ew", pady=6)
        ttk.Entry(form, textvariable=self.end_var).grid(row=5, column=1, sticky="ew", pady=6)
        ttk.Label(form, text="日時例：2026-04-25 21:00（空欄では自動除外を行いません）", foreground="#505c6b").grid(row=6, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Label(form, text="送信NR例：ALL JA=11M / 全市全郡=100116M（RST不要）", foreground="#505c6b").grid(row=7, column=0, columnspan=2, sticky="w", pady=(3, 0))
        radio_frame = ttk.LabelFrame(wrapper, text="ICOM CI-V 接続（無線機確認は19 00 / 送信禁止）", padding=9)
        radio_frame.pack(fill="x", pady=(12, 0))
        model_line = ttk.Frame(radio_frame)
        model_line.pack(fill="x")
        ttk.Label(model_line, text="想定無線機").pack(side="left", padx=(0, 8))
        self.radio_model_box = ttk.Combobox(model_line, textvariable=self.radio_model_var,
                                            state="readonly", width=22,
                                            values=[x.name for x in MODELS])
        self.radio_model_box.pack(side="left")
        self.radio_model_box.bind("<<ComboboxSelected>>", self._on_radio_model_change)
        ttk.Label(model_line, text="アドレス変更時").pack(side="left", padx=(12, 5))
        ttk.Entry(model_line, textvariable=self.address_override_var, width=5).pack(side="left")
        transport_line = ttk.Frame(radio_frame)
        transport_line.pack(fill="x", pady=(6, 0))
        ttk.Label(transport_line, text="接続方式").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(transport_line, text="USB", variable=self.civ_transport_var,
                        value="USB").pack(side="left")
        self.bt_button = ttk.Radiobutton(transport_line, text="Bluetooth SPP", variable=self.civ_transport_var,
                                         value="Bluetooth")
        self.bt_button.pack(side="left", padx=(14, 0))
        ttk.Label(transport_line, text="Wi-Fiは標準対象外", foreground="#505c6b").pack(side="left", padx=(15, 0))
        line = ttk.Frame(radio_frame)
        line.pack(fill="x", pady=(7, 0))
        ttk.Label(line, text="COMポート").pack(side="left", padx=(0, 7))
        ttk.Entry(line, textvariable=self.civ_var, width=11).pack(side="left", padx=(0, 9))
        ttk.Button(line, text="無線機確認", command=self._connect_radio).pack(side="left")
        ttk.Button(line, text="切断", command=self._disconnect_radio).pack(side="left", padx=(8, 0))
        ttk.Label(radio_frame, textvariable=self.radio_ident_var).pack(anchor="w", pady=(7, 2))
        ttk.Label(radio_frame, textvariable=self.radio_var).pack(anchor="w", pady=(2, 3))
        ttk.Label(radio_frame, textvariable=self.worked_var).pack(anchor="w")
        audio = ttk.LabelFrame(wrapper, text="USB Audio / CW受信モニタ（実験版・受信専用）", padding=9)
        audio.pack(fill="x", pady=(12, 0))
        audio_line = ttk.Frame(audio)
        audio_line.pack(fill="x")
        ttk.Label(audio_line, text="入力デバイス").pack(side="left")
        self.audio_box = ttk.Combobox(audio_line, textvariable=self.audio_device_var, width=28)
        self.audio_box.pack(side="left", fill="x", expand=True, padx=(5, 6))
        ttk.Button(audio_line, text="一覧取得", command=self._refresh_audio_devices).pack(side="left")
        tone_line = ttk.Frame(audio)
        tone_line.pack(fill="x", pady=(7, 0))
        ttk.Label(tone_line, text="CW音程(Hz)").pack(side="left")
        ttk.Entry(tone_line, textvariable=self.audio_tone_var, width=7).pack(side="left", padx=(5, 12))
        ttk.Button(tone_line, text="受信開始", command=self._start_rx).pack(side="left")
        ttk.Button(tone_line, text="停止", command=self._stop_rx).pack(side="left", padx=(6, 0))
        ttk.Button(tone_line, text="WAV試験", command=self._open_rx_wav).pack(side="left", padx=(6, 0))
        ttk.Label(audio, textvariable=self.rx_var).pack(anchor="w", pady=(6, 0))
        ttk.Label(audio, textvariable=self.rx_text_var, wraplength=560).pack(anchor="w", pady=(4, 0))
        buttons = ttk.Frame(wrapper)
        buttons.pack(fill="x", pady=(14, 8))
        ttk.Button(buttons, text="設定を保存", command=self._on_save).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="交信ログを表示", command=self.open_log_window).pack(side="left")
        ttk.Label(wrapper, textvariable=self.notice_var, foreground="#8a4b00", wraplength=520).pack(anchor="w", pady=(12, 3))
        ttk.Label(wrapper, text="本GUIは受信・候補提示・手動ログ登録まで。自動送信とDeepCW接続は未実装。", foreground="#505c6b").pack(anchor="w")

    def _update_transport_buttons(self):
        model = BY_NAME.get(self.radio_model_var.get())
        supports_bt = bool(model and model.bluetooth_spp_civ)
        if not supports_bt:
            self.civ_transport_var.set("USB")
        self.bt_button.configure(state="normal" if supports_bt else "disabled")

    def _on_radio_model_change(self, _event=None):
        self._disconnect_radio()
        self._update_transport_buttons()
        profile = BY_NAME.get(self.radio_model_var.get())
        self.radio_ident_var.set(f"{profile.name if profile else '不明'}：未確認（識別コードを取得してください）")
        self.notice_var.set("機種変更：設定を保存後、無線機確認でCI-V 19 00を実行してください。")

    def _audio_device_id(self) -> int:
        value = self.audio_device_var.get().strip()
        if value in self._audio_devices:
            return self._audio_devices[value]
        if not value:
            return -1
        try:
            return int(value.split(":", 1)[0])
        except ValueError as exc:
            raise LogValidationError("USB Audioデバイスを一覧から選択してください。") from exc

    def _refresh_audio_devices(self):
        try:
            from .audio_usb import list_devices
            devices = list_devices()
        except Exception as exc:
            messagebox.showerror("音声デバイス", str(exc), parent=self.root)
            return
        self._audio_devices = {f"{i}: {name}": i for i, name, _ in devices}
        self.audio_box.configure(values=list(self._audio_devices))
        selected = self._audio_device_id()
        for name, number in self._audio_devices.items():
            if selected == number:
                self.audio_device_var.set(name)
                break
        self.rx_var.set(f"入力デバイス {len(devices)} 件（無線機のUSB Audioを選択）")

    def _start_rx(self):
        try:
            device, tone = self._audio_device_id(), int(self.audio_tone_var.get())
            if self.settings is None:
                raise LogValidationError("先に自局設定を保存してください。")
            if device != self.settings.audio_device or tone != self.settings.cw_tone_hz:
                raise LogValidationError("選択した音声デバイスと音程を設定保存してから開始してください。")
            receiver = AudioDecodeMonitor(device, tone, self.rx_events)
        except (ValueError, LogValidationError) as exc:
            messagebox.showerror("CW受信開始", str(exc), parent=self.root)
            return
        self._stop_rx()
        self.rx_events = Queue()
        receiver.events = self.rx_events
        self.rx_monitor = receiver
        self.rx_var.set("USB音声を受信中（8秒窓・4秒周期・送信なし）")
        receiver.start()

    def _stop_rx(self):
        if self.rx_monitor is not None:
            self.rx_monitor.stop()
            self.rx_monitor = None
        self.rx_var.set("USB CW受信停止中（送信禁止）")

    def _open_rx_wav(self):
        try:
            tone = int(self.audio_tone_var.get())
            if not 400 <= tone <= 1100:
                raise ValueError("トーン周波数は400～1100Hzで指定してください。")
        except ValueError as exc:
            messagebox.showerror("WAV試験", str(exc), parent=self.root)
            return
        filename = filedialog.askopenfilename(parent=self.root, title="CW WAVを選択",
                                              filetypes=[("WAV音声", "*.wav")])
        if not filename:
            return
        self.rx_var.set(f"WAV復号中：{Path(filename).name}")
        events = self.rx_events
        def job():
            try:
                events.put(decode_file(filename, tone))
            except Exception as exc:
                events.put(ReceiveUpdate(error=f"WAV読取失敗: {exc}"))
        Thread(target=job, daemon=True, name="CW-WAV-TEST").start()

    def _poll_rx_events(self):
        if self._closing:
            return
        try:
            while True:
                result = self.rx_events.get_nowait()
                if result.error:
                    self.rx_var.set(result.error)
                    if "停止" in result.error or "オーバーフロー" in result.error:
                        self.candidate_tracker.clear()
                else:
                    self.rx_text_var.set(f"{result.origin}復号: {result.text or '--'}  "
                                         f"/ {result.wpm or '--'} WPM")
                    self.candidate_tracker.observe(result.text)
                    self.rx_var.set("受信候補を更新（オペレーター確認必須 / 送信禁止）")
                self._refresh_candidates()
        except Empty:
            pass
        self.root.after(300, self._poll_rx_events)

    def _refresh_candidates(self):
        tree = self.candidate_tree
        if tree is None or not tree.winfo_exists():
            return
        for child in tree.get_children():
            tree.delete(child)
        for call, count in self.candidate_tracker.candidates():
            if self.settings is None:
                status = "自局設定未保存"
            else:
                try:
                    status = evaluate_candidates(self.storage, self.settings, self.radio_state,
                                                 [call])[0].reason
                except Exception as exc:
                    status = f"判定エラー: {exc}"
            tree.insert("", "end", values=(call, count, status))

    def _choose_candidate(self, _event=None):
        if self.candidate_tree is None:
            return
        selection = self.candidate_tree.selection()
        if selection:
            values = self.candidate_tree.item(selection[0])["values"]
            if values:
                self.other_call_var.set(str(values[0]))
                self.notice_var.set("復号候補を手動登録欄へ転記。交信成立・NRを確認してから登録してください。")

    def _refresh_band_choices(self):
        contest_id = LABEL_TO_CONTEST.get(self.contest_var.get(), "ALL_JA")
        bands = sorted(ALLOWED_BANDS[contest_id], key=float)
        self.band_box.configure(values=bands)
        if self.band_var.get() not in bands:
            self.band_var.set("7" if "7" in bands else bands[0])

    def _read_form(self) -> DesktopSettings:
        contest_id = LABEL_TO_CONTEST.get(self.contest_var.get(), "")
        return DesktopSettings(self.call_var.get(), contest_id, self.nr_var.get(),
                               self.band_var.get(), self.start_var.get(),
                               self.end_var.get(), self.civ_var.get(),
                               self._audio_device_id(), int(self.audio_tone_var.get()),
                               self.radio_model_var.get(), self.civ_transport_var.get(),
                               self.address_override_var.get()).checked()

    def _on_save(self):
        try:
            value = self.storage.save_settings(self._read_form())
        except (OSError, LogValidationError, TypeError, ValueError) as exc:
            messagebox.showerror("設定エラー", str(exc), parent=self.root)
            return
        previous = self.settings
        self.settings = value
        self.call_var.set(value.station_callsign)
        self.nr_var.set(value.sent_nr)
        self.start_var.set(value.contest_start_jst)
        self.end_var.set(value.contest_end_jst)
        self.civ_var.set(value.civ_port)
        self.radio_model_var.set(value.radio_model)
        self.civ_transport_var.set(value.civ_transport)
        self.address_override_var.set(value.civ_address_override)
        self._update_transport_buttons()
        self.audio_tone_var.set(str(value.cw_tone_hz))
        self._update_worked_status()
        self.notice_var.set(f"設定保存済み: {value.station_callsign} / {value.sent_nr} ・送信禁止")
        if previous != value:
            self._stop_rx()
            self.candidate_tracker.clear()
            self._refresh_candidates()
            self._disconnect_radio()  # invalidate the old profile/port context
            self._log_stamp = None
            self._refresh_log(force=True)

    def _connect_radio(self):
        try:
            settings = self._read_form()
            if self.settings != settings:
                raise LogValidationError("設定を保存してからCI-Vへ接続してください。")
            if not settings.civ_port:
                raise LogValidationError("COMポートを指定してください。")
        except LogValidationError as exc:
            messagebox.showerror("CI-V接続", str(exc), parent=self.root)
            return
        self._disconnect_radio()
        self.radio_events = Queue()  # old worker events cannot revive stale state
        self.radio_monitor = RadioMonitor(settings.civ_port, self.radio_events,
                                          model=settings.radio_model,
                                          transport=settings.civ_transport,
                                          address_override=settings.civ_address_override)
        self.radio_ident_var.set("19 00 無線機識別を実行中…")
        self.radio_var.set(f"{settings.civ_port} 接続確認中…（送信禁止）")
        self.radio_monitor.start()

    def _disconnect_radio(self):
        if self.radio_monitor is not None:
            self.radio_monitor.stop()
            self.radio_monitor = None
        self.radio_state = None
        self.verified_radio_model = None
        self.radio_ident_var.set("無線機未確認（送信禁止）")
        self.selected_station = None
        self.candidate_tracker.clear()
        if self.rx_monitor is not None:
            self.rx_monitor.invalidate()
        self._refresh_candidates()
        self.radio_var.set("CI-V未接続（受信状態不明 / 自動送信禁止）")
        self._update_worked_status()

    def _poll_radio_events(self):
        if self._closing:
            return
        try:
            while True:
                update = self.radio_events.get_nowait()
                previous = self.radio_state
                if update.identified_model and update.detected_id is not None:
                    self.verified_radio_model = update.identified_model
                    self.radio_ident_var.set(f"確認済み: {update.identified_model} / ID {update.detected_id:02X}h / {self.civ_transport_var.get()}")
                if update.state is None and not update.error and update.identified_model:
                    continue  # recognition handshake, no frequency yet
                self.radio_state = update.state
                if update.state is not None:
                    state = update.state
                    if previous and (previous.frequency_hz != state.frequency_hz or previous.mode != state.mode):
                        self.selected_station = None
                        self.candidate_tracker.clear()
                        if self.rx_monitor is not None:
                            self.rx_monitor.invalidate()
                        self._refresh_candidates()
                        self.notice_var.set("周波数またはモード変更：旧受信候補を破棄しました（送信禁止）")
                    warning = "CWコンテスト帯域内" if state.in_cw_contest_segment else "CWコンテスト帯域外"
                    if state.edge_warning:
                        warning = "帯域境界付近・要確認"
                    if not state.cw_mode:
                        warning = "CW以外・対象外"
                    self.radio_var.set(f"{self.verified_radio_model or 'ICOM'} {state.frequency_label}  {state.mode}  "
                                       f"{state.band or '帯域不明'}MHz / {warning}")
                else:
                    self.verified_radio_model = None
                    self.radio_ident_var.set("無線機確認失敗・切断（送信禁止）")
                    self.selected_station = None
                    self.candidate_tracker.clear()
                    if self.rx_monitor is not None:
                        self.rx_monitor.invalidate()
                    self._refresh_candidates()
                    self.radio_var.set(update.error or "CI-V取得失敗（自動送信禁止）")
                self._update_worked_status()
        except Empty:
            pass
        self.root.after(200, self._poll_radio_events)

    def _update_worked_status(self):
        if self.settings is None:
            self.worked_var.set("自局情報未設定")
            return
        if self.settings.contest_window is None:
            self.worked_var.set("開催期間未設定：交信済み局の自動除外は停止")
            return
        state = self.radio_state
        if state is None or state.band is None:
            self.worked_var.set("CI-V情報なし：バンド別自動判定停止")
            return
        if not state.eligible_for(self.settings.contest_id):
            self.worked_var.set("CWコンテスト帯域外・モード不一致：自動判定停止")
            return
        try:
            count = self.storage.worked_count(self.settings, state.band)
            self.worked_var.set(f"{state.band}MHzの交信済み局: {count}局（同一バンドで除外）")
        except (OSError, LogValidationError, sqlite3.DatabaseError) as exc:
            self.worked_var.set(f"ログ照合不可：{exc}")

    def open_log_window(self):
        if self._closing:
            return
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.log_window = window
        window.title("交信ログ（自動更新） - ICOM CW")
        window.geometry("1050x620+675+70")
        window.minsize(750, 470)
        window.protocol("WM_DELETE_WINDOW", self._close_log_window)
        outer = ttk.Frame(window, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="交信ログ（内部SQLite + CSV同期・1秒ごと）", font=("Yu Gothic UI" if os.name == "nt" else "TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(outer, textvariable=self.log_summary_var).pack(anchor="w", pady=(4, 8))
        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("time", "freq", "band", "call", "sent", "received", "rst", "status")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        self.tree = tree
        for key, label, width in (("time", "時刻 (JST)", 160),
                                  ("freq", "周波数 (MHz)", 110), ("band", "バンド", 65),
                                  ("call", "相手コール", 115), ("sent", "送信NR", 100),
                                  ("received", "受信NR", 100), ("rst", "RST", 70),
                                  ("status", "状態", 90)):
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=60, stretch=key == "time")
        tree.tag_configure("duplicate", foreground="#9a601d")
        tree.tag_configure("incomplete", foreground="#9b3b3b")
        sy = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        sx = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        candidates = ttk.LabelFrame(outer, text="CW受信候補（候補をダブルクリック→手動登録欄へ転記、QSO自動成立ではありません）", padding=7)
        candidates.pack(fill="x", pady=(8, 0))
        self.candidate_tree = ttk.Treeview(candidates, columns=("call", "count", "status"),
                                           show="headings", height=3)
        for key, title, width in (("call", "候補局", 150), ("count", "検出回数", 80),
                                  ("status", "選択判定", 500)):
            self.candidate_tree.heading(key, text=title)
            self.candidate_tree.column(key, width=width, stretch=key=="status")
        self.candidate_tree.pack(fill="x")
        self.candidate_tree.bind("<Double-1>", self._choose_candidate)
        self._refresh_candidates()
        manual = ttk.LabelFrame(outer, text="交信成立を確認したQSOを手動登録（受信内容からの自動確定は行いません）", padding=9)
        manual.pack(fill="x", pady=(10, 0))
        ttk.Label(manual, text="相手局").pack(side="left")
        ttk.Entry(manual, textvariable=self.other_call_var, width=14).pack(side="left", padx=(4, 12))
        ttk.Label(manual, text="受信NR").pack(side="left")
        ttk.Entry(manual, textvariable=self.other_nr_var, width=12).pack(side="left", padx=(4, 12))
        ttk.Label(manual, text="RST").pack(side="left")
        ttk.Entry(manual, textvariable=self.other_rst_var, width=5).pack(side="left", padx=(4, 12))
        ttk.Button(manual, text="QSOを登録", command=self._add_qso).pack(side="left")
        control = ttk.Frame(outer)
        control.pack(fill="x", pady=(10, 0))
        ttk.Button(control, text="CSVの保存場所を開く", command=self._open_folder).pack(side="left")
        ttk.Label(control, text="※「重複候補」は表示用の簡易判定。公式得点ではありません。", foreground="#505c6b").pack(side="left", padx=12)
        self._log_stamp = None
        self._refresh_log(force=True)

    def _close_log_window(self):
        if self.log_window is not None:
            self.log_window.destroy()
        self.log_window = None
        self.tree = None
        self.candidate_tree = None

    def _refresh_log(self, *, force: bool = False):
        if self.log_window is None or not self.log_window.winfo_exists() or self.tree is None:
            return
        if self.settings is None:
            self.log_summary_var.set("設定画面で自局コールサイン・コンテストナンバーを保存してください。")
            for item in self.tree.get_children():
                self.tree.delete(item)
            return
        path = self.storage.log_path(self.settings)
        try:
            records = self.storage.list_records(self.settings)
            qsos = [r.qso for r in records]
            rows = summarize_live_log(qsos)
        except (OSError, LogValidationError, ValueError, sqlite3.DatabaseError) as exc:
            self.log_summary_var.set(f"ログ読み込みエラー: {exc}")
            return
        self._log_stamp = None  # SQLite is monitored; no CSV mtime cache
        existing_selection = self.tree.selection()
        selected_index = self.tree.index(existing_selection[0]) if existing_selection else -1
        for item in self.tree.get_children():
            self.tree.delete(item)
        for record, (qso, status) in zip(records, rows):
            rowtag = "duplicate" if status == "重複候補" else "incomplete" if status == "未完了" else ""
            self.tree.insert("", "end", values=(
                qso.time_jst.strftime("%Y-%m-%d %H:%M:%S"),
                f"{record.frequency_hz / 1e6:.6f}" if record.frequency_hz else "--", qso.band,
                qso.callsign, qso.sent_nr, qso.rcvd_nr,
                f"{qso.sent_rst}/{qso.rcvd_rst}", status,
            ), tags=(rowtag,) if rowtag else ())
        if selected_index >= 0 and selected_index < len(rows):
            self.tree.selection_set(self.tree.get_children()[selected_index])
        complete = sum(q.completed for q in qsos)
        duplicates = sum(status == "重複候補" for _, status in rows)
        self.log_summary_var.set(
            f"自局 {self.settings.station_callsign}　{CONTEST_LABELS[self.settings.contest_id]}　"
            f"計 {len(qsos)} 件（完了 {complete} / 重複候補 {duplicates}）　"
            f"保存先: {path.name}"
        )

    def _poll_log(self):
        if self._closing:
            return
        self._refresh_log()
        self._update_worked_status()
        self.root.after(1000, self._poll_log)

    def _add_qso(self):
        if self.settings is None:
            messagebox.showerror("設定未保存", "先に自局設定を保存してください。", parent=self.log_window)
            return
        try:
            live = self.radio_state
            if live is not None and not live.eligible_for(self.settings.contest_id):
                raise LogValidationError("CI-V周波数またはモードがCWコンテスト条件外です。登録を中止しました。")
            actual_band = live.band if live is not None else self.settings.band
            qso = QSO(
                time_jst=datetime.now(JST), band=actual_band,
                mode="CW", callsign=self.other_call_var.get().strip().upper(),
                sent_rst="599", sent_nr=self.settings.sent_nr,
                rcvd_rst=self.other_rst_var.get().strip(),
                rcvd_nr=self.other_nr_var.get().strip().upper().replace(" ", ""),
                completed=True,
            )
            # Validate *before* asking whether to commit.
            if not qso.callsign or not qso.rcvd_nr:
                raise LogValidationError("相手コールサインと受信ナンバーを入力してください。")
            # append_qso checks all remaining fields.
            if not messagebox.askyesno("QSO確定確認", "実際に交信が成立し、相手局と交換ナンバーを確認しましたか？\nこの内容でログへ追記します。", parent=self.log_window):
                return
            self.storage.append_qso(self.settings, qso,
                                    frequency_hz=live.frequency_hz if live else None)
        except (LogValidationError, OSError, ValueError, sqlite3.DatabaseError) as exc:
            messagebox.showerror("ログ登録失敗", str(exc), parent=self.log_window)
            return
        self.other_call_var.set("")
        self.other_nr_var.set("")
        self._refresh_log(force=True)
        self._update_worked_status()

    def _open_folder(self):
        folder = self.storage.base_dir / "logs"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(folder))
            else:
                messagebox.showinfo("保存場所", str(folder), parent=self.log_window)
        except OSError as exc:
            messagebox.showerror("保存場所", str(exc), parent=self.log_window)

    def _on_close(self):
        self._closing = True
        self._disconnect_radio()
        self._stop_rx()
        self._close_log_window()
        self.root.destroy()


def main():
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
