# 自動CW交信と国内コンテストの先行実装レビュー（2026-11-05）

対象: JARL CW AutoContest Rev.A（初代IC-7300＋Windows PC＋USB Audio/CI-V）

本書は2026-11-05時点の公開一次資料・作者説明をもとにした**設計レビュー**。紹介製品を実機試験した意味ではない。先行例を丸ごと組み込むのではなく、特定の機能の要求条件・試験条件へ落とし込む。既存のv0.3.0試作コードは変更しない。

## 先行例と自動化の範囲（重要）

| 先行例 | 実際に説明・公開されている範囲 | 今回の利用方針 | 注意点 |
|---|---|---|---|
| DeepCW / deepcw-engine | ONNX CW復号、WAV Python/Node例、WebのSINGLE/MULTI | 第一候補のデコーダー・アダプター | 自動QSOソフトではない。ライブAPI/同一ピッチ重畳の精度は未実証 |
| PreppComm DitStorm Cypher V3.2 | Auto-CQ/Auto-Responder、相手局判別、トークン展開、繰返し、空き周波数確認・受信再送、手動介入 | 交信FSM、安全な送信判断、セッション上の局識別の参考 | 開発元説明によるもので、IC-7300やJARLコンテストでの実証ではない |
| Kvasha HAM Radio CW Keyer | CQ/ANSのマクロ、Enter等の操作に連動する送信、番号再送、ADIFログ | 交信フロー・マクロテンプレートの参考 | **AUTO Contestでも人間が受信内容を入力する**。完全自動受信・局選択ではない |
| zLog令和版 / cwListener | 国内CWコンテスト向けメッセージ、部分コピー・NR?、重複、zLog用CW復号プラグイン（α） | 国内規約・部分コールと交換NRのルール、ログ連携評価 | cwListenerは完全自動QSOではない |
| Morse Runner Community Edition | ALLJA/ACAGパイルアップ模擬、QRM/QRN/QSB、不完全な送信・呼び直し | 検証音声の生成・誤呼出率比較 | 模擬相手局であり、現実の無線機との完全自動交信ではない |
| CWSD (yo6ssw) | IC-7300でのhamlib rigctld・cwdaemon・USB音声ストリーム等 | USB/CATインターフェースの比較参考 | Linux主体、CWはDTR/RTS。Rev.AのCI-V `17h`方式を勝手に変更しない |
| WSJT-X Auto Seq | FT8等で自動応答順序を支援 | 「交信終了後に送信許可を解除する」安全パターンの参考 | CWそのものの先行実装ではない |

## 実装へ反映する要件

### P1: 自局宛てかを判断する

- 受信文字列のコールサインを単純抽出するだけでなく、`<自局CALL> DE <呼出局>` 等の構文と送受の局面から「自局に応答している局」を識別する。
- 自局送信と受信音声のサイドトーン混入、他局同士の交信、近傍局のCQを誤って自分へのコールと扱わない。
- 過度な構文固定を避け、日本で使う省略形・単独コールなどの認識も**推測し過ぎず**候補として扱う。

### P2: 取捨選択して1局を固定する

- 全局復号は不要。候補のうち正しい識別ができそうな1局を優先選択する。
- 候補の選択基準: コール完全性 → デコード継続性 → 同一バンドの非重複 → 必要なら手動優先。
- 一度選択した局にロックし、途中の別局の送信を選択局の交換ナンバーへ混ぜない。
- 判別不能なら`AGN?`、`NR?`、部分コール確認を行うか、一定回数で中断する。

### P3: マクロとログを結びつける

- 自局CALL、相手CALL、交換NR、送信済みNR、CW速度などをマクロ変数として扱う。
- 各マクロ変数が**未確定なら送信を拒否**する。未知の番号・コールをでっち上げない。
- 番号再送時は**前回相手へ送信した値**を使い、連番採用コンテストで再送のたびに値を増やさない。ALL JA/ACAGの固定地域番号にも対応できる構造にする。
- 相手局が異なるコール・不完全NR・既交信だった場合の再送・再確認・記録処理を明示する。
- 交信が成立したときだけログ確定し、未成立候補は監査用の一時記録として区別する。

### P4: 送信の作法と異常時処理

- CQ再送は受信監視により待機・抑制可能にする。タイマーだけで盲目的に送信を繰り返さない。
- 本装置の送信停止・電源/USB切断・CI-Vエラー時は再自動送信させない。
- 自動送信はデフォルトOFF、オペレーター承認を維持。送信待ち行列が残っていても復帰時に自動再開しない。
- 特定局の呼出中は他局からの割込みと自局宛ての応答を区別する。
- WindowsのソフトウェアからのCI-V `17h`文字送信と中止機能を主方式として維持する。

### P5: オフラインの再現試験

- DeepCWのモデルは実装時に**コミット＋ONNXファイルハッシュ＋メタデータ＋依存バージョン**で固定する。公開リポジトリの現行README/ライセンス表示はMIT（2026-11-05再確認）。取り込み時はそのリビジョンのLICENSE実体を再確認する。
- Morse Runner CEでALLJA/ACAG、QRM/QRN/QSB、異WPM・近接ピッチのパイルアップ等を試験音声へ録音し、正解局ラベルを別途設定する。テストに使う版を固定する。
- 合成混合音声／Morse Runnerの模擬音声／IC-7300からの実USB AF録音は別データセットとし、精度の数字を混同しない。
- 初期評価指標: 呼出先誤判定率、誤ログ確定、選択した1局の完全コピー率、QSO成立率、QSO/分、再送率、応答までの時間。
- 同一ピッチ・同時符号により観測情報が潰れる場合の**完全解読は保証しない**。

## プロジェクトへの反映順序（提案）

1. 模擬CW音声 → DeepCW候補抽出アダプター（送信しない）。
2. セッション状態機械へ「宛先判定」「1局ロック」「未確定トークン拒否」を追加（模擬送信のみ）。
3. Morse Runner CEなどを利用した自動化テストとオペレーター承認UI。
4. IC-7300 USB Audio実機検証、オフラインでの選局検証。
5. 監督下の送信テスト。完全自律での公式コンテスト参加はJARLの確認が先。

## 規約・公平性

- JARL 2026 ALL JA規約はCWスキマー等の受信支援を認める。ただし完全自律ロボット運用を明示して承認していると解釈しない。
- CQ WW 2026年10月7日改訂では、人間による局呼出・周波数変更・ログ確定を要求し、自律ロボットは禁止。**JARLとは別大会の規約であり、同一視しない**。
- JARLへの問い合わせで「自動局選択、送信、ログ確定」の各段階を具体的に提示し、適用できる参加部門・オペレーター管理条件を確認するまで競技参加用の完全自動送信は許可しない。

## 出典（直接資料と区別）

- DeepCW engine: https://github.com/e04/deepcw-engine
- DeepCWの作者による説明: https://zenn.dev/e04/articles/1408d7b03d78cb
- DitStorm 2026-08-17開発元記事: https://morsenexus.com/blogs/news/an-automated-station-with-manners
- Kvasha manual Part1/Part2/Part3: https://www.kvasha.us/guide/ham-radio-cw-keyer-morse-code/ ; https://www.kvasha.us/guide/ham-radio-cw-keyer-morse-code-part2/ ; https://www.kvasha.us/guide/ham-radio-cw-keyer-morse-code-part3/
- zLog CW運用説明: https://use.zlog.org/manual/%E4%BA%A4%E4%BF%A1%E6%96%B9%E6%B3%95%EF%BC%88%EF%BC%A3%EF%BC%B7%EF%BC%89.html
- zLogプラグインリスト: https://use.zlog.org/plugins.html
- cwListener: https://github.com/jucky154/cwListener
- 東京大学無線クラブとcwListener取材: https://www.fbnews.jp/202212/musennosekai/
- Morse Runner CE 1.84の作者案内: https://599010103.blog84.fc2.com/blog-entry-1214.html
- Morse Runner CE 1.84リリース: https://github.com/w7sst/MorseRunner/releases/tag/v1.84
- CWSD: https://github.com/yo6ssw/cwsd
- WSJT-X Auto Seq: https://wsjtx.github.io/wsjtx/guide-full.html
- JARL ALL JA 2026: https://www.jarl.org/Japanese/1_Tanoshimo/1-1_Contest/allja_rules.html
- CQ WW 2026規約改訂: https://cqww.com/blog/2026-rule-changes/
