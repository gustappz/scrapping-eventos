# Scraping de Eventos

Aplicação desktop que coleta eventos de **10 plataformas de ingressos e turismo** e consolida tudo em planilhas padronizadas. Feita sob demanda para uma cliente e entregue como executável para Windows.

## O que faz

- Coleta eventos de: Clubinho, Fever, Ingresse, Mapa dos Festivais, Shotgun, Ticket360, TicketSports, Uhuu, Visite Rio e Visite São Paulo.
- Normaliza os dados de todas as fontes em um formato único (`EventDTO`) e classifica cada evento numa taxonomia de categorias.
- Exporta um CSV por fonte/estado e gera uma planilha Excel (`.xlsx`) consolidada.
- Interface gráfica para escolher fontes e período, com log em tempo real, sem precisar de terminal.

## Stack

- **Python** · **Selenium** (navegação e coleta) · **Requests**
- **pandas** + **openpyxl** para consolidar e formatar a planilha final
- **PySide6 (Qt)** para a interface desktop, com a coleta rodando em thread separada (`QThread`) para não travar a tela
- **PyInstaller** para empacotar como `.exe`

## Arquitetura

```
src/
├── app.py            # interface PySide6 e orquestração da coleta
├── base.py           # SeleniumBase: configuração e utilitários do navegador
├── scraping/         # um navigator por plataforma
├── eventDTO.py       # modelo único de evento
├── taxonomia.py      # classificação de eventos em categorias
├── database.py       # gravação em CSV e consolidação em XLSX
└── logger.py         # logs
```

Cada plataforma tem seu próprio módulo em `scraping/`, então adicionar uma fonte nova não mexe nas outras.

## Como rodar

```bash
pip install selenium requests PySide6 pandas openpyxl
python src/app.py
```

Para gerar o executável: `python build_exe.py`.
