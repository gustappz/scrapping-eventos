"""Roda o scraper do Ingresse por estado."""
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import SeleniumBase
from database import DatabaseCSV
from logger import LoggerService
from scraping.ingresse_navigator import IngresseNavigator


def main():
    args = sys.argv[1:]
    state = (args[0] if args else input("Digite a sigla do estado (RJ, SP, MG...): ")).strip().upper()
    if not state:
        print("Estado vazio. Abortando.")
        return

    base = Path(__file__).resolve().parent.parent
    data_dir = base / "output" / "data"
    logs_dir = base / "output" / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = LoggerService(log_dir=str(logs_dir))
    db = DatabaseCSV(str(data_dir))

    folder = "ingresse"
    (data_dir / folder).mkdir(parents=True, exist_ok=True)
    csv_path = f"{folder}/{state}.csv"
    full_csv = data_dir / csv_path
    if full_csv.exists():
        full_csv.unlink()

    sb = SeleniumBase(logger)
    sb.initialize_driver(headless=True)
    events = []
    try:
        nav = IngresseNavigator(sb, logger)
        events = nav.get_events_URLs(state)
        # Enriquece com descrição + endereço completo via JSON-LD (Selenium em cada)
        for i, e in enumerate(events, 1):
            if i % 10 == 0:
                logger.info(f"Enriquecendo {i}/{len(events)} eventos...")
            nav.enrich_event(e, downloads_folder=str(base / "output" / "downloads"))
        for e in events:
            row = asdict(e)
            extras = list(row.pop("extra_dates", []) or [])
            db.concatenate(row, csv_path)
            for d in extras:
                extra_row = dict(row)
                extra_row["dateEvents"] = d
                db.concatenate(extra_row, csv_path)
    finally:
        sb.quit_driver()

    db.group_csv_to_xlsx(folder, "ingresse.xlsx")
    xlsx_path = data_dir / "ingresse.xlsx"
    print(f"\n[OK] xlsx gerado em: {xlsx_path}")
    print(f"[OK] {len(events)} eventos coletados para {state}.")


if __name__ == "__main__":
    main()
