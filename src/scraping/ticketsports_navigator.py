"""TicketSports scraper (post-2026 redesign).

Site novo:
- URL antiga `/Calendario/Todos-os-organizadores/Todas-as-modalidades/RJ` virou 404.
- URL nova: `/calendar/filters` (Next.js, JS-rendered).
- Cards na listagem ja trazem: nome, cidade/UF, data, imagem, href.
- Paginação por botão "Carregar mais eventos".

Estratégia: deixar o site carregar todos os eventos (clicar "Carregar mais" até
desaparecer), parsear cards via BeautifulSoup direto do page_source, filtrar por
estado em código.
"""
import re
import time
from pathlib import Path
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from base import SeleniumBase
from eventDTO import EventDTO
from logger import LoggerService
from utils import brazilian_states

CALENDAR_URL = "https://www.ticketsports.com.br/calendar/filters"
EVENTS_API_URL = "https://www.ticketsports.com.br/api/events/list"
DETAIL_API_URL = "https://www.ticketsports.com.br/api/events/detail"
EVENT_BASE = "https://www.ticketsports.com.br"


class TicketSportsNavigator:
    def __init__(self, webdriver: SeleniumBase, logger: LoggerService):
        self.webdriver = webdriver
        self.logger = logger

    def _extract_modalities(self, text: str) -> list[str]:
        found = []
        aliases = {
            "corrida": "Corrida",
            "running": "Corrida",
            "run": "Corrida",
            "caminhada": "Caminhada",
            "ciclismo": "Ciclismo",
            "bike": "Ciclismo",
            "mtb": "MTB",
            "trail": "Trail",
            "trail run": "Trail",
            "maratona": "Maratona",
            "triathlon": "Triathlon",
            "triatlo": "Triathlon",
            "aquathlon": "Aquathlon",
            "duathlon": "Duathlon",
            "natação": "Natação",
            "natacao": "Natação",
        }
        low = (text or "").lower()
        for alias, official in aliases.items():
            if re.search(rf"(?:^|[^a-z0-9]){re.escape(alias)}(?:[^a-z0-9]|$)", low):
                if official not in found:
                    found.append(official)
        return found

    def _apply_modalities_to_category(self, dto: EventDTO, text: str) -> None:
        mods = self._extract_modalities(text)
        if mods:
            existing = [x.strip() for x in (dto.amenities or "").split(",") if x.strip()]
            for mod in mods:
                if mod not in existing:
                    existing.append(mod)
            dto.amenities = ", ".join(existing)
            dto.category = "Todos, Esportivos, " + ", ".join(mods)
        else:
            dto.category = "Todos, Esportivos"

    def get_events_URLs(self, state: str) -> List[EventDTO]:
        """Carrega todos os eventos do calendário e filtra pelo estado (sigla, ex 'RJ').

        Retorna lista de EventDTO já com os campos do card (sem preço/descrição).
        Para enriquecer com descrição/preço, chamar `enrich_event(dto)` em sequência.
        """
        state = (state or "").strip().upper()
        if state and state not in brazilian_states:
            self.logger.warning(f"Estado '{state}' não reconhecido; vou retornar TODOS os eventos.")
            state = ""

        api_events = self._get_events_from_api(state)
        if api_events:
            return api_events
        if not self.webdriver:
            return []

        self.webdriver.navigate_to(CALENDAR_URL)
        # espera o JS popular os primeiros cards
        try:
            self.webdriver.wait_for_element(By.XPATH, "//a[contains(@href, '/e/')]", timeout=20)
        except Exception:
            self.logger.error("Nenhum card de evento apareceu após carregar /calendar/filters.")
            return []
        self.logger.info("Calendar carregado.")

        # Aplica filtro "6 meses". Espera mais (DOM precisa terminar de hidratar
        # antes do dropdown funcionar) e tenta varias vezes.
        time.sleep(5)
        applied = False
        for attempt in range(4):
            try:
                periodo_btn = self.webdriver.driver.find_element(
                    By.XPATH, "//button[contains(text(),'Selecione o período')]"
                )
                periodo_btn.click()
                time.sleep(3)
                seis = self.webdriver.driver.find_element(
                    By.XPATH, "//button[normalize-space(text())='6 meses']"
                )
                seis.click()
                self.logger.info(f"Filtro '6 meses' aplicado (tentativa {attempt+1}).")
                applied = True
                time.sleep(4)
                break
            except Exception as e:
                self.logger.warning(f"Tentativa {attempt+1} de aplicar filtro falhou: {str(e)[:100]}")
                time.sleep(3)
        if not applied:
            self.logger.warning("Filtro '6 meses' nao aplicado - so eventos da semana.")

        # Coleta incremental: parseia após cada click. Assim, mesmo que a listagem
        # resete no fim, já temos tudo que apareceu.
        collected: dict[str, EventDTO] = {}

        def harvest():
            try:
                html_now = self.webdriver.driver.execute_script(
                    "return document.documentElement.outerHTML;"
                )
            except Exception:
                html_now = self.webdriver.driver.page_source
            for c in self._parse_cards(html_now):
                key = c.webSite or c.event_url_internal
                if key and key not in collected:
                    collected[key] = c

        harvest()
        self._click_load_more_until_exhausted(on_after_click=harvest)
        # last harvest after pagination
        harvest()

        cards = list(collected.values())
        self.logger.info(f"Eventos únicos coletados: {len(cards)}")

        # Filtra por estado
        if state:
            cards = [c for c in cards if c.state.upper() == state]
            self.logger.info(f"Após filtro estado={state}: {len(cards)} eventos.")
        return cards

    def _get_events_from_api(self, state: str) -> List[EventDTO]:
        """Coleta a listagem pelo endpoint JSON do site."""
        try:
            r = requests.get(
                EVENTS_API_URL,
                params={"quantity": 1000, "atlheteId": 0, "term": ""},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json",
                },
                timeout=35,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            self.logger.warning(f"API TicketSports falhou; usando Selenium: {e}")
            return []
        if not isinstance(payload, list):
            return []

        out: List[EventDTO] = []
        seen = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            address_short = str(item.get("address") or "")
            city, uf = self._parse_city_state(address_short)
            if state and uf.upper() != state:
                continue
            event_url = str(item.get("uri") or "")
            if not event_url or event_url in seen:
                continue
            seen.add(event_url)
            title = str(item.get("title") or "").strip()
            image_url = str(item.get("logoImageSource") or "")
            price = item.get("price") or item.get("fullPrice") or 0.0
            try:
                price = float(str(price).replace(",", ".")) if price else 0.0
            except Exception:
                price = 0.0
            out.append(EventDTO(
                eventName=title,
                dateEvents=str(item.get("date") or ""),
                desc="",
                webSite=event_url,
                city=city,
                state=uf,
                price=price,
                image=image_url,
                category="Todos, Esportivos",
                produtor=str(item.get("organizer") or ""),
                local="",
                bairro="",
                address=address_short,
                instagram="https://www.instagram.com/ticketsports",
                site_extracao="TicketSports",
                image_url=image_url,
                event_url_internal=event_url,
            ))
        self.logger.info(f"TicketSports API: {len(out)} eventos coletados para estado={state or 'TODOS'}.")
        return out

    @staticmethod
    def _parse_city_state(address: str) -> tuple[str, str]:
        if not address:
            return "", ""
        parts = [p.strip() for p in address.split(",") if p.strip()]
        if len(parts) >= 2 and re.fullmatch(r"[A-Z]{2}", parts[-1]):
            return ", ".join(parts[:-1]), parts[-1]
        m = re.search(r"\b([A-Z]{2})\b", address)
        return (parts[0] if parts else "", m.group(1) if m else "")

    def _click_load_more_until_exhausted(self, max_clicks: int = 80, on_after_click=None):
        """Clica 'Carregar mais eventos' até o botão sumir, OU até não vir mais evento novo,
        OU até a página resetar (alguns sites zeram a lista quando dá ruim)."""

        def count_events() -> int:
            return len(self.webdriver.driver.find_elements(By.XPATH, "//a[contains(@href,'/e/')]"))

        previous_count = count_events()
        clicks = 0
        no_growth_streak = 0
        while clicks < max_clicks:
            try:
                btn = self.webdriver.driver.find_element(
                    By.XPATH,
                    "//button[contains(translate(text(), 'CARREGAMORE', 'carregamore'), 'carregar')]",
                )
            except NoSuchElementException:
                self.logger.info("Botão 'Carregar mais' não encontrado mais. Fim da paginação.")
                break

            if not btn.is_displayed() or not btn.is_enabled():
                self.logger.info("Botão 'Carregar mais' desabilitado/oculto. Fim.")
                break

            self.logger.info(f"Clicando 'Carregar mais' (tentativa #{clicks + 1}) — atual={previous_count} eventos")
            try:
                self.webdriver.scroll_to_element(btn, factor=0.85)
                time.sleep(0.5)
                btn.click()
            except Exception:
                try:
                    self.webdriver.driver.execute_script("arguments[0].click();", btn)
                except Exception as e:
                    self.logger.error(f"Falha ao clicar carregar mais: {e}")
                    break
            time.sleep(1.3)
            if on_after_click:
                try:
                    on_after_click()
                except Exception:
                    pass

            now = count_events()
            # Página resetou (lista zerou). Em vez de continuar, paramos.
            if now == 0 and previous_count > 0:
                self.logger.warning("Listagem resetou para 0 — provavelmente fim/erro. Parando.")
                # tenta voltar pra estado anterior com Ctrl+Z? Não rola; só paramos.
                break
            # Não cresceu. Conta como tentativa "vazia"; se acontecer 2x, paramos.
            if now <= previous_count:
                no_growth_streak += 1
                if no_growth_streak >= 2:
                    self.logger.info(f"Sem crescimento em 2 cliques seguidos (atual={now}). Parando.")
                    break
            else:
                no_growth_streak = 0
            previous_count = now
            clicks += 1

    def _parse_cards(self, html: str) -> List[EventDTO]:
        """Extrai EventDTOs dos cards de evento na página de listagem."""
        soup = BeautifulSoup(html, "html.parser")
        seen_urls = set()
        out: List[EventDTO] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/e/" not in href:
                continue
            if href.startswith("/"):
                event_url = EVENT_BASE + href
            elif href.startswith("http"):
                event_url = href
            else:
                continue
            if event_url in seen_urls:
                continue
            seen_urls.add(event_url)

            strong = a.find("strong")
            name = strong.get_text(strip=True) if strong else ""
            ps = a.find_all("p")
            city = ""
            state = ""
            date_str = ""
            for p in ps:
                txt = p.get_text(" ", strip=True)
                # "Cidade, UF"
                m_loc = re.match(r"^(.+),\s*([A-Z]{2})$", txt)
                if m_loc and not city:
                    city, state = m_loc.group(1).strip(), m_loc.group(2).strip()
                    continue
                # "Data do evento: 17/05/2026"
                m_date = re.search(r"Data do evento[:\s]+(\d{2}/\d{2}/\d{4})", txt)
                if m_date and not date_str:
                    date_str = m_date.group(1)

            img = a.find("img")
            image_url = img.get("src", "") if img else ""

            out.append(EventDTO(
                eventName=name,
                dateEvents=date_str,
                desc="",
                webSite=event_url,
                city=city,
                state=state,
                price=0.0,
                image=image_url,
                category="Todos, Esportivos",
                produtor="",
                local="",
                bairro="",
                address="",
                instagram="https://www.instagram.com/ticketsports",
                site_extracao="TicketSports",
                image_url=image_url,
                event_url_internal=event_url,
            ))
        return out

    @staticmethod
    def _event_id_from_url(url: str) -> str:
        m = re.search(r"-(\d+)(?:\D*)?$", url or "")
        return m.group(1) if m else ""

    def _enrich_event_from_api(self, dto: EventDTO, downloads_folder: str = "downloads") -> bool:
        from taxonomia import classify_category
        from utils import (extract_bairro_from_address, handle_description,
                            download_image_named, find_minimum_price_of_text)

        event_id = self._event_id_from_url(dto.webSite or dto.event_url_internal)
        if not event_id:
            return False
        try:
            r = requests.get(
                DETAIL_API_URL,
                params={"eventId": event_id},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json",
                    "Referer": dto.webSite,
                },
                timeout=25,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            self.logger.warning(f"Detalhe API TicketSports falhou {dto.webSite}: {e}")
            return False
        if not isinstance(data, dict):
            return False

        if data.get("title"):
            dto.eventName = str(data["title"]).strip()
            dto.titleEvents = dto.eventName
        if data.get("date"):
            dto.dateEvents = str(data["date"])
        if data.get("organizer"):
            dto.produtor = str(data["organizer"]).strip()

        contents = []
        for content in data.get("eventContents") or []:
            if not isinstance(content, dict):
                continue
            title = str(content.get("title") or "").strip()
            desc = str(content.get("description") or "").strip()
            if title or desc:
                contents.append(f"{title}. {desc}".strip())
        if data.get("description"):
            contents.insert(0, str(data["description"]))
        full_text = handle_description(" ".join(contents))
        if full_text:
            dto.desc = full_text[:2000]

        address = str(data.get("address") or dto.address or "").strip()
        if address:
            dto.address = address
            if ":" in address and not dto.local:
                dto.local = address.split(":", 1)[0].strip()
            if not dto.bairro:
                dto.bairro = extract_bairro_from_address(address)

        img = str(data.get("headerImageSource") or data.get("logoImageSource") or dto.image_url or "")
        if img:
            dto.image_url = img
            if downloads_folder:
                slug = dto.webSite.rstrip("/").split("/")[-1]
                local = download_image_named(downloads_folder, img, "ticketsports", slug)
                if local:
                    dto.image = local

        price = 0.0
        for key in ("price", "fullPrice", "discount"):
            try:
                value = data.get(key)
                if value not in (None, ""):
                    price = float(str(value).replace(",", "."))
                    if price:
                        break
            except Exception:
                pass
        if not price:
            price = find_minimum_price_of_text(full_text)
        if price:
            dto.price = price

        self._apply_modalities_to_category(
            dto,
            f"{dto.eventName} {full_text} {data.get('activityType') or ''} {data.get('modalities') or ''}",
        )
        return True

    def enrich_event_selenium(self, dto: EventDTO, downloads_folder: str = "downloads") -> EventDTO:
        """Versão LENTA (Selenium per page) que pega descrição COMPLETA + modalidade
        do corpo renderizado da página. ~5s por evento. Vale a pena pra TicketSports
        porque o JSON-LD só tem descrição genérica e a modalidade só aparece
        depois que o JS roda."""
        import time as _t
        from taxonomia import classify_category
        from utils import (handle_description, download_image_named,
                           extract_bairro_from_address,
                           find_minimum_price_of_text)
        try:
            self.webdriver.navigate_to(dto.webSite)
            _t.sleep(3.5)
            try:
                self.webdriver.driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight * 0.5);"
                )
            except Exception:
                pass
            _t.sleep(1.5)
            body = ""
            try:
                body = self.webdriver.driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                pass

            # Descrição: tudo entre "Data do evento" e "Sobre a Plataforma"
            if body:
                start = body.find("Data do evento")
                if start < 0:
                    start = 0
                end = body.find("Sobre a Plataforma")
                if end < 0:
                    end = body.find("PARTICIPANTES")
                if end < 0:
                    end = len(body)
                desc_chunk = body[start:end]
                desc_clean = handle_description(desc_chunk)
                if len(desc_clean) > len(dto.desc):
                    dto.desc = desc_clean[:2000]

                price = find_minimum_price_of_text(body)
                if price:
                    dto.price = price

                # Endereço: linha após "Local do evento:"
                m_addr = re.search(r"Local do evento:\s*(.+?)(?:\n|$)", body)
                if m_addr and not dto.address:
                    dto.address = m_addr.group(1).strip()

                self._apply_modalities_to_category(dto, f"{dto.eventName} {body}")

            # Bairro
            if not dto.bairro and dto.address:
                dto.bairro = extract_bairro_from_address(dto.address)

            # Imagem local
            if dto.image_url and downloads_folder:
                slug = dto.webSite.rstrip("/").split("/")[-1]
                local = download_image_named(downloads_folder, dto.image_url, "ticketsports", slug)
                if local:
                    dto.image = local
        except Exception as e:
            self.logger.error(f"Selenium enrich TicketSports falhou {dto.webSite}: {e}")
        return dto

    def enrich_event(self, dto: EventDTO, downloads_folder: str = "downloads") -> EventDTO:
        """Busca dados extras via requests + JSON-LD (RÁPIDO).
        Para descrição completa + modalidade real, prefira `enrich_event_selenium`."""
        from taxonomia import classify_category
        from utils import (extract_bairro_from_address, handle_description,
                            download_image_named, find_minimum_price_of_text)
        if self._enrich_event_from_api(dto, downloads_folder):
            return dto
        try:
            r = requests.get(
                dto.webSite,
                headers={"User-Agent":
                         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"},
                timeout=15,
            )
            if r.status_code != 200:
                return dto
            html = r.text
            soup = BeautifulSoup(html, "html.parser")

            # 1) JSON-LD com @type SportsEvent — fonte primária
            import json
            ld_data = None
            for s in soup.find_all("script", type="application/ld+json"):
                try:
                    raw = s.string or s.get_text() or ""
                    if not raw.strip():
                        continue
                    j = json.loads(raw)
                    items = j if isinstance(j, list) else [j]
                    for c in items:
                        if isinstance(c, dict) and c.get("@type") in ("SportsEvent", "Event"):
                            ld_data = c
                            break
                    if ld_data:
                        break
                except Exception:
                    continue

            if ld_data:
                # Endereço
                loc = ld_data.get("location")
                if isinstance(loc, dict):
                    addr = loc.get("address")
                    if isinstance(addr, dict):
                        a = addr.get("name") or addr.get("streetAddress") or ""
                        if a:
                            dto.address = a.strip()
                    elif isinstance(addr, str):
                        dto.address = addr.strip()
                    if not dto.address and loc.get("name"):
                        dto.address = loc["name"].strip()
                    if loc.get("name") and not dto.local:
                        dto.local = loc["name"].strip()
                # Organizador (produtor)
                org = ld_data.get("organizer")
                if isinstance(org, dict) and org.get("name"):
                    dto.produtor = org["name"].strip()
                # Descrição
                if ld_data.get("description"):
                    dto.desc = handle_description(ld_data["description"])[:2000]

            # 2) og:description fallback (geralmente mais completo)
            og = soup.find("meta", attrs={"property": "og:description"})
            if og and og.get("content"):
                content = handle_description(og["content"])
                if not dto.desc or len(content) > len(dto.desc):
                    dto.desc = content[:2000]

            # 3) Modalidade via regex no body do HTML (sem precisar de Selenium)
            body_text = soup.get_text(" ", strip=True)
            price = find_minimum_price_of_text(body_text)
            if price:
                dto.price = price

            # 4) Bairro
            if not dto.bairro and dto.address:
                dto.bairro = extract_bairro_from_address(dto.address)

            # 5) Categoria + modalidade do site
            self._apply_modalities_to_category(dto, f"{dto.eventName} {body_text}")

            # 6) Instagram do organizador (procura no body)
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "instagram.com/" in href.lower():
                    dto.instagram = href
                    break

            # 7) Imagem local
            if dto.image_url and downloads_folder:
                slug = dto.webSite.rstrip("/").split("/")[-1]
                local = download_image_named(downloads_folder, dto.image_url, "ticketsports", slug)
                if local:
                    dto.image = local
        except Exception as e:
            self.logger.error(f"Falha ao enriquecer {dto.webSite}: {e}")
        return dto
