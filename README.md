# market-chart-lab

BIST hisseleri, yabancı hisseler ve kripto paralar için **göstergeli fiyat grafiği** üretir.
Aynı veriden iki çıktı çıkar:

- **PNG** — Telegram'a fotoğraf olarak gönderilebilen statik grafik
- **HTML** — zoom, hover ve seri açıp kapatma destekli etkileşimli sayfa (Plotly)

`stock-technical-telegram` deposundan farkı: orada göstergeler sayı ve tablo olarak
raporlanıyordu, burada **grafiğin üstünde çiziliyor**.

Göstergeler tek bir dev grafiğe yığılmaz; her biri 2–4 katman taşıyan **odaklı karelere**
bölünür. Bollinger'e bakarken MACD gürültüsü, momentuma bakarken bulut karmaşası ekranı
meşgul etmez.

---

## Göstergeler

Dört kategoriden toplam 19 gösterge. Kareler her kategoriden birer tane seçer.

| Kategori | Göstergeler |
|---|---|
| **Trend** | EMA/SMA, Supertrend, Ichimoku, Parabolic SAR, ADX/DMI |
| **Momentum** | RSI, MACD, Stochastic RSI, CCI, Williams %R, Awesome Oscillator |
| **Volatilite** | Bollinger, ATR, Keltner, Donchian |
| **Hacim** | Hacim/RVOL, VWAP, OBV, Volume Profile (VPVR) |

Wilder yumuşatması (`rma`) kullanan göstergelerde TradingView ile aynı sonuç hedeflenmiştir.
Dört ayrıntı özellikle önemsenmiştir:

- **Ichimoku kaydırması** TradingView'daki gibi `displacement - 1` bardır (varsayılan 26
  ayarında 25 bar). Bu atlanırsa bulut bir bar kayar.
- **VWAP çapası** aralığa göre seçilir: gün içi barlarda seans başında sıfırlanan kümülatif
  VWAP, günlük ve üzeri barlarda 20 barlık hareketli VWAP. Günlük barda seans çapası
  kullanılırsa her grup tek bardan oluşacağı için VWAP fiyata eşitlenir.
- **Parabolic SAR** dönüş anlarında son iki barın ucuna kırpılır; bu kırpma atlanırsa
  gösterge fiyatın içine girip yanlış sinyal üretir.
- **Volume Profile** her barın hacmini yüksek–düşük aralığına eşit dağıtır (yalnızca
  kapanışa bakmaz) ve **görünen pencereden** hesaplanır, tüm geçmişten değil.

---

## Kareler ve ızgara

Varsayılan çalıştırma dört kare üretip **tek bir görselde 2×2 ızgara** olarak birleştirir.

**Her karenin yapısı aynı: mum grafiğinin üstünde TEK gösterge, altında kendi ölçeğine
sahip ÜÇ panel.** Fiyat panelinde birden fazla katman üst üste binince grafik okunmaz hale
geliyor; bu kural bir testle korunuyor.

| Kare | Fiyat üstünde | Panel 1 | Panel 2 | Panel 3 |
|---|---|---|---|---|
| Klasik | EMA/SMA *(trend)* | RSI *(momentum)* | Bollinger %B *(volatilite)* | Hacim *(hacim)* |
| Trend takip | Supertrend *(trend)* | MACD *(momentum)* | ATR *(volatilite)* | OBV *(hacim)* |
| Bulut ve kanal | Ichimoku *(trend)* | Stoch RSI *(momentum)* | Keltner konumu *(volatilite)* | VWAP sapması *(hacim)* |
| Kırılım ve dönüş | Parabolic SAR *(trend)* | CCI *(momentum)* | Donchian konumu *(volatilite)* | RVOL *(hacim)* |

Doğası gereği fiyat üstüne binen volatilite göstergeleri panel biçimine çevrilmiştir:
Bollinger yerine **%B** (fiyatın bantlar içindeki konumu), Keltner yerine **kanal içi konum**
(0 = orta bant, ±1 = bantlar), Donchian yerine **kanal yüzdesi** (0 = dip, 100 = tepe),
VWAP yerine **yüzde sapma**. Böylece bilgi kaybolmadan mum grafiği temiz kalır.

Beşinci bir kare de var: `profil` (Volume Profile + Williams %R + bant genişliği + ADX).
Varsayılan sette değil, `--views profil` ile çağrılır.

```bash
python -m src.cli --symbol THYAO                  # 2x2 izgara, tek PNG
python -m src.cli --symbol THYAO --grid 4         # 1x4 yan yana
python -m src.cli --symbol THYAO --grid 0         # birlestirme yok, ayri PNG'ler
python -m src.cli --symbol THYAO --views klasik   # tek kare
python -m src.cli --symbol THYAO --views tumu     # on gosterge tek karede
```

Bir setteki tüm kareler **aynı x aralığını** paylaşır; Ichimoku projeksiyonu varsa hepsine
uygulanır, böylece ızgarada karolar hizalı durur.

Tüm kareler tek veri çekimi ve tek hesap turuyla üretilir.

### Veriyi dürüst gösteren üç davranış

**Tamamlanmamış son bar.** Seans açıkken çekilen veride son bar hâlâ oluşuyordur; RVOL,
RSI ve günlük değişim gün kapanınca değişir. Yarım seansta RVOL doğal olarak 1'in çok
altında görünür ve bu yanıltıcıdır. Bar süresi (barlar arası medyan fark) son barın
başlangıcına eklendiğinde gelecekte kalıyorsa bar açık sayılır: başlıkta `SON BAR AÇIK`
uyarısı çıkar, kare künyesine `● bar açık` eklenir ve o mum soluk çizilir.

**Logaritmik fiyat ekseni.** 100'den 700'e çıkan bir seride lineer eksen ilk ayları ezer.
Görünen aralıkta yüksek/düşük oranı 4'ü aşarsa eksen otomatik log'a geçer; `--scale log`
veya `--scale linear` ile zorlanabilir.

**Aykırı hacim kırpma.** Tek bir devasa hacim barı panelin geri kalanını düz çizgiye
çevirir. Tavan 95. yüzdeliğe göre belirlenir, tavanı aşan barlar mor renkle işaretlenir ve
panel başlığında `3 bar kırpıldı` yazar — aykırı değer gizlenmez, sadece ölçek okunur olur.

### Görünüm

Tema TradingView'ın koyu düzenine yakındır: fiyat ekseni sağda, her işaretli serinin son
değeri kendi renginde bir kutucuk olarak sağ kenarda, panellerin sol üstünde `RSI (14) 56,10`
biçiminde satır içi künye. Sayılar Türkçe biçimlenir (`1.234,56`), ay adları Türkçedir.
Bunlar `locale` ayarından bağımsız yapılır; GitHub Actions'ta Türkçe locale kurulu olmayabilir.

Sağdaki değer etiketleri çakışırsa dikeyde itilir — etiketteki **sayı değişmez**, yalnızca
çizim konumu kayar.

---

## Kurulum

```bash
git clone https://github.com/<kullanici>/market-chart-lab.git
cd market-chart-lab
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Kullanım

```bash
# BIST, günlük, altı kare, hem PNG hem sekmeli HTML
python -m src.cli --symbol THYAO

# Yabancı hisse, saatlik, iki kare
python -m src.cli --symbol AAPL --interval 1h --bars 200 --views momentum,bollinger

# Kripto, serbest gösterge listesi (tek kare üretir)
python -m src.cli --symbol BTC-USD --indicators ma,bbands,rsi,macd --no-png

# Açık zemin teması, geniş PNG
python -m src.cli --symbol ASELS --theme paper --width 2000

# Telegram'a gönder: PNG'ler albüm, HTML dosya olarak
python -m src.cli --symbol GARAN --telegram
```

Çıktılar `out/` klasörüne yazılır.

### Sembol yazımı

| Yazım | Sonuç |
|-------|-------|
| `THYAO` | BIST (borsapy) |
| `AAPL` | yabancı hisse (yfinance) |
| `BTC-USD`, `ETH` | kripto (yfinance) |
| `bist:YENIK` | BIST'e zorla |
| `yf:ASELS.IS` | yfinance'a zorla |
| `crypto:SOL` | `SOL-USD` olarak çözülür |

`AAPL` ile `THYAO` biçimsel olarak ayırt edilemediği için `src/bist_symbols.py` içinde
bir BIST kod listesi tutulur. Yeni halka arzlardan sonra tazelemek için:

```bash
python -m src.bist_symbols --refresh
```

Listede olmayan bir kodu tek seferlik kullanmak için `bist:` öneki yeterlidir.

### Önemli parametreler

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `--interval` | `1d` | `1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo` |
| `--bars` | `250` | Grafikte gösterilecek bar sayısı |
| `--period` | aralığa göre | Çekilecek geçmiş; göstergeler tüm geçmişte hesaplanıp sonra kırpılır |
| `--views` | `set` | `set` (4 kare ızgara), `all` (tümü) veya virgüllü görünüm listesi |
| `--grid` | `2` | Izgara sütun sayısı. `0` = birleştirme yok |
| `--indicators` | — | Görünüm yerine serbest gösterge listesi; tek kare üretir |
| `--scale` | `auto` | `auto` (oran 4'ü aşarsa log), `log`, `linear` |
| `--theme` | `tv` | `tv` (TradingView koyu), `ink`, `paper` (açık) |
| `--project-bars` | `25` | Ichimoku bulutunun fiyatın kaç bar önüne taşınacağı |
| `--embed-js` | kapalı | Plotly'yi HTML içine gömer; çevrimdışı açılır (~3 MB) |

---

## Mimari

```
src/
  views.py          kare tanımları: hangi göstergeler hangi karede
  compose.py        kareleri tek görselde ızgaraya dizen katman
  format.py         Türkçe sayı ve tarih biçimleme (locale'den bağımsız)
  data_sources.py   sembol çözümleme + borsapy/yfinance yönlendirme ve yedekleme
  bist_symbols.py   BIST kod listesi (tazelenebilir)
  indicators.py     10 göstergenin saf pandas hesabı — çizim bağımlılığı yok
  plotspec.py       "ne çizilecek" tarifi: Trace / Panel / ChartSpec
  render_png.py     matplotlib arka ucu
  render_html.py    plotly arka ucu + sayfa kabuğu
  theme.py          renk ve yazı tipi belirteçleri (iki arka uç da buradan okur)
  pipeline.py       veri → gösterge → tarif akışı
  telegram.py       fotoğraf ve dosya gönderimi
  cli.py            komut satırı
```

Tasarımın özü: **gösterge hesabı ile çizim ayrıdır**, ve iki arka uç aynı `ChartSpec`
nesnesini tüketir. Yeni bir gösterge eklemek için `indicators.py`'ye hesabı,
`plotspec.py`'ye bir builder yazmak yeterlidir; PNG ve HTML kendiliğinden günceller.
Yeni bir kare eklemek içinse `views.py`'ye tek bir `View` satırı yazmak yeter.

Her iki arka uçta da x ekseni tarih değil **bar konumudur**; etiketler sonradan takılır.
Bu sayede hafta sonu ve tatil boşlukları oluşmaz ve iki çıktı bar bar örtüşür.

## Telegram

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="-100..."
export TELEGRAM_TOPIC_ID="18"        # istege bagli, forum gruplari icin
python -m src.cli --symbol THYAO --telegram
```

Windows PowerShell'de:

```powershell
$env:TELEGRAM_BOT_TOKEN = "123456:ABC..."
$env:TELEGRAM_CHAT_ID   = "-1003502567927"
$env:TELEGRAM_TOPIC_ID  = "18"
python -m src.cli --symbol THYAO --telegram
```

**Konu (topic) numarası:** grup forum modundaysa mesajın doğru konuya düşmesi için
`message_thread_id` gerekir. Numara `web.telegram.org` bağlantısının sonundaki sayıdır:
`https://web.telegram.org/a/#-1003502567927_18` → chat id `-1003502567927`, konu `18`.
Boş bırakılırsa mesaj grubun genel akışına gider.

Izgara görseli **dosya olarak** gönderilir. Fotoğraf olarak gönderilseydi Telegram uzun
kenarı ~1280 piksele indirir ve künyelerdeki rakamlar okunmaz hale gelirdi.

## GitHub Actions

`Actions → Grafik Üret → Run workflow` ile sembol, aralık ve kare seti seçilerek çalıştırılır.
Çıktılar hem artifact olarak yüklenir hem de istenirse Telegram'a gönderilir. Izgara görseli
geniş olduğu için Telegram'a **dosya olarak** gönderilir; fotoğraf olarak gönderilse Telegram
uzun kenarı ~1280 piksele indirir ve yazılar okunmaz hale gelir.
`TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` depo secret'ı olarak tanımlanmalıdır.

## Testler

```bash
python -m unittest discover -s tests -t .
```

71 test, hepsi ağsız; sentetik OHLCV serisi üretilir. Gösterge testleri Wilder RMA'sını
elle hesaplanmış değerlerle, Ichimoku kaydırmasını bar sayısıyla, MACD histogramını kimlik
bağıntısıyla, Volume Profile'ı toplam hacmin korunmasıyla ve OBV'yi fiyat yönüyle uyumuyla
doğrular. Kare testleri her ızgara karesinin dört kategoriden birer gösterge taşıdığını, hiçbir
göstergenin tekrar etmediğini, karoların aynı x aralığını paylaştığını ve **mum panelinde
tek gösterge + üç alt panel** kuralının hem tanımda hem üretilen `ChartSpec`'te geçerli
olduğunu kontrol eder. Ayrıca kırpma mantığının panellere gerçekten bağlandığını doğrulayan
testler vardır: `clip_outliers` doğru çalışıp panel onu kullanmazsa kırpma sessizce devre
dışı kalırdı.

---

Bu depo teknik gösterge görselleştirmesi üretir; **yatırım tavsiyesi değildir**.
