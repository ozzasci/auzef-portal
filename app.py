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
app.secret_key = "auzef_portal_tam_surum_2026_gizli_anahtar"[cite: 1]
DB_NAME = "auzef_calisma.db"[cite: 1]

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "kitaplar")[cite: 1]
os.makedirs(UPLOAD_FOLDER, exist_ok=True)[cite: 1]

GUZ_DERSLERI = [
    "20. Yüzyıl Türkiye’sinde Gayrimüslimler ve Kurumları",
    "Osmanlı Diplomasi Tarihi",
    "Osmanlı İktisat Tarihi",
    "Osmanlı Tarihi (1789-1908)",
    "Osmanlı Teşkilatı ve Kültür Tarihi",
    "Sömürgecilik Tarihi"
][cite: 1]

UNITE_BASLIKLARI = {i: f"{i}. Ünite" for i in range(1, 15)}[cite: 1]

# --- VERİTABANI BAĞLANTISI VE TABLOLAR ---

def veritabani_baglan():
    conn = sqlite3.connect(DB_NAME, timeout=30.0)[cite: 1]
    conn.row_factory = sqlite3.Row[cite: 1]
    return conn[cite: 1]

def veritabani_hazirla():
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kullanici_adi TEXT UNIQUE,
            ad_soyad TEXT,
            sifre_hash TEXT,
            kayit_tarihi TEXT
        )
    """)[cite: 1]

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
    """)[cite: 1]

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
    """)[cite: 1]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS performans (
            soru_id INTEGER PRIMARY KEY,
            dogru_sayisi INTEGER DEFAULT 0,
            yanlis_sayisi INTEGER DEFAULT 0,
            son_durum TEXT DEFAULT ''
        )
    """)[cite: 1]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_kaynaklari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            kaynak_turu TEXT,
            dosya_yolu TEXT
        )
    """)[cite: 1]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_takip (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            okundu INTEGER DEFAULT 0,
            izlendi INTEGER DEFAULT 0
        )
    """)[cite: 1]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ders_videolari (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            video_url TEXT
        )
    """)[cite: 1]

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unite_ozetleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ders_adi TEXT,
            unite_no INTEGER,
            madde TEXT
        )
    """)[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

veritabani_hazirla()[cite: 1]

# --- DEKORATÖR VE YARDIMCILAR (HATA ÖNLEMEK İÇİN EN BAŞTA) ---

def giris_zorunlu(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "kullanici_id" not in session:
            return redirect(url_for("giris_yap"))[cite: 1]
        return f(*args, **kwargs)[cite: 1]
    return wrap[cite: 1]

def sinav_oturumunu_temizle():
    anahtarlar = [
        "soru_idleri", "sorular", "aktif_ders", "sinav_modu", "mevcut_indeks", 
        "cevaplar", "dogru", "yanlis", "bos", "toplam_sure_saniye"
    ]
    for key in anahtarlar:
        session.pop(key, None)

def drive_id_yakala(link):
    if not link:
        return None[cite: 1]
    dosya_id = re.search(r'/d/([a-zA-Z0-9_-]+)', link)[cite: 1]
    if dosya_id:
        return dosya_id.group(1)[cite: 1]
    id_param = re.search(r'id=([a-zA-Z0-9_-]+)', link)[cite: 1]
    if id_param:
        return id_param.group(1)[cite: 1]
    return None[cite: 1]

def drive_link_donustur(link):
    dosya_id = drive_id_yakala(link)[cite: 1]
    if dosya_id:
        return f"https://drive.google.com/file/d/{dosya_id}/view?usp=sharing"[cite: 1]
    return link[cite: 1]

# --- 14 ÜNİTE SABİT HAP BİLGİ SEEDER ---

GAYRIMUSLIM_OZETLERI = {
    1: [
        "Osmanlı'da Müslümanlara, 'millet-i hâkime' denilirdi.",
        "Osmanlı'da Gayrimüslimlere 'sâir milletler, milel-i gayrimüslime, Devlet-i Osmâniyye'nin bil-cümle tebaa-i sâdıkası, Tebaa-i sâdıka' denilirdi.",
        "Gayrimüslimler İslam Hukukuna göre zımmi statüsüyle yönetiliyorlardı.",
        "Gayrimüslimlerin devlete ödedikleri verginin adı cizye idi.",
        "Fatih'in gayrimüslimlerle ilgili ilk uygulamalarından birisi Galata'da yaşayan Latinlere verilen bir ahitnâme ile bu topluluğun statüsünün belirlenmesiydi.",
        "Osmanlı tebaası olmayan yabancılara Levantenler denilirdi.",
        "Fetih öncesinde ve sırasında İstanbul'dan kaçıp sonradan tekrar şehre dönenlere Levantenler denilir.",
        "Millet başı olan patriklerin, göreve gelirken ödedikleri vergi adı pişkeş vergisi denilirdi.",
        "Hahambaşıların ödedikleri vergiye Rav Akçesi denilirdi.",
        "Dinî liderlerin yeniçerilerden oluşan ve emirlerinde bulunan askerî birlik Yasakçı denilirdi.",
        "Fatih, Rumların Patriklik merkezi olarak Ayasofya'dan sonra Havariyyun Kilisesini kullanmalarına izin verdi.",
        "Ermeni cemaati içindeki cemaat idaresinde de yetki sahibi olan sınıfa amira denir.",
        "Ermeni Patrikhanesi'nin sorumluluğuna bırakılan ve onlara bağlanan topluluk Süryanilerdir.",
        "Yahudi cemaatinin kendi aralarındaki davaları takip eden özel mahkemelere 'bet-din' denilirdi.",
        "Fetih sonrası İstanbul'un ilk hahambaşısı Moşe Kapsali'dir."
    ],
    2: [
        "Osmanlı Ermenileri üzerinde ciddi bir etki yapmayı başaranlar Katolik Misyonerleridir.",
        "İlk Nizamname Katolik Ermeniler için hazırlanan 1850 tarihli Katolik Milleti Nizamnamesi'dir.",
        "Nasturi Kilisesi, Süryanilik'ten ayrılarak kurulmuştur.",
        "Keldani ismi Nasturilik'ten ayrılarak Katolik mezhebini kabul edenlere Papalık tarafından verilmiştir.",
        "Osmanlı sınırlarında en yaygın misyonerlik çalışmalarını Kalvinci Puritan ABCFM örgütü yürütmüştür.",
        "Osmanlıda ilk Protestan kilisesi 1842'de Kudüs'te, 1846'da İstanbul'da açılmıştır.",
        "Misyonerlerin öncelikli faaliyet sahaları eğitim, ardından sağlık alanıdır."
    ],
    3: [
        "Tanzimat Fermanı 3 Kasım 1839 tarihinde Gülhane Parkı'nda Koca Mustafa Reşit Paşa tarafından ilân edildi.",
        "1844 yılında, İslam dininden başka bir dine dönme (irtidad) için verilen ölüm cezası kaldırılmıştır.",
        "Gayrimüslimlerin askerlik yapmamaları karşılığında alınan vergi 'bedel-i askerî' olarak anılmıştır.",
        "1862 yılında ilan edilen Rum Patrikliği Nizamnamesi 8 farklı nizamnamenin bir araya getirilmesinden oluşur.",
        "Osmanlı gayrimüslim tebaası konusunu uluslararası boyuta taşıyan gelişme Paris Antlaşması'dır."
    ],
    4: [
        "Bulgar milli hareketinin 18. yy uyanışının öncüsü keşiş Paisiy Hilendarski kabul edilir.",
        "Abdülaziz 11 Mart 1870'te bağımsız Bulgar Kilisesi kurulmasını ilân eden Eksarhlık Fermanı'nı yayımlamıştır.",
        "Gayrimüslim millet nizamnameleri ile ilgili en fazla tartışmanın yaşandığı dönem II. Abdülhamit dönemidir.",
        "1909 yılında gayrimüslimlerin muafiyetine son verilerek bedel-i askerî vergisi kaldırılmıştır."
    ],
    5: [
        "Müslüman-Gayrimüslim ayrışmasının ekonomik göstergesi Müslümanların başlattığı yerli boykotlardır.",
        "27 Mayıs 1915'te Sevk ve İskân Kanunu çıkarılmıştır; metinde Ermenilerden bahsedilmemektedir.",
        "1917'de çıkan Hukuk-ı Aile Kararnâmesi ile nikâhların resmî memur huzurunda yapılması şartı getirilmiştir."
    ],
    6: [
        "Mütareke dönemi Rum Patriği Dorotheos Mammelis Rum okullarında Türkçe eğitimi yasaklamıştır.",
        "Ermeni Patriği Zaven Efendi mütareke sürecinde İngiliz yanlısı sert bir siyaset takip etmiştir.",
        "Tehcir davaları gerekçesiyle Boğazlıyan Kaymakamı Kemal Bey ve Urfa Mutasarrıfı Nusret Bey idam edilmiştir.",
        "Nutuk'ta Atatürk, Rum Patrikhanesi'nde kurulan Mavri Mira Heyeti'nin çeteleri idare ettiğini belirtmiştir."
    ],
    7: [
        "Hahambaşı Haim Nahum Efendi Milli Mücadele'yi desteklemiş, kamuoyunda İkinci Pierre Loti olarak anılmıştır.",
        "Hahambaşı Vekili Haim Bejerano: 'Türklerden şikâyet edecek bir Musevi, Musevi milletinden değildir' demiştir.",
        "Süryani Kadîm Patriği III. İlyas Şakir işgallere karşı Mustafa Kemal Paşa'yı ve Kuva-yı Milliye'yi desteklemiştir."
    ],
    8: [
        "İç Anadolu'da yaşayan ve Türkçe konuşan Ortodoks topluluk Karamanlılar olarak tanımlanıyordu.",
        "Papa Eftim: 'Ben Türk dostu Eftim değil, Türk oğlu Türk Eftim'im' demiştir.",
        "21 Eylül 1922 tarihinde Kayseri'de Bağımsız Türk Ortodoks Patrikhanesi kurulduğu ilân edilmiştir."
    ],
    9: [
        "Lozan'da Türk heyetinin azınlıklar konusunda en çok üzerinde durduğu prensip eşitliktir.",
        "30 Ocak 1923'te imzalanan sözleşmeyle İstanbul Rumları ile Batı Trakya Müslümanları mübadele dışı tutulmuştur.",
        "Lozan Antlaşması'nda azınlık maddeleri 'Ekalliyetlerin Himayesi' başlığı altındaki 37-45. maddelerdir."
    ],
    10: [
        "1926 Medeni Kanun ile azınlık aile hukuku haklarından ilk feragat edenler Yahudiler olmuştur.",
        "Azınlıklara karşı ilk güvensizlik ve gerginlik 1934 Trakya Olayları ile yaşanmıştır.",
        "6-7 Eylül 1955 olayları sonrasında Rumların Türkiye'den göç dalgası hızlanmıştır.",
        "1971 yılında Heybeliada Ruhban Okulu devletleştirme kanunları çerçevesinde kapatılmıştır."
    ],
    11: [
        "Cumhuriyet döneminin ilk Ermeni patriği 1927 yılında seçilen I. Mesrob Naroyan'dır.",
        "Patrik Şınorhk Kalustyan 29 yıllık göreviyle Türkiye Ermenileri arasında en uzun süre patriklik yapan kişidir.",
        "2019'da yapılan seçimle Sahak Maşalyan Türkiye Ermenileri Patriği seçilmiştir."
    ],
    12: [
        "Cumhuriyetin ilk yıllarında Türkiye Hükümeti patrik için resmiyette sadece 'başrahip/başpapaz' unvanını kullanmıştır.",
        "Patrik seçilen Konstantin Araboğlu mübadeleye tâbi olduğu gerekçesiyle Selanik'e gönderilmiştir.",
        "1964'te İkamet ve Ticaret Mukavelesi feshedilmiş ve Rum göçü hızlanmıştır."
    ],
    13: [
        "Haim Moşe Bejerano'dan sonra 1953'e kadar seçim yapılmamış, ilk resmî hahambaşı Rafael David Saban seçilmiştir.",
        "2002 yılından itibaren İshak Haleva Türkiye Hahambaşılığı görevini sürdürmektedir."
    ],
    14: [
        "Süryani Patrikliği merkezi 1933'te Humus'a, 1959'da Şam'a taşınmıştır.",
        "1924 yılındaki Hakkâri merkezli Nasturi İsyanı Musul'un kaybedilmesinde etkili olmuştur.",
        "Bulgar Eksarhlığı Balkan Savaşları sonrası merkezini Sofya'ya taşımış, İstanbul'da vekâlet bırakmıştır."
    ]
}

def varsayilan_ozetleri_yukle():
    try:
        conn = veritabani_baglan()
        cursor = conn.cursor()
        ders_adi = "20. Yüzyıl Türkiye’sinde Gayrimüslimler ve Kurumları"
        cursor.execute("SELECT COUNT(*) FROM unite_ozetleri WHERE TRIM(ders_adi) LIKE ?", (f"%{ders_adi}%",))
        if cursor.fetchone()[0] < 30:
            cursor.execute("DELETE FROM unite_ozetleri WHERE TRIM(ders_adi) LIKE ?", (f"%{ders_adi}%",))
            for u_no, maddeler in GAYRIMUSLIM_OZETLERI.items():
                for m in maddeler:
                    cursor.execute("INSERT INTO unite_ozetleri (ders_adi, unite_no, madde) VALUES (?, ?, ?)", (ders_adi, u_no, m))
            conn.commit()
        conn.close()
    except Exception as e:
        print("Özet yükleme hatası:", e)

varsayilan_ozetleri_yukle()

# --- TEK VE NET KULLANICI GİRİŞ & ÇIKIŞ METODLARI ---

@app.route("/giris", methods=["GET", "POST"])
def giris_yap():
    if "kullanici_id" in session:
        return redirect(url_for("ana_sayfa"))[cite: 1]

    if request.method == "POST":
        kullanici_adi = request.form.get("kullanici_adi", "").strip().lower()[cite: 1]
        sifre = request.form.get("sifre", "")[cite: 1]

        conn = veritabani_baglan()[cite: 1]
        cursor = conn.cursor()[cite: 1]
        cursor.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = ?", (kullanici_adi,))[cite: 1]
        kullanici = cursor.fetchone()[cite: 1]
        conn.close()[cite: 1]

        if kullanici and check_password_hash(kullanici["sifre_hash"], sifre):[cite: 1]
            session["kullanici_id"] = kullanici["id"][cite: 1]
            session["kullanici_adi"] = kullanici["kullanici_adi"][cite: 1]
            session["ad_soyad"] = kullanici["ad_soyad"][cite: 1]
            return redirect(url_for("ana_sayfa"))[cite: 1]
        else:
            session["bildirim"] = {"tur": "danger", "metin": "Kullanıcı adı veya şifre hatalı."}[cite: 1]
            return redirect(url_for("giris_yap"))[cite: 1]

    mesaj = session.pop("bildirim", None)[cite: 1]
    return render_template("index.html", durum="giris", bildirim=mesaj)[cite: 1]

@app.route("/kayit", methods=["GET", "POST"])
def kayit_ol():
    if "kullanici_id" in session:
        return redirect(url_for("ana_sayfa"))[cite: 1]

    if request.method == "POST":
        kullanici_adi = request.form.get("kullanici_adi", "").strip().lower()[cite: 1]
        ad_soyad = request.form.get("ad_soyad", "").strip()[cite: 1]
        sifre = request.form.get("sifre", "")[cite: 1]

        if len(kullanici_adi) < 3 or len(sifre) < 4:[cite: 1]
            session["bildirim"] = {"tur": "danger", "metin": "Kullanıcı adı en az 3, şifre en az 4 karakter olmalıdır."}[cite: 1]
            return redirect(url_for("kayit_ol"))[cite: 1]

        conn = veritabani_baglan()[cite: 1]
        cursor = conn.cursor()[cite: 1]
        cursor.execute("SELECT id FROM kullanicilar WHERE kullanici_adi = ?", (kullanici_adi,))[cite: 1]
        if cursor.fetchone():[cite: 1]
            conn.close()[cite: 1]
            session["bildirim"] = {"tur": "warning", "metin": "Bu kullanıcı adı zaten alınmış."}[cite: 1]
            return redirect(url_for("kayit_ol"))[cite: 1]

        sifre_hash = generate_password_hash(sifre)[cite: 1]
        simdi = datetime.now().strftime("%d.%m.%Y %H:%M")[cite: 1]
        cursor.execute("""
            INSERT INTO kullanicilar (kullanici_adi, ad_soyad, sifre_hash, kayit_tarihi)
            VALUES (?, ?, ?, ?)
        """, (kullanici_adi, ad_soyad, sifre_hash, simdi))[cite: 1]
        conn.commit()[cite: 1]
        conn.close()[cite: 1]

        session["bildirim"] = {"tur": "success", "metin": "Kayıt başarılı! Şimdi giriş yapabilirsiniz."}[cite: 1]
        return redirect(url_for("giris_yap"))[cite: 1]

    mesaj = session.pop("bildirim", None)[cite: 1]
    return render_template("index.html", durum="kayit", bildirim=mesaj)[cite: 1]

@app.route("/cikis")
def cikis_yap():
    session.clear()[cite: 1]
    return redirect(url_for("giris_yap"))[cite: 1]

# --- ANA SAYFA VE DERS MODÜLLERİ ---

@app.route("/")
@giris_zorunlu
def ana_sayfa():
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("SELECT ders_adi, COUNT(*) as soru_sayisi FROM sorular GROUP BY ders_adi")[cite: 1]
    dersler = cursor.fetchall()[cite: 1]
    cursor.execute("SELECT COUNT(*) FROM sorular")[cite: 1]
    toplam_soru = cursor.fetchone()[0][cite: 1]

    cursor.execute("SELECT COUNT(*) FROM sorular WHERE yildizli = 1")[cite: 1]
    yildizli_soru_sayisi = cursor.fetchone()[0][cite: 1]

    cursor.execute("""
        SELECT COUNT(*) FROM sorular s
        JOIN performans p ON s.id = p.soru_id
        WHERE p.son_durum = 'YANLIS'
    """)[cite: 1]
    hatali_soru_sayisi = cursor.fetchone()[0][cite: 1]
    conn.close()[cite: 1]

    mesaj = session.pop("bildirim", None)[cite: 1]
    return render_template("index.html", 
                           durum="baslangic", 
                           dersler=dersler, 
                           toplam_soru=toplam_soru, 
                           yildizli_sayisi=yildizli_soru_sayisi,
                           hatali_sayisi=hatali_soru_sayisi,
                           bildirim=mesaj)[cite: 1]

@app.route("/icerik-merkezi")
@giris_zorunlu
def icerik_merkezi():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()[cite: 1]
    return render_template("index.html", durum="icerik_merkezi", aktif_ders=secilen_ders, dersler=GUZ_DERSLERI)[cite: 1]

@app.route("/yukle-pdf-dosya", methods=["POST"])
@giris_zorunlu
def yukle_pdf_dosya():
    ders = request.form.get("ders_adi", "").strip()[cite: 1]
    unite_no = int(request.form.get("unite_no", 1))[cite: 1]
    dosya = request.files.get("pdf_dosya")[cite: 1]

    if not dosya or not dosya.filename.lower().endswith(".pdf"):[cite: 1]
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir .pdf dosyası seçin."}[cite: 1]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 1]

    dosya_adi = f"{abs(hash(ders))}_{unite_no}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"[cite: 1]
    hedef_yol = os.path.join(UPLOAD_FOLDER, dosya_adi)[cite: 1]
    dosya.save(hedef_yol)[cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("DELETE FROM unite_kaynaklari WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))[cite: 1]
    cursor.execute("""
        INSERT INTO unite_kaynaklari (ders_adi, unite_no, kaynak_turu, dosya_yolu)
        VALUES (?, ?, 'yerel', ?)
    """, (ders, unite_no, f"/static/kitaplar/{dosya_adi}"))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' dersinin {unite_no}. Ünite PDF'i başarıyla yüklendi!"}[cite: 1]
    return redirect(url_for("ders_calis", ders=ders, unite=unite_no))[cite: 1]

@app.route("/kaydet-drive-link", methods=["POST"])
@giris_zorunlu
def kaydet_drive_link():
    ders = request.form.get("ders_adi", "").strip()[cite: 1]
    unite_no = int(request.form.get("unite_no", 1))[cite: 1]
    raw_link = request.form.get("drive_url", "").strip()[cite: 1]

    if not raw_link:[cite: 1]
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir Google Drive bağlantısı yapıştırın."}[cite: 1]
        return redirect(url_for("icerik_merkezi", ders=ders))[cite: 1]

    preview_link = drive_link_donustur(raw_link)[cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("DELETE FROM unite_kaynaklari WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite_no))[cite: 1]
    cursor.execute("""
        INSERT INTO unite_kaynaklari (ders_adi, unite_no, kaynak_turu, dosya_yolu)
        VALUES (?, ?, 'drive', ?)
    """, (ders, unite_no, preview_link))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

    session["bildirim"] = {"tur": "success", "metin": f"'{ders}' - Ünite {unite_no} için Google Drive PDF kaynağı bağlandı!"}[cite: 1]
    return redirect(url_for("ders_calis", ders=ders, unite=unite_no))[cite: 1]

@app.route("/ders-calis")
@giris_zorunlu
def ders_calis():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()[cite: 1]
    secilen_unite = int(request.args.get("unite", 1))[cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]

    cursor.execute("""
        SELECT kaynak_turu, dosya_yolu FROM unite_kaynaklari 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))[cite: 1]
    row_kaynak = cursor.fetchone()[cite: 1]
    
    pdf_url = row_kaynak["dosya_yolu"] if row_kaynak else ""[cite: 1]
    kaynak_turu = row_kaynak["kaynak_turu"] if row_kaynak else ""[cite: 1]

    cursor.execute("""
        SELECT video_url FROM ders_videolari 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))[cite: 1]
    row_video = cursor.fetchone()[cite: 1]
    video_url = row_video["video_url"] if row_video else ""[cite: 1]

    cursor.execute("""
        SELECT unite_no, okundu, izlendi FROM unite_takip 
        WHERE TRIM(ders_adi) LIKE ?
    """, (f"%{secilen_ders}%",))[cite: 1]
    takip_verileri = {r["unite_no"]: {"okundu": r["okundu"], "izlendi": r["izlendi"]} for r in cursor.fetchall()}[cite: 1]

    cursor.execute("""
        SELECT madde FROM unite_ozetleri 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))[cite: 1]
    ozet_maddeleri = [r["madde"] for r in cursor.fetchall()][cite: 1]

    conn.close()[cite: 1]

    embed_url = ""[cite: 1]
    if video_url:[cite: 1]
        if "watch?v=" in video_url:[cite: 1]
            embed_url = video_url.replace("watch?v=", "embed/")[cite: 1]
        elif "youtu.be/" in video_url:[cite: 1]
            embed_url = video_url.replace("youtu.be/", "www.youtube.com/embed/")[cite: 1]
        else:
            embed_url = video_url[cite: 1]

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
                           dersler=GUZ_DERSLERI)[cite: 1]

@app.route("/hafiza-kartlari")
@giris_zorunlu
def hafiza_kartlari():
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()[cite: 1]
    secilen_unite = int(request.args.get("unite", 1))[cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("""
        SELECT madde FROM unite_ozetleri 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
    """, (f"%{secilen_ders}%", secilen_unite))[cite: 1]
    satirlar = cursor.fetchall()[cite: 1]
    conn.close()[cite: 1]

    kartlar = [][cite: 1]
    for s in satirlar:[cite: 1]
        metin = s["madde"].strip()[cite: 1]
        if not metin:[cite: 1]
            continue[cite: 1]

        if " denilirdi" in metin or " denirdi" in metin or " adı verilmektedir" in metin:[cite: 1]
            parcalar = re.split(r' (?:denilirdi|denirdi|adı verilmektedir)', metin)[cite: 1]
            on_yuz = parcalar[0] + " kavramı nasıl adlandırılırdı?"[cite: 1]
            arka_yuz = metin[cite: 1]
        elif " idi" in metin:[cite: 1]
            parcalar = metin.split(" idi")[cite: 1]
            on_yuz = parcalar[0] + " nedir / kimdir?"[cite: 1]
            arka_yuz = metin[cite: 1]
        else:
            on_yuz = f"📌 {secilen_unite}. Ünite Kritik Sınav Bilgisi"[cite: 1]
            arka_yuz = metin[cite: 1]

        kartlar.append({"on": on_yuz, "arka": arka_yuz})[cite: 1]

    random.shuffle(kartlar)[cite: 1]
    return render_template("index.html", 
                           durum="flashcards", 
                           aktif_ders=secilen_ders, 
                           aktif_unite=secilen_unite, 
                           kartlar=kartlar, 
                           dersler=GUZ_DERSLERI)[cite: 1]

@app.route("/unite-durum-guncelle", methods=["POST"])
@giris_zorunlu
def unite_durum_guncelle():
    ders = request.form.get("ders")[cite: 1]
    unite = int(request.form.get("unite"))[cite: 1]
    tur = request.form.get("tur")[cite: 1]
    deger = int(request.form.get("deger"))[cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("SELECT id FROM unite_takip WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite))[cite: 1]
    kayit = cursor.fetchone()[cite: 1]
    if kayit:[cite: 1]
        cursor.execute(f"UPDATE unite_takip SET {tur} = ? WHERE id = ?", (deger, kayit["id"]))[cite: 1]
    else:
        cursor.execute(f"INSERT INTO unite_takip (ders_adi, unite_no, {tur}) VALUES (?, ?, ?)", (ders, unite, deger))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]
    return jsonify({"basarili": True})[cite: 1]

@app.route("/video-kaydet", methods=["POST"])
@giris_zorunlu
def video_kaydet():
    ders = request.form.get("ders")[cite: 1]
    unite = int(request.form.get("unite"))[cite: 1]
    url = request.form.get("video_url", "").strip()[cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("DELETE FROM ders_videolari WHERE TRIM(ders_adi) = TRIM(?) AND unite_no = ?", (ders, unite))[cite: 1]
    cursor.execute("""
        INSERT INTO ders_videolari (ders_adi, unite_no, video_url) 
        VALUES (?, ?, ?)
    """, (ders, unite, url))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]
    return redirect(url_for("ders_calis", ders=ders, unite=unite))[cite: 1]

@app.route("/unite-pekistirme")
@giris_zorunlu
def unite_pekistirme_listesi():
    ders = request.args.get("ders", "").strip()[cite: 1]
    if not ders and GUZ_DERSLERI:[cite: 1]
        ders = GUZ_DERSLERI[0][cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("""
        SELECT unite_no, COUNT(*) as adet 
        FROM sorular 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no > 0
        GROUP BY unite_no
        ORDER BY unite_no ASC
    """, (f"%{ders}%",))[cite: 1]
    sayilar = {row["unite_no"]: row["adet"] for row in cursor.fetchall()}[cite: 1]
    conn.close()[cite: 1]

    uniteler = [][cite: 1]
    for i in range(1, 15):[cite: 1]
        uniteler.append({
            "no": i,
            "baslik": f"Ünite {i}",
            "soru_sayisi": sayilar.get(i, 0),
            "ders_adi": ders
        })[cite: 1]

    return render_template("index.html", 
                           durum="unite_pekistirme", 
                           uniteler=uniteler, 
                           aktif_ders=ders, 
                           dersler=GUZ_DERSLERI)[cite: 1]

# --- SESSION OVERFLOW VE BAD GATEWAY ENGELLEYEN SINAV MOTORU ---

@app.route("/unite-test-baslat/<int:unite_no>")
@giris_zorunlu
def unite_test_baslat(unite_no):
    ders = request.args.get("ders", "").strip()[cite: 1]
    if not ders and GUZ_DERSLERI:[cite: 1]
        ders = GUZ_DERSLERI[0][cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("""
        SELECT id FROM sorular 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
        ORDER BY id ASC
    """, (f"%{ders}%", unite_no))
    satirlar = cursor.fetchall()[cite: 1]
    conn.close()[cite: 1]

    if not satirlar:[cite: 1]
        session["bildirim"] = {"tur": "warning", "metin": f"'{ders}' dersinin {unite_no}. ünitesine ait soru bulunamadı."}
        return redirect(url_for("unite_pekistirme_listesi", ders=ders))[cite: 1]

    soru_idleri = [r["id"] for r in satirlar]
    random.shuffle(soru_idleri)
    sinav_oturumunu_temizle()

    # Sadece ID dizisi saklanarak HTTP Header Overflow / Bad Gateway kesinlikle engellenir
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
    secilen_ders = request.args.get("ders", GUZ_DERSLERI[0]).strip()[cite: 1]
    
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("""
        SELECT id, soru_metni, aciklama, dogru_cevap, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e 
        FROM sorular 
        WHERE TRIM(ders_adi) LIKE ?
    """, (f"%{secilen_ders}%",))[cite: 1]
    satirlar = cursor.fetchall()[cite: 1]
    conn.close()[cite: 1]

    otomatik_olaylar = [][cite: 1]
    gorulen_yillar = set()[cite: 1]

    for s in satirlar:[cite: 1]
        metin_havuzu = f"{s['soru_metni']} {s['aciklama']}"[cite: 1]
        yillar = re.findall(r'\b(1[3-9]\d{2})\b', metin_havuzu)[cite: 1]
        
        if yillar:[cite: 1]
            yil = int(yillar[0])[cite: 1]
            if yil not in gorulen_yillar:[cite: 1]
                gorulen_yillar.add(yil)[cite: 1]
                olay_metni = s['soru_metni'][cite: 1]
                if len(olay_metni) > 130:[cite: 1]
                    olay_metni = olay_metni[:127] + "..."[cite: 1]
                
                otomatik_olaylar.append({
                    "id": s["id"],
                    "yil": yil,
                    "olay": olay_metni,
                    "detay": f"Doğru Cevap: {s['dogru_cevap']} | {s['aciklama'][:90]}..." if s['aciklama'] else f"Doğru Seçenek: {s['dogru_cevap']}"
                })[cite: 1]
        
        if len(otomatik_olaylar) >= 6:[cite: 1]
            break[cite: 1]

    if len(otomatik_olaylar) < 3:[cite: 1]
        karisik_olaylar = [
            {"id": 1, "yil": 1453, "olay": "İstanbul'un fethi sonrası Gennadios'un Rum Patriği seçilmesi", "detay": "Fatih Sultan Mehmet dönemi."},
            {"id": 2, "yil": 1461, "olay": "Episkopos Hovagim'in İstanbul Ermeni Patriği tayin edilmesi", "detay": "Fatih Sultan Mehmet dönemi."},
            {"id": 3, "yil": 1492, "olay": "Sefarad Yahudilerinin Osmanlı topraklarına gelişi", "detay": "II. Bayezid dönemi."},
            {"id": 4, "yil": 1602, "olay": "Fener Rum Patrikhanesi'nin Aya Yorgi'ye taşınması", "detay": "Patrikhane merkezi."},
            {"id": 5, "yil": 1835, "olay": "Hahambaşılık makamına yeniden resmi berat verilmesi", "detay": "II. Mahmud dönemi."},
            {"id": 6, "yil": 1856, "olay": "Islahat Fermanı ile millet nizamnamelerinin başlaması", "detay": "Tanzimat dönemi."}
        ][cite: 1]
        uyari_mesaji = "Bu dersin soru havuzunda yeterli tarihli veri bulunamadığı için genel tarih seti yüklendi."[cite: 1]
    else:
        karisik_olaylar = list(otomatik_olaylar)[cite: 1]
        uyari_mesaji = None[cite: 1]

    random.shuffle(karisik_olaylar)[cite: 1]

    return render_template("index.html", 
                           durum="kronoloji", 
                           aktif_ders=secilen_ders, 
                           karisik_olaylar=karisik_olaylar, 
                           uyari_mesaji=uyari_mesaji, 
                           dersler=GUZ_DERSLERI)[cite: 1]

@app.route("/sinav-baslat", methods=["POST"])
@giris_zorunlu
def sinav_baslat():
    ders = request.form.get("ders", "HEPSI").strip()[cite: 1]
    unite_secim = request.form.get("unite", "TUMU").strip()[cite: 1]
    sure_dakika = int(request.form.get("sure", 0))[cite: 1]
    mod = request.form.get("mod", "sinav")[cite: 1]
    limit = int(request.form.get("limit", 20))[cite: 1]
    ozel_havuz = request.form.get("ozel_havuz", "")[cite: 1]

    if unite_secim.startswith("UNITE_"):
        limit = 0

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]

    if ozel_havuz == "yildizli":[cite: 1]
        cursor.execute("SELECT id FROM sorular WHERE yildizli = 1")
        aktif_ders_adi = "⭐ Yıldızlı Sorular Havuzu"[cite: 1]
    elif ozel_havuz == "hatalar":[cite: 1]
        cursor.execute("""
            SELECT s.id FROM sorular s
            JOIN performans p ON s.id = p.soru_id
            WHERE p.son_durum = 'YANLIS'
        """)
        aktif_ders_adi = "🎯 Yanlışlar & Telafi Havuzu"[cite: 1]
    elif ders == "HEPSI":[cite: 1]
        cursor.execute("SELECT id FROM sorular")
        aktif_ders_adi = "Tüm Dersler (Karışık)"[cite: 1]
    else:
        if unite_secim == "VIZE":[cite: 1]
            cursor.execute("""
                SELECT id FROM sorular 
                WHERE TRIM(ders_adi) LIKE ? AND (unite_no BETWEEN 1 AND 7 OR unite_no = 0)
            """, (f"%{ders}%",))
            aktif_ders_adi = f"{ders} (Vize Konuları)"[cite: 1]
        elif unite_secim.startswith("UNITE_"):[cite: 1]
            u_no = int(unite_secim.replace("UNITE_", ""))[cite: 1]
            cursor.execute("""
                SELECT id FROM sorular 
                WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
            """, (f"%{ders}%", u_no))
            aktif_ders_adi = f"{ders} (Ünite {u_no})"[cite: 1]
        else:
            cursor.execute("""
                SELECT id FROM sorular 
                WHERE TRIM(ders_adi) LIKE ?
            """, (f"%{ders}%",))
            aktif_ders_adi = ders[cite: 1]

    satirlar = cursor.fetchall()[cite: 1]
    conn.close()[cite: 1]

    if not satirlar and ders != "HEPSI":[cite: 1]
        conn = veritabani_baglan()[cite: 1]
        cursor = conn.cursor()[cite: 1]
        cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE ?", (f"%{ders}%",))
        satirlar = cursor.fetchall()[cite: 1]
        conn.close()[cite: 1]
        aktif_ders_adi = ders[cite: 1]

    if not satirlar:[cite: 1]
        session["bildirim"] = {"tur": "warning", "metin": "Seçilen kritere ait soru bulunamadı."}[cite: 1]
        return redirect(url_for("ana_sayfa"))[cite: 1]

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
    indeks = session.get("mevcut_indeks", 0)[cite: 1]
    aktif_ders = session.get("aktif_ders", "Genel Sınav")[cite: 1]
    mod = session.get("sinav_modu", "sinav")[cite: 1]
    kalan_sure = request.args.get("kalan_sure")[cite: 1]

    if not soru_idleri:
        return redirect(url_for("ana_sayfa"))[cite: 1]

    if indeks >= len(soru_idleri):
        return redirect(url_for("sonuc_goruntule"))[cite: 1]

    aktif_id = soru_idleri[indeks]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("SELECT * FROM sorular WHERE id = ?", (aktif_id,))
    row = cursor.fetchone()[cite: 1]
    conn.close()[cite: 1]

    if not row:
        return redirect(url_for("ana_sayfa"))

    soru = dict(row)

    if request.method == "POST":[cite: 1]
        secilen = request.form.get("secenek", "")[cite: 1]
        kalan_saniye = request.form.get("kalan_saniye")[cite: 1]
        dogru = soru["dogru_cevap"][cite: 1]

        if not secilen:[cite: 1]
            durum = "BOS"[cite: 1]
            session["bos"] = session.get("bos", 0) + 1[cite: 1]
        elif secilen == dogru:[cite: 1]
            durum = "DOGRU"[cite: 1]
            session["dogru"] = session.get("dogru", 0) + 1[cite: 1]
        else:
            durum = "YANLIS"[cite: 1]
            session["yanlis"] = session.get("yanlis", 0) + 1[cite: 1]

        cevap_listesi = session.get("cevaplar", [])[cite: 1]
        cevap_listesi.append({
            "soru_id": soru["id"],
            "soru_metni": soru["soru_metni"][:65] + "...",
            "secilen": secilen if secilen else "Boş",
            "dogru": dogru,
            "durum": durum
        })
        session["cevaplar"] = cevap_listesi[cite: 1]
        session["mevcut_indeks"] = indeks + 1[cite: 1]

        if mod == "ogrenme":[cite: 1]
            conn = veritabani_baglan()[cite: 1]
            cursor = conn.cursor()[cite: 1]
            cursor.execute("INSERT OR IGNORE INTO performans (soru_id, dogru_sayisi, yanlis_sayisi, son_durum) VALUES (?, 0, 0, '')", (soru["id"],))[cite: 1]
            if durum == "DOGRU":[cite: 1]
                cursor.execute("UPDATE performans SET dogru_sayisi = dogru_sayisi + 1, son_durum = 'DOGRU' WHERE soru_id = ?", (soru["id"],))[cite: 1]
            elif durum == "YANLIS":[cite: 1]
                cursor.execute("UPDATE performans SET yanlis_sayisi = yanlis_sayisi + 1, son_durum = 'YANLIS' WHERE soru_id = ?", (soru["id"],))[cite: 1]
            conn.commit()[cite: 1]
            conn.close()[cite: 1]

        if mod == "sinav":[cite: 1]
            if session["mevcut_indeks"] >= len(soru_idleri):
                return redirect(url_for("sonuc_goruntule"))[cite: 1]
            return redirect(url_for("soru_goruntule", kalan_sure=kalan_saniye))[cite: 1]

        return render_template("index.html", 
                               durum="geribildirim", 
                               soru=soru, 
                               secilen=secilen, 
                               sonuc=durum, 
                               aktif_ders=aktif_ders, 
                               kalan_saniye=kalan_saniye, 
                               sira=indeks + 1, 
                               toplam=len(soru_idleri))

    toplam_sure = session.get("toplam_sure_saniye", 0)[cite: 1]
    baslangic_sure = kalan_sure if kalan_sure is not None else toplam_sure[cite: 1]

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
    dogru = session.get("dogru", 0)[cite: 1]
    yanlis = session.get("yanlis", 0)[cite: 1]
    bos = session.get("bos", 0)[cite: 1]
    aktif_ders = session.get("aktif_ders", "Genel Sınav")[cite: 1]
    mod = session.get("sinav_modu", "sinav")[cite: 1]
    cevaplar = session.get("cevaplar", [])[cite: 1]
    toplam = dogru + yanlis + bos[cite: 1]

    net = dogru - (yanlis * 0.25)[cite: 1]
    puan = max(0, (net / toplam) * 100) if toplam > 0 else 0[cite: 1]

    try:
        conn = veritabani_baglan()[cite: 1]
        cursor = conn.cursor()[cite: 1]
        simdi = datetime.now().strftime("%d.%m.%Y %H:%M")[cite: 1]
        cursor.execute("""
            INSERT INTO sinav_gecmisi (tarih, ders_adi, dogru, yanlis, bos, net, puan)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (simdi, aktif_ders, dogru, yanlis, bos, round(net, 2), round(puan, 1)))[cite: 1]

        for c in cevaplar:[cite: 1]
            if "soru_id" in c:
                s_id = c["soru_id"]
                durum = c["durum"][cite: 1]
                cursor.execute("INSERT OR IGNORE INTO performans (soru_id, dogru_sayisi, yanlis_sayisi, son_durum) VALUES (?, 0, 0, '')", (s_id,))[cite: 1]
                if durum == "DOGRU":[cite: 1]
                    cursor.execute("UPDATE performans SET dogru_sayisi = dogru_sayisi + 1, son_durum = 'DOGRU' WHERE soru_id = ?", (s_id,))[cite: 1]
                elif durum == "YANLIS":[cite: 1]
                    cursor.execute("UPDATE performans SET yanlis_sayisi = yanlis_sayisi + 1, son_durum = 'YANLIS' WHERE soru_id = ?", (s_id,))[cite: 1]
        conn.commit()[cite: 1]
        conn.close()[cite: 1]
    except Exception:
        pass[cite: 1]

    return render_template("index.html", 
                           durum="sonuc", 
                           dogru=dogru, 
                           yanlis=yanlis, 
                           bos=bos, 
                           net=round(net, 2), 
                           puan=round(puan, 1), 
                           aktif_ders=aktif_ders, 
                           mod=mod, 
                           cevaplar=cevaplar)[cite: 1]

@app.route("/istatistik")
@giris_zorunlu
def istatistik_paneli():
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]

    cursor.execute("""
        SELECT 
            s.ders_adi,
            COUNT(p.soru_id) as cozulen_soru,
            SUM(p.dogru_sayisi) as toplam_dogru,
            SUM(p.yanlis_sayisi) as toplam_yanlis
        FROM sorular s
        INNER JOIN performans p ON s.id = p.soru_id
        GROUP BY s.ders_adi
    """)[cite: 1]
    veriler = cursor.fetchall()[cite: 1]

    rapor = [][cite: 1]
    toplam_genel_cozulen, toplam_genel_dogru, toplam_genel_yanlis = 0, 0, 0[cite: 1]

    for row in veriler:[cite: 1]
        d_adi = row["ders_adi"][cite: 1]
        d = row["toplam_dogru"] or 0[cite: 1]
        y = row["toplam_yanlis"] or 0[cite: 1]
        cozulen = d + y[cite: 1]
        net = d - (y * 0.25)[cite: 1]
        oran = round((d / cozulen) * 100, 1) if cozulen > 0 else 0[cite: 1]

        toplam_genel_cozulen += cozulen[cite: 1]
        toplam_genel_dogru += d[cite: 1]
        toplam_genel_yanlis += y[cite: 1]

        rapor.append({
            "ders_adi": d_adi, "cozulen": cozulen, "dogru": d, "yanlis": y, "net": round(net, 2), "oran": oran
        })[cite: 1]

    genel_net = toplam_genel_dogru - (toplam_genel_yanlis * 0.25)[cite: 1]
    genel_oran = round((toplam_genel_dogru / toplam_genel_cozulen) * 100, 1) if toplam_genel_cozulen > 0 else 0[cite: 1]

    cursor.execute("SELECT * FROM sinav_gecmisi ORDER BY id DESC LIMIT 15")[cite: 1]
    gecmis_sinavlar = [dict(row) for row in cursor.fetchall()][cite: 1]
    conn.close()[cite: 1]

    return render_template("index.html", 
                           durum="istatistik", 
                           rapor=rapor, 
                           toplam_cozulen=toplam_genel_cozulen, 
                           genel_net=round(genel_net, 2), 
                           genel_oran=genel_oran, 
                           gecmis_sinavlar=gecmis_sinavlar)[cite: 1]

@app.route("/yildiz-degistir/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def yildiz_degistir(soru_id):
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("SELECT yildizli FROM sorular WHERE id = ?", (soru_id,))[cite: 1]
    row = cursor.fetchone()[cite: 1]
    if row:[cite: 1]
        yeni_durum = 0 if row["yildizli"] == 1 else 1[cite: 1]
        cursor.execute("UPDATE sorular SET yildizli = ? WHERE id = ?", (yeni_durum, soru_id))[cite: 1]
        conn.commit()[cite: 1]
        conn.close()[cite: 1]
        return jsonify({"basarili": True, "yildizli": yeni_durum})[cite: 1]
    conn.close()[cite: 1]
    return jsonify({"basarili": False}), 404[cite: 1]

@app.route("/not-kaydet/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def not_kaydet(soru_id):
    yeni_not = request.form.get("not", "").strip()[cite: 1]
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("UPDATE sorular SET kullanici_notu = ? WHERE id = ?", (yeni_not, soru_id))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]
    return jsonify({"basarili": True, "not": yeni_not})[cite: 1]

@app.route("/yazdir")
@giris_zorunlu
def sinav_yazdir():
    ders = request.args.get("ders", "HEPSI")[cite: 1]
    limit = int(request.args.get("limit", 20))[cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    if ders == "HEPSI":[cite: 1]
        cursor.execute("SELECT * FROM sorular")[cite: 1]
        aktif_ders = "Tüm Dersler (Karma Deneme Sınavı)"[cite: 1]
    else:
        cursor.execute("SELECT * FROM sorular WHERE ders_adi = ?", (ders,))[cite: 1]
        aktif_ders = ders[cite: 1]

    satirlar = cursor.fetchall()[cite: 1]
    conn.close()[cite: 1]

    if not satirlar:[cite: 1]
        session["bildirim"] = {"tur": "warning", "metin": "Yazdırılacak soru bulunamadı."}[cite: 1]
        return redirect(url_for("ana_sayfa"))[cite: 1]

    tum_sorular = [dict(r) for r in satirlar][cite: 1]
    random.shuffle(tum_sorular)[cite: 1]
    secilen_sorular = tum_sorular[:limit] if (limit > 0 and len(tum_sorular) > limit) else tum_sorular[cite: 1]
    return render_template("yazdir.html", sorular=secilen_sorular, aktif_ders=aktif_ders)[cite: 1]

@app.route("/yonetim", methods=["GET"])
@giris_zorunlu
def soru_yonetimi():
    kelime = request.args.get("kelime", "").strip()[cite: 1]
    secilen_ders = request.args.get("ders", "")[cite: 1]

    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    sql = "SELECT * FROM sorular WHERE 1=1"[cite: 1]
    paramlar = [][cite: 1]

    if kelime:[cite: 1]
        sql += " AND (soru_metni LIKE ? OR secenek_a LIKE ? OR secenek_b LIKE ? OR secenek_c LIKE ? OR secenek_d LIKE ? OR secenek_e LIKE ? OR aciklama LIKE ? OR kullanici_notu LIKE ?)"[cite: 1]
        for _ in range(8):[cite: 1]
            paramlar.append(f"%{kelime}%")[cite: 1]

    if secilen_ders:[cite: 1]
        sql += " AND ders_adi = ?"[cite: 1]
        paramlar.append(secilen_ders)[cite: 1]

    sql += " ORDER BY id DESC LIMIT 50"[cite: 1]
    cursor.execute(sql, tuple(paramlar))[cite: 1]
    bulunan_sorular = [dict(r) for r in cursor.fetchall()][cite: 1]
    conn.close()[cite: 1]

    return render_template("index.html", durum="yonetim", sorular=bulunan_sorular, kelime=kelime, secilen_ders=secilen_ders, dersler=GUZ_DERSLERI)[cite: 1]

@app.route("/soru-duzenle/<int:soru_id>", methods=["GET", "POST"])
@giris_zorunlu
def soru_duzenle(soru_id):
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]

    if request.method == "POST":[cite: 1]
        ders = request.form.get("ders_adi")[cite: 1]
        metin = request.form.get("soru_metni")[cite: 1]
        a = request.form.get("secenek_a")[cite: 1]
        b = request.form.get("secenek_b")[cite: 1]
        c = request.form.get("secenek_c")[cite: 1]
        d = request.form.get("secenek_d")[cite: 1]
        e = request.form.get("secenek_e")[cite: 1]
        dogru = request.form.get("dogru_cevap")[cite: 1]
        aciklama = request.form.get("aciklama")[cite: 1]
        kullanici_notu = request.form.get("kullanici_notu", "")[cite: 1]
        unite_no = int(request.form.get("unite_no", 0))[cite: 1]

        cursor.execute("""
            UPDATE sorular 
            SET ders_adi = ?, soru_metni = ?, secenek_a = ?, secenek_b = ?, secenek_c = ?, secenek_d = ?, secenek_e = ?, dogru_cevap = ?, aciklama = ?, kullanici_notu = ?, unite_no = ?
            WHERE id = ?
        """, (ders, metin, a, b, c, d, e, dogru, aciklama, kullanici_notu, unite_no, soru_id))[cite: 1]
        conn.commit()[cite: 1]
        conn.close()[cite: 1]
        session["bildirim"] = {"tur": "success", "metin": f"Soru #{soru_id} güncellendi."}[cite: 1]
        return redirect(url_for("soru_yonetimi"))[cite: 1]

    cursor.execute("SELECT * FROM sorular WHERE id = ?", (soru_id,))[cite: 1]
    soru = cursor.fetchone()[cite: 1]
    conn.close()[cite: 1]
    if not soru:[cite: 1]
        return redirect(url_for("soru_yonetimi"))[cite: 1]
    return render_template("index.html", durum="duzenle", soru=dict(soru), dersler=GUZ_DERSLERI)[cite: 1]

@app.route("/soru-sil/<int:soru_id>", methods=["POST"])
@giris_zorunlu
def soru_sil(soru_id):
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("DELETE FROM sorular WHERE id = ?", (soru_id,))[cite: 1]
    cursor.execute("DELETE FROM performans WHERE soru_id = ?", (soru_id,))[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]
    session["bildirim"] = {"tur": "info", "metin": f"Soru #{soru_id} silindi."}[cite: 1]
    return redirect(url_for("soru_yonetimi"))[cite: 1]

@app.route("/yedek-indir")
@giris_zorunlu
def yedek_indir():
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("SELECT ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no FROM sorular")[cite: 1]
    sorular = [dict(r) for r in cursor.fetchall()][cite: 1]
    conn.close()[cite: 1]

    dosya_metni = json.dumps(sorular, ensure_ascii=False, indent=2)[cite: 1]
    tarih_etiketi = datetime.now().strftime("%Y%m%d_%H%M")[cite: 1]
    return Response(
        dosya_metni,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename=auzef_soru_yedegi_{tarih_etiketi}.json"}
    )[cite: 1]

@app.route("/yedek-yukle", methods=["POST"])
@giris_zorunlu
def yedek_yukle():
    dosya = request.files.get("yedek_dosyasi")[cite: 1]
    if not dosya or not dosya.filename.lower().endswith(".json"):[cite: 1]
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir .json dosyası yükleyin."}[cite: 1]
        return redirect(url_for("ana_sayfa"))[cite: 1]

    try:
        veri = json.load(dosya)[cite: 1]
        conn = veritabani_baglan()[cite: 1]
        cursor = conn.cursor()[cite: 1]
        eklenen = 0[cite: 1]
        for s in veri:[cite: 1]
            cursor.execute("""
                INSERT INTO sorular (ders_adi, soru_metni, secenek_a, secenek_b, secenek_c, secenek_d, secenek_e, dogru_cevap, aciklama, yildizli, kullanici_notu, unite_no)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                s.get("ders_adi", ""), s.get("soru_metni", ""), s.get("secenek_a", ""), s.get("secenek_b", ""),
                s.get("secenek_c", ""), s.get("secenek_d", ""), s.get("secenek_e", ""), s.get("dogru_cevap", "A"),
                s.get("aciklama", ""), s.get("yildizli", 0), s.get("kullanici_notu", ""), s.get("unite_no", 0)
            ))[cite: 1]
            eklenen += 1[cite: 1]
        conn.commit()[cite: 1]
        conn.close()[cite: 1]
        session["bildirim"] = {"tur": "success", "metin": f"Yedekten {eklenen} soru başarıyla yüklendi."}[cite: 1]
    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"Hata: {str(e)}"}[cite: 1]

    return redirect(url_for("ana_sayfa"))[cite: 1]

@app.route("/sifirla", methods=["POST"])
@giris_zorunlu
def veritabani_sifirla():
    conn = veritabani_baglan()[cite: 1]
    cursor = conn.cursor()[cite: 1]
    cursor.execute("DELETE FROM sorular")[cite: 1]
    cursor.execute("DELETE FROM performans")[cite: 1]
    cursor.execute("DELETE FROM sinav_gecmisi")[cite: 1]
    cursor.execute("DELETE FROM unite_kaynaklari")[cite: 1]
    cursor.execute("DELETE FROM unite_takip")[cite: 1]
    cursor.execute("DELETE FROM ders_videolari")[cite: 1]
    cursor.execute("DELETE FROM unite_ozetleri")[cite: 1]
    conn.commit()[cite: 1]
    conn.close()[cite: 1]

    session.clear()[cite: 1]
    session["bildirim"] = {"tur": "success", "metin": "Tüm veriler, kayıtlı PDF bağlantıları, özetler ve geçmiş silindi."}[cite: 1]
    return redirect(url_for("giris_yap"))[cite: 1]

@app.route("/sw.js")
def service_worker():
    return send_from_directory(os.path.join(app.root_path, "static"), "sw.js", mimetype="application/javascript")[cite: 1]

if __name__ == "__main__":
    app.run(debug=True)[cite: 1]
