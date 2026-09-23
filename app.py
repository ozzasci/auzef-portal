import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
import io
import json
import random
import urllib.request
import csv
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from pypdf import PdfReader

app = Flask(__name__)
app.secret_key = "auzef_portal_tam_surum_2026_gizli_anahtar"

# Supabase PostgreSQL Bağlantı URI'si
DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://postgres.luvrwqfypquitdyqqpao:1O2g3z1o2g3z@aws-0-eu-central-1.pooler.supabase.com:6543/postgres")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "kitaplar")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

GUZ_DERSLERI = [
    "20. Yüzyıl Türkiye’sinde Gayrimüslimler ve Kurumları",
    "Osmanlı Diplomasi Tarihi",
    "Osmanlı İktisat Tarihi",
    "Osmanlı Tarihi (1789-1908)",
    "Osmanlı Teşkilatı ve Kültür Tarihi",
    "Sömürgecilik Tarihi"
]

UNITE_BASLIKLARI = {i: f"{i}. Ünite" for i in range(1, 15)}

def veritabani_baglan():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def veritabani_hazirla():
    conn = veritabani_baglan()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id SERIAL PRIMARY KEY,
            kullanici_adi TEXT UNIQUE,
            ad_soyad TEXT,
            sifre_hash TEXT,
            kayit_tarihi TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sorular (
            id SERIAL PRIMARY KEY,
            ders_adi TEXT,
            soru_metni TEXT,
            secenek_a TEXT,
            secenek_b TEXT,
            secenek_c TEXT,
            secenek_d TEXT,
            secenek_e TEXT,
            dogru_cevap TEXT,
            aciklama TEXT,
            yildizli INTEGER DEFAULT 0,
            kullanici_notu TEXT DEFAULT '',
            unite_no INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sinav_gecmisi (
            id SERIAL PRIMARY KEY,
            tarih TEXT,
            ders_adi TEXT,
            dogru INTEGER,
            yanlis INTEGER,
            bos INTEGER,
            net REAL,
            puan REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS performans (
            soru_id INTEGER PRIMARY KEY,
            dogru_sayisi INTEGER DEFAULT 0,
            yanlis_sayisi INTEGER DEFAULT 0,
            son_durum TEXT DEFAULT ''
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_kaynaklari (
            id SERIAL PRIMARY KEY,
            ders_adi TEXT,
            unite_no INTEGER,
            kaynak_turu TEXT,
            dosya_yolu TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_takip (
            id SERIAL PRIMARY KEY,
            ders_adi TEXT,
            unite_no INTEGER,
            okundu INTEGER DEFAULT 0,
            izlendi INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ders_videolari (
            id SERIAL PRIMARY KEY,
            ders_adi TEXT,
            unite_no INTEGER,
            video_url TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_ozetleri (
            id SERIAL PRIMARY KEY,
            ders_adi TEXT,
            unite_no INTEGER,
            madde TEXT
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

veritabani_hazirla()

def giris_zorunlu(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "kullanici_id" not in session:
            return redirect(url_for("giris_yap"))
        return f(*args, **kwargs)
    return wrap

def sinav_oturumunu_temizle():
    anahtarlar = [
        "soru_idleri", "sorular", "aktif_ders", "sinav_modu", "mevcut_indeks", 
        "cevaplar", "dogru", "yanlis", "bos", "toplam_sure_saniye"
    ]
    for key in anahtarlar:
        session.pop(key, None)

def drive_id_yakala(link):
    if not link:
        return None
    dosya_id = re.search(r'/d/([a-zA-Z0-9_-]+)', link)
    if dosya_id:
        return dosya_id.group(1)
    id_param = re.search(r'id=([a-zA-Z0-9_-]+)', link)
    if id_param:
        return id_param.group(1)
    return None

def drive_link_donustur(link):
    dosya_id = drive_id_yakala(link)
    if dosya_id:
        return f"https://drive.google.com/file/d/{dosya_id}/preview"
    return link

@app.route("/giris", methods=["GET", "POST"])
def giris_yap():
    if "kullanici_id" in session:
        return redirect(url_for("ana_sayfa"))

    if request.method == "POST":
        kullanici_adi = request.form.get("kullanici_adi", "").strip().lower()
        sifre = request.form.get("sifre", "")

        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = %s", (kullanici_adi,))
        kullanici = cursor.fetchone()
        cursor.close()
        conn.close()

        if kullanici and check_password_hash(kullanici["sifre_hash"], sifre):
            session["kullanici_id"] = kullanici["id"]
            session["kullanici_adi"] = kullanici["kullanici_adi"]
            session["ad_soyad"] = kullanici["ad_soyad"]
            return redirect(url_for("ana_sayfa"))
        else:
            session["bildirim"] = {"tur": "danger", "metin": "Kullanıcı adı veya şifre hatalı."}
            return redirect(url_for("giris_yap"))

    mesaj = session.pop("bildirim", None)
    return render_template("index.html", durum="giris", bildirim=mesaj)

@app.route("/kayit", methods=["GET", "POST"])
def kayit_ol():
    if "kullanici_id" in session:
        return redirect(url_for("ana_sayfa"))

    if request.method == "POST":
        kullanici_adi = request.form.get("kullanici_adi", "").strip().lower()
        ad_soyad = request.form.get("ad_soyad", "").strip()
        sifre = request.form.get("sifre", "")

        if len(kullanici_adi) < 3 or len(sifre) < 4:
            session["bildirim"] = {"tur": "danger", "metin": "Kullanıcı adı en az 3, şifre en az 4 karakter olmalıdır."}
            return redirect(url_for("kayit_ol"))

        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = %s", (kullanici_adi,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            session["bildirim"] = {"tur": "warning", "metin": "Bu kullanıcı adı zaten alınmış."}
            return redirect(url_for("kayit_ol"))

        sifre_hash = generate_password_hash(sifre)
        simdi = datetime.now().strftime("%d.%m.%Y %H:%M")
        cursor.execute("""
            INSERT INTO kullanicilar (kullanici_adi, ad_soyad, sifre_hash, kayit_tarihi)
            VALUES (%s, %s, %s, %s)
        """, (kullanici_adi, ad_soyad, sifre_hash, simdi))
        conn.commit()
        cursor.close()
        conn.close()

        session["bildirim"] = {"tur": "success", "metin": "Kayıt başarılı! Şimdi giriş yapabilirsiniz."}
        return redirect(url_for("giris_yap"))

    mesaj = session.pop("bildirim", None)
    return render_template("index.html", durum="kayit", bildirim=mesaj)

@app.route("/cikis")
def cikis_yap():
    session.clear()
    return redirect(url_for("giris_yap"))

@app.route("/")
@giris_zorunlu
def ana_sayfa():
    conn = veritabani_baglan()
    cursor = conn.cursor()
    
    cursor.execute("SELECT ders_adi, COUNT(*) as soru_sayisi FROM sorular GROUP BY ders_adi")
    veritabanindaki_dersler = {row["ders_adi"]: row["soru_sayisi"] for row in cursor.fetchall()}
    
    dersler = []
    for d in GUZ_DERSLERI:
        adet = veritabanindaki_dersler.get(d, 0)
        dersler.append({"ders_adi": d, "soru_sayisi": adet})

    cursor.execute("SELECT COUNT(*) FROM sorular")
    toplam_soru = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) FROM sorular WHERE yildizli = 1")
    yildizli_soru_sayisi = cursor.fetchone()["count"]

    cursor.execute("""
        SELECT COUNT(*) FROM sorular s
        JOIN performans p ON s.id = p.soru_id
        WHERE p.son_durum = 'YANLIS'
    """)
    hatali_soru_sayisi = cursor.fetchone()["count"]
    cursor.close()
    conn.close()

    mesaj = session.pop("bildirim", None)
    return render_template("index.html", 
                           durum="baslangic", 
                           dersler=dersler, 
                           toplam_soru=toplam_soru, 
                           yildizli_sayisi=yildizli_soru_sayisi,
                           hatali_sayisi=hatali_soru_sayisi,
                           bildirim=mesaj)

@app.route("/icerik-merkezi")
@giris_zorunlu
def icerik_merkezi():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    return render_template("index.html", durum="icerik_merkezi", aktif_ders=secilen_ders, dersler=GUZ_DERSLERI)

@app.route("/kaydet-drive-link", methods=["POST"])
@giris_zorunlu
def kaydet_drive_link():
    ders = request.form.get("ders_adi", "").strip()
    unite_no = int(request.form.get("unite_no", 1))
    raw_link = request.form.get("drive_url", "").strip()

    if not raw_link:
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir Google Drive bağlantısı yapıştırın."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    preview_link = drive_link_donustur(raw_link)

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO unite_kaynaklari (ders_adi, unite_no, kaynak_turu, dosya_yolu) VALUES (%s, %s, 'drive', %s)", 
                   (ders, unite_no, preview_link))
    conn.commit()
    cursor.close()
    conn.close()

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' - Ünite {unite_no} için Google Drive PDF kaynağı bağlandı!"}
    return redirect(url_for("ders_calis", ders=ders, unite=unite_no))

@app.route("/yukle-pdf-dosya", methods=["POST"])
@giris_zorunlu
def yukle_pdf_dosya():
    ders = request.form.get("ders_adi", "").strip()
    unite_no = int(request.form.get("unite_no", 1))
    dosya = request.files.get("pdf_dosya")

    if not dosya or not dosya.filename.lower().endswith(".pdf"):
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir .pdf dosyası seçin."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    dosya_adi = f"{abs(hash(ders))}_{unite_no}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    hedef_yol = os.path.join(UPLOAD_FOLDER, dosya_adi)
    dosya.save(hedef_yol)

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO unite_kaynaklari (ders_adi, unite_no, kaynak_turu, dosya_yolu) VALUES (%s, %s, 'yerel', %s)", 
                   (ders, unite_no, f"/static/kitaplar/{dosya_adi}"))
    conn.commit()
    cursor.close()
    conn.close()

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' dersinin {unite_no}. Ünite PDF'i başarıyla kaydedildi!"}
    return redirect(url_for("ders_calis", ders=ders, unite=unite_no))

def klavuz_pdf_ayikla(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    tam_metin = ""
    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            tam_metin += txt + "\n"

    satirlar = tam_metin.splitlines()
    unite_verileri = {i: [] for i in range(1, 15)}
    mevcut_unite = 1
    tampon = ""

    for satir in satirlar:
        s = satir.strip()
        if not s:
            continue
        s_upper = s.upper()
        if any(kelime in s_upper for kelime in ["FAITH S. AKADEMİ", "TELEGRAM", "AUZEF TARİH", "SINIF KANALI"]):
            continue
        if re.match(r'^\s*20\.\s*(YY|YÜZYIL)', s, re.IGNORECASE) or s.endswith("KILAVUZU") or s.isdigit():
            continue

        baslik_m = re.match(r'^([1-9]|1[0-4])\.\s+[A-ZÇĞİIÖŞÜ\s\',-]{3,}', s)
        if baslik_m:
            if tampon and len(tampon) >= 15:
                unite_verileri[mevcut_unite].append(tampon)
                tampon = ""
            mevcut_unite = int(baslik_m.group(1))
            continue

        if tampon:
            tampon += " " + s
        else:
            tampon = s

        if tampon.endswith((".", ":", "!", "?", "idi", "denirdi", "denilirdi", "olmuştur", "edilmiştir")):
            if len(tampon) >= 15:
                unite_verileri[mevcut_unite].append(tampon)
            tampon = ""

    if tampon and len(tampon) >= 15:
        unite_verileri[mevcut_unite].append(tampon)

    return {k: v for k, v in unite_verileri.items() if v}

@app.route("/otomatik-klavuz-isle", methods=["POST"])
@giris_zorunlu
def otomatik_klavuz_isle():
    ders = request.form.get("ders_adi", "").strip()
    drive_link = request.form.get("drive_url", "").strip()
    yuklenen_dosya = request.files.get("klavuz_dosya")

    pdf_bytes = None
    klavuz_yolu = ""

    if yuklenen_dosya and yuklenen_dosya.filename != "" and yuklenen_dosya.filename.lower().endswith(".pdf"):
        try:
            pdf_bytes = yuklenen_dosya.read()
            dosya_adi = f"klavuz_{abs(hash(ders))}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
            hedef_yol = os.path.join(UPLOAD_FOLDER, dosya_adi)
            with open(hedef_yol, "wb") as f:
                f.write(pdf_bytes)
            klavuz_yolu = f"/static/kitaplar/{dosya_adi}"
        except Exception as e:
            session["bildirim"] = {"tur": "danger", "metin": f"Dosya okunamadı: {str(e)}"}
            return redirect(url_for("icerik_merkezi", ders=ders))

    elif drive_link:
        dosya_id = drive_id_yakala(drive_link)
        if not dosya_id:
            session["bildirim"] = {"tur": "danger", "metin": "Geçersiz Google Drive bağlantısı."}
            return redirect(url_for("icerik_merkezi", ders=ders))

        indirme_url = f"https://drive.google.com/uc?export=download&id={dosya_id}"
        try:
            req = urllib.request.Request(indirme_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=20) as response:
                pdf_bytes = response.read()
            klavuz_yolu = drive_link_donustur(drive_link)
        except Exception as e:
            session["bildirim"] = {"tur": "danger", "metin": f"Drive dosya çekme hatası: {str(e)}."}
            return redirect(url_for("icerik_merkezi", ders=ders))
    else:
        session["bildirim"] = {"tur": "warning", "metin": "Lütfen cihazdan bir PDF dosyası seçin veya geçerli bir bağlantı girin."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    try:
        ayiklanan = klavuz_pdf_ayikla(pdf_bytes)
        toplam_madde = sum(len(maddeler) for maddeler in ayiklanan.values())

        if toplam_madde == 0:
            session["bildirim"] = {"tur": "danger", "metin": "PDF okundu ancak içinde kılavuz formatına uygun ünite ve bilgi satırları bulunamadı."}
            return redirect(url_for("icerik_merkezi", ders=ders))

        conn = veritabani_baglan()
        cursor = conn.cursor()
        for u_no, maddeler in ayiklanan.items():
            for m in maddeler:
                cursor.execute("INSERT INTO unite_ozetleri (ders_adi, unite_no, madde) VALUES (%s, %s, %s)", (ders, u_no, m))

        if klavuz_yolu:
            cursor.execute("DELETE FROM unite_kaynaklari WHERE TRIM(ders_adi) LIKE %s AND kaynak_turu = 'klavuz_pdf'", (f"%{ders}%",))
            cursor.execute("""
                INSERT INTO unite_kaynaklari (ders_adi, unite_no, kaynak_turu, dosya_yolu)
                VALUES (%s, 0, 'klavuz_pdf', %s)
            """, (ders, klavuz_yolu))

        conn.commit()
        cursor.close()
        conn.close()

        session["bildirim"] = {"tur": "success", "metin": f"✅ İşlem Başarılı! {len(ayiklanan)} üniteden toplam {toplam_madde} hap bilgi eklendi ve Kılavuz PDF'i bağlandı."}
        return redirect(url_for("ders_calis", ders=ders, unite=1))

    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"Ayrıştırma hatası oluştu: {str(e)}"}
        return redirect(url_for("icerik_merkezi", ders=ders))

def auzef_harfsiz_ve_harfli_soru_ayikla(metin, unite_no=1):
    temiz = re.sub(r'about:blank\s*\d*/?\d*', '', metin)
    temiz = re.sub(r'\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{1,2}', '', temiz)
    temiz = re.sub(r'Ders:\s*.*?(?:\n|\|)', '', temiz, flags=re.IGNORECASE)
    temiz = re.sub(r'Ünite:\s*.*?\n', '', temiz, flags=re.IGNORECASE)

    bloklar = re.split(r'(?:^|\n)\s*Soru\s*(\d{1,2})\s*:\s*', temiz, flags=re.IGNORECASE)
    sorular = []

    if len(bloklar) > 1:
        for i in range(1, len(bloklar), 2):
            icerik = bloklar[i+1].strip()
            cevap_match = re.search(r'\n\s*Cevap\s*:\s*(.*)', icerik, flags=re.IGNORECASE)
            if not cevap_match:
                continue

            dogru_cevap_metni = cevap_match.group(1).strip()
            govde = icerik[:cevap_match.start()].strip()

            satirlar = [s.strip() for s in govde.splitlines() if s.strip()]
            if len(satirlar) < 6:
                continue

            sec_e = satirlar[-1]
            sec_d = satirlar[-2]
            sec_c = satirlar[-3]
            sec_b = satirlar[-4]
            sec_a = satirlar[-5]
            soru_kok = " ".join(satirlar[:-5]).strip()

            dogru_harf = "A"
            c_norm = dogru_cevap_metni.replace("Â", "A").replace("â", "a").strip().lower()

            for harf, val in [("A", sec_a), ("B", sec_b), ("C", sec_c), ("D", sec_d), ("E", sec_e)]:
                v_norm = val.replace("Â", "A").replace("â", "a").strip().lower()
                if v_norm == c_norm or v_norm in c_norm or c_norm in v_norm:
                    dogru_harf = harf
                    break

            sorular.append({
                "unite_no": unite_no,
                "metin": soru_kok,
                "a": sec_a,
                "b": sec_b,
                "c": sec_c,
                "d": sec_d,
                "e": sec_e,
                "dogru_cevap": dogru_harf,
                "aciklama": f"Doğru Yanıt: {dogru_cevap_metni}"
            })
    return sorular

@app.route("/yukle-unite-sorulari", methods=["POST"])
@giris_zorunlu
def yukle_unite_sorulari():
    ders = request.form.get("ders_adi", "").strip()
    unite_no = int(request.form.get("unite_no", 1))
    dosya = request.files.get("soru_dosyasi")
    drive_link = request.form.get("drive_url", "").strip()

    pdf_bytes = None

    if dosya and dosya.filename != "" and dosya.filename.lower().endswith(".pdf"):
        try:
            pdf_bytes = dosya.read()
        except Exception as e:
            session["bildirim"] = {"tur": "danger", "metin": f"Dosya okunamadı: {str(e)}"}
            return redirect(url_for("icerik_merkezi", ders=ders))

    elif drive_link:
        dosya_id = drive_id_yakala(drive_link)
        if not dosya_id:
            session["bildirim"] = {"tur": "danger", "metin": "Geçersiz Google Drive bağlantısı."}
            return redirect(url_for("icerik_merkezi", ders=ders))

        indirme_url = f"https://drive.google.com/uc?export=download&id={dosya_id}"
        try:
            req = urllib.request.Request(indirme_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=20) as response:
                pdf_bytes = response.read()
        except Exception as e:
            session["bildirim"] = {"tur": "danger", "metin": f"Drive dosya çekme hatası: {str(e)}"}
            return redirect(url_for("icerik_merkezi", ders=ders))
    else:
        session["bildirim"] = {"tur": "warning", "metin": "Lütfen cihazdan bir PDF seçin veya geçerli bir Google Drive bağlantısı girin."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    metin = ""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            t = page.extract_text()
            if t:
                metin += t + "\n"
    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"PDF metinleri okunamadı: {str(e)}"}
        return redirect(url_for("icerik_merkezi", ders=ders))

    sorular = auzef_harfsiz_ve_harfli_soru_ayikla(metin, unite_no)

    if not sorular:
        session["bildirim"] = {"tur": "warning", "metin": f"PDF okundu ancak {unite_no}. ünite formatına uygun soru algılanamadı."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    conn = veritabani_baglan()
    cursor = conn.cursor()
    
    for s in sorular:
        cursor.execute("""
            INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, '', %s)
        """, (ders, s["metin"], s["a"], s["b"], s["c"], s["d"], s["e"], s["dogru_cevap"], s["aciklama"], unite_no))

    conn.commit()
    cursor.close()
    conn.close()

    session["bildirim"] = {"tur": "success", "metin": f"🎉 Tebrikler! '{ders}' dersinin {unite_no}. ünitesine ait {len(sorular)} soru bulut veritabanına eklendi."}
    return redirect(url_for("unite_pekistirme_listesi", ders=ders))

@app.route("/ders-calis")
@giris_zorunlu
def ders_calis():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    secilen_unite = int(request.args.get("unite", 1))

    conn = veritabani_baglan()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT kaynak_turu, dosya_yolu FROM unite_kaynaklari 
        WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s AND kaynak_turu != 'klavuz_pdf'
        ORDER BY id DESC LIMIT 1
    """, (f"%{secilen_ders}%", secilen_unite))
    row_kaynak = cursor.fetchone()
    
    pdf_url = row_kaynak["dosya_yolu"] if row_kaynak else ""
    kaynak_turu = row_kaynak["kaynak_turu"] if row_kaynak else ""

    cursor.execute("""
        SELECT dosya_yolu FROM unite_kaynaklari 
        WHERE TRIM(ders_adi) LIKE %s AND kaynak_turu = 'klavuz_pdf'
        ORDER BY id DESC LIMIT 1
    """, (f"%{secilen_ders}%",))
    row_klavuz = cursor.fetchone()
    klavuz_pdf_url = row_klavuz["dosya_yolu"] if row_klavuz else ""

    cursor.execute("""
        SELECT video_url FROM ders_videolari 
        WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s
        ORDER BY id DESC LIMIT 1
    """, (f"%{secilen_ders}%", secilen_unite))
    row_video = cursor.fetchone()
    video_url = row_video["video_url"] if row_video else ""

    cursor.execute("""
        SELECT unite_no, okundu, izlendi FROM unite_takip 
        WHERE TRIM(ders_adi) LIKE %s
    """, (f"%{secilen_ders}%",))
    takip_verileri = {r["unite_no"]: {"okundu": r["okundu"], "izlendi": r["izlendi"]} for r in cursor.fetchall()}

    cursor.execute("""
        SELECT madde FROM unite_ozetleri 
        WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s
    """, (f"%{secilen_ders}%", secilen_unite))
    ozet_maddeleri = [r["madde"] for r in cursor.fetchall()]

    cursor.close()
    conn.close()

    embed_url = ""
    is_direct_video = False
    
    if video_url:
        if video_url.lower().endswith(('.mp4', '.webm', '.ogg', '.mov')):
            is_direct_video = True
            embed_url = video_url
        elif "watch?v=" in video_url:
            embed_url = video_url.replace("watch?v=", "embed/")
        elif "youtu.be/" in video_url:
            embed_url = video_url.replace("youtu.be/", "www.youtube.com/embed/")
        else:
            embed_url = video_url

    return render_template("index.html", 
                           durum="ogrenme_modu", 
                           aktif_ders=secilen_ders, 
                           aktif_unite=secilen_unite, 
                           pdf_url=pdf_url, 
                           klavuz_pdf_url=klavuz_pdf_url,
                           kaynak_turu=kaynak_turu, 
                           video_url=video_url, 
                           embed_url=embed_url, 
                           is_direct_video=is_direct_video,
                           takip=takip_verileri, 
                           ozetler=ozet_maddeleri, 
                           unite_baslik=f"{secilen_unite}. Ünite", 
                           dersler=GUZ_DERSLERI)

@app.route("/hafiza-kartlari")
@giris_zorunlu
def hafiza_kartlari():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    secilen_unite = int(request.args.get("unite", 1))

    kartlar = []
    try:
        conn = veritabani_baglan()
        cursor = conn.cursor()
        
        # Tüm olası formatlardaki kartları güvenle çekiyoruz
        cursor.execute("""
            SELECT madde FROM unite_ozetleri 
            WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s
        """, (f"%{secilen_ders}%", secilen_unite))
        
        satirlar = cursor.fetchall()
        cursor.close()
        conn.close()

        for s in satirlar:
            metin = s.get("madde", "").strip()
            if not metin:
                continue
                
            on_yuz = ""
            arka_yuz = ""

            # Güvenli metin ayrıştırma
            if "Soru:" in metin and "Cevap:" in metin:
                try:
                    parcalar = metin.split("Cevap:")
                    on_yuz = parcalar[0].replace("Soru:", "").strip()
                    arka_yuz = parcalar[1].strip()
                except Exception:
                    on_yuz = "Bilgi Kartı"
                    arka_yuz = metin
            elif "->" in metin:
                try:
                    parcalar = metin.split("->")
                    on_yuz = parcalar[0].strip()
                    arka_yuz = parcalar[1].strip()
                except Exception:
                    on_yuz = "Bilgi Kartı"
                    arka_yuz = metin
            else:
                # Sadece dışarıdan yüklenen Anki/dosya formatlarını filtrelemek istiyorsan burayı atlayabilirsin
                # Ancak uygulamanın çökmemesi için düz metinleri de karta dönüştürüyoruz:
                on_yuz = f"📌 {secilen_unite}. Ünite Kartı"
                arka_yuz = metin

            if on_yuz and arka_yuz:
                kartlar.append({"on": on_yuz, "arka": arka_yuz})

        random.shuffle(kartlar)
    except Exception as e:
        print(f"Hafıza kartları yüklenirken hata oluştu: {str(e)}")

    return render_template("index.html", 
                           durum="flashcards", 
                           aktif_ders=secilen_ders, 
                           aktif_unite=secilen_unite, 
                           kartlar=kartlar, 
                           dersler=GUZ_DERSLERI)

@app.route("/unite-durum-guncelle", methods=["POST"])
@giris_zorunlu
def unite_durum_guncelle():
    ders = request.form.get("ders")
    unite = int(request.form.get("unite"))
    tur = request.form.get("tur")
    deger = int(request.form.get("deger"))

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM unite_takip WHERE TRIM(ders_adi) = TRIM(%s) AND unite_no = %s", (ders, unite))
    kayit = cursor.fetchone()
    if kayit:
        if tur == "okundu":
            cursor.execute("UPDATE unite_takip SET okundu = %s WHERE id = %s", (deger, kayit["id"]))
        elif tur == "izlendi":
            cursor.execute("UPDATE unite_takip SET izlendi = %s WHERE id = %s", (deger, kayit["id"]))
    else:
        o_val = deger if tur == "okundu" else 0
        i_val = deger if tur == "izlendi" else 0
        cursor.execute("INSERT INTO unite_takip (ders_adi, unite_no, okundu, izlendi) VALUES (%s, %s, %s, %s)", (ders, unite, o_val, i_val))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"basarili": True})

@app.route("/video-kaydet", methods=["POST"])
@giris_zorunlu
def video_kaydet():
    ders = request.form.get("ders_adi", "").strip() or request.form.get("ders", "").strip()
    unite = int(request.form.get("unite_no", 1) or request.form.get("unite", 1))
    url = request.form.get("video_url", "").strip()
    kaynak_sayfa = request.form.get("kaynak_sayfa", "icerik_merkezi")

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO ders_videolari (ders_adi, unite_no, video_url) VALUES (%s, %s, %s)", (ders, unite, url))
    conn.commit()
    cursor.close()
    conn.close()

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' - {unite}. Ünite videosu başarıyla kaydedildi."}
    if kaynak_sayfa == "ders_calis":
        return redirect(url_for("ders_calis", ders=ders, unite=unite))
    return redirect(url_for("icerik_merkezi", ders=ders))

@app.route("/unite-pekistirme")
@giris_zorunlu
def unite_pekistirme_listesi():
    ders = request.args.get("ders", "").strip()
    if not ders and GUZ_DERSLERI:
        ders = GUZ_DERSLERI[0]

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT unite_no, COUNT(*) as adet 
        FROM sorular 
        WHERE TRIM(ders_adi) LIKE %s AND unite_no > 0
        GROUP BY unite_no
        ORDER BY unite_no ASC
    """, (f"%{ders}%",))
    sayilar = {row["unite_no"]: row["adet"] for row in cursor.fetchall()}
    cursor.close()
    conn.close()

    uniteler = []
    for i in range(1, 15):
        uniteler.append({
            "no": i,
            "baslik": f"Ünite {i}",
            "soru_sayisi": sayilar.get(i, 0),
            "ders_adi": ders
        })

    return render_template("index.html", 
                           durum="unite_pekistirme", 
                           uniteler=uniteler, 
                           aktif_ders=ders, 
                           dersler=GUZ_DERSLERI)

@app.route("/unite-test-baslat/<int:unite_no>")
@giris_zorunlu
def unite_test_baslat(unite_no):
    ders = request.args.get("ders", "").strip()
    if not ders and GUZ_DERSLERI:
        ders = GUZ_DERSLERI[0]

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM sorular 
        WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s
        ORDER BY id ASC
    """, (f"%{ders}%", unite_no))
    satirlar = cursor.fetchall()
    cursor.close()
    conn.close()

    if not satirlar:
        session["bildirim"] = {"tur": "warning", "metin": f"'{ders}' dersinin {unite_no}. ünitesine ait soru bulunamadı."}
        return redirect(url_for("unite_pekistirme_listesi", ders=ders))

    soru_idleri = [r["id"] for r in satirlar]
    random.shuffle(soru_idleri)
    sinav_oturumunu_temizle()

    session["soru_idleri"] = soru_idleri
    session["aktif_ders"] = f"{ders} (Ünite {unite_no} - {len(soru_idleri)} Soru)"
    session["sinav_modu"] = "ogrenme"
    session["mevcut_indeks"] = 0
    session["cevaplar"] = []
    session["dogru"] = 0
    session["yanlis"] = 0
    session["bos"] = 0
    session["toplam_sure_saniye"] = 0

    return redirect(url_for("soru_goruntule"))

@app.route("/kronoloji")
@giris_zorunlu
def kronoloji_egzersizi():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, soru_metni, aciklama, dogru_cevap, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e 
        FROM sorular 
        WHERE TRIM(ders_adi) LIKE %s
    """, (f"%{secilen_ders}%",))
    satirlar = cursor.fetchall()
    cursor.close()
    conn.close()

    otomatik_olaylar = []
    gorulen_yillar = set()

    for s in satirlar:
        metin_havuzu = f"{s['soru_metni']} {s['aciklama']}"
        yillar = re.findall(r'\b(1[3-9]\d{2})\b', metin_havuzu)
        
        if yillar:
            yil = int(yillar[0])
            if yil not in gorulen_yillar:
                gorulen_yillar.add(yil)
                olay_metni = s['soru_metni']
                if len(olay_metni) > 130:
                    olay_metni = olay_metni[:127] + "..."
                
                otomatik_olaylar.append({
                    "id": s["id"],
                    "yil": yil,
                    "olay": olay_metni,
                    "detay": f"Doğru Cevap: {s['dogru_cevap']} | {s['aciklama'][:90]}..." if s['aciklama'] else f"Doğru Seçenek: {s['dogru_cevap']}"
                })
        if len(otomatik_olaylar) >= 6:
            break

    if len(otomatik_olaylar) < 3:
        karisik_olaylar = [
            {"id": 1, "yil": 1453, "olay": "İstanbul'un fethi sonrası Gennadios'un Rum Patriği seçilmesi", "detay": "Fatih Sultan Mehmet dönemi."},
            {"id": 2, "yil": 1461, "olay": "Episkopos Hovagim'in İstanbul Ermeni Patriği tayin edilmesi", "detay": "Fatih Sultan Mehmet dönemi."},
            {"id": 3, "yil": 1492, "olay": "Sefarad Yahudilerinin Osmanlı topraklarına gelişi", "detay": "II. Bayezid dönemi."},
            {"id": 4, "yil": 1602, "olay": "Fener Rum Patrikhanesi'nin Aya Yorgi'ye taşınması", "detay": "Patrikhane merkezi."},
            {"id": 5, "yil": 1835, "olay": "Hahambaşılık makamına yeniden resmi berat verilmesi", "detay": "II. Mahmud dönemi."},
            {"id": 6, "yil": 1856, "olay": "Islahat Fermanı ile millet nizamnamelerinin başlaması", "detay": "Tanzimat dönemi."}
        ]
    else:
        karisik_olaylar = list(otomatik_olaylar)

    random.shuffle(karisik_olaylar)

    return render_template("index.html", 
                           durum="kronoloji", 
                           aktif_ders=secilen_ders, 
                           karisik_olaylar=karisik_olaylar, 
                           dersler=GUZ_DERSLERI)

@app.route("/sinav-baslat", methods=["POST"])
@giris_zorunlu
def sinav_baslat():
    ders = request.form.get("ders", "HEPSI").strip()
    unite_secim = request.form.get("unite", "TUMU").strip()
    sure_dakika = int(request.form.get("sure", 0))
    mod = request.form.get("mod", "sinav")
    limit = int(request.form.get("limit", 20))
    ozel_havuz = request.form.get("ozel_havuz", "")

    if unite_secim.startswith("UNITE_"):
        limit = 0

    conn = veritabani_baglan()
    cursor = conn.cursor()

    if ozel_havuz == "yildizli":
        cursor.execute("SELECT id FROM sorular WHERE yildizli = 1")
        aktif_ders_adi = "⭐ Yıldızlı Sorular Havuzu"
    elif ozel_havuz == "hatalar":
        cursor.execute("""
            SELECT s.id FROM sorular s
            JOIN performans p ON s.id = p.soru_id
            WHERE p.son_durum = 'YANLIS'
        """)
        aktif_ders_adi = "🎯 Yanlışlar & Telafi Havuzu"
    elif ders == "HEPSI":
        cursor.execute("SELECT id FROM sorular")
        aktif_ders_adi = "Tüm Dersler (Karışık)"
    else:
        if unite_secim == "VIZE":
            cursor.execute("""
                SELECT id FROM sorular 
                WHERE TRIM(ders_adi) LIKE %s AND (unite_no BETWEEN 1 AND 7 OR unite_no = 0)
            """, (f"%{ders}%",))
            aktif_ders_adi = f"{ders} (Vize Konuları)"
        elif unite_secim.startswith("UNITE_"):
            u_no = int(unite_secim.replace("UNITE_", ""))
            cursor.execute("""
                SELECT id FROM sorular 
                WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s
            """, (f"%{ders}%", u_no))
            aktif_ders_adi = f"{ders} (Ünite {u_no})"
        else:
            cursor.execute("""
                SELECT id FROM sorular 
                WHERE TRIM(ders_adi) LIKE %s
            """, (f"%{ders}%",))
            aktif_ders_adi = ders

    satirlar = cursor.fetchall()
    cursor.close()
    conn.close()

    if not satirlar and ders != "HEPSI":
        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s", (f"%{ders}%",))
        satirlar = cursor.fetchall()
        cursor.close()
        conn.close()
        aktif_ders_adi = ders

    if not satirlar:
        session["bildirim"] = {"tur": "warning", "metin": "Seçilen kritere ait soru bulunamadı."}
        return redirect(url_for("ana_sayfa"))

    tum_idlar = [row["id"] for row in satirlar]
    random.shuffle(tum_idlar)
    secilen_idlar = tum_idlar[:limit] if (limit > 0 and len(tum_idlar) > limit) else tum_idlar

    sinav_oturumunu_temizle()

    session["soru_idleri"] = secilen_idlar
    session["aktif_ders"] = aktif_ders_adi
    session["sinav_modu"] = mod
    session["mevcut_indeks"] = 0
    session["cevaplar"] = []
    session["dogru"] = 0
    session["yanlis"] = 0
    session["bos"] = 0
    session["toplam_sure_saniye"] = sure_dakika * 60

    return redirect(url_for("soru_goruntule"))

@app.route("/soru", methods=["GET", "POST"])
@giris_zorunlu
def soru_goruntule():
    soru_idleri = session.get("soru_idleri", [])
    indeks = session.get("mevcut_indeks", 0)
    aktif_ders = session.get("aktif_ders", "Genel Sınav")
    mod = session.get("sinav_modu", "sinav")
    kalan_sure = request.args.get("kalan_sure")

    if not soru_idleri:
        return redirect(url_for("ana_sayfa"))

    if indeks >= len(soru_idleri):
        return redirect(url_for("sonuc_goruntule"))

    aktif_id = soru_idleri[indeks]

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sorular WHERE id = %s", (aktif_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return redirect(url_for("ana_sayfa"))

    soru = dict(row)

    if request.method == "POST":
        secilen = request.form.get("secenek", "")
        kalan_saniye = request.form.get("kalan_saniye")
        dogru = soru["dogru_cevap"]

        if not secilen:
            durum = "BOS"
            session["bos"] = session.get("bos", 0) + 1
        elif secilen == dogru:
            durum = "DOGRU"
            session["dogru"] = session.get("dogru", 0) + 1
        else:
            durum = "YANLIS"
            session["yanlis"] = session.get("yanlis", 0) + 1

        cevap_listesi = session.get("cevaplar", [])
        cevap_listesi.append({
            "soru_id": soru["id"],
            "soru_metni": soru["soru_metni"][:65] + "...",
            "secilen": secilen if secilen else "Boş",
            "dogru": dogru,
            "durum": durum
        })
        session["cevaplar"] = cevap_listesi
        session["mevcut_indeks"] = indeks + 1

        if mod == "ogrenme":
            conn = veritabani_baglan()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO performans (soru_id, dogru_sayisi, yanlis_sayisi, son_durum) VALUES (%s, 0, 0, '') ON CONFLICT (soru_id) DO NOTHING", (soru["id"],))
            if durum == "DOGRU":
                cursor.execute("UPDATE performans SET dogru_sayisi = dogru_sayisi + 1, son_durum = 'DOGRU' WHERE soru_id = %s", (soru["id"],))
            elif durum == "YANLIS":
                cursor.execute("UPDATE performans SET yanlis_sayisi = yanlis_sayisi + 1, son_durum = 'YANLIS' WHERE soru_id = %s", (soru["id"],))
            conn.commit()
            cursor.close()
            conn.close()

        if mod == "sinav":
            if session["mevcut_indeks"] >= len(soru_idleri):
                return redirect(url_for("sonuc_goruntule"))
            return redirect(url_for("soru_goruntule", kalan_sure=kalan_saniye))

        return render_template("index.html", 
                               durum="geribildirim", 
                               soru=soru, 
                               secilen=secilen, 
                               sonuc=durum, 
                               aktif_ders=aktif_ders, 
                               kalan_saniye=kalan_saniye, 
                               sira=indeks + 1, 
                               toplam=len(soru_idleri))

    toplam_sure = session.get("toplam_sure_saniye", 0)
    baslangic_sure = kalan_sure if kalan_sure is not None else toplam_sure

    return render_template("index.html", 
                           durum="soru", 
                           soru=soru, 
                           sira=indeks + 1, 
                           toplam=len(soru_idleri), 
                           aktif_ders=aktif_ders, 
                           kalan_saniye=baslangic_sure, 
                           mod=mod)

@app.route("/testi-bitir")
@giris_zorunlu
def testi_bitir():
    soru_idleri = session.get("soru_idleri", [])
    indeks = session.get("mevcut_indeks", 0)
    kalan_adet = len(soru_idleri) - indeks
    if kalan_adet > 0:
        session["bos"] = session.get("bos", 0) + kalan_adet
    session["mevcut_indeks"] = len(soru_idleri)
    return redirect(url_for("sonuc_goruntule"))

@app.route("/sonuc")
@giris_zorunlu
def sonuc_goruntule():
    dogru = session.get("dogru", 0)
    yanlis = session.get("yanlis", 0)
    bos = session.get("bos", 0)
    aktif_ders = session.get("aktif_ders", "Genel Sınav")
    mod = session.get("sinav_modu", "sinav")
    cevaplar = session.get("cevaplar", [])
    toplam = dogru + yanlis + bos

    net = dogru - (yanlis * 0.25)
    puan = max(0, (net / toplam) * 100) if toplam > 0 else 0

    try:
        conn = veritabani_baglan()
        cursor = conn.cursor()
        simdi = datetime.now().strftime("%d.%m.%Y %H:%M")
        cursor.execute("""
            INSERT INTO sinav_gecmisi (tarih, ders_adi, dogru, yanlis, bos, net, puan)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (simdi, aktif_ders, dogru, yanlis, bos, round(net, 2), round(puan, 1)))

        for c in cevaplar:
            if "soru_id" in c:
                s_id = c["soru_id"]
                durum = c["durum"]
                cursor.execute("INSERT INTO performans (soru_id, dogru_sayisi, yanlis_sayisi, son_durum) VALUES (%s, 0, 0, '') ON CONFLICT (soru_id) DO NOTHING", (s_id,))
                if durum == "DOGRU":
                    cursor.execute("UPDATE performans SET dogru_sayisi = dogru_sayisi + 1, son_durum = 'DOGRU' WHERE soru_id = %s", (s_id,))
                elif durum == "YANLIS":
                    cursor.execute("UPDATE performans SET yanlis_sayisi = yanlis_sayisi + 1, son_durum = 'YANLIS' WHERE soru_id = %s", (s_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass

    return render_template("index.html", 
                           durum="sonuc", 
                           dogru=dogru, 
                           yanlis=yanlis, 
                           bos=bos, 
                           net=round(net, 2), 
                           puan=round(puan, 1), 
                           aktif_ders=aktif_ders, 
                           mod=mod, 
                           cevaplar=cevaplar)

@app.route("/istatistik")
@giris_zorunlu
def istatistik_paneli():
    conn = veritabani_baglan()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            s.ders_adi,
            COUNT(p.soru_id) as cozulen_soru,
            SUM(p.dogru_sayisi) as toplam_dogru,
            SUM(p.yanlis_sayisi) as toplam_yanlis
        FROM sorular s
        INNER JOIN performans p ON s.id = p.soru_id
        GROUP BY s.ders_adi
    """)
    veriler = cursor.fetchall()

    rapor = []
    toplam_genel_cozulen, toplam_genel_dogru, toplam_genel_yanlis = 0, 0, 0

    for row in veriler:
        d_adi = row["ders_adi"]
        d = row["toplam_dogru"] or 0
        y = row["toplam_yanlis"] or 0
        cozulen = d + y
        net = d - (y * 0.25)
        oran = round((d / cozulen) * 100, 1) if cozulen > 0 else 0

        toplam_genel_cozulen += cozulen
        toplam_genel_dogru += d
        toplam_genel_yanlis += y

        rapor.append({
            "ders_adi": d_adi, "cozulen": cozulen, "dogru": d, "yanlis": y, "net": round(net, 2), "oran": oran
        })

    genel_net = toplam_genel_dogru - (toplam_genel_yanlis * 0.25)
    genel_oran = round((toplam_genel_dogru / toplam_genel_cozulen) * 100, 1) if toplam_genel_cozulen > 0 else 0

    cursor.execute("SELECT * FROM sinav_gecmisi ORDER BY id DESC LIMIT 15")
    gecmis_sinavlar = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    return render_template("index.html", 
                           durum="istatistik", 
                           rapor=rapor, 
                           toplam_cozulen=toplam_genel_cozulen, 
                           genel_net=round(genel_net, 2), 
                           genel_oran=genel_oran, 
                           gecmis_sinavlar=gecmis_sinavlar)

@app.route("/yildiz-degistir/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def yildiz_degistir(soru_id):
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT yildizli FROM sorular WHERE id = %s", (soru_id,))
    row = cursor.fetchone()
    if row:
        yeni_durum = 0 if row["yildizli"] == 1 else 1
        cursor.execute("UPDATE sorular SET yildizli = %s WHERE id = %s", (yeni_durum, soru_id))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"basarili": True, "yildizli": yeni_durum})
    cursor.close()
    conn.close()
    return jsonify({"basarili": False}), 404

@app.route("/yonetim", methods=["GET"])
@giris_zorunlu
def soru_yonetimi():
    kelime = request.args.get("kelime", "").strip()
    secilen_ders = request.args.get("ders", "")

    conn = veritabani_baglan()
    cursor = conn.cursor()
    sql = "SELECT * FROM sorular WHERE 1=1"
    paramlar = []

    if kelime:
        sql += " AND (soru_metni ILIKE %s OR secenek_a ILIKE %s OR secenek_b ILIKE %s OR secenek_c ILIKE %s OR secenek_d ILIKE %s OR secenek_e ILIKE %s OR aciklama ILIKE %s OR kullanici_notu ILIKE %s)"
        for _ in range(8):
            paramlar.append(f"%{kelime}%")

    if secilen_ders:
        sql += " AND ders_adi = %s"
        paramlar.append(secilen_ders)

    sql += " ORDER BY id DESC LIMIT 50"
    cursor.execute(sql, tuple(paramlar))
    bulunan_sorular = [dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()

    return render_template("index.html", durum="yonetim", sorular=bulunan_sorular, kelime=kelime, secilen_ders=secilen_ders, dersler=GUZ_DERSLERI)

@app.route("/soru-duzenle/<int:soru_id>", methods=["GET", "POST"])
@giris_zorunlu
def soru_duzenle(soru_id):
    conn = veritabani_baglan()
    cursor = conn.cursor()

    if request.method == "POST":
        ders = request.form.get("ders_adi")
        metin = request.form.get("soru_metni")
        a = request.form.get("secenek_a")
        b = request.form.get("secenek_b")
        c = request.form.get("secenek_c")
        d = request.form.get("secenek_d")
        e = request.form.get("secenek_e")
        dogru = request.form.get("dogru_cevap")
        aciklama = request.form.get("aciklama")
        kullanici_notu = request.form.get("kullanici_notu", "")
        unite_no = int(request.form.get("unite_no", 0))

        cursor.execute("""
            UPDATE sorular 
            SET ders_adi = %s, soru_metni = %s, secenek_a = %s, secenek_b = %s, secenek_c = %s, secenek_d = %s, secenek_e = %s, dogru_cevap = %s, aciklama = %s, kullanici_notu = %s, unite_no = %s
            WHERE id = %s
        """, (ders, metin, a, b, c, d, e, dogru, aciklama, kullanici_notu, unite_no, soru_id))
        conn.commit()
        cursor.close()
        conn.close()
        session["bildirim"] = {"tur": "success", "metin": f"Soru #{soru_id} güncellendi."}
        return redirect(url_for("soru_yonetimi"))

    cursor.execute("SELECT * FROM sorular WHERE id = %s", (soru_id,))
    soru = cursor.fetchone()
    cursor.close()
    conn.close()
    if not soru:
        return redirect(url_for("soru_yonetimi"))
    return render_template("index.html", durum="duzenle", soru=dict(soru), dersler=GUZ_DERSLERI)

@app.route("/soru-sil/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def soru_sil(soru_id):
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sorular WHERE id = %s", (soru_id,))
    cursor.execute("DELETE FROM performans WHERE soru_id = %s", (soru_id,))
    conn.commit()
    cursor.close()
    conn.close()
    session["bildirim"] = {"tur": "info", "metin": f"Soru #{soru_id} silindi."}
    return redirect(url_for("soru_yonetimi"))

@app.route("/sorulari-sifirla", methods=["POST"])
@giris_zorunlu
def sorulari_sifirla():
    try:
        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sorular")
        conn.commit()
        cursor.close()
        conn.close()
        session["bildirim"] = {"tur": "success", "metin": "Tüm soru havuzu başarıyla sıfırlandı."}
    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"Hata: {str(e)}"}
    return redirect(url_for("soru_yonetimi"))

@app.route("/yedek-indir")
@giris_zorunlu
def yedek_indir():
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no FROM sorular")
    sorular = [dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()

    dosya_metni = json.dumps(sorular, ensure_ascii=False, indent=2)
    tarih_etiketi = datetime.now().strftime("%Y%m%d_%H%M")
    return Response(
        dosya_metni,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=auzef_soru_yedegi_{tarih_etiketi}.json"}
    )

@app.route("/yedek-yukle", methods=["POST"])
@giris_zorunlu
def yedek_yukle():
    dosya = request.files.get("yedek_dosyasi")
    hedef_ders = request.form.get("secilen_ders", GUZ_DERSLERI[0]).strip()
    veri_turu = request.form.get("veri_turu", "otomatik").strip()

    if not dosya or not dosya.filename:
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir dosya seçin."}
        return redirect(url_for("ana_sayfa"))

    dosya_adi = dosya.filename.lower()
    conn = veritabani_baglan()
    cursor = conn.cursor()
    eklenen_soru = 0
    eklenen_kart = 0

    if veri_turu == "otomatik":
        is_kart_dosyasi = "kart" in dosya_adi or dosya_adi.endswith(".txt") or dosya_adi.endswith(".apkg")
    else:
        is_kart_dosyasi = (veri_turu == "kart")

    try:
        if dosya_adi.endswith(".json"):
            veri = json.load(dosya)
            if isinstance(veri, dict) and "quiz" in veri:
                veri = veri["quiz"]

            for s in veri:
                ders = s.get("ders_adi", hedef_ders).strip()
                if is_kart_dosyasi or "madde" in s or "on" in s or ("question" in s and "answerOptions" not in s):
                    madde_metni = s.get("madde") or s.get("question") or f"Soru: {s.get('on')} | Cevap: {s.get('arka')}"
                    u_no = int(s.get("unite_no", 1))
                    cursor.execute("""
                        INSERT INTO unite_ozetleri (ders_adi, unite_no, madde)
                        VALUES (%s, %s, %s)
                    """, (ders, u_no, madde_metni))
                    eklenen_kart += 1
                elif "question" in s and "answerOptions" in s:
                    soru_metni = s.get("question", "")
                    secenekler = s.get("answerOptions", [])
                    dogru_metin = "Doğru Yanıt"
                    for opt in secenekler:
                        if opt.get("isCorrect") is True:
                            dogru_metin = opt.get("text", "")
                            break
                    cursor.execute("""
                        INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, '', 1)
                    """, (ders, soru_metni, dogru_metin, "Alternatif B", "Alternatif C", "Alternatif D", "Alternatif E", "A", "NotebookLM Aktarımı"))
                    eklenen_soru += 1
                else:
                    cursor.execute("""
                        INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        ders, s.get("soru_metni", ""), s.get("secenek_a", "A"), s.get("secenek_b", "B"),
                        s.get("secenek_c", "C"), s.get("secenek_d", "D"), s.get("secenek_e", "E"), 
                        s.get("dogru_cevap", "A"), s.get("aciklama", ""), 
                        s.get("yildizli", 0), s.get("kullanici_notu", ""), s.get("unite_no", 1)
                    ))
                    eklenen_soru += 1

        elif dosya_adi.endswith(".csv") or dosya_adi.endswith(".txt"):
            icerik_metni = dosya.read().decode("utf-8", errors="ignore")
            satirlar = icerik_metni.splitlines()

            for satir_str in satirlar:
                satir_str = satir_str.strip()
                if not satir_str:
                    continue
                
                # Anki dışa aktarımındaki # ile başlayan ayar/yorum satırlarını pas geç
                if satir_str.startswith("#"):
                    continue
                
                on_yuz = ""
                arka_yuz = ""

                if "\t" in satir_str:
                    parcalar = satir_str.split("\t")
                    on_yuz = parcalar[0].strip()
                    arka_yuz = parcalar[1].strip() if len(parcalar) > 1 else ""
                elif "Q:" in satir_str and "A:" in satir_str:
                    parcalar = satir_str.split("A:")
                    on_yuz = parcalar[0].replace("Q:", "").strip()
                    arka_yuz = parcalar[1].strip() if len(parcalar) > 1 else ""
                elif ";" in satir_str:
                    parcalar = satir_str.split(";")
                    on_yuz = parcalar[0].replace("Q:", "").strip()
                    arka_yuz = parcalar[1].replace("A:", "").strip() if len(parcalar) > 1 else ""
                else:
                    on_yuz = satir_str

                if not on_yuz:
                    continue

                if is_kart_dosyasi:
                    madde_metni = f"Soru: {on_yuz} | Cevap: {arka_yuz}" if arka_yuz else on_yuz
                    cursor.execute("""
                        INSERT INTO unite_ozetleri (ders_adi, unite_no, madde)
                        VALUES (%s, 1, %s)
                    """, (hedef_ders, madde_metni))
                    eklenen_kart += 1
                else:
                    cursor.execute("""
                        INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, '', 1)
                    """, (hedef_ders, on_yuz, arka_yuz if arka_yuz else "Doğru Yanıt", "Alternatif B", "Alternatif C", "Alternatif D", "Alternatif E", "A", "Anki Aktarımı"))
                    eklenen_soru += 1
        else:
            session["bildirim"] = {"tur": "danger", "metin": "Desteklenmeyen dosya formatı."}
            cursor.close()
            conn.close()
            return redirect(url_for("ana_sayfa"))

        conn.commit()
        cursor.close()
        conn.close()
        
        mesaj = []
        if eklenen_soru > 0: mesaj.append(f"{eklenen_soru} soru")
        if eklenen_kart > 0: mesaj.append(f"{eklenen_kart} Anki bilgi kartı")
        
        bildirim_metni = " ve ".join(mesaj) + f" ({hedef_ders}) hafıza kartlarına başarıyla aktarıldı!" if mesaj else "Hiçbir veri eklenemedi."
        session["bildirim"] = {"tur": "success", "metin": bildirim_metni}
        
    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"Hata: {str(e)}"}

    return redirect(url_for("ana_sayfa"))
@app.route("/sifirla", methods=["POST"])
@giris_zorunlu
def veritabani_sifirla():
    session.clear()
    session["bildirim"] = {"tur": "info", "metin": "Oturum güvenle kapatıldı. Bulut veritabanındaki tüm verileriniz eksiksiz korunmaktadır."}
    return redirect(url_for("giris_yap"))
@app.route("/arama")
@giris_zorunlu
def global_arama():
    sorgu = request.args.get("q", "").strip()
    bulunan_sorular = []
    bulunan_kartlar = []

    if sorgu:
        conn = veritabani_baglan()
        cursor = conn.cursor()
        
        # 1. Soru havuzunda arama yap
        cursor.execute("""
            SELECT id, ders_adi, soru_metni, secenek_a, dogru_cevap, aciklama 
            FROM sorular 
            WHERE soru_metni ILIKE %s OR ders_adi ILIKE %s OR aciklama ILIKE %s
            LIMIT 20
        """, (f"%{sorgu}%", f"%{sorgu}%", f"%{sorgu}%"))
        bulunan_sorular = cursor.fetchall()

        # 2. Hafıza kartları / hap bilgiler tablosunda arama yap
        cursor.execute("""
            SELECT id, ders_adi, unite_no, madde 
            FROM unite_ozetleri 
            WHERE madde ILIKE %s OR ders_adi ILIKE %s
            LIMIT 20
        """, (f"%{sorgu}%", f"%{sorgu}%"))
        bulunan_kartlar = cursor.fetchall()

        cursor.close()
        conn.close()

    return render_template("index.html", 
                           durum="arama_sonuclari", 
                           sorgu=sorgu, 
                           bulunan_sorular=bulunan_sorular, 
                           bulunan_kartlar=bulunan_kartlar, 
                           dersler=GUZ_DERSLERI)
@app.route("/sw.js")
def service_worker():
    return send_from_directory(os.path.join(app.root_path, "static"), "sw.js", mimetype="application/javascript")

if __name__ == "__main__":
    app.run(debug=True)
