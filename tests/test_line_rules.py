# -*- coding: utf-8 -*-
"""
اختبارات قواعد سطري المنتج والتوصيل والخصم (قواعد صاحبة النظام، 2026-09-10).
تشغيل: python3 tests/test_line_rules.py
"""
import os, sys, json

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import normalize_result, _ORDER_CODE_LEN, _norm_order_date  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  ✔ " if cond else "  ✘ ") + name + ("" if cond else "  <<< " + str(detail)))
    if not cond:
        FAILED.append(name)


def L(qty, name, code, weight, price, raw=""):
    return {"qty": qty, "name": name, "code": code, "weight": weight,
            "price": price, "raw_text": raw or name}


def run(lines, subtotal=None, delivery=None, delivery_printed=False, total=None,
        items_count=None, adjustments=None, platform="keeta", order_code=None,
        medium="printed_receipt", branch="Al Yasmin"):
    return normalize_result({
        "order_code": order_code,
        "platform": platform,
        "branch": branch,
        "order_date": "2026-09-06",
        "items_count": items_count,
        "lines": lines,
        "subtotal": subtotal,
        "delivery": delivery,
        "delivery_printed": delivery_printed,
        "total": total,
        "adjustments": adjustments or [],
        "evidence_medium": medium,
        "prepared_items": [],
        "fulfillment": {"coverage": "none", "verdict": "not_verifiable", "lines": []},
        "confidence": "high",
        "field_confidence": {"order_code": "high", "platform": "high",
                             "branch": "high", "order_total": "high"},
    })


def prod(res, code):
    for p in res["items"]:
        if p.get("code") == code:
            return p
    return None


print("\n1) المثال المرجعي thechefz 736961876 — ثلاثة منتجات ومجموعها 147.25")
r = run([
    L(1, "Myrrh Frankincense Male R112", "R112", None, 50.00),
    L(1, "Myrrh frankincense male 500g", None, "500g", 50.00),
    L(1, "Mastic Incense R712", "R712", None, 30.00),
    L(1, "Mastic Incense 250g", None, "250g", 0.00),
    L(1, "Black Raisins R569", "R569", None, 17.25),
    L(1, "Black Raisins 250g", None, "250g", 0.00),
], subtotal=147.25, total=147.25, items_count=3, platform="thechefz",
   order_code="736961876")
check("عدد المنتجات 3", len(r["items"]) == 3, len(r["items"]))
check("R112 = 100.00 و 500جم", prod(r, "R112")["line_total"] == 100.00 and prod(r, "R112")["total_weight_g"] == 500.0, prod(r, "R112"))
check("R712 = 30.00 و 250جم", prod(r, "R712")["line_total"] == 30.00 and prod(r, "R712")["total_weight_g"] == 250.0, prod(r, "R712"))
check("R569 = 17.25 و 250جم", prod(r, "R569")["line_total"] == 17.25 and prod(r, "R569")["total_weight_g"] == 250.0, prod(r, "R569"))
check("مجموع المنتجات 147.25", r["products_sum"] == 147.25, r["products_sum"])
check("الفحص الذاتي سليم", r["self_check"]["passed"], r["self_check"]["summary"])
check("thechefz بطول 9 مقبول", "order_code_len" not in r["self_check"]["failed"], r["self_check"]["failed"])

print("\n2) المثال المرجعي keeta 5146821078229802 — كمية 2 والتوصيل متجاهل")
r = run([
    L(2, "Raw Sunflower Seeds R665", "R665", None, 9.50),
    L(1, "Raw sunflower seeds 1000g", None, "1000g", 28.50),
], subtotal=76.00, delivery=18.00, delivery_printed=True, total=76.00,
   items_count=1, order_code="5146821078229802")
p = prod(r, "R665")
check("منتج واحد", len(r["items"]) == 1, len(r["items"]))
check("سعر الحبة 38.00", p["price"] == 38.00, p["price"])
check("السعر الكلي 76.00", p["line_total"] == 76.00, p["line_total"])
check("الوزن الكلي 2000جم", p["total_weight_g"] == 2000.0, p["total_weight_g"])
check("المرجع = SubTotal 76.00", r["order_total"] == 76.00 and r["order_total_basis"] == "subtotal", (r["order_total"], r["order_total_basis"]))
check("التوصيل منسوخ ولم يدخل المجموع", r["delivery"] == 18.00 and r["products_sum"] == 76.00, (r["delivery"], r["products_sum"]))
check("الفحص الذاتي سليم", r["self_check"]["passed"], r["self_check"]["summary"])

print("\n3) qwf-5-1106 — سطر وزن باسم مختلف يؤكده «N Items» المطبوع")
r = run([
    L(1, "Dried Fruits With Apricots and Prunes R584", "R584", None, 25.00),
    L(1, "Dried fruits prunes Bukhara 500g", None, "500g", 25.00),
], subtotal=50.00, delivery=22.00, delivery_printed=True, total=50.00, items_count=1)
p = prod(r, "R584")
check("منتج واحد", len(r["items"]) == 1, len(r["items"]))
check("R584 ×1 و500جم و50.00",
      p["quantity"] == 1 and p["total_weight_g"] == 500.0 and p["line_total"] == 50.00, p)
check("الفحص الذاتي سليم", r["self_check"]["passed"], r["self_check"]["summary"])

print("\n4) qws-5-5260 — سطر وزن 1000جم بسعر 75.00")
r = run([
    L(1, "فواكي مجففة فراصية برقوق بخاري R584", "R584", None, 25.00),
    L(1, "فواكي مجففة فراصية برقوق بخاري 1000g", None, "1000g", 75.00),
], subtotal=100.00, total=100.00, items_count=1)
p = prod(r, "R584")
check("R584 ×1 و1000جم و100.00",
      p["quantity"] == 1 and p["total_weight_g"] == 1000.0 and p["line_total"] == 100.00, p)
check("الفحص الذاتي سليم", r["self_check"]["passed"], r["self_check"]["summary"])

print("\n5) الصف 86 (جاهز) — منتج بلا سطر وزن + سطر وزن بلا وزن")
r = run([
    L(2, "Talbinah of the Prophet's Sunnah, Mugo Land R115", "R115", None, 23.00),
    L(1, "Viola Naturals Dandelion Tea 24 Bags R870", "R870", None, 35.00),
    L(1, "Viola Naturals Dandelion Tea 24 Bags", None, None, 0.00),
], subtotal=81.00, total=81.00, items_count=2, platform="jahez", order_code="5764382265")
check("عدد المنتجات 2", len(r["items"]) == 2, len(r["items"]))
check("R115 ×2 = 46.00", prod(r, "R115")["line_total"] == 46.00, prod(r, "R115"))
check("R870 ×1 = 35.00", prod(r, "R870")["line_total"] == 35.00, prod(r, "R870"))
check("المجموع 81.00", r["products_sum"] == 81.00, r["products_sum"])
check("R115 بلا وزن (منتج كامل)", prod(r, "R115")["total_weight_g"] is None, prod(r, "R115"))
check("R870 دُمج ووزنه null", prod(r, "R870")["merged_weight_line"] and prod(r, "R870")["total_weight_g"] is None, prod(r, "R870"))
check("عدد المنتجات مطابق للمطبوع", "items_count_match" not in r["self_check"]["failed"], r["self_check"]["failed"])
check("سقط all_weights فقط (وزن غير مطبوع)", r["self_check"]["failed"] == ["all_weights"], r["self_check"]["failed"])

print("\n6) سطر بلا كود R باسم مختلف تماماً — لا يُدمج")
r = run([
    L(1, "Talbinah of the Prophet Sunnah R115", "R115", None, 23.00),
    L(1, "Something Completely Different", None, None, 10.00),
], subtotal=33.00, total=33.00, items_count=2)
check("منتجان لا منتج", len(r["items"]) == 2, len(r["items"]))
check("سُجّل سبب صريح", any("لا يطابق اسم المنتج" in n for n in r["merge_notes"]), r["merge_notes"])
check("سقط lines_merged_cleanly", "lines_merged_cleanly" in r["self_check"]["failed"], r["self_check"]["failed"])
check("سقط all_codes", "all_codes" in r["self_check"]["failed"], r["self_check"]["failed"])

print("\n7) سطر سفلي بنفس كود العلوي — يُدمج")
r = run([
    L(1, "Japanese Mixed Nuts R76", "R76", None, 29.98),
    L(1, "Japanese mixed nuts R76 500g", "R76", "500g", 29.98),
], subtotal=59.96, total=59.96, items_count=1)
check("منتج واحد", len(r["items"]) == 1, len(r["items"]))
check("R76 = 59.96 و500جم",
      prod(r, "R76")["line_total"] == 59.96 and prod(r, "R76")["total_weight_g"] == 500.0, prod(r, "R76"))
check("الفحص الذاتي سليم", r["self_check"]["passed"], r["self_check"]["summary"])

print("\n8) نفس كود R في سطرين علويين — منتجان")
r = run([
    L(1, "Black Lemon Seeds R335", "R335", "250g", 15.00),
    L(1, "Black Lemon Seeds R335", "R335", "250g", 15.00),
], subtotal=30.00, total=30.00, items_count=2)
check("منتجان", len(r["items"]) == 2, len(r["items"]))
check("مجموعهما 30.00", r["products_sum"] == 30.00, r["products_sum"])
check("عدد المنتجات مطابق 2", "items_count_match" not in r["self_check"]["failed"], r["self_check"]["failed"])

print("\n9) نفس المنتج بسطرين علويين مع «2 Items» مطبوع = 1 — 🔵 بسبب عدد المنتجات")
r = run([
    L(1, "Black Lemon Seeds R335", "R335", "250g", 15.00),
    L(1, "Black Lemon Seeds R335", "R335", "250g", 15.00),
], subtotal=30.00, total=30.00, items_count=1)
check("سقط items_count_match", "items_count_match" in r["self_check"]["failed"], r["self_check"]["failed"])
check("السبب يذكر الرقمين", "2" in r["self_check"]["summary"] and "1" in r["self_check"]["summary"], r["self_check"]["summary"])

print("\n10) فاتورة بلا SubTotal و Total فيها توصيل — المرجع = Total ناقص التوصيل")
r = run([
    L(2, "Raw Sunflower Seeds R665", "R665", None, 9.50),
    L(1, "Raw sunflower seeds 1000g", None, "1000g", 28.50),
], subtotal=None, delivery=18.00, delivery_printed=True, total=94.00, items_count=1)
check("المرجع 76.00", r["order_total"] == 76.00, (r["order_total"], r["order_total_basis"]))
check("الأساس total_minus_delivery", r["order_total_basis"] == "total_minus_delivery", r["order_total_basis"])
check("مطابق بلا فرق", r["self_check"]["passed"], r["self_check"]["summary"])

print("\n11) بلا SubTotal والتوصيل مطبوع وغير مقروء — 🔵 بسبب صريح")
r = run([
    L(1, "Mastic Incense R712", "R712", "250g", 30.00),
], subtotal=None, delivery=None, delivery_printed=True, total=48.00, items_count=1)
check("لا مرجع", r["order_total"] is None, r["order_total"])
check("سقط total_read بسبب صريح", "total_read" in r["self_check"]["failed"] and "التوصيل غير مقروء" in r["self_check"]["summary"], r["self_check"]["summary"])

print("\n12) بلا سطر توصيل إطلاقاً — المرجع = Total")
r = run([
    L(1, "Mastic Incense R712", "R712", "250g", 30.00),
], subtotal=None, delivery=None, delivery_printed=False, total=30.00, items_count=1)
check("المرجع 30.00 أساسه total_no_delivery_line",
      r["order_total"] == 30.00 and r["order_total_basis"] == "total_no_delivery_line",
      (r["order_total"], r["order_total_basis"]))
check("الفحص الذاتي سليم", r["self_check"]["passed"], r["self_check"]["summary"])

print("\n13) كوبون — يُنسخ في adjustments ولا يدخل أي مجموع")
r = run([
    L(1, "Mastic Incense R712", "R712", "250g", 30.00),
], subtotal=30.00, delivery=18.00, delivery_printed=True, total=33.00, items_count=1,
   adjustments=[{"label": "Coupon", "amount": -15.00}])
check("adjustments منسوخ", r["adjustments"] == [{"label": "Coupon", "amount": -15.0}], r["adjustments"])
check("المنتجات مطابقة للمرجع", r["self_check"]["passed"], r["self_check"]["summary"])
check("المرجع لم يتأثر بالكوبون", r["order_total"] == 30.00, r["order_total"])

print("\n14) شاشة هنجر بلا أي مبالغ — لا مرجع، والمنصة تُستنتج")
r = run([
    L(1, "Greek Mastic 20g R181", "R181", "20g", 99.00),
], platform=None, medium="app_screen", branch=None)
check("المنصة hunger بالاستنتاج", r["platform"] == "hunger" and r["platform_source"] == "inferred_medium", (r["platform"], r["platform_source"]))
check("لا مرجع", r["order_total"] is None, r["order_total"])

print("\n15) التوصيل لا يصبح بنداً أبداً")
r = run([
    L(1, "Mastic Incense R712", "R712", "250g", 30.00),
], subtotal=30.00, delivery=18.00, delivery_printed=True, total=30.00, items_count=1)
check("لا منتج اسمه توصيل", not any("توصيل" in (p.get("name") or "") or "delivery" in (p.get("name") or "").lower() for p in r["items"]), r["items"])
check("عدد المنتجات 1", len(r["items"]) == 1, len(r["items"]))

print("\n16) سطر وزن باسم مختلف و«N Items» غير مقروء — لا يُدمج مع سبب صريح")
r = run([
    L(1, "Dried Fruits With Apricots and Prunes R584", "R584", None, 25.00),
    L(1, "Dried fruits prunes Bukhara 500g", None, "500g", 25.00),
], subtotal=50.00, total=50.00, items_count=None)
check("منتجان لا منتج", len(r["items"]) == 2, len(r["items"]))
check("السبب حرفياً كما طلبت",
      any("اسم السطر السفلي مختلف" in n and "ولا يوجد عدد منتجات للتأكيد" in n for n in r["merge_notes"]),
      r["merge_notes"])
check("سقط lines_merged_cleanly", "lines_merged_cleanly" in r["self_check"]["failed"], r["self_check"]["failed"])

print("\n17) سطر وزن باسم مختلف و«N Items» مقروء لكنه لا يطابق بعد الدمج — لا يُدمج")
r = run([
    L(1, "Dried Fruits With Apricots and Prunes R584", "R584", None, 25.00),
    L(1, "Dried fruits prunes Bukhara 500g", None, "500g", 25.00),
], subtotal=50.00, total=50.00, items_count=2)
check("منتجان (العدد المطبوع 2)", len(r["items"]) == 2, len(r["items"]))
check("عدد المنتجات مطابق للمطبوع", "items_count_match" not in r["self_check"]["failed"], r["self_check"]["failed"])

print("\n18) سطر بلا كود وتشابه اسمه ≥ 0.85 — يُدمج بلا حاجة لعدد المنتجات")
r = run([
    L(1, "Raw Sunflower Seeds R665", "R665", None, 9.50),
    L(1, "Raw sunflower seeds 1000g", None, "1000g", 28.50),
], subtotal=38.00, total=38.00, items_count=None)
p18 = prod(r, "R665")
check("منتج واحد", len(r["items"]) == 1, len(r["items"]))
check("سعر الحبة 38.00 والوزن 1000جم",
      p18["line_total"] == 38.00 and p18["total_weight_g"] == 1000.0, p18)
check("بلا ملاحظات دمج", r["merge_notes"] == [], r["merge_notes"])

print("\n19) تاريخ الطلب — «Printed At» بصيغة اليوم أولاً")
check("Printed At: 06-09-2026 ← 2026-09-06",
      _norm_order_date("06-09-2026") == "2026-09-06", _norm_order_date("06-09-2026"))
check("Printed At: 08-09-2026 01:12 AM ← 2026-09-08",
      _norm_order_date("08-09-2026 01:12 AM") == "2026-09-08",
      _norm_order_date("08-09-2026 01:12 AM"))
check("27/08/2026 ← 2026-08-27",
      _norm_order_date("27/08/2026") == "2026-08-27", _norm_order_date("27/08/2026"))
check("صيغة ISO تبقى كما هي",
      _norm_order_date("2026-09-06") == "2026-09-06", _norm_order_date("2026-09-06"))
check("Today ليست تاريخاً", _norm_order_date("Today") is None, _norm_order_date("Today"))
check("null / فراغ ← None",
      _norm_order_date(None) is None and _norm_order_date("") is None
      and _norm_order_date("null") is None)
check("تاريخ مستحيل ← None",
      _norm_order_date("32-13-2026") is None, _norm_order_date("32-13-2026"))
check("نص بلا تاريخ ← None",
      _norm_order_date("Printed At") is None, _norm_order_date("Printed At"))
r = run([L(1, "Test Item R100", "R100", None, 10.00)], subtotal=10.00, total=10.00)
check("normalize_result يعيد التاريخ موحّداً",
      r["order_date"] == "2026-09-06", r["order_date"])
r = normalize_result({
    "order_code": None, "platform": "keeta", "branch": "Al Yasmin",
    "order_date": "08-09-2026 01:12 AM", "items_count": 1,
    "lines": [L(1, "Dried Fruits With Apricots and Prunes R584", "R584", None, 25.00),
              L(1, "Dried fruits prunes Bukhara 500g", None, "500g", 25.00)],
    "subtotal": 50.00, "delivery": 22.00, "delivery_printed": True, "total": 50.00,
    "adjustments": None, "evidence_medium": "printed_receipt",
    "field_confidence": {"order_code": "low", "platform": "high",
                         "branch": "high", "order_total": "high"},
})
check("فاتورة qwf-5-1106: التاريخ 2026-09-08 لا فراغ",
      r["order_date"] == "2026-09-08", r["order_date"])


print("\n" + ("=" * 60))
if FAILED:
    print("سقطت %d حالة: %s" % (len(FAILED), " | ".join(FAILED)))
    sys.exit(1)
print("كل الاختبارات نجحت ✅")
