import base64
from datetime import date
from io import BytesIO
import barcode
from barcode.writer import ImageWriter
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
  """Mengambil 4 karakter/angka terakhir no bon dan mengonversi angka ke huruf."""
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
def ambil_data_penjualan(store_id: str, date_tx: str, user_id: str) -> dict | list:
  """Menarik data laporan penjualan per nomor bon dari server."""
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
      "Accept": "application/json, text/plain, */*",
      "App-Name": "CEXP-CLOUD",
      "Platform": "ANDROID",
      "x-api-key": API_KEY,
      "Api-Key": API_KEY,
  }
  response = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
  response.raise_for_status()
  return response.json()


# --- Form Input Parameter ---
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

if tarik_data or ("hasil_api" in st.session_state):
  if tarik_data:
    if not store_id or not user_id:
      st.warning("Kode Toko dan NIK wajib diisi.")
      st.stop()
    with st.spinner(f"Mengambil data toko {store_id} ({date_tx})..."):
      try:
        st.session_state["hasil_api"] = ambil_data_penjualan(
            store_id, date_tx, user_id
        )
        st.session_state["meta"] = (store_id, date_tx, user_id)
      except requests.exceptions.HTTPError as err:
        st.error(f"HTTP Error {err.response.status_code}: {err.response.text}")
        st.stop()
      except requests.exceptions.RequestException as err:
        st.error(f"Gagal terhubung ke server: {err}")
        st.stop()

  hasil = st.session_state["hasil_api"]
  meta_store, meta_date, meta_nik = st.session_state["meta"]

  # Ekstrak list transaksi dari respons JSON
  daftar_transaksi = []
  if isinstance(hasil, list):
    daftar_transaksi = hasil
  elif isinstance(hasil, dict):
    for key in ("data", "result", "records", "rows"):
      if isinstance(hasil.get(key), list):
        daftar_transaksi = hasil[key]
        break

  if not daftar_transaksi:
    st.info("Data transaksi tidak ditemukan untuk parameter tersebut.")
    with st.expander("Lihat Respons Mentah Server"):
      st.json(hasil)
    st.stop()

  # Filter pencarian cepat nomor bon / kode sandi
  filter_bon = st.text_input(
      "Cari No. Bon / Kode Sandi (opsional)",
      placeholder="Ketik 4 digit bon (misal: 3580) atau huruf (misal: DUIM)...",
  ).strip().upper()

  baris_html = ""
  jumlah_tampil = 0

  for idx, trx in enumerate(daftar_transaksi, start=1):
    no_bon = str(
        trx.get("no_bon")
        or trx.get("nomor_bon")
        or trx.get("receipt_no")
        or trx.get("bon")
        or ""
    ).strip()

    if not no_bon:
      continue

    kode_sandi = konversi_kode_bon(no_bon)

    if filter_bon and (
        filter_bon not in no_bon.upper() and filter_bon not in kode_sandi
    ):
      continue

    jumlah_tampil += 1
    b64_img = buat_barcode_base64(kode_sandi)
    kode_spasi = " ".join(kode_sandi)

    tx_val = trx.get("tx") or trx.get("jml_item") or trx.get("item") or "-"
    qty_val = trx.get("qty") or trx.get("total_qty") or "-"
    raw_price = (
        trx.get("lbl_price")
        or trx.get("total")
        or trx.get("grand_total")
        or trx.get("nilai")
        or 0
    )
    price_str = (
        f"{int(raw_price):,}"
        if isinstance(raw_price, (int, float))
        else str(raw_price)
    )

    baris_html += f"""
        <tr>
            <td>{idx}.</td>
            <td class="no-bon">{no_bon}</td>
            <td>{tx_val}</td>
            <td class="qty">{qty_val}</td>
            <td class="price">{price_str}</td>
            <td class="barcode-cell">
                <img src="data:image/png;base64,{b64_img}" alt="{kode_sandi}">
                <div class="kode-text">{kode_spasi}</div>
            </td>
        </tr>
        """

  # Latar putih dipaksa (!important) agar barcode tetap terbaca scanner walau HP mode gelap
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
            font-size: 20px;
            font-weight: 700;
            margin: 0 0 2px 0;
            color: #1f1f1f !important;
        }}
        .bon-sub {{
            font-size: 13px;
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
        <div class="bon-title">Daftar Nomor BON ({meta_store})</div>
        <div class="bon-sub">Tgl: {meta_date} | NIK: {meta_nik} • Total: {jumlah_tampil} bon</div>
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

  with st.expander("Cek Struktur JSON Asli (Jika ada kolom yang masih '-')"):
    st.json(daftar_transaksi[0])
