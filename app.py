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
        return f"https://drive.google.com/file/d/{dosya_id}/view?usp=sharing"
    return link

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

    if yuklenen_dosya and yuklenen_dosya.filename != "" and yuklenen_dosya.filename.lower().endswith(".pdf"):
        try:
            pdf_bytes = yuklenen_dosya.read()
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
            session["bildirim"] = {"tur": "danger", "metin": f"Drive dosya çekme hatası: {str(e)}. Cihazdan PDF yüklemeyi deneyin."}
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
        cursor.execute("DELETE FROM unite_ozetleri WHERE TRIM(ders_adi) LIKE ?", (f"%{ders}%",))
        for u_no, maddeler in ayiklanan.items():
            for m in maddeler:
                cursor.execute("INSERT INTO unite_ozetleri (ders_adi, unite_no, madde) VALUES (?, ?, ?)", (ders, u_no, m))

        conn.commit()
        conn.close()

        session["bildirim"] = {"tur": "success", "metin": f"✅ İşlem Başarılı! {len(ayiklanan)} üniteden toplam {toplam_madde} hap bilgi sisteme aktarıldı."}
        return redirect(url_for("ders_calis", ders=ders, unite=1))

    except Exception as e:
        session["bildirim"] = {"tur": "danger", "metin": f"Ayrıştırma hatası oluştu: {str(e)}"}
        return redirect(url_for("icerik_merkezi", ders=ders))

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

def tekil_unite_klasik_soru_ayikla(metin, unite_no):
    bloklar = re.split(r'(?:^|\n)\s*Soru\s*(\d{1,2})\s*:\s*', metin, flags=re.IGNORECASE)
    ham_sorular = []
    
    if len(bloklar) > 1:
        for i in range(1, len(bloklar), 2):
            s_no = bloklar[i].strip()
            icerik = bloklar[i+1].strip()
            satirlar = [s.strip() for s in icerik.splitlines() if s.strip()]
            
            temiz = []
            for s in satirlar:
                if any(x in s.upper() for x in ["FAITH S.", "TELEGRAM", "SON SAYFA"]) or s.isdigit():
                    continue
                temiz.append(s)
            
            if not temiz:
                continue
                
            soru_govdesi = []
            cevap_govdesi = []
            cevap_basladi = False
            
            for s in temiz:
                if not cevap_basladi:
                    soru_govdesi.append(s)
                    if "?" in s or len(soru_govdesi) >= 3:
                        cevap_basladi = True
                else:
                    cevap_govdesi.append(s)
            
            s_metin = " ".join(soru_govdesi).strip()
            c_metin = " ".join(cevap_govdesi).strip()
            
            if not c_metin and len(soru_govdesi) > 1:
                s_metin = " ".join(soru_govdesi[:-1]).strip()
                c_metin = soru_govdesi[-1].strip()
                
            if s_metin and c_metin:
                ham_sorular.append({"soru": s_metin, "cevap": c_metin})

    tum_cevaplar = [x["cevap"] for x in ham_sorular]
    sorular = []
    
    for h in ham_sorular:
        c_dogru = h["cevap"]
        havuz = [c for c in tum_cevaplar if c != c_dogru and len(c) > 1]
        
        secenekler = [c_dogru]
        if len(havuz) >= 4:
            secenekler.extend(random.sample(havuz, 4))
        else:
            secenekler.extend(havuz)
            ekstra = 1
            while len(secenekler) < 5:
                secenekler.append(f"Seçenek {chr(64 + ekstra)}")
                ekstra += 1
                
        random.shuffle(secenekler)
        harfler = ["A", "B", "C", "D", "E"]
        sec_dict = {}
        dogru_harf = "A"
        for idx, harf in enumerate(harfler):
            sec_dict[harf] = secenekler[idx]
            if secenekler[idx] == c_dogru:
                dogru_harf = harf
                
        sorular.append({
            "metin": h["soru"],
            "a": sec_dict["A"],
            "b": sec_dict["B"],
            "c": sec_dict["C"],
            "d": sec_dict["D"],
            "e": sec_dict["E"],
            "dogru_cevap": dogru_harf,
            "aciklama": f"Doğru Cevap: {c_dogru}"
        })
        
    return sorular

@app.route("/yukle-unite-sorulari", methods=["POST"])
@giris_zorunlu
def yukle_unite_sorulari():
    ders = request.form.get("ders_adi", "").strip()
    unite_no = int(request.form.get("unite_no", 1))
    dosya = request.files.get("soru_dosyasi")

    if not dosya or not dosya.filename.lower().endswith(".pdf"):
        session["bildirim"] = {"tur": "danger", "metin": "Lütfen geçerli bir soru PDF'i seçin."}
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

    sorular = tekil_unite_klasik_soru_ayikla(metin, unite_no)

    if not sorular:
        session["bildirim"] = {"tur": "warning", "metin": f"PDF okundu ancak {unite_no}. üniteye ait soru algılanamadı."}
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
        SELECT id FROM sorular 
        WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
        ORDER BY id ASC
    """, (f"%{ders}%", unite_no))
    satirlar = cursor.fetchall()
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
                WHERE TRIM(ders_adi) LIKE ? AND (unite_no BETWEEN 1 AND 7 OR unite_no = 0)
            """, (f"%{ders}%",))
            aktif_ders_adi = f"{ders} (Vize Konuları)"
        elif unite_secim.startswith("UNITE_"):
            u_no = int(unite_secim.replace("UNITE_", ""))
            cursor.execute("""
                SELECT id FROM sorular 
                WHERE TRIM(ders_adi) LIKE ? AND unite_no = ?
            """, (f"%{ders}%", u_no))
            aktif_ders_adi = f"{ders} (Ünite {u_no})"
        else:
            cursor.execute("""
                SELECT id FROM sorular 
                WHERE TRIM(ders_adi) LIKE ?
            """, (f"%{ders}%",))
            aktif_ders_adi = ders

    satirlar = cursor.fetchall()
    conn.close()

    if not satirlar and ders != "HEPSI":
        conn = veritabani_baglan()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM sorular WHERE TRIM(ders_adi) LIKE ?", (f"%{ders}%",))
        satirlar = cursor.fetchall()
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
    cursor.execute("SELECT * FROM sorular WHERE id = ?", (aktif_id,))
    row = cursor.fetchone()
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
            cursor.execute("INSERT OR IGNORE INTO performans (soru_id, dogru_sayisi, yanlis_sayisi, son_durum) VALUES (?, 0, 0, '')", (soru["id"],))
            if durum == "DOGRU":
                cursor.execute("UPDATE performans SET dogru_sayisi = dogru_sayisi + 1, son_durum = 'DOGRU' WHERE soru_id = ?", (soru["id"],))
            elif durum == "YANLIS":
                cursor.execute("UPDATE performans SET yanlis_sayisi = yanlis_sayisi + 1, son_durum = 'YANLIS' WHERE soru_id = ?", (soru["id"],))
            conn.commit()
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
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (simdi, aktif_ders, dogru, yanlis, bos, round(net, 2), round(puan, 1)))

        for c in cevaplar:
            if "soru_id" in c:
                s_id = c["soru_id"]
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
        session["bildirim"] = {"tur": "success", "metin": f"Yedekten {eklenen} soru başarıyla yüklendi."}
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
