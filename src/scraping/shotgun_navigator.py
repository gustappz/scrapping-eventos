"""Shotgun.live scraper.

Site tem proteção anti-bot agressiva (bloqueou requisições simples com 429).
Solução: undetected-chromedriver (Chrome em modo stealth, igual Visite RJ/SP).

Os cards na listagem ja trazem:
  - nome do evento (img alt / p.font-bold)
  - venue (div.text-muted-foreground)
  - data em ISO no atributo `datetime` do <time>
  - preço em R$
  - imagem
  - URL relativa (/pt-br/events/<slug>)

Pagina por click em "Ver mais".
"""
import re
import time
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from base import SeleniumBase
from eventDTO import EventDTO
from logger import LoggerService
from utils import remove_accents

BASE = "https://shotgun.live"
CITY_URL = "https://shotgun.live/pt-br/cities/{slug}"

CITY_TO_STATE = {
    "Rio de Janeiro": "RJ",
    "São Paulo": "SP",
    "Niterói": "RJ",
    "Porto Alegre": "RS",
    "Curitiba": "PR",
    "Belo Horizonte": "MG",
    "Salvador": "BA",
    "Brasília": "DF",
    "Recife": "PE",
    "Florianópolis": "SC",
    "Fortaleza": "CE",
}


def city_to_slug(city: str) -> str:
    s = remove_accents(city or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    return s


class ShotgunNavigator:
    def __init__(self, webdriver: SeleniumBase, logger: LoggerService):
        self.webdriver = webdriver
        self.logger = logger

    def get_events_URLs(self, city: str) -> List[EventDTO]:
        slug = city_to_slug(city)
        base_url = CITY_URL.format(slug=slug)
        all_events: dict[str, EventDTO] = {}
        page = 0
        max_pages = 20
        while page <= max_pages:
            url = base_url if page == 0 else f"{base_url}?page={page}"
            self.webdriver.navigate_to(url)
            try:
                self.webdriver.wait_for_element(
                    By.XPATH, "//a[contains(@href, '/events/')]", timeout=25,
                )
            except Exception:
                if page == 0:
                    self.logger.error(f"Shotgun: nao carregou cidade {city}.")
                    return []
                else:
                    self.logger.info(f"Pagina {page} sem eventos. Fim.")
                    break
            time.sleep(2)
            html = self.webdriver.driver.execute_script(
                "return document.documentElement.outerHTML;"
            )
            page_events = self._parse_cards(html, city)
            new_count = 0
            for e in page_events:
                if e.webSite not in all_events:
                    all_events[e.webSite] = e
                    new_count += 1
            self.logger.info(f"Pagina {page}: +{new_count} novos eventos (total {len(all_events)})")
            if new_count == 0:
                self.logger.info("Sem eventos novos. Fim da paginação.")
                break
            # Existe link "Ver mais"?
            try:
                self.webdriver.driver.find_element(
                    By.XPATH,
                    "//a[contains(translate(., 'VERMAIS', 'vermais'), 'ver mais') and contains(@href, 'page=')]"
                )
                page += 1
            except NoSuchElementException:
                self.logger.info("Sem botão 'Ver mais' na página. Fim.")
                break
        events = list(all_events.values())
        self.logger.info(f"Shotgun {city}: {len(events)} eventos coletados.")
        return events

    def _parse_cards(self, html: str, city: str) -> List[EventDTO]:
        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        out: List[EventDTO] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/events/" not in href:
                continue
            event_url = urljoin(BASE, href)
            if event_url in seen:
                continue
            seen.add(event_url)

            # Image + alt (name)
            img = a.find("img")
            image_url = ""
            name_alt = ""
            if img:
                image_url = img.get("src", "")
                name_alt = img.get("alt", "")

            # Name: prefere p.font-bold dentro do card
            name_tag = a.find("p", class_=re.compile(r"font-bold"))
            name = (name_tag.get_text(strip=True) if name_tag else name_alt) or ""

            # Venue: text-muted-foreground na primeira ocorrencia textual
            venue_tag = a.find("div", class_=re.compile(r"text-muted-foreground"))
            venue = venue_tag.get_text(strip=True) if venue_tag else ""

            # Data: <time datetime="2026-05-16T...">
            date_iso = ""
            time_tag = a.find("time", attrs={"datetime": True})
            if time_tag:
                date_iso = time_tag["datetime"]
            date_str = self._fmt_iso_date(date_iso)

            # Preço: procura R$
            price = self._extract_price(a.get_text(" ", strip=True))

            out.append(EventDTO(
                eventName=name,
                dateEvents=date_str,
                desc="",
                webSite=event_url,
                city=city,
                state=CITY_TO_STATE.get(city, ""),
                price=price,
                image=image_url,
                category="Todos, Festas",
                produtor="",
                local=venue,
                bairro="",
                address="",
                instagram="https://www.instagram.com/shotgun.br",
                site_extracao="Shotgun",
                image_url=image_url,
                event_url_internal=event_url,
            ))
        return out

    @staticmethod
    def _fmt_iso_date(iso: str) -> str:
        if not iso:
            return ""
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
        if m:
            y, mo, d = m.groups()
            return f"{d}/{mo}/{y}"
        return iso

    @staticmethod
    def _extract_price(text: str) -> float:
        m = re.findall(r"R\$\s* ?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+(?:,\d{2})?)", text)
        if not m:
            return 0.0
        # primeiro = menor; pega o primeiro encontrado
        try:
            return float(m[0].replace(".", "").replace(",", "."))
        except Exception:
            return 0.0

    def enrich_event_selenium(self, dto: EventDTO, downloads_folder: str = "downloads") -> EventDTO:
        """Lento (~5s/evento). Pega MOOD direto do body renderizado.
        Use só se Nath precisa MOOD exato — caso contrario `enrich_event` (rapido)
        usa classifier da descricao."""
        import time as _t
        from taxonomia import classify_category, classify_genres
        from utils import (extract_bairro_from_address, download_image_named)
        if not (self.webdriver and self.webdriver.driver):
            return self.enrich_event(dto, downloads_folder)
        try:
            self.webdriver.navigate_to(dto.webSite)
            _t.sleep(4)
            self.webdriver.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            _t.sleep(2)
            body = self.webdriver.driver.find_element(By.TAG_NAME, "body").text

            # MOOD: lista de gêneros entre "Mood" e "Localização"
            m = re.search(r"Mood\s*\n(.+?)(?:Localização|Local )", body, re.DOTALL)
            mood_text = m.group(1) if m else ""

            # Junta com a description já extraída pra dar mais contexto ao classifier
            classifier_text = (mood_text + " " + dto.desc).lower()
            genres = classify_genres(classifier_text)
            if genres:
                dto.genresGroup = genres

            # Categoria (default Festas + qualquer outra detectada)
            cat = classify_category(f"{dto.eventName} {dto.desc}")
            if "Festas" not in cat:
                cat = cat.rstrip(",") + ", Festas" if cat else "Todos, Festas"
            dto.category = cat

            # Endereço completo da seção "Localização"
            m_addr = re.search(r"Localização\s*\n([^\n]+)\n([^\n]+)", body)
            if m_addr and not dto.address:
                dto.local = m_addr.group(1).strip()
                dto.address = m_addr.group(2).strip()

            # Bairro
            if not dto.bairro and dto.address:
                dto.bairro = extract_bairro_from_address(dto.address)

            # Imagem local
            if dto.image_url and downloads_folder:
                slug = dto.webSite.rstrip("/").split("/")[-1]
                local = download_image_named(downloads_folder, dto.image_url, "shotgun", slug)
                if local:
                    dto.image = local
        except Exception as e:
            self.logger.error(f"Selenium enrich Shotgun falhou {dto.webSite}: {e}")
        return dto

    def enrich_event(self, dto: EventDTO, downloads_folder: str = "downloads") -> EventDTO:
        """Enriquece o DTO via JSON-LD MusicEvent + categoria/gênero oficial +
        bairro extraído do endereço + imagem local."""
        import cloudscraper
        import json
        from taxonomia import classify_category, classify_genres
        from utils import extract_bairro_from_address, handle_description, download_image_named
        try:
            scraper = getattr(self, "_cs", None)
            if scraper is None:
                scraper = cloudscraper.create_scraper()
                self._cs = scraper
            r = scraper.get(dto.webSite, timeout=15)
            if r.status_code != 200:
                return dto
            ld_blocks = re.findall(
                r'<script type="application/ld\+json">(.+?)</script>',
                r.text, re.DOTALL,
            )
            event_ld = None
            for block in ld_blocks:
                try:
                    j = json.loads(block)
                except Exception:
                    continue
                items = j if isinstance(j, list) else [j]
                for c in items:
                    if isinstance(c, dict) and c.get("@type") in ("MusicEvent", "Event", "SportsEvent"):
                        event_ld = c
                        break
                if event_ld:
                    break
            if event_ld:
                desc = event_ld.get("description", "")
                if desc:
                    dto.desc = handle_description(desc)[:2000]
                org = event_ld.get("organizer")
                if isinstance(org, dict) and org.get("name"):
                    dto.produtor = org["name"].strip()
                offers = event_ld.get("offers")
                if offers and not dto.price:
                    first = offers[0] if isinstance(offers, list) and offers else offers
                    if isinstance(first, dict):
                        try:
                            dto.price = float(first.get("price", 0))
                        except Exception:
                            pass
                loc = event_ld.get("location")
                if isinstance(loc, dict):
                    addr = loc.get("address")
                    if isinstance(addr, dict):
                        parts = [addr.get(k, "") for k in
                                 ("streetAddress", "addressLocality",
                                  "addressRegion", "postalCode")]
                        addr_str = ", ".join(p for p in parts if p)
                        if addr_str:
                            dto.address = addr_str
                    elif isinstance(addr, str):
                        dto.address = addr
                    if not dto.local and loc.get("name"):
                        dto.local = loc["name"]
            # Bairro a partir do endereço
            if not dto.bairro and dto.address:
                dto.bairro = extract_bairro_from_address(dto.address)
            # Categoria oficial (sempre Festas pra Shotgun)
            cat_text = f"{dto.eventName} {dto.desc}"
            dto.category = classify_category(cat_text)
            if "Festas" not in dto.category:
                dto.category = dto.category.rstrip(",") + ", Festas" if dto.category else "Todos, Festas"
            # Gêneros: extrai a parte 'Mood' do body text. Formato:
            # "Mood\nPOP\nDANCE\nEURODANCE\n...\nLocalização"
            mood_text = ""
            body_text = re.search(
                r"Mood[\s\n]+(.+?)[\s\n]+Localização",
                r.text.replace("\\n", "\n"), re.DOTALL,
            )
            if body_text:
                mood_text = body_text.group(1)
            dto.genresGroup = classify_genres(mood_text + " " + cat_text)
            # Baixa imagem
            if dto.image_url and downloads_folder:
                slug = dto.webSite.rstrip("/").split("/")[-1]
                local = download_image_named(downloads_folder, dto.image_url, "shotgun", slug)
                if local:
                    dto.image = local
        except Exception as e:
            self.logger.error(f"Falha ao enriquecer Shotgun {dto.webSite}: {e}")
        return dto
