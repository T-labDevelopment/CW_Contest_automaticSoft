# ICOM USB / Bluetooth CI-V 識別対応（v0.7.0設計・実装）

作成日：2026-11-05。**実機識別・Windows Bluetooth通信は未検証**。既存 IC-7300 USB を既定機種とし、送信禁止とオペレーターによるログ確定を維持する。

## 目的と判定

Windowsアプリの「無線機確認」を押した場合だけCI-Vシリアルポートを開き、`19 00`（トランシーバーIDを読み出す）を送信し、戻るIDを登録表と照合する。**応答の送信元アドレスだけで機種を決定せず、受信した識別データ１バイトを検査**する。選択モデルと異なるID、不正応答、タイムアウト、未定義IDの場合は、周波数読取を開始せず停止する。識別成功後のみ`03`（周波数）と`04`（モード）を定期読取する。`17`（CW文字送信）は識別処理で送信しない。GUIのRF送信は禁止のまま。

CI-Vフレーム例（IC-7300を初期アドレス`94h`で識別）:

```
PC→無線機 : FE FE 94 E0 19 00 FD
無線機→PC : FE FE E0 94 19 00 94 FD    (期待例)
```

無線機設定でCI-Vアドレスを変更した場合は、アドレス欄へ2桁16進値を指定する。たとえば接続先アドレス`62h`でIC-705を使うときは宛先`62h`を指定し、`19 00`の**IDはA4h**を期待する。ブロードキャストアドレス`00`は混在機器の誤検知を避けるため使わない。ユーザーがモデルを先に選択してから確認する方式であり、未接続機種を自動スキャンして無線機を推測しない。

## 読取コマンド（共通最小セット）

| 用途 | Command | 性質 | 備考 |
|---|---|---|---|
| 無線機ID | `19 00` | Read | 先に実行。戻りIDでモデルを照合 |
| 表示周波数 | `03` | Read | 照合後のみに実行 |
| 表示モード | `04` | Read | 照合後のみに実行 |
| CW文字列送信 | `17` | Write | 別途仕様確認が必要。GUIでは実行禁止 |

個別機の追加コマンドは付属の電子マニュアルを再確認して機種別プロファイルへ追加する。周波数のメイン/サブVFO、スプリット制御、16/47(BK-IN)、1C/00(TX状態)は機種共通と仮定しない。

## 対象候補の初期CI-Vアドレスと接続手段

以下は**USB-CI-V識別候補**で、CW自動交信の動作保証機種一覧ではない。Bluetooth SPP CI-Vの欄は仕様を確認できた機種のみに付ける。`17`が未確認の機種はCW送信機能を開放しない。

| モデル | Default CI-V | USB CI-V | BT SPP CI-V | 17h CW | 備考 |
|---|---:|---|---|---|---|
| IC-7300/M/S | 94h | 有 | 無 | 資料確認 | 標準機 |
| IC-705 | A4h | 有 | 有 | 資料確認 | BTはCI-Vのみ。WindowsのBT音声入力は未確認 |
| IC-7300MK2/M/S | B6h | 有 | 無 | 資料確認 | 初代と別機種 |
| IC-7610/M | 98h | 有 | 無 | 資料確認 | 複数RXの扱いは要検証 |
| IC-9700/S | A2h | 有 | 無 | 資料確認 | VHF/UHF |
| IC-7760 | B2h | 有 | 無 | 資料確認 | ツーピース式 |
| IC-905/905XG | ACh | 有 | 無 | 資料確認 | SHF帯を含み対応コンテストは限定 |
| IC-7100/M/S | 88h | 有 | 無 | 要確認 | USB音声/CI-V。17hは機種別未確認 |
| IC-9100/M | 7Ch | 有 | 無 | 要確認 | USB音声/CI-V。17hは機種別未確認 |
| IC-7600/M | 7Ah | 有 | 無 | 一部FW確認 | 17hの追加ファーム版を確認 |
| IC-7410/M | 80h | 有 | 無 | 資料確認 | IC-7410操作説明書に17h |
| IC-7200 | 76h | 有 | 無 | 要確認 | 17h未確認 |
| IC-7850 / IC-7851 | 8Eh | 有 | 無 | 要確認 | ID共通で両者を識別不能 |

Bluetoothに対応する非CW機（例：ID-52、ID-4100、ID-5100等）は、**CWコンテスト用のリグ選択候補に含めない**。CI-V搭載でもCWモード・CW送信に対応するとは限らない。

## GUI操作と動作

- モデル選択 → USB/Bluetooth（機種対応フラグで非対応の場合はRadioButtonをdisabledにする） → COMポート入力 → 設定保存 → **無線機確認**。
- USBはPCの仮想COMとUSB Audioを別々に選ぶ。IC-705 Bluetooth SPPはWindowsのペアリングで生成されるCOMを選ぶ。**Bluetooth音声がPCに取り込めるとの保証はしない**。
- 接続確認はGUI起動時・音声開始時に勝手に走らない。接続確認後、識別した機種名・IDを表示し、周波数/モード/交信済み局リストを使う。
- 通信断時は識別結果と周波数を無効にして既存の安全停止状態へ戻す。
- Wi-Fiネットワークの変更、接続確立、IP経路の切替は一切行わない。既存のPCインターネット接続へ干渉しない。

## 公式資料・出典

実機向け機種別コマンド一覧は、以下のICOM公式製品ページにある「補足説明書（CI-Vコマンド説明）」または「取扱説明書」に従う。各マニュアル全文は著作権上同梱しない。

- [IC-7300](https://www.icom.co.jp/lineup/products/IC-7300/)（補足説明書：CI-V）
- [IC-7300MK2](https://www.icom.co.jp/lineup/products/IC-7300MK2/)（補足説明書：CI-V、初期B6h）
- [IC-705](https://www.icom.co.jp/lineup/products/IC-705/)（CI-V補足説明書、BT/SPP）
- [IC-7610](https://www.icom.co.jp/lineup/products/IC-7610/)（CI-V補足説明書）
- [IC-9700](https://www.icom.co.jp/lineup/products/IC-9700/)（CI-V補足説明書）
- [IC-7760](https://www.icom.co.jp/lineup/products/IC-7760/)（CI-V補足説明書、初期B2h）
- [IC-905](https://www.icom.co.jp/lineup/products/IC-905/)（CI-V補足説明書）
- [IC-7100](https://www.icom.co.jp/lineup/products/IC-7100/)（補足説明書）
- [IC-9100](https://www.icom.co.jp/lineup/products/IC-9100/)（取扱説明書）
- [IC-7600](https://www.icom.co.jp/lineup/products/IC-7600/)（取扱説明書・ファーム更新資料）
- [IC-7410](https://www.icom.co.jp/lineup/products/IC-7410/)（取扱説明書）
- [IC-7200](https://www.icom.co.jp/lineup/products/IC-7200/)（取扱説明書）
- [IC-7851](https://www.icom.co.jp/lineup/products/IC-7851/)（取扱説明書）
- [ICOM公式USBドライバー機種表](https://www.icom.co.jp/support/drivers/3860/)
- [ICOM America IC-705 Bluetooth FAQ](https://icomamericasupport.zendesk.com/hc/en-us/articles/35050966822036-IC-705-Instructions-and-FAQs)（BT 4.2、SPP/HFP/HSP/GATT）

**実装範囲**: IDの安全照合、GUIの対象機種・接続方式、設定保存と旧設定移行、USB/BTシリアルの読取共通化。**未実装/未検証**: Bluetooth音声、全機種のRF送信、各ファームでの17h動作、実機PC接続、DeepCW、完全自動交信。
