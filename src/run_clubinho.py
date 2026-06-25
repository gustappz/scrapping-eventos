"""Roda o scraper do Clubinho filtrado por cidade.

Uso:
    python run_clubinho.py                  # pergunta a cidade
    python run_clubinho.py "São Paulo"
    python run_clubinho.py sao-paulo
"""
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import DatabaseCSV
from logger import LoggerService
from scraping.clubinho_scraper import ClubinhoScraper, CITY_MAPPING, format_city_name


def main():
    args = sys.argv[1:]
    if args:
        city = " ".join(args)
    else:
        print("Cidades disponíveis:")
        for c in CITY_MAPPING:
            print(f"  - {c}")
        city = input("\nDigite a cidade: ").strip()
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

    folder = "clubinho"
    (data_dir / folder).mkdir(parents=True, exist_ok=True)
    # slug pra nome do arquivo
    slug = CITY_MAPPING.get(city) or format_city_name(city)
    csv_path = f"{folder}/{slug}.csv"
    full_csv = data_dir / csv_path
    if full_csv.exists():
        full_csv.unlink()

    nav = ClubinhoScraper(logger=logger, downloads_folder=str(base / "output" / "downloads"))
    events = nav.get_params_from_city(city, fetch_details=True)
    for e in events:
        db.concatenate(asdict(e), csv_path)

    db.group_csv_to_xlsx(folder, "clubinho.xlsx")
    xlsx_path = data_dir / "clubinho.xlsx"
    print(f"\n[OK] xlsx gerado em: {xlsx_path}")
    print(f"[OK] {len(events)} eventos coletados para {city}.")


if __name__ == "__main__":
    main()
