import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
import io
import json
import random
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from pypdf import PdfReader

app = Flask(__name__)
app.secret_key = "auzef_portal_tam_surum_2026_gizli_anahtar"

DATABASE_URL = "postgres://postgres.luvrwqfypquitdyqqpao:1O2g3z1o2g3z@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

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
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def veritabani_hazirla():
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS kullanicilar (id SERIAL PRIMARY KEY, kullanici_adi TEXT UNIQUE, ad_soyad TEXT, sifre_hash TEXT, kayit_tarihi TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS sorular (id SERIAL PRIMARY KEY, ders_adi TEXT, soru_metni TEXT, secenek_a TEXT, secenek_b TEXT, secenek_c TEXT, secenek_d TEXT, secenek_e TEXT, dogru_cevap TEXT, aciklama TEXT, yildizli INTEGER DEFAULT 0, kullanici_notu TEXT DEFAULT '', unite_no INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS sinav_gecmisi (id SERIAL PRIMARY KEY, tarih TEXT, ders_adi TEXT, dogru INTEGER, yanlis INTEGER, bos INTEGER, net REAL, puan REAL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS performans (soru_id INTEGER PRIMARY KEY, dogru_sayisi INTEGER DEFAULT 0, yanlis_sayisi INTEGER DEFAULT 0, son_durum TEXT DEFAULT '')")
    cursor.execute("CREATE TABLE IF NOT EXISTS unite_kaynaklari (id SERIAL PRIMARY KEY, ders_adi TEXT, unite_no INTEGER, kaynak_turu TEXT, dosya_yolu TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS unite_takip (id SERIAL PRIMARY KEY, ders_adi TEXT, unite_no INTEGER, okundu INTEGER DEFAULT 0, izlendi INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS unite_ozetleri (id SERIAL PRIMARY KEY, ders_adi TEXT, unite_no INTEGER, madde TEXT)")
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
    for key in ["soru_idleri", "aktif_ders", "sinav_modu", "mevcut_indeks", "dogru", "yanlis", "bos"]:
        session.pop(key, None)

@app.route("/giris", methods=["GET", "POST"])
def giris_yap():
    if request.method == "POST":
        k_adi = request.form.get("kullanici_adi", "").strip().lower()
        sifre = request.form.get("sifre", "")
        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = %s", (k_adi,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user and check_password_hash(user["sifre_hash"], sifre):
            session["kullanici_id"] = user["id"]
            session["ad_soyad"] = user["ad_soyad"]
            return redirect(url_for("ana_sayfa"))
        session["bildirim"] = {"tur": "danger", "metin": "Hatalı giriş."}
    return render_template("index.html", durum="giris")

@app.route("/kayit", methods=["GET", "POST"])
def kayit_ol():
    if request.method == "POST":
        k_adi = request.form.get("kullanici_adi", "").strip().lower()
        ad_soyad = request.form.get("ad_soyad", "").strip()
        sifre = request.form.get("sifre", "")
        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO kullanicilar (kullanici_adi, ad_soyad, sifre_hash, kayit_tarihi) VALUES (%s, %s, %s, %s)", 
                       (k_adi, ad_soyad, generate_password_hash(sifre), datetime.now().strftime("%d.%m.%Y")))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for("giris_yap"))
    return render_template("index.html", durum="kayit")

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
    db_dersler = {row["ders_adi"]: row["soru_sayisi"] for row in cursor.fetchall()}
    dersler = [{"ders_adi": d, "soru_sayisi": db_dersler.get(d, 0)} for d in GUZ_DERSLERI]
    cursor.execute("SELECT COUNT(*) FROM sorular")
    toplam_soru = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) FROM sorular WHERE yildizli = 1")
    yildizli_sayisi = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) FROM sorular s JOIN performans p ON s.id = p.soru_id WHERE p.son_durum = 'YANLIS'")
    hatali_sayisi = cursor.fetchone()["count"]
    cursor.close()
    conn.close()
    return render_template("index.html", durum="baslangic", dersler=dersler, toplam_soru=toplam_soru, yildizli_sayisi=yildizli_sayisi, hatali_sayisi=hatali_sayisi)

# AYRI ÇIKMIŞ SORULAR SAYFASI
@app.route("/cikmis-sorular-sayfasi")
@giris_zorunlu
def cikmis_sorular_sayfasi():
    return render_template("index.html", durum="cikmis_sorular", dersler=GUZ_DERSLERI)

@app.route("/icerik-merkezi")
@giris_zorunlu
def icerik_merkezi():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    return render_template("index.html", durum="icerik_merkezi", aktif_ders=secilen_ders, dersler=GUZ_DERSLERI)

# ÇIKMIŞ SORULARIN KOYU ŞIKLARINI OKUYAN AYRIŞTIRICI
def auzef_cikmis_soru_ayikla(metin, unite_no=1):
    temiz = re.sub(r'about:blank\s*\d*/?\d*', '', metin)
    bloklar = re.split(r'(?:^|\n)\s*([1-9][0-9]?)\.\s+', temiz)
    sorular = []

    for i in range(1, len(bloklar), 2):
        if i + 1 >= len(bloklar):
            break
        icerik = bloklar[i+1].strip()
        secenekler = re.findall(r'([A-E])\)\s*(.*?)(?=(?:[A-E]\)|$|\n\s*[1-9][0-9]?\.))', icerik, re.DOTALL)
        if len(secenekler) < 4:
            continue
            
        ilk_sik_idx = icerik.find('A)')
        if ilk_sik_idx == -1:
            continue
        soru_kok = re.sub(r'\n', ' ', icerik[:ilk_sik_idx]).strip()

        s_dict = {}
        for harf, met in secenekler:
            s_dict[harf] = met.strip().replace('\n', ' ')

        dogru_harf = "A"
        for harf in ['A', 'B', 'C', 'D', 'E']:
            if f"**{harf}**" in icerik or f"\n{harf}\n" in icerik:
                dogru_harf = harf
                break

        sorular.append({
            "unite_no": unite_no,
            "metin": soru_kok,
            "a": s_dict.get('A', ''),
            "b": s_dict.get('B', ''),
            "c": s_dict.get('C', ''),
            "d": s_dict.get('D', ''),
            "e": s_dict.get('E', ''),
            "dogru_cevap": dogru_harf,
            "aciklama": "Geçmiş Yıl Çıkmış Soru Çözüm Havuzu"
        })
    return sorular

@app.route("/yukle-unite-sorulari", methods=["POST"])
@giris_zorunlu
def yukle_unite_sorulari():
    ders = request.form.get("ders_adi", "").strip()
    unite_no = int(request.form.get("unite_no", 1))
    dosya = request.files.get("soru_dosyasi")

    if not dosya or not dosya.filename.lower().endswith(".pdf"):
        return redirect(url_for("icerik_merkezi", ders=ders))

    pdf_bytes = dosya.read()
    metin = ""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    for page in reader.pages:
        t = page.extract_text()
        if t:
            metin += t + "\n"

    sorular = auzef_cikmis_soru_ayikla(metin, unite_no)
    
    conn = veritabani_baglan()
    cursor = conn.cursor()
    for s in sorular:
        cursor.execute("INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, unite_no) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", 
                       (ders, s["metin"], s["a"], s["b"], s["c"], s["d"], s["e"], s["dogru_cevap"], s["aciklama"], unite_no))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for("cikmis_sorular_sayfasi"))

@app.route("/sinav-baslat", methods=["POST"])
@giris_zorunlu
def sinav_baslat():
    ders = request.form.get("ders", "HEPSI").strip()
    unite_secim = request.form.get("unite", "TUMU").strip()
    mod = request.form.get("mod", "sinav")
    ozel_havuz = request.form.get("ozel_havuz", "")

    conn = veritabani_baglan()
    cursor = conn.cursor()

    if ozel_havuz == "cikmis_sorular":
        if unite_secim == "VIZE":
            cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s AND (unite_no BETWEEN 1 AND 7 OR unite_no = 0)", (f"%{ders}%",))
        elif unite_secim == "FINAL":
            cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s AND (unite_no BETWEEN 8 AND 14)", (f"%{ders}%",))
        else:
            cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s", (f"%{ders}%",))
    else:
        cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s", (f"%{ders}%",))

    satirlar = cursor.fetchall()
    cursor.close()
    conn.close()

    if not satirlar:
        session["bildirim"] = {"tur": "warning", "metin": "Seçilen kritere uygun çıkmış soru bulunamadı. Lütfen İçerik Merkezi'nden soru PDF'i yükleyin."}
        return redirect(url_for("cikmis_sorular_sayfasi"))

    id_listesi = [r["id"] for r in satirlar]
    random.shuffle(id_listesi)
    sinav_oturumunu_temizle()

    session["soru_idleri"] = id_listesi
    session["aktif_ders"] = f"{ders} (Çıkmış Sorular)"
    session["sinav_modu"] = mod
    session["mevcut_indeks"] = 0
    session["dogru"] = 0
    session["yanlis"] = 0
    session["bos"] = 0

    return redirect(url_for("soru_goruntule"))

@app.route("/soru", methods=["GET", "POST"])
@giris_zorunlu
def soru_goruntule():
    s_ids = session.get("soru_idleri", [])
    idx = session.get("mevcut_indeks", 0)
    if not s_ids or idx >= len(s_ids):
        return redirect(url_for("sonuc_goruntule"))

    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sorular WHERE id = %s", (s_ids[idx],))
    soru = dict(cursor.fetchone())
    cursor.close()
    conn.close()

    if request.method == "POST":
        secilen = request.form.get("secenek", "")
        if not secilen:
            session["bos"] = session.get("bos", 0) + 1
        elif secilen == soru["dogru_cevap"]:
            session["dogru"] = session.get("dogru", 0) + 1
        else:
            session["yanlis"] = session.get("yanlis", 0) + 1
        session["mevcut_indeks"] = idx + 1
        
        if session["sinav_modu"] == "ogrenme":
            return render_template("index.html", durum="geribildirim", soru=soru)
        return redirect(url_for("soru_goruntule"))

    return render_template("index.html", durum="soru", soru=soru, sira=idx + 1, toplam=len(s_ids), aktif_ders=session.get("aktif_ders"))

@app.route("/sonuc")
@giris_zorunlu
def sonuc_goruntule():
    d = session.get("dogru", 0)
    y = session.get("yanlis", 0)
    b = session.get("bos", 0)
    toplam = d + y + b
    net = d - (y * 0.25)
    puan = max(0, (net / toplam) * 100) if toplam > 0 else 0
    return render_template("index.html", durum="sonuc", dogru=d, yanlis=y, bos=b, net=round(net, 2), puan=round(puan, 1))

@app.route("/ders-calis")
@giris_zorunlu
def ders_calis():
    return render_template("index.html", durum="ogrenme_modu", dersler=GUZ_DERSLERI, aktif_ders=GUZ_DERSLERI[0], aktif_unite=1, unite_baslik="1. Ünite")

@app.route("/kronoloji")
@giris_zorunlu
def kronoloji_egzersizi():
    return render_template("index.html", durum="kronoloji", dersler=GUZ_DERSLERI)

@app.route("/unite-pekistirme")
@giris_zorunlu
def unite_pekistirme_listesi():
    return render_template("index.html", durum="unite_pekistirme", dersler=GUZ_DERSLERI)

@app.route("/yonetim")
@giris_zorunlu
def soru_yonetimi():
    return render_template("index.html", durum="yonetim", dersler=GUZ_DERSLERI)

@app.route("/istatistik")
@giris_zorunlu
def istatistik_paneli():
    return render_template("index.html", durum="istatistik")

@app.route("/sifirla", methods=["POST"])
@giris_zorunlu
def veritabani_sifirla():
    session.clear()
    return redirect(url_for("giris_yap"))

if __name__ == "__main__":
    app.run(debug=True)
