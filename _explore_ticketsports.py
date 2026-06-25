"""Abre o site novo do TicketSports, espera renderizar via JS, dumpa HTML pra inspecao."""
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
from logger import LoggerService
from base import SeleniumBase


def main():
    logger = LoggerService(log_dir="output/logs")
    sb = SeleniumBase(logger)
    sb.initialize_driver(headless=True)
    try:
        urls = [
            ("home", "https://www.ticketsports.com.br/"),
            ("calendar", "https://www.ticketsports.com.br/calendar/filters"),
        ]
        for name, url in urls:
            print(f"\n========== {name}: {url} ==========")
            sb.navigate_to(url)
            time.sleep(6)  # deixa o JS renderizar
            sb.scroll_to_bottom()
            time.sleep(2)
            html = sb.driver.page_source
            out = Path(f"_dump_{name}.html")
            out.write_text(html, encoding="utf-8")
            print(f"  Salvo: {out.absolute()} ({len(html)} bytes)")
            # Tenta listar links de evento visiveis
            anchors = sb.driver.find_elements("xpath", "//a[contains(@href,'/event') or contains(@href,'/e/')]")
            print(f"  Anchors com /event ou /e/: {len(anchors)}")
            for a in anchors[:10]:
                try:
                    print("   ", a.get_attribute("href"))
                except Exception:
                    pass
    finally:
        sb.quit_driver()


if __name__ == "__main__":
    main()
