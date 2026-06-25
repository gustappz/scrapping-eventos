"""Roda o scraper Visite RJ.

follow_five_days: quantos blocos de 5 dias a frente puxar (1 = só os próximos 5 dias).
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
    raw = args[0] if args else input("Quantos períodos de 5 dias avançar (1 a 4)? ").strip()
    try:
        ffd = int(raw)
    except ValueError:
        print("Valor inválido.")
        return
    if ffd < 1 or ffd > 15:
        print("Use 1 a 15.")
        return

    base = Path(__file__).resolve().parent.parent
    data_dir = base / "output" / "data"
    logs_dir = base / "output" / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = LoggerService(log_dir=str(logs_dir))
    db = DatabaseCSV(str(data_dir))

    folder = "visiterj"
    (data_dir / folder).mkdir(parents=True, exist_ok=True)
    csv_path = f"{folder}/Rio-de-Janeiro.csv"
    full = data_dir / csv_path
    if full.exists():
        full.unlink()

    sb = SeleniumBase(logger)
    # Cloudflare bloqueia. Usa undetected-chromedriver (stealth).
    sb.initialize_driver(headless=False, stealth=True)
    n = 0
    try:
        nav = VisiteNavigator(sb, logger)
        urls = nav.get_events_URLs_RJ(ffd)
        for i, url in enumerate(urls, 1):
            logger.info(f"[{i}/{len(urls)}] Visite RJ event")
            dto = nav.get_info_of_event_RJ(url, downloads_folder=str(base / "output" / "downloads"))
            if dto:
                db.concatenate(asdict(dto), csv_path)
                n += 1
    finally:
        sb.quit_driver()
    db.group_csv_to_xlsx(folder, "visiteRJ.xlsx")
    print(f"\n[OK] {n} eventos -> output/data/visiteRJ.xlsx")


if __name__ == "__main__":
    main()
