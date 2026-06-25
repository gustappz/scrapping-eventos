"""Roda o scraper Shotgun por cidade."""
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import SeleniumBase
from database import DatabaseCSV
from logger import LoggerService
from scraping.shotgun_navigator import ShotgunNavigator, city_to_slug


def main():
    args = sys.argv[1:]
    city = " ".join(args) if args else input("Digite a cidade (ex: São Paulo): ").strip()
    if not city:
        print("Cidade vazia. Abortando.")
        return

    base = Path(__file__).resolve().parent.parent
    data_dir = base / "output" / "data"
    logs_dir = base / "output" / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = LoggerService(log_dir=str(logs_dir))
    db = DatabaseCSV(str(data_dir))

    folder = "shotgun"
    (data_dir / folder).mkdir(parents=True, exist_ok=True)
    slug = city_to_slug(city)
    csv_path = f"{folder}/{slug}.csv"
    full = data_dir / csv_path
    if full.exists():
        full.unlink()

    sb = SeleniumBase(logger)
    # Shotgun bloqueia. Chrome stealth.
    sb.initialize_driver(headless=False, stealth=True)
    events = []
    try:
        nav = ShotgunNavigator(sb, logger)
        events = nav.get_events_URLs(city)
        # Enrichment: descrição + produtor + endereço via JSON-LD MusicEvent
        for i, e in enumerate(events, 1):
            if i % 25 == 0:
                logger.info(f"Enriquecendo {i}/{len(events)} eventos...")
            nav.enrich_event(e, downloads_folder=str(base / "output" / "downloads"))
        for e in events:
            db.concatenate(asdict(e), csv_path)
    finally:
        sb.quit_driver()

    db.group_csv_to_xlsx(folder, "shotgun.xlsx")
    xlsx_path = data_dir / "shotgun.xlsx"
    print(f"\n[OK] xlsx gerado em: {xlsx_path}")
    print(f"[OK] {len(events)} eventos para {city}.")


if __name__ == "__main__":
    main()
