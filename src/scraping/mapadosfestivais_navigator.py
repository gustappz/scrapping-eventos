"""MapaDosFestivais scraper.

Strategy (sites mudou em 2026):
- Lista de eventos: lê o sitemap WordPress (job_listing-sitemap.xml). Pega tudo de uma vez,
  sem precisar de Chrome automatizado nem clicar "Carregar mais".
- Página de cada evento: usa JSON-LD (<script type="application/ld+json"> com @type=Event)
  pra pegar nome, data e local — é estrutura padrão schema.org, muito mais estável que CSS.
- Complementa com meta tags og:image, og:description e seletores HTML pra endereço,
  link de compra, etc.
"""
import json
import re
import time
import uuid
import html as html_lib
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, List, Optional

import requests
from bs4 import BeautifulSoup

from eventDTO import EventDTO
from logger import LoggerService
from taxonomia import classify_category, classify_genres
from utils import (
    brazilian_states,
    download_image_named,
    extract_bairro_from_address,
    find_city_on_address,
    find_minimum_price_of_text,
    find_state_on_address,
    first_date,
    handle_description,
    month_map,
    remove_accents,
)

SITEMAP_URL = "https://mapadosfestivais.com.br/job_listing-sitemap.xml"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.5",
}


class MapaDosFestivaisNavigator:
    def __init__(self, logger: LoggerService, downloads_folder: str = "downloads"):
        self.logger = logger
        self.downloads_folder = downloads_folder
        Path(downloads_folder).mkdir(parents=True, exist_ok=True)

    def get_events_URLs(self) -> List[str]:
        """Pega todas as URLs de eventos do sitemap."""
        self.logger.info(f"Lendo sitemap: {SITEMAP_URL}")
        r = requests.get(SITEMAP_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
        event_urls = [u for u in urls if "/eventos/" in u]
        self.logger.info(f"Encontradas {len(event_urls)} URLs de eventos no sitemap.")
        return event_urls

    def get_params_from_event(self, event_url: str) -> Optional[EventDTO]:
        """Lê uma página de evento e devolve um EventDTO."""
        try:
            r = requests.get(event_url, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except Exception as e:
            self.logger.error(f"Falha ao baixar {event_url}: {e}")
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # 1) JSON-LD com @type Event — fonte primária (mais estável).
        event_ld = self._extract_event_ld(soup)

        # 2) Título: prefere JSON-LD; fallback p/ h1.
        name = ""
        if event_ld and event_ld.get("name"):
            name = event_ld["name"].strip()
        if not name and soup.find("h1"):
            name = soup.find("h1").get_text(strip=True)
        name = html_lib.unescape(name)

        # 3) Datas: SÓ A PRIMEIRA (Nath pediu).
        date_str = ""
        if event_ld:
            start = event_ld.get("startDate", "")
            if start:
                date_str = self._fmt_date(start)
        date_str = first_date(date_str)

        # 4) Imagem: og:image (URL). Baixa local depois.
        image_url = ""
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            image_url = og["content"]

        # 5) Endereço: tenta class="address" e variações; se não, do JSON-LD location.
        address = self._extract_address(soup, event_ld)

        # 6) Descrição: og:description + corpo da página. handle_description já
        # limpa emojis/paragrafos/html.
        description = ""
        ogd = soup.find("meta", property="og:description")
        if ogd and ogd.get("content"):
            description = ogd["content"]
        if not description:
            description = self._extract_ld_description(soup)
        # Também procura por descrição mais longa no body
        body_desc = ""
        for tag in soup.find_all(["div", "section"], class_=lambda x: x and "description" in (x or "").lower()):
            t = tag.get_text(" ", strip=True)
            if len(t) > len(body_desc):
                body_desc = t
        if len(body_desc) > len(description):
            description = body_desc
        description = handle_description(description)
        body_text = soup.get_text(" ", strip=True)

        if not date_str:
            date_str = self._extract_date_from_text(f"{name} {description} {body_text[:5000]}")

        city = self._city_from_address(address) or find_city_on_address(address)
        state_sigla = (
            find_state_on_address(address)
            or self._state_from_event_ld(event_ld)
            or self._state_from_text(f"{address} {description}")
        )

        # 7) Preço: MENOR (regex no corpo da página, conforme Nath).
        price = find_minimum_price_of_text(body_text)

        # 8) Categoria oficial (Festivais, Shows, etc).
        cat_text = f"{name} {description}"
        category = self._extract_site_category(soup, cat_text)
        # 9) Gêneros (do nome + descrição).
        genres = classify_genres(cat_text)

        # 10) Local (nome do espaço): primeira parte do endereço.
        local = ""
        if address:
            local = address.split(",")[0].strip()

        # 11) Bairro (regex melhorado).
        bairro = extract_bairro_from_address(address)

        # 12) Imagem local — baixa pra pasta downloads/mapadosfestivais
        from utils import safe_filename
        slug = event_url.rstrip("/").split("/")[-1]
        image_local = ""
        if image_url:
            image_local = download_image_named(
                self.downloads_folder, image_url, "mapadosfestivais", slug
            )

        # 13) Instagram: procura @<conta> ou link instagram.com no corpo
        instagram = self._extract_instagram(soup)

        dto = EventDTO(
            eventName=name,
            dateEvents=date_str,
            desc=description[:2000],
            webSite=event_url,
            city=city,
            state=state_sigla,
            price=price,
            image=image_local or image_url,
            genresGroup=genres,
            category=category,
            produtor=self._extract_organizer(event_ld),
            local=local,
            bairro=bairro,
            address=address,
            instagram=instagram or "https://www.instagram.com/mapadosfestivais",
            site_extracao="MapaDosFestivais",
            image_url=image_url,
            event_url_internal=event_url,
        )
        return dto

    def _extract_instagram(self, soup) -> str:
        """Procura link de Instagram (clube oficial do evento) na página."""
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "instagram.com/" in href.lower():
                # ignora links de redes sociais do MapaDosFestivais oficial
                if "mapadosfestivais" in href.lower():
                    continue
                return href
        raw = str(soup)
        for href in re.findall(r"https?://(?:www\.)?instagram\.com/[^\"'<>\s)]+", raw, re.I):
            if "mapadosfestivais" not in href.lower():
                return href.rstrip("/")
        m = re.search(r"@([A-Za-z0-9._]{3,40})", soup.get_text(" ", strip=True))
        if m and "mapadosfestivais" not in m.group(1).lower():
            return f"https://www.instagram.com/{m.group(1)}/"
        return ""

    def _extract_site_category(self, soup: BeautifulSoup, text: str) -> str:
        """Usa a divisão do próprio Mapa: Festivais ou Shows e Turnês."""
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            label = a.get_text(" ", strip=True).lower()
            if href.strip() == "#shows-turne" or label == "shows":
                return "Todos, Shows"
        if re.search(r"\b(show|turn[eê]|apresenta[cç][aã]o)\b", text or "", re.I):
            return "Todos, Shows"
        return "Todos, Festivais"

    def _extract_organizer(self, event_ld) -> str:
        if not event_ld:
            return ""
        org = event_ld.get("organizer")
        if isinstance(org, dict) and org.get("name"):
            return org["name"].strip()
        if isinstance(org, str):
            return org.strip()
        return ""

    def scrape_all(self, save_callback=None, on_progress=None, should_stop=None) -> List[EventDTO]:
        urls = self.get_events_URLs()
        out: List[EventDTO] = []
        for i, url in enumerate(urls, start=1):
            if should_stop and should_stop():
                self.logger.info("Scraping MapaDosFestivais interrompido pelo usuário.")
                break
            self.logger.info(f"[{i}/{len(urls)}] Processando {url}")
            dto = self.get_params_from_event(url)
            if dto:
                out.append(dto)
                if save_callback:
                    save_callback(dto)
            if on_progress:
                on_progress(i, len(urls))
            time.sleep(0.4)  # gentil com o servidor
        self.logger.info(f"Total de eventos coletados: {len(out)}")
        return out

    # -------- helpers --------

    def _extract_event_ld(self, soup: BeautifulSoup) -> Optional[dict]:
        for s in soup.find_all("script", type="application/ld+json"):
            raw = s.string or s.get_text() or ""
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except Exception:
                # Some sites wrap multiple JSON-LD in @graph; try light cleanup
                try:
                    data = json.loads(raw.strip().rstrip(";"))
                except Exception:
                    continue
            candidates = []
            if isinstance(data, list):
                candidates = data
            elif isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    candidates = data["@graph"]
                else:
                    candidates = [data]
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                t = c.get("@type", "")
                if t == "Event" or (isinstance(t, list) and "Event" in t):
                    return c
        return None

    def _fmt_date(self, raw: str) -> str:
        if not raw:
            return ""
        # ISO "2026-08-07 00:00:00" or "2026-08-07T00:00:00+00:00"
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if m:
            y, mo, d = m.groups()
            return f"{d}/{mo}/{y}"
        return raw

    def _extract_address(self, soup: BeautifulSoup, event_ld: Optional[dict]) -> str:
        page_text = soup.get_text("\n", strip=True)

        # Seção completa "LOCALIZAÇÃO" costuma trazer endereço melhor que o
        # resumo do topo.
        m = re.search(
            r"LOCALIZAÇÃO\s*\n(.+?)(?:\nComo Chegar|\nSEGUIR O FESTIVAL|\nONDE FICAR|\nAVALIAÇÕES)",
            page_text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            loc = " ".join(x.strip() for x in m.group(1).splitlines() if x.strip())
            loc = re.sub(r"\s+", " ", loc).strip()
            if loc and not re.match(r"^(SEGUIR O FESTIVAL|Instagram|Site Oficial)\b", loc, re.I):
                return loc

        # Cabeçalho dos eventos do Mapa: "pin-location-event" seguido do local.
        m = re.search(
            r"pin-location-event\s*\n(.+?)(?:\nR\$|\n\d{4}-\d{2}-\d{2}|\nComprar|\nRECEBER|\nLINEUP)",
            page_text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            loc = " ".join(x.strip() for x in m.group(1).splitlines() if x.strip())
            loc = re.sub(r"\s+", " ", loc).strip()
            if loc:
                return loc

        # 1) class regex contendo "address"
        el = soup.find(class_=re.compile(r"address", re.IGNORECASE))
        if el:
            txt = el.get_text(" ", strip=True)
            # Remove "Como Chegar" / "Get Directions" do final
            txt = re.sub(r"\s*(Como Chegar|Get Directions)\s*$", "", txt, flags=re.IGNORECASE)
            if txt:
                return txt

        # 2) class regex contendo "pin-location" / "location-event"
        for pat in [r"pin-location", r"location-event", r"event-location", r"map-block"]:
            el = soup.find(class_=re.compile(pat, re.IGNORECASE))
            if el:
                txt = el.get_text(" ", strip=True)
                if txt:
                    return re.sub(r"\s*(Como Chegar|Get Directions)\s*$", "", txt,
                                  flags=re.IGNORECASE)

        # 3) JSON-LD location
        if event_ld:
            loc = event_ld.get("location")
            if isinstance(loc, dict):
                addr = loc.get("address")
                if isinstance(addr, str):
                    return addr
                if isinstance(addr, dict):
                    parts = [addr.get(k, "") for k in
                             ("streetAddress", "addressLocality", "addressRegion", "addressCountry")]
                    return ", ".join(p for p in parts if p)
                name = loc.get("name", "")
                if name:
                    return name
        return ""

    def _extract_ld_description(self, soup: BeautifulSoup) -> str:
        for s in soup.find_all("script", type="application/ld+json"):
            raw = s.string or s.get_text() or ""
            if not raw.strip():
                continue
            try:
                parsed = json.loads(raw.strip().rstrip(";"))
            except Exception:
                continue
            items = parsed if isinstance(parsed, list) else [parsed]
            for item in list(items):
                if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                    items.extend(item["@graph"])
                if isinstance(item, dict) and item.get("description"):
                    return str(item["description"])
        return ""

    def _extract_date_from_text(self, text: str) -> str:
        if not text:
            return ""
        year_match = re.search(r"\b(20\d{2})\b", text)
        fallback_year = year_match.group(1) if year_match else str(time.localtime().tm_year)
        m = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
        if m:
            return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"
        m = re.search(
            r"\b(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)(?:\s+de\s+(20\d{2}))?\b",
            text,
            re.IGNORECASE,
        )
        if not m:
            return ""
        month = month_map.get(remove_accents(m.group(2)).lower())
        if not month:
            return ""
        return f"{int(m.group(1)):02d}/{month}/{m.group(3) or fallback_year}"

    def _state_from_event_ld(self, event_ld: Optional[dict]) -> str:
        if not event_ld:
            return ""
        loc = event_ld.get("location")
        if not isinstance(loc, dict):
            return ""
        addr = loc.get("address")
        if isinstance(addr, dict):
            region = str(addr.get("addressRegion") or "")
            if region in brazilian_states:
                return region
            return find_state_on_address(region)
        return ""

    def _state_from_text(self, text: str) -> str:
        low = remove_accents(text or "").lower()
        for uf, name in sorted(brazilian_states.items(), key=lambda x: len(x[1]), reverse=True):
            norm_name = remove_accents(name).lower()
            if re.search(rf"\b{re.escape(norm_name)}\b", low):
                return uf
        return find_state_on_address(text)

    def _city_from_address(self, address: str) -> str:
        if not address:
            return ""
        parts_dash = [p.strip() for p in re.split(r"\s+-\s+", address) if p.strip()]
        if len(parts_dash) == 2 and "," not in parts_dash[1]:
            return parts_dash[1]
        return ""

    def _extract_ticket_url(self, soup: BeautifulSoup) -> str:
        for a in soup.find_all("a"):
            text = a.get_text(strip=True).upper()
            href = a.get("href", "")
            if not href or href.startswith("#"):
                continue
            if "COMPRAR" in text or "INGRESSO" in text:
                return href
        return ""

    def _extract_bairro(self, address: str) -> str:
        if not address:
            return ""
        # Em endereços tipo "Jockey Club, Praça Santos Dumont, 31, 350 - Gávea, Rio de Janeiro, Rio de Janeiro"
        # o bairro geralmente vem depois do "-".
        m = re.search(r"-\s*([^,]+),", address)
        if m:
            return m.group(1).strip()
        return ""
