# Windows 配布・受信モニタ実装 v0.6.0

基準：初代 ICOM IC-7300、Windows 10/11 x64。既存v0.5.0のSQLite記録とCI-V受信監視を維持する。**CWの自動送信、パイルアップ時のDeepCW復号、自動ログ確定は実装していない**。

## アプリの機能

- 設定画面：自局コールサイン、ALL JA/全市全郡、送信NR、バンド、コンテスト開始/終了JST、CI-V COMポート、USB Audio入力デバイス、CW音程(400～1100 Hz)。`%LOCALAPPDATA%\JARL_CW_AutoContest\settings.json`に保存する。v0.5.0以前の設定JSONは新規項目にデフォルト値を補って読み込める。
- CI-V（読取専用）：周波数とモードを画面表示。モード・バンド変更時に候補局と音声復号窓を破棄し、旧受信内容を新バンドに引き継がない。
- USB Audio：ユーザーが選択した入力から16kHz/mono/16bitで音声を取得、8秒窓・4秒ホップのGoertzel単一音程復号を表示。受信に使用する`RawInputStream`は出力経路を持たない。
- WAV試験：PCM 16bitモノラルまたはステレオWAVを読み込み同一の単一トーンデコーダで検証。受信デバイスや無線機を接続しなくても利用できる。
- 候補表示：復号文字列から形式上コールサインに見える文字列を候補として一覧化。完了QSOと同一バンドの過去交信をSQLiteから照会し、**交信済みやCI-V未接続時は応答対象から除外**。候補をダブルクリックすると手動ログ登録欄へ転記するが、その時点ではQSOは成立しない。
- 交信ログ：別ウィンドウでSQLiteの記録を1秒ごとに更新。ユーザーが成立を確認し、双方のナンバーを入力して承認した場合のみSQLite/CSVへ追記。
- CW送信：GUIからは無効。独立したCLIでの単発送信検証コードはv0.5.0から変更しない。

### 復号の制限

今回の単一音程Goertzel復号はDeepCWではない。異なる複数局が重なったCW、QRN、QRM、QSB、短い断片、ドップラー、クリッピングでの正確性は未検証。復号結果には形式だけを基準とした偽コールサイン候補が混入し得る。WPMも推定値にすぎない。**候補の自動送信・ログの自動確定は許可しない**。

## インストール不要な単独EXEの作成

このLinux実行環境ではWindows用EXEをビルドできない。GitHub Actions `windows-latest` 上で `scripts/build_windows.ps1` を実行して生成する。

GitHub Actionsワークフロー：`.github/workflows/windows-build.yml`。Windows 64bit / Python 3.13 / PyInstaller 6.22.3 / setuptools 81.0.0 / pyserial 3.5 / sounddevice 0.5.6で固定。ユニットテスト→EXE生成→パッケージ自己診断（RF送信なし）→アーティファクトアップロードの順で実行する。

生成されるファイル名：`IC7300_CW_AutoContest.exe`。Windows用ビルドが成功した場合のみ配布可能。使用者PCにPythonのインストールは必要ないが、ICOM公式USBドライバーなど接続に必要なドライバーは別途導入する。

ソースから動かす場合は：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[radio,audio]"
.\.venv\Scripts\python.exe -m cwcontest desktop
```

### 操作順

1. IC-7300のUSBドライバーを導入、USBケーブルを接続、USB Audio（AF）・CI-Vを設定する。KEY/PTT送信機能はオフ。
2. アプリの設定で**実際の**コールサイン、参加コンテスト、送信NR、開催日時(JST)、COMポートを登録。
3. 「接続・読取」でCI-V周波数・モードを確認する。コンテスト周波数外なら交信候補として許可しない。
4. 「一覧取得」でIC-7300の録音デバイスを選び、700HzなどにCW音程を設定して保存する。「受信開始」で単一音程を復号する。
5. 別ウィンドウの候補一覧から局を手動選択し、**実際に交信が成立した場合のみ**相手NRを入力して手動確定する。
6. 交信終了後、既存の`cwcontest audit/export`でCSV集計・JARL電子ログドラフトを作成する。提出ファイルの真偽はオペレーターが検証する。

## 動作確認の範囲

- Linux Python 3.13系でユニット試験、Xvfb仮想画面のTkinter試験が可能。
- IC-7300実機のUSB音声・CI-V接続、DeepCW統合、実RF送信、JARL受理は未検証。
- Windows実機・単独EXEのビルド結果はGitHub Actionsの実行結果を確認して判断する。
