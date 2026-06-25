"""Modelo de dados do evento. Espelha as colunas da planilha oficial da Nath.

Ordem exata da MODELO Mapeamento bases.xlsx:
INFORMAÇÕES BÁSICAS: eventName, titleEvents, dateEvents, desc, webSite, city,
                    state, coupon, price, ageRating, image, genresGroup,
                    amenities, category
INFORMAÇÕES EXTRAS: Produtor, Local, Bairro, Endereço, Instagram
IMPORTAÇÃO:        Site Extração, Data extração, Extrator, Data validação,
                    Validador por, Importado, Local Ajustado
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EventDTO:
    # INFORMAÇÕES BÁSICAS
    eventName: str = ""
    titleEvents: str = ""       # = eventName
    dateEvents: str = ""        # dd/mm/yyyy
    desc: str = ""              # descrição sem parágrafos/emojis
    webSite: str = ""           # URL DO EVENTO (não nome do site)
    city: str = ""
    state: str = ""
    coupon: str = "-"
    price: float = 0.0          # inteiro arredondado pra cima (cheio)
    ageRating: str = ""
    image: str = ""             # CAMINHO LOCAL do arquivo de imagem
    genresGroup: str = ""       # ex: "Pop, Eletrônica"
    amenities: str = ""         # ex: "DJ, Open Bar"
    category: str = "Todos"     # SEMPRE inclui "Todos"

    # INFORMAÇÕES EXTRAS
    produtor: str = ""
    local: str = ""
    bairro: str = ""
    address: str = ""
    instagram: str = ""

    # IMPORTAÇÃO
    site_extracao: str = ""     # ex: "Shotgun"
    data_extracao: str = ""     # data de hoje dd/mm/yyyy
    extrator: str = "Bot"
    data_validacao: str = ""
    validador_por: str = ""
    importado: str = ""
    local_ajustado: str = ""

    # Campos internos (não vão pro xlsx)
    image_url: str = ""         # URL remota da imagem (pra baixar)
    event_url_internal: str = ""  # cópia da URL pra dedup
    raw_categories: list = field(default_factory=list)  # categorias originais do site
    extra_dates: list = field(default_factory=list)     # outras datas (eventos multi-dia)

    def __post_init__(self):
        if not self.titleEvents and self.eventName:
            self.titleEvents = self.eventName
        if not self.data_extracao:
            self.data_extracao = datetime.now().strftime("%d/%m/%Y")
