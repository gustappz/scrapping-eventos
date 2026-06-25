"""Clubinho de Ofertas scraper.

Estrategia: API Algolia direta (sem Selenium). As chaves do scraper original
ainda funcionam em 2026. Para detalhes de preco/venue, complementa com a API
interna `/api/products/{id}/variations/single`.
"""
import json
import re
import time
import unicodedata
from typing import Iterable, List, Optional

import cloudscraper
from bs4 import BeautifulSoup

from eventDTO import EventDTO
from logger import LoggerService
from utils import handle_description

ALGOLIA_URL = "https://cum4v9330e-3.algolianet.com/1/indexes/*/queries"
ALGOLIA_PARAMS = {
    "x-algolia-agent": (
        "Algolia for JavaScript (3.35.1); Browser (lite); "
        "JS Helper (2.28.1); vue-instantsearch 1.7.0"
    ),
    "x-algolia-application-id": "CUM4V9330E",
    "x-algolia-api-key": "e44ddfef706279649b24a5051fccfc56",
}
INDEX_NAME = "search_products_index"
HITS_PER_PAGE = 50

# Cidades suportadas (slugs do Clubinho). Mesmas do scraper original.
CITY_MAPPING = {
    "Rio de Janeiro": "rio-de-janeiro",
    "São Paulo": "sao-paulo",
    "Niterói": "niteroi",
    "Porto Alegre": "porto-alegre",
    "Goiânia": "goiania",
    "Olinda": "olinda",
    "Minas Gerais": "minas-gerais",
    "São Caetano do Sul": "sao-caetano-do-sul",
}

STATE_ABBR_FROM_NAME = {
    "Rio de Janeiro": "RJ",
    "São Paulo": "SP",
    "Niterói": "RJ",
    "Porto Alegre": "RS",
    "Goiânia": "GO",
    "Olinda": "PE",
    "Minas Gerais": "MG",
    "São Caetano do Sul": "SP",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def format_city_name(city_name: str) -> str:
    s = unicodedata.normalize("NFKD", city_name).encode("ASCII", "ignore").decode()
    return s.strip().lower().replace(" ", "-")


def extract_event_id(url: str) -> Optional[int]:
    if not url:
        return None
    m = re.search(r"-([0-9]+)$", url)
    return int(m.group(1)) if m else None


def format_date(date_str: str) -> str:
    """ISO 'YYYY-MM-DD' -> 'dd/mm/yyyy'. Aceita string vazia."""
    if not date_str:
        return ""
    try:
        from datetime import datetime
        return datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return date_str


class ClubinhoScraper:
    def __init__(self, logger: LoggerService, downloads_folder: str = "downloads"):
        self.logger = logger
        self.downloads_folder = downloads_folder
        self.city_mapping = CITY_MAPPING

    def list_supported_cities(self) -> List[str]:
        return list(self.city_mapping.keys())

    def get_params_from_city(self, city: str, fetch_details: bool = True,
                             should_stop=None, on_progress=None) -> List[EventDTO]:
        """Coleta eventos da cidade. `city` aceita o nome bonito (ex 'Rio de Janeiro')
        ou o slug ('rio-de-janeiro')."""
        slug = self.city_mapping.get(city)
        if not slug:
            slug = format_city_name(city)
        pretty = next((k for k, v in self.city_mapping.items() if v == slug), city)
        self.logger.info(f"Clubinho: buscando eventos em {pretty} ({slug})")

        scraper = cloudscraper.create_scraper()
        out: List[EventDTO] = []
        seen_ids: set = set()

        # Paginação via Algolia
        page = 0
        while True:
            if should_stop and should_stop():
                self.logger.info("Clubinho interrompido pelo usuário.")
                break
            body = {
                "requests": [{
                    "indexName": INDEX_NAME,
                    "params": (
                        f"query=&hitsPerPage={HITS_PER_PAGE}&page={page}"
                        f"&highlightPreTag=__h__&highlightPostTag=__/h__&facets="
                        f"&facetFilters=[[%22city.slug:{slug}%22],[%22has_events:true%22]]"
                    )
                }]
            }
            try:
                r = scraper.post(ALGOLIA_URL, params=ALGOLIA_PARAMS, json=body,
                                 headers={"Content-Type": "application/json"}, timeout=30)
                r.raise_for_status()
            except Exception as e:
                self.logger.error(f"Erro na requisição Algolia (page {page}): {e}")
                break
            data = r.json().get("results", [{}])[0]
            hits = data.get("hits", []) or []
            nb_pages = data.get("nbPages", 1)
            self.logger.info(f"  página {page+1}/{nb_pages}: {len(hits)} hits")
            for hit in hits:
                # Cada hit pode ter várias datas (exhibitions)
                for date_iso in (hit.get("exhibitions") or [""]):
                    if should_stop and should_stop():
                        break
                    dto = self._hit_to_dto(
                        hit, date_iso, scraper,
                        fetch_details=fetch_details,
                        default_pretty_city=pretty,
                        downloads_folder=self.downloads_folder,
                    )
                    if dto is None:
                        continue
                    key = f"{dto.webSite}|{dto.dateEvents}"
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    out.append(dto)
                    if on_progress:
                        on_progress(len(out))
            page += 1
            if page >= nb_pages:
                break
            time.sleep(0.25)

        self.logger.info(f"Clubinho ({pretty}): total {len(out)} eventos (com datas).")
        return out

    def _hit_to_dto(self, hit: dict, date_iso: str, scraper: cloudscraper.CloudScraper,
                    fetch_details: bool, default_pretty_city: str,
                    downloads_folder: str = "downloads") -> Optional[EventDTO]:
        from taxonomia import classify_category, classify_genres
        from utils import download_image_named, round_up_int

        title = hit.get("title") or hit.get("name") or ""
        event_url = hit.get("url") or hit.get("permalink") or hit.get("link", "")
        if not event_url and hit.get("slug"):
            event_url = f"https://clubinhodeofertas.com.br/eventos/{hit['slug']}"

        city_obj = hit.get("city") or {}
        city = city_obj.get("name") or default_pretty_city
        state = city_obj.get("state") or STATE_ABBR_FROM_NAME.get(city, "")

        # imagem (flyer)
        flyer = ""
        f = hit.get("flyer") or {}
        if isinstance(f, dict):
            urls = f.get("urls") or {}
            flyer = urls.get("high") or urls.get("med") or urls.get("low") or ""
        if not flyer:
            flyer = hit.get("image") or ""

        # generos do site (ex: "Teatro Infantil")
        raw_genres = []
        g = hit.get("genres") or []
        if isinstance(g, list):
            raw_genres = [x.get("name", "") if isinstance(x, dict) else str(x) for x in g]
        raw_genres = [n for n in raw_genres if n]

        # Preço mostrado no site. No Clubinho o valor principal é o "sale";
        # "full" é o valor de referência/riscado.
        # Vem em centavos: 6000 = R$ 60.00
        price_val = 0.0
        p = hit.get("price")
        if isinstance(p, dict):
            cents = p.get("sale") or p.get("full") or 0
            try:
                price_val = float(cents) / 100.0
            except Exception:
                price_val = 0.0
        elif isinstance(p, (int, float)):
            price_val = float(p) / 100.0

        venue = hit.get("venue") or ""
        neighborhood = hit.get("neighborhood") or ""
        region = hit.get("region") or ""
        address_parts = [x for x in [venue, neighborhood, region, city, state] if x]
        address = ", ".join(address_parts)

        # Categoria oficial: classifica baseado em gêneros + nome
        cat_text = f"{title} {' '.join(raw_genres)}"
        category = classify_category(cat_text)
        # Genres oficial
        genres_official = classify_genres(cat_text)

        # Imagem local
        image_local = ""
        slug_hint = (hit.get("slug") or title or "clubinho")[:60]
        if flyer:
            image_local = download_image_named(
                downloads_folder, flyer, "clubinho", slug_hint
            )

        dto = EventDTO(
            eventName=title,
            dateEvents=format_date(date_iso),
            desc="",
            webSite=event_url,
            city=city,
            state=state,
            price=price_val,
            image=image_local or flyer,
            genresGroup=genres_official,
            category=category,
            produtor="",
            local=venue,
            bairro=neighborhood,
            address=address,
            instagram="https://www.instagram.com/clubinhodeofertas",
            site_extracao="Clubinho",
            image_url=flyer,
            event_url_internal=event_url,
            raw_categories=raw_genres,
        )
        # Descrição via JSON-LD da página do evento (~0.4s extra por evento).
        if fetch_details and event_url:
            self._enrich_description(dto, scraper)
        return dto

    def _enrich_description(self, dto: EventDTO, scraper):
        """Busca descrição via JSON-LD ou og:description da página HTML."""
        try:
            r = scraper.get(dto.webSite, headers={"User-Agent": UA}, timeout=15)
            if r.status_code != 200:
                return
            soup = BeautifulSoup(r.text, "html.parser")
            for s in soup.find_all("script", type="application/ld+json"):
                try:
                    j = json.loads(s.string or "")
                except Exception:
                    continue
                items = j if isinstance(j, list) else [j]
                for c in items:
                    if isinstance(c, dict) and c.get("@type") == "Event":
                        dto.desc = handle_description(c.get("description", ""))[:2000]
                        if dto.desc:
                            return
            og = soup.find("meta", property="og:description")
            if og and og.get("content"):
                dto.desc = handle_description(og["content"])[:2000]
        except Exception:
            pass
