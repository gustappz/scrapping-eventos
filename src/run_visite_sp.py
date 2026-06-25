"""Roda o scraper Visite SP.

months_ahead: meses a frente de hoje (1 a 6).
"""
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import SeleniumBase
from database import DatabaseCSV
from logger import LoggerService
from scraping.visite_navigator import VisiteNavigator


def main():
    args = sys.argv[1:]
    raw = args[0] if args else input("Quantos meses a frente puxar (1 a 6)? ").strip()
    try:
        m = int(raw)
    except ValueError:
        print("Valor inválido.")
        return
    if m < 1 or m > 6:
        print("Use 1 a 6.")
        return

    base = Path(__file__).resolve().parent.parent
    data_dir = base / "output" / "data"
    logs_dir = base / "output" / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = LoggerService(log_dir=str(logs_dir))
    db = DatabaseCSV(str(data_dir))

    folder = "visitesp"
    (data_dir / folder).mkdir(parents=True, exist_ok=True)
    csv_path = f"{folder}/Sao-Paulo.csv"
    full = data_dir / csv_path
    if full.exists():
        full.unlink()

    sb = SeleniumBase(logger)
    sb.initialize_driver(headless=False, stealth=True)
    n = 0
    try:
        nav = VisiteNavigator(sb, logger)
        urls = nav.get_events_URLs_SP(m)
        for i, url in enumerate(urls, 1):
            logger.info(f"[{i}/{len(urls)}] Visite SP event")
            dto = nav.get_info_of_event_SP(url, downloads_folder=str(base / "output" / "downloads"))
            if dto:
                db.concatenate(asdict(dto), csv_path)
                n += 1
    finally:
        sb.quit_driver()
    db.group_csv_to_xlsx(folder, "visiteSP.xlsx")
    print(f"\n[OK] {n} eventos -> output/data/visiteSP.xlsx")


if __name__ == "__main__":
    main()
