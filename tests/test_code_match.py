# -*- coding: utf-8 -*-
"""
اختبارات ثابتة لقاعدة «المطابقة بالكود» (قواعد صاحبة النظام، 2026-09-12):
  1) وصف يحمل نفس كود R للمنتج الذي فوقه ليس بنداً مستقلاً أبداً — يُدمج فيه.
  2) سطر بلا كود واسمه مختلف (أو بلغة أخرى) لا يُحسم بتشابه الحروف:
     «N Items» المطبوع هو الحكم — يؤكد الدمج أو يؤكد الاستقلال، وتسقط الملاحظة عند الحسم.
  3) بند بلا كود على شاشة التطبيق يتبنّى كود ملصق العبوة إذا كان المرشح واحداً لا غير.
  4) لا يُضعَّف أي فحص آخر: الوزن والسعر والعدد والتعارض تبقى كما هي.
الحالتان الأوليان مأخوذتان حرفياً من «سجل استخراج الفيديو» (tests/fixtures).
تشغيل: python3 tests/test_code_match.py
"""
import io, json, os, sys

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.main import normalize_result  # noqa: E402

FAILED = []
FX = os.path.join(os.path.dirname(__file__), "fixtures")


def check(name, cond, detail=""):
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else "  <<< " + str(detail)))
    if not cond:
        FAILED.append(name)


def fixture(fn):
    return normalize_result(json.load(io.open(os.path.join(FX, fn), encoding="utf-8")))


def failed_ids(res):
    return set(res["self_check"]["failed"])


def codes(res):
    return [p.get("code") for p in res["items"]]


def L(qty, name, code, price, weight=None, raw=None):
    return {"qty": qty, "name": name, "code": code, "weight": weight,
            "price": price, "raw_text": raw or name}


def run(lines, items_count=None, subtotal=None, total=None, delivery=None,
        delivery_printed=False, platform="keeta", prepared=None, fulfillment=None):
    return normalize_result({
        "order_code": None, "platform": platform, "branch": "Al Yasmin",
        "order_date": "2026-09-11", "evidence_medium": "printed_receipt",
        "items_count": items_count, "subtotal": subtotal, "delivery": delivery,
        "delivery_printed": delivery_printed, "total": total, "adjustments": [],
        "lines": lines, "prepared_items": prepared or [], "fulfillment": fulfillment or {},
        "field_confidence": {"order_total": "high"}, "confidence": "high",
    })


print("\n=== 1) qwd-5-1323 — القراءة المحفوظة للفيديو VID_20260911_003453 ===")
r = fixture("qwd-5-1323_1WKMQJhM.json")
check("منتجان لا ثلاثة", r["products_count"] == 2, r["products_count"])
check("العدد المطبوع مطابق", r["items_count"] == 2 and "items_count_match" not in failed_ids(r))
check("الكودان R856 و R76 (تبنّي كود الملصق)", codes(r) == ["R856", "R76"], codes(r))
check("مصدر الكود مسجَّل", r["items"][1].get("code_source") == "label", r["items"][1])
check("label_codes يذكر R76", [x["code"] for x in r["label_codes"]] == ["R76"], r["label_codes"])
check("لا ملاحظة دمج معلّقة", r["merge_notes"] == [], r["merge_notes"])
check("all_codes لم يعد ساقطاً", "all_codes" not in failed_ids(r), failed_ids(r))
check("lines_merged_cleanly لم يعد ساقطاً", "lines_merged_cleanly" not in failed_ids(r), failed_ids(r))
check("مجموع المنتجات 44.98 = فاتورة سماك", r["products_sum"] == 44.98, r["products_sum"])
check("الأسعار كما طُبعت", [p["line_total"] for p in r["items"]] == [15, 29.98],
      [p["line_total"] for p in r["items"]])
check("الأوزان 250جم لكل بند", [p["total_weight_g"] for p in r["items"]] == [250, 250],
      [p["total_weight_g"] for p in r["items"]])
check("لا إضعاف: فحوص الإجمالي تبقى ساقطة (لا إجمالي مطبوع وثقته low)",
      {"total_read", "sum_matches_total", "total_confidence"} <= failed_ids(r), failed_ids(r))

print("\n=== 2) qwd-5-1329 — سطر ملصق ﷼0.00 تشابهه 0.84 ===")
r = fixture("qwd-5-1329_1aPkJHiZ.json")
check("ثلاثة منتجات = العدد المطبوع", r["products_count"] == 3 == r["items_count"], r["products_count"])
check("الأكواد R626/R325/R625", codes(r) == ["R626", "R325", "R625"], codes(r))
check("لا بند بلا كود", all(codes(r)), codes(r))
check("لا ملاحظة دمج معلّقة", r["merge_notes"] == [], r["merge_notes"])
check("all_codes / items_count_match / lines_merged_cleanly كلها سليمة",
      not ({"all_codes", "items_count_match", "lines_merged_cleanly"} & failed_ids(r)), failed_ids(r))
check("المجموع 94 كما هو", r["products_sum"] == 94, r["products_sum"])
check("اللوز 500جم بسعر 40 (دمج سطر الوزن كما كان)",
      r["items"][1]["total_weight_g"] == 500 and r["items"][1]["line_total"] == 40, r["items"][1])
check("لا إضعاف: all_weights يبقى ساقطاً (شاي بلا وزن — استثناء الحبة يقع في n8n من وحدة سماك)",
      "all_weights" in failed_ids(r), failed_ids(r))

print("\n=== 3) قاعدة نفس الكود: وصف بلغة أخرى بنفس الكود يُدمج ===")
r = run([L(1, "مكسرات يابانية مشكلة R76", "R76", 29.98),
         L(1, "Japanese Mixed Nuts 250g", "R76", None, "250 g")],
        items_count=None, subtotal=29.98)
check("منتج واحد لا اثنان", r["products_count"] == 1, r["products_count"])
check("الكود R76 والوزن 250جم", codes(r) == ["R76"] and r["items"][0]["total_weight_g"] == 250, r["items"])
check("لا ملاحظة", r["merge_notes"] == [], r["merge_notes"])

print("\n=== 4) الحمايات كما هي ===")
r = run([L(1, "Colored Nuts 250g", "R856", 15, "250 g"),
         L(1, "Japanese Mixed Nuts 250g", None, 29.98, "250 g")], items_count=None, subtotal=44.98)
check("بلا عدد مطبوع: لا دمج والملاحظة تبقى فيسقط lines_merged_cleanly",
      r["products_count"] == 2 and r["merge_notes"] and "lines_merged_cleanly" in failed_ids(r),
      (r["products_count"], r["merge_notes"], failed_ids(r)))

r = run([L(1, "Colored Nuts 250g", "R856", 15, "250 g"),
         L(1, "Japanese Mixed Nuts 250g", "R76", 29.98, "250 g")], items_count=None, subtotal=44.98)
check("كودان مختلفان = منتجان دائماً", r["products_count"] == 2 and codes(r) == ["R856", "R76"], codes(r))

r = run([L(1, "Talbinah R115", "R115", 23, "200 g"),
         L(1, "Talbinah R115", "R115", 23, "200 g")], items_count=2, subtotal=46)
check("توأم متطابق (نفس الكود والوزن والسعر) = حبتان مستقلتان",
      r["products_count"] == 2 and r["products_sum"] == 46, (r["products_count"], r["products_sum"]))

r = run([L(1, "Attar Tea Anise Tea R626", "R626", 27),
         L(1, "Something Else Entirely", None, 15)], items_count=2, subtotal=42)
check("العدد المطبوع يؤكد الاستقلال (سعر حقيقي): لا دمج ولا ملاحظة معلّقة",
      r["products_count"] == 2 and r["merge_notes"] == [], (r["products_count"], r["merge_notes"]))

r = run([L(1, "Colored Nuts", None, 15), L(1, "Japanese Mixed Nuts", None, 29.98)],
        items_count=2, subtotal=44.98,
        prepared=[{"code": "R856", "label_weight": "0.250"}, {"code": "R76", "label_weight": "0.250"}],
        fulfillment={"coverage": "full", "verdict": "matched", "lines": [
            {"code": "R856", "status": "matched", "note": "عبوة بملصق R856"},
            {"code": "R76", "status": "matched", "note": "عبوة بملصق R76"}]})
check("لا تبنّي عند تعدد المرشحين بلا دليل ربط: يبقى بلا كود ويسقط all_codes",
      codes(r) == [None, None] and "all_codes" in failed_ids(r), (codes(r), failed_ids(r)))

r = run([L(1, "Colored Nuts 250g", "R856", 15, "250 g"),
         L(1, "Japanese Mixed Nuts 250g", None, 29.98, "250 g")], items_count=2, subtotal=44.98,
        prepared=[{"code": "R76", "label_weight": "0.250"}],
        fulfillment={"coverage": "full", "verdict": "matched", "lines": [
            {"code": "R76", "status": "matched", "note": "عبوة بملصق R76 وزن 0.250"}]})
check("تبنّي بالوزن عند مرشح واحد لا منازع له", codes(r) == ["R856", "R76"], codes(r))

r = run([L(1, "Colored Nuts 250g", "R856", 15, "250 g"),
         L(2, "Japanese Mixed Nuts 250g", None, 29.98, "250 g")], items_count=1, subtotal=74.96)
check("كمية السطر السفلي 2X: لا يُدمج أبداً", r["products_count"] == 2, r["products_count"])

print("\n" + ("فشل: " + "، ".join(FAILED) if FAILED else "كل الاختبارات ناجحة"))
sys.exit(1 if FAILED else 0)
