"""The place-search benchmark: real Egyptian queries with ground truth that does NOT come from the
data under test.

Every PLACE target is a real place written down from knowledge of Egypt — its usual names in
Arabic / English / Franco and where it is (`near`, with a radius that is honest about how well the
point is known). A result counts when its name matches one of `names` (normalized word containment,
the same textnorm the index uses) AND it lies within `r` metres of `near`.

CATEGORY targets are judged on the results themselves: the right search category, within `km` of
the anchor (or of the route / destination), and the nearest one compared with the nearest one any
source knows (the oracle).

Fields
  q       the text typed / spoken
  at      anchor key (ANCHORS) — where the user is
  g       group (what the query tests)       s  style: ar | en | franco | typo | colloquial | mixed
  place   {"names": [...], "near": (lat, lng), "r": metres}
  cat     {"scat": id, "km": max distance}
  route   key in ROUTES (along-route queries)   dest  (lat, lng) (near-destination queries)
"""

ANCHORS = {
    # Cairo
    "maadi": (29.9602, 31.2569, "cairo"), "downtown": (30.0444, 31.2357, "cairo"),
    "nasr": (30.0561, 31.3301, "cairo"), "heliopolis": (30.0911, 31.3220, "cairo"),
    "newcairo": (30.0074, 31.4913, "cairo"), "shubra": (30.1100, 31.2450, "cairo"),
    "helwan": (29.8500, 31.3340, "cairo"), "zamalek": (30.0614, 31.2197, "cairo"),
    "mokattam": (30.0130, 31.3020, "cairo"),
    # Giza
    "dokki": (30.0384, 31.2122, "giza"), "mohandessin": (30.0560, 31.2000, "giza"),
    "haram": (30.0050, 31.1600, "giza"), "october": (29.9714, 30.9440, "giza"),
    "zayed": (30.0440, 30.9800, "giza"),
    # Alexandria
    "raml": (31.2001, 29.9187, "alexandria"), "smouha": (31.2150, 29.9450, "alexandria"),
    "montaza": (31.2830, 30.0150, "alexandria"), "agami": (31.1000, 29.7700, "alexandria"),
    # Delta and Canal
    "banha": (30.4660, 31.1840, "qalyubia"), "shubra_kheima": (30.1286, 31.2422, "qalyubia"),
    "mansoura": (31.0409, 31.3785, "dakahlia"), "zagazig": (30.5877, 31.5020, "sharqia"),
    "tenth": (30.3060, 31.7420, "sharqia"), "tanta": (30.7865, 31.0004, "gharbia"),
    "mahalla": (30.9697, 31.1669, "gharbia"), "shebin": (30.5580, 31.0110, "monufia"),
    "damanhour": (31.0341, 30.4682, "beheira"), "kafrsheikh": (31.1107, 30.9388, "kafr_el_sheikh"),
    "damietta": (31.4165, 31.8133, "damietta"), "portsaid": (31.2653, 32.3019, "port_said"),
    "ismailia": (30.5965, 32.2715, "ismailia"), "suez": (29.9668, 32.5498, "suez"),
    # Upper Egypt
    "faiyum": (29.3084, 30.8428, "faiyum"), "benisuef": (29.0661, 31.0994, "beni_suef"),
    "minya": (28.1099, 30.7503, "minya"), "asyut": (27.1809, 31.1837, "asyut"),
    "sohag": (26.5591, 31.6957, "sohag"), "qena": (26.1551, 32.7160, "qena"),
    "luxor": (25.6872, 32.6396, "luxor"), "aswan": (24.0889, 32.8998, "aswan"),
    # Coasts, Sinai, desert
    "hurghada": (27.2579, 33.8116, "red_sea"), "sharm": (27.9158, 34.3299, "south_sinai"),
    "dahab": (28.4920, 34.5130, "south_sinai"), "arish": (31.1316, 33.7984, "north_sinai"),
    "matrouh": (31.3525, 27.2373, "matrouh"), "kharga": (25.4390, 30.5586, "new_valley"),
}

ROUTES = {
    # Cairo → Alexandria desert road (waypoints on the road)
    "cairo_alex": [(30.0600, 31.0320), (30.1300, 30.9600), (30.2300, 30.8500), (30.3600, 30.6900),
                   (30.5000, 30.5300), (30.6500, 30.3600), (30.8300, 30.1900), (31.0200, 30.0100),
                   (31.1500, 29.9200)],
    # Ring road, Maadi → Nasr City → Salam
    "ring_east": [(29.9750, 31.2950), (30.0100, 31.3250), (30.0500, 31.3650), (30.0900, 31.3850),
                  (30.1300, 31.3800)],
    # Cairo → Ain Sokhna road
    "sokhna": [(29.9900, 31.4200), (29.9600, 31.6000), (29.8800, 31.8500), (29.7600, 32.1200),
               (29.6600, 32.3300)],
}

Q = []


def P(q, at, g, s, names, near, r=1500):
    Q.append({"q": q, "at": at, "g": g, "s": s, "place": {"names": names, "near": near, "r": r}})


def C(q, at, g, s, scat, km, **kw):
    e = {"q": q, "at": at, "g": g, "s": s, "cat": {"scat": scat, "km": km}}
    e.update(kw)
    Q.append(e)


# ── colloquial category queries (the «بنزينة قريبة» class) ──────────────────────
C("بنزينة قريبة", "maadi", "fuel", "colloquial", "gas_station", 4)
C("بنزينه", "nasr", "fuel", "colloquial", "gas_station", 4)
C("محطة بنزين", "tanta", "fuel", "ar", "gas_station", 6)
C("gas station near me", "newcairo", "fuel", "en", "gas_station", 5)
C("banzina", "october", "fuel", "franco", "gas_station", 6)
C("بنزينة", "asyut", "fuel", "colloquial", "gas_station", 8)
C("محطة وقود", "aswan", "fuel", "ar", "gas_station", 8)
C("بنزينة", "hurghada", "fuel", "colloquial", "gas_station", 8)
C("بنزينة", "mansoura", "fuel", "colloquial", "gas_station", 6)
C("بنزينة", "arish", "fuel", "colloquial", "gas_station", 10)
C("صيدلية قريبة", "maadi", "pharmacy", "colloquial", "pharmacy", 2)
C("اجزخانة", "shubra", "pharmacy", "colloquial", "pharmacy", 2)
C("pharmacy", "zamalek", "pharmacy", "en", "pharmacy", 2)
C("saydaleya", "mohandessin", "pharmacy", "franco", "pharmacy", 2)
C("صيدليه", "zagazig", "pharmacy", "typo", "pharmacy", 3)
C("صيدلية", "sohag", "pharmacy", "ar", "pharmacy", 4)
C("صيدلية", "kharga", "pharmacy", "ar", "pharmacy", 6)
C("صيدلية", "damanhour", "pharmacy", "ar", "pharmacy", 3)
C("صيدلية", "benisuef", "pharmacy", "ar", "pharmacy", 3)
C("صيدلية فاتحة دلوقتي", "heliopolis", "pharmacy", "colloquial", "pharmacy", 2)
C("مستشفى", "helwan", "hospital", "ar", "hospital", 8)
C("مستشفى طوارئ", "dokki", "hospital", "colloquial", "hospital", 6)
C("hospital", "smouha", "hospital", "en", "hospital", 6)
C("مستشفى", "minya", "hospital", "ar", "hospital", 8)
C("مستشفى", "qena", "hospital", "ar", "hospital", 10)
C("مستشفى", "matrouh", "hospital", "ar", "hospital", 10)
C("كافيه", "newcairo", "cafe", "colloquial", "cafe", 2)
C("قهوة", "downtown", "cafe", "colloquial", "cafe", 1.5)
C("ahwa", "raml", "cafe", "franco", "cafe", 2)
C("coffee shop", "zayed", "cafe", "en", "cafe", 3)
C("كافيه", "portsaid", "cafe", "colloquial", "cafe", 3)
C("مطعم", "mansoura", "restaurant", "ar", "restaurant", 3)
C("مطعم قريب", "faiyum", "restaurant", "colloquial", "restaurant", 4)
C("restaurant", "sharm", "restaurant", "en", "restaurant", 4)
C("كشري", "downtown", "restaurant", "colloquial", "koshary", 3)
C("فول وطعمية", "shubra", "restaurant", "colloquial", "restaurant", 3)
C("مشويات", "haram", "restaurant", "colloquial", "grill", 4)
C("سمك", "damietta", "restaurant", "colloquial", "seafood", 5)
C("بيتزا", "smouha", "restaurant", "ar", "pizza", 4)
C("فاست فود", "heliopolis", "restaurant", "colloquial", "fast_food", 3)
C("ماكينة صراف", "nasr", "money", "ar", "atm", 2)
C("atm", "luxor", "money", "en", "atm", 4)
C("صراف آلي", "ismailia", "money", "ar", "atm", 4)
C("عايز اسحب فلوس", "mohandessin", "money", "colloquial", "atm", 2)
C("بنك", "tanta", "money", "ar", "bank", 3)
C("bank", "hurghada", "money", "en", "bank", 6)
C("مسجد", "maadi", "worship", "ar", "mosque", 1.5)
C("جامع قريب", "asyut", "worship", "colloquial", "mosque", 2)
C("كنيسة", "shubra", "worship", "ar", "church", 3)
C("سوبر ماركت", "zamalek", "grocery", "ar", "supermarket", 1.5)
C("ماركت", "mahalla", "grocery", "colloquial", "supermarket", 3)
C("supermarket", "october", "grocery", "en", "supermarket", 4)
C("فرن عيش", "shebin", "grocery", "colloquial", "bakery", 3)
C("مكوجي", "dokki", "services", "colloquial", "laundry", 2)
C("حلاق", "mansoura", "services", "colloquial", "barber", 3)
C("جيم", "newcairo", "services", "colloquial", "gym", 4)
C("gym", "sharm", "services", "en", "gym", 6)
C("ميكانيكي", "faiyum", "car", "colloquial", "car_repair", 6)
C("ورشة عربيات", "nasr", "car", "colloquial", "car_repair", 4)
C("كاوتش", "benisuef", "car", "colloquial", "tyre_shop", 6)
C("غسيل عربيات", "zayed", "car", "colloquial", "car_wash", 6)
C("جراج", "downtown", "car", "colloquial", "parking", 2)
C("قسم شرطة", "maadi", "government", "ar", "police", 5)
C("قسم", "zagazig", "government", "colloquial", "police", 5)
C("مرور", "october", "government", "colloquial", "traffic_department", 15)
C("سجل مدني", "heliopolis", "government", "ar", "civil_registry", 8)
C("شهر عقاري", "mansoura", "government", "ar", "real_estate_registry", 8)
C("مكتب بريد", "asyut", "government", "ar", "post_office", 5)
C("بوستة", "tanta", "government", "colloquial", "post_office", 5)
C("مدرسة", "kafrsheikh", "education", "ar", "school", 3)
C("حضانة", "nasr", "education", "colloquial", "kindergarten", 3)
C("جامعة", "minya", "education", "ar", "university", 10)
C("محطة مترو", "dokki", "transport", "ar", "metro_station", 3)
C("موقف ميكروباص", "haram", "transport", "colloquial", "bus_station", 6)
C("محطة قطر", "benisuef", "transport", "colloquial", "train_station", 6)
C("مول", "smouha", "mall", "ar", "mall", 6)
C("محل ملابس", "mohandessin", "shopping", "colloquial", "clothing_store", 2)
C("محل موبايلات", "sohag", "shopping", "colloquial", "mobile_shop", 3)
C("دكتور اسنان", "maadi", "health", "colloquial", "dentist", 3)
C("وجعني ضرسي", "zagazig", "health", "colloquial", "dentist", 4)
C("معمل تحاليل", "tanta", "health", "ar", "medical_lab", 3)
C("مركز اشعة", "nasr", "health", "ar", "radiology", 4)
C("دكتور بيطري", "october", "health", "colloquial", "veterinary", 8)
C("فندق", "luxor", "lodging", "ar", "hotel", 4)
C("hotel", "dahab", "lodging", "en", "hotel", 4)
C("شاطئ", "matrouh", "leisure", "ar", "beach", 15)
C("سينما", "nasr", "leisure", "ar", "cinema", 6)
C("نادي", "zagazig", "leisure", "colloquial", "sports_club", 6)
# along route / near destination
C("بنزينة على الطريق", "october", "along_route", "colloquial", "gas_station", 2, route="cairo_alex")
C("استراحة على الطريق", "october", "along_route", "colloquial", "rest_area", 3, route="cairo_alex")
C("صيدلية في الطريق", "maadi", "along_route", "colloquial", "pharmacy", 1.5, route="ring_east")
C("بنزينة في السكة", "newcairo", "along_route", "colloquial", "gas_station", 2, route="sokhna")
C("صيدلية جنب الوصول", "maadi", "near_dest", "colloquial", "pharmacy", 1.5, dest=(30.0729, 31.3456))
C("مطعم عند الوصول", "downtown", "near_dest", "colloquial", "restaurant", 2, dest=(31.2001, 29.9187))
C("صيدلية في المعادي", "nasr", "in_area", "ar", "pharmacy", 3, center=(29.9602, 31.2569))
C("بنزينة في مدينة نصر", "maadi", "in_area", "ar", "gas_station", 4, center=(30.0561, 31.3301))

# ── chains ───────────────────────────────────────────────────────────────────
def B(q, at, s, names, km=12):
    Q.append({"q": q, "at": at, "g": "chain", "s": s, "brand": {"names": names, "km": km}})


B("العزبي", "maadi", "ar", ["العزبي", "ezaby", "elezaby"])
B("صيدليات العزبي", "mansoura", "ar", ["العزبي", "ezaby"], 15)
B("el ezaby", "heliopolis", "en", ["العزبي", "ezaby"])
B("صيدليه العزبى", "nasr", "typo", ["العزبي", "ezaby"])
B("سيف", "dokki", "ar", ["سيف", "seif"])
B("صيدليات رشدي", "raml", "ar", ["رشدي", "rushdy", "roshdy"])
B("كارفور", "maadi", "ar", ["كارفور", "carrefour"], 15)
B("carfour", "smouha", "typo", ["كارفور", "carrefour"], 15)
B("هايبر وان", "zayed", "ar", ["هايبر وان", "hyper one", "hyperone"], 15)
B("سبينيز", "newcairo", "ar", ["سبينيز", "spinneys"], 15)
B("خير زمان", "shubra", "ar", ["خير زمان", "kheir zaman"])
B("اولاد رجب", "haram", "ar", ["رجب", "ragab"])
B("فتح الله", "raml", "ar", ["فتح الله", "fathalla"])
B("ماكدونالدز", "nasr", "ar", ["ماكدونالدز", "mcdonald"])
B("macdonalds", "tanta", "typo", ["ماكدونالدز", "mcdonald"], 25)
B("كنتاكي", "zagazig", "colloquial", ["كنتاكي", "kfc"], 25)
B("kfc", "aswan", "en", ["كنتاكي", "kfc"], 25)
B("مؤمن", "nasr", "ar", ["مؤمن", "mo'men", "momen"])
B("كوك دور", "downtown", "ar", ["كوك دور", "cook door"])
B("بازوكا", "mohandessin", "ar", ["بازوكا", "bazooka"])
B("بافلو برجر", "newcairo", "typo", ["بافلو", "بافالو", "buffalo"])
B("starbucks", "zamalek", "en", ["ستاربكس", "starbucks"])
B("ستاربكس", "zayed", "ar", ["ستاربكس", "starbucks"], 15)
B("كوستا", "heliopolis", "ar", ["كوستا", "costa"])
B("cilantro", "dokki", "en", ["cilantro", "سيلانترو"])
B("بنك مصر", "shebin", "ar", ["بنك مصر", "banque misr"], 15)
B("البنك الاهلي", "minya", "ar", ["الاهلي", "ahly", "national bank of egypt", "nbe"], 15)
B("cib", "smouha", "en", ["cib", "التجاري الدولي", "commercial international"])
B("فودافون", "portsaid", "ar", ["فودافون", "vodafone"], 10)
B("اورانج", "ismailia", "ar", ["اورانج", "اورنج", "orange"], 10)
B("وي", "faiyum", "ar", ["we", "وي", "المصرية للاتصالات", "telecom egypt"], 15)
B("بي تك", "asyut", "ar", ["بي تك", "btech", "b.tech", "b tech"], 25)
B("وطنية", "nasr", "ar", ["وطنية", "wataniya"], 15)
B("شل", "maadi", "ar", ["شل", "shell"], 15)
B("توتال", "newcairo", "ar", ["توتال", "total"], 15)
B("مصر للبترول", "tanta", "ar", ["مصر للبترول", "misr petroleum"], 25)
B("موبيل", "october", "ar", ["موبيل", "mobil"], 15)
B("بيم", "sohag", "ar", ["بيم", "bim"], 25)
B("كازيون", "damietta", "ar", ["كازيون", "kazyon"], 25)
B("زهران", "raml", "ar", ["زهران", "zahran"], 15)

# ── malls ────────────────────────────────────────────────────────────────────
P("سيتي ستارز", "maadi", "mall", "ar", ["سيتي ستارز", "city stars", "citystars"], (30.0729, 31.3456), 1500)
P("city starz", "downtown", "mall", "typo", ["سيتي ستارز", "city stars", "citystars"], (30.0729, 31.3456), 1500)
P("كايرو فستيفال", "nasr", "mall", "ar", ["كايرو فستيفال", "cairo festival", "festival city"], (30.0287, 31.4085), 1500)
P("cfc mall", "maadi", "mall", "en", ["cairo festival", "كايرو فستيفال", "cfc"], (30.0287, 31.4085), 1500)
P("مول العرب", "zayed", "mall", "ar", ["مول العرب", "mall of arabia"], (30.0063, 30.9739), 2500)
P("mall of arbia", "october", "mall", "typo", ["mall of arabia", "مول العرب"], (30.0063, 30.9739), 2500)
P("مول مصر", "dokki", "mall", "ar", ["مول مصر", "mall of egypt"], (29.9726, 31.0167), 2500)
P("mol masr", "haram", "mall", "franco", ["mall of egypt", "مول مصر"], (29.9726, 31.0167), 2500)
P("بوينت 90", "maadi", "mall", "ar", ["point 90", "بوينت 90", "بوينت تسعين"], (30.0216, 31.4895), 2500)
P("أركان بلازا", "october", "mall", "ar", ["arkan", "اركان"], (30.0199, 31.0053), 2000)  # GT fixed: 3 sources agree
P("المعادي جراند مول", "maadi", "mall", "ar", ["جراند مول", "grand mall"], (29.9585, 31.2672), 2500)
P("سان ستيفانو", "raml", "mall", "ar", ["سان ستيفانو", "san stefano"], (31.2457, 29.9666), 1500)
P("سيتي سنتر اسكندرية", "smouha", "mall", "ar", ["سيتي سنتر", "city centre", "city center"], (31.1660, 29.9320), 4000)
P("سنزو مول", "hurghada", "mall", "ar", ["سنزو", "senzo"], (27.0951, 33.8220), 2000)  # GT fixed: OSM + Meta agree

# ── landmarks, culture ───────────────────────────────────────────────────────
P("الاهرامات", "downtown", "landmark", "ar", ["اهرام", "هرم", "pyramid", "pyramids"], (29.9792, 31.1342), 2500)
P("الاهرمات", "maadi", "landmark", "typo", ["اهرام", "هرم", "pyramid"], (29.9792, 31.1342), 2500)
P("pyramids of giza", "zamalek", "landmark", "en", ["pyramid", "اهرام", "هرم"], (29.9792, 31.1342), 2500)
P("المتحف المصري الكبير", "maadi", "landmark", "ar", ["المتحف المصري الكبير", "grand egyptian museum"], (29.9940, 31.1194), 1500)
P("المتحف المصري", "nasr", "landmark", "ar", ["المتحف المصري", "egyptian museum"], (30.0478, 31.2336), 800)
P("egyptian museum", "dokki", "landmark", "en", ["egyptian museum", "المتحف المصري"], (30.0478, 31.2336), 800)
P("برج القاهرة", "nasr", "landmark", "ar", ["برج القاهرة", "cairo tower"], (30.0459, 31.2243), 700)
P("القلعة", "downtown", "landmark", "ar", ["القلعة", "قلعة صلاح الدين", "citadel"], (30.0287, 31.2599), 1200)
P("2al3a", "maadi", "landmark", "franco", ["قلعة", "citadel"], (30.0287, 31.2599), 1500)
P("خان الخليلي", "maadi", "landmark", "ar", ["خان الخليلي", "khan el khalili", "khan al khalili"], (30.0477, 31.2623), 800)
P("الجامع الأزهر", "nasr", "landmark", "ar", ["الازهر", "al azhar", "al-azhar"], (30.0458, 31.2627), 800)
P("حديقة الأزهر", "heliopolis", "landmark", "ar", ["حديقة الازهر", "al azhar park", "azhar park"], (30.0405, 31.2646), 1000)
P("ميدان التحرير", "maadi", "landmark", "ar", ["التحرير", "tahrir"], (30.0444, 31.2357), 800)
P("الكنيسة المعلقة", "zamalek", "landmark", "ar", ["المعلقة", "hanging church"], (30.0053, 31.2302), 800)
P("الكاتدرائية المرقسية", "shubra", "landmark", "ar", ["الكاتدرائية", "كاتدرائية", "cathedral"], (30.0717, 31.2753), 1500)
P("قصر البارون", "nasr", "landmark", "ar", ["البارون", "baron"], (30.0864, 31.3302), 800)
P("دار الاوبرا", "maadi", "landmark", "ar", ["الاوبرا", "opera"], (30.0425, 31.2243), 1000)
P("مسجد محمد علي", "maadi", "landmark", "ar", ["محمد علي", "muhammad ali", "mohamed ali"], (30.0287, 31.2599), 1200)
P("مكتبة الاسكندرية", "downtown", "landmark", "ar", ["مكتبة الاسكندرية", "bibliotheca alexandrina", "library of alexandria"], (31.2089, 29.9092), 1000)
P("bibliotheca alexandrena", "smouha", "landmark", "typo", ["bibliotheca", "مكتبة الاسكندرية"], (31.2089, 29.9092), 1000)
P("قلعة قايتباي", "montaza", "landmark", "ar", ["قايتباي", "qaitbay", "qaitbey", "kaitbay"], (31.2140, 29.8856), 1000)
P("قصر المنتزه", "raml", "landmark", "ar", ["المنتزه", "montaza", "montazah"], (31.2883, 30.0164), 2000)
P("كوبري ستانلي", "smouha", "landmark", "ar", ["ستانلي", "stanley"], (31.2353, 29.9480), 1000)
P("عمود السواري", "raml", "landmark", "ar", ["عمود السواري", "pompey"], (31.1825, 29.8963), 800)
P("معبد الكرنك", "luxor", "landmark", "ar", ["الكرنك", "karnak"], (25.7188, 32.6573), 1500)
P("karnak temple", "luxor", "landmark", "en", ["karnak", "الكرنك"], (25.7188, 32.6573), 1500)
P("معبد الأقصر", "aswan", "landmark", "ar", ["معبد الاقصر", "luxor temple"], (25.6995, 32.6391), 1000)
P("وادي الملوك", "luxor", "landmark", "ar", ["وادي الملوك", "valley of the kings"], (25.7402, 32.6014), 3000)
P("السد العالي", "aswan", "landmark", "ar", ["السد العالي", "high dam"], (23.9707, 32.8771), 3000)
P("معبد فيلة", "aswan", "landmark", "ar", ["فيلة", "فيله", "philae"], (24.0255, 32.8844), 2000)
P("ابو سمبل", "aswan", "landmark", "ar", ["ابو سمبل", "abu simbel"], (22.3372, 31.6258), 3000)
P("معبد دندرة", "qena", "landmark", "ar", ["دندرة", "دندره", "dendera"], (26.1418, 32.6703), 2000)
P("دير سانت كاترين", "sharm", "landmark", "ar", ["سانت كاترين", "saint catherine", "st. catherine", "st catherine"], (28.5560, 33.9760), 3000)
P("blue hole dahab", "dahab", "landmark", "en", ["blue hole", "البلو هول", "الثقب الازرق"], (28.5719, 34.5375), 2500)
P("خليج نعمة", "sharm", "landmark", "ar", ["نعمة", "naama"], (27.9150, 34.3290), 2500)
P("hurghada marina", "hurghada", "landmark", "en", ["marina", "مارينا"], (27.2269, 33.8416), 2500)
P("بحيرة قارون", "faiyum", "landmark", "ar", ["قارون", "qarun", "karun"], (29.4700, 30.6000), 15000)
P("وادي الريان", "faiyum", "landmark", "ar", ["وادي الريان", "wadi el rayan", "wadi rayan"], (29.2000, 30.4000), 15000)
P("سيوة", "matrouh", "area", "ar", ["سيوة", "سيوه", "siwa"], (29.2032, 25.5195), 15000)
P("السيد البدوي", "mahalla", "landmark", "ar", ["البدوي", "badawi"], (30.7900, 31.0020), 1500)

# ── transport hubs ───────────────────────────────────────────────────────────
P("مطار القاهرة", "maadi", "transport", "ar", ["مطار القاهرة", "cairo international airport", "cairo airport"], (30.1219, 31.4056), 4000)
P("cairo airport", "zayed", "transport", "en", ["cairo international", "cairo airport", "مطار القاهرة"], (30.1219, 31.4056), 4000)
P("مطار برج العرب", "raml", "transport", "ar", ["برج العرب", "borg el arab", "borg al arab"], (30.9177, 29.6964), 4000)
P("مطار الغردقة", "hurghada", "transport", "ar", ["مطار الغردقة", "hurghada international", "hurghada airport"], (27.1783, 33.7994), 4000)
P("مطار شرم الشيخ", "sharm", "transport", "ar", ["مطار شرم", "sharm el sheikh international", "sharm el-sheikh international"], (27.9773, 34.3950), 4000)
P("مطار الاقصر", "luxor", "transport", "ar", ["مطار الاقصر", "luxor international", "luxor airport"], (25.6710, 32.7066), 4000)
P("محطة رمسيس", "maadi", "transport", "ar", ["رمسيس", "ramses", "ramsis", "محطة مصر"], (30.0626, 31.2466), 1500)
P("ma7atet ramsis", "nasr", "transport", "franco", ["رمسيس", "ramses", "محطة مصر"], (30.0626, 31.2466), 1500)
P("محطة سيدي جابر", "montaza", "transport", "ar", ["سيدي جابر", "sidi gaber"], (31.2186, 29.9419), 1200)
P("محطة مصر اسكندرية", "smouha", "transport", "ar", ["محطة مصر", "misr station", "مصر"], (31.1925, 29.9063), 1500)
P("مترو السادات", "dokki", "transport", "ar", ["السادات", "sadat"], (30.0441, 31.2355), 800)

# ── hospitals ────────────────────────────────────────────────────────────────
P("مستشفى القصر العيني", "maadi", "hospital", "ar", ["القصر العيني", "قصر العيني", "kasr el aini", "kasr al ainy", "qasr el eyni"], (30.0310, 31.2290), 1500)
P("قصر العيني", "nasr", "hospital", "ar", ["القصر العيني", "قصر العيني", "kasr"], (30.0310, 31.2290), 1500)
P("مستشفى الدمرداش", "maadi", "hospital", "ar", ["الدمرداش", "demerdash", "el demerdash"], (30.0770, 31.2780), 1500)
P("مستشفى السلام الدولي", "nasr", "hospital", "ar", ["السلام الدولي", "as-salam international", "as salam international", "assalam international"], (29.9850, 31.2310), 2500)
P("مستشفي السلام الدولى", "maadi", "hospital", "typo", ["السلام الدولي", "as-salam international", "as salam international"], (29.9850, 31.2310), 2500)
P("مستشفى 57357", "heliopolis", "hospital", "ar", ["57357"], (30.0234, 31.2426), 1500)
P("مستشفى دار الفؤاد", "dokki", "hospital", "ar", ["دار الفؤاد", "dar al fouad", "dar el fouad"], (29.9867, 30.9655), 4000)
P("مستشفى كليوباترا", "nasr", "hospital", "ar", ["كليوباترا", "cleopatra"], (30.0930, 31.3240), 2500)
P("مستشفى السعودي الالماني", "heliopolis", "hospital", "ar", ["السعودي الالماني", "saudi german"], (30.1180, 31.3600), 4000)
P("mostashfa el mansoura el gam3y", "mansoura", "hospital", "franco", ["المنصورة", "mansoura"], (31.0420, 31.3600), 3000)
P("مستشفى طنطا الجامعي", "tanta", "hospital", "ar", ["طنطا الجامعي", "tanta university"], (30.7920, 31.0000), 3000)
P("مستشفى اسيوط الجامعي", "asyut", "hospital", "ar", ["اسيوط الجامعي", "assiut university", "asyut university"], (27.1850, 31.1700), 3000)
P("مستشفى الغردقة العام", "hurghada", "hospital", "ar", ["الغردقة العام", "hurghada general"], (27.2470, 33.8150), 4000)
P("مستشفى أسوان الجامعي", "aswan", "hospital", "ar", ["اسوان الجامعي", "aswan university"], (24.0900, 32.9000), 5000)
P("مستشفى المواساة", "smouha", "hospital", "ar", ["المواساة", "المواساه", "mowasat", "el mowasah"], (31.2030, 29.9240), 2500)

# ── universities, government, institutions ──────────────────────────────────
P("جامعة القاهرة", "maadi", "education", "ar", ["جامعة القاهرة", "cairo university"], (30.0262, 31.2080), 2000)
P("جامعه عين شمس", "maadi", "education", "typo", ["عين شمس", "ain shams"], (30.0764, 31.2848), 2500)
P("الجامعة الامريكية", "maadi", "education", "ar", ["الجامعة الامريكية", "american university"], (30.0199, 31.5008), 3000)
P("auc", "nasr", "education", "en", ["american university", "الجامعة الامريكية", "auc"], (30.0199, 31.5008), 3000)
P("جامعة الاسكندرية", "montaza", "education", "ar", ["جامعة الاسكندرية", "alexandria university"], (31.2090, 29.9170), 3000)
P("جامعة المنصورة", "mansoura", "education", "ar", ["جامعة المنصورة", "mansoura university"], (31.0410, 31.3530), 3000)
P("جامعة الزقازيق", "zagazig", "education", "ar", ["جامعة الزقازيق", "zagazig university"], (30.5880, 31.4830), 4000)
P("جامعة قناة السويس", "ismailia", "education", "ar", ["قناة السويس", "suez canal university"], (30.6200, 32.2700), 4000)
P("مجمع التحرير", "nasr", "government", "ar", ["مجمع التحرير", "mogamma", "the mogamma"], (30.0442, 31.2338), 800)
P("السفارة الامريكية", "maadi", "government", "ar", ["السفارة الامريكية", "embassy of the united states", "u.s. embassy", "us embassy", "american embassy"], (30.0390, 31.2320), 1500)
P("ماسبيرو", "maadi", "government", "ar", ["ماسبيرو", "maspero"], (30.0538, 31.2318), 1500)
P("القرية الذكية", "dokki", "government", "ar", ["القرية الذكية", "smart village"], (30.0716, 31.0187), 3000)
P("استاد القاهرة", "maadi", "leisure", "ar", ["استاد القاهرة", "cairo international stadium", "cairo stadium"], (30.0691, 31.3125), 2000)
P("النادي الاهلي", "maadi", "leisure", "ar", ["النادي الاهلي", "al ahly", "الاهلي"], (30.0565, 31.2213), 2500)
P("nady el ahly", "nasr", "leisure", "franco", ["al ahly", "الاهلي", "ahly"], (30.0565, 31.2213), 2500)
P("نادي الزمالك", "dokki", "leisure", "ar", ["الزمالك", "zamalek"], (30.0517, 31.2103), 2500)
P("حديقة الحيوان", "maadi", "leisure", "ar", ["حديقة الحيوان", "giza zoo", "zoo"], (30.0240, 31.2131), 1500)

# ── small / independent places (single-site, not chains) ─────────────────────
P("كشري ابو طارق", "maadi", "small_local", "ar", ["ابو طارق", "abou tarek", "abu tarek"], (30.0505, 31.2420), 1200)
P("abou tarek", "zamalek", "small_local", "en", ["abou tarek", "ابو طارق", "abu tarek"], (30.0505, 31.2420), 1200)
P("مطعم فلفلة", "maadi", "small_local", "ar", ["فلفلة", "felfela"], (30.0476, 31.2385), 1200)
P("قهوة الفيشاوي", "maadi", "small_local", "ar", ["الفيشاوي", "fishawy", "el fishawy"], (30.0478, 31.2622), 800)
P("زوبا", "zamalek", "small_local", "ar", ["زوبا", "zooba"], (30.0640, 31.2190), 3000)
P("مكتبة ديوان", "zamalek", "small_local", "ar", ["ديوان", "diwan"], (30.0637, 31.2227), 4000)
P("جروبي", "maadi", "small_local", "ar", ["جروبي", "groppi"], (30.0485, 31.2395), 1500)
P("مطعم الدهان", "nasr", "small_local", "ar", ["الدهان", "el dahan", "dahan"], (30.0475, 31.2630), 2500)
P("حلواني العبد", "maadi", "small_local", "ar", ["العبد", "el abd"], (30.0500, 31.2410), 3000)
P("قدورة", "smouha", "small_local", "ar", ["قدورة", "kadoura", "qadoura"], (31.2000, 29.8860), 2500)
P("محمد احمد فول", "smouha", "small_local", "colloquial", ["محمد احمد", "mohamed ahmed"], (31.2000, 29.8990), 2500)
P("بلبع", "montaza", "small_local", "ar", ["بلبع", "balbaa"], (31.2400, 29.9600), 6000)
P("مطعم صبحي كابر", "downtown", "small_local", "ar", ["صبحي كابر", "sobhy kaber"], (30.0870, 31.2400), 4000)
P("ابو حيدر", "maadi", "small_local", "ar", ["ابو حيدر", "abu haidar", "abou haidar", "abo haidar"], (29.9600, 31.2600), 6000)
P("lucille's maadi", "maadi", "small_local", "en", ["lucille"], (29.9605, 31.2575), 1500)
P("أبو السيد", "zamalek", "small_local", "ar", ["ابو السيد", "abou el sid", "abou el seid"], (30.0610, 31.2200), 4000)
P("قهوة ريش", "maadi", "small_local", "ar", ["ريش", "riche"], (30.0478, 31.2396), 1200)

# ── streets and addresses ────────────────────────────────────────────────────
P("شارع 9 المعادي", "nasr", "street", "ar", ["شارع 9", "9", "road 9", "street 9"], (29.9600, 31.2580), 1500)
P("شارع التسعين", "maadi", "street", "ar", ["التسعين", "90"], (30.0215, 31.4700), 9000)  # a 12 km street
P("شارع جامعة الدول العربية", "maadi", "street", "ar", ["جامعة الدول", "gameat el dewal", "arab league"], (30.0546, 31.2035), 2500)
P("شارع فيصل", "dokki", "street", "ar", ["فيصل", "faisal"], (29.9975, 31.1600), 5000)
P("شارع الهرم", "dokki", "street", "ar", ["الهرم", "الاهرام", "haram", "ahram", "pyramids"], (29.9990, 31.1720), 8000)  # official name «شارع الأهرام»
P("شارع عباس العقاد", "maadi", "street", "ar", ["عباس العقاد", "abbas el akkad", "abbas al aqqad"], (30.0606, 31.3417), 2500)
P("ش مكرم عبيد", "heliopolis", "street", "colloquial", ["مكرم عبيد", "makram ebeid", "makram ebid"], (30.0610, 31.3460), 2500)
P("شارع طلعت حرب", "zamalek", "street", "ar", ["طلعت حرب", "talaat harb"], (30.0500, 31.2400), 1500)
P("talaat harb street", "nasr", "street", "en", ["talaat harb", "طلعت حرب"], (30.0500, 31.2400), 1500)
P("طريق صلاح سالم", "maadi", "street", "ar", ["صلاح سالم", "salah salem"], (30.0450, 31.2750), 9000)  # Old Cairo → Heliopolis
P("كوبري اكتوبر", "maadi", "street", "ar", ["اكتوبر", "6 october", "october"], (30.0520, 31.2300), 5000)
P("kobry 6 october", "dokki", "street", "franco", ["اكتوبر", "6 october", "october"], (30.0520, 31.2300), 5000)
P("محور 26 يوليو", "maadi", "street", "ar", ["26 يوليو", "26th of july", "26 july"], (30.0620, 31.0500), 15000)
P("شارع فؤاد", "smouha", "street", "ar", ["فؤاد", "fouad", "fuad", "الحرية", "horreya"], (31.1980, 29.9050), 3000)  # officially «طريق الحرية»
P("طريق الكورنيش اسكندرية", "smouha", "street", "ar", ["الكورنيش", "corniche"], (31.2200, 29.9400), 6000)
P("شارع البحر طنطا", "mahalla", "street", "ar", ["البحر", "el bahr"], (30.7860, 31.0010), 2500)
P("شارع الجمهورية", "asyut", "street", "ar", ["الجمهورية", "gomhoria", "el gomhoreya"], (27.1809, 31.1837), 4000)
P("الطريق الدائري", "maadi", "street", "ar", ["الدائري", "ring road"], (29.9750, 31.2950), 30000)

# ── areas, cities, villages ──────────────────────────────────────────────────
P("المعادي", "nasr", "area", "ar", ["المعادي", "maadi"], (29.9602, 31.2569), 3000)
P("m3ady", "zamalek", "area", "franco", ["المعادي", "maadi"], (29.9602, 31.2569), 3000)
P("مدينة نصر", "maadi", "area", "ar", ["مدينة نصر", "nasr city"], (30.0561, 31.3301), 5000)
P("مصر الجديدة", "maadi", "area", "ar", ["مصر الجديدة", "heliopolis"], (30.0911, 31.3220), 5000)
P("masr el gedida", "dokki", "area", "franco", ["مصر الجديدة", "heliopolis"], (30.0911, 31.3220), 5000)
P("الزمالك", "nasr", "area", "ar", ["الزمالك", "zamalek"], (30.0614, 31.2197), 2500)
P("التجمع الخامس", "maadi", "area", "ar", ["التجمع الخامس", "fifth settlement", "5th settlement", "new cairo"], (30.0074, 31.4613), 7000)
P("el tagamo3", "zamalek", "area", "franco", ["التجمع", "settlement", "new cairo"], (30.0074, 31.4613), 8000)
P("الشيخ زايد", "dokki", "area", "ar", ["الشيخ زايد", "sheikh zayed"], (30.0440, 30.9800), 6000)
P("6 اكتوبر", "maadi", "area", "ar", ["اكتوبر", "october"], (29.9714, 30.9440), 12000)
P("الدقي", "nasr", "area", "ar", ["الدقي", "dokki"], (30.0384, 31.2122), 2500)
P("المهندسين", "maadi", "area", "ar", ["المهندسين", "mohandessin", "mohandeseen"], (30.0560, 31.2000), 3000)
P("سموحة", "raml", "area", "ar", ["سموحة", "smouha"], (31.2150, 29.9450), 3000)
P("العجمي", "raml", "area", "ar", ["العجمي", "agami"], (31.1000, 29.7700), 8000)
P("الرحاب", "maadi", "area", "ar", ["الرحاب", "rehab"], (30.0600, 31.4900), 4000)
P("مدينتي", "nasr", "area", "ar", ["مدينتي", "madinaty"], (30.0900, 31.6400), 6000)
P("العاشر من رمضان", "zagazig", "area", "ar", ["العاشر", "10th of ramadan", "tenth of ramadan"], (30.3060, 31.7420), 12000)
P("ميت غمر", "mansoura", "area", "ar", ["ميت غمر", "mit ghamr"], (30.7169, 31.2628), 4000)
P("كفر الدوار", "raml", "area", "ar", ["كفر الدوار", "kafr el dawar", "kafr ad dawwar"], (31.1339, 30.1297), 5000)
P("منوف", "shebin", "area", "ar", ["منوف", "menouf"], (30.4648, 30.9318), 5000)
P("ملوي", "minya", "area", "ar", ["ملوي", "mallawi"], (27.7310, 30.8410), 5000)
P("ديروط", "asyut", "area", "ar", ["ديروط", "dairut", "dayrout"], (27.5530, 30.8130), 6000)
P("إسنا", "luxor", "area", "ar", ["اسنا", "esna", "isna"], (25.2934, 32.5540), 5000)
P("كوم امبو", "aswan", "area", "ar", ["كوم امبو", "kom ombo"], (24.4760, 32.9480), 6000)
P("طهطا", "sohag", "area", "ar", ["طهطا", "tahta"], (26.7690, 31.5020), 5000)
P("بلبيس", "zagazig", "area", "ar", ["بلبيس", "belbeis", "bilbeis"], (30.4200, 31.5600), 5000)
P("سمنود", "mahalla", "area", "ar", ["سمنود", "samannoud", "samanud"], (30.9610, 31.2420), 4000)
P("رشيد", "damanhour", "area", "ar", ["رشيد", "rashid", "rosetta"], (31.4040, 30.4160), 5000)
P("القنطرة", "ismailia", "area", "ar", ["القنطرة", "qantara", "kantara"], (30.8500, 32.3200), 6000)
P("كرداسة", "haram", "area", "ar", ["كرداسة", "kerdasa"], (30.0300, 31.1100), 4000)
P("راس البر", "damietta", "area", "ar", ["راس البر", "ras el bar", "ras elbar"], (31.5130, 31.8240), 4000)
P("دهب", "sharm", "area", "ar", ["دهب", "dahab"], (28.4920, 34.5130), 6000)
P("الغردقة", "luxor", "area", "ar", ["الغردقة", "hurghada"], (27.2579, 33.8116), 10000)
P("العريش", "ismailia", "area", "ar", ["العريش", "arish", "el arish"], (31.1316, 33.7984), 8000)
P("الخارجة", "asyut", "area", "ar", ["الخارجة", "kharga", "el kharga"], (25.4390, 30.5586), 10000)

# ── far lookups (a famous place from the other end of the country) ───────────
P("مول مصر", "aswan", "far", "ar", ["مول مصر", "mall of egypt"], (29.9726, 31.0167), 2500)
P("مستشفى 57357", "raml", "far", "ar", ["57357"], (30.0234, 31.2426), 1500)
P("مكتبة الاسكندرية", "aswan", "far", "ar", ["مكتبة الاسكندرية", "bibliotheca alexandrina"], (31.2089, 29.9092), 1000)
P("سيتي ستارز", "hurghada", "far", "ar", ["سيتي ستارز", "city stars", "citystars"], (30.0729, 31.3456), 1500)
P("معبد الكرنك", "raml", "far", "ar", ["الكرنك", "karnak"], (25.7188, 32.6573), 1500)
P("cairo festival city", "sharm", "far", "en", ["festival city", "كايرو فستيفال"], (30.0287, 31.4085), 1500)

# ── Qalyubia, Suez ───────────────────────────────────────────────────────────
C("صيدلية", "banha", "pharmacy", "ar", "pharmacy", 3)
C("بنزينة", "shubra_kheima", "fuel", "colloquial", "gas_station", 4)
C("مستشفى", "banha", "hospital", "ar", "hospital", 6)
P("جامعة بنها", "shubra_kheima", "education", "ar", ["جامعة بنها", "benha university"], (30.4550, 31.1870), 5000)
C("بنزينة", "suez", "fuel", "colloquial", "gas_station", 6)
C("مستشفى", "suez", "hospital", "ar", "hospital", 8)
P("بور توفيق", "suez", "area", "ar", ["بور توفيق", "port tawfik", "port tewfik"], (29.9370, 32.5600), 3000)

# ── more typos and Franco ────────────────────────────────────────────────────
C("صيدلبة", "nasr", "pharmacy", "typo", "pharmacy", 2)
C("مستشفئ", "tanta", "hospital", "typo", "hospital", 6)
C("بنزنيه", "maadi", "fuel", "typo", "gas_station", 4)
C("اجزخانه", "mansoura", "pharmacy", "typo", "pharmacy", 3)
B("ماكدونلدز", "heliopolis", "typo", ["ماكدونالدز", "mcdonald"])
B("فودفون", "nasr", "typo", ["فودافون", "vodafone"])
B("starbuks", "newcairo", "typo", ["ستاربكس", "starbucks"])
P("سيتي ستار", "heliopolis", "mall", "typo", ["سيتي ستارز", "city stars", "citystars"], (30.0729, 31.3456), 1500)
P("cairo festivel", "heliopolis", "mall", "typo", ["festival city", "كايرو فستيفال"], (30.0287, 31.4085), 1500)
P("karnack", "luxor", "landmark", "typo", ["karnak", "الكرنك"], (25.7188, 32.6573), 1500)
P("zamalk", "dokki", "area", "typo", ["الزمالك", "zamalek"], (30.0614, 31.2197), 2500)
P("mohandesin", "maadi", "area", "typo", ["المهندسين", "mohandessin", "mohandeseen"], (30.0560, 31.2000), 3000)
P("heliopolice", "maadi", "area", "typo", ["heliopolis", "مصر الجديدة"], (30.0911, 31.3220), 5000)
P("مستشفي الدمرداش", "shubra", "hospital", "typo", ["الدمرداش", "demerdash"], (30.0770, 31.2780), 1500)
B("saydaleyet seif", "zamalek", "franco", ["سيف", "seif"])
P("el ma3adi", "heliopolis", "area", "franco", ["المعادي", "maadi"], (29.9602, 31.2569), 3000)
P("khan el 5alily", "nasr", "landmark", "franco", ["خان الخليلي", "khan el khalili", "khan al khalili"], (30.0477, 31.2623), 800)
P("gam3et el qahera", "maadi", "education", "franco", ["جامعة القاهرة", "cairo university"], (30.0262, 31.2080), 2000)
