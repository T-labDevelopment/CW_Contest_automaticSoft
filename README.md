# JARL CW AutoContest Rev.A / v0.3.0 (IC-7300基準)

**IC-7300（初代）を第一基準機としたWindows PC完結型のCWコンテスト交信試作**。

現在の達成範囲：
- IC-7300 CI-Vのフレーム構築と模擬応答付き読取（周波数、CWモード、BK-IN、TX状態）、最大30文字のCWメッセージ送信コマンド、FFh中止コマンド。
- USB Audio入力をPCM WAVに録音する機能（実機未検証）。単一局のCW音をWAVから復号する実験的デコーダー。
- オペレーター承認付きのQSO状態機械（送受信のソフトウェア結線なし、手順のユニットテストのみ）。
- 既存のALL JA/全市全郡ログ集計、JARL R2.1ドラフト、Excel確認用CSV。**既存コアは維持**。

**未実装**：USB AudioのライブCW自動解読と連動交信、多数局・QRM・QSBの復号、完成QSOの自動ログ追記、zLogへのライブ同期、JARL提出サイトへの自動提出、実機USB接続とRF送出実証。JARLで自律ロボット局が参加可能かどうかも未確認。送信機能はデフォルト無効。

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

- [`SPEC.md`](SPEC.md) – 全体仕様（既存のv0.2.0基本方針を維持し、v0.3.0追補あり）
- [`docs/USB_IO_DESIGN.md`](docs/USB_IO_DESIGN.md) – 初期USB分離設計
- [`docs/IC7300_INTEGRATION.md`](docs/IC7300_INTEGRATION.md) – IC-7300具体的な接続・安全・コマンド仕様
- [`profiles/ic7300_usb.json`](profiles/ic7300_usb.json) – 実行用の送信禁止プロファイル
- [`profiles/ic7300_usb_draft.json`](profiles/ic7300_usb_draft.json) – v0.2.0以前の資料（削除せず保持）

変更履歴はローカルGit管理。GitHubへのアップロード・同期は未実施です。
