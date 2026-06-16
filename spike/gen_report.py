"""
快速生成报告用于调试（不依赖 DatabaseManager）
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MPLBACKEND"] = "Agg"

from reporter.report_html import create_html_generator
from storage.db import create_database_manager

DB_PATH = "data/eyefocus.db"


def main():
    # 找到数据最丰富的 session
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""
        SELECT session_id FROM focus_records
        GROUP BY session_id ORDER BY COUNT(*) DESC LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()

    if not row:
        print("无数据"); return

    sid = row[0]
    print(f"使用 session: {sid}")

    # 用 DatabaseManager 运行完整 pipeline (含 insights)
    db = create_database_manager(DB_PATH)
    db.initialize()
    gen = create_html_generator(db)
    html = gen.generate_report_with_insights(sid)

    path = "reports/debug_report.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"报告已生成: {path}")
    db.close()


if __name__ == "__main__":
    main()
