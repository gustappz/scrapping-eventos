import os
import pandas as pd

files = {
    "mapadosfestivais.xlsx": "MapaDosFestivais",
    "ticketsports.xlsx": "TicketSports",
    "clubinho.xlsx": "Clubinho",
    "ingresse.xlsx": "Ingresse",
    "visiteRJ.xlsx": "Visite RJ",
    "visiteSP.xlsx": "Visite SP",
    "shotgun.xlsx": "Shotgun",
}

print(f"{'Site':<20} {'Linhas':>8} {'C/data':>8} {'C/img':>8} {'C/preço':>10} {'C/end':>8}")
print("-" * 70)
for fname, name in files.items():
    path = f"output/data/{fname}"
    if not os.path.exists(path):
        print(f"{name:<20} ARQUIVO NÃO EXISTE")
        continue
    df = pd.read_excel(path)
    def cnt(col):
        if col not in df.columns:
            return 0
        s = df[col].astype(str).str.strip()
        return ((s != "") & (s != "nan") & (s != "0")).sum()
    com_data = cnt("dateEvents")
    com_img = cnt("image")
    com_preco = (pd.to_numeric(df.get("price", pd.Series()), errors="coerce") > 0).sum() if "price" in df else 0
    com_addr = cnt("address") if "address" in df.columns else cnt("local")
    print(f"{name:<20} {len(df):>8} {com_data:>8} {com_img:>8} {com_preco:>10} {com_addr:>8}")
