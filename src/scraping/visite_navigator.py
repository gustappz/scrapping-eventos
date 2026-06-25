"""Visite RJ + Visite SP scraper.

Estrategia (mesma do scraper original):
- Selenium abre a lista do calendario (visitrio.com.br ou visitesaopaulo.com).
- Extrai URLs de eventos via XPath (tribe-events-* pro RJ, link-evento-carrossel pro SP).
- Para cada evento, abre a pagina, converte HTML em markdown e manda pro Gemini
  pedindo os campos estruturados em JSON.
- Gemini devolve, parseamos, montamos EventDTO.

Custo: cada chamada do Gemini-2.5-flash custa ~$0.002 USD por evento. Pra 100 eventos
da uns R$ 1. A chave esta no .env (vinda do projeto antigo).
"""
import json
import os
import re
import requests
import sys
import time
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from markdownify import markdownify as md
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from base import SeleniumBase
from eventDTO import EventDTO
from logger import LoggerService
from utils import (extract_date_for_visitesp, handle_description,
                   find_minimum_price_of_text, first_date, month_map,
                   remove_accents, extract_ingresse_price_from_url,
                   extract_ticketsports_price_from_url)

# .env pode estar:
#  - no diretorio atual (dev)
#  - junto ao .exe (PyInstaller frozen)
#  - empacotado no bundle temp (sys._MEIPASS)
def _load_env():
    candidates = []
    try:
        if getattr(sys, "frozen", False):
            candidates.append(os.path.join(os.path.dirname(sys.executable), ".env"))
            mp = getattr(sys, "_MEIPASS", None)
            if mp:
                candidates.append(os.path.join(mp, ".env"))
    except Exception:
        pass
    candidates.append(".env")
    for c in candidates:
        if c and os.path.exists(c):
            load_dotenv(c)
            return
    load_dotenv()


_load_env()


VISIT_RIO_URL = "https://visitrio.com.br/calendario-de-eventos/lista/"
VISIT_SP_URL = (
    "https://visitesaopaulo.com/calendario-busca/"
    "?nomeEvento=&dataInicio={start}&dataFinal={end}"
    "&tipologia=&segmento=&local=&exibirEventosPassados=on"
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}

KNOWN_VENUES = {
    "vivo rio": {
        "address": "Av. Infante Dom Henrique, 85 - Parque do Flamengo, Rio de Janeiro - RJ",
        "bairro": "Flamengo",
        "city": "Rio de Janeiro",
        "state": "RJ",
    },
    "qualistage": {
        "address": "Av. Ayrton Senna, 3000 - Barra da Tijuca, Rio de Janeiro - RJ",
        "bairro": "Barra da Tijuca",
        "city": "Rio de Janeiro",
        "state": "RJ",
    },
    "farmasi arena": {
        "address": "Av. Embaixador Abelardo Bueno, 6555 - Barra da Tijuca, Rio de Janeiro - RJ",
        "bairro": "Barra da Tijuca",
        "city": "Rio de Janeiro",
        "state": "RJ",
    },
    "riocentro": {
        "address": "Av. Embaixador Abelardo Bueno, 6555 - Jacarepaguá, Rio de Janeiro - RJ",
        "bairro": "Jacarepaguá",
        "city": "Rio de Janeiro",
        "state": "RJ",
    },
    "marina da gloria": {
        "address": "Av. Infante Dom Henrique, S/N - Glória, Rio de Janeiro - RJ",
        "bairro": "Glória",
        "city": "Rio de Janeiro",
        "state": "RJ",
    },
    "museu do amanha": {
        "address": "Praça Mauá, 1 - Centro, Rio de Janeiro - RJ",
        "bairro": "Centro",
        "city": "Rio de Janeiro",
        "state": "RJ",
    },
    "jockey club brasileiro": {
        "address": "Praça Santos Dumont, 31 - Gávea, Rio de Janeiro - RJ",
        "bairro": "Gávea",
        "city": "Rio de Janeiro",
        "state": "RJ",
    },
    "blue note sao paulo": {
        "address": "Av. Paulista, 2073 - Bela Vista, São Paulo - SP",
        "bairro": "Bela Vista",
        "city": "São Paulo",
        "state": "SP",
    },
    "centro de convencoes reboucas": {
        "address": "Av. Rebouças, 600 - Pinheiros, São Paulo - SP",
        "bairro": "Pinheiros",
        "city": "São Paulo",
        "state": "SP",
    },
    "centro de convencoes frei caneca": {
        "address": "Rua Frei Caneca, 569 - Bela Vista, São Paulo - SP",
        "bairro": "Bela Vista",
        "city": "São Paulo",
        "state": "SP",
    },
    "wtc events center": {
        "address": "Av. das Nações Unidas, 12551 - Brooklin Novo, São Paulo - SP",
        "bairro": "Brooklin Novo",
        "city": "São Paulo",
        "state": "SP",
    },
    "sao paulo expo": {
        "address": "Rodovia dos Imigrantes, km 1,5 - Água Funda, São Paulo - SP",
        "bairro": "Água Funda",
        "city": "São Paulo",
        "state": "SP",
    },
    "expo center norte": {
        "address": "Rua José Bernardo Pinto, 333 - Vila Guilherme, São Paulo - SP",
        "bairro": "Vila Guilherme",
        "city": "São Paulo",
        "state": "SP",
    },
    "usp": {
        "address": "Av. Prof. Mello Moraes, 1721 - Butantã, São Paulo - SP",
        "bairro": "Butantã",
        "city": "São Paulo",
        "state": "SP",
    },
}


def html_to_clean_markdown(html: str) -> str:
    """Remove scripts/styles/nav, converte pra markdown enxuto."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "svg"]):
        tag.extract()
    # remove atributos pesados
    for tag in soup.find_all(True):
        keep = {"href", "src", "alt", "title"}
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in keep}
    raw = md(str(soup), heading_style="ATX")
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    return "\n".join(lines)[:18000]  # corta pra não estourar tokens


def build_event_prompt(markdown_text: str, params: List[str]) -> str:
    descriptions = {
        "local": "Local do evento (nome do local, ex: Teatro XYZ)",
        "address": "Endereço completo do local (ex: Rua ABC, 123, Bairro, Cidade, Estado, CEP)",
        "bairro": "Bairro do local (ex: Centro)",
        "category": (
            "Categoria do evento entre 'Assembléia', 'Campeonato', 'Colóquio', "
            "'Comemorações, Eventos, Festas Populares', 'Concurso', 'Conferência', "
            "'Congresso', 'Convenção', 'Corrida (automobilismo)', 'Corrida (Maratona)', "
            "'Curso', 'Encontro', 'Exposição', 'Feira', 'Festival', 'Forum', 'Mostra', "
            "'Palestra', 'Show', 'Simpósio', 'Workshop'. Se não encaixar, deixe null."
        ),
        "produtor": "Nome do produtor ou organizador do evento (ex: Empresa XYZ)",
        "price": (
            "Preço do menor ingresso. Regras: "
            "1. Se gratuito, coloque 0. "
            "2. Para preço pago, só números e centavos com ponto ou vírgula, "
            "sem símbolo de moeda. Ex: 'R$ 50,00' -> '50,00'. 'Grátis' -> 0."
        ),
        "dateEvents": "Data do primeiro dia do evento no formato DD/MM/AAAA (ex: 25/12/2026)",
        "image": "Link da imagem principal do evento (ex: https://site.com/imagem.jpg)",
        "description": "Descrição detalhada do evento, somente com o texto da página, sem inventar.",
    }
    fields_block = "\n".join(f"- {p}: {descriptions.get(p, '')}" for p in params)
    return (
        "Você é um assistente que extrai informações de um markdown de um site de eventos.\n\n"
        f"Sua tarefa é preencher os seguintes campos de um objeto EventDTO:\n{fields_block}\n\n"
        "Regras obrigatórias:\n"
        "1. Use apenas informações explícitas do texto. Não invente nada.\n"
        "2. Se não houver informação para um campo, use null.\n"
        "3. Responda **apenas em JSON válido**, com as chaves correspondentes.\n\n"
        f"Markdown do evento:\n```\n{markdown_text}\n```\n\n"
        "Agora retorne apenas o JSON."
    )


def call_gemini(prompt: str, model: str = "gemini-2.5-flash-lite") -> str:
    """Chama Gemini; em cota estourada, falha rápido para acionar fallback HTML."""
    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não configurada (cheque .env).")
    client = genai.Client(api_key=api_key)
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model=model, contents=prompt)
            return resp.text or ""
        except Exception as e:
            msg = str(e)
            last_error = e
            # 429 / RESOURCE_EXHAUSTED
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                # Cota diária não melhora com retry curto; retorna logo para o
                # fallback por HTML salvar a planilha em vez de travar.
                raise RuntimeError(f"Gemini sem cota/limite: {msg[:300]}")
            raise
    if last_error:
        raise last_error
    return ""


def parse_event_json(json_str: str, params: List[str]) -> dict:
    """Limpa ```json fences``` e devolve dict com chaves dos params."""
    s = re.sub(r"^```(json)?", "", json_str.strip(), flags=re.IGNORECASE | re.MULTILINE)
    s = re.sub(r"```$", "", s.strip(), flags=re.MULTILINE).strip()
    try:
        d = json.loads(s)
    except json.JSONDecodeError:
        return {p: None for p in params}
    if isinstance(d, list) and d:
        d = d[0]
    return {p: d.get(p) for p in params}


class VisiteNavigator:
    def __init__(self, webdriver: Optional[SeleniumBase], logger: LoggerService):
        self.webdriver = webdriver
        self.logger = logger

    # ============ RIO DE JANEIRO ============

    def get_events_URLs_RJ(self, follow_five_days: int) -> List[str]:
        """follow_five_days = quantos blocos de 5 dias avançar a partir de hoje."""
        if follow_five_days < 1:
            raise ValueError("follow_five_days deve ser >= 1")
        self.webdriver.navigate_to(VISIT_RIO_URL)
        try:
            self.webdriver.wait_for_element(
                By.XPATH,
                "//h3[contains(@class,'tribe-events-calendar-list__event-title')]//a",
                timeout=25,
            )
        except Exception:
            self.logger.error("Visite RJ: listagem não carregou.")
            return []

        all_urls: set = set()
        for i in range(follow_five_days):
            self.logger.info(f"Visite RJ: período {i+1}/{follow_five_days}")
            time.sleep(1)
            anchors = self.webdriver.driver.find_elements(
                By.XPATH,
                "//h3[contains(@class,'tribe-events-calendar-list__event-title')]//a",
            )
            for a in anchors:
                href = a.get_attribute("href")
                if href:
                    all_urls.add(href)
            if i == follow_five_days - 1:
                break
            try:
                nxt = self.webdriver.driver.find_element(
                    By.XPATH, "//a[contains(@class,'tribe-events-c-nav__next')]",
                )
                if not nxt.is_enabled() or "tribe-events-c-nav__next--disabled" in (nxt.get_attribute("class") or ""):
                    self.logger.info("Botão 'Próximo' desabilitado — fim.")
                    break
                self.webdriver.scroll_to_element(nxt, factor=0.85)
                time.sleep(0.5)
                nxt.click()
                time.sleep(1.5)
            except NoSuchElementException:
                self.logger.info("Sem botão 'Próximo' — fim.")
                break
        self.logger.info(f"Visite RJ: {len(all_urls)} URLs únicas coletadas.")
        return list(all_urls)

    def get_info_of_event_RJ(self, event_url: str,
                              downloads_folder: str = "downloads") -> Optional[EventDTO]:
        self.logger.info(f"Visite RJ: extraindo {event_url}")
        from taxonomia import classify_category, classify_genres
        from utils import (extract_bairro_from_address, download_image_named,
                            first_date)
        params = ["local", "address", "bairro", "category", "produtor",
                  "price", "dateEvents", "image", "description", "instagram"]
        data = self._scrape_with_ai(event_url, params)
        if data is None:
            return None
        name = handle_description(self._extract_title_or_h1())
        desc = handle_description(str(data.get("description") or ""))[:2000]
        address = handle_description(str(data.get("address") or ""))
        bairro = handle_description(str(data.get("bairro") or "")) or extract_bairro_from_address(address)
        cat_text = f"{name} {desc} {data.get('category','')}"
        category = classify_category(cat_text)
        genres = classify_genres(cat_text)
        image_url = str(data.get("image") or "")
        image_local = ""
        if image_url and downloads_folder:
            slug = event_url.rstrip("/").split("/")[-1]
            image_local = download_image_named(downloads_folder, image_url, "visiterj", slug)
        date_clean = first_date(str(data.get("dateEvents") or ""))
        dto = EventDTO(
            eventName=name,
            dateEvents=date_clean,
            desc=desc,
            webSite=event_url,
            city="Rio de Janeiro",
            state="RJ",
            price=_to_float(data.get("price")),
            image=image_local or image_url,
            genresGroup=genres,
            category=category,
            produtor=handle_description(str(data.get("produtor") or "")),
            local=handle_description(str(data.get("local") or "")),
            bairro=bairro,
            address=address,
            instagram=str(data.get("instagram") or "https://www.instagram.com/visit.rio"),
            site_extracao="VisiteRJ",
            image_url=image_url,
            event_url_internal=event_url,
        )
        return dto

    # ============ SAO PAULO ============

    def get_events_URLs_SP(self, months_ahead: int) -> List[str]:
        if months_ahead < 1:
            raise ValueError("months_ahead deve ser >= 1")
        start = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + relativedelta(months=months_ahead)).strftime("%Y-%m-%d")
        request_urls = self._get_events_urls_sp_requests(start, end)
        if request_urls:
            return request_urls
        if not (self.webdriver and getattr(self.webdriver, "driver", None)):
            return []

        base = VISIT_SP_URL.format(start=start, end=end)
        self.webdriver.navigate_to(base)
        try:
            self.webdriver.wait_for_element(
                By.XPATH, "//a[contains(@class,'link-evento-carrossel')]", timeout=25,
            )
        except Exception:
            self.logger.error("Visite SP: listagem não carregou.")
            return []
        # extrai URLs página 1
        urls = self._sp_collect_current_page()
        # tenta páginas adicionais
        page = 2
        while True:
            page_url = self._sp_listing_url(start, end, page)
            self.webdriver.navigate_to(page_url)
            time.sleep(3)
            els = self.webdriver.driver.find_elements(
                By.XPATH, "//a[contains(@class,'link-evento-carrossel')]",
            )
            new = self._sp_collect_current_page()
            if not new or new.issubset(urls):
                break
            urls |= new
            page += 1
            if page > 30:
                break
        self.logger.info(f"Visite SP: {len(urls)} URLs únicas coletadas em {page-1} pagina(s).")
        return list(urls)

    def _sp_listing_url(self, start: str, end: str, page: int = 1) -> str:
        if page <= 1:
            return VISIT_SP_URL.format(start=start, end=end)
        return (
            f"https://visitesaopaulo.com/calendario-busca/page/{page}/"
            f"?nomeEvento=&dataInicio={start}&dataFinal={end}"
            "&tipologia=&segmento=&local=&exibirEventosPassados=on"
        )

    def _get_events_urls_sp_requests(self, start: str, end: str) -> List[str]:
        """Coleta o Visite SP por HTML estático. O site pagina em /page/2/,
        não em &pag=2, então isso pega muito mais eventos e bem mais rápido.
        """
        urls: list[str] = []
        seen: set[str] = set()
        max_page = 1

        def collect_from_html(html: str):
            nonlocal max_page
            soup = BeautifulSoup(html or "", "html.parser")
            for a in soup.select("a.link-evento-carrossel"):
                href = a.get("href")
                if href and href not in seen:
                    seen.add(href)
                    urls.append(href)
            for a in soup.find_all("a", href=True):
                m = re.search(r"/calendario-busca/page/(\d+)/", a["href"])
                if m:
                    max_page = max(max_page, int(m.group(1)))

        try:
            r = requests.get(self._sp_listing_url(start, end), headers=REQUEST_HEADERS, timeout=25)
            if r.status_code >= 400 or not r.text:
                return []
            collect_from_html(r.text)

            def fetch_page(page: int):
                try:
                    rp = requests.get(
                        self._sp_listing_url(start, end, page),
                        headers=REQUEST_HEADERS,
                        timeout=25,
                    )
                    if rp.status_code < 400 and rp.text:
                        return page, rp.text
                except Exception as e:
                    self.logger.warning(f"Visite SP: falha na página {page}: {e}")
                return page, ""

            from concurrent.futures import ThreadPoolExecutor
            pages = range(2, min(max_page, 50) + 1)
            with ThreadPoolExecutor(max_workers=6) as pool:
                for _page, html in pool.map(fetch_page, pages):
                    if html:
                        collect_from_html(html)
            self.logger.info(f"Visite SP: {len(urls)} URLs únicas coletadas em {max_page} página(s).")
            return urls
        except Exception as e:
            self.logger.warning(f"Visite SP requests falhou; tentando Selenium: {e}")
            return []

    def _sp_collect_current_page(self) -> set:
        out = set()
        for a in self.webdriver.driver.find_elements(
            By.XPATH, "//a[contains(@class,'link-evento-carrossel')]"
        ):
            href = a.get_attribute("href")
            if href:
                out.add(href)
        return out

    def get_info_of_event_SP(self, event_url: str,
                              downloads_folder: str = "downloads") -> Optional[EventDTO]:
        self.logger.info(f"Visite SP: extraindo {event_url}")
        from taxonomia import classify_category, classify_genres
        from utils import (extract_bairro_from_address, download_image_named,
                            first_date)
        params = ["local", "address", "bairro", "category", "produtor",
                  "price", "dateEvents", "image", "description", "instagram"]

        html = self._fetch_html_requests(event_url)
        if html:
            data = self._fallback_data_from_html(html, event_url, params)
            if data and any(data.values()):
                name = self._extract_title_from_html(html)
                return self._build_sp_dto(
                    event_url, data, name, downloads_folder,
                    classify_category, classify_genres,
                    extract_bairro_from_address, download_image_named, first_date,
                )
        if not (self.webdriver and getattr(self.webdriver, "driver", None)):
            return None

        data = self._scrape_with_ai(event_url, params)
        if data is None:
            return None
        name = self._extract_title_or_h1()
        return self._build_sp_dto(
            event_url, data, name, downloads_folder,
            classify_category, classify_genres,
            extract_bairro_from_address, download_image_named, first_date,
        )

    def _build_sp_dto(self, event_url: str, data: dict, name: str,
                      downloads_folder: str, classify_category, classify_genres,
                      extract_bairro_from_address, download_image_named,
                      first_date) -> EventDTO:
        date_raw = str(data.get("dateEvents") or "")
        date_clean = extract_date_for_visitesp(date_raw) if "de" in date_raw.lower() else first_date(date_raw)
        name = handle_description(name)
        desc = handle_description(str(data.get("description") or ""))[:2000]
        address = handle_description(str(data.get("address") or ""))
        bairro = handle_description(str(data.get("bairro") or "")) or extract_bairro_from_address(address)
        cat_text = f"{name} {desc} {data.get('category','')}"
        category = classify_category(cat_text)
        genres = classify_genres(cat_text)
        image_url = str(data.get("image") or "")
        image_local = ""
        if image_url and downloads_folder:
            slug = event_url.rstrip("/").split("/")[-1]
            image_local = download_image_named(downloads_folder, image_url, "visitesp", slug)
        dto = EventDTO(
            eventName=name,
            dateEvents=date_clean,
            desc=desc,
            webSite=event_url,
            city="São Paulo",
            state="SP",
            price=_to_float(data.get("price")),
            image=image_local or image_url,
            genresGroup=genres,
            category=category,
            produtor=handle_description(str(data.get("produtor") or "")),
            local=handle_description(str(data.get("local") or "")),
            bairro=bairro,
            address=address,
            instagram=str(data.get("instagram") or "https://www.instagram.com/visitesaopaulo"),
            site_extracao="VisiteSP",
            image_url=image_url,
            event_url_internal=event_url,
        )
        return dto

    # ============ HELPERS ============

    def _scrape_with_ai(self, event_url: str, params: List[str]) -> Optional[dict]:
        if not (self.webdriver and getattr(self.webdriver, "driver", None)):
            return None
        try:
            self.webdriver.navigate_to(event_url)
        except Exception as e:
            self.logger.error(f"Falha ao abrir {event_url}: {e}")
            return None
        # Espera passar o desafio Cloudflare. Conferimos pelo <title>
        # — durante o desafio o title é só o dominio ("visitrio.com.br" / "visitesaopaulo.com").
        # Quando passa, o title vira o nome do evento.
        ok = False
        for attempt in range(45):
            try:
                title = self.webdriver.driver.title or ""
            except Exception as e:
                self.logger.error(f"Erro ao obter title: {e}")
                return None
            tl = title.lower().strip()
            if tl and not any(b in tl for b in
                              ("visitrio.com.br", "visitesaopaulo.com",
                               "um momento", "just a moment", "verificação")):
                ok = True
                break
            time.sleep(0.4)
        if not ok:
            self.logger.error(f"Cloudflare não liberou: {event_url} (title='{title}')")
            return None
        html = self.webdriver.driver.page_source
        fallback = self._fallback_data_from_html(html, event_url, params)
        if not fallback.get("price"):
            external_price = self._external_price_from_html_with_driver(event_url, html)
            if external_price:
                fallback["price"] = external_price
        if self._has_enough_fallback(fallback):
            return fallback
        markdown = html_to_clean_markdown(html)
        if not markdown:
            self.logger.error(f"Markdown vazio em {event_url}.")
            return fallback if any(fallback.values()) else None
        prompt = build_event_prompt(markdown, params)
        # Retry: Gemini falha intermitente. Tenta 3x.
        last_err = None
        for attempt in range(3):
            try:
                answer = call_gemini(prompt)
                parsed = parse_event_json(answer, params)
                # Se vier tudo None, considera falha e retry
                if parsed and any(v is not None for v in parsed.values()):
                    return self._merge_data(fallback, parsed)
                last_err = "Parse retornou só nulls"
            except Exception as e:
                last_err = str(e)
                if "Gemini sem cota" in last_err:
                    break
            time.sleep(2)
        self.logger.error(f"Gemini falhou 3x em {event_url}: {last_err}")
        return fallback if any(fallback.values()) else None

    def _fetch_html_with_cloudflare(self, event_url: str) -> Optional[str]:
        """Navega via Selenium até passar Cloudflare e devolve HTML + atualiza
        title do driver pro _extract_title_or_h1."""
        try:
            self.webdriver.navigate_to(event_url)
        except Exception as e:
            self.logger.error(f"Falha ao abrir {event_url}: {e}")
            return None
        for attempt in range(45):
            try:
                title = self.webdriver.driver.title or ""
            except Exception:
                return None
            tl = title.lower().strip()
            if tl and not any(b in tl for b in
                              ("visitrio.com.br", "visitesaopaulo.com",
                               "um momento", "just a moment", "verificação")):
                return self.webdriver.driver.page_source
            time.sleep(0.4)
        return None

    def _process_html_with_gemini(self, html: str, params: List[str],
                                    event_url: str) -> Optional[dict]:
        """Converte HTML em markdown e manda pro Gemini. Thread-safe."""
        fallback = self._fallback_data_from_html(html, event_url, params)
        if self._has_enough_fallback(fallback):
            return fallback
        markdown = html_to_clean_markdown(html)
        if not markdown:
            return fallback if any(fallback.values()) else None
        prompt = build_event_prompt(markdown, params)
        last_err = None
        for attempt in range(3):
            try:
                answer = call_gemini(prompt)
                parsed = parse_event_json(answer, params)
                if parsed and any(v is not None for v in parsed.values()):
                    return self._merge_data(fallback, parsed)
                last_err = "Parse retornou só nulls"
            except Exception as e:
                last_err = str(e)
                if "Gemini sem cota" in last_err:
                    break
            time.sleep(2)
        self.logger.error(f"Gemini falhou 3x em {event_url}: {last_err}")
        return fallback if any(fallback.values()) else None

    def get_info_of_event_RJ_from_html(self, event_url: str, html: str,
                                          title_from_listing: str,
                                          downloads_folder: str = "downloads") -> Optional[EventDTO]:
        """Versão thread-safe: recebe HTML pronto + título, processa só Gemini."""
        from taxonomia import classify_category, classify_genres
        from utils import (extract_bairro_from_address, download_image_named,
                            first_date)
        params = ["local", "address", "bairro", "category", "produtor",
                  "price", "dateEvents", "image", "description", "instagram"]
        data = self._process_html_with_gemini(html, params, event_url)
        if data is None:
            return None
        name = handle_description(title_from_listing or "")
        desc = handle_description(str(data.get("description") or ""))[:2000]
        address = handle_description(str(data.get("address") or ""))
        bairro = handle_description(str(data.get("bairro") or "")) or extract_bairro_from_address(address)
        cat_text = f"{name} {desc} {data.get('category','')}"
        category = classify_category(cat_text)
        genres = classify_genres(cat_text)
        image_url = str(data.get("image") or "")
        image_local = ""
        if image_url and downloads_folder:
            slug = event_url.rstrip("/").split("/")[-1]
            image_local = download_image_named(downloads_folder, image_url, "visiterj", slug)
        date_clean = first_date(str(data.get("dateEvents") or ""))
        return EventDTO(
            eventName=name,
            dateEvents=date_clean,
            desc=desc,
            webSite=event_url,
            city="Rio de Janeiro",
            state="RJ",
            price=_to_float(data.get("price")),
            image=image_local or image_url,
            genresGroup=genres,
            category=category,
            produtor=handle_description(str(data.get("produtor") or "")),
            local=handle_description(str(data.get("local") or "")),
            bairro=bairro,
            address=address,
            instagram=str(data.get("instagram") or "https://www.instagram.com/visit.rio"),
            site_extracao="VisiteRJ",
            image_url=image_url,
            event_url_internal=event_url,
        )

    def _extract_title_or_h1(self) -> str:
        """Pega o nome do evento. Remove sufixos do tipo ' - Visit Rio' / ' - Visite São Paulo'."""
        title = ""
        try:
            h1 = self.webdriver.driver.find_element(By.TAG_NAME, "h1")
            title = (h1.text or "").strip()
        except Exception:
            pass
        if not title:
            try:
                og = self.webdriver.driver.find_element(
                    By.XPATH, "//meta[@property='og:title']"
                )
                title = (og.get_attribute("content") or "").strip()
            except Exception:
                pass
        # Remove sufixos comuns do site
        for suffix in (" - Visit Rio", " - Visite São Paulo", " - Visite Sao Paulo",
                       " | Visit Rio", " | Visite São Paulo"):
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()
        return title

    def _extract_title_from_html(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        title = ""
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
        if not title:
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                title = og["content"].strip()
        for suffix in (" - Visit Rio", " - Visite São Paulo", " - Visite Sao Paulo",
                       " | Visit Rio", " | Visite São Paulo"):
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()
        return title

    def _fetch_html_requests(self, event_url: str) -> str:
        try:
            r = requests.get(event_url, headers=REQUEST_HEADERS, timeout=25)
            if r.status_code < 400 and r.text:
                return r.text
        except Exception as e:
            self.logger.warning(f"Requests falhou em {event_url}: {e}")
        return ""

    def _fallback_data_from_html(self, html: str, event_url: str,
                                 params: List[str]) -> dict:
        data = {p: None for p in params}
        soup = BeautifulSoup(html or "", "html.parser")
        text = soup.get_text(" ", strip=True)
        event_ld = self._extract_event_ld(soup)

        if event_ld:
            data["description"] = event_ld.get("description")
            data["produtor"] = self._extract_org_name(event_ld.get("organizer"))
            data["dateEvents"] = self._format_date(event_ld.get("startDate"))
            data["price"] = self._extract_price_from_offers(event_ld.get("offers"))
            event_type = event_ld.get("eventType") or event_ld.get("category")
            genre = event_ld.get("genre")
            audience = event_ld.get("audience")
            audience_type = ""
            if isinstance(audience, dict):
                audience_type = str(audience.get("audienceType") or "")
            data["category"] = " ".join(
                str(v) for v in (event_type, genre, audience_type) if v
            ) or None
            loc = event_ld.get("location")
            if isinstance(loc, dict):
                data["local"] = loc.get("name")
                data["address"] = self._address_to_text(loc.get("address"))
            img = event_ld.get("image")
            if isinstance(img, list) and img:
                data["image"] = img[0]
            elif isinstance(img, str):
                data["image"] = img

        if not data.get("description"):
            meta = soup.find("meta", property="og:description")
            if meta and meta.get("content"):
                data["description"] = meta["content"]
        best_desc = self._extract_best_description(soup)
        if best_desc and (
            not data.get("description")
            or len(str(data.get("description") or "")) < len(best_desc)
            or "acesse e saiba" in str(data.get("description") or "").lower()
        ):
            data["description"] = best_desc
        if data.get("image") and not self._is_event_image(str(data["image"])):
            data["image"] = None
        if not data.get("image"):
            data["image"] = self._extract_image_candidate(soup, event_url)
        if data.get("image"):
            data["image"] = urljoin(event_url, str(data["image"]))

        if not data.get("dateEvents"):
            data["dateEvents"] = self._extract_date_from_text(text)
        if not data.get("local"):
            data["local"] = self._extract_label_value(
                text, "Local", ("Site", "Endereço", "Endereco", "Preço", "Valor", "Data")
            )
        if not data.get("address"):
            data["address"] = self._extract_label_value(
                text, "Endereço", ("Site", "Preço", "Valor", "Data", "Local")
            ) or self._extract_label_value(
                text, "Endereco", ("Site", "Preço", "Valor", "Data", "Local")
            )
        self._apply_known_venue_fallbacks(data)
        if not data.get("price"):
            price = find_minimum_price_of_text(text)
            if price:
                data["price"] = price
            elif re.search(r"\b(gr[aá]tis|gratuito|entrada franca)\b", text, re.I):
                data["price"] = 0
        if not data.get("price"):
            external_links = self._extract_external_ticket_links(soup, event_url, text)
            external_price = self._extract_price_from_external_links(external_links)
            if external_price:
                data["price"] = external_price

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "instagram.com/" in href.lower():
                data["instagram"] = href
                break

        if data.get("description"):
            data["description"] = handle_description(str(data["description"]))[:2000]
        return data

    def _extract_best_description(self, soup: BeautifulSoup) -> str:
        blocked = (
            "compartilhe", "redes sociais", "visit rio tem como missão",
            "descubra são paulo", "área do associado", "cookies",
            "calendário de eventos", "somos associados", "buscar resultados",
            "idiomas onde ficar", "explore o rio onde comprar",
        )
        def candidates(tags):
            found = []
            for tag in tags:
                raw = tag.get_text(" ", strip=True)
                clean = handle_description(raw)
                if len(clean) < 80 or len(clean) > 2500:
                    continue
                low = clean.lower()
                if any(b in low for b in blocked):
                    continue
                found.append(clean)
            return found

        paragraph_candidates = candidates(soup.find_all("p"))
        if paragraph_candidates:
            return max(paragraph_candidates, key=len)

        scoped_divs = []
        for tag in soup.find_all("div"):
            classes = " ".join(tag.get("class") or []).lower()
            if any(k in classes for k in ("description", "content", "evento", "event")):
                scoped_divs.append(tag)
        div_candidates = candidates(scoped_divs)
        if div_candidates:
            return max(div_candidates, key=len)
        return ""

    def _extract_label_value(self, text: str, label: str, stops: tuple[str, ...]) -> str:
        if not text:
            return ""
        stop_pattern = "|".join(re.escape(s) for s in stops)
        m = re.search(
            rf"\b{re.escape(label)}\s*:?\s+(.+?)(?=\s+(?:{stop_pattern})\b|$)",
            text,
            re.IGNORECASE,
        )
        if not m:
            return ""
        value = handle_description(m.group(1))
        return value[:200].strip(" :-")

    def _apply_known_venue_fallbacks(self, data: dict) -> None:
        local = str(data.get("local") or "").strip()
        if not local:
            return
        local_norm = remove_accents(local).lower()
        local_norm = re.sub(r"[^a-z0-9]+", " ", local_norm).strip()
        for key, meta in KNOWN_VENUES.items():
            if key in local_norm or local_norm in key:
                if not data.get("address"):
                    data["address"] = meta.get("address", "")
                if not data.get("bairro"):
                    data["bairro"] = meta.get("bairro", "")
                return

    def _is_event_image(self, url: str) -> bool:
        if not url:
            return False
        low = url.lower()
        bad = (
            "logo", "favicon", "apple-touch", "banner-eventos", "menu.png",
            "icone", "icon-", "icon_", "bandeira", "esp.png", "eua-1.png",
            "italia.png", "placeholder", "google", "facebook", "twitter",
            "whatsapp", "loader", "sprite", "ticket360_og", "logo-sympla",
        )
        if any(b in low for b in bad):
            return False
        return any(ext in low.split("?", 1)[0] for ext in (".jpg", ".jpeg", ".png", ".webp"))

    def _extract_image_candidate(self, soup: BeautifulSoup, event_url: str) -> str:
        candidates: list[str] = []

        def add(value, label: str = ""):
            if not value:
                return
            label_low = remove_accents(label or "").lower()
            if any(b in label_low for b in (
                "agenda de eventos", "bandeira", "english", "espanol",
                "italiano", "local acessivel", "download no",
            )):
                return
            if isinstance(value, list):
                for item in value:
                    add(item, label)
                return
            url = str(value).strip()
            if not url:
                return
            if "," in url and " " in url:
                url = url.split(",", 1)[0].split()[0]
            url = urljoin(event_url, url)
            if self._is_event_image(url) and url not in candidates:
                candidates.append(url)

        for attr in ({"property": "og:image"}, {"name": "twitter:image"}, {"rel": "image_src"}):
            tag = soup.find("meta", attrs=attr) if "rel" not in attr else soup.find("link", attrs=attr)
            if tag:
                add(tag.get("content") or tag.get("href"))

        for tag in soup.find_all(attrs={"data-bg": True}):
            add(tag.get("data-bg"))
        for tag in soup.find_all(style=True):
            for m in re.findall(r"url\(['\"]?([^'\")]+)", tag.get("style") or "", re.I):
                add(m)

        wp_img = self._extract_wp_rest_image(soup, event_url)
        add(wp_img)
        return candidates[0] if candidates else ""

    def _has_bad_image_ancestor(self, tag) -> bool:
        for parent in list(tag.parents)[:6]:
            classes = " ".join(parent.get("class") or []).lower()
            ident = str(parent.get("id") or "").lower()
            if any(k in f"{classes} {ident}" for k in (
                "blog", "footer", "header", "menu", "sidebar", "shortcode-content",
                "card-carrossel", "box-blog",
            )):
                return True
        return False

    def _extract_wp_rest_image(self, soup: BeautifulSoup, event_url: str) -> str:
        body = soup.find("body")
        class_text = " ".join(body.get("class") or []) if body else ""
        m = re.search(r"postid-(\d+)", class_text)
        if not m:
            return ""
        post_id = m.group(1)
        base = f"{urlparse(event_url).scheme}://{urlparse(event_url).netloc}"
        try:
            r = requests.get(
                f"{base}/wp-json/wp/v2/evento/{post_id}",
                headers=REQUEST_HEADERS,
                timeout=8,
            )
            if r.status_code >= 400 or not r.text:
                return ""
            data = r.json()
        except Exception:
            return ""

        candidates = []
        yoast = data.get("yoast_head_json") if isinstance(data, dict) else {}
        if isinstance(yoast, dict):
            for item in yoast.get("og_image") or []:
                if isinstance(item, dict):
                    candidates.append(item.get("url"))
        content = data.get("content", {}).get("rendered", "") if isinstance(data.get("content"), dict) else ""
        if content:
            content_soup = BeautifulSoup(content, "html.parser")
            for img in content_soup.find_all("img"):
                candidates.append(img.get("src") or img.get("data-src"))
        featured_id = data.get("featured_media")
        if featured_id:
            try:
                mr = requests.get(
                    f"{base}/wp-json/wp/v2/media/{featured_id}",
                    headers=REQUEST_HEADERS,
                    timeout=8,
                )
                if mr.status_code < 400:
                    media = mr.json()
                    candidates.append(media.get("source_url"))
            except Exception:
                pass
        for candidate in candidates:
            if candidate and self._is_event_image(str(candidate)):
                return urljoin(event_url, str(candidate))
        return ""

    def _extract_event_ld(self, soup: BeautifulSoup) -> Optional[dict]:
        for s in soup.find_all("script", type="application/ld+json"):
            raw = s.string or s.get_text() or ""
            if not raw.strip():
                continue
            try:
                parsed = json.loads(raw.strip().rstrip(";"))
            except Exception:
                continue
            stack = parsed if isinstance(parsed, list) else [parsed]
            for item in stack:
                if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
                if not isinstance(item, dict):
                    continue
                typ = item.get("@type", "")
                if typ == "Event" or (isinstance(typ, list) and "Event" in typ):
                    return item
        return None

    def _has_enough_fallback(self, data: dict) -> bool:
        filled = [data.get(k) for k in ("dateEvents", "image", "description",
                                        "local", "address", "price")]
        return sum(1 for v in filled if v not in (None, "")) >= 2

    def _merge_data(self, fallback: dict, parsed: dict) -> dict:
        out = dict(fallback or {})
        for k, v in (parsed or {}).items():
            if v not in (None, ""):
                out[k] = v
        return out

    def _format_date(self, raw) -> str:
        if not raw:
            return ""
        s = str(raw)
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            y, mo, d = m.groups()
            return f"{d}/{mo}/{y}"
        return self._extract_date_from_text(s) or s

    def _extract_date_from_text(self, text: str) -> str:
        m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text or "")
        if m:
            return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"
        m = re.search(r"\b(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})\b",
                      text or "", re.IGNORECASE)
        if m:
            month = month_map.get(remove_accents(m.group(2)).lower())
            if month:
                return f"{int(m.group(1)):02d}/{month}/{m.group(3)}"
        return ""

    def _address_to_text(self, addr) -> str:
        if isinstance(addr, str):
            return addr.strip()
        if isinstance(addr, dict):
            parts = [addr.get(k, "") for k in
                     ("streetAddress", "addressLocality",
                      "addressRegion", "postalCode")]
            return ", ".join(p for p in parts if p)
        return ""

    def _extract_org_name(self, org) -> str:
        if isinstance(org, dict):
            return str(org.get("name") or "")
        if isinstance(org, str):
            return org
        return ""

    def _extract_price_from_offers(self, offers):
        candidates = offers if isinstance(offers, list) else [offers]
        prices = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            for key in ("price", "lowPrice"):
                try:
                    value = item.get(key)
                    if value not in (None, ""):
                        prices.append(float(str(value).replace(",", ".")))
                except Exception:
                    pass
        return min(prices) if prices else None

    def _extract_external_ticket_links(self, soup: BeautifulSoup, event_url: str,
                                       text: str) -> List[str]:
        own_host = urlparse(event_url).netloc.lower().replace("www.", "")
        blocked = (
            "facebook.com", "instagram.com", "twitter.com", "x.com",
            "linkedin.com", "whatsapp", "addtoany.com", "google.com",
            "maps.google", "waze.com", "youtube.com", "tiktok.com",
            "flickr.com", "blog.visitesaopaulo.com",
        )
        allowed = (
            "ticket360.com", "sympla.com", "eventim.com", "ingresse.com",
            "uhuu.com", "bilheteriadigital.com", "ticketmaster", "ticketsforfun",
            "ticketsports.com", "shotgun.live", "feverup.com", "eventbrite",
            "totalacesso.com", "clubedoingresso.com", "zig.tickets",
            "zigtickets", "byma.com", "icones.com.br", "blueteicket",
            "blueticket.com.br", "megabilheteria.com",
        )
        out = []

        def add(candidate: str):
            if not candidate:
                return
            url = candidate.strip().strip(".,;)")
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("www."):
                url = "https://" + url
            elif re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}/", url):
                url = "https://" + url
            url = urljoin(event_url, url)
            parsed = urlparse(url)
            host = parsed.netloc.lower().replace("www.", "")
            if not host or own_host in host:
                return
            if any(b in host or b in url.lower() for b in blocked):
                return
            if not any(a in host for a in allowed):
                return
            if url not in out:
                out.append(url)

        for a in soup.find_all("a", href=True):
            href = a.get("href") or ""
            label = a.get_text(" ", strip=True)
            joined = f"{href} {label}".lower()
            if any(k in joined for k in ("ingresso", "ticket", "bilheteria", "comprar", "sympla", "eventim")):
                add(href)

        for m in re.findall(r"(?:https?://|www\.)[^\s<>()\"']+|(?:ticket360|sympla|eventim|ingresse|uhuu|ticketmaster|ticketsforfun|eventbrite)\.[^\s<>()\"']+", text or "", re.I):
            add(m)
        return out[:4]

    def _extract_price_from_external_links(self, links: List[str]) -> float:
        for link in links[:3]:
            try:
                host = urlparse(link).netloc.lower()
                if "ingresse.com" in host:
                    price = extract_ingresse_price_from_url(link)
                    if price is not None:
                        return price
                if "ticketsports.com" in host:
                    price = extract_ticketsports_price_from_url(link)
                    if price is not None:
                        return price
                r = requests.get(
                    link,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/126.0.0.0 Safari/537.36"
                        ),
                        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
                    },
                    timeout=8,
                    allow_redirects=True,
                )
                if r.status_code >= 400 or not r.text:
                    continue
                original = urlparse(link)
                final = urlparse(r.url)
                # Alguns sites mandam link antigo para a home; isso costuma
                # trazer uma lista de eventos e preços errados.
                if final.path in ("", "/") and original.path not in ("", "/"):
                    continue
                raw_price = self._extract_price_from_raw_html(r.text)
                if raw_price:
                    return raw_price
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style", "noscript", "svg"]):
                    tag.extract()
                text = soup.get_text(" ", strip=True)
                price = find_minimum_price_of_text(text)
                if price:
                    return price
            except Exception:
                continue
        return 0.0

    def _extract_price_from_raw_html(self, html: str) -> float:
        price = find_minimum_price_of_text(html)
        if price:
            return price
        values = []
        for raw in re.findall(
            r'"(?:price|lowPrice|minPrice|amount|valor|preco)"\s*:\s*"?([0-9]+(?:[,.][0-9]{1,2})?)"?',
            html or "",
            re.I,
        ):
            try:
                value = float(raw.replace(",", "."))
                # evita IDs/anos tratados como preço
                if 0 < value < 10000:
                    values.append(value)
            except Exception:
                pass
        return min(values) if values else 0.0

    def _external_price_from_html_with_driver(self, event_url: str, html: str) -> float:
        if not (self.webdriver and getattr(self.webdriver, "driver", None)):
            return 0.0
        soup = BeautifulSoup(html or "", "html.parser")
        text = soup.get_text(" ", strip=True)
        links = self._extract_external_ticket_links(soup, event_url, text)
        if not links:
            return 0.0
        driver = self.webdriver.driver
        try:
            original = driver.current_window_handle
        except Exception:
            return 0.0
        for link in links[:2]:
            try:
                driver.execute_script("window.open(arguments[0], '_blank');", link)
                time.sleep(1)
                driver.switch_to.window(driver.window_handles[-1])
                time.sleep(7)
                body = driver.find_element(By.TAG_NAME, "body").text
                if re.search(r"queue-it|fila para|aguarde sua vez", body, re.I):
                    continue
                price = find_minimum_price_of_text(body)
                if price:
                    return price
            except Exception:
                continue
            finally:
                try:
                    if driver.current_window_handle != original:
                        driver.close()
                except Exception:
                    pass
                try:
                    driver.switch_to.window(original)
                except Exception:
                    pass
        return 0.0


def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0
