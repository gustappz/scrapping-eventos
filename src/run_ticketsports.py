"""Roda o scraper do TicketSports filtrado por estado.

Uso:
    python run_ticketsports.py            # pergunta o estado
    python run_ticketsports.py RJ         # passa direto
    python run_ticketsports.py RJ --enrich   # também busca descrição/preço (lento)
"""
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import DatabaseCSV
from logger import LoggerService
from base import SeleniumBase
from scraping.ticketsports_navigator import TicketSportsNavigator


def main():
    args = [a for a in sys.argv[1:] if a not in ("--enrich", "--no-enrich")]
    # Enrichment ligado por padrão. --no-enrich pula a 2a passada.
    enrich = "--no-enrich" not in sys.argv

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

    folder = "ticketsports"
    (data_dir / folder).mkdir(parents=True, exist_ok=True)
    csv_path = f"{folder}/{state}.csv"
    full_csv = data_dir / csv_path
    if full_csv.exists():
        full_csv.unlink()

    sb = SeleniumBase(logger)
    # Chrome stealth ajuda a evitar problemas de paginação que aconteciam no Edge.
    sb.initialize_driver(headless=False, stealth=True)
    try:
        nav = TicketSportsNavigator(sb, logger)
        events = nav.get_events_URLs(state)
        if enrich:
            for i, e in enumerate(events, 1):
                logger.info(f"[enrich {i}/{len(events)}] {e.webSite}")
                nav.enrich_event(e, downloads_folder=str(base / "output" / "downloads"))
        for e in events:
            db.concatenate(asdict(e), csv_path)
    finally:
        sb.quit_driver()

    db.group_csv_to_xlsx(folder, "ticketsports.xlsx")
    xlsx_path = data_dir / "ticketsports.xlsx"
    print(f"\n[OK] xlsx gerado em: {xlsx_path}")
    print(f"[OK] {len(events)} eventos para o estado {state}.")


if __name__ == "__main__":
    main()
