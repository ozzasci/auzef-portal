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
app.secret_key = "auzef_portal_tam_surum_2026_gizli_anahtar"[cite: 1, 4]
DB_NAME = "auzef_calisma.db"[cite: 1, 4]

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "kitaplar")[cite: 1, 4]
os.makedirs(UPLOAD_FOLDER, exist_ok=True)[cite: 1, 4]

GUZ_DERSLERI = [
    "20. Yüzyıl Türkiye’sinde Gayrimüslimler ve Kurumları",
    "Osmanlı Diplomasi Tarihi",
    "Osmanlı İktisat Tarihi",
    "Osmanlı Tarihi (1789-1908)",
    "Osmanlı Teşkilatı ve Kültür Tarihi",
    "Sömürgecilik Tarihi"
][cite: 1, 4]

UNITE_BASLIKLARI = {i: f"{i}. Ünite" for i in range(1, 15)}[cite: 1, 4]

def veritabani_baglan():
    conn = sqlite3.connect(DB_NAME, timeout=30.0)[cite: 1, 4]
    conn.row_factory = sqlite3.Row[cite: 1, 4]
    return conn[cite: 1, 4]

def veritabani_hazirla():
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_adi TEXT UNIQUE,
            ad_soyad TEXT,
            sifre_hash TEXT,
            kayit_tarihi TEXT
        )
    """)[cite: 1, 4]

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
    """)[cite: 1, 4]

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
    """)[cite: 1, 4]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS performans (
            soru_id INTEGER PRIMARY KEY,
            dogru_sayisi INTEGER DEFAULT 0,
            yanlis_sayisi INTEGER DEFAULT 0,
            son_durum TEXT DEFAULT ''
        )
    """)[cite: 1, 4]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_kaynaklari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            kaynak_turu TEXT,
            dosya_yolu TEXT
        )
    """)[cite: 1, 4]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_takip (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            okundu INTEGER DEFAULT 0,
            izlendi INTEGER DEFAULT 0
        )
    """)[cite: 1, 4]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ders_videolari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            video_url TEXT
        )
    """)[cite: 1, 4]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_ozetleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            madde TEXT
        )
    """)[cite: 4]
    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]

veritabani_hazirla()[cite: 1, 4]

def giris_zorunlu(f):
    @wraps(f)[cite: 1, 4]
    def wrap(*args, **kwargs):
        if "kullanici_id" not in session:[cite: 1, 4]
            return redirect(url_for("giris_yap"))[cite: 1, 4]
        return f(*args, **kwargs)[cite: 1, 4]
    return wrap[cite: 1, 4]

def sinav_oturumunu_temizle():
    anahtarlar = [
        "sorular", "aktif_ders", "sinav_modu", "mevcut_indeks", 
        "cevaplar", "dogru", "yanlis", "bos", "toplam_sure_saniye"
    ][cite: 1, 4]
    for key in anahtarlar:[cite: 1, 4]
        session.pop(key, None)[cite: 1, 4]

def drive_id_yakala(link):
    if not link:
        return None
    dosya_id = re.search(r'/d/([a-zA-Z0-9_-]+)', link)[cite: 4]
    if dosya_id:
        return dosya_id.group(1)[cite: 4]
    id_param = re.search(r'id=([a-zA-Z0-9_-]+)', link)[cite: 4]
    if id_param:
        return id_param.group(1)[cite: 4]
    return None

def drive_link_donustur(link):
    dosya_id = drive_id_yakala(link)[cite: 4]
    if dosya_id:
        return f"https://drive.google.com/file/d/{dosya_id}/view?usp=sharing"[cite: 4]
    return link[cite: 4]

def auzef_harfsiz_ve_harfli_soru_ayikla(metin, unite_no=1):
    temiz = re.sub(r'about:blank\s*\d+/\d+', '', metin)[cite: 1, 4]
    temiz = re.sub(r'\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{1,2}', '', temiz)[cite: 1, 4]
    temiz = re.sub(r'Ders:\s*.*?(?:\n|\|)', '', temiz, flags=re.IGNORECASE)[cite: 1, 4]
    temiz = re.sub(r'Ünite:\s*.*?\n', '', temiz, flags=re.IGNORECASE)[cite: 1, 4]

    bloklar = re.split(r'(?:^|\n)\s*Soru\s*[-–—:]*\s*(\d{1,2})\s*:', temiz, flags=re.IGNORECASE)[cite: 1, 4]
    sorular = [][cite: 1, 4]
    if len(bloklar) > 1:[cite: 1, 4]
        for i in range(1, len(bloklar), 2):[cite: 1, 4]
            s_no = bloklar[i].strip()[cite: 1, 4]
            icerik = bloklar[i+1].strip()[cite: 1, 4]

            cevap_ara = re.search(r'(?:Cevap\s*[-–—:]*\s*\d{0,2}\s*:|Doğru\s*Cevap\s*:)\s*([^\n\r]+)', icerik, flags=re.IGNORECASE)[cite: 1, 4]
            cevap_metni = cevap_ara.group(1).strip() if cevap_ara else ""[cite: 1, 4]

            govde = icerik[:cevap_ara.start()].strip() if cevap_ara else icerik[cite: 1, 4]
            govde = re.sub(r'\(Çoktan Seçmeli\)', '', govde, flags=re.IGNORECASE).strip()[cite: 1, 4]

            satirlar = [s.strip() for s in govde.split("\n") if s.strip()][cite: 1, 4]
            if not satirlar:[cite: 1, 4]
                continue[cite: 1, 4]

            if len(satirlar) >= 6 and not re.match(r'^\(?[A-Ea-e]\)?', satirlar[-1]):[cite: 1, 4]
                sec_e, sec_d, sec_c, sec_b, sec_a = satirlar[-1], satirlar[-2], satirlar[-3], satirlar[-4], satirlar[-5][cite: 1, 4]
                soru_kok = " ".join(satirlar[:-5])[cite: 1, 4]
            else:
                sec_a_m = re.search(r'(?:\(A\)|A\)|A\.-)\s*(.*?)(?=(?:\([B-E]\)|[B-E]\)|[B-E]\.-))', govde, re.DOTALL)[cite: 1, 4]
                sec_b_m = re.search(r'(?:\(B\)|B\)|B\.-)\s*(.*?)(?=(?:\([C-E]\)|[C-E]\)|[C-E]\.-))', govde, re.DOTALL)[cite: 1, 4]
                sec_c_m = re.search(r'(?:\(C\)|C\)|C\.-)\s*(.*?)(?=(?:\([D-E]\)|[D-E]\)|[D-E]\.-))', govde, re.DOTALL)[cite: 1, 4]
                sec_d_m = re.search(r'(?:\(D\)|D\)|D\.-)\s*(.*?)(?=(?:\(E\)|E\)|E\.-|\Z))', govde, re.DOTALL)[cite: 1, 4]
                sec_e_m = re.search(r'(?:\(E\)|E\)|E\.-)\s*(.*?)$', govde, re.DOTALL)[cite: 1, 4]

                if sec_a_m and sec_b_m and sec_c_m:[cite: 1, 4]
                    soru_kok = govde[:sec_a_m.start()].strip()[cite: 1, 4]
                    sec_a = sec_a_m.group(1).strip()[cite: 1, 4]
                    sec_b = sec_b_m.group(1).strip()[cite: 1, 4]
                    sec_c = sec_c_m.group(1).strip()[cite: 1, 4]
                    sec_d = sec_d_m.group(1).strip() if sec_d_m else "-"[cite: 1, 4]
                    sec_e = sec_e_m.group(1).strip() if sec_e_m else "-"[cite: 1, 4]
                else:
                    soru_kok = satirlar[0][cite: 1, 4]
                    sec_a = satirlar[1] if len(satirlar) > 1 else "-"[cite: 1, 4]
                    sec_b = satirlar[2] if len(satirlar) > 2 else "-"[cite: 1, 4]
                    sec_c = satirlar[3] if len(satirlar) > 3 else "-"[cite: 1, 4]
                    sec_d = satirlar[4] if len(satirlar) > 4 else "-"[cite: 1, 4]
                    sec_e = satirlar[5] if len(satirlar) > 5 else "-"[cite: 1, 4]

            val_a, val_b, val_c, val_d, val_e = " ".join(sec_a.split()), " ".join(sec_b.split()), " ".join(sec_c.split()), " ".join(sec_d.split()), " ".join(sec_e.split())[cite: 1, 4]
            dogru_harf = "A"[cite: 1, 4]
            c_clean = " ".join(cevap_metni.split()).lower()[cite: 1, 4]
            tek_harf = re.search(r'^[A-Ea-e]$', c_clean.strip())[cite: 1, 4]
            if tek_harf:[cite: 1, 4]
                dogru_harf = tek_harf.group(0).upper()[cite: 1, 4]
            else:
                for harf, val in [("A", val_a), ("B", val_b), ("C", val_c), ("D", val_d), ("E", val_e)]:[cite: 1, 4]
                    if val != "-" and (val.lower() == c_clean or val.lower() in c_clean or c_clean in val.lower()):[cite: 1, 4]
                        dogru_harf = harf[cite: 1, 4]
                        break[cite: 1, 4]

            sorular.append({
                "unite_no": unite_no,
                "metin": " ".join(soru_kok.split()),
                "a": val_a, "b": val_b, "c": val_c, "d": val_d, "e": val_e,
                "dogru_cevap": dogru_harf,
                "aciklama": f"Ünite {unite_no} Soru {s_no}. Doğru Cevap: {dogru_harf}"
            })[cite: 1, 4]
    return sorular[cite: 1, 4]

def klavuz_pdf_ayikla(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))[cite: 4]
    tam_metin = ""[cite: 4]
    for page in reader.pages:[cite: 4]
        y = page.extract_text()[cite: 4]
        if y:[cite: 4]
            tam_metin += y + "\n"[cite: 4]

    satirlar = [s.strip() for s in tam_metin.split("\n") if s.strip()][cite: 4]
    unite_verileri = {}[cite: 4]
    mevcut_unite = 1[cite: 4]

    for satir in satirlar:[cite: 4]
        if "FAITH S. AKADEMİ" in satir or "TELEGRAM" in satir or "KILAVUZU" in satir:[cite: 2, 4]
            continue[cite: 4]
        
        unite_baslik = re.match(r'^(\d{1,2})\.\s+[A-ZÇĞİÖŞÜ\s]{3,}', satir)[cite: 4]
        if unite_baslik:[cite: 4]
            no = int(unite_baslik.group(1))[cite: 4]
            if 1 <= no <= 14:[cite: 4]
                mevcut_unite = no[cite: 4]
                if mevcut_unite not in unite_verileri:[cite: 4]
                    unite_verileri[mevcut_unite] = [][cite: 4]
                continue[cite: 4]

        if len(satir) > 15:[cite: 4]
            if mevcut_unite not in unite_verileri:[cite: 4]
                unite_verileri[mevcut_unite] = [][cite: 4]
            unite_verileri[mevcut_unite].append(satir)[cite: 4]

    return unite_verileri[cite: 4]

@app.route("/giris", methods=["GET", "POST"])
def giris_yap():
    if "kullanici_id" in session:[cite: 1, 4]
        return redirect(url_for("ana_sayfa"))[cite: 1, 4]

    if request.method == "POST":[cite: 1, 4]
        kullanici_adi = request.form.get("kullanici_adi", "").strip().lower()[cite: 1, 4]
        sifre = request.form.get("sifre", "")[cite: 1, 4]

        conn = veritabani_baglan()[cite: 1, 4]
        cursor = conn.cursor()[cite: 1, 4]
        cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = ?", (kullanici_adi,))[cite: 1, 4]
        kullanici = cursor.fetchone()[cite: 1, 4]
        conn.close()[cite: 1, 4]

        if kullanici and check_password_hash(kullanici["sifre_hash"], sifre):[cite: 1, 4]
            session["kullanici_id"] = kullanici["id"][cite: 1, 4]
            session["kullanici_adi"] = kullanici["kullanici_adi"][cite: 1, 4]
            session["ad_soyad"] = kullanici["ad_soyad"][cite: 1, 4]
            return redirect(url_for("ana_sayfa"))[cite: 1, 4]
        else:
            session["bildirim"] = {"tur": "danger", "metin": "Kullanıcı adı veya şifre hatalı."}[cite: 1, 4]
            return redirect(url_for("giris_yap"))[cite: 1, 4]

    mesaj = session.pop("bildirim", None)[cite: 1, 4]
    return render_template("index.html", durum="giris", bildirim=mesaj)[cite: 1, 4]

@app.route("/kayit", methods=["GET", "POST"])
def kayit_ol():
    if "kullanici_id" in session:[cite: 1, 4]
        return redirect(url_for("ana_sayfa"))[cite: 1, 4]

    if request.method == "POST":[cite: 1, 4]
        kullanici_adi = request.form.get("kullanici_adi", "").strip().lower()[cite: 1, 4]
        ad_soyad = request.form.get("ad_soyad", "").strip()[cite: 1, 4]
        sifre = request.form.get("sifre", "")[cite: 1, 4]

        if len(kullanici_adi) < 3 or len(sifre) < 4:[cite: 1, 4]
            session["bildirim"] = {"tur": "danger", "metin": "Kullanıcı adı en az 3, şifre en az 4 karakter olmalıdır."}[cite: 1, 4]
            return redirect(url_for("kayit_ol"))[cite: 1, 4]

        conn = veritabani_baglan()[cite: 1, 4]
        cursor = conn.cursor()[cite: 1, 4]
        cursor.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = ?", (kullanici_adi,))[cite: 1, 4]
        if cursor.fetchone():[cite: 1, 4]
            conn.close()[cite: 1, 4]
            session["bildirim"] = {"tur": "warning", "metin": "Bu kullanıcı adı zaten alınmış."}[cite: 1, 4]
            return redirect(url_for("kayit_ol"))[cite: 1, 4]

        sifre_hash = generate_password_hash(sifre)[cite: 1, 4]
        simdi = datetime.now().strftime("%d.%m.%Y %H:%M")[cite: 1, 4]
        cursor.execute("""
            INSERT INTO kullanicilar (kullanici_adi, ad_soyad, sifre_hash, kayit_tarihi)
            VALUES (?, ?, ?, ?)
        """, (kullanici_adi, ad_soyad, sifre_hash, simdi))[cite: 1, 4]
        conn.commit()[cite: 1, 4]
        conn.close()[cite: 1, 4]

        session["bildirim"] = {"tur": "success", "metin": "Kayıt başarılı! Şimdi giriş yapabilirsiniz."}[cite: 1, 4]
        return redirect(url_for("giris_yap"))[cite: 1, 4]

    mesaj = session.pop("bildirim", None)[cite: 1, 4]
    return render_template("index.html", durum="kayit", bildirim=mesaj)[cite: 1, 4]

@app.route("/cikis")
def cikis_yap():
    session.clear()[cite: 1, 4]
    return redirect(url_for("giris_yap"))[cite: 1, 4]

@app.route("/")
@giris_zorunlu
def ana_sayfa():
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("SELECT ders_adi, COUNT(*) as soru_sayisi FROM sorular GROUP BY ders_adi")[cite: 1, 4]
    dersler = cursor.fetchall()[cite: 1, 4]
    cursor.execute("SELECT COUNT(*) FROM sorular")[cite: 1, 4]
    toplam_soru = cursor.fetchone()[0][cite: 1, 4]

    cursor.execute("SELECT COUNT(*) FROM sorular WHERE yildizli = 1")[cite: 1, 4]
    yildizli_soru_sayisi = cursor.fetchone()[0][cite: 1, 4]

    cursor.execute("""
        SELECT COUNT(*) FROM sorular s
        JOIN performans p ON s.id = p.soru_id
        WHERE p.son_durum = 'YANLIS'
    """)[cite: 1, 4]
    hatali_soru_sayisi = cursor.fetchone()[0][cite: 1, 4]
    conn.close()[cite: 1, 4]

    mesaj = session.pop("bildirim", None)[cite: 1, 4]
    return render_template("index.html", 
                           durum="baslangic", 
                           dersler=dersler, 
                           toplam_soru=toplam_soru, 
                           yildizli_sayisi=yildizli_soru_sayisi,
                           hatali_sayisi=hatali_soru_sayisi,
                           bildirim=mesaj)[cite: 1, 4]

@app.route("/icerik-merkezi")
@giris_zorunlu
def icerik_merkezi():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()[cite: 1, 4]
    return render_template("index.html", durum="icerik_merkezi", aktif_ders=secilen_ders, dersler=GUZ_DERSLERI)[cite: 1, 4]

@app.route("/otomatik-klavuz-isle", methods=["POST"])
@giris_zorunlu
def otomatik_klavuz_isle():
    ders = request.form.get("ders_adi", "").strip()[cite: 4]
    drive_link = request.form.get("drive_url", "").strip()[cite: 4]
    yuklenen_dosya = request.files.get("klavuz_dosya")[cite: 4]

    pdf_bytes = None[cite: 4]

    if drive_link:[cite: 4]
        dosya_id = drive_id_yakala(drive_link)[cite: 4]
        if not dosya_id:[cite: 4]
            session["bildirim"] = {"tur": "danger", "metin": "Geçersiz Google Drive bağlantısı."}[cite: 4]
            return redirect(url_for("icerik_merkezi", ders=ders))[cite: 4]

        indirme_url = f"https://drive.google.com/uc?export=download&id={dosya_id}"[cite: 4]
        try:
            req = urllib.request.Request(indirme_url, headers={'User-Agent': 'Mozilla/5.0'})[cite: 4]
            with urllib.request.urlopen(req, timeout=20) as response:[cite: 4]
                pdf_bytes = response.read()[cite: 4]
        except Exception as e:
            session["bildirim"] = {"tur": "danger", "metin": f"Drive'dan dosya çekilemedi: {str(e)}. Linkin 'Bağlantıya sahip olan herkes görüntüleyebilir' olduğundan emin olun."}[cite: 4]
            return redirect(url_for("icerik_merkezi", ders=ders))[cite: 4]

    elif yuklenen_dosya and yuklenen_dosya.filename.lower().endswith(".pdf"):[cite: 4]
        pdf_bytes = yuklenen_dosya.read()[cite: 4]

    else:
        session["bildirim"] = {"tur": "warning", "metin": "Lütfen bir Drive linki yapıştırın veya PDF yükleyin."}[cite: 4]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 4]

    try:
        ayiklanan_uniteler = klavuz_pdf_ayikla(pdf_bytes)[cite: 4]
        if not ayiklanan_uniteler:[cite: 4]
            session["bildirim"] = {"tur": "warning", "metin": "PDF okundu fakat kılavuz formatına uygun ünite maddeleri algılanamadı."}[cite: 4]
            return redirect(url_for("icerik_merkezi", ders=ders))[cite: 4]

        conn = veritabani_baglan()[cite: 4]
        cursor = conn.cursor()[cite: 4]
        cursor.execute("DELETE FROM unite_ozetleri WHERE TRIM(ders_adi) LIKE ?", (f"%{ders}%",))[cite: 4]

        toplam_eklenen = 0[cite: 4]
        for u_no, maddeler in ayiklanan_uniteler.items():[cite: 4]
            for m in maddeler:[cite: 4]
                cursor.execute("INSERT INTO unite_ozetleri (ders_adi, unite_no, madde) VALUES (?, ?, ?)", (ders, u_no, m))[cite: 4]
                toplam_eklenen += 1[cite: 4]

        conn.commit()[cite: 4]
        conn.close()[cite: 4]

        session["bildirim"] = {"tur": "success", "metin": f"Harika! '{ders}' için {len(ayiklanan_uniteler)} ünite ve toplam {toplam_eklenen} hap bilgi başarıyla aktarıldı."}
        return redirect(url_for("ders_calis", ders=ders, unite=1))[cite: 4]

    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"Ayrıştırma hatası: {str(e)}"}[cite: 4]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 4]

@app.route("/yukle-pdf-dosya", methods=["POST"])
@giris_zorunlu
def yukle_pdf_dosya():
    ders = request.form.get("ders_adi", "").strip()[cite: 1, 4]
    unite_no = int(request.form.get("unite_no", 1))[cite: 1, 4]
    dosya = request.files.get("pdf_dosya")[cite: 1, 4]

    if not dosya or not dosya.filename.lower().endswith(".pdf"):[cite: 1, 4]
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir .pdf dosyası seçin."}[cite: 1, 4]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 1, 4]

    dosya_adi = f"{abs(hash(ders))}_{unite_no}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"[cite: 1, 4]
    hedef_yol = os.path.join(UPLOAD_FOLDER, dosya_adi)[cite: 1, 4]
    dosya.save(hedef_yol)[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("DELETE FROM unite_kaynaklari WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))[cite: 1, 4]
    cursor.execute("""
        INSERT INTO unite_kaynaklari (ders_adi, unite_no, kaynak_turu, dosya_yolu)
        VALUES (?, ?, 'yerel', ?)
    """, (ders, unite_no, f"/static/kitaplar/{dosya_adi}"))[cite: 1, 4]
    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' dersinin {unite_no}. Ünite PDF'i başarıyla yüklendi!"}[cite: 1, 4]
    return redirect(url_for("ders_calis", ders=ders, unite=unite_no))[cite: 1, 4]

@app.route("/kaydet-drive-link", methods=["POST"])
@giris_zorunlu
def kaydet_drive_link():
    ders = request.form.get("ders_adi", "").strip()[cite: 1, 4]
    unite_no = int(request.form.get("unite_no", 1))[cite: 1, 4]
    raw_link = request.form.get("drive_url", "").strip()[cite: 1, 4]

    if not raw_link:[cite: 1, 4]
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir Google Drive bağlantısı yapıştırın."}[cite: 1, 4]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 1, 4]

    preview_link = drive_link_donustur(raw_link)[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("DELETE FROM unite_kaynaklari WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))[cite: 1, 4]
    cursor.execute("""
        INSERT INTO unite_kaynaklari (ders_adi, unite_no, kaynak_turu, dosya_yolu)
        VALUES (?, ?, 'drive', ?)
    """, (ders, unite_no, preview_link))[cite: 1, 4]
    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' - Ünite {unite_no} için Google Drive PDF kaynağı bağlandı!"}[cite: 1, 4]
    return redirect(url_for("ders_calis", ders=ders, unite=unite_no))[cite: 1, 4]

@app.route("/yukle-unite-sorulari", methods=["POST"])
@giris_zorunlu
def yukle_unite_sorulari():
    ders = request.form.get("ders_adi", "").strip()[cite: 1, 4]
    unite_no = int(request.form.get("unite_no", 1))[cite: 1, 4]
    dosya = request.files.get("soru_dosyasi")[cite: 1, 4]

    if not dosya or not dosya.filename.lower().endswith(".pdf"):[cite: 1, 4]
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen soru PDF'i seçin."}[cite: 1, 4]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 1, 4]

    metin = ""[cite: 1, 4]
    try:
        reader = PdfReader(io.BytesIO(dosya.read()))[cite: 1, 4]
        for page in reader.pages:[cite: 1, 4]
            y = page.extract_text()[cite: 1, 4]
            if y:[cite: 1, 4]
                metin += y + "\n"[cite: 1, 4]
    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"PDF okunamadı: {str(e)}"}[cite: 1, 4]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 1, 4]

    sorular = auzef_harfsiz_ve_harfli_soru_ayikla(metin, unite_no)[cite: 1, 4]
    if not sorular:[cite: 1, 4]
        session["bildirim"] = {"tur": "warning", "metin": f"PDF okundu ancak {unite_no}. üniteye ait sorular algılanamadı."}[cite: 1, 4]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("DELETE FROM sorular WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))[cite: 1, 4]

    for s in sorular:[cite: 1, 4]
        cursor.execute("""
            INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?)
        """, (ders, s["metin"], s["a"], s["b"], s["c"], s["d"], s["e"], s["dogru_cevap"], s["aciklama"], unite_no))[cite: 1, 4]

    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]

    session["bildirim"] = {"tur": "success", "metin": f"Tebrikler! {ders} - Ünite {unite_no} için {len(sorular)} soru aktarıldı."}[cite: 1, 4]
    return redirect(url_for("unite_pekistirme_listesi", ders=ders))[cite: 1, 4]

@app.route("/hizli-soru-ekle", methods=["POST"])
@giris_zorunlu
def hizli_soru_ekle():
    ders = request.form.get("ders_adi", "").strip()[cite: 1, 4]
    unite_no = int(request.form.get("unite_no", 1))[cite: 1, 4]
    ham_metin = request.form.get("soru_metinleri", "")[cite: 1, 4]

    if not ham_metin.strip():[cite: 1, 4]
        session["bildirim"] = {"tur": "warning", "metin": "Lütfen soru metinlerini yapıştırın."}[cite: 1, 4]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 1, 4]

    sorular = auzef_harfsiz_ve_harfli_soru_ayikla(ham_metin, unite_no)[cite: 1, 4]
    if not sorular:[cite: 1, 4]
        session["bildirim"] = {"tur": "danger", "metin": "Metin çözümlenemedi. Lütfen formatı kontrol edin."}[cite: 1, 4]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("DELETE FROM sorular WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))[cite: 1, 4]
    for s in sorular:[cite: 1, 4]
        cursor.execute("""
            INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?)
        """, (ders, s["metin"], s["a"], s["b"], s["c"], s["d"], s["e"], s["dogru_cevap"], s["aciklama"], unite_no))[cite: 1, 4]
    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' - Ünite {unite_no} için {len(sorular)} soru başarıyla kaydedildi."}[cite: 1, 4]
    return redirect(url_for("unite_pekistirme_listesi", ders=ders))[cite: 1, 4]

@app.route("/ders-calis")
@giris_zorunlu
def ders_calis():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()[cite: 1, 4]
    secilen_unite = int(request.args.get("unite", 1))[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]

    cursor.execute("""
        SELECT kaynak_turu, dosya_yolu FROM unite_kaynaklari 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))[cite: 1, 4]
    row_kaynak = cursor.fetchone()[cite: 1, 4]
    
    pdf_url = row_kaynak["dosya_yolu"] if row_kaynak else ""[cite: 1, 4]
    kaynak_turu = row_kaynak["kaynak_turu"] if row_kaynak else ""[cite: 1, 4]

    cursor.execute("""
        SELECT video_url FROM ders_videolari 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))[cite: 1, 4]
    row_video = cursor.fetchone()[cite: 1, 4]
    video_url = row_video["video_url"] if row_video else ""[cite: 1, 4]

    cursor.execute("""
        SELECT unite_no, okundu, izlendi FROM unite_takip 
        WHERE TRIM(ders_adi) LIKE ?
    """, (f"%{secilen_ders}%",))[cite: 1, 4]
    takip_verileri = {r["unite_no"]: {"okundu": r["okundu"], "izlendi": r["izlendi"]} for r in cursor.fetchall()}[cite: 1, 4]

    cursor.execute("""
        SELECT madde FROM unite_ozetleri 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))[cite: 4]
    ozet_maddeleri = [r["madde"] for r in cursor.fetchall()][cite: 4]

    conn.close()[cite: 1, 4]

    embed_url = ""[cite: 1, 4]
    if video_url:[cite: 1, 4]
        if "watch?v=" in video_url:[cite: 1, 4]
            embed_url = video_url.replace("watch?v=", "embed/")[cite: 1, 4]
        elif "youtu.be/" in video_url:[cite: 1, 4]
            embed_url = video_url.replace("youtu.be/", "www.youtube.com/embed/")[cite: 1, 4]
        else:
            embed_url = video_url[cite: 1, 4]

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
                           dersler=GUZ_DERSLERI)[cite: 1, 4]

@app.route("/hafiza-kartlari")
@giris_zorunlu
def hafiza_kartlari():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()[cite: 4]
    secilen_unite = int(request.args.get("unite", 1))[cite: 4]

    conn = veritabani_baglan()[cite: 4]
    cursor = conn.cursor()[cite: 4]
    cursor.execute("""
        SELECT madde FROM unite_ozetleri 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))[cite: 4]
    satirlar = cursor.fetchall()[cite: 4]
    conn.close()[cite: 4]

    kartlar = [][cite: 4]
    for s in satirlar:[cite: 4]
        metin = s["madde"][cite: 4]
        if " denilirdi" in metin or " denirdi" in metin or " adı verilmektedir" in metin:[cite: 4]
            parcalar = re.split(r' (?:denilirdi|denirdi|adı verilmektedir)', metin)[cite: 4]
            on_yuz = parcalar[0] + " ne olarak adlandırılırdı?"[cite: 4]
            arka_yuz = metin[cite: 4]
        elif " idi" in metin or " olmuştur" in metin:[cite: 4]
            on_yuz = metin.split(" ")[0] + " ile ilgili temel hüküm nedir?"[cite: 4]
            arka_yuz = metin[cite: 4]
        else:
            on_yuz = f"📌 {secilen_unite}. Ünite Kritik Notu"[cite: 4]
            arka_yuz = metin[cite: 4]
        kartlar.append({"on": on_yuz, "arka": arka_yuz})[cite: 4]

    random.shuffle(kartlar)[cite: 4]
    return render_template("index.html",
                           durum="flashcards",
                           aktif_ders=secilen_ders,
                           aktif_unite=secilen_unite,
                           kartlar=kartlar,
                           dersler=GUZ_DERSLERI)[cite: 4]

@app.route("/unite-durum-guncelle", methods=["POST"])
@giris_zorunlu
def unite_durum_guncelle():
    ders = request.form.get("ders")[cite: 1, 4]
    unite = int(request.form.get("unite"))[cite: 1, 4]
    tur = request.form.get("tur")[cite: 1, 4]
    deger = int(request.form.get("deger"))[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("SELECT id FROM unite_takip WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite))[cite: 1, 4]
    kayit = cursor.fetchone()[cite: 1, 4]
    if kayit:[cite: 1, 4]
        cursor.execute(f"UPDATE unite_takip SET {tur} = ? WHERE id = ?", (deger, kayit["id"]))[cite: 1, 4]
    else:
        cursor.execute(f"INSERT INTO unite_takip (ders_adi, unite_no, {tur}) VALUES (?, ?, ?)", (ders, unite, deger))[cite: 1, 4]
    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]
    return jsonify({"basarili": True})[cite: 1, 4]

@app.route("/video-kaydet", methods=["POST"])
@giris_zorunlu
def video_kaydet():
    ders = request.form.get("ders")[cite: 1, 4]
    unite = int(request.form.get("unite"))[cite: 1, 4]
    url = request.form.get("video_url", "").strip()[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("DELETE FROM ders_videolari WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite))[cite: 1, 4]
    cursor.execute("""
        INSERT INTO ders_videolari (ders_adi, unite_no, video_url) 
        VALUES (?, ?, ?)
    """, (ders, unite, url))[cite: 1, 4]
    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]
    return redirect(url_for("ders_calis", ders=ders, unite=unite))[cite: 1, 4]

@app.route("/unite-pekistirme")
@giris_zorunlu
def unite_pekistirme_listesi():
    ders = request.args.get("ders", "").strip()[cite: 1, 4]
    if not ders and GUZ_DERSLERI:[cite: 1, 4]
        ders = GUZ_DERSLERI[0][cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("""
        SELECT unite_no, COUNT(*) as adet 
        FROM sorular 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no > 0
        GROUP BY unite_no
        ORDER BY unite_no ASC
    """, (f"%{ders}%",))[cite: 1, 4]
    sayilar = {row["unite_no"]: row["adet"] for row in cursor.fetchall()}[cite: 1, 4]
    conn.close()[cite: 1, 4]

    uniteler = [][cite: 1, 4]
    for i in range(1, 15):[cite: 1, 4]
        uniteler.append({
            "no": i,
            "baslik": f"Ünite {i}",
            "soru_sayisi": sayilar.get(i, 0),
            "ders_adi": ders
        })[cite: 1, 4]

    return render_template("index.html", 
                           durum="unite_pekistirme", 
                           uniteler=uniteler, 
                           aktif_ders=ders, 
                           dersler=GUZ_DERSLERI)[cite: 1, 4]

@app.route("/unite-test-baslat/<int:unite_no>")
@giris_zorunlu
def unite_test_baslat(unite_no):
    ders = request.args.get("ders", "").strip()[cite: 1, 4]
    if not ders and GUZ_DERSLERI:[cite: 1, 4]
        ders = GUZ_DERSLERI[0][cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("""
        SELECT * FROM sorular 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
        ORDER BY id ASC
    """, (f"%{ders}%", unite_no))[cite: 1, 4]
    satirlar = cursor.fetchall()[cite: 1, 4]
    conn.close()[cite: 1, 4]

    if not satirlar:[cite: 1, 4]
        session["bildirim"] = {"tur": "warning", "metin": f"'{ders}' dersinin {unite_no}. ünitesine ait soru bulunamadı. Lütfen 'İçerik Yükle' alanından soru PDF'ini yükleyin."}[cite: 1, 4]
        return redirect(url_for("unite_pekistirme_listesi", ders=ders))[cite: 1, 4]

    sorular = [dict(r) for r in satirlar][cite: 1, 4]
    sinav_oturumunu_temizle()[cite: 1, 4]

    session["sorular"] = sorular[cite: 1, 4]
    session["aktif_ders"] = f"{ders} (Ünite {unite_no} Pekiştirme)"[cite: 1, 4]
    session["sinav_modu"] = "ogrenme"[cite: 1, 4]
    session["mevcut_indeks"] = 0[cite: 1, 4]
    session["cevaplar"] = [][cite: 1, 4]
    session["dogru"] = 0[cite: 1, 4]
    session["yanlis"] = 0[cite: 1, 4]
    session["bos"] = 0[cite: 1, 4]
    session["toplam_sure_saniye"] = 0[cite: 1, 4]

    return redirect(url_for("soru_goruntule"))[cite: 1, 4]

@app.route("/kronoloji")
@giris_zorunlu
def kronoloji_egzersizi():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()[cite: 1, 4]
    
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("""
        SELECT id, soru_metni, aciklama, dogru_cevap, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e 
        FROM sorular 
        WHERE TRIM(ders_adi) LIKE ?
    """, (f"%{secilen_ders}%",))[cite: 1, 4]
    satirlar = cursor.fetchall()[cite: 1, 4]
    conn.close()[cite: 1, 4]

    otomatik_olaylar = [][cite: 1, 4]
    gorulen_yillar = set()[cite: 1, 4]

    for s in satirlar:[cite: 1, 4]
        metin_havuzu = f"{s['soru_metni']} {s['aciklama']}"[cite: 1, 4]
        yillar = re.findall(r'\b(1[3-9]\d{2})\b', metin_havuzu)[cite: 1, 4]
        
        if yillar:[cite: 1, 4]
            yil = int(yillar[0])[cite: 1, 4]
            if yil not in gorulen_yillar:[cite: 1, 4]
                gorulen_yillar.add(yil)[cite: 1, 4]
                olay_metni = s['soru_metni'][cite: 1, 4]
                if len(olay_metni) > 130:[cite: 1, 4]
                    olay_metni = olay_metni[:127] + "..."[cite: 1, 4]
                
                otomatik_olaylar.append({
                    "id": s["id"],
                    "yil": yil,
                    "olay": olay_metni,
                    "detay": f"Doğru Cevap: {s['dogru_cevap']} | {s['aciklama'][:90]}..." if s['aciklama'] else f"Doğru Seçenek: {s['dogru_cevap']}"
                })[cite: 1, 4]
        
        if len(otomatik_olaylar) >= 6:[cite: 1, 4]
            break[cite: 1, 4]

    if len(otomatik_olaylar) < 3:[cite: 1, 4]
        karisik_olaylar = [
            {"id": 1, "yil": 1453, "olay": "İstanbul'un fethi sonrası Gennadios'un Rum Patriği seçilmesi", "detay": "Fatih Sultan Mehmet dönemi."},
            {"id": 2, "yil": 1461, "olay": "Episkopos Hovagim'in İstanbul Ermeni Patriği tayin edilmesi", "detay": "Fatih Sultan Mehmet dönemi."},
            {"id": 3, "yil": 1492, "olay": "Sefarad Yahudilerinin Osmanlı topraklarına gelişi", "detay": "II. Bayezid dönemi."},
            {"id": 4, "yil": 1602, "olay": "Fener Rum Patrikhanesi'nin Aya Yorgi'ye taşınması", "detay": "Patrikhane merkezi."},
            {"id": 5, "yil": 1835, "olay": "Hahambaşılık makamına yeniden resmi berat verilmesi", "detay": "II. Mahmud dönemi."},
            {"id": 6, "yil": 1856, "olay": "Islahat Fermanı ile millet nizamnamelerinin başlaması", "detay": "Tanzimat dönemi."}
        ][cite: 1, 4]
        uyari_mesaji = "Bu dersin soru havuzunda yeterli tarihli veri bulunamadığı için genel tarih seti yüklendi."[cite: 1, 4]
    else:
        karisik_olaylar = list(otomatik_olaylar)[cite: 1, 4]
        uyari_mesaji = None[cite: 1, 4]

    random.shuffle(karisik_olaylar)[cite: 1, 4]

    return render_template("index.html",
                           durum="kronoloji",
                           aktif_ders=secilen_ders,
                           karisik_olaylar=karisik_olaylar,
                           uyari_mesaji=uyari_mesaji,
                           dersler=GUZ_DERSLERI)[cite: 1, 4]

@app.route("/sinav-baslat", methods=["POST"])
@giris_zorunlu
def sinav_baslat():
    ders = request.form.get("ders", "HEPSI").strip()[cite: 1, 4]
    unite_secim = request.form.get("unite", "TUMU").strip()[cite: 1, 4]
    sure_dakika = int(request.form.get("sure", 0))[cite: 1, 4]
    mod = request.form.get("mod", "sinav")[cite: 1, 4]
    limit = int(request.form.get("limit", 20))[cite: 1, 4]
    ozel_havuz = request.form.get("ozel_havuz", "")[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]

    if ozel_havuz == "yildizli":[cite: 1, 4]
        cursor.execute("SELECT * FROM sorular WHERE yildizli = 1")[cite: 1, 4]
        aktif_ders_adi = "⭐ Yıldızlı Sorular Havuzu"[cite: 1, 4]
    elif ozel_havuz == "hatalar":[cite: 1, 4]
        cursor.execute("""
            SELECT s.* FROM sorular s
            JOIN performans p ON s.id = p.soru_id
            WHERE p.son_durum = 'YANLIS'
        """)[cite: 1, 4]
        aktif_ders_adi = "🎯 Yanlışlar & Telafi Havuzu"[cite: 1, 4]
    elif ders == "HEPSI":[cite: 1, 4]
        cursor.execute("SELECT * FROM sorular")[cite: 1, 4]
        aktif_ders_adi = "Tüm Dersler (Karışık)"[cite: 1, 4]
    else:
        if unite_secim == "VIZE":[cite: 1, 4]
            cursor.execute("""
                SELECT * FROM sorular 
                WHERE TRIM(ders_adi) LIKE ? AND (unite_no BETWEEN 1 AND 7 OR unite_no = 0)
            """, (f"%{ders}%",))[cite: 1, 4]
            aktif_ders_adi = f"{ders} (Vize Konuları)"[cite: 1, 4]
        elif unite_secim.startswith("UNITE_"):[cite: 1, 4]
            u_no = int(unite_secim.replace("UNITE_", ""))[cite: 1, 4]
            cursor.execute("""
                SELECT * FROM sorular 
                WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
            """, (f"%{ders}%", u_no))[cite: 1, 4]
            aktif_ders_adi = f"{ders} (Ünite {u_no})"[cite: 1, 4]
        else:
            cursor.execute("""
                SELECT * FROM sorular 
                WHERE TRIM(ders_adi) LIKE ?
            """, (f"%{ders}%",))[cite: 1, 4]
            aktif_ders_adi = ders[cite: 1, 4]

    satirlar = cursor.fetchall()[cite: 1, 4]
    conn.close()[cite: 1, 4]

    if not satirlar and ders != "HEPSI":[cite: 1, 4]
        conn = veritabani_baglan()[cite: 1, 4]
        cursor = conn.cursor()[cite: 1, 4]
        cursor.execute("SELECT * FROM sorular WHERE TRIM(ders_adi) LIKE ?", (f"%{ders}%",))[cite: 1, 4]
        satirlar = cursor.fetchall()[cite: 1, 4]
        conn.close()[cite: 1, 4]
        aktif_ders_adi = ders[cite: 1, 4]

    if not satirlar:[cite: 1, 4]
        session["bildirim"] = {"tur": "warning", "metin": "Seçilen kritere ait soru bulunamadı."}[cite: 1, 4]
        return redirect(url_for("ana_sayfa"))[cite: 1, 4]

    tum_sorular = [dict(row) for row in satirlar][cite: 1, 4]
    random.shuffle(tum_sorular)[cite: 1, 4]
    secilen_sorular = tum_sorular[:limit] if (limit > 0 and len(tum_sorular) > limit) else tum_sorular[cite: 1, 4]

    sinav_oturumunu_temizle()[cite: 1, 4]

    session["sorular"] = secilen_sorular[cite: 1, 4]
    session["aktif_ders"] = aktif_ders_adi[cite: 1, 4]
    session["sinav_modu"] = mod[cite: 1, 4]
    session["mevcut_indeks"] = 0[cite: 1, 4]
    session["cevaplar"] = [][cite: 1, 4]
    session["dogru"] = 0[cite: 1, 4]
    session["yanlis"] = 0[cite: 1, 4]
    session["bos"] = 0[cite: 1, 4]
    session["toplam_sure_saniye"] = sure_dakika * 60[cite: 1, 4]

    return redirect(url_for("soru_goruntule"))[cite: 1, 4]

@app.route("/soru", methods=["GET", "POST"])
@giris_zorunlu
def soru_goruntule():
    sorular = session.get("sorular", [])[cite: 1, 4]
    indeks = session.get("mevcut_indeks", 0)[cite: 1, 4]
    aktif_ders = session.get("aktif_ders", "Genel Sınav")[cite: 1, 4]
    mod = session.get("sinav_modu", "sinav")[cite: 1, 4]
    kalan_sure = request.args.get("kalan_sure")[cite: 1, 4]

    if not sorular:[cite: 1, 4]
        return redirect(url_for("ana_sayfa"))[cite: 1, 4]

    if indeks >= len(sorular):[cite: 1, 4]
        return redirect(url_for("sonuc_goruntule"))[cite: 1, 4]

    soru = sorular[indeks][cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("SELECT yildizli, kullanici_notu, unite_no FROM sorular WHERE id = ?", (soru["id"],))[cite: 1, 4]
    row = cursor.fetchone()[cite: 1, 4]
    if row:[cite: 1, 4]
        soru["yildizli"] = row["yildizli"][cite: 1, 4]
        soru["kullanici_notu"] = row["kullanici_notu"] or ""[cite: 1, 4]
        soru["unite_no"] = row["unite_no"] or 0[cite: 1, 4]
    conn.close()[cite: 1, 4]

    if request.method == "POST":[cite: 1, 4]
        secilen = request.form.get("secenek", "")[cite: 1, 4]
        kalan_saniye = request.form.get("kalan_saniye")[cite: 1, 4]
        dogru = soru["dogru_cevap"][cite: 1, 4]

        if not secilen:[cite: 1, 4]
            durum = "BOS"[cite: 1, 4]
            session["bos"] = session.get("bos", 0) + 1[cite: 1, 4]
        elif secilen == dogru:[cite: 1, 4]
            durum = "DOGRU"[cite: 1, 4]
            session["dogru"] = session.get("dogru", 0) + 1[cite: 1, 4]
        else:
            durum = "YANLIS"[cite: 1, 4]
            session["yanlis"] = session.get("yanlis", 0) + 1[cite: 1, 4]

        cevap_listesi = session.get("cevaplar", [])[cite: 1, 4]
        cevap_listesi.append({
            "soru": soru,
            "secilen": secilen if secilen else "Boş",
            "dogru": dogru,
            "durum": durum
        })[cite: 1, 4]
        session["cevaplar"] = cevap_listesi[cite: 1, 4]
        session["mevcut_indeks"] = indeks + 1[cite: 1, 4]

        if mod == "ogrenme":[cite: 1, 4]
            conn = veritabani_baglan()[cite: 1, 4]
            cursor = conn.cursor()[cite: 1, 4]
            cursor.execute("INSERT OR IGNORE INTO performans (soru_id, dogru_sayisi, yanlis_sayisi, son_durum) VALUES (?, 0, 0, '')", (soru["id"],))[cite: 1, 4]
            if durum == "DOGRU":[cite: 1, 4]
                cursor.execute("UPDATE performans SET dogru_sayisi = dogru_sayisi + 1, son_durum = 'DOGRU' WHERE soru_id = ?", (soru["id"],))[cite: 1, 4]
            elif durum == "YANLIS":[cite: 1, 4]
                cursor.execute("UPDATE performans SET yanlis_sayisi = yanlis_sayisi + 1, son_durum = 'YANLIS' WHERE soru_id = ?", (soru["id"],))[cite: 1, 4]
            conn.commit()[cite: 1, 4]
            conn.close()[cite: 1, 4]

        if mod == "sinav":[cite: 1, 4]
            if session["mevcut_indeks"] >= len(sorular):[cite: 1, 4]
                return redirect(url_for("sonuc_goruntule"))[cite: 1, 4]
            return redirect(url_for("soru_goruntule", kalan_sure=kalan_saniye))[cite: 1, 4]

        return render_template("index.html", 
                               durum="geribildirim", 
                               soru=soru, 
                               secilen=secilen, 
                               sonuc=durum, 
                               aktif_ders=aktif_ders,
                               kalan_saniye=kalan_saniye,
                               sira=indeks + 1,
                               toplam=len(sorular))[cite: 1, 4]

    toplam_sure = session.get("toplam_sure_saniye", 0)[cite: 1, 4]
    baslangic_sure = kalan_sure if kalan_sure is not None else toplam_sure[cite: 1, 4]

    return render_template("index.html", 
                           durum="soru", 
                           soru=soru, 
                           sira=indeks + 1, 
                           toplam=len(sorular), 
                           aktif_ders=aktif_ders,
                           kalan_saniye=baslangic_sure,
                           mod=mod)[cite: 1, 4]

@app.route("/testi-bitir")
@giris_zorunlu
def testi_bitir():
    sorular = session.get("sorular", [])[cite: 1, 4]
    indeks = session.get("mevcut_indeks", 0)[cite: 1, 4]
    cevap_listesi = session.get("cevaplar", [])[cite: 1, 4]

    for i in range(indeks, len(sorular)):[cite: 1, 4]
        s = sorular[i][cite: 1, 4]
        cevap_listesi.append({
            "soru": s,
            "secilen": "Boş",
            "dogru": s["dogru_cevap"],
            "durum": "BOS"
        })[cite: 1, 4]
        session["bos"] = session.get("bos", 0) + 1[cite: 1, 4]

    session["cevaplar"] = cevap_listesi[cite: 1, 4]
    session["mevcut_indeks"] = len(sorular)[cite: 1, 4]
    return redirect(url_for("sonuc_goruntule"))[cite: 1, 4]

@app.route("/sonuc")
@giris_zorunlu
def sonuc_goruntule():
    dogru = session.get("dogru", 0)[cite: 1, 4]
    yanlis = session.get("yanlis", 0)[cite: 1, 4]
    bos = session.get("bos", 0)[cite: 1, 4]
    aktif_ders = session.get("aktif_ders", "Genel Sınav")[cite: 1, 4]
    mod = session.get("sinav_modu", "sinav")[cite: 1, 4]
    cevaplar = session.get("cevaplar", [])[cite: 1, 4]
    toplam = dogru + yanlis + bos[cite: 1, 4]

    net = dogru - (yanlis * 0.25)[cite: 1, 4]
    puan = max(0, (net / toplam) * 100) if toplam > 0 else 0[cite: 1, 4]

    try:
        conn = veritabani_baglan()[cite: 1, 4]
        cursor = conn.cursor()[cite: 1, 4]
        simdi = datetime.now().strftime("%d.%m.%Y %H:%M")[cite: 1, 4]
        cursor.execute("""
            INSERT INTO sinav_gecmisi (tarih, ders_adi, dogru, yanlis, bos, net, puan)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (simdi, aktif_ders, dogru, yanlis, bos, round(net, 2), round(puan, 1)))[cite: 1, 4]

        for c in cevaplar:[cite: 1, 4]
            s_id = c["soru"]["id"][cite: 1, 4]
            durum = c["durum"][cite: 1, 4]
            cursor.execute("INSERT OR IGNORE INTO performans (soru_id, dogru_sayisi, yanlis_sayisi, son_durum) VALUES (?, 0, 0, '')", (s_id,))[cite: 1, 4]
            if durum == "DOGRU":[cite: 1, 4]
                cursor.execute("UPDATE performans SET dogru_sayisi = dogru_sayisi + 1, son_durum = 'DOGRU' WHERE soru_id = ?", (s_id,))[cite: 1, 4]
            elif durum == "YANLIS":[cite: 1, 4]
                cursor.execute("UPDATE performans SET yanlis_sayisi = yanlis_sayisi + 1, son_durum = 'YANLIS' WHERE soru_id = ?", (s_id,))[cite: 1, 4]
        conn.commit()[cite: 1, 4]
        conn.close()[cite: 1, 4]
    except Exception:
        pass[cite: 1, 4]

    return render_template("index.html", 
                           durum="sonuc", 
                           dogru=dogru, 
                           yanlis=yanlis, 
                           bos=bos, 
                           net=round(net, 2), 
                           puan=round(puan, 1), 
                           aktif_ders=aktif_ders,
                           mod=mod,
                           cevaplar=cevaplar)[cite: 1, 4]

@app.route("/istatistik")
@giris_zorunlu
def istatistik_paneli():
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]

    cursor.execute("""
        SELECT 
            s.ders_adi,
            COUNT(p.soru_id) as cozulen_soru,
            SUM(p.dogru_sayisi) as toplam_dogru,
            SUM(p.yanlis_sayisi) as toplam_yanlis
        FROM sorular s
        INNER JOIN performans p ON s.id = p.soru_id
        GROUP BY s.ders_adi
    """)[cite: 1, 4]
    veriler = cursor.fetchall()[cite: 1, 4]

    rapor = [][cite: 1, 4]
    toplam_genel_cozulen, toplam_genel_dogru, toplam_genel_yanlis = 0, 0, 0[cite: 1, 4]

    for row in veriler:[cite: 1, 4]
        d_adi = row["ders_adi"][cite: 1, 4]
        d = row["toplam_dogru"] or 0[cite: 1, 4]
        y = row["toplam_yanlis"] or 0[cite: 1, 4]
        cozulen = d + y[cite: 1, 4]
        net = d - (y * 0.25)[cite: 1, 4]
        oran = round((d / cozulen) * 100, 1) if cozulen > 0 else 0[cite: 1, 4]

        toplam_genel_cozulen += cozulen[cite: 1, 4]
        toplam_genel_dogru += d[cite: 1, 4]
        toplam_genel_yanlis += y[cite: 1, 4]

        rapor.append({
            "ders_adi": d_adi, "cozulen": cozulen, "dogru": d, "yanlis": y, "net": round(net, 2), "oran": oran
        })[cite: 1, 4]

    genel_net = toplam_genel_dogru - (toplam_genel_yanlis * 0.25)[cite: 1, 4]
    genel_oran = round((toplam_genel_dogru / toplam_genel_cozulen) * 100, 1) if toplam_genel_cozulen > 0 else 0[cite: 1, 4]

    cursor.execute("SELECT * FROM sinav_gecmisi ORDER BY id DESC LIMIT 15")[cite: 1, 4]
    gecmis_sinavlar = [dict(row) for row in cursor.fetchall()][cite: 1, 4]
    conn.close()[cite: 1, 4]

    return render_template("index.html", 
                           durum="istatistik", 
                           rapor=rapor, 
                           toplam_cozulen=toplam_genel_cozulen,
                           genel_net=round(genel_net, 2),
                           genel_oran=genel_oran,
                           gecmis_sinavlar=gecmis_sinavlar)[cite: 1, 4]

@app.route("/yildiz-degistir/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def yildiz_degistir(soru_id):
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("SELECT yildizli FROM sorular WHERE id = ?", (soru_id,))[cite: 1, 4]
    row = cursor.fetchone()[cite: 1, 4]
    if row:[cite: 1, 4]
        yeni_durum = 0 if row["yildizli"] == 1 else 1[cite: 1, 4]
        cursor.execute("UPDATE sorular SET yildizli = ? WHERE id = ?", (yeni_durum, soru_id))[cite: 1, 4]
        conn.commit()[cite: 1, 4]
        conn.close()[cite: 1, 4]
        return jsonify({"basarili": True, "yildizli": yeni_durum})[cite: 1, 4]
    conn.close()[cite: 1, 4]
    return jsonify({"basarili": False}), 404[cite: 1, 4]

@app.route("/not-kaydet/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def not_kaydet(soru_id):
    yeni_not = request.form.get("not", "").strip()[cite: 1, 4]
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("UPDATE sorular SET kullanici_notu = ? WHERE id = ?", (yeni_not, soru_id))[cite: 1, 4]
    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]
    return jsonify({"basarili": True, "not": yeni_not})[cite: 1, 4]

@app.route("/yazdir")
@giris_zorunlu
def sinav_yazdir():
    ders = request.args.get("ders", "HEPSI")[cite: 1, 4]
    limit = int(request.args.get("limit", 20))[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    if ders == "HEPSI":[cite: 1, 4]
        cursor.execute("SELECT * FROM sorular")[cite: 1, 4]
        aktif_ders = "Tüm Dersler (Karma Deneme Sınavı)"[cite: 1, 4]
    else:
        cursor.execute("SELECT * FROM sorular WHERE ders_adi = ?", (ders,))[cite: 1, 4]
        aktif_ders = ders[cite: 1, 4]

    satirlar = cursor.fetchall()[cite: 1, 4]
    conn.close()[cite: 1, 4]

    if not satirlar:[cite: 1, 4]
        session["bildirim"] = {"tur": "warning", "metin": "Yazdırılacak soru bulunamadı."}[cite: 1, 4]
        return redirect(url_for("ana_sayfa"))[cite: 1, 4]

    tum_sorular = [dict(r) for r in satirlar][cite: 1, 4]
    random.shuffle(tum_sorular)[cite: 1, 4]
    secilen_sorular = tum_sorular[:limit] if (limit > 0 and len(tum_sorular) > limit) else tum_sorular[cite: 1, 4]
    return render_template("yazdir.html", sorular=secilen_sorular, aktif_ders=aktif_ders)[cite: 1, 4]

@app.route("/yonetim", methods=["GET"])
@giris_zorunlu
def soru_yonetimi():
    kelime = request.args.get("kelime", "").strip()[cite: 1, 4]
    secilen_ders = request.args.get("ders", "")[cite: 1, 4]

    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    sql = "SELECT * FROM sorular WHERE 1=1"[cite: 1, 4]
    paramlar = [][cite: 1, 4]

    if kelime:[cite: 1, 4]
        sql += " AND (soru_metni LIKE ? OR secenek_a LIKE ? OR secenek_b LIKE ? OR secenek_c LIKE ? OR secenek_d LIKE ? OR secenek_e LIKE ? OR aciklama LIKE ? OR kullanici_notu LIKE ?)"[cite: 1, 4]
        for _ in range(8):[cite: 1, 4]
            paramlar.append(f"%{kelime}%")[cite: 1, 4]

    if secilen_ders:[cite: 1, 4]
        sql += " AND ders_adi = ?"[cite: 1, 4]
        paramlar.append(secilen_ders)[cite: 1, 4]

    sql += " ORDER BY id DESC LIMIT 50"[cite: 1, 4]
    cursor.execute(sql, tuple(paramlar))[cite: 1, 4]
    bulunan_sorular = [dict(r) for r in cursor.fetchall()][cite: 1, 4]
    conn.close()[cite: 1, 4]

    return render_template("index.html", durum="yonetim", sorular=bulunan_sorular, kelime=kelime, secilen_ders=secilen_ders, dersler=GUZ_DERSLERI)[cite: 1, 4]

@app.route("/soru-duzenle/<int:soru_id>", methods=["GET", "POST"])
@giris_zorunlu
def soru_duzenle(soru_id):
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]

    if request.method == "POST":[cite: 1, 4]
        ders = request.form.get("ders_adi")[cite: 1, 4]
        metin = request.form.get("soru_metni")[cite: 1, 4]
        a = request.form.get("secenek_a")[cite: 1, 4]
        b = request.form.get("secenek_b")[cite: 1, 4]
        c = request.form.get("secenek_c")[cite: 1, 4]
        d = request.form.get("secenek_d")[cite: 1, 4]
        e = request.form.get("secenek_e")[cite: 1, 4]
        dogru = request.form.get("dogru_cevap")[cite: 1, 4]
        aciklama = request.form.get("aciklama")[cite: 1, 4]
        kullanici_notu = request.form.get("kullanici_notu", "")[cite: 1, 4]
        unite_no = int(request.form.get("unite_no", 0))[cite: 1, 4]

        cursor.execute("""
            UPDATE sorular 
            SET ders_adi = ?, soru_metni = ?, secenek_a = ?, secenek_b = ?, secenek_c = ?, secenek_d = ?, secenek_e = ?, dogru_cevap = ?, aciklama = ?, kullanici_notu = ?, unite_no = ?
            WHERE id = ?
        """, (ders, metin, a, b, c, d, e, dogru, aciklama, kullanici_notu, unite_no, soru_id))[cite: 1, 4]
        conn.commit()[cite: 1, 4]
        conn.close()[cite: 1, 4]
        session["bildirim"] = {"tur": "success", "metin": f"Soru #{soru_id} güncellendi."}[cite: 1, 4]
        return redirect(url_for("soru_yonetimi"))[cite: 1, 4]

    cursor.execute("SELECT * FROM sorular WHERE id = ?", (soru_id,))[cite: 1, 4]
    soru = cursor.fetchone()[cite: 1, 4]
    conn.close()[cite: 1, 4]
    if not soru:[cite: 1, 4]
        return redirect(url_for("soru_yonetimi"))[cite: 1, 4]
    return render_template("index.html", durum="duzenle", soru=dict(soru), dersler=GUZ_DERSLERI)[cite: 1, 4]

@app.route("/soru-sil/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def soru_sil(soru_id):
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("DELETE FROM sorular WHERE id = ?", (soru_id,))[cite: 1, 4]
    cursor.execute("DELETE FROM performans WHERE soru_id = ?", (soru_id,))[cite: 1, 4]
    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]
    session["bildirim"] = {"tur": "info", "metin": f"Soru #{soru_id} silindi."}[cite: 1, 4]
    return redirect(url_for("soru_yonetimi"))[cite: 1, 4]

@app.route("/yedek-indir")
@giris_zorunlu
def yedek_indir():
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("SELECT ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no FROM sorular")[cite: 1, 4]
    sorular = [dict(r) for r in cursor.fetchall()][cite: 1, 4]
    conn.close()[cite: 1, 4]

    dosya_metni = json.dumps(sorular, ensure_ascii=False, indent=2)[cite: 1, 4]
    tarih_etiketi = datetime.now().strftime("%Y%m%d_%H%M")[cite: 1, 4]
    return Response(
        dosya_metni,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=auzef_soru_yedegi_{tarih_etiketi}.json"}
    )[cite: 1, 4]

@app.route("/yedek-yukle", methods=["POST"])
@giris_zorunlu
def yedek_yukle():
    dosya = request.files.get("yedek_dosyasi")[cite: 1, 4]
    if not dosya or not dosya.filename.lower().endswith(".json"):[cite: 1, 4]
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir .json dosyası yükleyin."}[cite: 1, 4]
        return redirect(url_for("ana_sayfa"))[cite: 1, 4]

    try:
        veri = json.load(dosya)[cite: 1, 4]
        conn = veritabani_baglan()[cite: 1, 4]
        cursor = conn.cursor()[cite: 1, 4]
        eklenen = 0[cite: 1, 4]
        for s in veri:[cite: 1, 4]
            cursor.execute("""
                INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s.get("ders_adi", ""), s.get("soru_metni", ""), s.get("secenek_a", ""), s.get("secenek_b", ""),
                s.get("secenek_c", ""), s.get("secenek_d", ""), s.get("secenek_e", ""), s.get("dogru_cevap", "A"),
                s.get("aciklama", ""), s.get("yildizli", 0), s.get("kullanici_notu", ""), s.get("unite_no", 0)
            ))[cite: 1, 4]
            eklenen += 1[cite: 1, 4]
        conn.commit()[cite: 1, 4]
        conn.close()[cite: 1, 4]
        session["bildirim"] = {"tur": "success", "metin": f"Yedekten {eklenen} soru başarıyla geri yüklendi."}[cite: 1, 4]
    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"Hata: {str(e)}"}[cite: 1, 4]

    return redirect(url_for("ana_sayfa"))[cite: 1, 4]

@app.route("/sifirla", methods=["POST"])
@giris_zorunlu
def veritabani_sifirla():
    conn = veritabani_baglan()[cite: 1, 4]
    cursor = conn.cursor()[cite: 1, 4]
    cursor.execute("DELETE FROM sorular")[cite: 1, 4]
    cursor.execute("DELETE FROM performans")[cite: 1, 4]
    cursor.execute("DELETE FROM sinav_gecmisi")[cite: 1, 4]
    cursor.execute("DELETE FROM unite_kaynaklari")[cite: 1, 4]
    cursor.execute("DELETE FROM unite_takip")[cite: 1, 4]
    cursor.execute("DELETE FROM ders_videolari")[cite: 1, 4]
    cursor.execute("DELETE FROM unite_ozetleri")[cite: 4]
    conn.commit()[cite: 1, 4]
    conn.close()[cite: 1, 4]

    session.clear()[cite: 1, 4]
    session["bildirim"] = {"tur": "success", "metin": "Tüm veriler, kayıtlı PDF bağlantıları, özetler ve geçmiş silindi."}[cite: 4]
    return redirect(url_for("giris_yap"))[cite: 1, 4]

@app.route("/sw.js")
def service_worker():
    return send_from_directory(os.path.join(app.root_path, "static"), "sw.js", mimetype="application/javascript")[cite: 1, 4]

if __name__ == "__main__":
    app.run(debug=True)[cite: 1, 4]
