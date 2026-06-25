"""Ingresse scraper (versao 2026).

Site: Next.js SPA. URL /search/?location=BRA-<UF>.
Pagina renderiza via JS, mas os cards na listagem ja trazem:
  - nome do evento (h3)
  - local/venue (p)
  - data formatada em pt-br (p)
  - imagem (img alt/src)
  - URL relativa (a href)

Detalhes (descricao completa, preco) so renderizam no detalhe, e o detalhe
tambem e JS. Para v1, usamos so dados do card — suficiente pra montar xlsx
util. Adicionar enriquecimento posterior se a usuaria pedir.
"""
import re
import requests
import time
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from base import SeleniumBase
from eventDTO import EventDTO
from logger import LoggerService
from utils import brazilian_states, clean_and_parse_date_ingresse

SEARCH_URL = "https://www.ingresse.com/search/?location=BRA-{state}&language=pt_br&page=1"
BASE = "https://www.ingresse.com"


class IngresseNavigator:
    def __init__(self, webdriver: SeleniumBase, logger: LoggerService):
        self.webdriver = webdriver
        self.logger = logger

    def get_events_URLs(self, state: str) -> List[EventDTO]:
        state = (state or "").strip().upper()
        if state not in brazilian_states:
            self.logger.error(f"Estado '{state}' invalido para Ingresse.")
            return []

        url = SEARCH_URL.format(state=state)
        self.webdriver.navigate_to(url)
        try:
            self.webdriver.wait_for_element(
                By.XPATH, "//a[starts-with(@href, '/') and .//h3]", timeout=20
            )
        except Exception:
            self.logger.error("Listagem do Ingresse nao carregou cards.")
            return []
        time.sleep(2)

        all_events: dict[str, EventDTO] = {}
        self._harvest_into(all_events, state)

        # Pagina por numero. Procura botoes com so um digito (1, 2, 3..).
        page_buttons = self._find_page_buttons()
        self.logger.info(f"Paginas detectadas: {len(page_buttons) or 1}")
        for n in range(2, len(page_buttons) + 1):
            try:
                btn = self.webdriver.driver.find_element(
                    By.XPATH, f"//button[normalize-space(text())='{n}']"
                )
                self.webdriver.scroll_to_element(btn, factor=0.85)
                time.sleep(0.5)
                btn.click()
                time.sleep(2.5)
                self.logger.info(f"Trocou para pagina {n}.")
                self._harvest_into(all_events, state)
            except NoSuchElementException:
                break
            except Exception as e:
                self.logger.error(f"Falha ao paginar para {n}: {e}")
                break

        events = list(all_events.values())
        self.logger.info(f"Ingresse {state}: {len(events)} eventos unicos coletados.")
        return events

    def _find_page_buttons(self) -> list:
        """Retorna lista de botoes de pagina numerados."""
        try:
            btns = self.webdriver.driver.find_elements(
                By.XPATH, "//button[string-length(normalize-space(text())) <= 2 and number(text()) > 0]"
            )
        except Exception:
            btns = []
        # Filtra so os realmente numerados
        out = []
        for b in btns:
            try:
                t = b.text.strip()
                if t.isdigit():
                    out.append(b)
            except Exception:
                pass
        return out

    def _harvest_into(self, store: dict, state: str):
        """Parsea os cards atuais e enfia no dict (chave = event_url)."""
        try:
            html = self.webdriver.driver.execute_script(
                "return document.documentElement.outerHTML;"
            )
        except Exception:
            html = self.webdriver.driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("/"):
                continue
            slug = href.strip("/")
            if not slug or "/" in slug:
                continue
            if any(b in slug for b in (
                "_next", "static", "favicon", "login", "cadastro", "help", "api",
                "sitemap", "ajuda", "sobre", "criar", "contato", "termos", "politica",
                "meia", "parceiros", "blog", "anuncie", "news", "search"
            )):
                continue
            h3 = a.find("h3")
            if not h3:
                continue  # cards de evento sempre tem h3
            name = h3.get_text(strip=True)
            ps = a.find_all("p")
            venue = ps[0].get_text(strip=True) if len(ps) >= 1 else ""
            date_raw = ps[1].get_text(strip=True) if len(ps) >= 2 else ""
            img = a.find("img")
            image_url = img.get("src", "") if img else ""

            event_url = urljoin(BASE, href)
            if event_url in store:
                continue
            store[event_url] = EventDTO(
                eventName=name,
                dateEvents=clean_and_parse_date_ingresse(date_raw),
                desc="",
                webSite=event_url,
                city="",
                state=state,
                price=0.0,
                image=image_url,
                category="Todos, Festas",
                produtor="",
                local=venue,
                bairro="",
                address="",
                instagram="https://www.instagram.com/ingresse",
                site_extracao="Ingresse",
                image_url=image_url,
                event_url_internal=event_url,
            )

    def enrich_event(self, dto: EventDTO, downloads_folder: str = "downloads") -> EventDTO:
        """Visita a página do evento (Selenium) e busca descrição + endereço
        via JSON-LD Event. Lento (~3s/evento) mas confiável.
        Se evento dura multiplos dias, popula `dto.extra_dates` com as datas
        adicionais — o runner gera uma linha pra cada.
        """
        import json
        import re
        import time as _t
        from datetime import datetime as _dt, timedelta as _td
        from taxonomia import classify_category, classify_genres
        from utils import (extract_bairro_from_address, handle_description,
                            download_image_named,
                            extract_ingresse_price_from_event_id)
        start_iso = ""
        end_iso = ""
        api_price_found = False
        try:
            self.webdriver.navigate_to(dto.webSite)
            _t.sleep(4)
            html = self.webdriver.driver.execute_script(
                "return document.documentElement.outerHTML;"
            )
            soup = BeautifulSoup(html, "html.parser")
            page_text = soup.get_text(" ", strip=True)
            api_event = self._fetch_public_event_api(dto.webSite)
            if api_event:
                self._apply_public_event_api(dto, api_event)
                api_price = extract_ingresse_price_from_event_id(str(api_event.get("id") or ""))
                if api_price is not None:
                    dto.price = api_price
                    api_price_found = True
            for s in soup.find_all("script", type="application/ld+json"):
                raw = s.string or s.get_text() or ""
                if not raw.strip():
                    continue
                try:
                    j = json.loads(raw)
                except Exception:
                    continue
                items = j if isinstance(j, list) else [j]
                for c in items:
                    if isinstance(c, dict) and c.get("@type") == "Event":
                        d = c.get("description", "")
                        if d:
                            dto.desc = handle_description(d)[:2000]
                        if c.get("name") and not dto.eventName:
                            dto.eventName = c["name"]
                        # Datas de início/fim (pra gerar linhas multi-dia)
                        start_iso = str(c.get("startDate", ""))
                        end_iso = str(c.get("endDate", ""))
                        loc = c.get("location")
                        if isinstance(loc, dict):
                            if loc.get("name"):
                                dto.local = loc["name"]
                            addr = loc.get("address")
                            if isinstance(addr, dict):
                                parts = [addr.get(k, "") for k in
                                         ("streetAddress", "addressLocality",
                                          "addressRegion", "postalCode")]
                                addr_str = ", ".join(p for p in parts if p)
                                if addr_str:
                                    dto.address = addr_str
                                if addr.get("addressLocality"):
                                    dto.city = addr["addressLocality"]
                        img = c.get("image")
                        if isinstance(img, list) and img:
                            if not dto.image_url:
                                dto.image_url = img[0]
                        elif isinstance(img, str):
                            if not dto.image_url:
                                dto.image_url = img
                        break
            # Eventos multi-dia: gera datas extras
            try:
                if start_iso and end_iso:
                    s_dt = _dt.fromisoformat(start_iso.replace("Z", "+00:00"))
                    e_dt = _dt.fromisoformat(end_iso.replace("Z", "+00:00"))
                    if e_dt.date() > s_dt.date():
                        extra = []
                        cur = s_dt.date() + _td(days=1)
                        while cur <= e_dt.date():
                            extra.append(cur.strftime("%d/%m/%Y"))
                            cur += _td(days=1)
                        dto.extra_dates = extra
                        self.logger.info(
                            f"Evento multi-dia: {dto.dateEvents} + {len(extra)} dias extras"
                        )
            except Exception:
                pass
            # Alguns eventos multi-dia não expõem endDate no JSON-LD, mas
            # trazem datas no texto/título. Usa isso como fallback leve.
            if not dto.extra_dates:
                dto.extra_dates = self._extract_extra_dates_from_text(
                    page_text, dto.dateEvents
                )
            # Bairro do endereço
            if not dto.bairro and dto.address:
                dto.bairro = extract_bairro_from_address(dto.address)
            # Categoria + gênero
            cat_text = f"{dto.eventName} {dto.desc}"
            dto.category = classify_category(cat_text)
            # Ingresse não expõe uma taxonomia consistente na página pública.
            # Usa a classificação pelo texto; se nada for detectado, assume Festas.
            if dto.category == "Todos":
                dto.category = "Todos, Festas"
            dto.genresGroup = classify_genres(cat_text)
            # Instagram
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "instagram.com/" in href.lower():
                    dto.instagram = href
                    break
            # Preço real fica no embedstore, não no JSON-LD da página pública.
            ticket_href = self._find_ticket_href(soup)
            if ticket_href and not api_price_found:
                self._enrich_price_from_ticket_page(dto, ticket_href)
            # Imagem local
            if dto.image_url and downloads_folder:
                slug = dto.webSite.rstrip("/").split("/")[-1]
                local = download_image_named(downloads_folder, dto.image_url, "ingresse", slug)
                if local:
                    dto.image = local
        except Exception as e:
            self.logger.error(f"Falha ao enriquecer Ingresse {dto.webSite}: {e}")
        return dto

    def _fetch_public_event_api(self, event_url: str) -> dict:
        slug = (event_url or "").rstrip("/").split("/")[-1]
        if not slug:
            return {}
        try:
            r = requests.get(
                f"https://api-site.ingresse.com/events/{slug}",
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=15,
            )
            if r.status_code >= 400:
                return {}
            data = r.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _apply_public_event_api(self, dto: EventDTO, data: dict) -> None:
        from datetime import datetime as _dt
        from utils import extract_bairro_from_address, handle_description

        if data.get("title"):
            dto.eventName = str(data["title"]).strip()
            dto.titleEvents = dto.eventName
        if data.get("description"):
            dto.desc = handle_description(str(data["description"]))[:2000]

        dates = []
        for session in data.get("sessions") or []:
            if not isinstance(session, dict):
                continue
            raw = str(session.get("dateTime") or "")
            try:
                dt = _dt.fromisoformat(raw.replace("Z", "+00:00"))
                formatted = dt.strftime("%d/%m/%Y")
                if formatted not in dates:
                    dates.append(formatted)
            except Exception:
                pass
        if dates:
            dto.dateEvents = dates[0]
            extras = [d for d in dates[1:] if d != dto.dateEvents]
            if extras:
                dto.extra_dates = extras

        place = data.get("place")
        if isinstance(place, dict):
            if place.get("name"):
                dto.local = str(place["name"]).strip()
            if place.get("city"):
                dto.city = str(place["city"]).strip()
            if place.get("state"):
                dto.state = str(place["state"]).strip()
            parts = [
                str(place.get("street") or "").strip(),
                str(place.get("city") or "").strip(),
                str(place.get("state") or "").strip(),
                str(place.get("zip") or "").strip(),
            ]
            address = ", ".join(p for p in parts if p)
            if address:
                dto.address = address
            if not dto.bairro and dto.address:
                dto.bairro = extract_bairro_from_address(dto.address)

        poster = data.get("poster")
        if isinstance(poster, dict):
            for key in ("xLarge", "large", "medium", "small"):
                if poster.get(key):
                    dto.image_url = str(poster[key])
                    break

    def _find_ticket_href(self, soup: BeautifulSoup) -> str:
        """A página pública aponta para o embedstore, onde os lotes/preços aparecem."""
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "embedstore.ingresse.com" in href:
                return href
        return ""

    def _enrich_price_from_ticket_page(self, dto: EventDTO, ticket_href: str) -> None:
        import time as _t
        from utils import find_minimum_price_of_text

        try:
            self.webdriver.navigate_to(ticket_href)
            _t.sleep(8)
            body = self.webdriver.driver.find_element(By.TAG_NAME, "body").text
            price = find_minimum_price_of_text(body)
            if price:
                dto.price = price
                return
            if re.search(r"ingressos indispon[ií]veis|esgotado|evento encerrado", body, re.I):
                return
        except Exception as e:
            self.logger.warning(f"Falha ao buscar preço Ingresse {dto.webSite}: {e}")

    def _extract_extra_dates_from_text(self, text: str, first_date: str) -> list:
        from datetime import datetime as _dt
        from utils import month_map, remove_accents

        if not text:
            return []
        found = []

        for d, m, y in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
            found.append(f"{int(d):02d}/{int(m):02d}/{y}")

        # "22 & 23 de maio de 2026", "22 e 23 de maio"
        for d1, d2, month_name, year in re.findall(
            r"\b(\d{1,2})\s*(?:e|&|\+|,)\s*(\d{1,2})\s*(?:de\s+)?([A-Za-zÀ-ÿ]+)(?:\s+de\s+(\d{4}))?",
            text,
            re.IGNORECASE,
        ):
            month = month_map.get(remove_accents(month_name).lower())
            if not month:
                continue
            y = year or str(_dt.now().year)
            found.extend([f"{int(d1):02d}/{month}/{y}", f"{int(d2):02d}/{month}/{y}"])

        unique = []
        for d in found:
            if d != first_date and d not in unique:
                unique.append(d)
        return unique
