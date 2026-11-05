"""Windows-first two-window GUI. All RF transmission is intentionally disabled."""
from __future__ import annotations

from datetime import datetime
import os
import sqlite3
from queue import Empty, Queue
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .core import ALLOWED_BANDS, JST, LogValidationError, QSO
from .desktop_data import DesktopSettings, DesktopStorage, summarize_live_log
from .contest_radio import RadioState
from .radio_monitor import RadioMonitor, RadioUpdate

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
        self.notice_var = tk.StringVar(value="送信禁止 / ライブ復号未接続。手動確定QSOのみ記録可能")
        self._log_stamp: tuple | None = None
        self._closing = False
        self.radio_state: RadioState | None = None
        self.radio_monitor: RadioMonitor | None = None
        self.radio_events: Queue[RadioUpdate] = Queue()
        self.selected_station: str | None = None  # stale candidates invalidated on band changes
        self.radio_var = tk.StringVar(value="CI-V未接続（受信状態不明）")
        self.worked_var = tk.StringVar(value="交信済み局判定: コンテスト期間未設定")
        self.civ_var = tk.StringVar()
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
        except LogValidationError as exc:
            messagebox.showwarning("設定読み込み", str(exc), parent=self.root)
        self._refresh_band_choices()
        self.open_log_window()
        self.root.after(1000, self._poll_log)
        self.root.after(200, self._poll_radio_events)

    def _configure_root(self):
        self.root.title("IC-7300 CWコンテスト - 設定")
        self.root.geometry("580x620+60+70")
        self.root.minsize(520, 580)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            ttk.Style(self.root).theme_use("vista" if os.name == "nt" else "clam")
        except tk.TclError:
            pass

    def _create_settings_ui(self):
        wrapper = ttk.Frame(self.root, padding=16)
        wrapper.pack(fill="both", expand=True)
        ttk.Label(wrapper, text="IC-7300 / CWコンテスト", font=("Yu Gothic UI" if os.name == "nt" else "TkDefaultFont", 15, "bold")).pack(anchor="w")
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
        radio_frame = ttk.LabelFrame(wrapper, text="IC-7300 / USB CI-V 受信専用", padding=9)
        radio_frame.pack(fill="x", pady=(12, 0))
        line = ttk.Frame(radio_frame)
        line.pack(fill="x")
        ttk.Label(line, text="COMポート").pack(side="left", padx=(0, 7))
        ttk.Entry(line, textvariable=self.civ_var, width=10).pack(side="left", padx=(0, 9))
        ttk.Button(line, text="接続・読取", command=self._connect_radio).pack(side="left")
        ttk.Button(line, text="切断", command=self._disconnect_radio).pack(side="left", padx=(8, 0))
        ttk.Label(radio_frame, textvariable=self.radio_var).pack(anchor="w", pady=(7, 3))
        ttk.Label(radio_frame, textvariable=self.worked_var).pack(anchor="w")
        buttons = ttk.Frame(wrapper)
        buttons.pack(fill="x", pady=(14, 8))
        ttk.Button(buttons, text="設定を保存", command=self._on_save).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="交信ログを表示", command=self.open_log_window).pack(side="left")
        ttk.Label(wrapper, textvariable=self.notice_var, foreground="#8a4b00", wraplength=520).pack(anchor="w", pady=(12, 3))
        ttk.Label(wrapper, text="この画面からは無線機へ送信しません。", foreground="#505c6b").pack(anchor="w")

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
                               self.end_var.get(), self.civ_var.get()).checked()

    def _on_save(self):
        try:
            value = self.storage.save_settings(self._read_form())
        except (OSError, LogValidationError, TypeError) as exc:
            messagebox.showerror("設定エラー", str(exc), parent=self.root)
            return
        previous = self.settings
        self.settings = value
        self.call_var.set(value.station_callsign)
        self.nr_var.set(value.sent_nr)
        self.start_var.set(value.contest_start_jst)
        self.end_var.set(value.contest_end_jst)
        self.civ_var.set(value.civ_port)
        self._update_worked_status()
        self.notice_var.set(f"設定保存済み: {value.station_callsign} / {value.sent_nr} ・送信禁止")
        if previous != value:
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
        self.radio_monitor = RadioMonitor(settings.civ_port, self.radio_events)
        self.radio_var.set(f"{settings.civ_port} 接続確認中…（送信禁止）")
        self.radio_monitor.start()

    def _disconnect_radio(self):
        if self.radio_monitor is not None:
            self.radio_monitor.stop()
            self.radio_monitor = None
        self.radio_state = None
        self.selected_station = None
        self.radio_var.set("CI-V未接続（受信状態不明 / 自動送信禁止）")
        self._update_worked_status()

    def _poll_radio_events(self):
        if self._closing:
            return
        try:
            while True:
                update = self.radio_events.get_nowait()
                previous = self.radio_state
                self.radio_state = update.state
                if update.state is not None:
                    state = update.state
                    if previous and (previous.frequency_hz != state.frequency_hz or previous.mode != state.mode):
                        self.selected_station = None
                        self.notice_var.set("周波数またはモード変更：旧受信候補を破棄しました（送信禁止）")
                    warning = "CWコンテスト帯域内" if state.in_cw_contest_segment else "CWコンテスト帯域外"
                    if state.edge_warning:
                        warning = "帯域境界付近・要確認"
                    if not state.cw_mode:
                        warning = "CW以外・対象外"
                    self.radio_var.set(f"IC-7300 {state.frequency_label}  {state.mode}  "
                                       f"{state.band or '帯域不明'}MHz / {warning}")
                else:
                    self.selected_station = None
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
        window.title("交信ログ（自動更新） - IC-7300 CW")
        window.geometry("1050x500+675+70")
        window.minsize(750, 340)
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
        manual = ttk.LabelFrame(outer, text="交信成立を確認したQSOを手動登録（受信・送信の自動処理は未接続）", padding=9)
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
        self._close_log_window()
        self.root.destroy()


def main():
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
