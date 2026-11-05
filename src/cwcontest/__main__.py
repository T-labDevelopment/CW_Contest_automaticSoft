"""CLI: PYTHONPATH=src python -m cwcontest audit|export ..."""
import argparse
from pathlib import Path
import sys
from .core import read_config, read_qsos, score_and_audit, jarlelog_r21, excel_csv, LogValidationError


def main() -> int:
    p = argparse.ArgumentParser(description="JARL国内CWコンテストログ試作ツール (送受信機能なし)")
    p.add_argument("command", choices=("audit", "export"))
    p.add_argument("--config", required=True)
    p.add_argument("--csv", required=True)
    p.add_argument("--out", default="output")
    p.add_argument("--confirm", action="store_true",
                   help="内容を本人が確認し、宣誓文と署名を付けることに同意した場合に指定")
    args = p.parse_args()
    try:
        config = read_config(args.config)
        audit = score_and_audit(config, read_qsos(args.csv))
    except (LogValidationError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for k in ("total_qsos", "complete_qsos", "incomplete_qsos", "dupes",
              "points", "multipliers", "total_score"):
        print(f"{k}: {audit[k]}")
    if args.command == "audit":
        print("検証のみ。提出ファイルは作成していません。")
        return 0
    if not args.confirm:
        print("提出ファイル生成には、ログ内容と宣誓・署名を本人が確認した後に --confirm が必要です。", file=sys.stderr)
        return 3
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / (config["station_callsign"].replace("/", "_").lower() + ".em")
    log_path.write_text(jarlelog_r21(config, audit), encoding="utf-8")
    (out / "review.csv").write_text(excel_csv(audit), encoding="utf-8-sig")
    print(f"JARL R2.1ドラフト: {log_path}")
    print(f"ExcelレビューCSV: {out / 'review.csv'}")
    print("※JARL受付システムでの実検証・提出は未実施。自動送信も行いません。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
