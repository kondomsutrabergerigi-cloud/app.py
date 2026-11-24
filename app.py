import base64
from datetime import date
from io import BytesIO
import re
import barcode
from barcode.writer import ImageWriter
from bs4 import BeautifulSoup
import requests
import streamlit as st

st.set_page_config(
    page_title="Reprint Nota - Barcode BON",
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
      "module_width": 0.42,
      "module_height": 11.0,
      "quiet_zone": 2.5,
      "write_text": False,
  }
  buffer = BytesIO()
  code128.write(buffer, options=opsi_writer)
  return base64.b64encode(buffer.getvalue()).decode("utf-8")


@st.cache_data(ttl=120, show_spinner=False)
def ambil_laporan_html(store_id: str, date_tx: str, user_id: str) -> dict:
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
  return {
      "status_code": response.status_code,
      "html": response.text,
  }


def parse_laporan_html(html_text: str) -> tuple[dict, list[dict], list[list[str]]]:
  """Mengekstrak metadata header dan baris transaksi dari HTML laporan."""
  soup = BeautifulSoup(html_text, "html.parser")
  info_header = {}
  daftar_transaksi = []
  semua_baris_mentah = []

  for table in soup.find_all("table"):
    teks_tabel = table.get_text(" ", strip=True)

    # 1. Ekstrak metadata header (Toko, Periode, Kd Kasir)
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

    # 2. Ekstrak tabel transaksi
    col_map = {}
    for tr in table.find_all("tr"):
      cells = tr.find_all(["th", "td"])
      if not cells:
        continue

      # Lewati baris summary/total yang memakai colspan
      if any(c.has_attr("colspan") for c in cells):
        continue

      row_texts = [c.get_text(" ", strip=True) for c in cells]
      row_lower = [t.lower() for t in row_texts]

      # Deteksi baris judul kolom (header tabel)
      is_header = bool(tr.find_all("th")) or any(
          any(k in cell for k in ("no. bon", "no bon", "nomor bon", "qty"))
          for cell in row_lower
      )
      if is_header:
        for idx, judul in enumerate(row_lower):
          if any(k in judul for k in ("bon", "struk", "receipt")):
            col_map["bon"] = idx
          elif any(k in judul for k in ("tx", "item", "plu", "jml")):
            col_map["tx"] = idx
          elif "qty" in judul or "kuantitas" in judul:
            col_map["qty"] = idx
          elif any(
              k in judul
              for k in ("nilai", "total", "harga", "price", "net", "amount")
          ):
            col_map["price"] = idx
        continue

      # Lewati baris total di bagian bawah tabel
      if any(
          t.startswith(("total", "grand total", "jumlah")) for t in row_lower if t
      ):
        continue

      if len(row_texts) < 2:
        continue

      semua_baris_mentah.append(row_texts)

      # Ambil nilai berdasarkan posisi kolom yang terdeteksi atau fallback urutan standar
      no_bon = ""
      if "bon" in col_map and col_map["bon"] < len(row_texts):
        no_bon = row_texts[col_map["bon"]]
      else:
        # Biasanya kolom 0 = nomor urut (1, 2, 3), kolom 1 = nomor bon
        if re.fullmatch(r"\d+\.?", row_texts[0]) and len(row_texts) >= 2:
          no_bon = row_texts[1]
        else:
          no_bon = row_texts[0]

      no_bon = no_bon.strip()
      if not no_bon or not any(ch.isdigit() for ch in no_bon):
        continue

      tx_val = (
          row_texts[col_map["tx"]]
          if "tx" in col_map and col_map["tx"] < len(row_texts)
          else "-"
      )
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

  return info_header, daftar_transaksi, semua_baris_mentah


# --- Antarmuka Streamlit ---
st.markdown("### 🧾 Reprint Nota & Barcode BON")

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
  if st.button("Refresh Cache", use_container_width=True):
    st.cache_data.clear()
    tarik_data = True

if tarik_data or ("hasil_html" in st.session_state):
  if tarik_data:
    if not store_id or not user_id:
      st.warning("Kode Toko dan NIK wajib diisi.")
      st.stop()
    with st.spinner(f"Mengambil data toko {store_id} ({date_tx})..."):
      try:
        st.session_state["hasil_html"] = ambil_laporan_html(
            store_id, date_tx, user_id
        )
        st.session_state["meta"] = (store_id, date_tx, user_id)
      except requests.exceptions.RequestException as err:
        st.error(f"Gagal terhubung ke server: {err}")
        st.stop()

  res = st.session_state["hasil_html"]
  meta_store, meta_date, meta_nik = st.session_state["meta"]
  html_mentah = res.get("html", "").strip()

  if not html_mentah:
    st.info(
        f"Tidak ada data transaksi untuk toko **{meta_store}**, NIK"
        f" **{meta_nik}**, tanggal **{meta_date}** (respons server kosong)."
    )
    st.stop()

  info_header, daftar_transaksi, semua_baris_mentah = parse_laporan_html(
      html_mentah
  )

  if not daftar_transaksi:
    st.warning("Halaman laporan diterima, tetapi baris nomor bon belum terbaca.")
    with st.expander("Lihat Baris & HTML Asli dari Server"):
      st.write(semua_baris_mentah)
      st.code(html_mentah[:3000], language="html")
    st.stop()

  filter_bon = st.text_input(
      "Cari No. Bon / Kode Sandi (opsional)",
      placeholder="Ketik 4 digit bon (misal: 3580) atau huruf (misal: DUIM)...",
  ).strip().upper()

  baris_html = ""
  jumlah_tampil = 0

  for idx, trx in enumerate(daftar_transaksi, start=1):
    no_bon = trx["no_bon"]
    kode_sandi = konversi_kode_bon(no_bon)

    if filter_bon and (
        filter_bon not in no_bon.upper() and filter_bon not in kode_sandi
    ):
      continue

    jumlah_tampil += 1
    b64_img = buat_barcode_base64(kode_sandi)
    kode_spasi = " ".join(kode_sandi)

    baris_html += f"""
        <tr>
            <td>{idx}.</td>
            <td class="no-bon">{no_bon}</td>
            <td>{trx['tx']}</td>
            <td class="qty">{trx['qty']}</td>
            <td class="price">{trx['price']}</td>
            <td class="barcode-cell">
                <img src="data:image/png;base64,{b64_img}" alt="{kode_sandi}">
                <div class="kode-text">{kode_spasi}</div>
            </td>
        </tr>
        """

  nama_kasir = info_header.get("Kd Kasir", meta_nik)
  nama_toko = info_header.get("Toko", meta_store)

  tabel_html = f"""
    <style>
        .bon-wrapper {{
            background-color: #ffffff !important;
            color: #222222 !important;
            padding: 14px;
            border-radius: 10px;
            border: 1px solid #e0e0e0;
            overflow-x: auto;
        }}
        .bon-title {{
            font-size: 19px;
            font-weight: 700;
            margin: 0 0 2px 0;
            color: #1f1f1f !important;
        }}
        .bon-sub {{
            font-size: 12.5px;
            font-weight: 700;
            color: #d4a017 !important;
            margin-bottom: 12px;
        }}
        .bon-table {{
            width: 100%;
            border-collapse: collapse;
            font-family: Arial, sans-serif;
            font-size: 13px;
            background-color: #ffffff !important;
        }}
        .bon-table th {{
            background-color: #e9ecef !important;
            color: #444444 !important;
            padding: 8px 6px;
            text-align: center;
            border-bottom: 1px solid #cccccc;
            white-space: nowrap;
        }}
        .bon-table td {{
            padding: 10px 6px;
            text-align: center;
            border-bottom: 1px solid #eeeeee;
            vertical-align: middle;
            color: #222222 !important;
            background-color: #ffffff !important;
        }}
        .no-bon {{ color: #2b7de9 !important; font-weight: 700; }}
        .qty {{ color: #c0392b !important; font-weight: 700; }}
        .price {{ color: #27ae60 !important; font-weight: 700; white-space: nowrap; }}
        .barcode-cell {{
            background-color: #ffffff !important;
            padding: 6px 8px !important;
        }}
        .barcode-cell img {{
            height: 44px;
            max-width: 165px;
            display: block;
            margin: 0 auto;
        }}
        .kode-text {{
            font-family: monospace;
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 2px;
            color: #444444 !important;
            margin-top: 3px;
        }}
    </style>
    <div class="bon-wrapper">
        <div class="bon-title">Daftar Nomor BON ({nama_toko})</div>
        <div class="bon-sub">Tgl: {meta_date} | Kasir: {nama_kasir} • Total: {jumlah_tampil} bon</div>
        <table class="bon-table">
            <thead>
                <tr>
                    <th>No</th>
                    <th>No.Bon</th>
                    <th>Tx</th>
                    <th>QTY</th>
                    <th>Lbl Price</th>
                    <th>Barcode View</th>
                </tr>
            </thead>
            <tbody>
                {baris_html}
            </tbody>
        </table>
    </div>
    """

  st.markdown(tabel_html, unsafe_allow_html=True)

  with st.expander("Cek Data Mentah Tabel (Jika urutan kolom perlu disesuaikan)"):
    st.write(semua_baris_mentah[:5])
