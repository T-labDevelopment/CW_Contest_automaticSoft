# JARL CW AutoContest Rev.A / v0.6.0 (IC-7300 / Windows USB受信・CI-V・ログ)

**IC-7300（初代）を第一基準機としたWindows PC完結型のCWコンテスト交信試作**。

現在の達成範囲：
- IC-7300 CI-Vのフレーム構築と模擬応答付き読取（周波数、CWモード、BK-IN、TX状態）、最大30文字のCWメッセージ送信コマンド、FFh中止コマンド。
- USB Audio入力をPCM WAVに録音する機能（実機未検証）。単一局のCW音をWAVから復号する実験的デコーダー。
- オペレーター承認付きのQSO状態機械（送受信のソフトウェア結線なし、手順のユニットテストのみ）。
- 既存のALL JA/全市全郡ログ集計、JARL R2.1ドラフト、Excel確認用CSV。**既存コアは維持**。

**v0.6.0追加：** Windows GUIにUSB Audio入力の録音デバイス選択、CW音程設定、8秒窓/4秒周期の単一音程ライブ復号、WAVファイル試験、受信候補局一覧（別ウィンドウ内）を実装。候補局は運用周波数・CWモード・交信済み局リストと照合して表示。候補局のダブルクリックで手動ログ入力へ転記する。DeepCW・自動交信・自動ログ確定・自動RF送信は**未実装**であり、受信内容はオペレーターが確認する。Windows EXEビルド用のGitHub Actionsワークフローを追加。詳細は [`docs/WINDOWS_BUILD_v0.6.0.md`](docs/WINDOWS_BUILD_v0.6.0.md)。

**v0.5.0追加：** 内部SQLiteによる交信済み局リスト、開催期間（JST）の指定、CI-Vで現在周波数とモードを約1秒間隔で読取、表示バンドの切替・モード確認、バンド別既交信除外候補判定を実装。GUIの自動局選択はライブCW復号に未接続。送信禁止は維持。詳細は [`docs/CI_V_WORKED_LIST.md`](docs/CI_V_WORKED_LIST.md)。

**v0.4.0 Windowsデスクトップ版：** `tkinter`/`ttk`で自局コールサイン・送信ナンバー・コンテスト・バンドの設定画面と、別ウィンドウの交信ログ自動更新画面を実装。GUIはデフォルト送信禁止。IC-7300の実USB受信・CW送信・DeepCW・自動交信とはまだ連動していない。Windows用EXEの作成手順と使用方法は[`docs/WINDOWS_DESKTOP.md`](docs/WINDOWS_DESKTOP.md)。

**v0.3.1仕様追補（実行コードは0.3.0のまま）**：パイルアップでは全局の同時受信・復号を必須とせず、交信可能な1局の選択・追跡・再送要求を優先。DeepCW公開エンジンを第一評価候補とする。現段階では仕様のみで、実装・実機検証は未実施。詳細は[`docs/PILEUP_SELECTION_DESIGN.md`](docs/PILEUP_SELECTION_DESIGN.md)。

**v0.3.2先行事例レビュー（設計のみ）**：DeepCW、DitStorm、Kvasha、zLog/cwListener、Morse Runner、CWSDを調査。自動交信とマクロ操作の差を明示し、自局宛て判定・選局固定・未確定番号送信拒否・帯域占有時のCQ抑制を要求事項に追加。詳細は[`docs/PRECEDENTS_AUTOMATED_CW_2026-11-05.md`](docs/PRECEDENTS_AUTOMATED_CW_2026-11-05.md)。

**未実装**：DeepCW連携とライブCW連動交信、多数局・QRM・QSBの確実な復号、完成QSOの自動ログ追記、zLogへのライブ同期、JARL提出サイトへの自動提出、実機USB接続とRF送出実証。JARLで自律ロボット局が参加可能かどうかも未確認。送信機能はデフォルト無効。

## Windows画面の起動

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[radio,audio]"
.\.venv\Scripts\python.exe -m cwcontest desktop
```

Windowsで単独実行EXEをビルドするには `powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1` を実行。生成物は `dist\IC7300_CW_AutoContest.exe`（**ビルドがWindowsで成功した場合のみ**）。この環境ではWindows実行ファイルの生成・検証は未実施。

## 動作環境

Python 3.13.5でテスト（標準ライブラリのテスト部分）。実機機能はWindowsのIC-7300用USBドライバーと次のオプションを使用します。

- `pyserial==3.5`（CI-V仮想COM）
- `sounddevice==0.5.6`（USB Audio）
- Python `>=3.11`、テストで使用した開発環境は3.13.5

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[radio,audio]"
python -m cwcontest radio-check --port COM4
python -m cwcontest audio-devices
python -m cwcontest audio-record --device 3 --seconds 10 --out rx.wav
python -m cwcontest decode-wav --wav rx.wav --tone 700
```

**COM4、device 3は例であり自動検出値ではありません。** 接続前に公式USBドライバーを導入してください。送信コマンドの確認・送信停止・実機手順は[`docs/IC7300_INTEGRATION.md`](docs/IC7300_INTEGRATION.md)参照。

既存のログ機能は従来どおり：

```bash
PYTHONPATH=src python -m cwcontest audit --config examples/allja2026_demo.json --csv examples/allja2026_demo.csv
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m cwcontest export --config examples/allja2026_demo.json --csv examples/allja2026_demo.csv --out output --confirm
```

提出ファイル生成は利用者の確認のうえでのみ実行。サンプルは架空QSO/架空個人情報なので実提出不可。JARL R2.1ファイルの実受理は未確認。

## 関連資料

- [`docs/CI_V_WORKED_LIST.md`](docs/CI_V_WORKED_LIST.md) – CI-V周波数・モード受信、SQLite交信済み除外、テスト対象
- [`docs/WINDOWS_DESKTOP.md`](docs/WINDOWS_DESKTOP.md) – Windows単独EXE、設定画面、別ウィンドウログ、保存場所と検証状態
- [`SPEC.md`](SPEC.md) – 全体仕様（既存のv0.2.0基本方針を維持し、v0.3.0追補あり）
- [`docs/USB_IO_DESIGN.md`](docs/USB_IO_DESIGN.md) – 初期USB分離設計
- [`docs/IC7300_INTEGRATION.md`](docs/IC7300_INTEGRATION.md) – IC-7300具体的な接続・安全・コマンド仕様
- [`docs/PILEUP_SELECTION_DESIGN.md`](docs/PILEUP_SELECTION_DESIGN.md) – DeepCW調査、1局選択型パイルアップ処理・検証項目
- [`docs/PRECEDENTS_AUTOMATED_CW_2026-11-05.md`](docs/PRECEDENTS_AUTOMATED_CW_2026-11-05.md) – 国内外先行例の実際の自動化範囲・採用する設計要件
- [`profiles/ic7300_usb.json`](profiles/ic7300_usb.json) – 実行用の送信禁止プロファイル
- [`profiles/ic7300_usb_draft.json`](profiles/ic7300_usb_draft.json) – v0.2.0以前の資料（削除せず保持）

ソース変更は作業ブランチでGit管理し、mainへの統合は明示的な承認を必要とします。
