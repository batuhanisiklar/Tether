# Remote Phone Control

Android telefonu masaustunden goruntulemek ve kontrol etmek icin uc parcali bir sistem:

- **Desktop:** Python 3.11+, PyQt6, `requests`, `websocket-client`
- **Server:** Python, `aiohttp`, WebSocket, PostgreSQL/psycopg2, `bcrypt`
- **Mobile:** Native Android Kotlin, XML layouts, OkHttp, CameraX, MediaProjection, foreground services

## Proje Yapisi

```text
remote_phone_control/
├── desktop_app/          # PyQt6 masaustu uygulamasi
│   ├── main.py           # Desktop entry point
│   ├── config/           # Sabitler ve prefs
│   ├── network/          # HTTP API, WebSocket, MJPEG alici
│   └── ui/               # Pencereler, sayfalar, komponentler, stiller
├── signaling_server/     # aiohttp HTTP/WebSocket server
│   ├── server.py         # Server entry point / app factory
│   ├── auth.py           # Signed auth token islemleri
│   ├── db_client.py      # PostgreSQL client ve schema
│   └── config/
├── mobile_app/           # Android Kotlin uygulamasi
├── requirements.txt      # Ortak Python bagimliliklari
└── .env.example          # Guvenli ortam degiskeni sablonu
```

## Baglanti Akisi

Sistem **12 haneli sabit device address** kullanir.

1. Telefon giris/kayit sirasinda sunucudan 12 haneli adres alir.
2. Telefon WebSocket uzerinden bu adreste bekler.
3. Masaustu uygulamasi kullanici token'i ile sunucuya baglanir.
4. Masaustu, telefonun 12 haneli adresini girerek yetkili eslesme baslatir.
5. Telefon ekran/kamera/ses akisini WebSocket veya yerel MJPEG URL uzerinden iletir.
6. Masaustu komutlari WebSocket uzerinden telefona aktarir.

## Ortam Degiskenleri

Gercek secret degerlerini repoya yazmayin. `.env.example` dosyasini sablon olarak kullanin.

| Degisken | Gerekli | Aciklama |
|---|---:|---|
| `DATABASE_URL` veya `NEON_DB_URL` | Evet | PostgreSQL connection string |
| `AUTH_SECRET` | Evet | Token imzalamak icin uzun rastgele secret |
| `AUTH_TOKEN_TTL_SEC` | Hayir | Token suresi, varsayilan 86400 |
| `APP_ENV` | Hayir | `development`, `test`, `production` gibi ortam adi |
| `ALLOW_DEV_AUTH_SECRET` | Hayir | Sadece lokal gelistirmede `APP_ENV=local` ile `1` yapilabilir |
| `PORT` | Hayir | Server portu, varsayilan 8765 |
| `RPC_SERVER_URL` | Hayir | Desktop icin varsayilan signaling URL override'i |

## Kurulum

### Python ortami

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Signaling Server

```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require"
$env:AUTH_SECRET="long-random-secret"
$env:APP_ENV="production"
python signaling_server/server.py
```

Health check:

```text
GET /health
```

### Desktop App

```powershell
.venv\Scripts\activate
python desktop_app/main.py
```

Desktop uygulamasinda telefonun gosterildigi 12 haneli sabit adresi girin.

### Android App

1. Android Studio ile `mobile_app/` klasorunu acin.
2. Gradle sync tamamlaninca uygulamayi cihaza yukleyin.
3. Login/kayit sonrasi uygulama 12 haneli cihaz adresini gosterir.
4. Uzaktan kontrol icin Android Accessibility iznini etkinlestirin.
5. Ekran paylasimi baslatildiginda MediaProjection iznini onaylayin.

## Guvenlik Notlari

- `AUTH_SECRET` ve DB connection string repoya yazilmamalidir.
- Production'da `wss://` kullanin.
- Android cleartext trafik yalnizca lokal/debug senaryolari icin kullanilmalidir.
- Auth/device bilgileri Android backup kapsamindan cikarilmalidir.

## Gelistirme Kontrolleri

Python syntax:

```powershell
python -m compileall desktop_app signaling_server
```

Android build:

```powershell
cd mobile_app
.\gradlew.bat :app:assembleDebug
```
