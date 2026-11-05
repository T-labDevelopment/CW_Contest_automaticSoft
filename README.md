# JARL CW AutoContest Rev.A / 0.2.0（設計仕様改訂）

JARL国内コンテスト向け自動CW交信装置の開発リポジトリです。

**現段階で動作するのは、オフラインCSV入力からのログ検査、重複判定、得点・マルチ集計、JARL R2.1形式（ドラフト）およびExcelレビュー用CSVの出力だけです。**
CWの受信解読、USB音声取得、CI-V／DTR/RTS／外付けUSB KEYによるキーイング、zLogのライブ連携、実RF送信、自動QSO、提出サイトへの送信は未実装です。
JARLによるファイル受理確認、法令適合性・完全自動交信のコンテスト参加可否も未検証です。

## Rev.A標準I/O（v0.2.0設計更新）

- 標準構成：**Windows PC ＋ 無線機内蔵USB Audio ＋ USB仮想COM／CI-V CWメッセージ送信**。内蔵USBを利用できればUSBケーブル1本で接続する。
- CW送信の優先順位は (1) **CI-V `17h` による無線機内蔵CW送出**、(2) **無線機内蔵USB仮想COM DTR/RTSキーイング**、(3) **簡易USB KEYユニットから無線機のKEY端子へ接点相当出力**。
- **専用MCU/キーヤー基板、独立音声I/O基板は標準構成から除外**。CW受信・送信指示・ログ集計をPCソフトウェアに統合する。
- 本版は**設計仕様のみを更新**。従来のログ集計コードは変更せず、USB通信・実送信はまだ実装していない。
- 詳細：[`docs/USB_IO_DESIGN.md`](docs/USB_IO_DESIGN.md)、機種別設定草案：[`profiles/ic7300_usb_draft.json`](profiles/ic7300_usb_draft.json)。

## 実行環境

- Python 3.13.5 / 標準ライブラリのみ（初期動作確認バージョン）
- `git` 2.47.3 で作業リポジトリをローカル生成
- 各開発情報はgit対象。サンプルの架空局はテスト専用。

## 使い方

```bash
PYTHONPATH=src python -m cwcontest audit --config examples/allja2026_demo.json --csv examples/allja2026_demo.csv
PYTHONPATH=src python -m unittest discover -s tests -v
# 実運用の交信データと本人確認済みの情報をセットしてから、本人の意思で実行:
PYTHONPATH=src python -m cwcontest export --config examples/allja2026_demo.json --csv examples/allja2026_demo.csv --out output --confirm
```

サンプルは**過去の2026年ALL JA・架空コールサイン・架空の個人情報**で、提出してはいけません。
`--confirm` は宣誓・署名欄について利用者本人がレビューしたことを示す操作です。生成ファイルはアップロードしません。

## QSO入力CSV

`time_jst,band,mode,callsign,sent_rst,sent_nr,rcvd_rst,rcvd_nr,completed`

- `time_jst`: **交信完了時刻**。`2026-04-25T21:10:00+09:00` のような秒・TZ付きJST
- `band`: MHz単位の文字列（例 `7`）。`mode`: `CW`
- `sent_rst` `rcvd_rst`: 3桁RST（例 599）
- `sent_nr` `rcvd_nr`: **RSTを除外**した交換ナンバー（例 10M、25P）
- `completed`: true / false。trueのみ電子ログへ出力、falseはレビューCSVに保持
- 同一バンド・同一局の重複QSOは得点0、記録は保持。時刻順に早いものを得点対象とする
- `scoring_bands` 外の交信は提出ログへ保持するが得点は0
- 終了時刻ジャストに完了した交信は期間外

## 対応状況と制約

- ALL JA / 全市全郡の基本的なCWナンバー形式、ログ記録と得点の概略を実装。
- **全市全郡の市郡区コード実在照合は未実装**（文字数のみを検査）。
- **カテゴリーコードの適法・部門・空中線電力整合検証、FD固有ルール、6m AND DOWN、支部ローカルルール、交信時刻の確定判断は未実装**。運用前に対応追加とJARL確認が必要。
- QSOの日時/交換内容の正確性を機械で保証するものではありません。
- ExcelレビューCSVはExcelの表計算用。zLog CSV形式との互換性は検証していません。
- JARL R2.1形式は公式資料に基づく試作出力ですが、提出先の受理を確認していません。
- 受信した符号を自動採番する場合、信号の再確認・訂正・コンテスト中のログ確定の仕様を別途設計します。

## 公式根拠（2026年11月5日参照）

- https://www.jarl.org/Japanese/1_Tanoshimo/1-1_Contest/allja_rules.html
- https://www.jarl.org/Japanese/1_Tanoshimo/1-1_Contest/acag_rules.html
- https://www.jarl.org/Japanese/1_Tanoshimo/1-1_Contest/logformat.html
- https://www.jarl.org/Japanese/1_Tanoshimo/1-1_Contest/q_and_a.html
- https://use.zlog.org/manual/zLog%E3%81%A7%E3%81%A7%E3%81%8D%E3%82%8B%E3%81%93%E3%81%A8.html

仕様詳細は `SPEC.md` を参照してください。
