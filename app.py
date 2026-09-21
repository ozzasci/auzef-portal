import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
import io
import json
import random
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pypdf import PdfReader

app = Flask(__name__)
app.secret_key = "auzef_portal_tam_surum_2026_gizli_anahtar"

DATABASE_URL = "postgres://postgres.luvrwqfypquitdyqqpao:1O2g3z1o2g3z@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

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

@app.route("/cikmis-sorular-sayfasi")
@giris_zorunlu
def cikmis_sorular_sayfasi():
    return render_template("index.html", durum="cikmis_sorular", dersler=GUZ_DERSLERI)

@app.route("/icerik-merkezi")
@giris_zorunlu
def icerik_merkezi():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    return render_template("index.html", durum="icerik_merkezi", aktif_ders=secilen_ders, dersler=GUZ_DERSLERI)

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
        sorular.append({"unite_no": unite_no, "metin": soru_kok, "a": s_dict.get('A', ''), "b": s_dict.get('B', ''), "c": s_dict.get('C', ''), "d": s_dict.get('D', ''), "e": s_dict.get('E', ''), "dogru_cevap": dogru_harf, "aciklama": "Çıkmış Soru Çözüm Havuzu"})
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

@app.route("/otomatik-klavuz-isle", methods=["POST"])
@giris_zorunlu
def otomatik_klavuz_isle():
    ders = request.form.get("ders_adi", "").strip()
    dosya = request.files.get("klavuz_dosya")
    if not dosya:
        return redirect(url_for("icerik_merkezi", ders=ders))
    pdf_bytes = dosya.read()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    tam_metin = ""
    for page in reader.pages:
        t = page.extract_text()
        if t: tam_metin += t + "\n"
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO unite_ozetleri (ders_adi, unite_no, madde) VALUES (%s, 1, %s)", (ders, tam_metin[:500]))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for("ders_calis", ders=ders))

@app.route("/sinav-baslat", methods=["POST"])
@giris_zorunlu
def sinav_baslat():
    ders = request.form.get("ders", "HEPSI").strip()
    unite_secim = request.form.get("unite", "TUMU").strip()
    mod = request.form.get("mod", "sinav")
    ozel_havuz = request.form.get("ozel_havuz", "")
    conn = veritabani_baglan()
    cursor = conn.cursor()
    if ozel_havuz == "yildizli":
        cursor.execute("SELECT id FROM sorular WHERE yildizli = 1")
    elif ozel_havuz == "hatalar":
        cursor.execute("SELECT s.id FROM sorular s JOIN performans p ON s.id = p.soru_id WHERE p.son_durum = 'YANLIS'")
    elif ozel_havuz == "cikmis_sorular":
        if unite_secim == "VIZE":
            cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s AND (unite_no BETWEEN 1 AND 7 OR unite_no = 0)", (f"%{ders}%",))
        elif unite_secim == "FINAL":
            cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s AND (unite_no BETWEEN 8 AND 14)", (f"%{ders}%",))
        else:
            cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s", (f"%{ders}%",))
    elif unite_secim == "VIZE":
        cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s AND (unite_no BETWEEN 1 AND 7 OR unite_no = 0)", (f"%{ders}%",))
    elif unite_secim.startswith("UNITE_"):
        u_no = int(unite_secim.replace("UNITE_", ""))
        cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s", (f"%{ders}%", u_no))
    elif ders == "HEPSI":
        cursor.execute("SELECT id FROM sorular")
    else:
        cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s", (f"%{ders}%",))
    satirlar = cursor.fetchall()
    cursor.close()
    conn.close()
    if not satirlar:
        return redirect(url_for("ana_sayfa"))
    id_listesi = [r["id"] for r in satirlar]
    random.shuffle(id_listesi)
    sinav_oturumunu_temizle()
    session["soru_idleri"] = id_listesi
    session["aktif_ders"] = f"{ders} (Sınav)"
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
        if not secilen: session["bos"] = session.get("bos", 0) + 1
        elif secilen == soru["dogru_cevap"]: session["dogru"] = session.get("dogru", 0) + 1
        else: session["yanlis"] = session.get("yanlis", 0) + 1
        session["mevcut_indeks"] = idx + 1
        if session["sinav_modu"] == "ogrenme":
            return render_template("index.html", durum="geribildirim", soru=soru)
        return redirect(url_for("soru_goruntule"))
    return render_template("index.html", durum="soru", soru=soru, sira=idx + 1, toplam=len(s_ids), aktif_ders=session.get("aktif_ders"))

@app.route("/sonuc")
@giris_zorunlu
def sonuc_goruntule():
    d = session.get("dogru", 0); y = session.get("yanlis", 0); b = session.get("bos", 0)
    toplam = d + y + b; net = d - (y * 0.25)
    return render_template("index.html", durum="sonuc", dogru=d, yanlis=y, bos=b, net=round(net, 2))

@app.route("/ders-calis")
@giris_zorunlu
def ders_calis():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    secilen_unite = int(request.args.get("unite", 1))
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT dosya_yolu FROM unite_kaynaklari WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s LIMIT 1", (f"%{secilen_ders}%", secilen_unite))
    row = cursor.fetchone()
    pdf_url = row["dosya_yolu"] if row else ""
    cursor.execute("SELECT madde FROM unite_ozetleri WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s", (f"%{secilen_ders}%", secilen_unite))
    ozetler = [r["madde"] for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return render_template("index.html", durum="ogrenme_modu", aktif_ders=secilen_ders, aktif_unite=secilen_unite, pdf_url=pdf_url, ozetler=ozetler, unite_baslik=f"{secilen_unite}. Ünite", dersler=GUZ_DERSLERI)

@app.route("/hafiza-kartlari")
@giris_zorunlu
def hafiza_kartlari():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    secilen_unite = int(request.args.get("unite", 1))
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT madde FROM unite_ozetleri WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s", (f"%{secilen_ders}%", secilen_unite))
    satirlar = cursor.fetchall()
    cursor.close()
    conn.close()
    kartlar = [{"on": f"📌 {secilen_unite}. Ünite Sınav Bilgisi", "arka": s["madde"]} for s in satirlar]
    return render_template("index.html", durum="flashcards", aktif_ders=secilen_ders, aktif_unite=secilen_unite, kartlar=kartlar, dersler=GUZ_DERSLERI)

@app.route("/kronoloji")
@giris_zorunlu
def kronoloji_egzersizi():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    karisik_olaylar = [{"yil": 1453, "olay": "İstanbul'un Fethi", "detay": "Fatih Sultan Mehmet"}, {"yil": 1461, "olay": "Trabzon'un Fethi", "detay": "Osmanlı dönemi"}]
    return render_template("index.html", durum="kronoloji", aktif_ders=secilen_ders, karisik_olaylar=karisik_olaylar, dersler=GUZ_DERSLERI)

@app.route("/unite-pekistirme")
@giris_zorunlu
def unite_pekistirme_listesi():
    ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT unite_no, COUNT(*) as adet FROM sorular WHERE TRIM(ders_adi) LIKE %s GROUP BY unite_no", (f"%{ders}%",))
    sayilar = {row["unite_no"]: row["adet"] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    uniteler = [{"no": i, "baslik": f"Ünite {i}", "soru_sayisi": sayilar.get(i, 0)} for i in range(1, 15)]
    return render_template("index.html", durum="unite_pekistirme", uniteler=uniteler, aktif_ders=ders, dersler=GUZ_DERSLERI)

@app.route("/unite-test-baslat/<int:unite_no>")
@giris_zorunlu
def unite_test_baslat(unite_no):
    ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE %s AND unite_no = %s", (f"%{ders}%", unite_no))
    satirlar = cursor.fetchall()
    cursor.close()
    conn.close()
    if not satirlar: return redirect(url_for("unite_pekistirme_listesi", ders=ders))
    id_listesi = [r["id"] for r in satirlar]
    random.shuffle(id_listesi)
    sinav_oturumunu_temizle()
    session["soru_idleri"] = id_listesi
    session["aktif_ders"] = f"{ders} (Ünite {unite_no})"
    session["sinav_modu"] = "ogrenme"
    session["mevcut_indeks"] = 0
    session["dogru"] = 0; session["yanlis"] = 0; session["bos"] = 0
    return redirect(url_for("soru_goruntule"))

@app.route("/yonetim")
@giris_zorunlu
def soru_yonetimi():
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sorular ORDER BY id DESC LIMIT 50")
    sorular = [dict(r) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return render_template("index.html", durum="yonetim", sorular=sorular, dersler=GUZ_DERSLERI)

@app.route("/istatistik")
@giris_zorunlu
def istatistik_paneli():
    conn = veritabani_baglan()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(p.soru_id) as cozulen, SUM(p.dogru_sayisi) as d, SUM(p.yanlis_sayisi) as y FROM performans p")
    row = cursor.fetchone()
    cozulen = row["cozulen"] or 0
    d = row["d"] or 0
    y = row["y"] or 0
    net = d - (y * 0.25)
    oran = round((d / cozulen) * 100, 1) if cozulen > 0 else 0
    cursor.close()
    conn.close()
    return render_template("index.html", durum="istatistik", toplam_cozulen=cozulen, genel_net=round(net, 2), genel_oran=oran, dersler=GUZ_DERSLERI)

@app.route("/sifirla", methods=["POST"])
@giris_zorunlu
def veritabani_sifirla():
    session.clear()
    return redirect(url_for("giris_yap"))

if __name__ == "__main__":
    app.run(debug=True)
