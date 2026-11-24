import base64
from datetime import date
from io import BytesIO
import re
import barcode
from barcode.writer import ImageWriter
from bs4 import BeautifulSoup
import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Daftar Nomor BON - Reprint Struk",
    page_icon="🧾",
    layout="centered",
)

BASE_URL = (
    "https://app.alfastore.co.id/prd/api/rpt/laporan/"
    "laporan_penjualan_per_nomor_bon"
)

DEFAULT_API_KEY = "iVOZX9MLmKrj1L8R23uF1aryMR1vGMXG"
try:
  API_KEY = st.secrets.get("ALFA_API_KEY", DEFAULT_API_KEY)
except Exception:
  API_KEY = DEFAULT_API_KEY

# Rumus konversi: M=0, O=1, Y=2, D=3, T=4, U=5, H=6, C=7, I=8, K=9
MAP_SANDI = {
    "0": "M",
    "1": "O",
    "2": "Y",
    "3": "D",
    "4": "T",
    "5": "U",
    "6": "H",
    "7": "C",
    "8": "I",
    "9": "K",
}


def konversi_kode_bon(no_bon: str) -> str:
  """Mengambil 4 angka/huruf terakhir no bon dan mengonversinya ke kode huruf."""
  empat_terakhir = str(no_bon).strip()[-4:].upper()
  return "".join(MAP_SANDI.get(karakter, karakter) for karakter in empat_terakhir)


@st.cache_data(show_spinner=False)
def buat_barcode_base64(kode_sandi: str) -> str:
  """Menghasilkan gambar barcode Code 128 dalam format Base64 PNG."""
  code128 = barcode.get("code128", kode_sandi, writer=ImageWriter())
  opsi_writer = {
      "module_width": 0.45,
      "module_height": 11.5,
      "quiet_zone": 2.0,
      "write_text": False,
  }
  buffer = BytesIO()
  code128.write(buffer, options=opsi_writer)
  return base64.b64encode(buffer.getvalue()).decode("utf-8")


@st.cache_data(ttl=120, show_spinner=False)
def ambil_laporan_html(store_id: str, date_tx: str, user_id: str) -> str:
  """Mengambil HTML laporan penjualan per nomor bon dari server."""
  params = {
      "storeId": store_id,
      "dateTx": date_tx,
      "userId": user_id,
  }
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Linux; Android 11; Mobile) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
      ),
      "Accept": "application/json, text/plain, text/html, */*",
      "App-Name": "CEXP-CLOUD",
      "Platform": "ANDROID",
      "x-api-key": API_KEY,
      "Api-Key": API_KEY,
  }
  response = requests.get(BASE_URL, params=params, headers=headers, timeout=20)
  response.raise_for_status()
  return response.text


def parse_laporan_html(html_text: str) -> tuple[dict, list[dict]]:
  """Mengekstrak metadata header dan baris transaksi dari HTML laporan."""
  soup = BeautifulSoup(html_text, "html.parser")
  info_header = {}
  daftar_transaksi = []

  for table in soup.find_all("table"):
    teks_tabel = table.get_text(" ", strip=True)

    # Ekstrak metadata header (Toko, Periode, Kd Kasir)
    if "Kd Kasir" in teks_tabel or (
        "Toko" in teks_tabel and "Periode" in teks_tabel
    ):
      for tr in table.find_all("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(tds) >= 2:
          kunci = tds[0].strip()
          nilai = tds[1].lstrip(": ").strip()
          if kunci:
            info_header[kunci] = nilai
      continue

    # Ekstrak tabel transaksi
    col_map = {}
    for tr in table.find_all("tr"):
      cells = tr.find_all(["th", "td"])
      if not cells or any(c.has_attr("colspan") for c in cells):
        continue

      row_texts = [c.get_text(" ", strip=True) for c in cells]
      row_lower = [t.lower() for t in row_texts]

      is_header = bool(tr.find_all("th")) or any(
          any(k in cell for k in ("no. bon", "no bon", "nomor bon", "qty"))
          for cell in row_lower
      )
      if is_header:
        for idx, judul in enumerate(row_lower):
          if any(k in judul for k in ("bon", "struk", "receipt")):
            col_map["bon"] = idx
          elif any(
              k in judul
              for k in ("tx", "item", "plu", "jml", "shift", "pos", "jenis")
          ):
            col_map["tx"] = idx
          elif "qty" in judul or "kuantitas" in judul:
            col_map["qty"] = idx
          elif any(
              k in judul
              for k in ("nilai", "total", "harga", "price", "net", "amount")
          ):
            col_map["price"] = idx
        continue

      if any(
          t.startswith(("total", "grand total", "jumlah")) for t in row_lower if t
      ):
        continue

      if len(row_texts) < 2:
        continue

      # Tentukan posisi kolom No.Bon
      if "bon" in col_map and col_map["bon"] < len(row_texts):
        idx_bon = col_map["bon"]
      elif re.fullmatch(r"\d+\.?", row_texts[0]) and len(row_texts) >= 2:
        idx_bon = 1
      else:
        idx_bon = 0

      no_bon = row_texts[idx_bon].strip()
      if not no_bon or not any(ch.isdigit() for ch in no_bon):
        continue

      # Ambil nilai Tx (kolom setelah No.Bon jika tidak terdeteksi dari header)
      if "tx" in col_map and col_map["tx"] < len(row_texts):
        tx_val = row_texts[col_map["tx"]]
      elif len(row_texts) >= 5 and (idx_bon + 1) < (len(row_texts) - 2):
        tx_val = row_texts[idx_bon + 1]
      else:
        tx_val = "-"

      qty_val = (
          row_texts[col_map["qty"]]
          if "qty" in col_map and col_map["qty"] < len(row_texts)
          else (row_texts[-2] if len(row_texts) >= 4 else "-")
      )
      price_val = (
          row_texts[col_map["price"]]
          if "price" in col_map and col_map["price"] < len(row_texts)
          else (row_texts[-1] if len(row_texts) >= 3 else "-")
      )

      daftar_transaksi.append({
          "no_bon": no_bon,
          "tx": tx_val or "-",
          "qty": qty_val or "-",
          "price": price_val or "-",
      })

  return info_header, daftar_transaksi


# --- Input Parameter ---
col1, col2, col3 = st.columns([1, 1.2, 1.2])
with col1:
  store_id = (
      st.text_input("Kode Toko", value="M1Z7", max_chars=10).strip().upper()
  )
with col2:
  user_id = st.text_input("NIK Kasir", value="20010907", max_chars=20).strip()
with col3:
  tgl_pilih = st.date_input("Tanggal", value=date.today(), format="DD-MM-YYYY")
  date_tx = tgl_pilih.strftime("%d-%m-%Y")

col_btn1, col_btn2 = st.columns([1, 1])
with col_btn1:
  tarik_data = st.button("Tarik Data BON", type="primary", use_container_width=True)
with col_btn2:
  if st.button("Refresh Data", use_container_width=True):
    st.cache_data.clear()
    tarik_data = True

if tarik_data or ("html_laporan" in st.session_state):
  if tarik_data:
    if not store_id or not user_id:
      st.warning("Kode Toko dan NIK wajib diisi.")
      st.stop()
    with st.spinner(f"Mengambil data {store_id} ({date_tx})..."):
      try:
        st.session_state["html_laporan"] = ambil_laporan_html(
            store_id, date_tx, user_id
        )
        st.session_state["meta"] = (store_id, date_tx, user_id)
      except requests.exceptions.RequestException as err:
        st.error(f"Gagal terhubung ke server: {err}")
        st.stop()

  html_mentah = st.session_state["html_laporan"].strip()
  meta_store, meta_date, meta_nik = st.session_state["meta"]

  if not html_mentah:
    st.info(
        f"Data kosong untuk toko **{meta_store}**, NIK **{meta_nik}**, tanggal"
        f" **{meta_date}**."
    )
    st.stop()

  _, daftar_transaksi = parse_laporan_html(html_mentah)

  if not daftar_transaksi:
    st.warning("Tidak ditemukan baris nomor bon pada laporan tanggal tersebut.")
    st.stop()

  filter_bon = st.text_input(
      "Cari No. Bon / Kode Huruf",
      placeholder="Contoh: 3580 atau DUIM...",
  ).strip().upper()

  baris_list = []
  for idx, trx in enumerate(daftar_transaksi, start=1):
    no_bon = trx["no_bon"]
    kode_sandi = konversi_kode_bon(no_bon)

    if filter_bon and (
        filter_bon not in no_bon.upper() and filter_bon not in kode_sandi
    ):
      continue

    b64_img = buat_barcode_base64(kode_sandi)
    kode_spasi = " ".join(kode_sandi)

    baris_list.append(
        f"<tr>"
        f"<td class='col-no'>{idx}.</td>"
        f"<td class='col-bon'>{no_bon}</td>"
        f"<td class='col-tx'>{trx['tx']}</td>"
        f"<td class='col-qty'>{trx['qty']}</td>"
        f"<td class='col-price'>{trx['price']}</td>"
        f"<td class='col-barcode'>"
        f"<img src='data:image/png;base64,{b64_img}' alt='{kode_sandi}'>"
        f"<div class='kode-text'>{kode_spasi}</div>"
        f"</td>"
        f"</tr>"
    )

  jumlah_tampil = len(baris_list)
  baris_html = "".join(baris_list)

  halaman_html = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    background-color: #ffffff;
    color: #222222;
    padding: 12px 6px;
  }}
  .header-box {{
    padding: 0 8px 12px 8px;
  }}
  .title {{
    font-size: 22px;
    font-weight: 700;
    color: #262626;
    margin-bottom: 4px;
  }}
  .subtitle {{
    font-size: 13.5px;
    font-weight: 700;
    color: #dfb027;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background-color: #ffffff;
  }}
  thead th {{
    background-color: #e6e7e9;
    color: #555555;
    font-size: 13px;
    font-weight: 700;
    padding: 10px 4px;
    text-align: center;
    white-space: nowrap;
  }}
  tbody td {{
    padding: 14px 4px;
    text-align: center;
    vertical-align: middle;
    border-bottom: 1px solid #eeeeee;
    font-size: 13.5px;
  }}
  .col-no {{
    color: #444444;
    width: 8%;
  }}
  .col-bon {{
    color: #3685d7;
    font-weight: 700;
    width: 15%;
  }}
  .col-tx {{
    color: #444444;
    width: 10%;
  }}
  .col-qty {{
    color: #b83227;
    font-weight: 700;
    width: 11%;
  }}
  .col-price {{
    color: #3a9d5d;
    font-weight: 700;
    white-space: nowrap;
    width: 21%;
  }}
  .col-barcode {{
    width: 35%;
    padding: 10px 6px;
  }}
  .col-barcode img {{
    height: 44px;
    width: auto;
    max-width: 165px;
    display: block;
    margin: 0 auto;
  }}
  .kode-text {{
    font-family: "Courier
