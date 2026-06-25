import os
import re
import html
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

month_map = {
    "janeiro": "01", "jan": "01",
    "fevereiro": "02", "fev": "02",
    "março": "03", "marco": "03", "mar": "03",
    "abril": "04", "abr": "04",
    "maio": "05", "mai": "05",
    "junho": "06", "jun": "06",
    "julho": "07", "jul": "07",
    "agosto": "08", "ago": "08",
    "setembro": "09", "set": "09",
    "outubro": "10", "out": "10",
    "novembro": "11", "nov": "11",
    "dezembro": "12", "dez": "12",
}

brazilian_states = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}

_sport_keywords = {
    "Corrida": ["corrida", "run", "running", "maratona", "marathon", "trail", "5k", "10k", "21k", "42k"],
    "Ciclismo": ["ciclismo", "bike", "cycling", "pedal", "mtb", "speed", "gravel"],
    "Triathlon": ["triathlon", "triatlo", "ironman", "duathlon"],
    "Natação": ["natação", "natacao", "swim", "aquathlon"],
    "Caminhada": ["caminhada", "walk"],
    "Outros": [],
}


def remove_accents(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def transform_to_path(text: str) -> str:
    s = remove_accents(text or "").strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^A-Za-z0-9\-_.]", "", s)
    return s or "Geral"


def handle_description(description: str) -> str:
    """Limpa descrição: remove emojis, tags HTML, parágrafos. Devolve uma linha só."""
    if not description:
        return ""
    s = html.unescape(str(description))
    # Alguns HTMLs do Visit Rio chegam com acentos PT-BR trocados por caracteres
    # parecidos (ex.: "vocę" no lugar de "você").
    s = s.translate(str.maketrans({"ę": "ê", "Ę": "Ê", "ă": "ã", "Ă": "Ã"}))
    # remove tags HTML
    s = re.sub(r"<[^>]+>", " ", s)
    # remove emojis e símbolos unicode > U+2000 (cobre 99% dos casos)
    s = re.sub(r"[\U00002000-\U0001FFFF]", "", s)
    # remove escape unicode visível tipo \u00xx
    s = re.sub(r"[ ​-‏  ]", " ", s)
    # remove controles invisiveis que quebram openpyxl/Excel
    s = re.sub(r"[\x00-\x08\x0B-\x1F\x7F]", " ", s)
    # tira marcações Markdown
    s = re.sub(r"[*_#`>]+", "", s)
    # quebras de linha viram espaço
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def find_state_on_address(address: str) -> str:
    if not address:
        return ""
    a = address
    # sigla (2 letras maiúsculas)
    m = re.search(r"\b([A-Z]{2})\b", a)
    if m and m.group(1) in brazilian_states:
        return m.group(1)
    # nome completo
    a_low = remove_accents(a).lower()
    for sigla, nome in sorted(brazilian_states.items(), key=lambda x: len(x[1]), reverse=True):
        nome_norm = remove_accents(nome).lower()
        if re.search(rf"\b{re.escape(nome_norm)}\b", a_low):
            return sigla
    return ""


def find_city_on_address(address: str) -> str:
    if not address:
        return ""
    parts = [p.strip() for p in re.split(r"[,\-–]|\n+", address) if p.strip()]
    state = find_state_on_address(address)
    # cidade geralmente vem logo antes da sigla do estado. Procura de trás
    # para frente para não confundir "São Paulo" cidade com "São Paulo" estado.
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].strip().upper() == state and i > 0:
            return parts[i - 1]
    state_name = remove_accents(brazilian_states.get(state, "")).lower()
    for i in range(len(parts) - 1, -1, -1):
        if remove_accents(parts[i]).lower() == state_name and i > 0:
            return parts[i - 1]
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")


def _parse_date_pt(day: str, month_name: str, year: Optional[str]) -> Optional[str]:
    m = month_map.get(remove_accents(month_name).lower())
    if not m:
        return None
    y = year or str(datetime.now().year)
    return f"{int(day):02d}/{m}/{y}"


def clean_and_parse_date_mapadosfestivais(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    # "7 agosto a 9 agosto 2026" / "7 a 9 de agosto de 2026" / "10 de outubro de 2026"
    m = re.search(r"(\d{1,2})\s*(?:de\s+)?([a-zà-ú]+)(?:\s+(?:a|até|–|-)\s+\d{1,2}\s*(?:de\s+)?[a-zà-ú]+)?\s*(?:de\s+)?(\d{4})", t, re.IGNORECASE)
    if m:
        d = _parse_date_pt(m.group(1), m.group(2), m.group(3))
        if d:
            return d
    return t


def clean_and_parse_date_ticketsports(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    m = re.search(r"(\d{2}/\d{2}/\d{4})", t)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)(?:\s+de\s+(\d{4}))?", t, re.IGNORECASE)
    if m:
        d = _parse_date_pt(m.group(1), m.group(2), m.group(3))
        if d:
            return d
    return t


def clean_and_parse_date_shotgun(text: str) -> str:
    if not text:
        return ""
    t = text.strip().lower()
    # "15 de maio de 2026" / "15 maio 2026" / "15 de maio"
    m = re.search(r"(\d{1,2})\s+(?:de\s+)?([a-zà-ú]+)(?:\s+(?:de\s+)?(\d{4}))?", t)
    if m:
        d = _parse_date_pt(m.group(1), m.group(2), m.group(3))
        if d:
            return d
    return text


def clean_and_parse_date_ingresse(text: str) -> str:
    return clean_and_parse_date_shotgun(text)


def extract_date_for_visitesp(data_str: str) -> str:
    if not data_str:
        return ""
    m = re.search(r"(\d{1,2})\s*de\s*(\w+).*?de\s+(\d{4})", data_str, re.IGNORECASE)
    if m:
        d = _parse_date_pt(m.group(1), m.group(2), m.group(3))
        if d:
            return d
    return data_str


def find_maximum_price_of_text(text: str) -> float:
    """Devolve o MAIOR preço encontrado no texto (uso legado)."""
    return _find_prices_in_text(text, "max")


def find_minimum_price_of_text(text: str) -> float:
    """Devolve o MENOR preço encontrado no texto. Nath quer o menor (ingresso mais barato)."""
    return _find_prices_in_text(text, "min")


def find_price_candidates_in_text(text: str) -> list[float]:
    """Extrai candidatos de preco sem inventar valor."""
    if not text:
        return []
    src = html.unescape(str(text))
    src = re.sub(r"<[^>]+>", " ", src)
    src = re.sub(r"\s+", " ", src)

    found: list[float] = []

    def add(raw: str, start: int, end: int, *, currency: bool) -> None:
        value = _parse_money_number(raw)
        if value is None or value < 0:
            return
        if value == 0:
            found.append(0.0)
            return
        if value > 100000:
            return
        before = src[max(0, start - 120):start]
        after = src[end:min(len(src), end + 80)]
        context = f"{before} {after}"
        if _looks_like_non_ticket_price(
            context, currency=currency, value=value, before=before, after=after
        ):
            return
        if not currency and value < 10:
            return
        found.append(value)

    currency_re = re.compile(
        r"(?:R\$\s*|BRL\s*)(\d{1,3}(?:[.\s]\d{3})+(?:[,.]\d{1,2})?|\d+(?:[,.]\d{1,2})?)",
        re.I,
    )
    for m in currency_re.finditer(src):
        add(m.group(1), m.start(1), m.end(1), currency=True)

    label_re = re.compile(
        r"(?<![\w])(?:pre[cç]o|valor|ingressos?|tickets?|entrada|inscri[cç][aã]o|passaporte)(?![\w])"
        r"[^0-9R$]{0,45}"
        r"(\d{1,3}(?:[.\s]\d{3})+(?:[,.]\d{1,2})?|\d+(?:[,.]\d{1,2})?)",
        re.I,
    )
    for m in label_re.finditer(src):
        add(m.group(1), m.start(1), m.end(1), currency=False)

    from_re = re.compile(
        r"(?<![\w])(?:ingressos?|tickets?|entradas?)(?![\w])"
        r"[^0-9]{0,45}(?:a partir de|desde|por)"
        r"[^0-9R$]{0,20}"
        r"(\d{1,3}(?:[.\s]\d{3})+(?:[,.]\d{1,2})?|\d+(?:[,.]\d{1,2})?)",
        re.I,
    )
    for m in from_re.finditer(src):
        add(m.group(1), m.start(1), m.end(1), currency=False)

    json_re = re.compile(
        r"[\"'](?P<key>price|lowPrice|minPrice|minimumPrice|amount|valor|preco|salePrice|sale|fullPrice|"
        r"priceInCents|amountInCents|valorCentavos|precoCentavos|unit_amount)[\"']\s*:\s*"
        r"[\"']?(?P<value>\d+(?:[,.]\d{1,2})?)[\"']?",
        re.I,
    )
    for m in json_re.finditer(src):
        key = m.group("key").lower()
        value = _parse_money_number(m.group("value"))
        if value is None:
            continue
        if any(k in key for k in ("cent", "unit_amount")):
            value = value / 100.0
        add(str(value), m.start("value"), m.end("value"), currency=False)

    unique: list[float] = []
    for value in found:
        rounded = round(float(value), 2)
        if rounded not in unique:
            unique.append(rounded)
    return unique


def _find_prices_in_text(text: str, mode: str) -> float:
    prices = find_price_candidates_in_text(text)
    if not prices:
        return 0.0
    return max(prices) if mode == "max" else min(prices)


def _parse_money_number(raw: str) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^0-9,.\-]", "", s)
    if not s or s == "-":
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) in (1, 2):
            s = "".join(parts[:-1]).replace(".", "") + "." + parts[-1]
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[-1]) in (1, 2):
            s = s
        else:
            s = "".join(parts)

    try:
        return float(s)
    except ValueError:
        return None


def _looks_like_non_ticket_price(
    context: str, *, currency: bool, value: float, before: str = "", after: str = ""
) -> bool:
    c = remove_accents(context or "").lower()
    b = remove_accents(before or "").lower()
    a = remove_accents(after or "").lower()
    if re.search(r"\b\d{1,2}\s*x\s*(?:de)?\s*$", b[-30:]):
        return True
    if re.search(
        r"^(?:\s|[^\w])*(?:anos?|idade|h|horas?|min|minutos?|atletas?|vagas?|participantes?|pessoas?|km|quilometros?)\b",
        a[:35],
    ):
        return True

    ticket_words = (
        "ingresso", "ticket", "entrada", "inscri", "lote", "kit", "valor",
        "preco", "meia", "inteira", "passaporte", "venda", "cortesia",
    )
    prize_words = (
        "premia", "premio", "trof", "ranking", "colocacao", "lugar",
        "classificacao geral", "faixas etarias",
    )
    if any(w in c for w in prize_words) and not any(w in c for w in ticket_words):
        return True
    if "taxa de servico" in c and not any(w in c for w in ticket_words):
        return True
    if not currency and value > 0 and re.search(r"\b(?:202[0-9]|19[0-9]{2})\b", c):
        if not any(w in c for w in ticket_words):
            return True
    return False


INGRESSE_EMBED_API_KEY = "172f24fd2a903fc0647b61d7112ee1b9814702be"


def extract_ingresse_price_from_url(url: str, timeout: int = 12) -> Optional[float]:
    """Busca menor preco direto na API publica usada pelo widget da Ingresse."""
    slug = _slug_from_url(url)
    if not slug:
        return None
    try:
        event = requests.get(
            f"https://api-site.ingresse.com/events/{slug}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=timeout,
        )
        if event.status_code >= 400:
            return None
        event_id = (event.json() or {}).get("id")
        if not event_id:
            return None
        return extract_ingresse_price_from_event_id(str(event_id), timeout=timeout)
    except Exception:
        return None


def extract_ingresse_price_from_event_id(event_id: str, timeout: int = 12) -> Optional[float]:
    if not event_id:
        return None
    try:
        r = requests.get(
            f"https://api-embedstore.ingresse.com/api/v1/event/{event_id}/session/0/tickets",
            params={"apikey": INGRESSE_EMBED_API_KEY},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Origin": "https://embedstore.ingresse.com",
                "Referer": f"https://embedstore.ingresse.com/tickets/ingresse.com/event/{event_id}",
            },
            timeout=timeout,
        )
        if r.status_code >= 400:
            return None
        data = r.json()
    except Exception:
        return None

    prices: list[float] = []

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "price":
                    try:
                        hidden = bool(obj.get("hidden"))
                        if not hidden and value not in (None, ""):
                            v = float(str(value).replace(",", "."))
                            if v >= 0:
                                prices.append(v)
                    except Exception:
                        pass
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    if not prices:
        return None
    paid = [p for p in prices if p > 0]
    return min(paid) if paid else 0.0


def extract_ticketsports_price_from_url(url: str, timeout: int = 12) -> Optional[float]:
    """Busca preco no detalhe publico da TicketSports quando a URL aponta para /e/...-ID."""
    m = re.search(r"-(\d+)(?:\D*)?$", url or "")
    if not m:
        return None
    event_id = m.group(1)
    try:
        r = requests.get(
            "https://www.ticketsports.com.br/api/events/detail",
            params={"eventId": event_id},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Referer": url,
            },
            timeout=timeout,
        )
        if r.status_code >= 400:
            return None
        data = r.json()
    except Exception:
        return None

    for key in ("price", "fullPrice", "discount"):
        try:
            value = data.get(key)
            if value not in (None, ""):
                v = float(str(value).replace(",", "."))
                if v >= 0:
                    return v
        except Exception:
            pass

    chunks = []
    for content in data.get("eventContents") or []:
        if isinstance(content, dict):
            chunks.append(str(content.get("title") or ""))
            chunks.append(str(content.get("description") or ""))
    text = " ".join(chunks)
    price = find_minimum_price_of_text(text)
    if price:
        return price
    if re.search(r"\b(gratuit[oa]|gratis|gr[aá]tis)\b", text, re.I):
        return 0.0
    return None


def _slug_from_url(url: str) -> str:
    try:
        path = urlparse(url or "").path.strip("/")
        if not path:
            return ""
        return path.split("/")[0]
    except Exception:
        return ""


def classify_sport(text: str) -> str:
    t = remove_accents(text or "").lower()
    for sport, keys in _sport_keywords.items():
        for k in keys:
            if k and k in t:
                return sport
    return "Outros"


def clear_folder(folder_path: str):
    import shutil
    p = Path(folder_path)
    if not p.exists():
        return
    for item in p.iterdir():
        try:
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception as e:
            print(f"Erro ao remover {item}: {e}")


def download_file(downloads_folder: str, url: str) -> str:
    if not url:
        return ""
    Path(downloads_folder).mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, timeout=20, stream=True)
        r.raise_for_status()
    except Exception:
        return ""
    ext = ".jpg"
    path_part = url.split("?")[0]
    if "." in path_part.split("/")[-1]:
        ext = "." + path_part.split(".")[-1].split("/")[0][:5].lower()
        if len(ext) > 6 or "/" in ext:
            ext = ".jpg"
    import uuid
    fname = f"{uuid.uuid4()}{ext}"
    out = os.path.join(downloads_folder, fname)
    with open(out, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    return out


# ============= NOVAS UTILIDADES (v2, p/ MODELO) =============

def extract_bairro_from_address(address: str) -> str:
    """Extrai bairro do endereço. Tenta vários padrões:
    1. ", numero - Bairro, " (formato brasileiro padrão)
    2. ", Bairro - Cidade" (sem número antes)
    Evita pegar coisas tipo 'Villa-Lobos' como bairro.
    """
    if not address:
        return ""
    # Padrão 1: número seguido de " - Bairro, "
    m = re.search(r"(?:^|,)\s*\d+(?:\.\d+)?\s+[-–]\s+([^\n,]+)", address)
    if m:
        # Se vier "loja 22a - Copacabana", o bairro é o último trecho.
        bairro = re.split(r"\s+[-–]\s+", m.group(1))[-1].strip()
        if not re.search(r"\b(bloco|andar|sala|loja)\b", bairro, re.IGNORECASE):
            return bairro
    # "Local - Bairro, Cidade - UF" / "Local - Bairro, Cidade, UF"
    m = re.search(r"^[^,]+?\s+[-–]\s+([^,]+),\s*[^,]+(?:,|\s+[-–]\s+)[A-Z]{2}\b", address)
    if m:
        bairro = m.group(1).strip()
        if not re.fullmatch(r"[A-Z]{2}|BR|Brasil", bairro, re.IGNORECASE):
            return bairro
    # Padrão 2: " - Bairro, Cidade" (sem número, mas com espaços ao redor do dash)
    m = re.search(r"(?:^|,)\s+([A-Za-zÀ-ÿ][\w\sÀ-ÿ]{2,40}?)\s+[-–]\s+([A-Za-zÀ-ÿ\s]{2,40})", address)
    if m:
        after_dash = m.group(2).strip()
        if re.fullmatch(r"[A-Z]{2}|BR|Brasil", after_dash, re.IGNORECASE):
            return ""
        return m.group(1).strip()
    # Fallback: bairro como trecho imediatamente antes da cidade.
    parts = [
        p.strip()
        for p in re.split(r"[,|\n]+", address)
        if p and p.strip()
    ]
    city = find_city_on_address(address)
    city_norm = remove_accents(city).lower()
    bad = re.compile(
        r"^\d|cep|andar|bloco|sala|loja|avenida|av\.|rua|r\.|rodovia|estrada",
        re.IGNORECASE,
    )
    for i, part in enumerate(parts):
        part_norm = remove_accents(part).lower()
        if city_norm and part_norm == city_norm and i > 0:
            candidate = parts[i - 1].strip()
            candidate = re.sub(r"^\d+(?:[ºª]?\s*)?", "", candidate).strip()
            if candidate and not bad.search(candidate):
                return candidate
    # Padrão 3: " - Bairro" antes da cidade conhecida
    return ""


def round_up_int(value) -> int:
    """Arredonda preço pra cima conforme regra da Nath ('Cheio, sem vírgula')."""
    try:
        import math
        return int(math.ceil(float(value)))
    except Exception:
        return 0


_SAFE_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-_"


def safe_filename(text: str, max_len: int = 60) -> str:
    """Transforma texto em filename seguro (sem acento, sem espaço, etc)."""
    s = remove_accents(text or "").lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = "".join(c if c in _SAFE_CHARS else "" for c in s)
    return s[:max_len] or "evento"


def download_image_named(downloads_folder: str, url: str, site: str, slug_hint: str) -> str:
    """Baixa imagem no diretório `downloads/<site>/`. Devolve caminho ABSOLUTO local
    pra colocar na coluna `image`. Nath vai usar isso pra subir no AWS."""
    if not url:
        return ""
    folder = os.path.join(downloads_folder, site)
    Path(folder).mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, timeout=20, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except Exception:
        return ""
    # extensão
    content_type = r.headers.get("Content-Type", "").lower()
    if "jpeg" in content_type or "jpg" in content_type:
        ext = ".jpg"
    elif "png" in content_type:
        ext = ".png"
    elif "webp" in content_type:
        ext = ".webp"
    elif "gif" in content_type:
        ext = ".gif"
    else:
        # fallback pela URL
        path_part = url.split("?")[0].lower()
        for e in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            if path_part.endswith(e):
                ext = e
                break
        else:
            ext = ".jpg"
    fname = safe_filename(slug_hint) + ext
    out = os.path.join(folder, fname)
    with open(out, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    return os.path.abspath(out)


def first_date(date_str: str) -> str:
    """Se vier 'dd/mm/yyyy - dd/mm/yyyy' devolve só a primeira."""
    if not date_str:
        return ""
    parts = re.split(r"\s*[-–]\s*", date_str)
    return parts[0].strip() if parts else date_str
