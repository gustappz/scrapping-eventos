"""Salva CSVs e gera xlsx final no formato EXATO da MODELO Mapeamento bases.xlsx.

Ordem das colunas (compatível com o painel adm da Nath):
"""
import os
import re
from pathlib import Path

import pandas as pd
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


# Ordem oficial das colunas do xlsx final (deixa em branco "16", "22", "29", "30"
# que existem na planilha original como gaps visuais entre seções).
MODELO_COLS = [
    # INFORMAÇÕES BÁSICAS
    "eventName", "titleEvents", "dateEvents", "desc", "webSite",
    "city", "state", "coupon", "price", "ageRating", "image",
    "genresGroup", "amenities", "category",
    # INFORMAÇÕES EXTRAS
    "Produtor", "Local", "Bairro", "Endereço", "Instagram",
    # IMPORTAÇÃO
    "Site Extração", "Data extração", "Extrator",
    "Data validação", "Validador por", "Importado", "Local Ajustado",
]

# Mapeamento campo do EventDTO -> nome da coluna no xlsx
DTO_TO_COL = {
    "eventName": "eventName",
    "titleEvents": "titleEvents",
    "dateEvents": "dateEvents",
    "desc": "desc",
    "webSite": "webSite",
    "city": "city",
    "state": "state",
    "coupon": "coupon",
    "price": "price",
    "ageRating": "ageRating",
    "image": "image",
    "genresGroup": "genresGroup",
    "amenities": "amenities",
    "category": "category",
    "produtor": "Produtor",
    "local": "Local",
    "bairro": "Bairro",
    "address": "Endereço",
    "instagram": "Instagram",
    "site_extracao": "Site Extração",
    "data_extracao": "Data extração",
    "extrator": "Extrator",
    "data_validacao": "Data validação",
    "validador_por": "Validador por",
    "importado": "Importado",
    "local_ajustado": "Local Ajustado",
}


class DatabaseCSV:
    def __init__(self, data_folder: str):
        self.data_folder = data_folder
        Path(self.data_folder).mkdir(parents=True, exist_ok=True)

    def _path(self, filepath: str) -> str:
        return os.path.join(self.data_folder, filepath)

    def open(self, filepath: str) -> pd.DataFrame:
        if not filepath.endswith(".csv"):
            raise ValueError("Arquivo precisa ter extensão csv")
        full = self._path(filepath)
        if not os.path.exists(full):
            return pd.DataFrame()
        return pd.read_csv(full)

    def save(self, dataframe: pd.DataFrame, filepath: str):
        if not filepath.endswith(".csv"):
            raise ValueError("Arquivo precisa ter extensão csv")
        full = self._path(filepath)
        Path(os.path.dirname(full)).mkdir(parents=True, exist_ok=True)
        dataframe.reset_index(drop=True).to_csv(full, index=False)

    def concatenate(self, row: dict, filepath: str):
        try:
            existing = self.open(filepath)
        except Exception:
            existing = pd.DataFrame()
        new_df = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
        self.save(new_df, filepath)

    def group_csv_to_xlsx(self, folderpath: str, excel_filepath: str):
        full_folder = self._path(folderpath)
        if not excel_filepath.endswith(".xlsx"):
            raise ValueError("excel_filepath precisa terminar em .xlsx")
        if not os.path.isdir(full_folder):
            return
        csvs = [f for f in os.listdir(full_folder) if f.endswith(".csv")]
        if not csvs:
            return
        frames = []
        for f in csvs:
            try:
                df = pd.read_csv(os.path.join(full_folder, f))
                frames.append(df)
            except Exception:
                continue
        if not frames:
            return
        df = pd.concat(frames, ignore_index=True)

        # Dedup: (webSite, dateEvents) — preserva mesmo evento em datas distintas.
        if "webSite" in df.columns and "dateEvents" in df.columns:
            df = df.drop_duplicates(subset=["webSite", "dateEvents"], keep="last")
        elif "webSite" in df.columns:
            df = df.drop_duplicates(subset=["webSite"], keep="last")

        # Renomeia colunas do DTO pras colunas oficiais
        df = df.rename(columns=DTO_TO_COL)

        # Garante TODAS as colunas do MODELO (mesmo as em branco)
        for col in MODELO_COLS:
            if col not in df.columns:
                df[col] = ""

        # Mantém só as colunas do MODELO, na ordem certa
        df = df[MODELO_COLS]

        # Remove caracteres invisiveis que o Excel/openpyxl nao aceita.
        illegal_chars = re.compile(r"[\x00-\x08\x0B-\x1F\x7F]")
        for col in df.columns:
            df[col] = df[col].map(
                lambda v: illegal_chars.sub(" ", v) if isinstance(v, str) else v
            )

        # Limpa NaN -> string vazia (Nath vai colar no painel)
        df = df.fillna("")

        # Preço como inteiro (regra: arredondar pra cima, sem vírgula)
        if "price" in df.columns:
            def _to_int(v):
                try:
                    import math
                    return int(math.ceil(float(v))) if v not in ("", None) else ""
                except Exception:
                    return ""
            df["price"] = df["price"].apply(_to_int)

        out_path = self._path(excel_filepath)
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="eventos")
            ws = writer.sheets["eventos"]
            header_font = Font(name="Calibri", bold=True, color="FFFFFF")
            header_fill = PatternFill(fill_type="solid", start_color="4472C4",
                                      end_color="4472C4")
            border = Border(*[Side(border_style="thin", color="999999")] * 4)
            for j, col in enumerate(df.columns, start=1):
                cell = ws.cell(row=1, column=j)
                cell.font = header_font
                cell.fill = header_fill
                cell.border = border
                # auto-ajusta largura
                try:
                    max_len = max(
                        [len(str(col))] +
                        [len(str(v)) for v in df[col].head(200).tolist()]
                    )
                except Exception:
                    max_len = len(str(col))
                ws.column_dimensions[get_column_letter(j)].width = min(
                    max(12, max_len + 2), 60
                )
