"""GUI principal: janela única com menu de sites + filtros + botão "Iniciar".

Roda cada scraper em uma QThread separada pra não travar a janela.
Logs aparecem em tempo real na caixa preta no rodapé.
"""
import os
import re
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

# garante que o pacote `scraping` carregue ao rodar como script direto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont, QIcon, QIntValidator, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from base import SeleniumBase
from database import DatabaseCSV
from eventDTO import EventDTO
from logger import LoggerService


# Cada site:
#   key: nome de exibição
#   filter_label / placeholder: texto pra ajudar o usuário
#   filter_kind: "city" | "state" | "int" | "none"
#   needs_chrome_stealth: precisa undetected-chromedriver?
SITES = {
    "MapaDosFestivais": {
        "label": "Filtro:",
        "placeholder": "Sem filtro — coleta o Brasil inteiro",
        "filter_kind": "none",
        "needs_chrome_stealth": False,
    },
    "TicketSports": {
        "label": "Estado (sigla):",
        "placeholder": "Ex: RJ, SP, MG, PR...",
        "filter_kind": "state",
        "needs_chrome_stealth": True,
    },
    "Clubinho": {
        "label": "Cidade:",
        "placeholder": "Ex: São Paulo, Rio de Janeiro, Porto Alegre",
        "filter_kind": "city",
        "needs_chrome_stealth": False,
    },
    "Ingresse": {
        "label": "Estado (sigla):",
        "placeholder": "Ex: RJ, SP, MG...",
        "filter_kind": "state",
        "needs_chrome_stealth": False,
    },
    "Visite RJ (com IA)": {
        "label": "Períodos de 5 dias (1-15):",
        "placeholder": "Ex: 6 (= 30 dias futuros). Nath, use 6+ pra ter margem.",
        "filter_kind": "int",
        "needs_chrome_stealth": True,
        "int_range": (1, 15),
        "default": "6",
    },
    "Visite SP (com IA)": {
        "label": "Meses a frente (1-6):",
        "placeholder": "Ex: 1 (= 1 mês futuro). Use 3 só se quiser muita margem.",
        "filter_kind": "int",
        "needs_chrome_stealth": True,
        "int_range": (1, 6),
        "default": "1",
    },
    "Shotgun": {
        "label": "Cidade:",
        "placeholder": "Ex: São Paulo, Rio de Janeiro",
        "filter_kind": "city",
        "needs_chrome_stealth": True,
    },
}


# ---------------------- WORKER THREAD ----------------------


class ScrapingWorker(QThread):
    finished = Signal(int)              # n_eventos
    error = Signal(str)
    log_message = Signal(str)

    def __init__(self, site_name: str, filter_value: str, base_dir: Path, parent=None):
        super().__init__(parent)
        self.site_name = site_name
        self.filter_value = filter_value
        self.base_dir = base_dir

    def run(self):
        try:
            self._run_inner()
        except Exception as e:
            tb = traceback.format_exc()
            self.error.emit(f"{e}\n\n{tb}")

    # ----- logger que repassa pra GUI -----
    def _make_logger(self):
        gui_logger = LoggerService(log_dir=str(self.base_dir / "output" / "logs"))
        original_debug = gui_logger.debug
        original_info = gui_logger.info
        original_error = gui_logger.error
        original_warning = gui_logger.warning

        def wrap(level, fn):
            def w(msg):
                fn(msg)
                self.log_message.emit(f"[{level}] {msg}")
            return w

        gui_logger.debug = wrap("DEBUG", original_debug)
        gui_logger.info = wrap("INFO", original_info)
        gui_logger.error = wrap("ERRO", original_error)
        gui_logger.warning = wrap("WARN", original_warning)
        return gui_logger

    def _run_inner(self):
        cfg = SITES[self.site_name]
        data_dir = self.base_dir / "output" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        logger = self._make_logger()
        db = DatabaseCSV(str(data_dir))

        if self.site_name == "MapaDosFestivais":
            self._run_mapados(logger, db)
        elif self.site_name == "TicketSports":
            self._run_ticketsports(logger, db)
        elif self.site_name == "Clubinho":
            self._run_clubinho(logger, db)
        elif self.site_name == "Ingresse":
            self._run_ingresse(logger, db)
        elif self.site_name == "Visite RJ (com IA)":
            self._run_visiterj(logger, db)
        elif self.site_name == "Visite SP (com IA)":
            self._run_visitesp(logger, db)
        elif self.site_name == "Shotgun":
            self._run_shotgun(logger, db)
        else:
            raise ValueError(f"Site desconhecido: {self.site_name}")

    # -------- runners --------

    def _run_mapados(self, logger, db):
        from scraping.mapadosfestivais_navigator import MapaDosFestivaisNavigator
        folder = "mapadosfestivais"
        (self.base_dir / "output" / "data" / folder).mkdir(parents=True, exist_ok=True)
        csv_path = f"{folder}/Geral.csv"
        self._reset_csv(csv_path)
        nav = MapaDosFestivaisNavigator(
            logger=logger,
            downloads_folder=str(self.base_dir / "output" / "downloads"),
        )
        n = 0
        for dto in nav.scrape_all(should_stop=self.isInterruptionRequested):
            db.concatenate(asdict(dto), csv_path)
            n += 1
        db.group_csv_to_xlsx(folder, "mapadosfestivais.xlsx")
        self.finished.emit(n)

    def _run_ticketsports(self, logger, db):
        from scraping.ticketsports_navigator import TicketSportsNavigator
        state = self.filter_value.strip().upper()
        folder = "ticketsports"
        (self.base_dir / "output" / "data" / folder).mkdir(parents=True, exist_ok=True)
        csv_path = f"{folder}/{state}.csv"
        self._reset_csv(csv_path)
        downloads = str(self.base_dir / "output" / "downloads")
        n = 0
        nav = TicketSportsNavigator(None, logger)
        events = nav.get_events_URLs(state)
        for i, e in enumerate(events, 1):
            if self.isInterruptionRequested():
                break
            if i % 10 == 0:
                logger.info(f"Detalhando TicketSports {i}/{len(events)}...")
            nav.enrich_event(e, downloads_folder=downloads)
            db.concatenate(asdict(e), csv_path)
            n += 1
        db.group_csv_to_xlsx(folder, "ticketsports.xlsx")
        self.finished.emit(n)

    def _run_clubinho(self, logger, db):
        from scraping.clubinho_scraper import ClubinhoScraper, CITY_MAPPING, format_city_name
        folder = "clubinho"
        (self.base_dir / "output" / "data" / folder).mkdir(parents=True, exist_ok=True)
        city = self.filter_value.strip()
        slug = CITY_MAPPING.get(city) or format_city_name(city)
        csv_path = f"{folder}/{slug}.csv"
        self._reset_csv(csv_path)
        nav = ClubinhoScraper(logger=logger,
                               downloads_folder=str(self.base_dir / "output" / "downloads"))
        events = nav.get_params_from_city(city, fetch_details=True,
                                          should_stop=self.isInterruptionRequested)
        for e in events:
            db.concatenate(asdict(e), csv_path)
        db.group_csv_to_xlsx(folder, "clubinho.xlsx")
        self.finished.emit(len(events))

    def _run_ingresse(self, logger, db):
        from scraping.ingresse_navigator import IngresseNavigator
        state = self.filter_value.strip().upper()
        folder = "ingresse"
        (self.base_dir / "output" / "data" / folder).mkdir(parents=True, exist_ok=True)
        csv_path = f"{folder}/{state}.csv"
        self._reset_csv(csv_path)
        downloads = str(self.base_dir / "output" / "downloads")
        sb = SeleniumBase(logger)
        sb.initialize_driver(headless=True)
        events = []
        try:
            nav = IngresseNavigator(sb, logger)
            events = nav.get_events_URLs(state)
            for i, e in enumerate(events, 1):
                if self.isInterruptionRequested():
                    break
                if i % 10 == 0:
                    logger.info(f"Enriquecendo {i}/{len(events)} eventos...")
                nav.enrich_event(e, downloads_folder=downloads)
            for e in events:
                row = asdict(e)
                # Eventos multi-dia: 1 linha por data
                extras = list(row.pop("extra_dates", []) or [])
                db.concatenate(row, csv_path)
                for d in extras:
                    extra_row = dict(row)
                    extra_row["dateEvents"] = d
                    db.concatenate(extra_row, csv_path)
        finally:
            sb.quit_driver()
        db.group_csv_to_xlsx(folder, "ingresse.xlsx")
        self.finished.emit(len(events))

    def _run_visiterj(self, logger, db):
        """Visite RJ — Selenium navega serial (precisa passar Cloudflare),
        mas após coletar HTML, chama Gemini em paralelo (4 threads)."""
        from scraping.visite_navigator import VisiteNavigator
        from concurrent.futures import ThreadPoolExecutor
        ffd = int(self.filter_value)
        folder = "visiterj"
        (self.base_dir / "output" / "data" / folder).mkdir(parents=True, exist_ok=True)
        csv_path = f"{folder}/Rio-de-Janeiro.csv"
        self._reset_csv(csv_path)
        downloads = str(self.base_dir / "output" / "downloads")
        sb = SeleniumBase(logger)
        sb.initialize_driver(headless=False, stealth=True)
        n = 0
        try:
            nav = VisiteNavigator(sb, logger)
            urls = nav.get_events_URLs_RJ(ffd)
            # Fase 1: Selenium serial pra baixar HTML (passa CF)
            htmls = []
            for i, url in enumerate(urls, 1):
                if self.isInterruptionRequested():
                    break
                logger.info(f"[CF {i}/{len(urls)}] Baixando {url}")
                html = nav._fetch_html_with_cloudflare(url)
                if html:
                    title = nav._extract_title_or_h1()
                    htmls.append((url, html, title))
            # Fase 2: Gemini em paralelo
            logger.info(f"Processando {len(htmls)} eventos com Gemini (paralelo)...")
            def _process(item):
                url, html, title = item
                dto = nav.get_info_of_event_RJ_from_html(
                    url, html, title, downloads_folder=downloads,
                )
                return dto
            with ThreadPoolExecutor(max_workers=4) as pool:
                for dto in pool.map(_process, htmls):
                    if self.isInterruptionRequested():
                        break
                    if dto:
                        db.concatenate(asdict(dto), csv_path)
                        n += 1
        finally:
            sb.quit_driver()
        db.group_csv_to_xlsx(folder, "visiteRJ.xlsx")
        self.finished.emit(n)

    def _run_visitesp(self, logger, db):
        from scraping.visite_navigator import VisiteNavigator
        from concurrent.futures import ThreadPoolExecutor
        months = int(self.filter_value)
        folder = "visitesp"
        (self.base_dir / "output" / "data" / folder).mkdir(parents=True, exist_ok=True)
        csv_path = f"{folder}/Sao-Paulo.csv"
        self._reset_csv(csv_path)
        downloads = str(self.base_dir / "output" / "downloads")
        n = 0
        nav = VisiteNavigator(None, logger)
        urls = nav.get_events_URLs_SP(months)
        logger.info(f"Processando {len(urls)} eventos do Visite SP em paralelo...")
        with ThreadPoolExecutor(max_workers=6) as pool:
            for dto in pool.map(lambda url: nav.get_info_of_event_SP(url, downloads_folder=downloads), urls):
                if self.isInterruptionRequested():
                    break
                if dto:
                    db.concatenate(asdict(dto), csv_path)
                    n += 1
        db.group_csv_to_xlsx(folder, "visiteSP.xlsx")
        self.finished.emit(n)

    def _run_shotgun(self, logger, db):
        from scraping.shotgun_navigator import ShotgunNavigator, city_to_slug
        city = self.filter_value.strip()
        folder = "shotgun"
        (self.base_dir / "output" / "data" / folder).mkdir(parents=True, exist_ok=True)
        slug = city_to_slug(city)
        csv_path = f"{folder}/{slug}.csv"
        self._reset_csv(csv_path)
        downloads = str(self.base_dir / "output" / "downloads")
        sb = SeleniumBase(logger)
        sb.initialize_driver(headless=False, stealth=True)
        n = 0
        try:
            nav = ShotgunNavigator(sb, logger)
            events = nav.get_events_URLs(city)
            # 1) Enriquecimento rápido (JSON-LD)
            for i, e in enumerate(events, 1):
                if self.isInterruptionRequested():
                    break
                if i % 25 == 0:
                    logger.info(f"Enriquecendo rápido {i}/{len(events)}...")
                nav.enrich_event(e, downloads_folder=downloads)
            # 2) Enriquecimento lento (Selenium per page) — pega MOOD real do site
            for i, e in enumerate(events, 1):
                if self.isInterruptionRequested():
                    break
                if i % 10 == 0:
                    logger.info(f"Detalhando Shotgun MOOD {i}/{len(events)}...")
                nav.enrich_event_selenium(e, downloads_folder=downloads)
            for e in events:
                db.concatenate(asdict(e), csv_path)
                n += 1
        finally:
            sb.quit_driver()
        db.group_csv_to_xlsx(folder, "shotgun.xlsx")
        self.finished.emit(n)

    def _reset_csv(self, rel_path: str):
        f = self.base_dir / "output" / "data" / rel_path
        if f.exists():
            f.unlink()


# ---------------------- MAIN WINDOW ----------------------


STYLE = """
QMainWindow { background: #1e1e2e; }
QLabel { color: #cdd6f4; font-size: 13px; }
#title { color: #f5f5f5; font-size: 22px; font-weight: 700; padding: 8px 0; }
#subtitle { color: #94a3b8; font-size: 12px; }
QComboBox, QLineEdit {
    background: #313244;
    color: #e2e2e2;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 14px;
}
QComboBox:hover, QLineEdit:hover { border-color: #74c7ec; }
QComboBox QAbstractItemView {
    background: #313244;
    color: #e2e2e2;
    selection-background-color: #45475a;
}
QPushButton#start {
    background: #4CAF50; color: white;
    border: none; border-radius: 6px;
    padding: 12px 18px; font-size: 15px; font-weight: 600;
}
QPushButton#start:hover { background: #45a049; }
QPushButton#start:disabled { background: #4a5060; color: #888; }
QPushButton#stop {
    background: #f44336; color: white;
    border: none; border-radius: 6px;
    padding: 12px 18px; font-size: 15px; font-weight: 600;
}
QPushButton#stop:hover { background: #d73a30; }
QPushButton#open {
    background: #2a2a3a; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 6px;
    padding: 8px 14px; font-size: 13px;
}
QPushButton#open:hover { background: #313244; border-color: #74c7ec; }
QTextEdit#log {
    background: #11111b;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 6px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
    padding: 8px;
}
QStatusBar { background: #1e1e2e; color: #94a3b8; border-top: 1px solid #313244; }
"""


class ScrapingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scraping Eventos")
        self.setMinimumSize(880, 640)
        self.setStyleSheet(STYLE)

        # base dir:
        #  - rodando como script: pasta do projeto (um nivel acima de src/)
        #  - rodando como .exe (PyInstaller): pasta onde o .exe esta
        if getattr(sys, "frozen", False):
            self.base_dir = Path(sys.executable).resolve().parent
        else:
            self.base_dir = Path(__file__).resolve().parent.parent

        self.worker: ScrapingWorker | None = None
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        # Header
        title = QLabel("Scraping Eventos")
        title.setObjectName("title")
        subtitle = QLabel(
            "Escolhe o site, define o filtro e clica em Iniciar. "
            "O resultado vai pra pasta output/data/*.xlsx"
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        # Row 1: site
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Site:"))
        self.site_combo = QComboBox()
        self.site_combo.addItems(SITES.keys())
        self.site_combo.currentIndexChanged.connect(self._on_site_changed)
        row1.addWidget(self.site_combo, 1)
        layout.addLayout(row1)

        # Row 2: filter
        row2 = QHBoxLayout()
        self.filter_label = QLabel("Filtro:")
        row2.addWidget(self.filter_label)
        self.filter_input = QLineEdit()
        row2.addWidget(self.filter_input, 1)
        layout.addLayout(row2)

        # Row 3: buttons
        row3 = QHBoxLayout()
        self.start_btn = QPushButton("Iniciar Scraping")
        self.start_btn.setObjectName("start")
        self.start_btn.clicked.connect(self._start)
        row3.addWidget(self.start_btn, 1)

        self.open_folder_btn = QPushButton("Abrir pasta de resultados")
        self.open_folder_btn.setObjectName("open")
        self.open_folder_btn.clicked.connect(self._open_output_folder)
        row3.addWidget(self.open_folder_btn)
        layout.addLayout(row3)

        # Logs
        log_label = QLabel("Logs:")
        layout.addWidget(log_label)
        self.log_output = QTextEdit()
        self.log_output.setObjectName("log")
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output, 1)

        self.setCentralWidget(central)

        self.status_bar = QStatusBar()
        self.status_bar.showMessage("Pronto pra começar.")
        self.setStatusBar(self.status_bar)

        # init placeholder
        self._on_site_changed(0)

    @Slot(int)
    def _on_site_changed(self, _idx: int):
        cfg = SITES[self.site_combo.currentText()]
        self.filter_label.setText(cfg["label"])
        self.filter_input.setPlaceholderText(cfg["placeholder"])
        self.filter_input.setText(cfg.get("default", ""))
        if cfg["filter_kind"] == "none":
            self.filter_input.setEnabled(False)
            self.filter_input.setText("(não precisa)")
        else:
            self.filter_input.setEnabled(True)
            if cfg["filter_kind"] == "int":
                self.filter_input.setValidator(QIntValidator(*cfg.get("int_range", (1, 99))))
            else:
                self.filter_input.setValidator(None)

    def _start(self):
        if self.worker and self.worker.isRunning():
            self._stop()
            return
        site = self.site_combo.currentText()
        cfg = SITES[site]
        value = self.filter_input.text().strip()
        if cfg["filter_kind"] != "none" and (not value or value == "(não precisa)"):
            QMessageBox.warning(self, "Filtro vazio",
                                f"Preencha o campo '{cfg['label']}'.")
            return
        if cfg["filter_kind"] == "state" and len(value) != 2:
            QMessageBox.warning(self, "Estado inválido",
                                "Digite a sigla de 2 letras (RJ, SP, MG...).")
            return
        if cfg["filter_kind"] == "int":
            try:
                n = int(value)
                lo, hi = cfg.get("int_range", (1, 99))
                if not (lo <= n <= hi):
                    raise ValueError()
            except ValueError:
                QMessageBox.warning(self, "Valor inválido",
                                    f"Digite um número entre {lo} e {hi}.")
                return

        self.log_output.clear()
        self._log(f"=== Iniciando scraping: {site} ({value or 'sem filtro'}) ===")
        self.status_bar.showMessage("Rodando...")
        self.start_btn.setText("Parar Scraping")
        self.start_btn.setObjectName("stop")
        self.start_btn.setStyleSheet("")  # força refresh
        self.setStyleSheet(STYLE)

        self.worker = ScrapingWorker(site, value, self.base_dir, parent=self)
        self.worker.log_message.connect(self._log)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _stop(self):
        if self.worker and self.worker.isRunning():
            self._log("=== Solicitando parada... ===")
            self.worker.requestInterruption()
            self.status_bar.showMessage("Parando...")
            self.start_btn.setEnabled(False)

    @Slot(str)
    def _log(self, message: str):
        # Remove timestamps de log do framework (já vem com nivel)
        self.log_output.append(message)
        cur = self.log_output.textCursor()
        cur.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cur)

    @Slot(int)
    def _on_finished(self, n_eventos: int):
        self._log(f"=== Concluído! {n_eventos} eventos salvos. ===")
        self.status_bar.showMessage(f"Pronto. {n_eventos} eventos coletados.")
        self.start_btn.setText("Iniciar Scraping")
        self.start_btn.setObjectName("start")
        self.setStyleSheet(STYLE)
        self.start_btn.setEnabled(True)
        QMessageBox.information(
            self, "Scraping concluído",
            f"{n_eventos} eventos foram salvos em output/data/*.xlsx",
        )

    @Slot(str)
    def _on_error(self, message: str):
        self._log(f"[ERRO] {message}")
        self.status_bar.showMessage("Erro durante scraping.")
        self.start_btn.setText("Iniciar Scraping")
        self.start_btn.setObjectName("start")
        self.setStyleSheet(STYLE)
        self.start_btn.setEnabled(True)
        QMessageBox.critical(self, "Erro no scraping", message[:600])

    def _open_output_folder(self):
        out = self.base_dir / "output" / "data"
        out.mkdir(parents=True, exist_ok=True)
        os.startfile(str(out))  # type: ignore[attr-defined]


def _run_cli(site: str, value: str):
    """Modo linha-de-comando: roda 1 scraper direto, sem GUI. Pra teste/automação.
    Como o .exe é windowed (sem console), a saida vai num arquivo `_cli_output.txt`
    na pasta do .exe."""
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent.parent

    out_log = base_dir / "_cli_output.txt"
    log_fp = open(out_log, "w", encoding="utf-8")

    def write(msg):
        try:
            log_fp.write(str(msg) + "\n")
            log_fp.flush()
        except Exception:
            pass
        try:
            print(msg)
        except Exception:
            pass

    write(f"=== CLI: {site} | filtro={value!r} | base_dir={base_dir} ===")

    worker = ScrapingWorker(site, value, base_dir)
    worker.log_message.connect(write)
    worker.finished.connect(lambda n: write(f"=== Done. {n} eventos ==="))
    worker.error.connect(lambda e: write(f"=== ERRO ===\n{e}"))
    try:
        worker._run_inner()
    except Exception as e:
        import traceback
        write(f"=== CRASH ===\n{e}\n{traceback.format_exc()}")
    log_fp.close()


def main():
    # Modo CLI: --cli SITE [FILTRO]
    if "--cli" in sys.argv:
        i = sys.argv.index("--cli")
        rest = sys.argv[i + 1:]
        site = rest[0] if rest else "MapaDosFestivais"
        value = rest[1] if len(rest) > 1 else ""
        # Precisa QApplication mesmo no CLI por causa do QThread/Signal
        app = QApplication(sys.argv)
        _run_cli(site, value)
        return

    app = QApplication(sys.argv)
    app.setApplicationName("Scraping Eventos")
    win = ScrapingApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
