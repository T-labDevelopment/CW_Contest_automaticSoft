# IC-7300 Rev.A 実装・検証計画（v0.3.0）

更新：2026-11-05。**初代IC-7300専用の暫定実装。実機未接続・未検証。** IC-7300MK2の仕様を混同しない。

## 前提と実装境界

- 機材：Windows PC、IC-7300、USB-B⇔USB-Aケーブル。外付けキーヤー・マイコン・音声インターフェースは不要。
- PC側：USB AudioのAF取得→CW音響解析（現在は単一局の録音WAVのみ）→交信状態機械（現在は手動認証のみ）→CI-V `17`で無線機内蔵CW送信→既存JARLログ集計。
- `ic7300.py`: コマンド`03`周波数、`04`モード、`16 47`BK-IN、`1C 00`TX状態の読取、および`17`文字送信と`17 FF`停止。CI-Vの`FE FE ... FD`フレーム解析。模擬応答テスト。
- `audio_usb.py`: 16-bit/monoのUSB AFをWAVに録音。デバイスをユーザーが指定。ライブQSOへの自動連携なし。
- `audio_cw.py`: 指定した単一トーン（初期700Hz）をGoertzelで検出し短点・長点を推定。WAVオフライン用。**多重局・妨害・速度変動・弱信号の実用性は未確認**。
- `qso_session.py`: CQ→相手局候補→承認→ナンバー候補→承認→TU送信確認→QSO確定。**独立シミュレーションでありUSB入出力・ログ保存を結線していない**。
- `core.py`: 既存のJARLデータ検査/得点/マルチ/提出形式下書き。変更せず維持。

## IC-7300側メニュー（推奨開始点）

| IC-7300のメニュー設定 | 値 | 理由 |
|---|---|---|
| USB Serial Function | CI-V | USB COMで制御 |
| CI-V Address | 94h（標準） | 固定アドレスで機種差を排除 |
| CI-V USB Port | Unlink from [REMOTE] | USB COMを独立動作 |
| CI-V USB Baud Rate | 115200 | PCと固定一致 |
| CI-V USB Echo Back | OFF | 照合を単純化（エコーはソフトでも無視） |
| ACC/USB Output Select | AF | 音声復号にベースバンド音声が必要 |
| USB SEND | OFF | DTR/RTSによる誤送信を避ける |
| USB Keying (CW) | OFF | CI-V `17h`方式を利用するためOFF |
| USB Keying (RTTY) | OFF | 不要 |
| Inhibit Timer at USB Connection | ON | USB接続時のキーイング抑制 |
| 運用モード | CW | コマンド`17h`はCW送信 |
| Break-in | 送信時にSemi/Full ON | メッセージのCW送信条件 |

以上は**推奨値**であり、ソフトがすべて検証できるわけではない。実機の設定に合わせる必要がある。

## Windowsでの実行

OSに対応するIC-7300公式USBドライバーをメーカーサイトから導入し、WindowsでUSB Audioデバイスと仮想COMポートを確認する。COMポートの自動探索・複数アプリ共有はしない。zLogと本ソフトが同じポートを同時に開く構成は不可。ポートを共有する必要があるなら、排他を守るブローカー方式を後日実装する。

```powershell
cd JARL_CW_AutoContest_RevA
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[radio,audio]"

# 初回は送信せず、無線機設定・AF入力を確認する
python -m cwcontest radio-check --port COM4
python -m cwcontest audio-devices
python -m cwcontest audio-record --device 3 --seconds 10 --out rx.wav
python -m cwcontest decode-wav --wav rx.wav --tone 700
```

上記のCOM4とdevice 3は例。実際のデバイス番号を確認する。`audio-record`は受信専用で、RF送信指令を発しない。

### CW送信に進む場合（実機試験でのみ）

- アンテナ/ダミーロード、局免許、送信可能な周波数、CWブレークイン、RF出力、接続確認を操作者が実施する。
- `profiles/ic7300_usb.json`の`keying.transmit_enabled`を**手作業で**`true`に変更して初めて送信指令を受け付ける。Gitには秘密情報を入れず、送信許可変更は常用設定にしない。
- 以下の2フラグも毎回必要。送信文は**最大30文字**。**1回のCW送出しか許可しない**。キューの自動再送、長文の自動分割、CQ連続送信は未実装。

```powershell
python -m cwcontest cw-send --port COM4 --text "VVV TEST" --arm-rf --menu-checked
# 最終操作としての停止要求。無線機を目視してTX停止確認すること。
python -m cwcontest cw-abort --port COM4
```

**重要**：`cw-send`の`FBh`応答は無線機側がCI-V命令を受け付けたことを示すだけで、実際のCW送出完了を示すものではない。応答欠落時も自動再送を行わない。送信中に接続が断たれた場合、ソフトウェア停止指令だけでTX解放が保証されるものではない。

## 交信データ・提出

- 未確定のコールサイン、受信ナンバーはログ確定しない。`qso_session.py`は操作者による候補承認とTU送出の確認を必須にする。
- 交信の送受、ログへの追記、コンテストルール最終照合はまだ統合していない。全自動運用のJARL規約・法令確認も未了。
- 既存の`audit`および`export`は引き続きオフラインCSV用で、JARLサイトへの実提出を実装したものではない。

## 実機確認の順序

1. USBドライバー認識→COM番号・入力音声デバイスの確認。
2. `radio-check`で周波数/モード/BK-IN/TX状態を実機で読めることを確認（**RF送信なし**）。
3. 受信信号を`audio-record`で録音してWAVを聞き、AFレベル・CWトーンを調整する。
4. `decode-wav`の解読文字と実際の受信符号を照合。弱信号や2局以上で誤認識を確認する。
5. ダミーロード/低出力で手動許可付きの短いCI-V CWを送信。ストップ指令を検証。
6. 交信状態機械とライブ受信・送信の結線、確認UI、送出完了検知を実装してからコンテスト運用試験。

## 公式根拠

- IC-7300製品：https://www.icom.co.jp/lineup/products/IC-7300/
- IC-7300公式取扱説明書：https://www.icom.co.jp/support/manual/2405/
- IC-7300公式CI-Vコマンド補足説明書：https://www.icom.co.jp/support/manual/2557/
- Icom English Full Manual 19章：https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-7300_ENG_FM_12a.pdf
- Icom USB接続資料と安全上の注意：https://www.icom.co.jp/lineup/products/IC-7300/
- sounddevice 0.5.6：https://pypi.org/project/sounddevice/
- pyserial 3.5：https://pypi.org/project/pyserial/
