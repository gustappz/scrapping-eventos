"""Roda o scraper do MapaDosFestivais e gera xlsx final."""
import os
import sys
from dataclasses import asdict
from pathlib import Path

# Permite rodar como script direto a partir de src/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import DatabaseCSV
from logger import LoggerService
from scraping.mapadosfestivais_navigator import MapaDosFestivaisNavigator


def main():
    base = Path(__file__).resolve().parent.parent  # .../scraping_claude
    data_dir = base / "output" / "data"
    logs_dir = base / "output" / "logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = LoggerService(log_dir=str(logs_dir))
    db = DatabaseCSV(str(data_dir))

    folder = "mapadosfestivais"
    (data_dir / folder).mkdir(parents=True, exist_ok=True)
    csv_path = f"{folder}/Geral.csv"

    # zera CSV antigo deste run
    full_csv = data_dir / csv_path
    if full_csv.exists():
        full_csv.unlink()

    nav = MapaDosFestivaisNavigator(logger=logger, downloads_folder=str(base / "output" / "downloads"))

    def save(dto):
        db.concatenate(asdict(dto), csv_path)

    nav.scrape_all(save_callback=save)
    db.group_csv_to_xlsx(folder, "mapadosfestivais.xlsx")

    xlsx_path = data_dir / "mapadosfestivais.xlsx"
    print(f"\n[OK] xlsx gerado em: {xlsx_path}")


if __name__ == "__main__":
    main()
