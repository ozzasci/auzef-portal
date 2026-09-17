import os
import re
import sqlite3
import io
import json
import random
import urllib.request
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from pypdf import PdfReader

app = Flask(__name__)
app.secret_key = "auzef_portal_tam_surum_2026_gizli_anahtar"
DB_NAME = "auzef_calisma.db"

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "kitaplar")
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
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def veritabani_hazirla():
    conn = veritabani_baglan()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_adi TEXT UNIQUE,
            ad_soyad TEXT,
            sifre_hash TEXT,
            kayit_tarihi TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sorular (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            kaynak_turu TEXT,
            dosya_yolu TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_takip (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            okundu INTEGER DEFAULT 0,
            izlendi INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ders_videolari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            video_url TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_ozetleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            madde TEXT
        )
    """)
    conn.commit()
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
        "sorular", "aktif_ders", "sinav_modu", "mevcut_indeks", 
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
        return f"https://drive.google.com/file/d/{dosya_id}/view?usp=sharing"
    return link

def auzef_harfsiz_ve_harfli_soru_ayikla(metin, unite_no=1):
    temiz = re.sub(r'about:blank\s*\d+/\d+', '', metin)
    temiz = re.sub(r'\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{1,2}', '', temiz)
    temiz = re.sub(r'Ders:\s*.*?(?:\n|\|)', '', temiz, flags=re.IGNORECASE)
    temiz = re.sub(r'Ünite:\s*.*?\n', '', temiz, flags=re.IGNORECASE)

    bloklar = re.split(r'(?:^|\n)\s*Soru\s*[-–—:]*\s*(\d{1,2})\s*:', temiz, flags=re.IGNORECASE)
    sorular = []
    if len(bloklar) > 1:
        for i in range(1, len(bloklar), 2):
            s_no = bloklar[i].strip()
            icerik = bloklar[i+1].strip()

            cevap_ara = re.search(r'(?:Cevap\s*[-–—:]*\s*\d{0,2}\s*:|Doğru\s*Cevap\s*:)\s*([^\n\r]+)', icerik, flags=re.IGNORECASE)
            cevap_metni = cevap_ara.group(1).strip() if cevap_ara else ""

            govde = icerik[:cevap_ara.start()].strip() if cevap_ara else icerik
            govde = re.sub(r'\(Çoktan Seçmeli\)', '', govde, flags=re.IGNORECASE).strip()

            satirlar = [s.strip() for s in govde.split("\n") if s.strip()]
            if not satirlar:
                continue

            if len(satirlar) >= 6 and not re.match(r'^\(?[A-Ea-e]\)?', satirlar[-1]):
                sec_e, sec_d, sec_c, sec_b, sec_a = satirlar[-1], satirlar[-2], satirlar[-3], satirlar[-4], satirlar[-5]
                soru_kok = " ".join(satirlar[:-5])
            else:
                sec_a_m = re.search(r'(?:\(A\)|A\)|A\.-)\s*(.*?)(?=(?:\([B-E]\)|[B-E]\)|[B-E]\.-))', govde, re.DOTALL)
                sec_b_m = re.search(r'(?:\(B\)|B\)|B\.-)\s*(.*?)(?=(?:\([C-E]\)|[C-E]\)|[C-E]\.-))', govde, re.DOTALL)
                sec_c_m = re.search(r'(?:\(C\)|C\)|C\.-)\s*(.*?)(?=(?:\([D-E]\)|[D-E]\)|[D-E]\.-))', govde, re.DOTALL)
                sec_d_m = re.search(r'(?:\(D\)|D\)|D\.-)\s*(.*?)(?=(?:\(E\)|E\)|E\.-|\Z))', govde, re.DOTALL)
                sec_e_m = re.search(r'(?:\(E\)|E\)|E\.-)\s*(.*?)$', govde, re.DOTALL)

                if sec_a_m and sec_b_m and sec_c_m:
                    soru_kok = govde[:sec_a_m.start()].strip()
                    sec_a = sec_a_m.group(1).strip()
                    sec_b = sec_b_m.group(1).strip()
                    sec_c = sec_c_m.group(1).strip()
                    sec_d = sec_d_m.group(1).strip() if sec_d_m else "-"
                    sec_e = sec_e_m.group(1).strip() if sec_e_m else "-"
                else:
                    soru_kok = satirlar[0]
                    sec_a = satirlar[1] if len(satirlar) > 1 else "-"
                    sec_b = satirlar[2] if len(satirlar) > 2 else "-"
                    sec_c = satirlar[3] if len(satirlar) > 3 else "-"
                    sec_d = satirlar[4] if len(satirlar) > 4 else "-"
                    sec_e = satirlar[5] if len(satirlar) > 5 else "-"

            val_a, val_b, val_c, val_d, val_e = " ".join(sec_a.split()), " ".join(sec_b.split()), " ".join(sec_c.split()), " ".join(sec_d.split()), " ".join(sec_e.split())
            dogru_harf = "A"
            c_clean = " ".join(cevap_metni.split()).lower()
            tek_harf = re.search(r'^[A-Ea-e]$', c_clean.strip())
            if tek_harf:
                dogru_harf = tek_harf.group(0).upper()
            else:
                for harf, val in [("A", val_a), ("B", val_b), ("C", val_c), ("D", val_d), ("E", val_e)]:
                    if val != "-" and (val.lower() == c_clean or val.lower() in c_clean or c_clean in val.lower()):
                        dogru_harf = harf
                        break

            sorular.append({
                "unite_no": unite_no,
                "metin": " ".join(soru_kok.split()),
                "a": val_a, "b": val_b, "c": val_c, "d": val_d, "e": val_e,
                "dogru_cevap": dogru_harf,
                "aciklama": f"Ünite {unite_no} Soru {s_no}. Doğru Cevap: {dogru_harf}"
            })
    return sorular

def klavuz_pdf_ayikla(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    tam_metin = ""
    for page in reader.pages:
        y = page.extract_text()
        if y:
            tam_metin += y + "\n"

    satirlar = [s.strip() for s in tam_metin.split("\n") if s.strip()]
    unite_verileri = {}
    mevcut_unite = 1

    for satir in satirlar:
        if "FAITH S. AKADEMİ" in satir or "TELEGRAM" in satir or "KILAVUZU" in satir:
            continue
        
        unite_baslik = re.match(r'^(\d{1,2})\.\s+[A-ZÇĞİÖŞÜ\s]{3,}', satir)
        if unite_baslik:
            no = int(unite_baslik.group(1))
            if 1 <= no <= 14:
                mevcut_unite = no
                if mevcut_unite not in unite_verileri:
                    unite_verileri[mevcut_unite] = []
                continue

        if len(satir) > 15:
            if mevcut_unite not in unite_verileri:
                unite_verileri[mevcut_unite] = []
            unite_verileri[mevcut_unite].append(satir)

    return unite_verileri

@app.route("/giris", methods=["GET", "POST"])
def giris_yap():
    if "kullanici_id" in session:
        return redirect(url_for("ana_sayfa"))

    if request.method == "POST":
        kullanici_adi = request.form.get("kullanici_adi", "").strip().lower()
        sifre = request.form.get("sifre", "")

        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = ?", (kullanici_adi,))
        kullanici = cursor.fetchone()
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
        cursor.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = ?", (kullanici_adi,))
        if cursor.fetchone():
            conn.close()
            session["bildirim"] = {"tur": "warning", "metin": "Bu kullanıcı adı zaten alınmış."}
            return redirect(url_for("kayit_ol"))

        sifre_hash = generate_password_hash(sifre)
        simdi = datetime.now().strftime("%d.%m.%Y %H:%M")
        cursor.execute("""
            INSERT INTO kullanicilar (kullanici_adi, ad_soyad, sifre_hash, kayit_tarihi)
            VALUES (?, ?, ?, ?)
        """, (kullanici_adi, ad_soyad, sifre_hash, simdi))
        conn.commit()
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
    dersler = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) FROM sorular")
    toplam_soru = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM sorular WHERE yildizli = 1")
    yildizli_soru_sayisi = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM sorular s
        JOIN performans p ON s.id = p.soru_id
        WHERE p.son_durum = 'YANLIS'
    """)
    hatali_soru_sayisi = cursor.fetchone()[0]
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

@app.route("/otomatik-klavuz-isle", methods=["POST"])
@giris_zorunlu
def otomatik_klavuz_isle():
    ders = request.form.get("ders_adi", "").strip()
    drive_link = request.form.get("drive_url", "").strip()
    yuklenen_dosya = request.files.get("klavuz_dosya")

    pdf_bytes = None

    if drive_link:
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
            session["bildirim"] = {"tur": "danger", "metin": f"Drive'dan dosya çekilemedi: {str(e)}. Linkin 'Bağlantıya sahip olan herkes görüntüleyebilir' olduğundan emin olun."}
            return redirect(url_for("icerik_merkezi", ders=ders))

    elif yuklenen_dosya and yuklenen_dosya.filename.lower().endswith(".pdf"):
        pdf_bytes = yuklenen_dosya.read()

    else:
        session["bildirim"] = {"tur": "warning", "metin": "Lütfen bir Drive linki yapıştırın veya PDF yükleyin."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    try:
        ayiklanan_uniteler = klavuz_pdf_ayikla(pdf_bytes)
        if not ayiklanan_uniteler:
            session["bildirim"] = {"tur": "warning", "metin": "PDF okundu fakat kılavuz formatına uygun ünite maddeleri algılanamadı."}
            return redirect(url_for("icerik_merkezi", ders=ders))

        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM unite_ozetleri WHERE TRIM(ders_adi) LIKE ?", (f"%{ders}%",))

        toplam_eklenen = 0
        for u_no, maddeler in ayiklanan_uniteler.items():
            for m in maddeler:
                cursor.execute("INSERT INTO unite_ozetleri (ders_adi, unite_no, madde) VALUES (?, ?, ?)", (ders, u_no, m))
                toplam_eklenen += 1

        conn.commit()
        conn.close()

        session["bildirim"] = {"tur": "success", "metin": f"Harika! '{ders}' için {len(ayiklanan_uniteler)} ünite ve toplam {toplam_eklenen} hap bilgi başarıyla aktarıldı."}
        return redirect(url_for("ders_calis", ders=ders, unite=1))

    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"Ayrıştırma hatası: {str(e)}"}
        return redirect(url_for("icerik_merkezi", ders=ders))

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
    cursor.execute("DELETE FROM unite_kaynaklari WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))
    cursor.execute("""
        INSERT INTO unite_kaynaklari (ders_adi, unite_no, kaynak_turu, dosya_yolu)
        VALUES (?, ?, 'yerel', ?)
    """, (ders, unite_no, f"/static/kitaplar/{dosya_adi}"))
    conn.commit()
    conn.close()

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' dersinin {unite_no}. Ünite PDF'i başarıyla yüklendi!"}
    return redirect(url_for("ders_calis", ders=ders, unite=unite_no))

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
    cursor.execute("DELETE FROM unite_kaynaklari WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))
    cursor.execute("""
        INSERT INTO unite_kaynaklari (ders_adi, unite_no, kaynak_turu, dosya_yolu)
        VALUES (?, ?, 'drive', ?)
    """, (ders, unite_no, preview_link))
    conn.commit()
    conn.close()

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' - Ünite {unite_no} için Google Drive PDF kaynağı bağlandı!"}
    return redirect(url_for("ders_calis", ders=ders, unite=unite_no))

@app.route("/yukle-unite-sorulari", methods=["POST"])
@giris_zorunlu
def yukle_unite_sorulari():
    ders = request.form.get("ders_adi", "").strip()
    unite_no = int(request.form.get("unite_no", 1))
    dosya = request.files.get("soru_dosyasi")

    if not dosya or not dosya.filename.lower().endswith(".pdf"):
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen soru PDF'i seçin."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    metin = ""
    try:
        reader = PdfReader(io.BytesIO(dosya.read()))
        for page in reader.pages:
            y = page.extract_text()
            if y:
                metin += y + "\n"
    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"PDF okunamadı: {str(e)}"}
        return redirect(url_for("icerik_merkezi", ders=ders))

    sorular = auzef_harfsiz_ve_harfli_soru_ayikla(metin, unite_no)
    if not sorular:
        session["bildirim"] = {"tur": "warning", "metin": f"PDF okundu ancak {unite_no}. üniteye ait sorular algılanamadı."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sorular WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))

    for s in sorular:
        cursor.execute("""
            INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?)
        """, (ders, s["metin"], s["a"], s["b"], s["c"], s["d"], s["e"], s["dogru_cevap"], s["aciklama"], unite_no))

    conn.commit()
    conn.close()

    session["bildirim"] = {"tur": "success", "metin": f"Tebrikler! {ders} - Ünite {unite_no} için {len(sorular)} soru aktarıldı."}
    return redirect(url_for("unite_pekistirme_listesi", ders=ders))

@app.route("/hizli-soru-ekle", methods=["POST"])
@giris_zorunlu
def hizli_soru_ekle():
    ders = request.form.get("ders_adi", "").strip()
    unite_no = int(request.form.get("unite_no", 1))
    ham_metin = request.form.get("soru_metinleri", "")

    if not ham_metin.strip():
        session["bildirim"] = {"tur": "warning", "metin": "Lütfen soru metinlerini yapıştırın."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    sorular = auzef_harfsiz_ve_harfli_soru_ayikla(ham_metin, unite_no)
    if not sorular:
        session["bildirim"] = {"tur": "danger", "metin": "Metin çözümlenemedi. Lütfen formatı kontrol edin."}
        return redirect(url_for("icerik_merkezi", ders=ders))

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sorular WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))
    for s in sorular:
        cursor.execute("""
            INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?)
        """, (ders, s["metin"], s["a"], s["b"], s["c"], s["d"], s["e"], s["dogru_cevap"], s["aciklama"], unite_no))
    conn.commit()
    conn.close()

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' - Ünite {unite_no} için {len(sorular)} soru başarıyla kaydedildi."}
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
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))
    row_kaynak = cursor.fetchone()
    
    pdf_url = row_kaynak["dosya_yolu"] if row_kaynak else ""
    kaynak_turu = row_kaynak["kaynak_turu"] if row_kaynak else ""

    cursor.execute("""
        SELECT video_url FROM ders_videolari 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))
    row_video = cursor.fetchone()
    video_url = row_video["video_url"] if row_video else ""

    cursor.execute("""
        SELECT unite_no, okundu, izlendi FROM unite_takip 
        WHERE TRIM(ders_adi) LIKE ?
    """, (f"%{secilen_ders}%",))
    takip_verileri = {r["unite_no"]: {"okundu": r["okundu"], "izlendi": r["izlendi"]} for r in cursor.fetchall()}

    cursor.execute("""
        SELECT madde FROM unite_ozetleri 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))
    ozet_maddeleri = [r["madde"] for r in cursor.fetchall()]

    conn.close()

    embed_url = ""
    if video_url:
        if "watch?v=" in video_url:
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
                           kaynak_turu=kaynak_turu,
                           video_url=video_url,
                           embed_url=embed_url,
                           takip=takip_verileri,
                           ozetler=ozet_maddeleri,
                           unite_baslik=f"{secilen_unite}. Ünite",
                           dersler=GUZ_DERSLERI)

@app.route("/hafiza-kartlari")
@giris_zorunlu
def hafiza_kartlari():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    secilen_unite = int(request.args.get("unite", 1))

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT madde FROM unite_ozetleri 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))
    satirlar = cursor.fetchall()
    conn.close()

    kartlar = []
    for s in satirlar:
        metin = s["madde"].strip()
        if not metin:
            continue

        # Kartın ön ve arka yüzünü akıllıca ayır
        if " denilirdi" in metin or " denirdi" in metin or " adı verilmektedir" in metin:
            parcalar = re.split(r' (?:denilirdi|denirdi|adı verilmektedir)', metin)
            on_yuz = parcalar[0] + " kavramı nasıl adlandırılırdı?"
            arka_yuz = metin
        elif " idi" in metin:
            parcalar = metin.split(" idi")
            on_yuz = parcalar[0] + " nedir / kimdir?"
            arka_yuz = metin
        else:
            on_yuz = f"📌 {secilen_unite}. Ünite Kritik Sınav Bilgisi"
            arka_yuz = metin

        kartlar.append({"on": on_yuz, "arka": arka_yuz})

    random.shuffle(kartlar)
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
    cursor.execute("SELECT id FROM unite_takip WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite))
    kayit = cursor.fetchone()
    if kayit:
        cursor.execute(f"UPDATE unite_takip SET {tur} = ? WHERE id = ?", (deger, kayit["id"]))
    else:
        cursor.execute(f"INSERT INTO unite_takip (ders_adi, unite_no, {tur}) VALUES (?, ?, ?)", (ders, unite, deger))
    conn.commit()
    conn.close()
    return jsonify({"basarili": True})

@app.route("/video-kaydet", methods=["POST"])
@giris_zorunlu
def video_kaydet():
    ders = request.form.get("ders")
    unite = int(request.form.get("unite"))
    url = request.form.get("video_url", "").strip()

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ders_videolari WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite))
    cursor.execute("""
        INSERT INTO ders_videolari (ders_adi, unite_no, video_url) 
        VALUES (?, ?, ?)
    """, (ders, unite, url))
    conn.commit()
    conn.close()
    return redirect(url_for("ders_calis", ders=ders, unite=unite))

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
        WHERE TRIM(ders_adi) LIKE ? AND unite_no > 0
        GROUP BY unite_no
        ORDER BY unite_no ASC
    """, (f"%{ders}%",))
    sayilar = {row["unite_no"]: row["adet"] for row in cursor.fetchall()}
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
        SELECT * FROM sorular 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
        ORDER BY id ASC
    """, (f"%{ders}%", unite_no))
    satirlar = cursor.fetchall()
    conn.close()

    if not satirlar:
        session["bildirim"] = {"tur": "warning", "metin": f"'{ders}' dersinin {unite_no}. ünitesine ait soru bulunamadı. Lütfen 'İçerik Yükle' alanından soru PDF'ini yükleyin."}
        return redirect(url_for("unite_pekistirme_listesi", ders=ders))

    sorular = [dict(r) for r in satirlar]
    sinav_oturumunu_temizle()

    session["sorular"] = sorular
    session["aktif_ders"] = f"{ders} (Ünite {unite_no} Pekiştirme)"
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
        WHERE TRIM(ders_adi) LIKE ?
    """, (f"%{secilen_ders}%",))
    satirlar = cursor.fetchall()
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
        uyari_mesaji = "Bu dersin soru havuzunda yeterli tarihli veri bulunamadığı için genel tarih seti yüklendi."
    else:
        karisik_olaylar = list(otomatik_olaylar)
        uyari_mesaji = None

    random.shuffle(karisik_olaylar)

    return render_template("index.html",
                           durum="kronoloji",
                           aktif_ders=secilen_ders,
                           karisik_olaylar=karisik_olaylar,
                           uyari_mesaji=uyari_mesaji,
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

    conn = veritabani_baglan()
    cursor = conn.cursor()

    if ozel_havuz == "yildizli":
        cursor.execute("SELECT * FROM sorular WHERE yildizli = 1")
        aktif_ders_adi = "⭐ Yıldızlı Sorular Havuzu"
    elif ozel_havuz == "hatalar":
        cursor.execute("""
            SELECT s.* FROM sorular s
            JOIN performans p ON s.id = p.soru_id
            WHERE p.son_durum = 'YANLIS'
        """)
        aktif_ders_adi = "🎯 Yanlışlar & Telafi Havuzu"
    elif ders == "HEPSI":
        cursor.execute("SELECT * FROM sorular")
        aktif_ders_adi = "Tüm Dersler (Karışık)"
    else:
        if unite_secim == "VIZE":
            cursor.execute("""
                SELECT * FROM sorular 
                WHERE TRIM(ders_adi) LIKE ? AND (unite_no BETWEEN 1 AND 7 OR unite_no = 0)
            """, (f"%{ders}%",))
            aktif_ders_adi = f"{ders} (Vize Konuları)"
        elif unite_secim.startswith("UNITE_"):
            u_no = int(unite_secim.replace("UNITE_", ""))
            cursor.execute("""
                SELECT * FROM sorular 
                WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
            """, (f"%{ders}%", u_no))
            aktif_ders_adi = f"{ders} (Ünite {u_no})"
        else:
            cursor.execute("""
                SELECT * FROM sorular 
                WHERE TRIM(ders_adi) LIKE ?
            """, (f"%{ders}%",))
            aktif_ders_adi = ders

    satirlar = cursor.fetchall()
    conn.close()

    if not satirlar and ders != "HEPSI":
        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sorular WHERE TRIM(ders_adi) LIKE ?", (f"%{ders}%",))
        satirlar = cursor.fetchall()
        conn.close()
        aktif_ders_adi = ders

    if not satirlar:
        session["bildirim"] = {"tur": "warning", "metin": "Seçilen kritere ait soru bulunamadı."}
        return redirect(url_for("ana_sayfa"))

    tum_sorular = [dict(row) for row in satirlar]
    random.shuffle(tum_sorular)
    secilen_sorular = tum_sorular[:limit] if (limit > 0 and len(tum_sorular) > limit) else tum_sorular

    sinav_oturumunu_temizle()

    session["sorular"] = secilen_sorular
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
    sorular = session.get("sorular", [])
    indeks = session.get("mevcut_indeks", 0)
    aktif_ders = session.get("aktif_ders", "Genel Sınav")
    mod = session.get("sinav_modu", "sinav")
    kalan_sure = request.args.get("kalan_sure")

    if not sorular:
        return redirect(url_for("ana_sayfa"))

    if indeks >= len(sorular):
        return redirect(url_for("sonuc_goruntule"))

    soru = sorular[indeks]

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT yildizli, kullanici_notu, unite_no FROM sorular WHERE id = ?", (soru["id"],))
    row = cursor.fetchone()
    if row:
        soru["yildizli"] = row["yildizli"]
        soru["kullanici_notu"] = row["kullanici_notu"] or ""
        soru["unite_no"] = row["unite_no"] or 0
    conn.close()

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
            "soru": soru,
            "secilen": secilen if secilen else "Boş",
            "dogru": dogru,
            "durum": durum
        })
        session["cevaplar"] = cevap_listesi
        session["mevcut_indeks"] = indeks + 1

        if mod == "ogrenme":
            conn = veritabani_baglan()
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO performans (soru_id, dogru_sayisi, yanlis_sayisi, son_durum) VALUES (?, 0, 0, '')", (soru["id"],))
            if durum == "DOGRU":
                cursor.execute("UPDATE performans SET dogru_sayisi = dogru_sayisi + 1, son_durum = 'DOGRU' WHERE soru_id = ?", (soru["id"],))
            elif durum == "YANLIS":
                cursor.execute("UPDATE performans SET yanlis_sayisi = yanlis_sayisi + 1, son_durum = 'YANLIS' WHERE soru_id = ?", (soru["id"],))
            conn.commit()
            conn.close()

        if mod == "sinav":
            if session["mevcut_indeks"] >= len(sorular):
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
                               toplam=len(sorular))

    toplam_sure = session.get("toplam_sure_saniye", 0)
    baslangic_sure = kalan_sure if kalan_sure is not None else toplam_sure

    return render_template("index.html", 
                           durum="soru", 
                           soru=soru, 
                           sira=indeks + 1, 
                           toplam=len(sorular), 
                           aktif_ders=aktif_ders,
                           kalan_saniye=baslangic_sure,
                           mod=mod)

@app.route("/testi-bitir")
@giris_zorunlu
def testi_bitir():
    sorular = session.get("sorular", [])
    indeks = session.get("mevcut_indeks", 0)
    cevap_listesi = session.get("cevaplar", [])

    for i in range(indeks, len(sorular)):
        s = sorular[i]
        cevap_listesi.append({
            "soru": s,
            "secilen": "Boş",
            "dogru": s["dogru_cevap"],
            "durum": "BOS"
        })
        session["bos"] = session.get("bos", 0) + 1

    session["cevaplar"] = cevap_listesi
    session["mevcut_indeks"] = len(sorular)
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
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (simdi, aktif_ders, dogru, yanlis, bos, round(net, 2), round(puan, 1)))

        for c in cevaplar:
            s_id = c["soru"]["id"]
            durum = c["durum"]
            cursor.execute("INSERT OR IGNORE INTO performans (soru_id, dogru_sayisi, yanlis_sayisi, son_durum) VALUES (?, 0, 0, '')", (s_id,))
            if durum == "DOGRU":
                cursor.execute("UPDATE performans SET dogru_sayisi = dogru_sayisi + 1, son_durum = 'DOGRU' WHERE soru_id = ?", (s_id,))
            elif durum == "YANLIS":
                cursor.execute("UPDATE performans SET yanlis_sayisi = yanlis_sayisi + 1, son_durum = 'YANLIS' WHERE soru_id = ?", (s_id,))
        conn.commit()
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
    cursor.execute("SELECT yildizli FROM sorular WHERE id = ?", (soru_id,))
    row = cursor.fetchone()
    if row:
        yeni_durum = 0 if row["yildizli"] == 1 else 1
        cursor.execute("UPDATE sorular SET yildizli = ? WHERE id = ?", (yeni_durum, soru_id))
        conn.commit()
        conn.close()
        return jsonify({"basarili": True, "yildizli": yeni_durum})
    conn.close()
    return jsonify({"basarili": False}), 404

@app.route("/not-kaydet/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def not_kaydet(soru_id):
    yeni_not = request.form.get("not", "").strip()
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("UPDATE sorular SET kullanici_notu = ? WHERE id = ?", (yeni_not, soru_id))
    conn.commit()
    conn.close()
    return jsonify({"basarili": True, "not": yeni_not})

@app.route("/yazdir")
@giris_zorunlu
def sinav_yazdir():
    ders = request.args.get("ders", "HEPSI")
    limit = int(request.args.get("limit", 20))

    conn = veritabani_baglan()
    cursor = conn.cursor()
    if ders == "HEPSI":
        cursor.execute("SELECT * FROM sorular")
        aktif_ders = "Tüm Dersler (Karma Deneme Sınavı)"
    else:
        cursor.execute("SELECT * FROM sorular WHERE ders_adi = ?", (ders,))
        aktif_ders = ders

    satirlar = cursor.fetchall()
    conn.close()

    if not satirlar:
        session["bildirim"] = {"tur": "warning", "metin": "Yazdırılacak soru bulunamadı."}
        return redirect(url_for("ana_sayfa"))

    tum_sorular = [dict(r) for r in satirlar]
    random.shuffle(tum_sorular)
    secilen_sorular = tum_sorular[:limit] if (limit > 0 and len(tum_sorular) > limit) else tum_sorular
    return render_template("yazdir.html", sorular=secilen_sorular, aktif_ders=aktif_ders)

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
        sql += " AND (soru_metni LIKE ? OR secenek_a LIKE ? OR secenek_b LIKE ? OR secenek_c LIKE ? OR secenek_d LIKE ? OR secenek_e LIKE ? OR aciklama LIKE ? OR kullanici_notu LIKE ?)"
        for _ in range(8):
            paramlar.append(f"%{kelime}%")

    if secilen_ders:
        sql += " AND ders_adi = ?"
        paramlar.append(secilen_ders)

    sql += " ORDER BY id DESC LIMIT 50"
    cursor.execute(sql, tuple(paramlar))
    bulunan_sorular = [dict(r) for r in cursor.fetchall()]
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
            SET ders_adi = ?, soru_metni = ?, secenek_a = ?, secenek_b = ?, secenek_c = ?, secenek_d = ?, secenek_e = ?, dogru_cevap = ?, aciklama = ?, kullanici_notu = ?, unite_no = ?
            WHERE id = ?
        """, (ders, metin, a, b, c, d, e, dogru, aciklama, kullanici_notu, unite_no, soru_id))
        conn.commit()
        conn.close()
        session["bildirim"] = {"tur": "success", "metin": f"Soru #{soru_id} güncellendi."}
        return redirect(url_for("soru_yonetimi"))

    cursor.execute("SELECT * FROM sorular WHERE id = ?", (soru_id,))
    soru = cursor.fetchone()
    conn.close()
    if not soru:
        return redirect(url_for("soru_yonetimi"))
    return render_template("index.html", durum="duzenle", soru=dict(soru), dersler=GUZ_DERSLERI)

@app.route("/soru-sil/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def soru_sil(soru_id):
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sorular WHERE id = ?", (soru_id,))
    cursor.execute("DELETE FROM performans WHERE soru_id = ?", (soru_id,))
    conn.commit()
    conn.close()
    session["bildirim"] = {"tur": "info", "metin": f"Soru #{soru_id} silindi."}
    return redirect(url_for("soru_yonetimi"))

@app.route("/yedek-indir")
@giris_zorunlu
def yedek_indir():
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no FROM sorular")
    sorular = [dict(r) for r in cursor.fetchall()]
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
    if not dosya or not dosya.filename.lower().endswith(".json"):
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir .json dosyası yükleyin."}
        return redirect(url_for("ana_sayfa"))

    try:
        veri = json.load(dosya)
        conn = veritabani_baglan()
        cursor = conn.cursor()
        eklenen = 0
        for s in veri:
            cursor.execute("""
                INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s.get("ders_adi", ""), s.get("soru_metni", ""), s.get("secenek_a", ""), s.get("secenek_b", ""),
                s.get("secenek_c", ""), s.get("secenek_d", ""), s.get("secenek_e", ""), s.get("dogru_cevap", "A"),
                s.get("aciklama", ""), s.get("yildizli", 0), s.get("kullanici_notu", ""), s.get("unite_no", 0)
            ))
            eklenen += 1
        conn.commit()
        conn.close()
        session["bildirim"] = {"tur": "success", "metin": f"Yedekten {eklenen} soru başarıyla geri yüklendi."}
    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"Hata: {str(e)}"}

    return redirect(url_for("ana_sayfa"))

@app.route("/sifirla", methods=["POST"])
@giris_zorunlu
def veritabani_sifirla():
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sorular")
    cursor.execute("DELETE FROM performans")
    cursor.execute("DELETE FROM sinav_gecmisi")
    cursor.execute("DELETE FROM unite_kaynaklari")
    cursor.execute("DELETE FROM unite_takip")
    cursor.execute("DELETE FROM ders_videolari")
    cursor.execute("DELETE FROM unite_ozetleri")
    conn.commit()
    conn.close()

    session.clear()
    session["bildirim"] = {"tur": "success", "metin": "Tüm veriler, kayıtlı PDF bağlantıları, özetler ve geçmiş silindi."}
    return redirect(url_for("giris_yap"))

@app.route("/sw.js")
def service_worker():
    return send_from_directory(os.path.join(app.root_path, "static"), "sw.js", mimetype="application/javascript")

if __name__ == "__main__":
    app.run(debug=True)
