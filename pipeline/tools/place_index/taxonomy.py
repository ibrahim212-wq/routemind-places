"""The place index's category taxonomy — what a place IS, in both languages.

Two levels:

  * the DISPLAY category (`cat`): fine-grained ("dental_clinic", "womens_clothing_store"), with an
    Arabic and an English label, shown under the name in every result row and sheet. Each source's
    own vocabulary maps onto it here — Overture's taxonomy by walking its hierarchy from the leaf up,
    OSM's tags by the ordered rules in OSM_RULES (the first rule that matches wins), Foursquare's by
    FSQ_LEAF.
  * the SEARCH category (`scat`): the coarse id the query side understands. It is the `id` of an
    entry in the app's lexicon (lib/features/search/domain/lexicon/egypt_categories.dart, exported to
    assets/search/egypt_lexicon.json), so «بنزينة», «محطة بنزين», «gas station», «banzina» all reach
    every place whose display category points at `gas_station`. build.py refuses an scat the lexicon
    does not define.

`prom` is the class importance used by the popularity score (the same scale as the Dart ranker's
Prominence.classImportance): an airport 1.0, a hospital 0.86 … a kiosk 0.3.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cat:
    id: str
    en: str
    ar: str
    scat: str | None  # lexicon search category, None = searchable by name only
    prom: float


def _c(id, en, ar, scat, prom):
    return Cat(id, en, ar, scat, prom)


CATS: list[Cat] = [
    # ── health ──
    _c("hospital", "Hospital", "مستشفى", "hospital", 0.86),
    _c("emergency_room", "Emergency", "طوارئ", "hospital", 0.80),
    _c("pharmacy", "Pharmacy", "صيدلية", "pharmacy", 0.50),
    _c("clinic", "Clinic", "عيادة", "clinic", 0.48),
    _c("medical_center", "Medical center", "مركز طبي", "clinic", 0.55),
    _c("doctor", "Doctor", "دكتور", "clinic", 0.45),
    _c("dental_clinic", "Dental clinic", "عيادة أسنان", "dentist", 0.46),
    _c("medical_lab", "Medical lab", "معمل تحاليل", "medical_lab", 0.48),
    _c("radiology", "Radiology center", "مركز أشعة", "radiology", 0.50),
    _c("physiotherapy", "Physiotherapy", "علاج طبيعي", "physiotherapy", 0.42),
    _c("eye_clinic", "Eye clinic", "مركز عيون", "clinic", 0.48),
    _c("health_unit", "Health unit", "وحدة صحية", "health_unit", 0.50),
    _c("veterinary", "Veterinary clinic", "عيادة بيطرية", "veterinary", 0.42),
    _c("medical_supply", "Medical supplies", "مستلزمات طبية", None, 0.35),
    # ── money ──
    _c("bank", "Bank", "بنك", "bank", 0.58),
    _c("atm", "ATM", "ماكينة صراف", "atm", 0.40),
    _c("exchange", "Currency exchange", "صرافة", "exchange", 0.42),
    _c("insurance", "Insurance", "تأمين", None, 0.38),
    _c("financial_service", "Financial services", "خدمات مالية", None, 0.36),
    _c("post_office", "Post office", "مكتب بريد", "post_office", 0.55),
    _c("money_transfer", "Payment point", "خدمات دفع", "electricity_payment", 0.33),
    # ── car ──
    _c("gas_station", "Fuel station", "محطة بنزين", "gas_station", 0.52),
    _c("ev_charging", "EV charging", "شحن سيارات كهربائية", "ev_charging", 0.45),
    _c("car_repair", "Car repair", "ورشة سيارات", "car_repair", 0.34),
    _c("car_wash", "Car wash", "غسيل سيارات", "car_wash", 0.34),
    _c("tyre_shop", "Tyre shop", "محل كاوتش", "tyre_shop", 0.34),
    _c("oil_change", "Oil change", "تغيير زيت", "oil_change", 0.34),
    _c("car_battery", "Car batteries", "بطاريات سيارات", "battery_shop", 0.33),
    _c("auto_parts", "Auto parts", "قطع غيار سيارات", "auto_parts", 0.36),
    _c("car_dealer", "Car dealer", "معرض سيارات", "car_dealer", 0.42),
    _c("car_rental", "Car rental", "تأجير سيارات", "car_rental", 0.38),
    _c("motorcycle_shop", "Motorcycles", "موتوسيكلات", None, 0.32),
    _c("towing", "Towing", "ونش", "roadside_assistance", 0.34),
    _c("parking", "Parking", "جراج", "parking", 0.38),
    _c("driving_school", "Driving school", "مدرسة قيادة", None, 0.36),
    # ── food ──
    _c("restaurant", "Restaurant", "مطعم", "restaurant", 0.48),
    _c("fast_food", "Fast food", "وجبات سريعة", "fast_food", 0.46),
    _c("cafe", "Café", "كافيه", "cafe", 0.42),
    _c("coffee_shop", "Coffee shop", "كوفي شوب", "cafe", 0.42),
    _c("ahwa", "Café (ahwa)", "قهوة", "cafe", 0.40),
    _c("bakery", "Bakery", "مخبز", "bakery", 0.38),
    _c("sweets", "Sweets", "حلواني", "sweets", 0.40),
    _c("ice_cream", "Ice cream", "آيس كريم", "ice_cream", 0.38),
    _c("juice_bar", "Juice bar", "عصير", "juice_bar", 0.34),
    _c("koshary", "Koshary", "كشري", "koshary", 0.42),
    _c("grill", "Grill", "مشويات", "grill", 0.44),
    _c("seafood", "Seafood", "مأكولات بحرية", "seafood", 0.44),
    _c("pizza", "Pizza", "بيتزا", "pizza", 0.44),
    _c("burger", "Burgers", "برجر", "burger", 0.44),
    _c("chicken", "Fried chicken", "فراخ", "fast_food", 0.44),
    _c("foul_taameya", "Foul & taameya", "فول وطعمية", "foul_taameya", 0.40),
    _c("shawarma", "Shawarma", "شاورما", "fast_food", 0.42),
    _c("bar", "Bar", "بار", None, 0.35),
    _c("food_court", "Food court", "فود كورت", "restaurant", 0.45),
    # ── shopping ──
    _c("supermarket", "Supermarket", "سوبر ماركت", "supermarket", 0.54),
    _c("hypermarket", "Hypermarket", "هايبر ماركت", "supermarket", 0.68),
    _c("grocery", "Grocery", "بقالة", "supermarket", 0.36),
    _c("convenience", "Convenience store", "ماركت", "supermarket", 0.34),
    _c("kiosk", "Kiosk", "كشك", None, 0.25),
    _c("mall", "Shopping mall", "مول", "mall", 0.72),
    _c("department_store", "Department store", "محلات كبرى", "mall", 0.55),
    _c("market", "Market", "سوق", "market", 0.50),
    _c("butcher", "Butcher", "جزارة", "butcher", 0.34),
    _c("poultry", "Poultry shop", "فراخ", "butcher", 0.32),
    _c("fishmonger", "Fish shop", "سمك", "seafood", 0.34),
    _c("greengrocer", "Fruit & vegetables", "خضار وفاكهة", "greengrocer", 0.32),
    _c("dairy", "Dairy", "ألبان", None, 0.32),
    _c("spices", "Spices & nuts", "عطارة وبن", "spices", 0.33),
    _c("mobile_shop", "Mobile phones", "موبايلات", "mobile_shop", 0.40),
    _c("telecom", "Telecom store", "فرع اتصالات", "mobile_shop", 0.45),
    _c("electronics", "Electronics", "إلكترونيات", "electronics_store", 0.40),
    _c("computer_store", "Computers", "كمبيوتر", "electronics_store", 0.38),
    _c("appliances", "Home appliances", "أجهزة كهربائية", "appliance_store", 0.40),
    _c("clothes", "Clothing", "ملابس", "clothing_store", 0.36),
    _c("womens_clothes", "Women's clothing", "ملابس حريمي", "clothing_store", 0.36),
    _c("mens_clothes", "Men's clothing", "ملابس رجالي", "clothing_store", 0.36),
    _c("kids_clothes", "Kids' clothing", "ملابس أطفال", "clothing_store", 0.36),
    _c("bridal", "Bridal", "فساتين زفاف", "clothing_store", 0.34),
    _c("shoes", "Shoes", "أحذية", "shoe_store", 0.36),
    _c("bags", "Bags & luggage", "شنط", None, 0.32),
    _c("sportswear", "Sportswear", "ملابس رياضية", "clothing_store", 0.36),
    _c("jewelry", "Jewelry", "مجوهرات", "jewelry_store", 0.38),
    _c("watches", "Watches", "ساعات", "jewelry_store", 0.34),
    _c("optician", "Optician", "نظارات", "optician", 0.38),
    _c("perfume", "Perfumes", "عطور", "perfume", 0.36),
    _c("cosmetics", "Cosmetics", "مستحضرات تجميل", "cosmetics", 0.36),
    _c("furniture", "Furniture", "موبيليا", "furniture_store", 0.38),
    _c("home_goods", "Home goods", "أدوات منزلية", "home_goods_store", 0.36),
    _c("hardware", "Hardware store", "أدوات وعدد", "hardware_store", 0.34),
    _c("paint", "Paint store", "دهانات", "hardware_store", 0.32),
    _c("building_materials", "Building materials", "مواد بناء", "hardware_store", 0.34),
    _c("sanitary", "Sanitary ware", "أدوات صحية", "hardware_store", 0.33),
    _c("lighting", "Lighting", "نجف وإضاءة", "home_goods_store", 0.32),
    _c("carpet", "Carpets", "سجاد", "home_goods_store", 0.33),
    _c("fabric", "Fabrics", "أقمشة", "fabric_store", 0.32),
    _c("bookshop", "Bookshop", "مكتبة", "bookshop", 0.36),
    _c("stationery", "Stationery", "أدوات مكتبية", "bookshop", 0.33),
    _c("toys", "Toys", "لعب أطفال", "toy_store", 0.33),
    _c("gifts", "Gifts", "هدايا", "gift_shop", 0.32),
    _c("florist", "Florist", "محل ورد", "florist", 0.32),
    _c("pets", "Pet shop", "مستلزمات حيوانات أليفة", "pet_store", 0.32),
    _c("sports_store", "Sports store", "أدوات رياضية", "sports_store", 0.34),
    _c("music_store", "Music store", "آلات موسيقية", None, 0.32),
    _c("tobacco", "Tobacco", "سجاير", None, 0.28),
    _c("second_hand", "Second hand", "مستعمل", None, 0.30),
    _c("shop", "Shop", "محل", None, 0.30),
    # ── services ──
    _c("laundry", "Laundry", "مغسلة", "laundry", 0.32),
    _c("dry_cleaning", "Dry cleaning", "دراي كلين", "laundry", 0.32),
    _c("barber", "Barber", "حلاق", "barber", 0.32),
    _c("hair_salon", "Hair salon", "كوافير", "barber", 0.33),
    _c("beauty_salon", "Beauty salon", "بيوتي سنتر", "beauty_salon", 0.35),
    _c("spa", "Spa", "سبا", "spa", 0.36),
    _c("tailor", "Tailor", "ترزي", "tailor", 0.30),
    _c("print_shop", "Print shop", "مطبعة وتصوير", "print_shop", 0.32),
    _c("internet_cafe", "Internet café", "سايبر", "internet_cafe", 0.30),
    _c("phone_repair", "Phone repair", "صيانة موبايلات", "mobile_shop", 0.32),
    _c("appliance_repair", "Appliance repair", "صيانة أجهزة", None, 0.30),
    _c("plumber", "Plumber", "سباك", "plumber", 0.30),
    _c("electrician", "Electrician", "كهربائي", "electrician", 0.30),
    _c("carpenter", "Carpenter", "نجار", "carpenter", 0.30),
    _c("locksmith", "Locksmith", "مفاتيح", None, 0.28),
    _c("real_estate", "Real estate", "عقارات", "real_estate_agent", 0.34),
    _c("developer", "Real estate developer", "تطوير عقاري", "real_estate_agent", 0.40),
    _c("travel_agency", "Travel agency", "شركة سياحة", "travel_agency", 0.36),
    _c("lawyer", "Lawyer", "محامي", "lawyer", 0.34),
    _c("accountant", "Accountant", "محاسب", None, 0.32),
    _c("office", "Office", "مكتب", None, 0.32),
    _c("company", "Company", "شركة", "company", 0.38),
    _c("coworking", "Coworking", "مساحة عمل", None, 0.34),
    _c("factory", "Factory", "مصنع", "factory", 0.40),
    _c("warehouse", "Warehouse", "مخزن", None, 0.30),
    _c("shipping", "Shipping", "شحن", "shipping", 0.34),
    _c("event_service", "Events", "تنظيم حفلات", None, 0.30),
    _c("photographer", "Photography", "تصوير", None, 0.30),
    _c("advertising", "Advertising", "دعاية وإعلان", None, 0.30),
    _c("tech_company", "Tech company", "شركة تكنولوجيا", "company", 0.38),
    _c("ngo", "Organization", "جمعية", "ngo", 0.38),
    _c("farm", "Farm", "مزرعة", None, 0.30),
    _c("cleaning", "Cleaning", "تنظيف", None, 0.28),
    _c("moving", "Movers", "نقل أثاث", None, 0.28),
    _c("construction", "Construction", "مقاولات", None, 0.30),
    _c("service", "Services", "خدمات", None, 0.30),
    # ── government / civic ──
    _c("police", "Police station", "قسم شرطة", "police", 0.62),
    _c("traffic_department", "Traffic department", "إدارة مرور", "traffic_department", 0.62),
    _c("civil_registry", "Civil registry", "سجل مدني", "civil_registry", 0.60),
    _c("notary", "Notary", "مكتب توثيق", "notary", 0.58),
    _c("real_estate_registry", "Real estate registry", "الشهر العقاري", "real_estate_registry", 0.60),
    _c("courthouse", "Courthouse", "محكمة", "courthouse", 0.62),
    _c("government", "Government office", "مصلحة حكومية", "government_office", 0.62),
    _c("townhall", "City council", "مجلس مدينة", "government_office", 0.64),
    _c("ministry", "Ministry", "وزارة", "government_office", 0.68),
    _c("embassy", "Embassy", "سفارة", "embassy", 0.62),
    _c("fire_station", "Fire station", "مطافي", "fire_station", 0.55),
    _c("telecom_exchange", "Telephone exchange", "سنترال", "telecom_exchange", 0.55),
    _c("electricity_office", "Electricity office", "شركة الكهرباء", "electricity_payment", 0.52),
    _c("water_office", "Water company", "شركة المياه", "government_office", 0.50),
    _c("military", "Military", "منطقة عسكرية", None, 0.40),
    _c("community_center", "Community center", "مركز شباب", "community_center", 0.45),
    # ── religion ──
    _c("mosque", "Mosque", "مسجد", "mosque", 0.50),
    _c("church", "Church", "كنيسة", "church", 0.50),
    _c("monastery", "Monastery", "دير", "church", 0.60),
    _c("place_of_worship", "Place of worship", "دار عبادة", None, 0.45),
    # ── education ──
    _c("school", "School", "مدرسة", "school", 0.54),
    _c("kindergarten", "Nursery", "حضانة", "kindergarten", 0.40),
    _c("university", "University", "جامعة", "university", 0.80),
    _c("college", "College", "كلية", "university", 0.72),
    _c("institute", "Institute", "معهد", "institute", 0.52),
    _c("language_school", "Language center", "مركز لغات", "institute", 0.40),
    _c("training_center", "Training center", "مركز تدريب", "institute", 0.38),
    _c("tutoring", "Tutoring center", "سنتر دروس", "tutoring", 0.36),
    _c("library", "Library", "مكتبة عامة", "library", 0.52),
    # ── transport ──
    _c("airport", "Airport", "مطار", "airport", 1.00),
    _c("train_station", "Train station", "محطة قطر", "train_station", 0.78),
    _c("metro_station", "Metro station", "محطة مترو", "metro_station", 0.66),
    _c("monorail_station", "Monorail station", "محطة مونوريل", "metro_station", 0.62),
    _c("lrt_station", "LRT station", "محطة القطار الكهربائي", "metro_station", 0.62),
    _c("bus_station", "Bus station", "موقف أتوبيس", "bus_station", 0.66),
    _c("bus_stop", "Bus stop", "محطة أتوبيس", "bus_station", 0.30),
    _c("microbus_stand", "Microbus stand", "موقف ميكروباص", "bus_station", 0.50),
    _c("ferry", "Ferry", "معدية", "ferry", 0.50),
    _c("port", "Port", "ميناء", "port", 0.70),
    _c("taxi", "Taxi", "تاكسي", None, 0.30),
    _c("rest_area", "Rest area", "استراحة", "rest_area", 0.50),
    _c("toll_gate", "Toll gate", "بوابة رسوم", None, 0.55),
    # ── leisure / culture ──
    _c("hotel", "Hotel", "فندق", "hotel", 0.58),
    _c("resort", "Resort", "منتجع", "hotel", 0.62),
    _c("hostel", "Hostel", "هوستل", "hotel", 0.40),
    _c("apartment_hotel", "Serviced apartments", "شقق فندقية", "hotel", 0.42),
    _c("camp_site", "Camp", "كامب", "hotel", 0.42),
    _c("park", "Park", "حديقة", "park", 0.55),
    _c("garden", "Garden", "جنينة", "park", 0.45),
    _c("playground", "Playground", "ملاهي أطفال", "park", 0.35),
    _c("amusement_park", "Amusement park", "ملاهي", "amusement_park", 0.65),
    _c("zoo", "Zoo", "حديقة حيوان", "park", 0.70),
    _c("beach", "Beach", "شاطئ", "beach", 0.62),
    _c("museum", "Museum", "متحف", "museum", 0.72),
    _c("historic_site", "Historic site", "أثر تاريخي", "historic_site", 0.66),
    _c("monument", "Monument", "نصب تذكاري", "historic_site", 0.60),
    _c("attraction", "Attraction", "مزار سياحي", "attraction", 0.70),
    _c("viewpoint", "Viewpoint", "مكان للمشاهدة", "attraction", 0.50),
    _c("cinema", "Cinema", "سينما", "cinema", 0.55),
    _c("theater", "Theater", "مسرح", "theater", 0.60),
    _c("art_gallery", "Art gallery", "جاليري", None, 0.45),
    _c("cultural_center", "Cultural center", "مركز ثقافي", "cultural_center", 0.55),
    _c("event_venue", "Event venue", "قاعة أفراح", "event_venue", 0.45),
    _c("stadium", "Stadium", "استاد", "stadium", 0.74),
    _c("sports_club", "Sports club", "نادي", "sports_club", 0.60),
    _c("gym", "Gym", "جيم", "gym", 0.44),
    _c("swimming_pool", "Swimming pool", "حمام سباحة", "sports_club", 0.42),
    _c("sports_field", "Sports field", "ملعب", "sports_field", 0.38),
    _c("diving_center", "Diving center", "مركز غطس", None, 0.42),
    _c("nightclub", "Night club", "ديسكو", None, 0.38),
    _c("lounge", "Lounge", "لاونج", "cafe", 0.40),
    # ── geography (named features that are not settlements) ──
    _c("mountain", "Mountain", "جبل", None, 0.55),
    _c("island", "Island", "جزيرة", None, 0.55),
    _c("lake", "Lake", "بحيرة", None, 0.55),
    _c("water", "Water", "مسطح مائي", None, 0.45),
    _c("natural", "Natural feature", "معلم طبيعي", None, 0.45),
    _c("square", "Square", "ميدان", "square", 0.62),
    _c("bridge", "Bridge", "كوبري", "bridge", 0.62),
    _c("tunnel", "Tunnel", "نفق", None, 0.58),
    _c("landmark", "Landmark", "معلم", "attraction", 0.66),
    _c("cemetery", "Cemetery", "مقابر", "cemetery", 0.45),
    _c("compound", "Compound", "كمبوند", "compound", 0.55),
    _c("industrial_zone", "Industrial zone", "منطقة صناعية", None, 0.55),
    _c("building", "Building", "مبنى", None, 0.40),
    _c("tower", "Tower", "برج", None, 0.50),
    _c("place", "Place", "مكان", None, 0.30),
    # ── kinds that are not POIs (areas and streets) ──
    _c("governorate", "Governorate", "محافظة", None, 1.00),
    _c("city", "City", "مدينة", None, 0.95),
    _c("town", "Town", "مدينة", None, 0.85),
    _c("district", "District", "حي", None, 0.80),
    _c("markaz", "District", "مركز", None, 0.80),
    _c("neighbourhood", "Neighbourhood", "منطقة", None, 0.70),
    _c("village", "Village", "قرية", None, 0.65),
    _c("hamlet", "Hamlet", "عزبة", None, 0.45),
    _c("street", "Street", "شارع", None, 0.50),
    _c("road", "Road", "طريق", None, 0.60),
    _c("highway", "Highway", "طريق سريع", None, 0.75),
    _c("axis", "Axis", "محور", None, 0.72),
]

BY_ID: dict[str, Cat] = {c.id: c for c in CATS}
AREA_CATS = frozenset({"governorate", "city", "town", "district", "markaz", "neighbourhood", "village", "hamlet"})
STREET_CATS = frozenset({"street", "road", "highway", "axis", "bridge", "tunnel", "square"})

# ── Overture taxonomy → display category ────────────────────────────────────
# Keys are Overture taxonomy ids at ANY level; a place takes the deepest level of its hierarchy
# that appears here. Anything whose whole hierarchy is unmapped falls to OVERTURE_ROOTS.
OVERTURE: dict[str, str] = {
    # health
    "hospital": "hospital", "emergency_room": "emergency_room", "childrens_hospital": "hospital",
    "pharmacy": "pharmacy", "pharmacy_and_drug_store": "pharmacy", "drugstore": "pharmacy",
    "dental_clinic": "dental_clinic", "cosmetic_dentistry": "dental_clinic", "general_dentistry": "dental_clinic",
    "orthodontics": "dental_clinic", "pediatric_dentist": "dental_clinic", "dentist": "dental_clinic",
    "doctors_office": "doctor", "doctor": "doctor", "laboratory_testing": "medical_lab",
    "medical_laboratory": "medical_lab", "diagnostics_imaging_or_lab_service": "medical_lab",
    "radiology": "radiology", "diagnostic_imaging": "radiology", "medical_imaging": "radiology",
    "physical_therapy": "physiotherapy", "physical_medicine_and_rehabilitation": "physiotherapy",
    "vision_or_eye_care_clinic": "eye_clinic", "ophthalmology": "eye_clinic", "optometrist": "eye_clinic",
    "outpatient_care_facility": "clinic", "medical_center": "medical_center", "health_care": "clinic",
    "specialized_health_care": "clinic", "surgery": "clinic", "surgery_center": "medical_center",
    "pediatric_clinic": "clinic", "obstetrics_and_gynecology": "clinic",
    "reproductive_perinatal_and_womens_care": "clinic", "dermatology": "clinic", "cardiology": "clinic",
    "orthopedics": "clinic", "ear_nose_and_throat": "clinic", "plastic_and_reconstructive_surgery": "clinic",
    "behavioral_or_mental_health_clinic": "clinic", "counseling": "clinic", "urgent_care_clinic": "clinic",
    "medical_service": "clinic", "medical_service_organization": "clinic", "nutrition_service": "clinic",
    "veterinarian": "veterinary", "animal_hospital": "veterinary", "medical_supply_store": "medical_supply",
    "b2b_surgical_appliances_and_supplies": "medical_supply",
    # money
    "bank": "bank", "bank_or_credit_union": "bank", "credit_union": "bank", "atm": "atm",
    "currency_exchange": "exchange", "insurance_agency": "insurance", "insurance": "insurance",
    "financial_service": "financial_service", "accountant": "accountant", "post_office": "post_office",
    "money_transfer_service": "money_transfer", "check_cashing_payday_loans": "money_transfer",
    # car
    "gas_station": "gas_station", "fuel_station": "gas_station", "ev_charging_station": "ev_charging",
    "automotive_repair": "car_repair", "automotive_service": "car_repair", "vehicle_service": "car_repair",
    "auto_body_shop": "car_repair", "auto_detailing": "car_wash", "car_wash": "car_wash",
    "tire_dealer_and_repair": "tyre_shop", "tire_shop": "tyre_shop", "oil_change_station": "oil_change",
    "auto_parts_store": "auto_parts", "vehicle_parts_store": "auto_parts", "auto_dealer": "car_dealer",
    "car_dealer": "car_dealer", "vehicle_dealer": "car_dealer", "used_car_dealer": "car_dealer",
    "car_rental_service": "car_rental", "rental_service": "car_rental", "motorcycle_dealer": "motorcycle_shop",
    "motorcycle_repair": "motorcycle_shop", "towing_service": "towing", "parking": "parking",
    "parking_lot": "parking", "parking_garage": "parking", "driving_school": "driving_school",
    "auto_company": "car_dealer",
    # food
    "restaurant": "restaurant", "fast_food_restaurant": "fast_food", "cafe": "cafe", "coffee_shop": "coffee_shop",
    "non_alcoholic_beverage_venue": "cafe", "bakery": "bakery", "dessert_shop": "sweets", "candy_store": "sweets",
    "chocolatier": "sweets", "patisserie": "sweets", "ice_cream_shop": "ice_cream",
    "smoothie_juice_bar": "juice_bar", "juice_bar": "juice_bar", "seafood_restaurant": "seafood",
    "pizza_restaurant": "pizza", "burger_restaurant": "burger", "chicken_restaurant": "chicken",
    "chicken_wings_restaurant": "chicken", "barbecue_restaurant": "grill", "steakhouse": "grill",
    "kebab_restaurant": "grill", "shawarma_restaurant": "shawarma", "egyptian_restaurant": "restaurant",
    "falafel_restaurant": "foul_taameya", "sandwich_shop": "fast_food", "casual_eatery": "restaurant",
    "food_and_drink": "restaurant", "bar": "bar", "pub": "bar", "lounge": "lounge", "hookah_bar": "ahwa",
    "food_court": "food_court", "diner": "restaurant", "breakfast_and_brunch_restaurant": "restaurant",
    "food_delivery_service": "restaurant", "food_service": "restaurant", "catering_service": "event_service",
    # shopping
    "supermarket": "supermarket", "grocery_store": "grocery", "convenience_store": "convenience",
    "hypermarket": "hypermarket", "warehouse_club_store": "hypermarket", "discount_store": "supermarket",
    "shopping_mall": "mall", "shopping_center": "mall", "department_store": "department_store",
    "outlet_store": "department_store", "market": "market", "farmers_market": "market", "flea_market": "market",
    "butcher_shop": "butcher", "meat_shop": "butcher", "poultry_store": "poultry", "fishmonger": "fishmonger",
    "seafood_market": "fishmonger", "produce_store": "greengrocer", "fruits_and_vegetables_store": "greengrocer",
    "dairy_store": "dairy", "health_food_store": "grocery", "food_and_beverage_store": "grocery",
    "spice_store": "spices", "coffee_and_tea_store": "spices", "nut_store": "spices", "tobacco_shop": "tobacco",
    "mobile_phone_store": "mobile_shop", "telecommunications_company": "telecom",
    "electronics_store": "electronics", "computer_store": "computer_store", "camera_and_photography_store": "electronics",
    "video_game_store": "electronics", "appliance_store": "appliances", "clothing_store": "clothes",
    "fashion_and_apparel_store": "clothes", "womens_clothing_store": "womens_clothes",
    "mens_clothing_store": "mens_clothes", "childrens_clothing_store": "kids_clothes",
    "bridal_shop": "bridal", "lingerie_store": "womens_clothes", "shoe_store": "shoes",
    "luggage_store": "bags", "handbag_store": "bags", "sportswear_store": "sportswear",
    "jewelry_store": "jewelry", "watch_store": "watches", "eyewear_store": "optician", "optician": "optician",
    "fashion_accessories_store": "clothes", "perfume_store": "perfume", "cosmetics_store": "cosmetics",
    "beauty_supply_store": "cosmetics", "personal_care_and_beauty_store": "cosmetics",
    "skin_care_and_makeup": "cosmetics", "hair_supply_store": "cosmetics",
    "furniture_store": "furniture", "mattress_store": "furniture", "home_goods_store": "home_goods",
    "kitchen_supply_store": "home_goods", "linen_store": "home_goods", "home_decor_store": "home_goods",
    "hardware_store": "hardware", "hardware_home_and_garden_store": "home_goods", "home_improvement_store": "hardware",
    "paint_store": "paint", "building_supply_store": "building_materials", "lighting_store": "lighting",
    "carpet_store": "carpet", "flooring_store": "building_materials", "plumbing_supply_store": "sanitary",
    "fabric_store": "fabric", "arts_crafts_and_hobby_store": "gifts", "bookstore": "bookshop",
    "books_music_and_video_store": "bookshop", "office_supply_store": "stationery", "stationery_store": "stationery",
    "toy_store": "toys", "toys_and_games_store": "toys", "gift_shop": "gifts", "souvenir_store": "gifts",
    "flowers_and_gifts_store": "florist", "florist": "florist", "pet_store": "pets", "animal_and_pet_store": "pets",
    "animal_or_pet_service": "pets", "sporting_goods_store": "sports_store", "music_store": "music_store",
    "musical_instrument_store": "music_store", "second_hand_store": "second_hand", "antique_store": "second_hand",
    "specialty_store": "shop", "shopping": "shop", "retail": "shop",
    # services
    "laundry_service": "laundry", "laundromat": "laundry", "dry_cleaning": "dry_cleaning", "barber": "barber",
    "hair_salon": "hair_salon", "beauty_salon": "beauty_salon", "personal_or_beauty_service": "beauty_salon",
    "makeup_artist": "beauty_salon", "nail_salon": "beauty_salon", "spa": "spa", "wellness_service": "spa",
    "tattoo_and_piercing": "beauty_salon", "tailor": "tailor", "sewing_and_alterations": "tailor",
    "printing_service": "print_shop", "print_shop": "print_shop", "internet_cafe": "internet_cafe",
    "mobile_phone_repair": "phone_repair", "it_service_and_computer_repair": "phone_repair",
    "appliance_repair_service": "appliance_repair", "electronics_repair_shop": "appliance_repair",
    "plumber": "plumber", "plumbing_service": "plumber", "electrician": "electrician",
    "carpenter": "carpenter", "carpentry": "carpenter", "locksmith": "locksmith",
    "real_estate_service": "real_estate", "real_estate_agent": "real_estate", "property_management": "real_estate",
    "commercial_real_estate": "real_estate", "home_developer": "developer", "real_estate_investment": "developer",
    "travel_service": "travel_agency", "travel_agency": "travel_agency", "tour_operator": "travel_agency",
    "attorney_or_law_firm": "lawyer", "legal_service": "lawyer", "notary_public": "notary",
    "professional_service": "office", "corporate_or_business_office": "company", "b2b_service": "company",
    "b2b_office_and_professional_service": "company", "industrial_company": "company",
    "information_technology_company": "tech_company", "software_development": "tech_company",
    "technical_service": "tech_company", "computer_hardware_company": "tech_company", "travel_company": "travel_agency",
    "pharmaceutical_company": "company", "clothing_company": "company", "coworking_space": "coworking",
    "manufacturer": "factory", "industrial_equipment_manufacturer": "factory", "metal_fabricator": "factory",
    "textile_manufacturer": "factory", "chemical_plant": "factory", "jewelry_and_watches_manufacturer": "factory",
    "warehouse": "warehouse", "b2b_transportation_and_storage_service": "shipping",
    "freight_and_cargo_service": "shipping", "shipping_or_delivery_service": "shipping", "shipping_center": "shipping",
    "courier_service": "shipping", "event_or_party_service": "event_service", "party_and_event_planning": "event_service",
    "wedding_planning": "event_service", "event_photography_service": "photographer", "photographer": "photographer",
    "media_service": "advertising", "advertising_agency": "advertising", "marketing_agency": "advertising",
    "internet_marketing_service": "advertising", "b2b_advertising_and_marketing_service": "advertising",
    "graphic_designer": "advertising", "web_designer": "tech_company", "design_service": "office",
    "architectural_designer": "office", "interior_design": "office", "engineering_service": "office",
    "building_or_construction_service": "construction", "contractor": "construction", "home_service": "service",
    "hvac_service": "service", "home_cleaning": "cleaning", "pest_control_service": "cleaning", "mover": "moving",
    "civic_organization": "ngo", "charity_organization": "ngo", "non_governmental_association": "ngo",
    "social_or_community_service": "ngo", "religious_organization": "ngo", "sport_league": "sports_club",
    "farm": "farm", "agricultural_service": "farm", "employment_agency": "office", "appraisal_service": "office",
    "elevator_service": "service", "glass_and_mirror_sales_service": "service", "windows_installation": "service",
    "home_security": "service", "broadcasting_media_production": "company", "music_production": "company",
    "supplier_or_distributor": "company", "electronic_equipment_supplier": "company",
    "restaurant_equipment_and_supply": "company", "b2b_water_treatment_service": "company",
    "family_service": "kindergarten", "day_care_preschool": "kindergarten",
    "taxi_or_ride_share_service": "taxi", "limo_service": "taxi", "taxi_service": "taxi",
    # government
    "police_station": "police", "fire_station": "fire_station", "courthouse": "courthouse",
    "government_office": "government", "community_and_government": "government", "town_hall": "townhall",
    "embassy": "embassy", "military_site": "military", "community_center": "community_center",
    "youth_center": "community_center", "public_service_and_government": "government",
    # religion
    "muslim_place_of_worship": "mosque", "mosque": "mosque", "christian_place_of_worship": "church",
    "church": "church", "monastery": "monastery", "religious_place": "place_of_worship",
    "place_of_worship": "place_of_worship",
    # education
    "school": "school", "elementary_school": "school", "middle_school": "school", "high_school": "school",
    "private_school": "school", "public_school": "school", "preschool": "kindergarten",
    "college_university": "university", "university": "university", "college": "college",
    "specialty_school": "institute", "language_school": "language_school", "vocational_school": "institute",
    "educational_service": "training_center", "tutoring_service": "tutoring", "education": "school",
    "place_of_learning": "school", "library": "library", "campus_building": "college",
    # transport
    "airport": "airport", "airport_terminal": "airport", "train_station": "train_station",
    "metro_station": "metro_station", "subway_station": "metro_station", "light_rail_station": "lrt_station",
    "bus_station": "bus_station", "bus_stop": "bus_stop", "transportation": "bus_station",
    "ferry_service": "ferry", "ferry_terminal": "ferry", "port": "port", "seaport": "port", "marina": "port",
    "rest_stop": "rest_area", "toll_station": "toll_gate", "travel_and_transportation": "travel_agency",
    # leisure
    "hotel": "hotel", "lodging": "hotel", "motel": "hotel", "resort": "resort", "hostel": "hostel",
    "serviced_apartment": "apartment_hotel", "vacation_rental": "apartment_hotel", "campground": "camp_site",
    "park": "park", "garden": "garden", "botanical_garden": "garden", "playground": "playground",
    "amusement_park": "amusement_park", "water_park": "amusement_park", "zoo": "zoo", "aquarium": "attraction",
    "beach": "beach", "museum": "museum", "historic_site": "historic_site", "monument": "monument",
    "landmark_and_historical_building": "historic_site", "cultural_and_historic": "historic_site",
    "tourist_attraction": "attraction", "attractions_and_activities": "attraction", "lookout": "viewpoint",
    "movie_theater": "cinema", "cinema": "cinema", "theatre": "theater", "theater": "theater",
    "performing_arts_venue": "theater", "auditorium": "theater", "music_venue": "theater",
    "art_gallery": "art_gallery", "arts_and_entertainment": "cultural_center", "cultural_center": "cultural_center",
    "event_venue": "event_venue", "wedding_venue": "event_venue", "banquet_hall": "event_venue",
    "stadium_arena": "stadium", "stadium": "stadium", "sports_club_and_league": "sports_club",
    "country_club": "sports_club", "gym": "gym", "fitness_center": "gym", "sport_or_fitness_facility": "gym",
    "fitness_trainer": "gym", "martial_arts_club": "gym", "swimming_pool": "swimming_pool",
    "sports_and_recreation": "sports_club", "soccer_field": "sports_field", "sports_field": "sports_field",
    "tennis_court": "sports_field", "scuba_diving_center": "diving_center", "dance_club": "nightclub",
    "night_club": "nightclub",
    # geography
    "mountain": "mountain", "island": "island", "lake": "lake", "river": "water", "sea": "water", "bay": "water",
    "desert": "natural", "nature_reserve": "natural", "national_park": "natural", "natural_feature": "natural",
    "geographic_entities": "natural", "cemetery": "cemetery", "bridge": "bridge", "industrial_estate": "industrial_zone",
    "residential_complex": "compound", "apartment_building": "building", "commercial_industrial": "industrial_zone",
}

OVERTURE_ROOTS = {
    "shopping": "shop", "services_and_business": "service", "food_and_drink": "restaurant",
    "health_care": "clinic", "education": "school", "travel_and_transportation": "travel_agency",
    "lifestyle_services": "service", "community_and_government": "government",
    "cultural_and_historic": "historic_site", "sports_and_recreation": "sports_club",
    "geographic_entities": "natural", "lodging": "hotel", "arts_and_entertainment": "cultural_center",
}


def overture_cat(primary: str | None, hierarchy: list[str] | None) -> str:
    path = list(hierarchy or [])
    if primary and (not path or path[-1] != primary):
        path.append(primary)
    for node in reversed(path):
        if node in OVERTURE:
            return OVERTURE[node]
    if path and path[0] in OVERTURE_ROOTS:
        return OVERTURE_ROOTS[path[0]]
    return "place"


# ── OSM tags → display category ─────────────────────────────────────────────
# Ordered (key, value-or-*, cat). The first match wins, so the specific rules sit above the
# generic ones (healthcare=laboratory before amenity=clinic, shop=* last).
OSM_RULES: list[tuple[str, str, str]] = [
    ("aeroway", "aerodrome", "airport"), ("aeroway", "terminal", "airport"),
    # station=* first: a metro station is railway=station + station=subway
    ("station", "subway", "metro_station"), ("station", "light_rail", "lrt_station"),
    ("station", "monorail", "monorail_station"), ("railway", "subway_entrance", "metro_station"),
    ("railway", "station", "train_station"), ("railway", "halt", "train_station"),
    ("amenity", "fuel", "gas_station"), ("amenity", "charging_station", "ev_charging"),
    ("amenity", "hospital", "hospital"), ("healthcare", "hospital", "hospital"),
    ("emergency", "emergency_ward_entrance", "emergency_room"),
    ("amenity", "pharmacy", "pharmacy"), ("healthcare", "pharmacy", "pharmacy"), ("shop", "chemist", "pharmacy"),
    ("healthcare", "laboratory", "medical_lab"), ("healthcare", "blood_donation", "medical_lab"),
    ("healthcare:speciality", "radiology", "radiology"), ("healthcare", "physiotherapist", "physiotherapy"),
    ("healthcare", "dentist", "dental_clinic"), ("amenity", "dentist", "dental_clinic"),
    ("healthcare", "optometrist", "eye_clinic"), ("amenity", "veterinary", "veterinary"),
    ("amenity", "doctors", "doctor"), ("healthcare", "doctor", "doctor"),
    ("amenity", "clinic", "clinic"), ("healthcare", "clinic", "clinic"), ("healthcare", "centre", "medical_center"),
    ("healthcare", "*", "clinic"), ("shop", "medical_supply", "medical_supply"),
    ("amenity", "bank", "bank"), ("amenity", "atm", "atm"), ("amenity", "bureau_de_change", "exchange"),
    ("amenity", "money_transfer", "money_transfer"), ("amenity", "payment_centre", "money_transfer"),
    ("amenity", "post_office", "post_office"), ("office", "insurance", "insurance"),
    ("amenity", "car_wash", "car_wash"), ("shop", "car_repair", "car_repair"), ("craft", "car_repair", "car_repair"),
    ("shop", "tyres", "tyre_shop"), ("shop", "car_parts", "auto_parts"), ("shop", "car", "car_dealer"),
    ("amenity", "car_rental", "car_rental"), ("shop", "motorcycle", "motorcycle_shop"),
    ("amenity", "parking", "parking"), ("amenity", "driving_school", "driving_school"),
    ("cuisine", "koshary", "koshary"), ("cuisine", "koshari", "koshary"), ("cuisine", "pizza", "pizza"),
    ("cuisine", "burger", "burger"), ("cuisine", "seafood", "seafood"), ("cuisine", "fish", "seafood"),
    ("cuisine", "grill", "grill"), ("cuisine", "kebab", "grill"), ("cuisine", "shawarma", "shawarma"),
    ("cuisine", "chicken", "chicken"), ("cuisine", "falafel", "foul_taameya"), ("cuisine", "foul", "foul_taameya"),
    ("amenity", "fast_food", "fast_food"), ("amenity", "restaurant", "restaurant"), ("amenity", "food_court", "food_court"),
    ("amenity", "ice_cream", "ice_cream"), ("shop", "ice_cream", "ice_cream"),
    ("amenity", "cafe", "cafe"), ("amenity", "bar", "bar"), ("amenity", "pub", "bar"), ("amenity", "nightclub", "nightclub"),
    ("amenity", "hookah_lounge", "ahwa"), ("shop", "bakery", "bakery"), ("shop", "pastry", "sweets"),
    ("shop", "confectionery", "sweets"), ("shop", "chocolate", "sweets"), ("shop", "beverages", "juice_bar"),
    ("shop", "juice", "juice_bar"),
    ("shop", "mall", "mall"), ("shop", "department_store", "department_store"), ("shop", "supermarket", "supermarket"),
    ("shop", "wholesale", "hypermarket"), ("shop", "convenience", "convenience"), ("shop", "kiosk", "kiosk"),
    ("shop", "grocery", "grocery"), ("shop", "general", "grocery"), ("amenity", "marketplace", "market"),
    ("shop", "butcher", "butcher"), ("shop", "poultry", "poultry"), ("shop", "seafood", "fishmonger"),
    ("shop", "greengrocer", "greengrocer"), ("shop", "dairy", "dairy"), ("shop", "spices", "spices"),
    ("shop", "coffee", "spices"), ("shop", "nuts", "spices"), ("shop", "tobacco", "tobacco"),
    ("shop", "mobile_phone", "mobile_shop"), ("shop", "telecommunication", "telecom"),
    ("shop", "electronics", "electronics"), ("shop", "computer", "computer_store"), ("shop", "appliance", "appliances"),
    ("shop", "clothes", "clothes"), ("shop", "fashion", "clothes"), ("shop", "boutique", "clothes"),
    ("shop", "wedding", "bridal"), ("shop", "shoes", "shoes"), ("shop", "bag", "bags"),
    ("shop", "jewelry", "jewelry"), ("shop", "gold", "jewelry"), ("shop", "watches", "watches"),
    ("shop", "optician", "optician"), ("shop", "perfumery", "perfume"), ("shop", "cosmetics", "cosmetics"),
    ("shop", "beauty", "beauty_salon"), ("shop", "furniture", "furniture"), ("shop", "houseware", "home_goods"),
    ("shop", "interior_decoration", "home_goods"), ("shop", "hardware", "hardware"), ("shop", "doityourself", "hardware"),
    ("shop", "paint", "paint"), ("shop", "trade", "building_materials"), ("shop", "bathroom_furnishing", "sanitary"),
    ("shop", "lighting", "lighting"), ("shop", "carpet", "carpet"), ("shop", "fabric", "fabric"),
    ("shop", "books", "bookshop"), ("shop", "stationery", "stationery"), ("shop", "copyshop", "print_shop"),
    ("shop", "toys", "toys"), ("shop", "gift", "gifts"), ("shop", "florist", "florist"), ("shop", "pet", "pets"),
    ("shop", "sports", "sports_store"), ("shop", "musical_instrument", "music_store"),
    ("shop", "second_hand", "second_hand"), ("shop", "laundry", "laundry"), ("shop", "dry_cleaning", "dry_cleaning"),
    ("shop", "hairdresser", "hair_salon"), ("shop", "tailor", "tailor"), ("craft", "tailor", "tailor"),
    ("amenity", "internet_cafe", "internet_cafe"), ("craft", "plumber", "plumber"),
    ("craft", "electrician", "electrician"), ("craft", "carpenter", "carpenter"), ("shop", "locksmith", "locksmith"),
    ("office", "estate_agent", "real_estate"), ("office", "travel_agent", "travel_agency"),
    ("shop", "travel_agency", "travel_agency"), ("office", "lawyer", "lawyer"), ("office", "accountant", "accountant"),
    ("office", "notary", "notary"), ("office", "telecommunication", "telecom"), ("office", "company", "company"),
    ("office", "it", "tech_company"), ("office", "ngo", "ngo"), ("office", "association", "ngo"),
    ("office", "government", "government"), ("office", "coworking", "coworking"), ("office", "*", "office"),
    ("man_made", "works", "factory"), ("industrial", "*", "factory"),
    ("amenity", "police", "police"), ("amenity", "fire_station", "fire_station"),
    ("amenity", "courthouse", "courthouse"), ("amenity", "townhall", "townhall"),
    ("diplomatic", "embassy", "embassy"), ("amenity", "embassy", "embassy"), ("office", "diplomatic", "embassy"),
    ("amenity", "community_centre", "community_center"), ("military", "*", "military"),
    ("amenity", "place_of_worship", "place_of_worship"),
    ("amenity", "kindergarten", "kindergarten"), ("amenity", "childcare", "kindergarten"),
    ("amenity", "school", "school"), ("amenity", "university", "university"), ("amenity", "college", "college"),
    ("amenity", "language_school", "language_school"), ("amenity", "training", "training_center"),
    ("amenity", "prep_school", "tutoring"), ("amenity", "library", "library"),
    ("amenity", "bus_station", "bus_station"), ("highway", "bus_stop", "bus_stop"),
    ("amenity", "ferry_terminal", "ferry"), ("landuse", "port", "port"), ("leisure", "marina", "port"),
    ("amenity", "taxi", "taxi"), ("highway", "rest_area", "rest_area"), ("highway", "services", "rest_area"),
    ("barrier", "toll_booth", "toll_gate"),
    ("tourism", "hotel", "hotel"), ("tourism", "motel", "hotel"), ("tourism", "guest_house", "hotel"),
    ("tourism", "hostel", "hostel"), ("tourism", "apartment", "apartment_hotel"), ("tourism", "chalet", "resort"),
    ("tourism", "camp_site", "camp_site"), ("tourism", "museum", "museum"), ("tourism", "zoo", "zoo"),
    ("tourism", "theme_park", "amusement_park"), ("leisure", "water_park", "amusement_park"),
    ("tourism", "viewpoint", "viewpoint"), ("tourism", "gallery", "art_gallery"), ("tourism", "attraction", "attraction"),
    ("historic", "monument", "monument"), ("historic", "memorial", "monument"), ("historic", "*", "historic_site"),
    ("amenity", "cinema", "cinema"), ("amenity", "theatre", "theater"), ("amenity", "arts_centre", "cultural_center"),
    ("amenity", "events_venue", "event_venue"), ("amenity", "conference_centre", "event_venue"),
    ("leisure", "stadium", "stadium"), ("leisure", "sports_centre", "sports_club"),
    ("leisure", "fitness_centre", "gym"), ("leisure", "swimming_pool", "swimming_pool"),
    ("leisure", "pitch", "sports_field"), ("leisure", "park", "park"), ("leisure", "garden", "garden"),
    ("leisure", "playground", "playground"), ("leisure", "amusement_arcade", "playground"),
    ("leisure", "beach_resort", "beach"), ("natural", "beach", "beach"),
    ("tourism", "*", "attraction"), ("place", "square", "square"), ("landuse", "cemetery", "cemetery"),
    ("amenity", "grave_yard", "cemetery"), ("natural", "peak", "mountain"), ("natural", "mountain_range", "mountain"),
    ("place", "island", "island"), ("natural", "water", "lake"), ("landuse", "industrial", "industrial_zone"),
    ("shop", "*", "shop"), ("amenity", "*", "place"), ("craft", "*", "service"),
]


def osm_cat(tags: dict[str, str]) -> str | None:
    for k, v, cat in OSM_RULES:
        tv = tags.get(k)
        if tv is None:
            continue
        if v == "*" or tv == v or v in tv.split(";"):
            if k == "amenity" and tv == "place_of_worship":
                rel = tags.get("religion", "")
                if rel == "muslim":
                    return "mosque"
                if rel == "christian":
                    return "monastery" if tags.get("building") == "monastery" else "church"
            return cat
    return None


# ── a transport place's NAME over a junk category ────────────────────────────
# Meta files Cairo's metro stations as travel agencies, OSM exports without the station tag file
# them as railway stations, and the two copies of one station then never merge. The name is the
# better evidence for these few kinds — but only over a category that says nothing about the place
# (a «مترو ماركت» supermarket keeps its category).
WEAK_FOR_TRANSPORT = frozenset({"travel_agency", "shipping", "train_station", "bus_station", "bus_stop", "place",
                                "landmark", "attraction", "transport", "cultural_center", "government", "office",
                                "company", "taxi", "car_rental"})
# (category, required word sets — every word of one set must be in the name's normalized words)
NAME_TRANSPORT = [
    ("metro_station", [{"محطه", "مترو"}, {"metro", "station"}, {"subway", "station"}, {"مترو", "انفاق"}]),
    ("train_station", [{"محطه", "قطار"}, {"محطه", "قطارات"}, {"محطه", "سكه", "حديد"}, {"محطه", "مصر"},
                       {"railway", "station"},
                       {"train", "station"}]),
    ("airport", [{"مطار"}, {"airport"}]),
    ("microbus_stand", [{"موقف", "ميكروباص"}, {"موقف", "مكروباص"}, {"microbus"}]),
]


# The civic offices people search by what they do there («مرور», «سجل مدني», «شهر عقاري»): Overture
# files them all as "government office" and most OSM ones carry only office=government.
WEAK_FOR_CIVIC = frozenset({"government", "office", "place", "landmark", "company", "attraction", "ngo", "notary"})
NAME_CIVIC = [
    ("traffic_department", [{"مرور"}, {"traffic", "department"}, {"traffic", "unit"}]),
    ("civil_registry", [{"سجل", "مدني"}, {"احوال", "مدنيه"}, {"civil", "registry"}]),
    ("real_estate_registry", [{"شهر", "عقاري"}, {"real", "estate", "registry"}]),
    ("notary", [{"توثيق"}, {"notary"}]),
    ("post_office", [{"بريد"}, {"بوسطه"}, {"post", "office"}]),
    ("police", [{"قسم", "شرطه"}, {"مركز", "شرطه"}, {"police", "station"}, {"نقطه", "شرطه"}]),
    ("courthouse", [{"محكمه"}, {"نيابه"}, {"court"}]),
]


# What a shop sells, said by its name over a category that says nothing («كشري التحرير» filed as a
# restaurant, «سوبر ماركت الأمل» as a grocery). A restaurant may become a koshary place, never a bakery:
# «فرن الحطب» is a pizza oven.
WEAK_FOR_GOODS = frozenset({"place", "shop", "store", "company", "grocery", "food", "convenience_store"})
NAME_GOODS = [
    ("koshary", [{"كشري"}, {"koshary"}, {"koshari"}, {"kushari"}], WEAK_FOR_GOODS | {"restaurant", "fast_food"}),
    ("car_wash", [{"غسيل", "سيارات"}, {"غسيل", "عربيات"}, {"مغسله", "سيارات"}, {"car", "wash"}],
     WEAK_FOR_GOODS | {"car_repair"}),
    ("bakery", [{"فرن"}, {"مخبز"}, {"bakery"}], WEAK_FOR_GOODS),
    ("foul_taameya", [{"فول"}, {"طعميه"}, {"فلافل"}, {"falafel"}, {"taameya"}],
     WEAK_FOR_GOODS | {"restaurant", "fast_food", "kiosk"}),
    ("supermarket", [{"سوبر", "ماركت"}, {"سوبرماركت"}, {"supermarket"}, {"ماركت"}, {"market"}], WEAK_FOR_GOODS),
]


# Overture files resort hotels near an airport AS airports ("Tivoli Tropicana, Sharm El Sheik"): an
# airport is named like one.
AIRPORT_WORDS = {"مطار", "airport", "aerodrome", "airfield", "airstrip", "terminal", "international"}


def refine_by_name(cat: str, names: list[str]) -> str:
    if cat == "airport":
        from . import textnorm as tn
        words = {tn.stems(t)[-1] for nm in names for t in tn.tokens(nm)}
        if not words & AIRPORT_WORDS:
            return "place"
    transport, civic = cat in WEAK_FOR_TRANSPORT, cat in WEAK_FOR_CIVIC
    goods = [(new, sets) for new, sets, weak in NAME_GOODS if cat in weak]
    if not (transport or civic or goods):
        return cat
    from . import textnorm as tn
    words = set()
    for nm in names:
        words.update(tn.stems(t)[-1] for t in tn.tokens(nm))
    for new, sets in (NAME_TRANSPORT if transport else []) + (NAME_CIVIC if civic else []) + goods:
        if any(ws <= words for ws in sets):
            # a railway station keeps its class unless the name says metro
            if cat == "train_station" and new == "train_station":
                return cat
            return new
    return cat


def validate(lexicon_category_ids: set[str]) -> list[str]:
    """Search categories the taxonomy points at that the lexicon does not define."""
    missing = sorted({c.scat for c in CATS if c.scat and c.scat not in lexicon_category_ids})
    return missing
