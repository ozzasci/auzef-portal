import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
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

# Supabase PostgreSQL Bağlantı URI'si
DATABASE_URL = "postgres://postgres.luvrwqfypquitdyqqpao:VERITABANI_SIFRENIZ@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

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

def veritabani_baglan():
    # PostgreSQL (Supabase) bağlantısı
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

# Temel Rotalar ve İşlevler
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

@app.route("/sifirla", methods=["POST"])
@giris_zorunlu
def veritabani_sifirla():
    session.clear()
    session["bildirim"] = {"tur": "info", "metin": "Oturum güvenle kapatıldı. Bulut veritabanındaki tüm verileriniz eksiksiz korunmaktadır."}
    return redirect(url_for("giris_yap"))

if __name__ == "__main__":
    app.run(debug=True)
