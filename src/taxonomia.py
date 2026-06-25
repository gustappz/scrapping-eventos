"""Categorias, gêneros e comodidades EXATAMENTE como na aba 'Classificações'
da planilha oficial da Nath. Tem que bater letra por letra senão o painel adm
não reconhece.
"""
from __future__ import annotations

CATEGORIAS = {
    "Todos", "Festas", "Sazonal", "Shows", "Festivais", "Gastronomia",
    "Culturais", "Pride", "Geek/Pop", "Stand Up", "Rodas de Samba",
    "Infantil", "Pets", "Esportivos", "Gratuitos",
    "Reveillon", "Halloween", "Carnaval", "Festas Juninas",
    "Acessíveis", "Casas Show / Boates", "Feito por elas", "Economia prateada",
}

GENEROS = {
    "Alternativo", "Pop", "Rock", "Eletrônica", "Rap", "Hip Hop", "MPB",
    "Samba", "Pagode", "Sertanejo", "Forró & Piseiro", "Funk", "Reggae",
    "R&B", "Country & Folk", "Disco", "Clássica", "Kpop", "Geek",
    "Latina", "Regionais", "Jazz & Blues", "Brasilidades", "Infantil",
}

COMODIDADES = {
    "Acessibilidade", "Área de fumantes", "Área Kids", "Comida no local",
    "Cardápio vegano", "Estacionamento", "Espaço Aberto", "Espaço Coberto",
    "Lugar para sentar", "Pet friendly", "Piso regular", "Ar condicionado",
    "Banda", "DJ", "Karaokê", "Open Bar",
    "Eventos diurnos", "Eventos ao entardecer", "Eventos noturnos",
}


# Mapeamento de termos comuns dos sites -> taxonomia oficial.
# Tudo lowercase pra match insensível.
_GENERO_ALIAS = {
    "alternative": "Alternativo", "alternativo": "Alternativo", "indie": "Alternativo",
    "pop": "Pop", "pop music": "Pop",
    "rock": "Rock", "rock and roll": "Rock", "metal": "Rock", "punk": "Rock",
    "eletronica": "Eletrônica", "eletrônica": "Eletrônica", "electronic": "Eletrônica",
    "techno": "Eletrônica", "house": "Eletrônica", "edm": "Eletrônica",
    "drum and bass": "Eletrônica", "dnb": "Eletrônica", "trance": "Eletrônica",
    "dance": "Eletrônica", "psytrance": "Eletrônica", "rave": "Eletrônica",
    "rap": "Rap", "trap": "Rap",
    "hip hop": "Hip Hop", "hip-hop": "Hip Hop", "hiphop": "Hip Hop",
    "mpb": "MPB", "música popular brasileira": "MPB",
    "samba": "Samba", "samba rock": "Samba",
    "pagode": "Pagode",
    "sertanejo": "Sertanejo", "country brasileiro": "Sertanejo",
    "forró": "Forró & Piseiro", "forro": "Forró & Piseiro",
    "piseiro": "Forró & Piseiro", "arrocha": "Forró & Piseiro",
    "funk": "Funk", "funk brasileiro": "Funk", "baile funk": "Funk",
    "reggae": "Reggae", "dub": "Reggae",
    "r&b": "R&B", "rnb": "R&B", "soul": "R&B",
    "country": "Country & Folk", "folk": "Country & Folk",
    "disco": "Disco",
    "clássica": "Clássica", "classica": "Clássica", "classical": "Clássica",
    "orquestral": "Clássica", "música clássica": "Clássica",
    "kpop": "Kpop", "k-pop": "Kpop", "k pop": "Kpop",
    "geek": "Geek", "anime": "Geek", "nerd": "Geek",
    "latina": "Latina", "reggaeton": "Latina", "salsa": "Latina", "latino": "Latina",
    "regional": "Regionais", "regionais": "Regionais",
    "jazz": "Jazz & Blues", "blues": "Jazz & Blues", "soulful": "Jazz & Blues",
    "brasilidades": "Brasilidades", "brasileira": "Brasilidades",
    "infantil": "Infantil", "criança": "Infantil", "kids": "Infantil",
}

_CATEGORIA_ALIAS = {
    "festa": "Festas", "festas": "Festas", "party": "Festas", "balada": "Festas",
    "show": "Shows", "shows": "Shows", "concerto": "Shows",
    "festival": "Festivais", "festivais": "Festivais",
    "gastronomia": "Gastronomia", "gastro": "Gastronomia",
    "food festival": "Gastronomia", "feira gastronômica": "Gastronomia",
    "cultural": "Culturais", "culturais": "Culturais", "exposição": "Culturais",
    "exposicao": "Culturais", "teatro": "Culturais", "musical": "Culturais",
    "ópera": "Culturais", "opera": "Culturais",
    "pride": "Pride", "lgbt": "Pride", "lgbtq": "Pride",
    "geek": "Geek/Pop", "anime": "Geek/Pop", "comic": "Geek/Pop",
    "stand up": "Stand Up", "standup": "Stand Up", "stand-up": "Stand Up",
    "comédia": "Stand Up", "comedia": "Stand Up", "humor": "Stand Up",
    "samba": "Rodas de Samba", "roda de samba": "Rodas de Samba",
    "infantil": "Infantil", "kids": "Infantil", "criança": "Infantil",
    "teatro infantil": "Infantil",
    "pet": "Pets", "pets": "Pets",
    "corrida": "Esportivos", "maratona": "Esportivos", "ciclismo": "Esportivos",
    "esporte": "Esportivos", "esportivo": "Esportivos", "triathlon": "Esportivos",
    "running": "Esportivos", "mtb": "Esportivos", "trail": "Esportivos",
    "gratuito": "Gratuitos", "grátis": "Gratuitos", "gratis": "Gratuitos",
    "free": "Gratuitos",
    "reveillon": "Reveillon", "réveillon": "Reveillon", "ano novo": "Reveillon",
    "halloween": "Halloween", "dia das bruxas": "Halloween",
    "carnaval": "Carnaval", "bloco": "Carnaval",
    "festa junina": "Festas Juninas", "junina": "Festas Juninas",
    "são joão": "Festas Juninas", "sao joao": "Festas Juninas",
    "arraial": "Festas Juninas",
    "show e turne": "Shows", "show e turnê": "Shows", "turne": "Shows",
}


def _normalize(text: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", text or "").encode("ASCII", "ignore").decode().lower().strip()
    return s


def _word_match(alias: str, text: str) -> bool:
    """Match com fronteira de palavra: 'pet' não casa em 'Peter Pan'."""
    import re
    # se contém espaço ou caractere especial, busca como substring com bordas
    pattern = r"(?:^|[^a-z0-9])" + re.escape(alias) + r"(?:[^a-z0-9]|$)"
    return bool(re.search(pattern, text))


def classify_genres(text: str) -> str:
    """Devolve string 'Pop, Eletrônica' (gêneros válidos detectados)."""
    if not text:
        return ""
    low = _normalize(text)
    found = []
    for alias, official in _GENERO_ALIAS.items():
        if _word_match(alias, low) and official not in found:
            found.append(official)
    return ", ".join(found)


def classify_category(text: str) -> str:
    """Devolve 'Todos, X' onde X são categorias detectadas. SEMPRE inclui Todos."""
    out = ["Todos"]
    if not text:
        return "Todos"
    low = _normalize(text)
    for alias, official in _CATEGORIA_ALIAS.items():
        if _word_match(alias, low) and official not in out:
            out.append(official)
    return ", ".join(out)


def classify_amenities(text: str) -> str:
    """Procura comodidades no texto."""
    if not text:
        return ""
    low = _normalize(text)
    found = []
    aliases = {
        "dj": "DJ",
        "open bar": "Open Bar", "openbar": "Open Bar",
        "estacionamento": "Estacionamento", "parking": "Estacionamento",
        "ar condicionado": "Ar condicionado",
        "pet friendly": "Pet friendly", "petfriendly": "Pet friendly",
        "karaoke": "Karaokê", "karaokê": "Karaokê",
        "comida": "Comida no local", "gastronomia": "Comida no local",
        "vegano": "Cardápio vegano", "vegan": "Cardápio vegano",
        "infantil": "Área Kids", "kids": "Área Kids",
        "acessibilidade": "Acessibilidade", "acessivel": "Acessibilidade",
        "fumante": "Área de fumantes",
        "banda": "Banda", "ao vivo": "Banda",
        "espaco aberto": "Espaço Aberto", "open air": "Espaço Aberto",
        "espaco coberto": "Espaço Coberto", "coberto": "Espaço Coberto",
        "noturno": "Eventos noturnos", "night": "Eventos noturnos",
        "diurno": "Eventos diurnos", "day": "Eventos diurnos",
        "entardecer": "Eventos ao entardecer",
    }
    for alias, official in aliases.items():
        if _word_match(alias, low) and official not in found:
            found.append(official)
    return ", ".join(found)
