# -*- coding: utf-8 -*-
"""
اختبارات قاعدة سطر الوصف بسعر 0.00 (قاعدة صاحبة النظام، 2026-09-12):
  1) وصف بسعر حقيقي: يُجمع سعره مع السطر الذي فوقه — المسار القديم لا يُمسّ.
  2) وصف بسعر 0.00: لا يُعدّ منتجاً أبداً؛ يُؤخذ وزنه/حجمه ويُنسب للسطر الذي فوقه ثم يُطرح.
  3) لا يُنشأ أي بند بلا كود من سطر سعره 0.00، في أي طلب وأي منصة.
الحالات 1-3 مأخوذة حرفياً من «سجل استخراج الفيديو» (tests/fixtures).
تشغيل: python3 tests/test_zero_price_lines.py
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


def codes(r):
    return [p.get("code") for p in r["items"]]


def failed_ids(r):
    return set(r["self_check"]["failed"])


def prod(r, code):
    return [p for p in r["items"] if p.get("code") == code][0]


def L(qty, name, code, price, weight=None, raw=None):
    return {"qty": qty, "name": name, "code": code, "weight": weight,
            "price": price, "raw_text": raw or name}


def run(lines, items_count=None, subtotal=None, total=None, platform="keeta"):
    return normalize_result({
        "order_code": None, "platform": platform, "branch": "Al Yasmin",
        "order_date": "2026-09-11", "evidence_medium": "printed_receipt",
        "items_count": items_count, "subtotal": subtotal, "delivery": None,
        "delivery_printed": False, "total": total, "adjustments": [], "lines": lines,
        "prepared_items": [], "fulfillment": {},
        "field_confidence": {"order_total": "high"}, "confidence": "high",
    })


print("\n=== 1) qwd-5-1331 — ثلاثة سطور 0.00 في فاتورة واحدة ===")
r = fixture("qwd-5-1331_1gHeY8Uu.json")
check("ثلاثة منتجات = العدد المطبوع", r["products_count"] == 3 == r["items_count"], r["products_count"])
check("الأكواد R255/R232/R630", codes(r) == ["R255", "R232", "R630"], codes(r))
check("لا بند بلا كود", all(codes(r)), codes(r))
check("الكركدية 150جم بسعر 23", prod(r, "R255")["total_weight_g"] == 150 and prod(r, "R255")["line_total"] == 23, prod(r, "R255"))
check("الورد المحمدي 100جم بسعر 56", prod(r, "R232")["total_weight_g"] == 100 and prod(r, "R232")["line_total"] == 56, prod(r, "R232"))
check("شاي الرمان 27 بلا وزن (وصف 1piece بلا وزن)", prod(r, "R630")["line_total"] == 27 and prod(r, "R630")["total_weight_g"] is None, prod(r, "R630"))
check("المجموع 106 كما هو", r["products_sum"] == 106, r["products_sum"])
check("لا ملاحظة دمج", r["merge_notes"] == [], r["merge_notes"])
check("all_codes / items_count_match / lines_merged_cleanly سليمة",
      not ({"all_codes", "items_count_match", "lines_merged_cleanly"} & failed_ids(r)), failed_ids(r))
check("لا إضعاف: all_weights يبقى ساقطاً على R630 (شاي بلا وزن)", "all_weights" in failed_ids(r), failed_ids(r))

print("\n=== 2) qwd-5-1333 — وصف 0.00 بنفس اسم السطر فوقه ووصف 1piece ===")
r = fixture("qwd-5-1333_1wAsHQb3.json")
check("منتجان = العدد المطبوع", r["products_count"] == 2 == r["items_count"], r["products_count"])
check("الأكواد R619/R870", codes(r) == ["R619", "R870"], codes(r))
check("الأسعار 27 و35 والمجموع 62", [p["line_total"] for p in r["items"]] == [27, 35] and r["products_sum"] == 62,
      [p["line_total"] for p in r["items"]])
check("لا ملاحظة دمج", r["merge_notes"] == [], r["merge_notes"])
check("all_codes / items_count_match / lines_merged_cleanly سليمة",
      not ({"all_codes", "items_count_match", "lines_merged_cleanly"} & failed_ids(r)), failed_ids(r))

print("\n=== 3) qwd-5-1329 — وصف 0.00 ووصف بسعر حقيقي في الفاتورة نفسها ===")
r = fixture("qwd-5-1329_1aPkJHiZ.json")
check("ثلاثة منتجات = العدد المطبوع", r["products_count"] == 3 == r["items_count"], r["products_count"])
check("الأكواد R626/R325/R625", codes(r) == ["R626", "R325", "R625"], codes(r))
check("(قاعدة 1 سليمة) اللوز 500جم بسعر 40 = 20+20", 
      prod(r, "R325")["total_weight_g"] == 500 and prod(r, "R325")["line_total"] == 40, prod(r, "R325"))
check("سطرا 0.00 لم يصيرا بندين", [p["line_total"] for p in r["items"]] == [27, 40, 27],
      [p["line_total"] for p in r["items"]])
check("المجموع 94 كما هو", r["products_sum"] == 94, r["products_sum"])
check("لا ملاحظة دمج", r["merge_notes"] == [], r["merge_notes"])

print("\n=== 4) القاعدة عامة، والحمايات كما هي ===")
r = run([L(1, "Hibiscus R255", "R255", 23), L(1, "Hibiscus 150g", None, 0, "150g")], subtotal=23)
check("بلا «N Items» أصلاً: الوصف 0.00 يُطوى ولا ينتظر تأكيداً",
      r["products_count"] == 1 and prod(r, "R255")["total_weight_g"] == 150 and r["merge_notes"] == [],
      (r["products_count"], r["merge_notes"]))

r = run([L(1, "Hibiscus R255", "R255", 23), L(1, "Totally Different Thing", None, 0)], items_count=2, subtotal=23)
check("حتى لو قال العدد المطبوع 2: سطر 0.00 لا يكون منتجاً أبداً", r["products_count"] == 1, r["products_count"])

r = run([L(1, "Hibiscus R255", "R255", 23), L(1, "Free Gift R900", "R900", 0)], items_count=2, subtotal=23)
check("سطر 0.00 بكود R خاص به = صنف مستقل (هدية/عرض)", r["products_count"] == 2 and codes(r) == ["R255", "R900"], codes(r))

r = run([L(1, "Hibiscus 150g", None, 0, "150g"), L(1, "Mohammadi Rose R232", "R232", 56)], subtotal=56)
check("سطر 0.00 في أول القائمة: لا يصير بنداً ويُسجَّل السبب",
      r["products_count"] == 1 and any("بلا سطر منتج قبله" in n for n in r["merge_notes"]),
      (r["products_count"], r["merge_notes"]))

r = run([L(1, "Colored Nuts 250g R856", "R856", 15, "250g"), L(1, "Colored nuts 1piece", None, 0)], subtotal=15)
check("وزن السطر العلوي لا يضيع حين يُطوى وصف بلا وزن",
      prod(r, "R856")["total_weight_g"] == 250, prod(r, "R856"))

r = run([L(1, "Talbinah R115", "R115", 23, "200g"), L(1, "Talbinah 200g", None, 0, "200g"),
         L(1, "Talbinah variant", None, 0)], items_count=1, subtotal=23)
check("وصفان متتاليان بـ 0.00 يُطويان في منتج واحد",
      r["products_count"] == 1 and prod(r, "R115")["line_total"] == 23, (r["products_count"], r["items"]))

r = run([L(1, "Talbinah R115", "R115", 23, "200g"), L(1, "Talbinah R115", "R115", 23, "200g")],
        items_count=2, subtotal=46)
check("توأم متطابق بسعر حقيقي = عبوتان (لا يُمسّ)", r["products_count"] == 2 and r["products_sum"] == 46,
      (r["products_count"], r["products_sum"]))

r = run([L(1, "Dried fruits R584", "R584", 25, None), L(1, "Dried fruits 250g", None, 25, "250g")],
        items_count=1, subtotal=50)
check("(قاعدة 1) وصف بسعر حقيقي: يُجمع 25+25 = 50 ووزن 250جم",
      r["products_count"] == 1 and prod(r, "R584")["line_total"] == 50 and prod(r, "R584")["total_weight_g"] == 250,
      r["items"])

print("\n" + ("فشل: " + "، ".join(FAILED) if FAILED else "كل الاختبارات ناجحة"))
sys.exit(1 if FAILED else 0)
