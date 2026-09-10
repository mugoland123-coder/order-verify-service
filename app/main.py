import os, re, subprocess, tempfile, base64, json, difflib
from pathlib import Path
import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from anthropic import Anthropic

app = FastAPI()
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

def extract_first_json_object(text: str) -> str | None:
    """
    يبحث عن أول '{' في النص ثم يتتبّع الأقواس المعقوفة بشكل متوازن
    (مع تجاهل أي '{' أو '}' تقع داخل نص JSON محاط بعلامتي اقتباس)
    حتى يصل للقوس المغلق المطابق تمامًا، ويرجع أول كائن JSON كامل
    ومتوازن كنص خام.

    هذا يتجاهل تلقائيًا أي شيء حول الكائن — code fence (```json أو ```
    بأي ترتيب/شكل)، نص عربي إضافي قبله أو بعده، أو حتى كلمة "json"
    نفسها — لأنه لا يعتمد على تفكيك الـ fence إطلاقاً، فقط على تطابق
    الأقواس. يرجع None إذا لم يوجد '{' أصلاً أو لم يوجد إغلاق متوازن له.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None

class VerifyRequest(BaseModel):
    video_url: str
    invoice_text: str | None = None

class FFmpegExtractionError(Exception):
    """يُرفع عند فشل ffmpeg تقنياً أثناء استخراج إطارات فيديو معيّن."""
    pass

IMAGE_EXTENSIONS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp"}

def detect_input_kind(source_url: str, file_path: str) -> tuple[str, str | None]:
    """
    يحدد نوع/امتداد الملف المستلم (صورة أم فيديو) في نقطة /verify-order
    أول شي.

    يعتمد أولاً على امتداد الرابط نفسه (video_url). إذا كان الامتداد غير
    معروف أو غير موجود بالرابط (كحال روابط Google Drive التي لا تحتوي
    عادة على امتداد ظاهر)، يرجع لفحص أول بايتات من الملف المُنزَّل فعلياً
    (JPEG/PNG signature) كخطة بديلة.

    يرجع ("image", media_type) للصور، أو ("video", None) لأي شيء آخر —
    بما يشمل mp4 وامتدادات الفيديو المعروفة — ليبقى المسار الحالي
    (ffmpeg) هو المسار الافتراضي تماماً كما كان.
    """
    ext = Path(source_url.split("?")[0]).suffix.lower()

    if ext in IMAGE_EXTENSIONS:
        return "image", IMAGE_EXTENSIONS[ext]
    if ext in VIDEO_EXTENSIONS:
        return "video", None

    try:
        with open(file_path, "rb") as f:
            header = f.read(12)
    except OSError:
        return "video", None

    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"

    return "video", None

def probe_duration(video_path: str):
    """مدة الفيديو بالثواني عبر ffprobe، أو None إن تعذّر."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", video_path],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        d = float(out)
        return d if d > 0 else None
    except Exception:
        return None


def frame_timestamps(duration: float, count: int = 40):
    """
    توقيتات ثابتة موزّعة بالتساوي على مدة الفيديو: t_i = duration * i / (count + 1)
    لـ i من 1 إلى count. حتمية تماماً: نفس المدة تعطي نفس التوقيتات دائماً.
    """
    return [round(duration * i / (count + 1), 3) for i in range(1, count + 1)]


def extract_frames_at(video_path: str, out_dir: str, timestamps):
    """
    يستخرج إطاراً واحداً عند كل طابع زمني صريح. الاختيار حتمي ولا يعتمد على
    معدّل إطارات ولا على ترتيب ملفات، فنفس الفيديو يعطي نفس الإطارات في كل تشغيلة.
    """
    frames = []
    for idx, t in enumerate(timestamps):
        out = f"{out_dir}/frame_{idx:03d}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-accurate_seek", "-ss", f"{t:.3f}",
                 "-i", video_path, "-frames:v", "1", "-q:v", "2", out],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError:
            continue
        p = Path(out)
        if p.exists() and p.stat().st_size > 0:
            frames.append(p)
    if not frames:
        raise FFmpegExtractionError("no frames extracted at the requested timestamps")
    return frames


def extract_frames(video_path: str, out_dir: str, fps: float = 3.0):
    """مسار احتياطي فقط: يُستخدم حين تتعذّر معرفة مدة الفيديو."""
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-i", video_path, "-vf", f"fps={fps}",
             f"{out_dir}/frame_%03d.jpg"],
            check=True, capture_output=True
        )
    except subprocess.CalledProcessError as e:
        raise FFmpegExtractionError(str(e)) from e
    return sorted(Path(out_dir).glob("frame_*.jpg"))


def select_frames_covering_full_video(frames, max_frames: int = 40):
    """اختيار متساوي التباعد من قائمة إطارات جاهزة — للمسار الاحتياطي فقط."""
    total = len(frames)
    if total <= max_frames:
        return frames
    step = total / max_frames
    indices = sorted({int(i * step) for i in range(max_frames)})
    if indices[-1] != total - 1:
        indices[-1] = total - 1
    return [frames[i] for i in indices]


# ---------------------------------------------------------------------------
# تطبيع رد النموذج قبل إرجاعه للـworkflow.
# النموذج يخرج أحياناً "ر253" بدل R253، أو وزناً بصيغة "0.250" بلا وحدة،
# أو اسم منصة بصيغة حرة. هذه الدالة توحّد كل ذلك، وتضمن وجود كل الحقول
# التي يعتمد عليها n8n حتى لو أغفلها النموذج.
# ---------------------------------------------------------------------------

_PLATFORM_MAP = {
    "keeta": "keeta", "كيتا": "keeta",
    "jahez": "jahez", "جاهز": "jahez",
    "hunger": "hunger", "hungerstation": "hunger", "هنجر": "hunger",
    "ninja": "ninja", "نينجا": "ninja",
    "thechefz": "thechefz", "chefz": "thechefz", "شيفز": "thechefz", "شيقز": "thechefz",
    "marsool": "marsool", "مرسول": "marsool",
    "toyou": "toyou", "تويو": "toyou",
}

_BRANCH_BY_CODE = {
    "0001": "Al Masiaf", "0002": "Al Wisham", "0003": "Al Khaleej",
    "0004": "Al Yasmin", "0005": "Dhahrat Laban",
}


def _norm_platform(value):
    if not value:
        return "unknown"
    s = str(value).strip().lower()
    if s in ("", "not_applicable", "n/a", "none", "null", "unknown"):
        return "unknown"
    if s in _PLATFORM_MAP:
        return _PLATFORM_MAP[s]
    for key, val in _PLATFORM_MAP.items():
        if key in s:
            return val
    return "unknown"


def _norm_branch(value):
    if value is None or str(value).strip() == "":
        return None
    s = str(value).strip()
    if s.lower() in ("unknown", "n/a", "none", "null"):
        return None
    digits = re.sub(r"\D", "", s)
    if digits and digits.zfill(4) in _BRANCH_BY_CODE:
        return _BRANCH_BY_CODE[digits.zfill(4)]
    return s


def _num(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _norm_code(item):
    """يقبل code جاهزاً أو يستخرجه من الاسم: R253 · ر253 · (R253) · SKU: R253"""
    candidate = item.get("code") or ""
    match = re.search(r"[رR]\s?(\d{1,5})", str(candidate))
    if not match:
        match = re.search(r"[رR]\s?(\d{1,5})", str(item.get("name") or ""))
    return "R" + match.group(1) if match else None


def _norm_weight(item):
    """يوحّد الوزن. القيمة بلا وحدة وأقل من 20 تُعامل كيلوجرام (0.250 = 250g)."""
    value = _num(item.get("weight_value"))
    unit = str(item.get("weight_unit") or "").strip().lower()
    if value is None:
        match = re.search(
            r"(\d+(?:\.\d+)?)\s*(kg|g|كجم|كيلو|كغ|جرام|جم|غم)?",
            str(item.get("weight") or "").replace(" ", ""),
        )
        if not match:
            return None, None
        value = float(match.group(1))
        unit = (match.group(2) or "").lower()
    if unit in ("kg", "كجم", "كيلو", "كغ") or (not unit and value < 20):
        return round(value, 4), "kg"
    return round(value, 2), "g"


def _grams(value, unit):
    """يحوّل (قيمة، وحدة) إلى جرامات، أو None."""
    if value is None:
        return None
    if str(unit or "").strip().lower() == "kg":
        return round(float(value) * 1000, 2)
    return round(float(value), 2)


def _clean_name(raw_name):
    name = re.sub(r"[رR]\s?\d{1,5}", "", str(raw_name or ""))
    name = re.sub(r"\(\s*\)|\[\s*\]", " ", name)
    name = re.sub(r"\s*-\s*SKU\s*:?\s*", " ", name, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", name).strip(" -–_")


_CONF = ("high", "medium", "low")


def _norm_conf(value):
    s = str(value or "").strip().lower()
    return s if s in _CONF else "low"


_FULFILL_STATUS = ("matched", "missing", "extra", "weight_diff", "not_seen")
_COVERAGE = ("full", "partial", "none")
_VERDICT = ("matched", "mismatch", "not_verifiable")
_MEDIUM = ("printed_receipt", "app_screen", "unknown")


def _norm_invoice_items(raw):
    """بنود الفاتورة كما قرأها النموذج من الشاشة/الورقة فقط."""
    out = []
    for it in (raw or []):
        if not isinstance(it, dict):
            continue
        qty = _num(it.get("quantity"))
        out.append({
            "code": _norm_code(it),
            "name": _clean_name(it.get("name")),
            "quantity": int(qty) if qty is not None else None,
            "unit_price": _num(it.get("unit_price") if it.get("unit_price") is not None else it.get("price")),
            "line_total": _num(it.get("line_total")),
        })
    return out


def _invoice_sum(rows, total_key="line_total", unit_key="unit_price"):
    """مجموع بنود قائمة الفاتورة؛ None إذا لم يكن فيها أي سعر."""
    total = None
    for it in (rows or []):
        if not isinstance(it, dict):
            continue
        val = _num(it.get(total_key))
        if val is None:
            unit = _num(it.get(unit_key))
            if unit is None:
                continue
            qty = _num(it.get("quantity")) or 1
            val = unit * qty
        total = val if total is None else total + val
    return None if total is None else round(total, 2)


def _reconcile_invoice_items(invoice_items, items, order_total):
    """
    الإجمالي المطبوع على الفاتورة هو المرجع.
    قائمتا items و invoice_items قراءتان لنفس الفاتورة، وقد تختلفان حين يقرأ
    النموذج عدداً مختلفاً من أسطر متغيّر الوزن. إن كانت إحداهما تطابق الإجمالي
    المطبوع والأخرى لا، تُعتمد المطابِقة. قرار حسابي بحت، بلا تخمين.
    """
    if order_total is None:
        return invoice_items, "no_total"
    sum_inv = _invoice_sum(invoice_items)
    sum_items = _invoice_sum(items, "line_total", "price")
    if sum_inv is not None and abs(sum_inv - order_total) <= 0.01:
        return invoice_items, "ok"
    if sum_items is None or abs(sum_items - order_total) > 0.01:
        return invoice_items, "conflict"
    rebuilt = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        line_total = _num(it.get("line_total"))
        unit_price = _num(it.get("price"))
        qty = _num(it.get("quantity"))
        if line_total is None and unit_price is not None:
            line_total = round(unit_price * (qty or 1), 2)
        rebuilt.append({
            "code": it.get("code"),
            "name": it.get("name"),
            "quantity": int(qty) if qty is not None else None,
            "unit_price": unit_price,
            "line_total": line_total,
        })
    if not rebuilt:
        return invoice_items, "conflict"
    return rebuilt, "rebuilt_from_items"


# أطوال أرقام الطلبات المعروفة لكل منصة، مقاسة على الاستخراجات المخزّنة.
# المنصات غير المذكورة هنا لا يُفحص طول رقم طلبها إطلاقاً.
_ORDER_CODE_LEN = {"hunger": (10,), "keeta": (16,), "ninja": (9,), "jahez": (10,),
                   "thechefz": (9,)}

# سماحية مطابقة مجموع البنود مع الإجمالي المطبوع (ريال).
_SELF_CHECK_TOL = 0.05


def _self_check(order_code, platform, reference, ref_basis, products,
                items_count, merge_notes, invoice_sum_check, field_conf):
    """
    فحص ذاتي حسابي بحت على القراءة نفسها — لا يحكم على الطلب ولا على الموظف،
    بل يقول: هل هذه القراءة موثوقة بما يكفي لتُقارَن بفاتورة سماك؟
    المرجع هو SubTotal المطبوع، أو Total ناقص التوصيل المطبوع. التوصيل لا يدخل أي مجموع.
    كل فحص يُرجع {id, ok, detail}. passed = False إذا سقط أي فحص واحد.
    """
    checks = []

    def add(cid, ok, detail=""):
        checks.append({"id": cid, "ok": bool(ok), "detail": detail if not ok else ""})

    ref_label = _REF_LABEL.get(ref_basis, "المرجع المطبوع")

    # 1) مرجع أسعار المنتجات مقروء (SubTotal، أو Total ناقص التوصيل)
    add("total_read", reference is not None,
        "لم يُقرأ مرجع أسعار المنتجات: لا SubTotal مطبوع، والتوصيل غير مقروء لخصمه من Total")

    # 2) مجموع أسعار المنتجات = المرجع المطبوع
    priced = [p for p in products if _num(p.get("line_total")) is not None]
    if reference is None:
        add("sum_matches_total", False, "لا مرجع مطبوع للمقارنة")
    elif not priced:
        add("sum_matches_total", False, "لا سعر مقروء لأي بند")
    else:
        line_sum = round(sum(_num(p.get("line_total")) for p in priced), 2)
        diff = round(abs(line_sum - reference), 2)
        add("sum_matches_total", diff <= _SELF_CHECK_TOL,
            "مجموع المنتجات %s لا يساوي %s %s (فارق %s)" % (line_sum, ref_label, reference, diff))

    # 3) قُرئ سعر بند واحد على الأقل
    add("any_price", bool(priced), "لم يُقرأ سعر أي بند")

    # 4) كل منتج يحمل كود R
    if not products:
        add("all_codes", False, "لم يُقرأ أي بند")
    else:
        no_code = [p for p in products if not p.get("code")]
        add("all_codes", not no_code, "%d بند بلا كود R" % len(no_code))

    # 5) كل منتج له وزن إجمالي مقروء
    if not products:
        add("all_weights", False, "لم يُقرأ أي بند")
    else:
        no_weight = [p for p in products if p.get("total_weight_g") is None]
        add("all_weights", not no_weight,
            "بنود بلا وزن: " + "، ".join((p.get("code") or p.get("name") or "?") for p in no_weight))

    # 6) طول رقم الطلب مطابق لطول المنصة المعروف
    lens = _ORDER_CODE_LEN.get(platform)
    if order_code and lens:
        digits = re.sub(r"\D", "", str(order_code))
        add("order_code_len", len(digits) in lens,
            "رقم الطلب %s طوله %d والمتوقع %s" % (order_code, len(digits),
                                                  "/".join(str(n) for n in lens)))
    else:
        # لا رقم طلب، أو منصة بلا طول معروف — لا شيء يمكن فحصه، فلا يسقط الفحص.
        add("order_code_len", True)

    # 7) ثقة النموذج في الإجمالي = high
    add("total_confidence",
        reference is not None and _norm_conf(field_conf.get("order_total")) == "high",
        "ثقة الإجمالي %s وليست high" % _norm_conf(field_conf.get("order_total")))

    # 8) القائمتان تتفقان مع المرجع المطبوع
    add("invoice_lists_agree", invoice_sum_check != "conflict",
        "قائمتا الفاتورة لا تتفقان مع المرجع المطبوع")

    # 9) كل سطر طُبع أُسند إلى منتجه بلا لبس (لا سطر متغيّر وزن معلّق)
    add("lines_merged_cleanly", not merge_notes, " ؛ ".join(merge_notes[:3]))

    # 10) عدد المنتجات بعد الدمج = «N Items» المطبوع (يُتخطى وحده إن لم يُقرأ العدد)
    if items_count is None:
        add("items_count_match", True)
    else:
        add("items_count_match", int(items_count) == len(products),
            "عدد المنتجات بعد الدمج %d لا يساوي العدد المطبوع %d" % (len(products), int(items_count)))

    failed = [c["id"] for c in checks if not c["ok"]]
    return {
        "passed": not failed,
        "failed": failed,
        "checks": checks,
        "summary": "سليم" if not failed
                   else " | ".join((c["detail"] or c["id"]) for c in checks if not c["ok"]),
    }


def _norm_prepared_items(raw):
    """العبوات التي رآها النموذج فعلاً. seen_count هو عدد العبوات المرئية، لا كمية الفاتورة."""
    out = []
    for it in (raw or []):
        if not isinstance(it, dict):
            continue
        seen = _num(it.get("seen_count"))
        wv, wu = _norm_weight({
            "weight_value": it.get("label_weight_value"),
            "weight_unit": it.get("label_weight_unit"),
            "weight": it.get("label_weight"),
        })
        out.append({
            "code": _norm_code(it),
            "name": _clean_name(it.get("name")),
            "seen_count": int(seen) if seen is not None else None,
            "label_weight": it.get("label_weight"),
            "label_weight_g": _grams(wv, wu),
        })
    return out


def _norm_fulfillment(raw, prepared):
    """
    يطبّع حكم التحضير. القاعدة الصارمة: 'missing' اتهام ولا تُقبل إلا مع coverage='full'؛
    أي شك يُخفَّض إلى 'not_seen'. وإذا لم تُرَ أي عبوة إطلاقاً فالحكم not_verifiable مهما قال النموذج.
    """
    raw = raw if isinstance(raw, dict) else {}
    coverage = str(raw.get("coverage") or "").strip().lower()
    if coverage not in _COVERAGE:
        coverage = "none" if not prepared else "partial"
    if not prepared:
        coverage = "none"

    lines = []
    for ln in (raw.get("lines") or []):
        if not isinstance(ln, dict):
            continue
        st = str(ln.get("status") or "").strip().lower()
        if st not in _FULFILL_STATUS:
            st = "not_seen"
        if st == "missing" and coverage != "full":
            st = "not_seen"
        lines.append({
            "code": _norm_code(ln),
            "status": st,
            "note": str(ln.get("note") or "").strip() or None,
        })

    # الحكم يُشتق من السطور بعد تطبيعها، لا يُؤخذ من النموذج كما هو،
    # حتى لا يبقى حكم "mismatch" قائماً بعد تخفيض سطوره إلى not_seen.
    hard = [l for l in lines if l["status"] in ("missing", "extra", "weight_diff")]
    if coverage == "none":
        verdict = "not_verifiable"
    elif hard:
        verdict = "mismatch"
    elif lines and coverage == "full" and all(l["status"] == "matched" for l in lines):
        verdict = "matched"
    else:
        verdict = "not_verifiable"

    counts = {k: 0 for k in _FULFILL_STATUS}
    for l in lines:
        counts[l["status"]] += 1

    return {"coverage": coverage, "verdict": verdict, "lines": lines, "counts": counts}


_WEIGHT_TOKEN = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:g|gm|gr|gram|grams|kg|كجم|كغ|كيلو|جرام|جم|غم)\b", re.I
)
_WEIGHT_ONLY = re.compile(
    r"^[\s\-–·xX×]*\d+(?:[.,]\d+)?\s*(?:g|gm|gr|gram|grams|kg|كجم|كغ|كيلو|جرام|جم|غم)\s*$", re.I
)


def _name_key(value):
    """اسم مبسّط للمقارنة: بلا كود R ولا أوزان ولا رموز."""
    txt = re.sub(r"[رR]\s?\d{1,5}", " ", str(value or ""))
    txt = _WEIGHT_TOKEN.sub(" ", txt)
    txt = re.sub(r"[^\w\u0600-\u06FF]+", " ", txt, flags=re.UNICODE)
    return re.sub(r"\s+", " ", txt).strip().lower()

_REF_LABEL = {
    "subtotal": "SubTotal المطبوع",
    "total_minus_delivery": "Total ناقص التوصيل",
    "total_no_delivery_line": "Total المطبوع (بلا سطر توصيل)",
}

# الحد الأدنى لتشابه الاسم بين السطر العلوي وسطر خيار الوزن.
_NAME_SIM_MIN = 0.85


def _name_sim(a, b):
    """تشابه اسمين بعد التطبيع: حروف صغيرة، بلا كود R ولا وزن ولا رموز، وبلا مسافات."""
    ka, kb = _name_key(a), _name_key(b)
    if not ka or not kb:
        return 0.0
    sa, sb = ka.replace(" ", ""), kb.replace(" ", "")
    return round(max(difflib.SequenceMatcher(None, ka, kb).ratio(),
                     difflib.SequenceMatcher(None, sa, sb).ratio()), 3)


def _has_weight_token(line):
    for key in ("raw_name", "name", "weight", "raw_text"):
        if _WEIGHT_TOKEN.search(str(line.get(key) or "")):
            return True
    return line.get("weight_value") is not None


def _norm_raw_line(raw):
    """سطر مطبوع كما نسخه النموذج: بلا دمج، بلا ضرب، بلا تفسير."""
    if not isinstance(raw, dict):
        return None
    qty = _num(raw.get("qty") if raw.get("qty") is not None else raw.get("quantity"))
    value, unit = _norm_weight(raw)
    price = _num(raw.get("price"))
    if price is None:
        price = _num(raw.get("line_total"))
    return {
        "qty": int(qty) if qty is not None else None,
        "name": _clean_name(raw.get("name")),
        "raw_name": str(raw.get("name") or ""),
        "code": _norm_code(raw),
        "weight_value": value,
        "weight_unit": unit,
        "weight": raw.get("weight"),
        "price": price,
        "raw_text": str(raw.get("raw_text") or "").strip()[:160],
    }


def _line_label(line):
    txt = line.get("raw_text") or line.get("raw_name") or line.get("name") or "?"
    return str(txt)[:60]


def _bottom_verdict(top, cur):
    """
    هل السطر الحالي خيار وزن للمنتج الذي فوقه، أم منتج مستقل؟
    القاعدة: كوده فارغ أو نفس كود العلوي + تطابق الاسم ≥ 0.85 + كميته 1X.
    كود مختلف = منتج جديد قطعاً. وتشابه أقل من الحد يحتاج تأكيد «N Items».
    """
    ccode, pcode = cur.get("code"), top.get("code")
    if ccode and pcode and ccode != pcode:
        return "product", ""
    # استثناء: سطران علويان متطابقان تماماً (نفس الكود ونفس الوزن ونفس السعر)
    # هما حبتان مستقلتان من الصنف نفسه، لا سطر خيار وزن.
    same_weight = (top.get("weight_value") == cur.get("weight_value")
                   and str(top.get("weight_unit") or "") == str(cur.get("weight_unit") or ""))
    same_price = _num(top.get("price")) == _num(cur.get("price"))
    if ccode and pcode and ccode == pcode and same_weight and same_price:
        return "product", ""
    sim = _name_sim(top.get("raw_name") or top.get("name"),
                    cur.get("raw_name") or cur.get("name"))
    qty_ok = cur.get("qty") in (None, 1)
    if sim >= _NAME_SIM_MIN:
        if qty_ok:
            return "merge", ""
        return "note", ("سطر خيار وزن كميته %s وليست 1X فلم يُدمج: «%s»"
                        % (cur.get("qty"), _line_label(cur)))
    if qty_ok and _has_weight_token(cur) and not _has_weight_token(top):
        return "merge_if_count", (
            "اسم السطر السفلي مختلف (تشابه %.2f) ولا يوجد عدد منتجات للتأكيد: «%s»"
            % (sim, _line_label(cur)))
    if not ccode:
        return "note", ("سطر بلا كود R ولا يطابق اسم المنتج فوقه (تشابه %.2f): «%s»"
                        % (sim, _line_label(cur)))
    return "product", ""


def _finalize_product(top, bottom, notes):
    """سعر الحبة = العلوي + سطر الوزن. السعر الكلي = الكمية × سعر الحبة.
    الوزن الكلي = الكمية × وزن سطر الوزن. الكمية من السطر العلوي فقط."""
    qty = top.get("qty")
    if qty is None:
        qty = 1
        notes.append("كمية السطر العلوي غير مقروءة فاعتُبرت 1: «%s»" % _line_label(top))
    unit_top = top.get("price")
    unit_bottom = bottom.get("price") if bottom else None
    if unit_top is None and unit_bottom is None:
        unit_price = None
    else:
        unit_price = round((unit_top or 0) + (unit_bottom or 0), 2)
    line_total = None if unit_price is None else round(unit_price * qty, 2)

    src, src_kind = None, None
    if bottom is not None and bottom.get("weight_value") is not None:
        src, src_kind = bottom, "weight_line"
    elif bottom is None and top.get("weight_value") is not None:
        src, src_kind = top, "top_line"
    unit_weight_g = _grams(src.get("weight_value"), src.get("weight_unit")) if src else None
    total_weight_g = None if unit_weight_g is None else round(unit_weight_g * qty, 2)

    return {
        "code": top.get("code") or ((bottom or {}).get("code") if bottom else None),
        "name": top.get("name"),
        "quantity": qty,
        "weight_value": (src or {}).get("weight_value"),
        "weight_unit": (src or {}).get("weight_unit"),
        "weight": (src or {}).get("weight"),
        "weight_basis": "per_unit" if unit_weight_g is not None else None,
        "total_weight_g": total_weight_g,
        "price": unit_price,
        "line_total": line_total,
        "unit_price_top": unit_top,
        "unit_price_weight_line": unit_bottom,
        "merged_weight_line": bottom is not None,
        "weight_source": src_kind,
    }


def _assemble_products(lines, items_count):
    """
    يبني المنتجات من السطور المطبوعة حسب قواعد صاحبة النظام.
    سطر بلا كود (أو بنفس كود العلوي) تشابه اسمه ≥ 0.85 وكميته 1X = خيار وزن يُدمج.
    تشابه أقل من الحد لا يُدمج إلا إذا كان «N Items» مقروءاً ومطابقاً لعدد المنتجات بعد الدمج؛
    وإن لم يكن مقروءاً فلا دمج، ويُسجَّل السبب صريحاً (المبلغ لا يميّز الدمج في منتج 1X).
    """
    plan, notes = [], []
    i, n = 0, len(lines)
    while i < n:
        bottom_idx, tentative = None, False
        if i + 1 < n:
            verdict, note = _bottom_verdict(lines[i], lines[i + 1])
            if verdict == "merge":
                bottom_idx = i + 1
            elif verdict == "merge_if_count":
                bottom_idx, tentative = i + 1, True
                notes.append(note)
            elif verdict == "note":
                notes.append(note)
        plan.append((i, bottom_idx, tentative))
        i = (bottom_idx + 1) if bottom_idx is not None else (i + 1)

    def build(apply_tentative):
        local, prods = [], []
        for top_i, bot_i, tent in plan:
            use_bottom = bot_i is not None and (apply_tentative or not tent)
            prods.append(_finalize_product(lines[top_i], lines[bot_i] if use_bottom else None, local))
            if bot_i is not None and not use_bottom:
                prods.append(_finalize_product(lines[bot_i], None, local))
        return prods, local

    prods_with, notes_with = build(True)
    if not any(t for _, _, t in plan):
        return prods_with, notes + notes_with

    prods_without, notes_without = build(False)
    if items_count is None:
        # لا عدد منتجات مطبوع: لا دمج، والسبب يبقى ظاهراً فيسقط lines_merged_cleanly
        return prods_without, notes + notes_without
    if len(prods_with) == int(items_count):
        kept = [x for x in notes if "ولا يوجد عدد منتجات للتأكيد" not in x]
        return prods_with, kept + notes_with
    if len(prods_without) == int(items_count):
        return prods_without, notes + notes_without
    return prods_without, notes + notes_without


def _reference_sum(subtotal, delivery, delivery_printed, total):
    """مرجع أسعار المنتجات: SubTotal المطبوع، وإلا Total ناقص التوصيل المطبوع."""
    if subtotal is not None:
        return round(subtotal, 2), "subtotal"
    if total is None:
        return None, None
    if delivery is not None:
        return round(total - delivery, 2), "total_minus_delivery"
    if delivery_printed is False:
        return round(total, 2), "total_no_delivery_line"
    return None, None


def _norm_adjustments(raw):
    """خصم أو كوبون أو عرض أو أي رسوم غير التوصيل — تُنسخ كما طُبعت ولا يُقرَّر فيها شيء."""
    out = []
    for a in (raw or []):
        if isinstance(a, dict):
            label = str(a.get("label") or a.get("name") or a.get("type") or "").strip()
            amount = _num(a.get("amount") if a.get("amount") is not None else a.get("value"))
        else:
            label, amount = str(a or "").strip(), None
        if label or amount is not None:
            out.append({"label": label[:80], "amount": amount})
    return out


def normalize_result(parsed):
    # حالة فشل تفكيك JSON تمر كما هي بلا تعديل — n8n يتعامل معها كفشل تقني.
    if not isinstance(parsed, dict) or "raw_response" in parsed:
        return parsed

    raw_lines = [x for x in (_norm_raw_line(l) for l in (parsed.get("lines") or [])) if x]
    lines_source = "lines"
    if not raw_lines and parsed.get("items"):
        # توافق خلفي مع رد بالشكل القديم: تُقرأ عناصره كسطور مطبوعة وتُبنى بنفس القواعد.
        raw_lines = [x for x in (_norm_raw_line(l) for l in (parsed.get("items") or [])) if x]
        lines_source = "items_fallback"

    subtotal = _num(parsed.get("subtotal"))
    delivery = _num(parsed.get("delivery"))
    dp = parsed.get("delivery_printed")
    delivery_printed = dp if isinstance(dp, bool) else None
    printed_total = _num(parsed.get("total"))
    if printed_total is None:
        printed_total = _num(parsed.get("order_total"))
    reference, ref_basis = _reference_sum(subtotal, delivery, delivery_printed, printed_total)

    items_count = _num(parsed.get("items_count"))
    items_count = int(items_count) if items_count is not None else None

    items, merge_notes = _assemble_products(raw_lines, items_count)
    adjustments = _norm_adjustments(parsed.get("adjustments"))

    order_code = parsed.get("order_code")
    order_code = str(order_code).strip() if order_code not in (None, "", "null") else None

    field_conf = parsed.get("field_confidence") or {}
    if not isinstance(field_conf, dict):
        field_conf = {}

    platform = _norm_platform(parsed.get("platform") or parsed.get("order_source_hint"))
    branch = _norm_branch(parsed.get("branch"))

    medium = str(parsed.get("evidence_medium") or "").strip().lower()
    if medium not in _MEDIUM:
        medium = "unknown"

    # شاشة تطبيق تحضير بلا اسم شركة ولا فرع ولا مرجع مطبوع = هنجر.
    platform_source = "read" if platform != "unknown" else "none"
    if platform == "unknown" and medium == "app_screen" and branch is None and reference is None:
        platform = "hunger"
        platform_source = "inferred_medium"

    # قائمة الفاتورة كما طُبعت سطراً سطراً، بلا دمج — للتوثيق والمراجعة.
    invoice_items = [{
        "code": l.get("code"),
        "name": l.get("name"),
        "quantity": l.get("qty"),
        "unit_price": l.get("price"),
        "line_total": l.get("price"),
        "raw_text": l.get("raw_text"),
    } for l in raw_lines]

    products_sum = None
    priced = [_num(p.get("line_total")) for p in items if _num(p.get("line_total")) is not None]
    if priced:
        products_sum = round(sum(priced), 2)
    if reference is None:
        invoice_sum_check = "no_total"
    elif products_sum is not None and abs(products_sum - reference) <= _SELF_CHECK_TOL:
        invoice_sum_check = "ok"
    else:
        invoice_sum_check = "conflict"

    prepared_items = _norm_prepared_items(parsed.get("prepared_items"))
    fulfillment = _norm_fulfillment(parsed.get("fulfillment"), prepared_items)

    field_confidence = {
        "order_code": _norm_conf(field_conf.get("order_code")) if order_code else "low",
        "platform": _norm_conf(field_conf.get("platform")) if platform != "unknown" else "low",
        "branch": _norm_conf(field_conf.get("branch")) if branch else "low",
        "order_total": _norm_conf(field_conf.get("order_total")) if reference is not None else "low",
    }

    return {
        "order_code": order_code,
        "platform": platform,
        "branch": branch,
        "order_date": parsed.get("order_date") or None,
        # order_total = مرجع أسعار المنتجات (بلا توصيل) وهو ما يُقارن بفاتورة سماك.
        "order_total": reference,
        "order_total_basis": ref_basis,
        "printed_total": printed_total,
        "subtotal": subtotal,
        "delivery": delivery,
        "delivery_printed": delivery_printed,
        "adjustments": adjustments,
        "items_count": items_count,
        "products_count": len(items),
        "products_sum": products_sum,
        "currency": parsed.get("currency") or "SAR",
        "lines": raw_lines,
        "lines_source": lines_source,
        "merge_notes": merge_notes,
        "items": items,
        "evidence_medium": medium,
        "platform_source": platform_source,
        "invoice_items": invoice_items,
        "invoice_sum_check": invoice_sum_check,
        "prepared_items": prepared_items,
        "fulfillment": fulfillment,
        "order_source_hint": parsed.get("order_source_hint") or "not_applicable",
        "confidence": _norm_conf(parsed.get("confidence")),
        "field_confidence": field_confidence,
        "self_check": _self_check(order_code, platform, reference, ref_basis, items,
                                  items_count, merge_notes, invoice_sum_check,
                                  field_confidence),
    }


def analyze_with_claude(image_content_blocks: list[dict], invoice_text: str | None) -> dict:
    """
    دالة تحليل الاستجابة المشتركة بين مسار الفيديو ومسار الصورة الثابتة:
    تستقبل قائمة كتل صور (إطارات فيديو مستخرجة عبر ffmpeg، أو صورة ثابتة
    واحدة باعتبارها "إطار واحد")، وتستخدم نفس البرومبت، نفس استدعاء
    client.messages.create، ونفس منطق تفكيك رد Claude وبناء الرد النهائي
    لكلا الحالتين — بدون أي تكرار للكود.
    """
    content = list(image_content_blocks)

    prompt = (
        "أنت مساعد ذكاء اصطناعي متخصص في التحقق من طلبات التوصيل عبر تحليل فيديو فتح الطرد.\n\n"
        "مهمتك ثلاثة أشياء فقط: (1) نسخ سطور الفاتورة أو شاشة الطلب كما هي مطبوعة حرفياً، "
        "(2) نسخ المبالغ المطبوعة أسفلها كما هي، (3) وصف ما رأيته فعلاً من عبوات مادية.\n"
        "ممنوع منعاً قاطعاً: لا تدمج سطرين، ولا تضرب سعراً في كمية، ولا تجمع مبالغ، ولا تحسب "
        "إجمالياً، ولا تفسّر ولا تصحّح ما هو مطبوع. الحساب كله يجري بعدك في البرنامج. "
        "مهمتك النسخ الأمين فقط. أي قيمة غير مقروءة = null، ولا تخمين إطلاقاً.\n\n"
        "تمييز مهم بين نوعين مختلفين من الأكواد — لا تخلط بينهما أبداً:\n"
        "1) order_code (رقم الطلب الحقيقي): رقم طويل يظهر على شاشة تطبيق التوصيل أو أعلى "
        "الفاتورة المطبوعة، وليس مطبوعاً على المنتج نفسه.\n"
        "2) كود الصنف / SKU: رمز قصير (مثل R210) مطبوع على سطر المنتج في الفاتورة أو على ملصق "
        "العبوة، يعرّف الصنف لا الطلب. لا تضعه مكان order_code أبداً.\n"
        "إذا لم يظهر order_code بوضوح في أي إطار، ضع قيمته null بدلاً من تخمينه من كود صنف.\n\n"
        "نوع الدليل المصوَّر — حدّده أولاً وضعه في evidence_medium:\n"
        "- 'printed_receipt': الفيديو يعرض فاتورة ورقية مطبوعة، فيها عادةً اسم منصة التوصيل واسم الفرع "
        "وقائمة السطور ومبالغ أسفلها.\n"
        "- 'app_screen': الفيديو يعرض شاشة تطبيق تحضير الطلبات على جوال أو جهاز لوحي — قائمة طلبات، "
        "بطاقات منتجات بصور، تبويبات مثل To pick / Picked / Not Found — ولا توجد فاتورة ورقية.\n"
        "- 'unknown': لا هذا ولا ذاك.\n"
        "قاعدة إلزامية: إذا كان evidence_medium = 'app_screen' ولم يظهر اسم شركة توصيل ولا اسم فرع ولا "
        "مبالغ مطبوعة، فالمنصة هي hunger — ضع platform = 'hunger' ولا تضع unknown.\n\n"
        "حقول على مستوى الطلب:\n"
        "- platform: من شعار التطبيق أو الاسم الظاهر فقط. القيم المسموحة: "
        "keeta | jahez | hunger | ninja | thechefz | marsool | toyou | unknown. "
        "لا تستنتج المنصة من شكل رقم الطلب إطلاقاً.\n"
        "- branch: الفرع أو المخزن الظاهر. القيم المتوقعة: Al Masiaf أو Al Wisham أو Al Khaleej "
        "أو Al Yasmin أو Dhahrat Laban، أو رمز المخزن من 0001 إلى 0005، أو null.\n"
        "- order_date: تاريخ الطلب بصيغة YYYY-MM-DD إن ظهر، وإلا null.\n"
        "- items_count: الرقم المطبوع في سطر مثل '3 Items' أو '2 أصناف' أعلى قائمة السطور، كرقم "
        "صحيح كما هو مطبوع. هذا عدد المنتجات لا عدد الحبات. null إن لم يُطبع.\n\n"
        "«lines» — قلب المهمة: انسخ كل سطر مطبوع في قائمة الطلب سطراً سطراً بالترتيب من أعلى إلى "
        "أسفل، بلا حذف ولا دمج ولا إعادة ترتيب. لكل سطر:\n"
        "- qty: الرقم المطبوع في بداية السطر (2X تعني 2، و1X تعني 1)، رقم صحيح، أو null إن لم يُطبع.\n"
        "- name: نص اسم الصنف في هذا السطر كما هو مطبوع.\n"
        "- code: كود R المطبوع في هذا السطر تحديداً (R253، وقد يظهر بالعربية ر253 أو داخل أقواس — "
        "طبّعه إلى R253). null إن لم يُطبع كود في هذا السطر بذاته. لا تنقل كود سطر إلى سطر آخر.\n"
        "- weight: الوزن أو الحجم المطبوع في هذا السطر نصياً كما هو ('500g'، '250 جرام'، '1kg')، "
        "أو null إن لم يُطبع وزن في هذا السطر.\n"
        "- price: المبلغ المطبوع في نهاية هذا السطر كرقم بلا رمز عملة (قد يكون 0.00 وهذا يُنسخ كما "
        "هو ولا يُهمَل)، أو null إن لم يُطبع مبلغ.\n"
        "- raw_text: السطر كما هو مطبوع نصاً كاملاً، للمراجعة.\n"
        "ملاحظة: فواتير المنصات تطبع كثيراً من المنتجات على سطرين متتاليين (سطر بالاسم والكود "
        "والسعر، وتحته سطر مُزاح فيه الوزن وسعر إضافي قد يكون 0.00). انسخهما سطرين منفصلين كما "
        "هما — البرنامج هو من يربطهما. لا تدمجهما أنت ولا تُسقط أحدهما.\n\n"
        "«المبالغ أسفل القائمة» — انسخها كما طُبعت، كل واحد في حقله:\n"
        "- subtotal: المبلغ المطبوع أمام SubTotal أو Sub Total أو المجموع، أو null إن لم يُطبع.\n"
        "- delivery: المبلغ المطبوع أمام Delivery أو Delivery Fee أو توصيل أو رسوم توصيل، "
        "أو null إن لم يُطبع سطر توصيل أو تعذّرت قراءة مبلغه.\n"
        "- delivery_printed: true إذا كان في الفاتورة سطر توصيل (حتى لو لم تُقرأ قيمته)، "
        "و false إذا لم يوجد سطر توصيل إطلاقاً.\n"
        "- total: المبلغ المطبوع أمام Total أو الإجمالي، أو null إن لم يُطبع.\n"
        "- adjustments: قائمة بكل سطر مبلغ آخر ليس منتجاً وليس توصيلاً — خصم، كوبون، عرض، "
        "Promo، Discount، Voucher، أو أي رسوم أخرى. لكل واحد: label كما طُبع نصاً، و amount "
        "كرقم كما طُبع (بإشارته إن كانت سالبة). قائمة فارغة إن لم يوجد شيء من هذا. "
        "لا تُدرج التوصيل هنا، ولا تُدرج SubTotal ولا Total.\n"
        "لا تجمع هذه المبالغ ولا تطرحها من شيء — انسخها فقط.\n\n"
        "«prepared_items» — ما رأيته فعلاً من عبوات مادية محضّرة في الفيديو. لكل صنف رأيت عبوته: "
        "code من ملصقها، name من ملصقها، seen_count = عدد العبوات المتطابقة التي رأيتها من هذا "
        "الصنف، و label_weight كما هو مطبوع على الملصق نصياً.\n"
        "ممنوع منعاً قاطعاً: لا تُدرج صنفاً لم ترَ عبوته فعلاً في إطار من الإطارات، حتى لو كان "
        "مذكوراً في الفاتورة، وحتى لو كان وجوده منطقياً. prepared_items شهادة بصرية لا استنتاج. "
        "وبالمقابل، إذا رأيت عبوة لصنف غير مذكور في الفاتورة فأدرجها كما هي.\n"
        "الأصناف بدون ملصق واضح: تعرّف عليها بصرياً وطابقها مع أي كتالوج مصوّر أو ورقة أصناف نصية "
        "تظهر في الفيديو نفسه، وسجّل في order_source_hint ما استخدمته: 'image_catalog' أو "
        "'text_list' أو 'mixed' أو 'not_applicable'. إن تعذّر التطابق بثقة فاذكر وصفاً مختصراً "
        "بدل اختلاق كود.\n\n"
        "«fulfillment» — مقارنتك بين ما طُلب وما رأيته محضّراً:\n"
        "- coverage: 'full' إذا أظهر الفيديو كل العبوات المحضّرة بوضوح يكفي للحكم، 'partial' إذا "
        "أظهر بعضها فقط، 'none' إذا لم يُظهر أي عبوة بوضوح.\n"
        "- verdict: 'matched' أو 'mismatch' أو 'not_verifiable'.\n"
        "- lines: سطر لكل كود ظهر في أي من الجانبين، فيه code و status و note مختصرة. قيم status: "
        "'matched' مطلوب ورأيته محضّراً بنفس العدد والوزن؛ 'missing' مطلوب ولم أره وأنا واثق لأن "
        "الفيديو أظهر كل ما جُهِّز؛ 'extra' رأيت عبوة لصنف غير مطلوب؛ 'weight_diff' موجود في "
        "الجانبين لكن وزن الملصق يخالف وزن السطر؛ 'not_seen' مطلوب ولم أستطع رؤيته بوضوح كافٍ.\n"
        "القاعدة الحاسمة: لا تستخدم 'missing' إلا إذا كان coverage = 'full'. في أي شك استخدم "
        "'not_seen'. الفرق جوهري: 'missing' اتهام للموظف، و'not_seen' اعتراف بأن الصورة لم تكفِ.\n\n"
        "مهم بخصوص الأسعار: شاشة تفاصيل الطلب التي تُظهر الأسعار قد تظهر في إطار واحد فقط من كل "
        "الإطارات (في البداية أو الوسط أو النهاية). قبل أن تضع price أو المبالغ بـ null، افحص كل "
        "إطار مرفق واحداً تلو الآخر بحثاً عن سطور الطلب والمبالغ.\n\n"
        "وأخيراً field_confidence: درجة ثقتك في كل حقل حرج على حدة (high أو medium أو low). "
        "أي حقل وضعت قيمته null يجب أن تكون ثقته low. حقل order_total هنا يعني ثقتك في المبالغ "
        "المطبوعة أسفل القائمة (subtotal/total).\n\n"
        "أعد النتيجة بصيغة JSON فقط بدون أي نص إضافي، وفق الحقول التالية بالضبط:\n"
        '{"order_code": "رقم الطلب أو null", '
        '"platform": "keeta|jahez|hunger|ninja|thechefz|marsool|toyou|unknown", '
        '"branch": "اسم الفرع أو رمز المخزن أو null", '
        '"order_date": "YYYY-MM-DD أو null", '
        '"items_count": "الرقم المطبوع في سطر N Items أو null", '
        '"lines": [{"qty": "الرقم في بداية السطر أو null", '
        '"name": "اسم الصنف كما هو مطبوع في هذا السطر", '
        '"code": "R253 أو null إن لم يُطبع في هذا السطر", '
        '"weight": "الوزن المطبوع في هذا السطر نصياً أو null", '
        '"price": "المبلغ في نهاية السطر كرقم أو null", '
        '"raw_text": "السطر كما هو مطبوع"}], '
        '"subtotal": "المبلغ أمام SubTotal أو null", '
        '"delivery": "المبلغ أمام Delivery أو null", '
        '"delivery_printed": "true أو false", '
        '"total": "المبلغ أمام Total أو null", '
        '"adjustments": [{"label": "نص السطر كما طُبع", "amount": "المبلغ كرقم أو null"}], '
        '"evidence_medium": "printed_receipt|app_screen|unknown", '
        '"prepared_items": [{"code": "كود R من الملصق أو null", "name": "الاسم من الملصق", '
        '"seen_count": "عدد العبوات التي رأيتها من هذا الصنف", "label_weight": "الوزن المطبوع على الملصق أو null"}], '
        '"fulfillment": {"coverage": "full|partial|none", "verdict": "matched|mismatch|not_verifiable", '
        '"lines": [{"code": "...", "status": "matched|missing|extra|weight_diff|not_seen", "note": "سبب مختصر أو null"}]}, '
        '"order_source_hint": "image_catalog|text_list|mixed|not_applicable", '
        '"confidence": "high|medium|low", '
        '"field_confidence": {"order_code": "high|medium|low", "platform": "high|medium|low", '
        '"branch": "high|medium|low", "order_total": "high|medium|low"}}'
    )
    if invoice_text:
        prompt += (
            "\n\nنص فاتورة مرجعية للمقارنة. استخدمه للتحقق من invoice_items فقط. "
            "يُمنع منعاً قاطعاً استخدامه في بناء prepared_items أو في الحكم على fulfillment — "
            "هاتان يجب أن تبقيا شهادة بصرية مستقلة عمّا هو مفترض:\n"
            f"{invoice_text}"
        )

    content.append({"type": "text", "text": prompt})

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        temperature=0,
        messages=[{"role": "user", "content": content}]
    )

    raw = msg.content[0].text.strip()

    extracted = extract_first_json_object(raw)
    if extracted is not None:
        raw = extracted

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"raw_response": raw}

    return {"status": "ok", "result": normalize_result(parsed)}

@app.post("/verify-order")
def verify_order(req: VerifyRequest):
    with tempfile.TemporaryDirectory() as tmp:
        input_path = f"{tmp}/input_file"
        with httpx.stream("GET", req.video_url, follow_redirects=True) as r:
            with open(input_path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)

        kind, image_media_type = detect_input_kind(req.video_url, input_path)

        if kind == "image":
            # مسار الصورة الثابتة الجديد: نتجاوز ffmpeg بالكامل ونرسل الصورة
            # نفسها مباشرة لـ Claude API (نفس analyze_with_claude المستخدمة
            # لإطارات الفيديو)، باعتبارها "إطار واحد" بدل 30 إطار.
            try:
                img_b64 = base64.b64encode(Path(input_path).read_bytes()).decode()
                image_content = [{
                    "type": "image",
                    "source": {"type": "base64", "media_type": image_media_type, "data": img_b64}
                }]
                return analyze_with_claude(image_content, req.invoice_text)
            except Exception:
                return {
                    "status": "extraction_failed",
                    "result": None,
                    "error": "فشل تحليل الصورة المرسلة، يحتاج مراجعة يدوية"
                }

        # المسار الحالي لمعالجة الفيديو — بدون أي تغيير في المنطق (ffmpeg
        # يستخرج الإطارات، ثم Claude API يحللها بنفس البرومبت الحالي).
        duration = probe_duration(input_path)
        try:
            if duration:
                selected_frames = extract_frames_at(
                    input_path, tmp, frame_timestamps(duration, 40)
                )
            else:
                selected_frames = select_frames_covering_full_video(
                    extract_frames(input_path, tmp), max_frames=40
                )
        except FFmpegExtractionError:
            return {
                "status": "extraction_failed",
                "result": None,
                "error": "فشل استخراج إطارات الفيديو تقنياً (ffmpeg)، يحتاج مراجعة يدوية"
            }
        if not selected_frames:
            return {"status": "error", "reason": "no_frames_extracted"}

        content = []
        for fp in selected_frames:
            img_b64 = base64.b64encode(fp.read_bytes()).decode()
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}
            })

        return analyze_with_claude(content, req.invoice_text)

@app.get("/health")
def health():
    return {"status": "ok"}

