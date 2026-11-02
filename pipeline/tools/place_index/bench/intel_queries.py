"""The search-INTELLIGENCE benchmark's data: what a Google-Maps-level search does for an Egyptian.

Every query and every target here is written from knowledge of Egypt, as Egyptians type (mostly
Arabic, colloquial and MSA; some English and Franco) — never from a map service's answer and never
from the index under test. Coordinates are honest about how well they are known: a famous single
site gets 0.6–2.5 km, a place known only by its city gets the city centre and 5 km or more.

Anchors (`at`) are keys of queries.ANCHORS or an explicit (lat, lng).

Judges (one per entry)
  place  {"names", "near", "r"[, "poi"][, "area"][, "scats"]}
         right = a result whose name / alt matches one accepted name (run.names_match) AND lies within
         r metres of near. Optional gates: "poi" — not an area row (a police station, never the census
         district «قسم أول طنطا»); "area" — an area row (the city, not a shop named after it);
         "scats" — the result's search category is one of these (a station, not a fuel station).
  cat    {"scats", "words", "km"}  right = scat in scats, or the name carries one of `words`, within
         km of the user.
  chain  {"names", "km"}           right = the name matches, within km of the user.

Suites
  PREFIX     the full text a user is typing; the runner types it keystroke by keystroke
  EXACT      a real place's full common name exactly as people write it (rank 1 required)
  VARIANT    the same targets under another spelling (ordinals, abbreviations, digits, spacing,
             Franco, nicknames, an English name in Arabic letters)
  NEED       a product / service, not a place name — the shop kinds that sell / do it in Egypt
  SCRIPT     everyday Arabic queries, no judge: how many of the top 5 carry an Arabic name
  IMPORTANT  the places a city cannot be without (security directorate, governorate building, police,
             hospital, university, railway station, stadium) in all 27 governorates + national ones
"""
from __future__ import annotations

from .queries import ANCHORS

REST = ["restaurant", "koshary", "grill", "seafood", "pizza", "burger", "fast_food", "foul_taameya"]


def place(names, near, r=1500, **gates) -> dict:
    d = {"names": list(names), "near": (float(near[0]), float(near[1])), "r": r}
    d.update(gates)
    return {"place": d}


def cat(scats, km, words=()) -> dict:
    return {"cat": {"scats": list(scats), "words": list(words), "km": km}}


def chain(names, km) -> dict:
    return {"chain": {"names": list(names), "km": km}}


# ── known targets (names, near, r[, gates]) — reused by every suite ────────────────────────────
K = {
    # Cairo
    "city_stars": (["سيتي ستارز", "city stars", "citystars"], (30.0729, 31.3456), 1500),
    "cfc": (["كايرو فستيفال", "cairo festival", "festival city", "cfc"], (30.0287, 31.4085), 1500),
    "point90": (["بوينت 90", "بوينت تسعين", "point 90", "point90"], (30.0205, 31.4920), 2500),
    "auc": (["الجامعة الامريكية", "american university in cairo", "american university", "auc"], (30.0199, 31.5008), 3000),
    "ain_shams_uni": (["جامعة عين شمس", "ain shams university"], (30.0764, 31.2848), 2500),
    "azhar_uni": (["جامعة الازهر", "al azhar university", "al-azhar university", "azhar university"], (30.0560, 31.3160), 4000),
    "helwan_uni": (["جامعة حلوان", "helwan university"], (29.8670, 31.3150), 2500),
    "kasr": (["القصر العيني", "قصر العيني", "kasr el aini", "kasr al ainy", "kasr el ainy", "qasr el aini",
              "kasr alainy"], (30.0310, 31.2290), 1500),
    "demerdash": (["الدمرداش", "demerdash", "el demerdash"], (30.0770, 31.2780), 1500),
    "57357": (["57357", "مستشفى سرطان الاطفال", "children's cancer hospital", "childrens cancer hospital",
               "children cancer hospital"], (30.0234, 31.2426), 1500),
    "saudi_german": (["السعودي الالماني", "saudi german"], (30.1180, 31.3600), 4000),
    "ramses": (["رمسيس", "ramses", "ramsis", "محطة مصر", "cairo railway station"], (30.0626, 31.2466), 1500,
               {"scats": ["train_station"]}),
    "metro_sadat": (["السادات", "sadat"], (30.0441, 31.2355), 700, {"scats": ["metro_station"]}),
    "metro_shohadaa": (["الشهداء", "shohadaa", "al shohadaa", "el shohadaa"], (30.0617, 31.2460), 700,
                       {"scats": ["metro_station"]}),
    "metro_ataba": (["العتبة", "attaba", "ataba"], (30.0525, 31.2470), 700, {"scats": ["metro_station"]}),
    "metro_cairo_uni": (["جامعة القاهرة", "cairo university"], (30.0260, 31.2010), 700, {"scats": ["metro_station"]}),
    "tahrir_sq": (["ميدان التحرير", "tahrir square", "midan tahrir", "midan el tahrir"], (30.0444, 31.2357), 700),
    "tahrir_st_dokki": (["شارع التحرير", "tahrir street", "tahrir st", "tahrir road"], (30.0400, 31.2160), 2500),
    "egy_museum": (["المتحف المصري", "egyptian museum"], (30.0478, 31.2336), 800),
    "cairo_tower": (["برج القاهرة", "cairo tower"], (30.0459, 31.2243), 700),
    "citadel": (["القلعة", "قلعة صلاح الدين", "citadel", "salah el din citadel", "saladin citadel",
                 "citadel of saladin"], (30.0287, 31.2599), 1200),
    "mohamed_ali": (["مسجد محمد علي", "محمد علي", "muhammad ali mosque", "mohamed ali mosque", "alabaster mosque"],
                    (30.0287, 31.2599), 1200),
    "khan": (["خان الخليلي", "khan el khalili", "khan al khalili", "khan el-khalili"], (30.0477, 31.2623), 800),
    "hussein": (["مسجد الحسين", "الامام الحسين", "al hussein mosque", "el hussein mosque", "al-hussein mosque"],
                (30.0478, 31.2625), 700),
    "azhar_park": (["حديقة الازهر", "al azhar park", "azhar park"], (30.0405, 31.2646), 1000),
    "hanging": (["الكنيسة المعلقة", "المعلقة", "hanging church"], (30.0053, 31.2302), 800),
    "amr_mosque": (["عمرو بن العاص", "amr ibn al-as", "amr ibn al as", "amr ibn el aas", "amr ebn el aas"],
                   (30.0103, 31.2331), 800),
    "nmec": (["متحف الحضارة", "المتحف القومي للحضارة", "national museum of egyptian civilization", "nmec"],
             (30.0083, 31.2481), 1000),
    "baron": (["قصر البارون", "baron palace", "baron empain"], (30.0864, 31.3302), 800),
    "opera": (["دار الاوبرا", "cairo opera house", "opera house"], (30.0425, 31.2243), 1000),
    "abdeen": (["قصر عابدين", "abdeen palace", "abdin palace"], (30.0429, 31.2472), 800),
    "mogamma": (["مجمع التحرير", "mogamma"], (30.0442, 31.2338), 800),
    "cairo_stadium": (["استاد القاهرة", "ستاد القاهرة", "cairo international stadium", "cairo stadium"],
                      (30.0691, 31.3125), 2000),
    "cairo_airport": (["مطار القاهرة", "cairo international airport", "cairo airport"], (30.1219, 31.4056), 4000),
    "ahly": (["النادي الاهلي", "al ahly club", "al ahly sporting club", "ahly club", "nady el ahly"],
             (30.0520, 31.2215), 2500),
    "zamalek_club": (["نادي الزمالك", "zamalek club", "zamalek sc", "zamalek sporting club"], (30.0517, 31.2103), 1500),
    "nile_city": (["نايل سيتي", "nile city"], (30.0717, 31.2285), 1200),
    "rehab": (["الرحاب", "rehab", "al rehab", "el rehab"], (30.0600, 31.4920), 4000),
    "madinaty": (["مدينتي", "madinaty"], (30.0950, 31.6400), 6000),
    "mivida": (["ميفيدا", "mivida"], (30.0010, 31.5280), 3000),
    "katameya_heights": (["قطامية هايتس", "كاتاميا هايتس", "katameya heights"], (29.9950, 31.4200), 3000),
    "uptown": (["اب تاون كايرو", "uptown cairo"], (30.0300, 31.3000), 3000),
    "mfa": (["وزارة الخارجية", "ministry of foreign affairs"], (30.0550, 31.2320), 1500),
    "cabinet": (["مجلس الوزراء", "council of ministers", "egyptian cabinet"], (30.0400, 31.2370), 1200, {"poi": True}),
    "cbe": (["البنك المركزي", "central bank of egypt"], (30.0495, 31.2420), 1500),
    "nac": (["العاصمة الادارية", "new administrative capital"], (30.0200, 31.7600), 10000),
    "iconic_tower": (["البرج الايقوني", "iconic tower"], (30.0200, 31.7350), 6000),
    "semiramis": (["سميراميس", "semiramis"], (30.0435, 31.2318), 800),
    "marriott_zamalek": (["ماريوت", "marriott"], (30.0573, 31.2246), 800),
    "nile_ritz": (["ريتز كارلتون", "ritz-carlton", "ritz carlton"], (30.0457, 31.2328), 800),
    "four_seasons_nile": (["فورسيزونز", "فور سيزونز", "four seasons"], (30.0363, 31.2290), 800),
    "fairmont": (["فيرمونت", "fairmont"], (30.0717, 31.2285), 1000),
    "ramses_hilton": (["رمسيس هيلتون", "هيلتون رمسيس", "ramses hilton"], (30.0505, 31.2320), 800),
    "korba": (["الكوربة", "korba"], (30.0890, 31.3230), 1500),
    "heliopolis": (["مصر الجديدة", "heliopolis"], (30.0911, 31.3220), 5000, {"area": True}),
    "nasr_city": (["مدينة نصر", "nasr city"], (30.0561, 31.3301), 5000, {"area": True}),
    "new_cairo": (["التجمع", "settlement", "new cairo", "القاهرة الجديدة"], (30.0074, 31.4613), 8000, {"area": True}),
    "abbassia": (["العباسية", "abbassia", "abbasiya", "abbaseya", "abbasiyya"], (30.0720, 31.2830), 2500, {"area": True}),
    "mohandessin": (["المهندسين", "mohandessin", "mohandeseen", "mohandiseen"], (30.0560, 31.2000), 3000, {"area": True}),
    # Giza
    "cairo_uni": (["جامعة القاهرة", "cairo university"], (30.0262, 31.2080), 2000),
    "pyramids": (["الاهرامات", "اهرامات الجيزة", "منطقة الاهرامات", "هرم خوفو", "الهرم الاكبر", "pyramids of giza",
                  "giza pyramids", "giza pyramid", "great pyramid", "pyramid of khufu"], (29.9792, 31.1342), 2500),
    "gem": (["المتحف المصري الكبير", "grand egyptian museum"], (29.9940, 31.1194), 1500),
    "giza_zoo": (["حديقة الحيوان", "giza zoo", "zoo"], (30.0240, 31.2131), 1500),
    "smart_village": (["القرية الذكية", "smart village"], (30.0716, 31.0187), 3000),
    "mall_arabia": (["مول العرب", "mall of arabia"], (30.0063, 30.9739), 2500),
    "mall_egypt": (["مول مصر", "mall of egypt"], (29.9726, 31.0167), 2500),
    "arkan": (["اركان", "arkan"], (30.0199, 31.0053), 2000),
    "dar_fouad": (["دار الفؤاد", "dar al fouad", "dar el fouad", "dar alfouad"], (29.9867, 30.9655), 4000),
    "mena_house": (["مينا هاوس", "mena house"], (29.9860, 31.1300), 1200),
    "hosary": (["الحصري", "el hosary", "al hosary", "el hossary", "al-hosary"], (29.9741, 30.9467), 1500),
    "beverly": (["بيفرلي هيلز", "beverly hills"], (30.0560, 30.9580), 3500),
    "dreamland": (["دريم لاند", "دريملاند", "dreamland", "dream land"], (29.9680, 31.0500), 4000),
    "cloud9": (["cloud 9", "cloud9", "cloud nine", "كلاود 9", "كلاود ناين"], (30.0493, 31.4757), 3000),
    "inovasys": (["inovasys", "انوفاسيس"], (29.9714, 30.9440), 120000),
    "october_city": (["6 اكتوبر", "السادس من اكتوبر", "مدينة اكتوبر", "6th of october", "6 october",
                      "sixth of october", "october city"], (29.9714, 30.9440), 12000, {"area": True}),
    "zayed_city": (["الشيخ زايد", "sheikh zayed", "el sheikh zayed", "shaikh zayed"], (30.0440, 30.9800), 6000,
                   {"area": True}),
    "umm_masryeen": (["مستشفى ام المصريين", "um el masryeen hospital", "om el masreyeen hospital"],
                     (30.0120, 31.2080), 2500),
    "giza_station": (["الجيزة", "giza", "محطة الجيزة"], (30.0105, 31.2070), 1500, {"scats": ["train_station"]}),
    # Alexandria
    "bib_alex": (["مكتبة الاسكندرية", "bibliotheca alexandrina", "library of alexandria", "bibliotheca"],
                 (31.2089, 29.9092), 1000),
    "qaitbay": (["قايتباي", "qaitbay", "qaitbey", "kaitbay", "qait bay"], (31.2140, 29.8856), 1000),
    "montaza_palace": (["قصر المنتزه", "حدائق المنتزه", "montaza palace", "montazah palace", "montaza gardens",
                        "montaza park"], (31.2883, 30.0164), 2000),
    "pompey": (["عمود السواري", "pompey's pillar", "pompeys pillar", "pompey pillar"], (31.1825, 29.8963), 800),
    "roman_amph": (["المسرح الروماني", "roman amphitheatre", "roman amphitheater", "كوم الدكة", "kom el dikka"],
                   (31.1946, 29.9042), 800),
    "morsi": (["المرسي ابو العباس", "el mursi abu el abbas", "abu al abbas al mursi", "morsi abul abbas",
               "mursi abu al-abbas"], (31.2058, 29.8822), 800),
    "alex_uni": (["جامعة الاسكندرية", "alexandria university"], (31.2090, 29.9170), 3000),
    "alex_misr_station": (["مصر", "misr", "محطة مصر", "الاسكندرية", "alexandria"], (31.1925, 29.9063), 1500,
                          {"scats": ["train_station"]}),
    "sidi_gaber_station": (["سيدي جابر", "sidi gaber", "sidi gabir"], (31.2186, 29.9419), 1200,
                           {"scats": ["train_station"]}),
    "alex_stadium": (["استاد الاسكندرية", "ستاد الاسكندرية", "alexandria stadium"], (31.1975, 29.9135), 1500),
    "borg_airport": (["مطار برج العرب", "borg el arab airport", "borg el arab international", "borg al arab airport"],
                     (30.9177, 29.6964), 4000),
    "san_stefano": (["سان ستيفانو", "san stefano"], (31.2457, 29.9666), 1500),
    "city_centre_alex": (["سيتي سنتر", "city centre", "city center"], (31.1660, 29.9320), 4000),
    "cecil": (["سيسيل", "cecil"], (31.2007, 29.8985), 800),
    "abu_qir": (["ابو قير", "ابوقير", "abu qir", "abukir", "aboukir", "abu kir", "abu qer"], (31.3170, 30.0600), 4000,
                {"area": True}),
    "smouha_club": (["نادي سموحة", "smouha club", "smouha sporting club"], (31.2090, 29.9440), 2000),
    "alex_main_hosp": (["المستشفى الاميري", "المستشفى الرئيسي الجامعي", "alexandria main university hospital"],
                       (31.2020, 29.9100), 1500),
    # Delta, Canal, Upper Egypt, coasts
    "benha_uni": (["جامعة بنها", "benha university", "banha university"], (30.4550, 31.1870), 5000),
    "qanater": (["القناطر الخيرية", "delta barrage", "el qanater el khayreya", "qanater"], (30.1900, 31.1300), 3000),
    "mansoura_uni": (["جامعة المنصورة", "mansoura university"], (31.0410, 31.3530), 3000),
    "mansoura_hosp": (["مستشفى المنصورة الجامعي", "مستشفيات جامعة المنصورة", "mansoura university hospital"],
                      (31.0420, 31.3600), 3000),
    "urology_mansoura": (["مركز الكلى", "مركز امراض الكلى", "urology and nephrology center", "urology nephrology"],
                         (31.0430, 31.3550), 3000),
    "zagazig_uni": (["جامعة الزقازيق", "zagazig university"], (30.5880, 31.4830), 4000),
    "tell_basta": (["تل بسطا", "tell basta", "bubastis"], (30.5733, 31.5107), 1500),
    "tanta_uni": (["جامعة طنطا", "tanta university"], (30.7930, 31.0000), 5000),
    "tanta_hosp": (["مستشفى طنطا الجامعي", "مستشفيات جامعة طنطا", "tanta university hospital"], (30.7920, 31.0000), 3000),
    "badawi": (["السيد البدوي", "sayed el badawi", "el sayed el badawi", "badawi mosque", "al-badawi mosque"],
               (30.7905, 31.0000), 1500),
    "menoufia_uni": (["جامعة المنوفية", "menoufia university", "menofia university", "monufia university"],
                     (30.5600, 31.0130), 5000),
    "kfs_uni": (["جامعة كفر الشيخ", "kafrelsheikh university", "kafr el sheikh university", "kafr elsheikh university"],
                (31.1000, 30.9450), 6000),
    "damietta_uni": (["جامعة دمياط", "damietta university"], (31.4400, 31.6800), 8000),
    "damietta_port": (["ميناء دمياط", "damietta port", "port of damietta"], (31.4700, 31.7600), 5000),
    "sca_portsaid": (["هيئة قناة السويس", "suez canal authority"], (31.2640, 32.3070), 1500),
    "scu": (["جامعة قناة السويس", "suez canal university"], (30.6200, 32.2700), 4000),
    "timsah": (["بحيرة التمساح", "lake timsah", "timsah lake"], (30.5700, 32.2950), 4000),
    "qarun": (["بحيرة قارون", "قارون", "qarun", "karun", "qaroun"], (29.4700, 30.6000), 15000),
    "fayoum_uni": (["جامعة الفيوم", "fayoum university", "faiyum university"], (29.3200, 30.8400), 5000),
    "beni_suef_uni": (["جامعة بني سويف", "beni suef university", "beni-suef university"], (29.0661, 31.0994), 8000),
    "minia_uni": (["جامعة المنيا", "minia university", "minya university"], (28.1240, 30.7350), 4000),
    "amarna": (["تل العمارنة", "tell el amarna", "amarna"], (27.6450, 30.8950), 6000),
    "asyut_uni": (["جامعة اسيوط", "assiut university", "asyut university"], (27.1870, 31.1680), 3000),
    "asyut_hosp": (["مستشفى اسيوط الجامعي", "مستشفيات جامعة اسيوط", "assiut university hospital"],
                   (27.1850, 31.1700), 3000),
    "white_monastery": (["الدير الابيض", "دير الانبا شنودة", "white monastery"], (26.5330, 31.6440), 4000),
    "sohag_uni": (["جامعة سوهاج", "sohag university"], (26.5591, 31.6957), 10000),
    "dendera": (["دندرة", "دندره", "dendera"], (26.1418, 32.6703), 2000),
    "svu": (["جامعة جنوب الوادي", "south valley university"], (26.1960, 32.7460), 5000),
    "karnak": (["الكرنك", "karnak"], (25.7188, 32.6573), 1500),
    "luxor_temple": (["معبد الاقصر", "luxor temple"], (25.6995, 32.6391), 1000),
    "hatshepsut": (["حتشبسوت", "hatshepsut", "الدير البحري", "deir el bahari", "deir el-bahari"], (25.7380, 32.6065), 1000),
    "valley_kings": (["وادي الملوك", "valley of the kings"], (25.7402, 32.6014), 3000),
    "winter_palace": (["ونتر بالاس", "winter palace"], (25.6990, 32.6380), 800),
    "luxor_airport": (["مطار الاقصر", "luxor international", "luxor airport"], (25.6710, 32.7066), 4000),
    "high_dam": (["السد العالي", "high dam", "aswan high dam"], (23.9707, 32.8771), 3000),
    "philae": (["فيلة", "فيله", "philae"], (24.0255, 32.8844), 2000),
    "abu_simbel": (["ابو سمبل", "abu simbel"], (22.3372, 31.6258), 3000),
    "cataract": (["كتراكت", "cataract"], (24.0815, 32.8870), 1000),
    "aswan_airport": (["مطار اسوان", "aswan international", "aswan airport"], (23.9644, 32.8200), 4000),
    "gouna": (["الجونة", "el gouna", "gouna"], (27.3940, 33.6780), 6000),
    "hurghada_marina": (["مارينا الغردقة", "hurghada marina", "marina"], (27.2269, 33.8416), 2500),
    "hurghada_airport": (["مطار الغردقة", "hurghada international", "hurghada airport"], (27.1783, 33.7994), 4000),
    "naama": (["خليج نعمة", "نعمة باي", "naama bay", "naama"], (27.9150, 34.3290), 2500),
    "sharm_airport": (["مطار شرم الشيخ", "sharm el sheikh international", "sharm el-sheikh international",
                       "sharm el sheikh airport"], (27.9773, 34.3950), 4000),
    "catherine": (["سانت كاترين", "saint catherine", "st. catherine", "st catherine"], (28.5560, 33.9760), 3000),
    "ras_mohammed": (["راس محمد", "ras mohammed", "ras muhammad"], (27.7300, 34.2500), 8000),
    "arish_airport": (["مطار العريش", "el arish international", "el arish airport", "arish airport"], (31.0733, 33.8358), 4000),
    "matrouh_airport": (["مطار مرسى مطروح", "مطار مطروح", "marsa matrouh airport", "mersa matruh airport",
                         "marsa matruh international"], (31.3254, 27.2217), 4000),
    "siwa": (["سيوة", "سيوه", "siwa"], (29.2032, 25.5195), 15000),
    "kharga_airport": (["مطار الخارجة", "kharga airport", "el kharga airport"], (25.4736, 30.5907), 5000),
    "hibis": (["معبد هيبس", "hibis temple", "temple of hibis"], (25.4740, 30.5520), 4000),
    # cities / areas (the city itself, not a shop named after it)
    "port_said_city": (["بورسعيد", "بور سعيد", "port said"], (31.2653, 32.3019), 6000, {"area": True}),
    "port_fouad": (["بورفؤاد", "بور فؤاد", "port fouad", "port fuad"], (31.2480, 32.3200), 4000, {"area": True}),
    "ras_el_bar": (["راس البر", "ras el bar", "ras elbar", "ras al bar"], (31.5130, 31.8240), 4000, {"area": True}),
    "kom_ombo": (["كوم امبو", "kom ombo"], (24.4760, 32.9480), 6000, {"area": True}),
    "hurghada_city": (["الغردقة", "hurghada", "al ghardaqa"], (27.2579, 33.8116), 10000, {"area": True}),
    "mahalla_city": (["المحلة الكبرى", "المحلة", "mahalla", "el mahalla el kubra", "al mahallah al kubra"],
                     (30.9697, 31.1669), 6000, {"area": True}),
    "kfs_city": (["كفر الشيخ", "kafr el sheikh", "kafr elsheikh", "kafr ash shaykh"], (31.1107, 30.9388), 6000,
                 {"area": True}),
    "beni_suef_city": (["بني سويف", "beni suef", "bani sweif", "beni sweif"], (29.0661, 31.0994), 6000, {"area": True}),
    "tenth_city": (["العاشر من رمضان", "10th of ramadan", "tenth of ramadan", "10th of ramadan city"],
                   (30.3060, 31.7420), 12000, {"area": True}),
    "sharm_city": (["شرم الشيخ", "sharm el sheikh", "sharm el-sheikh", "sharm"], (27.9158, 34.3299), 12000, {"area": True}),
}


def KP(key, **more) -> dict:
    """The place judge of a known target (its gates kept, `more` added)."""
    e = K[key]
    gates = dict(e[3]) if len(e) > 3 else {}
    gates.update(more)
    return place(e[0], e[1], e[2], **gates)


# ═══ A. PREFIX — typed keystroke by keystroke ════════════════════════════════════════════════════
PREFIX: list[dict] = []


def PX(q, at, judge, g):
    PREFIX.append({"q": q, "at": at, "g": g, **judge})


# the owner's cases, standing in 6th of October City
PX("kansas", "october", chain(["kansas", "كانساس"], 10), "chain")
PX("bazooka", "october", chain(["bazooka", "بازوكا"], 6), "chain")
PX("مطعم", "october", cat(REST, 2), "category")
PX("كنتاكي", "october", chain(["كنتاكي", "kfc"], 6), "chain")
PX("صيدلية", "october", cat(["pharmacy"], 2), "category")
PX("هايبر وان", "october", chain(["هايبر وان", "hyper one", "hyperone"], 15), "chain")
PX("مول العرب", "october", KP("mall_arabia"), "mall")
PX("جامعة القاهرة", "haram", KP("cairo_uni"), "university")
# chains, Arabic
PX("العزبي", "nasr", chain(["العزبي", "ezaby", "elezaby"], 3), "chain")
PX("صيدليات سيف", "dokki", chain(["سيف", "seif"], 3), "chain")
PX("كارفور", "maadi", chain(["كارفور", "carrefour"], 12), "chain")
PX("ماكدونالدز", "mansoura", chain(["ماكدونالدز", "mcdonald"], 5), "chain")
PX("مؤمن", "heliopolis", chain(["مؤمن", "momen", "mo'men"], 4), "chain")
PX("كوك دور", "downtown", chain(["كوك دور", "cook door"], 4), "chain")
PX("بيم", "tanta", chain(["بيم", "bim"], 4), "chain")
PX("كازيون", "damanhour", chain(["كازيون", "kazyon"], 5), "chain")
PX("فتح الله", "raml", chain(["فتح الله", "fathalla", "fathallah"], 6), "chain")
PX("خير زمان", "shubra", chain(["خير زمان", "kheir zaman"], 5), "chain")
PX("اولاد رجب", "haram", chain(["رجب", "ragab"], 6), "chain")
PX("بلبن", "mansoura", chain(["بلبن", "b.laban", "blaban", "b laban"], 5), "chain")
PX("بي تك", "zagazig", chain(["بي تك", "btech", "b.tech", "b tech"], 8), "chain")
PX("فودافون", "portsaid", chain(["فودافون", "vodafone"], 4), "chain")
PX("اورانج", "ismailia", chain(["اورانج", "اورنج", "orange"], 4), "chain")
PX("البنك الاهلي", "minya", chain(["البنك الاهلي", "national bank of egypt", "nbe"], 4), "chain")
PX("بنك مصر", "asyut", chain(["بنك مصر", "banque misr"], 4), "chain")
PX("مصر للبترول", "benisuef", chain(["مصر للبترول", "misr petroleum"], 6), "chain")
PX("وطنية", "october", chain(["وطنية", "wataniya"], 8), "chain")
PX("ستاربكس", "zayed", chain(["ستاربكس", "starbucks"], 6), "chain")
PX("كوستا", "smouha", chain(["كوستا", "costa"], 5), "chain")
PX("جاد", "shubra", chain(["جاد", "gad"], 4), "chain")
PX("التابعي الدمياطي", "downtown", chain(["التابعي", "tabei", "tabie"], 5), "chain")
PX("كشري التحرير", "mohandessin", chain(["كشري التحرير", "koshary el tahrir", "tahrir koshary"], 5), "chain")
PX("زهران", "montaza", chain(["زهران", "zahran"], 8), "chain")
PX("سبينيس", "newcairo", chain(["سبينيس", "سبينيز", "spinneys"], 8), "chain")
PX("هارديز", "nasr", chain(["هارديز", "hardee"], 5), "chain")
PX("بيتزا هت", "smouha", chain(["بيتزا هت", "pizza hut"], 5), "chain")
# places, Arabic
PX("سيتي ستارز", "nasr", KP("city_stars"), "mall")
PX("كايرو فستيفال", "newcairo", KP("cfc"), "mall")
PX("مول مصر", "october", KP("mall_egypt"), "mall")
PX("دار الفؤاد", "october", KP("dar_fouad"), "hospital")
PX("جامعة عين شمس", "shubra", KP("ain_shams_uni"), "university")
PX("جامعة الازهر", "nasr", KP("azhar_uni"), "university")
PX("جامعة المنصورة", "mansoura", KP("mansoura_uni"), "university")
PX("جامعة الاسكندرية", "smouha", KP("alex_uni"), "university")
PX("جامعة اسيوط", "asyut", KP("asyut_uni"), "university")
PX("جامعة طنطا", "tanta", KP("tanta_uni"), "university")
PX("مستشفى المنصورة الجامعي", "mansoura", KP("mansoura_hosp"), "hospital")
PX("القصر العيني", "maadi", KP("kasr"), "hospital")
PX("الدمرداش", "heliopolis", KP("demerdash"), "hospital")
PX("مستشفى 57357", "nasr", KP("57357"), "hospital")
PX("مترو السادات", "dokki", KP("metro_sadat"), "metro")
PX("مترو الشهداء", "shubra", KP("metro_shohadaa"), "metro")
PX("مترو العتبة", "downtown", KP("metro_ataba"), "metro")
PX("محطة رمسيس", "shubra", KP("ramses"), "station")
PX("محطة سيدي جابر", "montaza", KP("sidi_gaber_station"), "station")
PX("الاهرامات", "haram", KP("pyramids"), "landmark")
PX("برج القاهرة", "zamalek", KP("cairo_tower"), "landmark")
PX("المتحف المصري الكبير", "october", KP("gem"), "landmark")
PX("قلعة صلاح الدين", "mokattam", KP("citadel"), "landmark")
PX("خان الخليلي", "downtown", KP("khan"), "landmark")
PX("مكتبة الاسكندرية", "raml", KP("bib_alex"), "landmark")
PX("قلعة قايتباي", "smouha", KP("qaitbay"), "landmark")
PX("معبد الكرنك", "luxor", KP("karnak"), "landmark")
PX("السد العالي", "aswan", KP("high_dam"), "landmark")
PX("مسجد السيد البدوي", "tanta", KP("badawi"), "landmark")
PX("مطار القاهرة", "heliopolis", KP("cairo_airport"), "airport")
PX("مطار برج العرب", "smouha", KP("borg_airport"), "airport")
PX("النادي الاهلي", "zamalek", KP("ahly"), "club")
PX("نادي الزمالك", "mohandessin", KP("zamalek_club"), "club")
PX("نادي سموحة", "smouha", KP("smouha_club"), "club")
PX("مدينتي", "newcairo", KP("madinaty"), "compound")
PX("القرية الذكية", "zayed", KP("smart_village"), "business_park")
# Latin and Franco
PX("city stars", "nasr", KP("city_stars"), "mall")
PX("cfc", "maadi", KP("cfc"), "mall")
PX("mall of egypt", "zayed", KP("mall_egypt"), "mall")
PX("cairo festival city", "heliopolis", KP("cfc"), "mall")
PX("mall of arabia", "october", KP("mall_arabia"), "mall")
PX("arkan", "zayed", KP("arkan"), "mall")
PX("kfc", "zagazig", chain(["كنتاكي", "kfc"], 6), "chain")
PX("mcdonalds", "smouha", chain(["ماكدونالدز", "mcdonald"], 5), "chain")
PX("pizza hut", "heliopolis", chain(["بيتزا هت", "pizza hut"], 5), "chain")
PX("carrefour", "october", chain(["كارفور", "carrefour"], 10), "chain")
PX("spinneys", "newcairo", chain(["سبينيس", "سبينيز", "spinneys"], 8), "chain")
PX("starbucks", "newcairo", chain(["ستاربكس", "starbucks"], 5), "chain")
PX("cairo university", "dokki", KP("cairo_uni"), "university")
PX("ain shams university", "heliopolis", KP("ain_shams_uni"), "university")
PX("auc", "newcairo", KP("auc"), "university")
PX("pyramids", "haram", KP("pyramids"), "landmark")
PX("egyptian museum", "downtown", KP("egy_museum"), "landmark")
PX("khan el khalili", "zamalek", KP("khan"), "landmark")
PX("citadel", "downtown", KP("citadel"), "landmark")
PX("ramses station", "downtown", KP("ramses"), "station")
PX("cairo airport", "heliopolis", KP("cairo_airport"), "airport")
PX("bibliotheca alexandrina", "smouha", KP("bib_alex"), "landmark")
PX("karnak", "luxor", KP("karnak"), "landmark")
PX("naama bay", "sharm", KP("naama"), "landmark")
PX("el gouna", "hurghada", KP("gouna"), "area")
PX("smart village", "zayed", KP("smart_village"), "business_park")
PX("madinaty", "newcairo", KP("madinaty"), "compound")
PX("kasr el aini", "downtown", KP("kasr"), "hospital")
PX("mol masr", "october", KP("mall_egypt"), "mall")
PX("2asr el 3eny", "maadi", KP("kasr"), "hospital")
PX("gam3et ain shams", "shubra", KP("ain_shams_uni"), "university")


# ═══ B. EXACT — the full common name, rank 1 required ════════════════════════════════════════════
EXACT: list[dict] = []


def EX(q, at, judge, g, gov):
    EXACT.append({"q": q, "at": at, "g": g, "gov": gov, **judge})


def _police(names_ar, near, r=5000, en=()):
    """A police station judge: its official forms (with and without «شرطة»), never the census district."""
    out = []
    for n in names_ar:
        out.append(n)
        if n.startswith("قسم شرطة "):
            out.append("قسم " + n[len("قسم شرطة "):])
        elif n.startswith("قسم "):
            out.append("قسم شرطة " + n[len("قسم "):])
    return place(list(dict.fromkeys(out)) + list(en), near, r, poi=True)


EX("مستشفى القصر العيني", "downtown", KP("kasr"), "hospital", "cairo")
EX("ميدان التحرير", "zamalek", KP("tahrir_sq"), "landmark", "cairo")
EX("قلعة صلاح الدين الأيوبي", "mokattam", KP("citadel"), "landmark", "cairo")
EX("مسجد عمرو بن العاص", "maadi", KP("amr_mosque"), "landmark", "cairo")
EX("الكنيسة المعلقة", "maadi", KP("hanging"), "landmark", "cairo")
EX("قصر عابدين", "downtown", KP("abdeen"), "landmark", "cairo")
EX("استاد القاهرة الدولي", "nasr", KP("cairo_stadium"), "stadium", "cairo")
EX("مطار القاهرة الدولي", "heliopolis", KP("cairo_airport"), "airport", "cairo")
EX("قسم شرطة الأزبكية", "downtown", _police(["قسم شرطة الازبكية"], (30.0540, 31.2470), 1500,
                                            en=["azbakeya police station", "ezbekiya police station"]), "police", "cairo")
EX("المتحف القومي للحضارة المصرية", "maadi", KP("nmec"), "landmark", "cairo")
EX("قصر البارون إمبان", "heliopolis", KP("baron"), "landmark", "cairo")
EX("الجامعة الأمريكية بالقاهرة", "newcairo", KP("auc"), "university", "cairo")
EX("مستشفى الدمرداش", "nasr", KP("demerdash"), "hospital", "cairo")
EX("مجمع التحرير", "maadi", KP("mogamma"), "government", "cairo")
EX("مستشفى سرطان الأطفال 57357", "heliopolis", KP("57357"), "hospital", "cairo")
EX("نايل سيتي", "zamalek", KP("nile_city"), "business_park", "cairo")
EX("المتحف المصري الكبير", "haram", KP("gem"), "landmark", "giza")
EX("حديقة الحيوان بالجيزة", "dokki", KP("giza_zoo"), "landmark", "giza")
EX("جامعة القاهرة", "dokki", KP("cairo_uni"), "university", "giza")
EX("القرية الذكية", "october", KP("smart_village"), "business_park", "giza")
EX("مول العرب", "zayed", KP("mall_arabia"), "mall", "giza")
EX("قسم شرطة الدقي", "mohandessin", _police(["قسم شرطة الدقي"], (30.0385, 31.2120), 2000, en=["dokki police station"]),
   "police", "giza")
EX("فندق ماريوت مينا هاوس", "haram", KP("mena_house"), "hotel", "giza")
EX("مكتبة الإسكندرية", "smouha", KP("bib_alex"), "landmark", "alexandria")
EX("قلعة قايتباي", "raml", KP("qaitbay"), "landmark", "alexandria")
EX("عمود السواري", "smouha", KP("pompey"), "landmark", "alexandria")
EX("المسرح الروماني", "raml", KP("roman_amph"), "landmark", "alexandria")
EX("مسجد المرسي أبو العباس", "montaza", KP("morsi"), "landmark", "alexandria")
EX("استاد الإسكندرية", "montaza", KP("alex_stadium"), "stadium", "alexandria")
EX("فندق سيسيل", "smouha", KP("cecil"), "hotel", "alexandria")
EX("جامعة بنها", "banha", KP("benha_uni"), "university", "qalyubia")
EX("القناطر الخيرية", "shubra_kheima", KP("qanater"), "landmark", "qalyubia")
EX("جامعة المنصورة", "mansoura", KP("mansoura_uni"), "university", "dakahlia")
EX("مستشفى المنصورة الجامعي", "mansoura", KP("mansoura_hosp"), "hospital", "dakahlia")
EX("مركز الكلى والمسالك البولية", "mansoura", KP("urology_mansoura"), "hospital", "dakahlia")
EX("جامعة الزقازيق", "zagazig", KP("zagazig_uni"), "university", "sharqia")
EX("تل بسطا", "zagazig", KP("tell_basta"), "landmark", "sharqia")
EX("مسجد السيد البدوي", "tanta", KP("badawi"), "landmark", "gharbia")
EX("جامعة طنطا", "mahalla", KP("tanta_uni"), "university", "gharbia")
EX("جامعة المنوفية", "shebin", KP("menoufia_uni"), "university", "monufia")
EX("مديرية أمن البحيرة", "damanhour", place(["مديرية امن البحيرة", "beheira security directorate"],
                                             ANCHORS["damanhour"][:2], 5000, poi=True), "police", "beheira")
EX("جامعة كفر الشيخ", "kafrsheikh", KP("kfs_uni"), "university", "kafr_el_sheikh")
EX("ميناء دمياط", "damietta", KP("damietta_port"), "landmark", "damietta")
EX("جامعة دمياط", "damietta", KP("damietta_uni"), "university", "damietta")
EX("هيئة قناة السويس", "portsaid", KP("sca_portsaid"), "government", "port_said")
EX("ديوان عام محافظة بورسعيد", "portsaid", place(["ديوان محافظة بورسعيد", "مبنى محافظة بورسعيد",
                                                  "port said governorate building"], ANCHORS["portsaid"][:2], 5000,
                                                 poi=True), "government", "port_said")
EX("جامعة قناة السويس", "ismailia", KP("scu"), "university", "ismailia")
EX("بحيرة التمساح", "ismailia", KP("timsah"), "landmark", "ismailia")
EX("مديرية أمن السويس", "suez", place(["مديرية امن السويس", "suez security directorate"], ANCHORS["suez"][:2], 6000,
                                       poi=True), "police", "suez")
EX("بحيرة قارون", "faiyum", KP("qarun"), "landmark", "faiyum")
EX("جامعة الفيوم", "faiyum", KP("fayoum_uni"), "university", "faiyum")
EX("جامعة بني سويف", "benisuef", KP("beni_suef_uni"), "university", "beni_suef")
EX("جامعة المنيا", "minya", KP("minia_uni"), "university", "minya")
EX("تل العمارنة", "minya", KP("amarna"), "landmark", "minya")
EX("جامعة أسيوط", "asyut", KP("asyut_uni"), "university", "asyut")
EX("مستشفى أسيوط الجامعي", "asyut", KP("asyut_hosp"), "hospital", "asyut")
EX("الدير الأبيض", "sohag", KP("white_monastery"), "landmark", "sohag")
EX("جامعة سوهاج", "sohag", KP("sohag_uni"), "university", "sohag")
EX("معبد دندرة", "qena", KP("dendera"), "landmark", "qena")
EX("جامعة جنوب الوادي", "qena", KP("svu"), "university", "qena")
EX("معبد الأقصر", "luxor", KP("luxor_temple"), "landmark", "luxor")
EX("معبد حتشبسوت", "luxor", KP("hatshepsut"), "landmark", "luxor")
EX("فندق ونتر بالاس", "luxor", KP("winter_palace"), "hotel", "luxor")
EX("السد العالي", "aswan", KP("high_dam"), "landmark", "aswan")
EX("معبد فيلة", "aswan", KP("philae"), "landmark", "aswan")
EX("فندق أولد كتراكت", "aswan", KP("cataract"), "hotel", "aswan")
EX("الجونة", "hurghada", KP("gouna"), "area", "red_sea")
EX("مطار الغردقة الدولي", "hurghada", KP("hurghada_airport"), "airport", "red_sea")
EX("خليج نعمة", "sharm", KP("naama"), "landmark", "south_sinai")
EX("دير سانت كاترين", "dahab", KP("catherine"), "landmark", "south_sinai")
EX("مطار العريش", "arish", KP("arish_airport"), "airport", "north_sinai")
EX("ديوان عام محافظة شمال سيناء", "arish", place(["ديوان محافظة شمال سيناء", "مبنى محافظة شمال سيناء",
                                                  "north sinai governorate building"], ANCHORS["arish"][:2], 6000,
                                                 poi=True), "government", "north_sinai")
EX("مطار مرسى مطروح", "matrouh", KP("matrouh_airport"), "airport", "matrouh")
EX("واحة سيوة", "matrouh", KP("siwa"), "area", "matrouh")
EX("معبد هيبس", "kharga", KP("hibis"), "landmark", "new_valley")
EX("مطار الخارجة", "kharga", KP("kharga_airport"), "airport", "new_valley")
# the same names typed from another governorate
EX("مكتبة الإسكندرية", "downtown", KP("bib_alex"), "landmark", "alexandria")
EX("معبد الكرنك", "raml", KP("karnak"), "landmark", "luxor")
EX("القرية الذكية", "maadi", KP("smart_village"), "business_park", "giza")
EX("جامعة أسيوط", "downtown", KP("asyut_uni"), "university", "asyut")
# the owner's case: a company whose true position is disputed — judged by name only
EX("inovasys", "october", KP("inovasys"), "company", "giza")


# ═══ C. VARIANT — the same target under another spelling ═══════════════════════════════════════════
VARIANT: list[dict] = []


def VA(q, at, judge, g, how):
    VARIANT.append({"q": q, "at": at, "g": g, "how": how, **judge})


POL_MAHALLA_2 = _police(["قسم ثان المحلة", "قسم ثان المحلة الكبرى", "قسم ثاني المحلة"], ANCHORS["mahalla"][:2], 5000,
                        en=["mahalla second police station", "el mahalla 2nd police station"])
POL_TANTA_1 = _police(["قسم أول طنطا"], ANCHORS["tanta"][:2], 5000, en=["tanta first police station"])
POL_TANTA_2 = _police(["قسم ثان طنطا", "قسم ثاني طنطا"], ANCHORS["tanta"][:2], 5000, en=["tanta second police station"])
POL_MANSOURA_1 = _police(["قسم أول المنصورة"], ANCHORS["mansoura"][:2], 5000, en=["mansoura first police station"])
POL_ZAGAZIG_2 = _police(["قسم ثان الزقازيق", "قسم ثاني الزقازيق"], ANCHORS["zagazig"][:2], 5000,
                        en=["zagazig second police station"])
POL_NASR_1 = _police(["قسم أول مدينة نصر"], (30.0590, 31.3300), 4000, en=["nasr city first police station"])

VA("قسم ثان المحلة", "mahalla", POL_MAHALLA_2, "police", "ordinal")
VA("قسم 2 المحلة", "mahalla", POL_MAHALLA_2, "police", "ordinal_digit")
VA("قسم التاني المحله", "mahalla", POL_MAHALLA_2, "police", "ordinal_colloquial")
VA("قسم اول طنطا", "tanta", POL_TANTA_1, "police", "ordinal")
VA("قسم 1 طنطا", "tanta", POL_TANTA_1, "police", "ordinal_digit")
VA("قسم تاني طنطا", "tanta", POL_TANTA_2, "police", "ordinal_colloquial")
VA("قسم اول المنصوره", "mansoura", POL_MANSOURA_1, "police", "ordinal")
VA("قسم تانى الزقازيق", "zagazig", POL_ZAGAZIG_2, "police", "ordinal_colloquial")
VA("قسم 1 مدينة نصر", "nasr", POL_NASR_1, "police", "ordinal_digit")
VA("ش التحرير", "dokki", KP("tahrir_st_dokki"), "street", "abbreviation")
VA("م التحرير", "maadi", KP("tahrir_sq"), "landmark", "abbreviation")
VA("مستشفي القصر العيني", "downtown", KP("kasr"), "hospital", "ya_alif")
VA("قصر العينى", "maadi", KP("kasr"), "hospital", "ya_alif")
VA("kasr el ainy", "zamalek", KP("kasr"), "hospital", "english")
VA("ج القاهره", "haram", KP("cairo_uni"), "university", "abbreviation")
VA("جامعه القاهره", "dokki", KP("cairo_uni"), "university", "ta_marbuta")
VA("cloud9 mall", "october", KP("cloud9"), "mall", "joined_digit")
VA("cloud 9 mall", "october", KP("cloud9"), "mall", "split_digit")
VA("كلاود ٩", "october", KP("cloud9"), "mall", "arabic_digit")
VA("كلاود ناين", "october", KP("cloud9"), "mall", "number_word")
VA("6 اكتوبر", "maadi", KP("october_city"), "area", "digit")
VA("السادس من اكتوبر", "downtown", KP("october_city"), "area", "number_word")
VA("6th of october", "dokki", KP("october_city"), "area", "english")
VA("مدينة اكتوبر", "haram", KP("october_city"), "area", "colloquial")
VA("ابو قير", "raml", KP("abu_qir"), "area", "spacing")
VA("ابوقير", "smouha", KP("abu_qir"), "area", "spacing")
VA("abu qir", "raml", KP("abu_qir"), "area", "english")
VA("el 7osary", "zayed", KP("hosary"), "landmark", "franco")
VA("مسجد الحصرى", "zayed", KP("hosary"), "landmark", "ya_alif")
VA("masr el gdeda", "maadi", KP("heliopolis"), "area", "franco")
VA("مصر الجديده", "dokki", KP("heliopolis"), "area", "ta_marbuta")
VA("سيتى ستارز", "heliopolis", KP("city_stars"), "mall", "ya_alif")
VA("citystars", "maadi", KP("city_stars"), "mall", "joined")
VA("ستي ستارز", "nasr", KP("city_stars"), "mall", "transliteration")
VA("مول اوف ايجيبت", "october", KP("mall_egypt"), "mall", "english_in_arabic")
VA("مول اوف ارابيا", "zayed", KP("mall_arabia"), "mall", "english_in_arabic")
VA("كايرو فستفال", "maadi", KP("cfc"), "mall", "transliteration")
VA("بوينت تسعين", "newcairo", KP("point90"), "mall", "number_word")
VA("مستشفى سرطان الاطفال", "heliopolis", KP("57357"), "hospital", "descriptive_name")
VA("57357 hospital", "maadi", KP("57357"), "hospital", "english")
VA("مستشفى سعودى المانى", "heliopolis", KP("saudi_german"), "hospital", "ya_alif")
VA("دمرداش", "shubra", KP("demerdash"), "hospital", "no_article")
VA("محطة مصر", "downtown", KP("ramses"), "station", "colloquial")
VA("محطه رمسيس", "nasr", KP("ramses"), "station", "ta_marbuta")
VA("مترو جامعة القاهره", "dokki", KP("metro_cairo_uni"), "metro", "ta_marbuta")
VA("الكوربه", "heliopolis", KP("korba"), "area", "ta_marbuta")
VA("mohandseen", "zamalek", KP("mohandessin"), "area", "franco")
VA("مهندسين", "nasr", KP("mohandessin"), "area", "no_article")
VA("التجمع", "maadi", KP("new_cairo"), "area", "colloquial")
VA("new cairo", "downtown", KP("new_cairo"), "area", "english")
VA("زايد", "october", KP("zayed_city"), "area", "colloquial")
VA("مدينه نصر", "downtown", KP("nasr_city"), "area", "ta_marbuta")
VA("el 3abbaseya", "zamalek", KP("abbassia"), "area", "franco")
VA("هيلتون رمسيس", "downtown", KP("ramses_hilton"), "hotel", "word_order")
VA("ماريوت الزمالك", "dokki", KP("marriott_zamalek"), "hotel", "english_in_arabic")
VA("القلعه", "downtown", KP("citadel"), "landmark", "ta_marbuta")
VA("salah el din citadel", "maadi", KP("citadel"), "landmark", "english")
VA("مسجد محمد على", "nasr", KP("mohamed_ali"), "landmark", "ya_alif")
VA("اهرامات الجيزه", "downtown", KP("pyramids"), "landmark", "ta_marbuta")
VA("ahramat", "zamalek", KP("pyramids"), "landmark", "franco")
VA("جامعه الاسكندريه", "raml", KP("alex_uni"), "university", "ta_marbuta")
VA("alex university", "smouha", KP("alex_uni"), "university", "abbreviation")
VA("مكتبة اسكندرية", "montaza", KP("bib_alex"), "landmark", "no_article")
VA("محطة سيدى جابر", "raml", KP("sidi_gaber_station"), "station", "ya_alif")
VA("راس البر", "damietta", KP("ras_el_bar"), "area", "hamza")
VA("ras el bar", "mansoura", KP("ras_el_bar"), "area", "english")
VA("بور سعيد", "ismailia", KP("port_said_city"), "area", "spacing")
VA("بورفؤاد", "portsaid", KP("port_fouad"), "area", "spacing")
VA("ابو سنبل", "aswan", KP("abu_simbel"), "landmark", "colloquial")
VA("kom ombo", "aswan", KP("kom_ombo"), "area", "english")
VA("الغردقه", "luxor", KP("hurghada_city"), "area", "ta_marbuta")
VA("hurgada", "sharm", KP("hurghada_city"), "area", "typo")
VA("المحله", "tanta", KP("mahalla_city"), "area", "colloquial")
VA("كفرالشيخ", "tanta", KP("kfs_city"), "area", "spacing")
VA("بنى سويف", "faiyum", KP("beni_suef_city"), "area", "ya_alif")
VA("10th of ramadan", "zagazig", KP("tenth_city"), "area", "english_digit")
VA("شرم", "dahab", KP("sharm_city"), "area", "colloquial")


# ═══ D. NEED — a product or a service, not a place name ════════════════════════════════════════════
NEED: list[dict] = []


def ND(q, at, scats, km, words, g):
    NEED.append({"q": q, "at": at, "g": g, **cat(scats, km, words)})


CAR_ACC = ["اكسسوارات", "كماليات", "accessories", "اكسسوار"]
MATTRESS = ["مراتب", "مرتبة", "mattress", "mattresses", "مفروشات", "يانسن", "janssen"]
PHONE_ACC = ["اكسسوارات", "موبايل", "موبايلات", "mobile", "accessories"]

ND("شاشه عربيات", "october", ["auto_parts"], 5, CAR_ACC + ["شاشات", "صوتيات", "car audio"], "car")
ND("بطارية عربية", "nasr", ["battery_shop", "auto_parts"], 4, ["بطاريات", "بطارية", "battery", "batteries"], "car")
ND("تيل فرامل", "haram", ["auto_parts", "car_repair"], 3, ["قطع غيار", "spare parts", "فرامل", "brake"], "car")
ND("فاميه عربية", "nasr", ["auto_parts", "car_wash"], 4, CAR_ACC + ["فاميه", "فامية", "تظليل", "tint", "detailing"], "car")
ND("ترصيص كاوتش", "tanta", ["tyre_shop", "car_repair"], 4, ["كاوتش", "اطارات", "ترصيص", "tyres", "tires"], "car")
ND("تغيير زيت", "october", ["oil_change", "gas_station", "car_repair"], 5, ["زيوت", "زيت", "oil", "lube"], "car")
ND("قطع غيار عربيات", "damietta", ["auto_parts"], 4, ["قطع غيار", "spare parts", "parts"], "car")
ND("car wash", "zayed", ["car_wash"], 5, ["مغسلة", "غسيل", "wash", "detailing"], "car")
ND("جزمة", "mohandessin", ["shoe_store"], 3, ["احذية", "شوز", "shoes", "باتا", "bata"], "shopping")
ND("كفر موبايل", "tanta", ["mobile_shop", "electronics_store"], 3, PHONE_ACC, "phone")
ND("phone charger", "downtown", ["mobile_shop", "electronics_store"], 2, PHONE_ACC, "phone")
ND("شحن رصيد", "zagazig", ["mobile_shop", "electricity_payment", "supermarket"], 2,
   ["فوري", "fawry", "موبايل", "فودافون", "vodafone", "اورانج", "orange", "اتصالات", "etisalat"], "phone")
ND("mobile repair", "raml", ["mobile_shop"], 3, ["صيانة", "repair", "موبايل", "mobile"], "phone")
ND("laptop repair", "nasr", ["electronics_store"], 4, ["laptop", "لابتوب", "computer", "كمبيوتر", "صيانة", "maintenance"],
   "electronics")
ND("حد يصلح تكييف", "newcairo", ["electrician", "appliance_store"], 5,
   ["تكييف", "تكييفات", "تبريد", "air condition", "hvac", "صيانة"], "home_service")
ND("سباك", "october", ["plumber", "hardware_store"], 5, ["سباك", "سباكة", "plumbing", "ادوات صحية"], "home_service")
ND("كهربائي", "benisuef", ["electrician", "hardware_store"], 4, ["كهرباء", "electric", "كهربائي", "ادوات كهربائية"],
   "home_service")
ND("نجار", "mahalla", ["carpenter", "furniture_store"], 4, ["نجارة", "موبيليا", "اثاث", "wood"], "home_service")
ND("نسخ مفاتيح", "mansoura", ["hardware_store"], 3, ["مفاتيح", "كوالين", "keys", "locksmith"], "home_service")
ND("تصوير ورق", "dokki", ["print_shop", "bookshop"], 2, ["تصوير", "مكتبة", "طباعة", "print", "copy", "فوتوكوبي"],
   "services")
ND("ترزي", "zagazig", ["tailor"], 3, ["ترزي", "خياط", "tailor"], "services")
ND("دراي كلين", "zamalek", ["laundry"], 2, ["dry clean", "مغسلة", "laundry", "دراي كلين"], "services")
ND("لحمه", "shubra", ["butcher"], 2, ["جزارة", "لحوم", "جزار", "butcher", "meat"], "food")
ND("فراخ", "mansoura", ["butcher"], 3, ["فراخ", "دواجن", "طيور", "poultry"], "food")
ND("تورتة عيد ميلاد", "heliopolis", ["sweets", "bakery"], 3,
   ["حلواني", "حلويات", "cake", "cakes", "تورت", "patisserie", "باتيسري"], "food")
ND("عيش فينو", "luxor", ["bakery"], 3, ["مخبز", "فرن", "bakery", "عيش"], "food")
ND("فاكهة", "aswan", ["greengrocer", "market", "supermarket"], 3, ["فاكهة", "فواكه", "خضار", "fruits", "fruit"], "food")
ND("سمك طازة", "portsaid", ["seafood"], 4, ["سمك", "اسماك", "fish"], "food")
ND("عطارة", "downtown", ["spices"], 3, ["عطارة", "عطار", "توابل", "spices", "herbs"], "food")
ND("نظارة طبية", "smouha", ["optician"], 3, ["نظارات", "بصريات", "optics", "optical", "نظارة"], "health")
ND("نضارة شمس", "hurghada", ["optician"], 5, ["نظارات", "بصريات", "optics", "sunglasses"], "health")
ND("مستلزمات طبية", "maadi", ["pharmacy"], 3, ["مستلزمات طبية", "medical supplies", "medical"], "health")
ND("تحليل دم", "tanta", ["medical_lab"], 3, ["معمل", "تحاليل", "lab", "laboratory", "laboratories"], "health")
ND("اشعة مقطعية", "mansoura", ["radiology", "hospital"], 4, ["اشعة", "scan", "radiology", "اسكان"], "health")
ND("حشو ضرس", "minya", ["dentist"], 3, ["اسنان", "dental", "dent"], "health")
ND("فيتامينات", "zayed", ["pharmacy"], 4, ["صيدلية", "pharmacy", "vitamin"], "health")
ND("مرتبة سرير", "october", ["furniture_store", "home_goods_store"], 6, MATTRESS, "home")
ND("mattress shop", "newcairo", ["furniture_store", "home_goods_store"], 6, MATTRESS, "home")
ND("فلتر مية", "maadi", ["home_goods_store", "hardware_store", "appliance_store"], 4,
   ["فلاتر", "فلتر", "water filter", "filters", "تنقية"], "home")
ND("موبيليا", "damietta", ["furniture_store", "carpenter"], 4, ["موبيليا", "اثاث", "furniture", "معرض"], "home")
ND("دهانات", "faiyum", ["hardware_store"], 4, ["دهانات", "بويات", "paint", "سايبس", "جوتن"], "home")
ND("سيراميك", "sohag", ["hardware_store", "home_goods_store"], 5, ["سيراميك", "ceramic", "بورسلين", "ادوات صحية"], "home")
ND("لمبة ليد", "qena", ["hardware_store", "home_goods_store", "electronics_store"], 4,
   ["كهرباء", "اضاءة", "lighting", "led", "لمبات", "ادوات كهربائية"], "home")
ND("لبس رياضي", "october", ["sports_store", "clothing_store"], 6,
   ["sport", "رياضة", "رياضي", "adidas", "اديداس", "nike", "نايكي", "decathlon", "ديكاتلون"], "shopping")
ND("هدوم اطفال", "shubra", ["clothing_store"], 3, ["اطفال", "kids", "baby", "بيبي"], "shopping")
ND("فستان فرح", "mohandessin", ["clothing_store"], 4, ["زفاف", "فساتين", "bridal", "wedding", "سواريه"], "shopping")
ND("خاتم دهب", "asyut", ["jewelry_store"], 3, ["مجوهرات", "ذهب", "صاغة", "jewel", "gold"], "shopping")
ND("برفان", "heliopolis", ["perfume", "cosmetics"], 3, ["عطور", "perfume", "برفانات", "parfum"], "shopping")
ND("عجلة", "ismailia", ["sports_store"], 4, ["عجل", "bike", "bicycle", "دراجات", "عجلة"], "shopping")
ND("اكل قطط", "newcairo", ["pet_store", "veterinary"], 5, ["pet", "pets", "اليفة", "cat food"], "shopping")
ND("ورد", "zamalek", ["florist"], 3, ["ورد", "زهور", "flowers", "florist", "ورود"], "shopping")
ND("هدية", "smouha", ["gift_shop", "toy_store"], 3, ["هدايا", "gifts", "gift"], "shopping")
ND("لعب اطفال", "nasr", ["toy_store"], 4, ["لعب", "العاب", "toys", "toy"], "shopping")
ND("شنطة مدرسة", "damanhour", ["bookshop", "clothing_store"], 3, ["شنط", "حقائب", "bags", "مكتبة"], "shopping")
ND("تجديد رخصة", "october", ["traffic_department"], 15, ["مرور", "وحدة مرور", "traffic"], "government")
ND("شهادة ميلاد", "nasr", ["civil_registry"], 8, ["سجل مدني", "احوال مدنية", "civil registry"], "government")
ND("تحويل فلوس", "asyut", ["bank", "exchange", "electricity_payment", "post_office"], 4,
   ["ويسترن", "western union", "تحويل", "بنك", "فوري", "bank"], "money")


# ═══ E. SCRIPT — everyday Arabic queries (no judge): the share of top-5 rows with an Arabic name ══════
SCRIPT: list[dict] = [{"q": q, "at": at, "g": "script"} for q, at in [
    ("مطعم كشري", "downtown"), ("صيدلية 24 ساعة", "nasr"), ("سوبر ماركت قريب", "maadi"),
    ("محل ملابس رجالي", "mansoura"), ("مكتبة", "tanta"), ("كافيه هادي", "newcairo"), ("مخبز", "asyut"),
    ("محطة بنزين", "zagazig"), ("مستشفى اطفال", "raml"), ("عيادة اسنان", "october"), ("جيم", "zayed"),
    ("حلاق رجالي", "shubra"), ("مغسلة عربيات", "heliopolis"), ("بنك", "minya"), ("فندق", "hurghada"),
    ("جامع", "sohag"), ("كنيسة", "minya"), ("مدرسة", "faiyum"), ("حضانة", "dokki"), ("سنتر دروس", "mahalla"),
    ("مكتب بريد", "damanhour"), ("محل موبايلات", "benisuef"), ("ورشة ميكانيكا", "haram"), ("بقالة", "shebin"),
    ("عصير قصب", "qena"), ("ايس كريم", "smouha"), ("حلويات", "damietta"), ("شاورما", "portsaid"),
    ("بيتزا", "ismailia"), ("فول وطعمية", "luxor"), ("مطعم سمك", "suez"), ("مول", "kafrsheikh"),
    ("مستوصف", "banha"),
]]


# ═══ F. IMPORTANT — what every city has, in all 27 governorates, + national places ══════════════════
IMPORTANT: list[dict] = []

GOV_AR = {"cairo": "القاهرة", "giza": "الجيزة", "alexandria": "الإسكندرية", "qalyubia": "القليوبية",
          "dakahlia": "الدقهلية", "sharqia": "الشرقية", "gharbia": "الغربية", "monufia": "المنوفية",
          "beheira": "البحيرة", "kafr_el_sheikh": "كفر الشيخ", "damietta": "دمياط", "port_said": "بورسعيد",
          "ismailia": "الإسماعيلية", "suez": "السويس", "faiyum": "الفيوم", "beni_suef": "بني سويف", "minya": "المنيا",
          "asyut": "أسيوط", "sohag": "سوهاج", "qena": "قنا", "luxor": "الأقصر", "aswan": "أسوان",
          "red_sea": "البحر الأحمر", "south_sinai": "جنوب سيناء", "north_sinai": "شمال سيناء", "matrouh": "مطروح",
          "new_valley": "الوادي الجديد"}
GOV_EN = {"cairo": ["cairo"], "giza": ["giza"], "alexandria": ["alexandria"], "qalyubia": ["qalyubia", "qaliubiya"],
          "dakahlia": ["dakahlia"], "sharqia": ["sharqia", "sharkia"], "gharbia": ["gharbia", "gharbiya"],
          "monufia": ["monufia", "menoufia", "menofia"], "beheira": ["beheira", "behaira"],
          "kafr_el_sheikh": ["kafr el sheikh", "kafr elsheikh"], "damietta": ["damietta"], "port_said": ["port said"],
          "ismailia": ["ismailia"], "suez": ["suez"], "faiyum": ["faiyum", "fayoum"], "beni_suef": ["beni suef"],
          "minya": ["minya", "minia"], "asyut": ["asyut", "assiut"], "sohag": ["sohag"], "qena": ["qena"],
          "luxor": ["luxor"], "aswan": ["aswan"], "red_sea": ["red sea"], "south_sinai": ["south sinai"],
          "north_sinai": ["north sinai"], "matrouh": ["matrouh", "matruh"], "new_valley": ["new valley"]}
# each governorate's capital — where its directorate, its governorate building and most of what follows are
CAPITAL = {"cairo": (30.0444, 31.2357), "giza": (30.0131, 31.2089), "alexandria": (31.2001, 29.9187),
           "qalyubia": (30.4660, 31.1840), "dakahlia": (31.0409, 31.3785), "sharqia": (30.5877, 31.5020),
           "gharbia": (30.7865, 31.0004), "monufia": (30.5580, 31.0110), "beheira": (31.0341, 30.4682),
           "kafr_el_sheikh": (31.1107, 30.9388), "damietta": (31.4165, 31.8133), "port_said": (31.2653, 32.3019),
           "ismailia": (30.5965, 32.2715), "suez": (29.9668, 32.5498), "faiyum": (29.3084, 30.8428),
           "beni_suef": (29.0661, 31.0994), "minya": (28.1099, 30.7503), "asyut": (27.1809, 31.1837),
           "sohag": (26.5591, 31.6957), "qena": (26.1551, 32.7160), "luxor": (25.6872, 32.6396),
           "aswan": (24.0889, 32.8998), "red_sea": (27.2579, 33.8116),
           "south_sinai": (28.2410, 33.6220),  # El Tor, the capital — not Sharm
           "north_sinai": (31.1316, 33.7984), "matrouh": (31.3525, 27.2373), "new_valley": (25.4390, 30.5586)}


def IM(gov, kind, query, names, near, r, **gates):
    e = {"gov": gov, "kind": kind, "query": query, "names": list(names), "near": (float(near[0]), float(near[1])),
         "r": r}
    e.update(gates)
    IMPORTANT.append(e)


def IMK(gov, kind, query, key):
    e = K[key]
    IM(gov, kind, query, e[0], e[1], e[2], **(e[3] if len(e) > 3 else {}))


def SEC(gov, near=None, r=5000):
    g = GOV_AR[gov]
    IM(gov, "police", f"مديرية أمن {g}",
       [f"مديرية أمن {g}"] + [f"{en} security directorate" for en in GOV_EN[gov]], near or CAPITAL[gov], r, poi=True)


def HQ(gov, near=None, r=5000):
    g = GOV_AR[gov]
    IM(gov, "government", f"ديوان عام محافظة {g}",
       [f"ديوان محافظة {g}", f"مبنى محافظة {g}"] + [f"{en} governorate building" for en in GOV_EN[gov]]
       + [f"{en} governorate headquarters" for en in GOV_EN[gov]], near or CAPITAL[gov], r, poi=True)


def POL(gov, query, more=(), near=None, r=5000):
    j = _police([query] + list(more), near or CAPITAL[gov], r)["place"]
    IM(gov, "police", query, j["names"], j["near"], j["r"], poi=True)


def HOSP(gov, query, names, near=None, r=4000):
    IM(gov, "hospital", query, [query] + list(names), near or CAPITAL[gov], r)


def UNI(gov, x_ar, en, near=None, r=5000):
    IM(gov, "university", f"جامعة {x_ar}", [f"جامعة {x_ar}"] + [f"{e} university" for e in en], near or CAPITAL[gov], r)


def STA(gov, x_ar, en, near=None, r=3000):
    """The city's railway station: a train station that carries the city's name."""
    IM(gov, "station", f"محطة قطار {x_ar}", [x_ar, f"محطة {x_ar}"] + list(en), near or CAPITAL[gov], r,
       scats=["train_station"])


def STAD(gov, x_ar, en, near=None, r=4000):
    IM(gov, "stadium", f"استاد {x_ar}", [f"استاد {x_ar}", f"ستاد {x_ar}"] + [f"{e} stadium" for e in en],
       near or CAPITAL[gov], r)


# Cairo
SEC("cairo", near=(30.0445, 31.2530), r=1200)          # Bab El Khalq
HQ("cairo", near=(30.0436, 31.2465), r=1500)           # Abdeen
POL("cairo", "قسم شرطة الأزبكية", near=(30.0540, 31.2470), r=1500)
POL("cairo", "قسم شرطة قصر النيل", near=(30.0470, 31.2380), r=1500)
POL("cairo", "قسم أول مدينة نصر", near=(30.0590, 31.3300), r=4000)
IMK("cairo", "hospital", "مستشفى القصر العيني", "kasr")
IMK("cairo", "hospital", "مستشفى الدمرداش", "demerdash")
IMK("cairo", "hospital", "مستشفى 57357", "57357")
IMK("cairo", "university", "جامعة عين شمس", "ain_shams_uni")
IMK("cairo", "university", "جامعة الأزهر", "azhar_uni")
IMK("cairo", "university", "جامعة حلوان", "helwan_uni")
IMK("cairo", "university", "الجامعة الأمريكية", "auc")
IMK("cairo", "station", "محطة رمسيس", "ramses")
IMK("cairo", "station", "محطة مترو السادات", "metro_sadat")
IMK("cairo", "stadium", "استاد القاهرة", "cairo_stadium")
IMK("cairo", "other", "مطار القاهرة", "cairo_airport")
IMK("cairo", "landmark", "برج القاهرة", "cairo_tower")
IMK("cairo", "landmark", "المتحف المصري", "egy_museum")
IMK("cairo", "landmark", "قلعة صلاح الدين", "citadel")
IMK("cairo", "landmark", "خان الخليلي", "khan")
IMK("cairo", "landmark", "مسجد الحسين", "hussein")
IMK("cairo", "landmark", "حديقة الأزهر", "azhar_park")
IMK("cairo", "landmark", "المتحف القومي للحضارة", "nmec")
IMK("cairo", "landmark", "دار الأوبرا", "opera")
IMK("cairo", "landmark", "ميدان التحرير", "tahrir_sq")
IMK("cairo", "mall", "سيتي ستارز", "city_stars")
IMK("cairo", "mall", "كايرو فستيفال سيتي", "cfc")
IMK("cairo", "mall", "بوينت 90", "point90")
IMK("cairo", "business_park", "نايل سيتي", "nile_city")
IMK("cairo", "compound", "الرحاب", "rehab")
IMK("cairo", "compound", "مدينتي", "madinaty")
IMK("cairo", "compound", "ميفيدا", "mivida")
IMK("cairo", "compound", "قطامية هايتس", "katameya_heights")
IMK("cairo", "compound", "اب تاون كايرو", "uptown")
IMK("cairo", "other", "العاصمة الإدارية الجديدة", "nac")
IMK("cairo", "landmark", "البرج الأيقوني", "iconic_tower")
IMK("cairo", "hotel", "فندق سميراميس", "semiramis")
IMK("cairo", "hotel", "فندق ماريوت الزمالك", "marriott_zamalek")
IMK("cairo", "hotel", "فندق ريتز كارلتون", "nile_ritz")
IMK("cairo", "hotel", "فندق فورسيزونز نايل بلازا", "four_seasons_nile")
IMK("cairo", "hotel", "فندق فيرمونت نايل سيتي", "fairmont")
IMK("cairo", "hotel", "فندق رمسيس هيلتون", "ramses_hilton")
IMK("cairo", "ministry", "وزارة الخارجية", "mfa")
IMK("cairo", "ministry", "مجلس الوزراء", "cabinet")
IMK("cairo", "ministry", "البنك المركزي المصري", "cbe")
IMK("cairo", "other", "النادي الأهلي", "ahly")
# Giza
SEC("giza", r=5000)
HQ("giza", near=(30.0150, 31.2100), r=4000)
POL("giza", "قسم شرطة الدقي", near=(30.0385, 31.2120), r=2000)
POL("giza", "قسم شرطة الهرم", near=(30.0000, 31.1650), r=4000)
IMK("giza", "hospital", "مستشفى أم المصريين", "umm_masryeen")
IMK("giza", "hospital", "مستشفى دار الفؤاد", "dar_fouad")
IMK("giza", "university", "جامعة القاهرة", "cairo_uni")
IMK("giza", "station", "محطة الجيزة", "giza_station")
IMK("giza", "landmark", "الأهرامات", "pyramids")
IMK("giza", "landmark", "المتحف المصري الكبير", "gem")
IMK("giza", "landmark", "حديقة الحيوان", "giza_zoo")
IMK("giza", "business_park", "القرية الذكية", "smart_village")
IMK("giza", "mall", "مول العرب", "mall_arabia")
IMK("giza", "mall", "مول مصر", "mall_egypt")
IMK("giza", "mall", "أركان بلازا", "arkan")
IMK("giza", "compound", "بيفرلي هيلز", "beverly")
IMK("giza", "compound", "دريم لاند", "dreamland")
IMK("giza", "hotel", "فندق مينا هاوس", "mena_house")
IMK("giza", "other", "نادي الزمالك", "zamalek_club")
# Alexandria
SEC("alexandria", r=6000)
HQ("alexandria", r=6000)
POL("alexandria", "قسم شرطة سيدي جابر", near=(31.2186, 29.9419), r=2000)
POL("alexandria", "قسم شرطة العطارين", near=(31.1950, 29.9010), r=1500)
IMK("alexandria", "hospital", "المستشفى الأميري", "alex_main_hosp")
IMK("alexandria", "university", "جامعة الإسكندرية", "alex_uni")
IMK("alexandria", "station", "محطة مصر", "alex_misr_station")
IMK("alexandria", "station", "محطة سيدي جابر", "sidi_gaber_station")
IMK("alexandria", "stadium", "استاد الإسكندرية", "alex_stadium")
IMK("alexandria", "landmark", "مكتبة الإسكندرية", "bib_alex")
IMK("alexandria", "landmark", "قلعة قايتباي", "qaitbay")
IMK("alexandria", "landmark", "قصر المنتزه", "montaza_palace")
IMK("alexandria", "landmark", "عمود السواري", "pompey")
IMK("alexandria", "landmark", "المسرح الروماني", "roman_amph")
IMK("alexandria", "landmark", "مسجد المرسي أبو العباس", "morsi")
IMK("alexandria", "other", "مطار برج العرب", "borg_airport")
IMK("alexandria", "mall", "سان ستيفانو", "san_stefano")
IMK("alexandria", "mall", "سيتي سنتر الإسكندرية", "city_centre_alex")
IMK("alexandria", "hotel", "فندق سيسيل", "cecil")
IMK("alexandria", "other", "نادي سموحة", "smouha_club")
# Qalyubia (Banha)
SEC("qalyubia")
HQ("qalyubia")
POL("qalyubia", "قسم أول بنها")
POL("qalyubia", "قسم ثان شبرا الخيمة", more=["قسم ثاني شبرا الخيمة"], near=ANCHORS["shubra_kheima"][:2])
HOSP("qalyubia", "مستشفى بنها الجامعي", ["مستشفيات جامعة بنها", "benha university hospital"])
IMK("qalyubia", "university", "جامعة بنها", "benha_uni")
STA("qalyubia", "بنها", ["benha", "banha"])
STAD("qalyubia", "بنها", ["benha", "banha"])
IMK("qalyubia", "landmark", "القناطر الخيرية", "qanater")
# Dakahlia (Mansoura)
SEC("dakahlia")
HQ("dakahlia")
POL("dakahlia", "قسم أول المنصورة")
POL("dakahlia", "قسم ثان المنصورة", more=["قسم ثاني المنصورة"])
IMK("dakahlia", "hospital", "مستشفى المنصورة الجامعي", "mansoura_hosp")
IMK("dakahlia", "hospital", "مركز الكلى بالمنصورة", "urology_mansoura")
IMK("dakahlia", "university", "جامعة المنصورة", "mansoura_uni")
STA("dakahlia", "المنصورة", ["mansoura"])
STAD("dakahlia", "المنصورة", ["mansoura"])
# Sharqia (Zagazig)
SEC("sharqia")
HQ("sharqia")
POL("sharqia", "قسم أول الزقازيق")
POL("sharqia", "قسم ثان الزقازيق", more=["قسم ثاني الزقازيق"])
HOSP("sharqia", "مستشفيات جامعة الزقازيق", ["مستشفى جامعة الزقازيق", "مستشفى الزقازيق الجامعي",
                                             "zagazig university hospital"], r=5000)
IMK("sharqia", "university", "جامعة الزقازيق", "zagazig_uni")
STA("sharqia", "الزقازيق", ["zagazig"])
STAD("sharqia", "الزقازيق", ["zagazig"])
IMK("sharqia", "landmark", "تل بسطا", "tell_basta")
# Gharbia (Tanta)
SEC("gharbia")
HQ("gharbia")
POL("gharbia", "قسم أول طنطا")
POL("gharbia", "قسم ثان طنطا", more=["قسم ثاني طنطا"])
POL("gharbia", "قسم أول المحلة", more=["قسم أول المحلة الكبرى"], near=ANCHORS["mahalla"][:2])
POL("gharbia", "قسم ثان المحلة", more=["قسم ثان المحلة الكبرى", "قسم ثاني المحلة"], near=ANCHORS["mahalla"][:2])
IMK("gharbia", "hospital", "مستشفى طنطا الجامعي", "tanta_hosp")
IMK("gharbia", "university", "جامعة طنطا", "tanta_uni")
STA("gharbia", "طنطا", ["tanta"], r=2500)
STAD("gharbia", "طنطا", ["tanta"])
IMK("gharbia", "landmark", "مسجد السيد البدوي", "badawi")
# Monufia (Shebin El Kom)
SEC("monufia")
HQ("monufia")
POL("monufia", "قسم شرطة شبين الكوم")
HOSP("monufia", "مستشفى المنوفية الجامعي", ["مستشفيات جامعة المنوفية", "menoufia university hospital"], r=5000)
HOSP("monufia", "مستشفى شبين الكوم التعليمي", ["shebin el kom teaching hospital"])
IMK("monufia", "university", "جامعة المنوفية", "menoufia_uni")
STA("monufia", "شبين الكوم", ["shebin el kom", "shibin el kom"])
# Beheira (Damanhour)
SEC("beheira")
HQ("beheira")
POL("beheira", "قسم شرطة دمنهور", more=["قسم أول دمنهور"])
HOSP("beheira", "مستشفى دمنهور التعليمي", ["damanhour teaching hospital", "damanhour medical national institute"])
UNI("beheira", "دمنهور", ["damanhour"], r=6000)
STA("beheira", "دمنهور", ["damanhour"])
STAD("beheira", "دمنهور", ["damanhour"])
# Kafr El Sheikh
SEC("kafr_el_sheikh")
HQ("kafr_el_sheikh")
POL("kafr_el_sheikh", "قسم أول كفر الشيخ")
HOSP("kafr_el_sheikh", "مستشفى كفر الشيخ الجامعي", ["مستشفيات جامعة كفر الشيخ", "kafrelsheikh university hospital"],
     r=6000)
HOSP("kafr_el_sheikh", "مستشفى كفر الشيخ العام", ["kafr el sheikh general hospital"])
IMK("kafr_el_sheikh", "university", "جامعة كفر الشيخ", "kfs_uni")
STA("kafr_el_sheikh", "كفر الشيخ", ["kafr el sheikh", "kafr elsheikh"])
STAD("kafr_el_sheikh", "كفر الشيخ", ["kafr el sheikh", "kafr elsheikh"])
# Damietta
SEC("damietta")
HQ("damietta")
POL("damietta", "قسم أول دمياط")
POL("damietta", "قسم ثان دمياط", more=["قسم ثاني دمياط"])
HOSP("damietta", "مستشفى دمياط التخصصي", ["مستشفى دمياط العام", "damietta specialized hospital",
                                          "damietta general hospital"], r=6000)
IMK("damietta", "university", "جامعة دمياط", "damietta_uni")
STA("damietta", "دمياط", ["damietta"])
STAD("damietta", "دمياط", ["damietta"])
IMK("damietta", "other", "ميناء دمياط", "damietta_port")
IMK("damietta", "other", "رأس البر", "ras_el_bar")
# Port Said
SEC("port_said")
HQ("port_said")
POL("port_said", "قسم شرطة العرب", more=["قسم العرب"])
POL("port_said", "قسم شرطة الشرق", more=["قسم الشرق"])
HOSP("port_said", "مستشفى بورسعيد العام", ["port said general hospital"], r=5000)
UNI("port_said", "بورسعيد", ["port said"], r=6000)
STA("port_said", "بورسعيد", ["port said"])
STAD("port_said", "بورسعيد", ["port said"], near=(31.2550, 32.2950))
IMK("port_said", "government", "مبنى هيئة قناة السويس", "sca_portsaid")
IMK("port_said", "other", "بورفؤاد", "port_fouad")
# Ismailia
SEC("ismailia")
HQ("ismailia")
POL("ismailia", "قسم أول الإسماعيلية")
POL("ismailia", "قسم ثان الإسماعيلية", more=["قسم ثاني الإسماعيلية"])
HOSP("ismailia", "مستشفى جامعة قناة السويس", ["مستشفيات جامعة قناة السويس", "suez canal university hospital"],
     near=(30.6200, 32.2700), r=4000)
HOSP("ismailia", "مستشفى الإسماعيلية العام", ["ismailia general hospital"])
IMK("ismailia", "university", "جامعة قناة السويس", "scu")
STA("ismailia", "الإسماعيلية", ["ismailia"], r=2500)
STAD("ismailia", "الإسماعيلية", ["ismailia", "ismaily"])
IMK("ismailia", "landmark", "بحيرة التمساح", "timsah")
# Suez
SEC("suez", r=6000)
HQ("suez", r=6000)
POL("suez", "قسم شرطة السويس", more=["قسم السويس"], r=6000)
POL("suez", "قسم شرطة الأربعين", more=["قسم الأربعين"], r=6000)
HOSP("suez", "مستشفى السويس العام", ["suez general hospital"], r=6000)
UNI("suez", "السويس", ["suez"], r=10000)
STA("suez", "السويس", ["suez"], r=5000)
STAD("suez", "السويس", ["suez"], r=6000)
# Faiyum
SEC("faiyum")
HQ("faiyum")
POL("faiyum", "قسم أول الفيوم")
POL("faiyum", "قسم ثان الفيوم", more=["قسم ثاني الفيوم"])
HOSP("faiyum", "مستشفى الفيوم العام", ["fayoum general hospital", "faiyum general hospital"])
HOSP("faiyum", "مستشفى الفيوم الجامعي", ["مستشفيات جامعة الفيوم", "fayoum university hospital"], r=6000)
IMK("faiyum", "university", "جامعة الفيوم", "fayoum_uni")
STA("faiyum", "الفيوم", ["fayoum", "faiyum"], r=2500)
STAD("faiyum", "الفيوم", ["fayoum", "faiyum"])
IM("faiyum", "landmark", "سواقي الفيوم", ["سواقي الفيوم", "السواقي", "water wheels", "fayoum water wheels"],
   (29.3090, 30.8420), 1500)
IMK("faiyum", "landmark", "بحيرة قارون", "qarun")
# Beni Suef
SEC("beni_suef")
HQ("beni_suef")
POL("beni_suef", "قسم شرطة بني سويف", more=["قسم أول بني سويف"])
HOSP("beni_suef", "مستشفى بني سويف الجامعي", ["مستشفيات جامعة بني سويف", "beni suef university hospital"], r=8000)
HOSP("beni_suef", "مستشفى بني سويف العام", ["beni suef general hospital"])
IMK("beni_suef", "university", "جامعة بني سويف", "beni_suef_uni")
STA("beni_suef", "بني سويف", ["beni suef"], r=2500)
STAD("beni_suef", "بني سويف", ["beni suef"])
# Minya
SEC("minya")
HQ("minya")
POL("minya", "قسم أول المنيا")
POL("minya", "قسم ثان المنيا", more=["قسم ثاني المنيا"])
HOSP("minya", "مستشفى المنيا الجامعي", ["مستشفيات جامعة المنيا", "minia university hospital"], r=5000)
IMK("minya", "university", "جامعة المنيا", "minia_uni")
STA("minya", "المنيا", ["minya", "minia"], r=2500)
STAD("minya", "المنيا", ["minya", "minia"])
IMK("minya", "landmark", "تل العمارنة", "amarna")
# Asyut
SEC("asyut")
HQ("asyut")
POL("asyut", "قسم أول أسيوط")
POL("asyut", "قسم ثان أسيوط", more=["قسم ثاني أسيوط"])
IMK("asyut", "hospital", "مستشفى أسيوط الجامعي", "asyut_hosp")
IMK("asyut", "university", "جامعة أسيوط", "asyut_uni")
STA("asyut", "أسيوط", ["assiut", "asyut"], r=2500)
STAD("asyut", "أسيوط", ["assiut", "asyut"])
# Sohag
SEC("sohag")
HQ("sohag")
POL("sohag", "قسم أول سوهاج")
POL("sohag", "قسم ثان سوهاج", more=["قسم ثاني سوهاج"])
HOSP("sohag", "مستشفى سوهاج الجامعي", ["مستشفيات جامعة سوهاج", "sohag university hospital"], r=8000)
IMK("sohag", "university", "جامعة سوهاج", "sohag_uni")
STA("sohag", "سوهاج", ["sohag"], r=2500)
STAD("sohag", "سوهاج", ["sohag"])
IMK("sohag", "landmark", "الدير الأبيض", "white_monastery")
# Qena
SEC("qena")
HQ("qena")
POL("qena", "قسم شرطة قنا", more=["قسم أول قنا"])
HOSP("qena", "مستشفى قنا العام", ["qena general hospital"])
HOSP("qena", "مستشفى قنا الجامعي", ["مستشفيات جامعة جنوب الوادي", "qena university hospital",
                                     "south valley university hospital"], r=6000)
IMK("qena", "university", "جامعة جنوب الوادي", "svu")
STA("qena", "قنا", ["qena"])
STAD("qena", "قنا", ["qena"])
IMK("qena", "landmark", "معبد دندرة", "dendera")
# Luxor
SEC("luxor")
HQ("luxor")
POL("luxor", "قسم شرطة الأقصر", more=["قسم أول الأقصر"])
HOSP("luxor", "مستشفى الأقصر الدولي", ["luxor international hospital"], r=7000)
HOSP("luxor", "مستشفى الأقصر العام", ["luxor general hospital"])
UNI("luxor", "الأقصر", ["luxor"], r=10000)
STA("luxor", "الأقصر", ["luxor"], r=2500)
IMK("luxor", "other", "مطار الأقصر", "luxor_airport")
STAD("luxor", "الأقصر", ["luxor"], r=5000)
IMK("luxor", "landmark", "معبد الكرنك", "karnak")
IMK("luxor", "landmark", "معبد الأقصر", "luxor_temple")
IMK("luxor", "landmark", "وادي الملوك", "valley_kings")
IMK("luxor", "landmark", "معبد حتشبسوت", "hatshepsut")
IMK("luxor", "hotel", "فندق ونتر بالاس", "winter_palace")
# Aswan
SEC("aswan")
HQ("aswan")
POL("aswan", "قسم أول أسوان")
POL("aswan", "قسم ثان أسوان", more=["قسم ثاني أسوان"])
HOSP("aswan", "مستشفى أسوان الجامعي", ["مستشفيات جامعة أسوان", "aswan university hospital"], r=6000)
UNI("aswan", "أسوان", ["aswan"], r=12000)
STA("aswan", "أسوان", ["aswan"], r=2500)
IMK("aswan", "other", "مطار أسوان", "aswan_airport")
STAD("aswan", "أسوان", ["aswan"], r=5000)
IMK("aswan", "landmark", "السد العالي", "high_dam")
IMK("aswan", "landmark", "معبد فيلة", "philae")
IMK("aswan", "landmark", "أبو سمبل", "abu_simbel")
IMK("aswan", "hotel", "فندق كتراكت", "cataract")
# Red Sea (Hurghada)
SEC("red_sea")
HQ("red_sea")
POL("red_sea", "قسم أول الغردقة", r=7000)
POL("red_sea", "قسم ثان الغردقة", more=["قسم ثاني الغردقة"], r=7000)
HOSP("red_sea", "مستشفى الغردقة العام", ["hurghada general hospital"], near=(27.2470, 33.8150), r=4000)
IMK("red_sea", "other", "مطار الغردقة", "hurghada_airport")
IM("red_sea", "other", "ميناء الغردقة", ["ميناء الغردقة", "hurghada port", "port of hurghada"], (27.2290, 33.8430), 3000)
STAD("red_sea", "الغردقة", ["hurghada"], r=7000)
IMK("red_sea", "compound", "الجونة", "gouna")
IMK("red_sea", "landmark", "مارينا الغردقة", "hurghada_marina")
IM("red_sea", "other", "مرسى علم", ["مرسى علم", "marsa alam"], (25.0700, 34.8900), 8000, area=True)
# South Sinai (El Tor is the capital)
SEC("south_sinai")
HQ("south_sinai")
POL("south_sinai", "قسم شرطة شرم الشيخ", more=["قسم أول شرم الشيخ"], near=ANCHORS["sharm"][:2], r=8000)
HOSP("south_sinai", "مستشفى شرم الشيخ الدولي", ["sharm el sheikh international hospital"],
     near=ANCHORS["sharm"][:2], r=8000)
HOSP("south_sinai", "مستشفى الطور العام", ["el tor general hospital", "tor general hospital"])
IMK("south_sinai", "other", "مطار شرم الشيخ", "sharm_airport")
IMK("south_sinai", "landmark", "خليج نعمة", "naama")
IMK("south_sinai", "landmark", "دير سانت كاترين", "catherine")
IMK("south_sinai", "landmark", "رأس محمد", "ras_mohammed")
IM("south_sinai", "other", "دهب", ["دهب", "dahab"], ANCHORS["dahab"][:2], 6000, area=True)
# North Sinai (El Arish)
SEC("north_sinai")
HQ("north_sinai")
POL("north_sinai", "قسم أول العريش", r=6000)
HOSP("north_sinai", "مستشفى العريش العام", ["el arish general hospital", "arish general hospital"], r=6000)
UNI("north_sinai", "العريش", ["arish", "el arish"], r=8000)
IMK("north_sinai", "other", "مطار العريش", "arish_airport")
STAD("north_sinai", "العريش", ["arish", "el arish"], r=6000)
# Matrouh (Marsa Matrouh)
SEC("matrouh")
HQ("matrouh")
POL("matrouh", "قسم شرطة مرسى مطروح", more=["قسم مرسى مطروح"])
HOSP("matrouh", "مستشفى مطروح العام", ["مستشفى مرسى مطروح العام", "matrouh general hospital"])
UNI("matrouh", "مطروح", ["matrouh", "matruh"], r=8000)
IMK("matrouh", "other", "مطار مرسى مطروح", "matrouh_airport")
STA("matrouh", "مرسى مطروح", ["marsa matrouh", "mersa matruh", "matrouh"], r=4000)
IMK("matrouh", "other", "واحة سيوة", "siwa")
IM("matrouh", "other", "العلمين الجديدة", ["العلمين الجديدة", "new alamein", "new el alamein"], (30.8300, 28.9500), 10000)
IM("matrouh", "compound", "مراسي", ["مراسي", "marassi"], (30.9700, 28.7700), 6000)
# New Valley (Kharga)
SEC("new_valley")
HQ("new_valley")
POL("new_valley", "قسم شرطة الخارجة", more=["قسم الخارجة"])
HOSP("new_valley", "مستشفى الخارجة العام", ["kharga general hospital", "el kharga general hospital"])
UNI("new_valley", "الوادي الجديد", ["new valley"], r=12000)
IMK("new_valley", "other", "مطار الخارجة", "kharga_airport")
IMK("new_valley", "landmark", "معبد هيبس", "hibis")
IM("new_valley", "other", "الداخلة", ["الداخلة", "dakhla", "el dakhla"], (25.4950, 28.9790), 12000, area=True)

SUITES = {"prefix": PREFIX, "exact": EXACT, "variant": VARIANT, "need": NEED, "script": SCRIPT, "important": IMPORTANT}
KINDS = {"police", "government", "hospital", "university", "station", "stadium", "mall", "business_park", "compound",
         "hotel", "landmark", "ministry", "other"}


def anchor(at) -> tuple[float, float]:
    if isinstance(at, (tuple, list)):
        return float(at[0]), float(at[1])
    a = ANCHORS[at]
    return a[0], a[1]


def validate() -> list[str]:
    """Every entry well formed: an anchor that exists, exactly one judge, coordinates inside Egypt, a
    known governorate and kind. The runner refuses to start on a problem."""
    out = []
    govs = {a[2] for a in ANCHORS.values()}

    def in_egypt(p):
        return 21.5 <= p[0] <= 31.8 and 24.5 <= p[1] <= 36.0

    for s, items in SUITES.items():
        for i, e in enumerate(items):
            tag = f"{s}[{i}] {e.get('q') or e.get('query')!r}"
            if s == "important":
                if e["gov"] not in govs:
                    out.append(f"{tag}: unknown gov {e['gov']}")
                if e["kind"] not in KINDS:
                    out.append(f"{tag}: unknown kind {e['kind']}")
                if not e["names"] or not in_egypt(e["near"]):
                    out.append(f"{tag}: names / near")
                continue
            if isinstance(e["at"], str) and e["at"] not in ANCHORS:
                out.append(f"{tag}: unknown anchor {e['at']}")
            judges = [k for k in ("place", "cat", "chain") if k in e]
            if s == "script":
                if judges:
                    out.append(f"{tag}: the script suite has no judge")
                continue
            if len(judges) != 1:
                out.append(f"{tag}: needs exactly one judge, has {judges}")
                continue
            if "place" in e and not in_egypt(e["place"]["near"]):
                out.append(f"{tag}: near outside Egypt")
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    probs = validate()
    for p in probs:
        print("PROBLEM", p)
    for s, items in SUITES.items():
        print(s, len(items))
