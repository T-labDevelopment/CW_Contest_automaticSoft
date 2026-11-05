# IC-705 Bluetooth / WLAN 接続検討 (2026-11-05)

状態: **設計調査のみ / 未実機検証**。現行 IC-7300 USB を標準機・基準実装として維持する。v0.6.0 のGUI、USB Audio、CI-V、SQLiteログ、CW復号処理、送信禁止初期値には変更を加えない。

## 確認された仕様

- IC-705 は Bluetooth 4.2 の SPP / HFP / HSP / GATT（Serial over LE）に対応する。WindowsとのCI-Vは **SPP / 仮想COM** を第一候補とし、GATTの使用は初期対象にしない。
- IC-705 `SET > Bluetooth Set > Data Device Set > Serialport Function` の初期値は `CI-V (Echo Back OFF)`。SPP接続でCI-Vを送受信可能。受信したシリアルデータを折り返さない設定。
- IC-705 のCI-V初期アドレスは `A4h`（初代IC-7300の `94h` と異なる）。周波数取得 `03h`、モード取得 `04h`、CWメッセージ送信 `17h`（最大30文字）はIC-705資料で確認。
- IC-705 のBluetooth音声は主にヘッドセット向け HFP/HSP。Windows標準のBluetooth音声の役割とは適合しない可能性があり、**PCの録音デバイスとして使用できることは未確認**。HFP音声がCW混信復号に十分かも未検証。
- IC-705 はWi-Fi経由のRS-BA1方式でCI-Vと音声を扱える。無線接続を完全化する場合の比較対象だが、現行開発での実装は未決定。

## 接続方式別の評価表

| モード | 送受信CI-V | 受信音声 | 検証位置付け |
|---|---|---|---|
| IC-7300 USB | USB COM | USB Audio | 既存標準・変更なし |
| IC-705 USB | USB COM | USB Audio | 次の有線機種候補 |
| IC-705 BT SPP | Windows BluetoothのOutgoing COM | 未確定 | 制御機能の試験対象 |
| IC-705 BT SPP + 端子音声 | BT COM | PCオーディオ入力 | 暫定策、音声回路・レベル調整が必要 |
| IC-705 Wi-Fi RS-BA1 | LANプロトコル | LAN音声 | 無線化の別候補（未実装） |

## 推奨するソフトウェア境界

- `RadioProfile`: `ic7300` (CI-V `0x94`) / `ic705` (CI-V `0xA4`) を独立して保持。アドレスをハードコードした共用化をしない。
- `CIVTransport`: USB仮想COMとBluetooth SPP仮想COMは同じシリアル読み書きAPIを利用。切断検知、タイムアウト、再接続時の送信禁止を共通化。
- `AudioSource`: USB Audio / 外部入力 / 将来のWLAN音声の切替を可能にし、CI-V物理層とは別設定にする。
- `ContestEngine`、`WorkedList`、`Logger`: 機種・接続方式に依存しない。実周波数・モードの取得に失敗したら自動選局・送信を停止し、以前の値を流用しない。
- プロファイル選択欄は `IC-7300 USB` をデフォルトにし、IC-705各モードは実機検証前の評価機能として段階的に有効化する。

## 実機評価手順（全項目未実施）

1. IC-705 `Bluetooth Set` でBluetoothを有効化し、`Data Device Set > Serialport Function = CI-V (Echo Back OFF)` に設定。Windowsとペアリング。
2. WindowsのBluetooth SPP `Outgoing` 側COMポートを確認。COMポートが存在することと開けることを検証。
3. 送信を無効にしたまま、CI-V `03h` / `04h` の応答を受信・表示し、`A4h` を照合。周波数変更、CW/CW-R切替、通信断、再接続を検証。
4. `17h` はまずメッセージ生成・模擬応答のみで確認。実RF送信前にCWモード、BK-IN、送信抑止、最大送信長、緊急中断の安全動作を実機で確認。
5. Bluetooth音声がWindows録音デバイスになるかを確認。認識できた場合は短点/長点、音質、帯域、遅延、途切れ、複数局パイルアップの復号精度を測定。できない場合は未対応扱いにし、USBまたはWi-Fi方式と比較。
6. Wi-Fi方式は音声とCI-V同時転送、接続断時停止、遅延、設定工数、ライセンスを比較するが、初期バージョンでは既存USB経路へ影響させない。

## 出典（2026-11-05確認）

- Icom公式 IC-705製品仕様: https://www.icom.co.jp/lineup/products/IC-705/
- Icom America FAQ（Bluetooth 4.2/SPP/HFP/HSP/GATT）: https://icomamericasupport.zendesk.com/hc/en-us/articles/35050966822036-IC-705-Instructions-and-FAQs
- Icom IC-705 Basic Manual（Bluetooth Data Device Set / CI-V over SPP）: https://www.icomeurope.com/wp-content/uploads/2024/06/IC-705_ENG_IM_Basic_7.pdf
- Icom IC-705 CI-V Reference Guide（A4h, 03h, 04h, 17h）: https://www.icomeurope.com/wp-content/uploads/2020/08/IC-705_ENG_CI-V_1_20200721.pdf
- Icom RS-BA1 Ver.2公式説明: https://www.icom.co.jp/lineup/options/RS-BA1_version2/
- Windows Bluetooth Audio仕様: https://learn.microsoft.com/windows-hardware/drivers/bluetooth/bluetooth-classic-audio
- kappanhang（非公式RS-BA1互換、Linux主対象）: https://github.com/nonoo/kappanhang

確認済み = 公式資料上の機能のみ。Windows/IC-705での実機動作、Bluetooth音声入力、交信送信は未検証。
