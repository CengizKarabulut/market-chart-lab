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

Toplam 10 gösterge; biri hareketli ortalama ailesi, dokuzu diğer türlerden.

| # | Anahtar | Gösterge | Yer |
|---|---------|----------|-----|
| 1 | `ma` | EMA 20 / EMA 50 / SMA 200 | fiyat üstü |
| 2 | `bbands` | Bollinger Bantları 20/2 | fiyat üstü |
| 3 | `supertrend` | Supertrend 10/3 (yöne göre renk değiştirir) | fiyat üstü |
| 4 | `ichimoku` | Ichimoku bulutu 9/26/52 | fiyat üstü |
| 5 | `vwap` | VWAP + standart sapma bandı | fiyat üstü |
| 6 | `volume` | Hacim + 20 barlık ortalama (RVOL) | alt panel |
| 7 | `rsi` | RSI 14 (Wilder) + sinyal ortalaması | alt panel |
| 8 | `macd` | MACD 12/26/9 + histogram | alt panel |
| 9 | `stochrsi` | Stochastic RSI 14/14/3/3 | alt panel |
| 10 | `adx` | ADX / DMI 14 | alt panel |

Wilder yumuşatması (`rma`) kullanan göstergelerde TradingView ile aynı sonuç hedeflenmiştir.
İki ayrıntı özellikle önemsenmiştir:

- **Ichimoku kaydırması** TradingView'daki gibi `displacement - 1` bardır (varsayılan 26 ayarında 25 bar).
  Bu atlanırsa bulut bir bar kayar.
- **VWAP çapası** aralığa göre seçilir: gün içi barlarda seans başında sıfırlanan kümülatif VWAP,
  günlük ve üzeri barlarda 20 barlık hareketli VWAP. Günlük barda seans çapası kullanılırsa
  her grup tek bardan oluşacağı için VWAP fiyatın kendisine eşitlenir ve gösterge anlamsızlaşır.

---

## Kareler (görünümler)

Varsayılan çalıştırma altı kare üretir. Her kare ayrı bir PNG'dir; hepsi **aynı genişlikte**
olduğu için Telegram albümünde hizalı durur.

| Görünüm | Karede ne var |
|---------|---------------|
| `ortalamalar` | Fiyat + EMA20/EMA50/SMA200 · hacim |
| `bollinger` | Bantlar + %B konumu + bant genişliği (sıkışma eşiği ile) |
| `momentum` | Fiyat + RSI · MACD · Stochastic RSI aynı karede |
| `supertrend` | Supertrend + ADX/DMI + hacim |
| `ichimoku` | Bulut (25 bar ileri taşınmış) + ADX |
| `hacim` | VWAP + bandı · hacim · RVOL |
| `tumu` | On göstergenin tamamı tek karede (varsayılan sette yok) |

```bash
python -m src.cli --symbol THYAO                      # 6 kare
python -m src.cli --symbol THYAO --views all          # 7 kare (tumu dahil)
python -m src.cli --symbol THYAO --views momentum     # tek kare
python -m src.cli --symbol THYAO --views bollinger,ichimoku
```

Tüm kareler **tek veri çekimi ve tek hesap turuyla** üretilir: birden fazla karede geçen
göstergeler (örneğin hareketli ortalamalar) yalnızca bir kez hesaplanır.

HTML tarafında altı ayrı dosya değil, **sekmeli tek sayfa** oluşur; kareler arasında
sekmelerle geçilir ve plotly.js yalnızca bir kez yüklenir.

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
| `--views` | `set` | `set` (6 kare), `all` (7 kare) veya virgüllü görünüm listesi |
| `--indicators` | — | Görünüm yerine serbest gösterge listesi; tek kare üretir |
| `--theme` | `ink` | `ink` (koyu) veya `paper` (açık) |
| `--project-bars` | `25` | Ichimoku bulutunun fiyatın kaç bar önüne taşınacağı |
| `--embed-js` | kapalı | Plotly'yi HTML içine gömer; çevrimdışı açılır (~3 MB) |

---

## Mimari

```
src/
  views.py          kare tanımları: hangi göstergeler hangi karede
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
python -m src.cli --symbol THYAO --telegram
```

## GitHub Actions

`Actions → Grafik Üret → Run workflow` ile sembol, aralık ve kare seti seçilerek çalıştırılır.
Çıktılar hem artifact olarak yüklenir hem de istenirse Telegram'a gönderilir.
`TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` depo secret'ı olarak tanımlanmalıdır.

## Testler

```bash
python -m unittest discover -s tests -t .
```

39 test, hepsi ağsız; sentetik OHLCV serisi üretilir. Gösterge testleri Wilder RMA'sını
elle hesaplanmış değerlerle, Ichimoku kaydırmasını bar sayısıyla ve MACD histogramını
kimlik bağıntısıyla doğrular. Kare testleri her görünümün geçerli anahtar kullandığını,
yedi karenin on göstergenin tamamını kapsadığını ve kareler arasında özet rakamların
tutarlı kaldığını kontrol eder.

---

Bu depo teknik gösterge görselleştirmesi üretir; **yatırım tavsiyesi değildir**.
