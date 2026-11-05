"""Windows-first two-window GUI. All RF transmission is intentionally disabled."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from .core import ALLOWED_BANDS, JST, LogValidationError, QSO
from .desktop_data import DesktopSettings, DesktopStorage, summarize_live_log

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
        except LogValidationError as exc:
            messagebox.showwarning("設定読み込み", str(exc), parent=self.root)
        self._refresh_band_choices()
        self.open_log_window()
        self.root.after(1000, self._poll_log)

    def _configure_root(self):
        self.root.title("IC-7300 CWコンテスト - 設定")
        self.root.geometry("480x460+60+70")
        self.root.minsize(440, 410)
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
        for i, title in enumerate(("自局コールサイン", "コンテスト", "送信ナンバー", "運用バンド (MHz)")):
            ttk.Label(form, text=title).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Entry(form, textvariable=self.call_var).grid(row=0, column=1, sticky="ew", pady=6)
        self.contest_box = ttk.Combobox(form, textvariable=self.contest_var, state="readonly", values=list(LABEL_TO_CONTEST))
        self.contest_box.grid(row=1, column=1, sticky="ew", pady=6)
        self.contest_box.bind("<<ComboboxSelected>>", lambda event: self._refresh_band_choices())
        ttk.Entry(form, textvariable=self.nr_var).grid(row=2, column=1, sticky="ew", pady=6)
        self.band_box = ttk.Combobox(form, textvariable=self.band_var, state="readonly")
        self.band_box.grid(row=3, column=1, sticky="ew", pady=6)
        ttk.Label(form, text="例：ALL JA = 11M / 全市全郡 = 100116M（RST不要）", foreground="#505c6b").grid(row=4, column=0, columnspan=2, sticky="w", pady=(5, 0))
        buttons = ttk.Frame(wrapper)
        buttons.pack(fill="x", pady=(14, 8))
        ttk.Button(buttons, text="設定を保存", command=self._on_save).pack(side="left", padx=(0, 10))
        ttk.Button(buttons, text="交信ログを表示", command=self.open_log_window).pack(side="left")
        ttk.Label(wrapper, textvariable=self.notice_var, foreground="#8a4b00", wraplength=430).pack(anchor="w", pady=(12, 3))
        ttk.Label(wrapper, text="この画面からは無線機へ送信しません。", foreground="#505c6b").pack(anchor="w")

    def _refresh_band_choices(self):
        contest_id = LABEL_TO_CONTEST.get(self.contest_var.get(), "ALL_JA")
        bands = sorted(ALLOWED_BANDS[contest_id], key=float)
        self.band_box.configure(values=bands)
        if self.band_var.get() not in bands:
            self.band_var.set("7" if "7" in bands else bands[0])

    def _read_form(self) -> DesktopSettings:
        contest_id = LABEL_TO_CONTEST.get(self.contest_var.get(), "")
        return DesktopSettings(self.call_var.get(), contest_id, self.nr_var.get(), self.band_var.get()).checked()

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
        self.notice_var.set(f"設定保存済み: {value.station_callsign} / {value.sent_nr} ・送信禁止")
        if previous != value:
            self._log_stamp = None
            self._refresh_log(force=True)

    def open_log_window(self):
        if self._closing:
            return
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.log_window = window
        window.title("交信ログ（自動更新） - IC-7300 CW")
        window.geometry("980x480+555+70")
        window.minsize(750, 340)
        window.protocol("WM_DELETE_WINDOW", self._close_log_window)
        outer = ttk.Frame(window, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="交信ログ（CSV自動監視・1秒ごと）", font=("Yu Gothic UI" if os.name == "nt" else "TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(outer, textvariable=self.log_summary_var).pack(anchor="w", pady=(4, 8))
        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("time", "band", "call", "sent", "received", "rst", "status")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        self.tree = tree
        for key, label, width in (("time", "時刻 (JST)", 160), ("band", "MHz", 66),
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
            stat = path.stat() if path.exists() else None
            stamp = (str(path), stat.st_mtime_ns if stat else None, stat.st_size if stat else 0)
            if not force and self._log_stamp == stamp:
                return
            qsos = self.storage.list_qsos(self.settings)
            rows = summarize_live_log(qsos)
        except (OSError, LogValidationError, ValueError) as exc:
            self.log_summary_var.set(f"ログ読み込みエラー: {exc}")
            return
        self._log_stamp = stamp
        existing_selection = self.tree.selection()
        selected_index = self.tree.index(existing_selection[0]) if existing_selection else -1
        for item in self.tree.get_children():
            self.tree.delete(item)
        for qso, status in rows:
            rowtag = "duplicate" if status == "重複候補" else "incomplete" if status == "未完了" else ""
            self.tree.insert("", "end", values=(
                qso.time_jst.strftime("%Y-%m-%d %H:%M:%S"), qso.band,
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
        self.root.after(1000, self._poll_log)

    def _add_qso(self):
        if self.settings is None:
            messagebox.showerror("設定未保存", "先に自局設定を保存してください。", parent=self.log_window)
            return
        try:
            qso = QSO(
                time_jst=datetime.now(JST), band=self.settings.band,
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
            self.storage.append_qso(self.settings, qso)
        except (LogValidationError, OSError, ValueError) as exc:
            messagebox.showerror("ログ登録失敗", str(exc), parent=self.log_window)
            return
        self.other_call_var.set("")
        self.other_nr_var.set("")
        self._refresh_log(force=True)

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
        self._close_log_window()
        self.root.destroy()


def main():
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
