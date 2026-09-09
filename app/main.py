import os, re, subprocess, tempfile, base64, json
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
_ORDER_CODE_LEN = {"hunger": (10,), "keeta": (16,), "ninja": (9,), "jahez": (10,)}

# سماحية مطابقة مجموع البنود مع الإجمالي المطبوع (ريال).
_SELF_CHECK_TOL = 0.05


def _self_check(order_code, platform, order_total, items, invoice_sum_check, field_conf):
    """
    فحص ذاتي حسابي بحت على القراءة نفسها — لا يحكم على الطلب ولا على الموظف،
    بل يقول: هل هذه القراءة موثوقة بما يكفي لتُقارَن بفاتورة سماك؟
    كل فحص يُرجع {id, ok, detail}. passed = False إذا سقط أي فحص واحد.
    """
    checks = []

    def add(cid, ok, detail=""):
        checks.append({"id": cid, "ok": bool(ok), "detail": detail if not ok else ""})

    # 1) الإجمالي المطبوع مقروء
    add("total_read", order_total is not None, "لم يُقرأ إجمالي الطلب")

    # 2) مجموع أسطر البنود = الإجمالي المطبوع
    priced = [i for i in items if _num(i.get("line_total")) is not None]
    if order_total is None:
        add("sum_matches_total", False, "لا إجمالي مطبوع للمقارنة")
    elif not priced:
        add("sum_matches_total", False, "لا سعر مقروء لأي بند")
    else:
        line_sum = round(sum(_num(i.get("line_total")) for i in priced), 2)
        diff = round(abs(line_sum - order_total), 2)
        add("sum_matches_total", diff <= _SELF_CHECK_TOL,
            "مجموع البنود %s لا يساوي الإجمالي %s (فارق %s)" % (line_sum, order_total, diff))

    # 3) قُرئ سعر بند واحد على الأقل
    add("any_price", bool(priced), "لم يُقرأ سعر أي بند")

    # 4) كل بند يحمل كود R
    if not items:
        add("all_codes", False, "لم يُقرأ أي بند")
    else:
        no_code = [i for i in items if not i.get("code")]
        add("all_codes", not no_code, "%d بند بلا كود R" % len(no_code))

    # 5) كل بند له وزن إجمالي مقروء
    if not items:
        add("all_weights", False, "لم يُقرأ أي بند")
    else:
        no_weight = [i for i in items if i.get("total_weight_g") is None]
        add("all_weights", not no_weight,
            "بنود بلا وزن: " + "، ".join((i.get("code") or i.get("name") or "?") for i in no_weight))

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
        order_total is not None and _norm_conf(field_conf.get("order_total")) == "high",
        "ثقة الإجمالي %s وليست high" % _norm_conf(field_conf.get("order_total")))

    # 8) قائمتا الفاتورة (items و invoice_items) تتفقان مع الإجمالي المطبوع
    add("invoice_lists_agree", invoice_sum_check != "conflict",
        "قائمتا الفاتورة لا تتفقان مع الإجمالي المطبوع")

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


def _is_weight_variant_line(prev, cur, code_key, name_key, weight_key, price_keys):
    """
    هل السطر الحالي متغيّر وزن للسطر الذي قبله مباشرة، لا صنفاً مستقلاً؟
    فواتير المنصات تطبع كل منتج بسطرين: سطر علوي بالاسم والكود والسعر الأساسي،
    وتحته سطر مُزاح فيه الوزن وسعر فرق الوزن. السطران منتج واحد.
    """
    if not prev or not cur:
        return False

    pcode = (prev.get(code_key) or "").strip()
    ccode = (cur.get(code_key) or "").strip()
    if ccode and pcode and ccode != pcode:
        return False

    pname_raw = str(prev.get(name_key) or "")
    cname_raw = str(cur.get(name_key) or "")
    pname, cname = _name_key(pname_raw), _name_key(cname_raw)

    # العلامة الحاسمة: السطر السفلي يذكر وزناً والعلوي لا يذكره — هذا متغيّر وزن لا تكرار
    variant_signal = bool(_WEIGHT_TOKEN.search(cname_raw)) and not bool(_WEIGHT_TOKEN.search(pname_raw))

    # تكرار حقيقي لا متغيّر وزن: سطران متطابقان تماماً بلا علامة الوزن — قطعتان مستقلتان
    same_weight = str(prev.get(weight_key) or "") == str(cur.get(weight_key) or "")
    same_price = all(_num(prev.get(k)) == _num(cur.get(k)) for k in price_keys)
    if pname == cname and same_weight and same_price and not variant_signal:
        return False

    if ccode and pcode and ccode == pcode:
        return True
    if ccode and not pcode:
        # الكود ظهر على السطر السفلي وحده: يُدمج فقط بدليل قوي (وزن + تطابق اسم)
        return bool(variant_signal and pname and cname and (cname in pname or pname in cname))
    # السطر السفلي بلا كود: يُربط بالتجاور والتطابق الجزئي بالاسم أو بكونه وزناً فقط
    if not cname:
        return True
    if _WEIGHT_ONLY.match(cname_raw.strip()):
        return True
    if pname and cname and (cname in pname or pname in cname):
        return True
    return False


def _merge_weight_variant_lines(rows, code_key="code", name_key="name",
                                weight_key="weight", price_keys=("line_total", "price")):
    """يدمج كل سطر متغيّر وزن مع السطر الذي قبله: الاسم من الأعلى، الوزن من الأسفل، والسعر مجموعهما."""
    merged = []
    for cur in rows:
        prev = merged[-1] if merged else None
        if not _is_weight_variant_line(prev, cur, code_key, name_key, weight_key, price_keys):
            merged.append(dict(cur))
            continue
        for k in price_keys:
            a, b = _num(prev.get(k)), _num(cur.get(k))
            if a is None and b is None:
                continue
            prev[k] = round((a or 0) + (b or 0), 2)
        if not (prev.get(code_key) or "").strip() and (cur.get(code_key) or "").strip():
            prev[code_key] = cur[code_key]
        for k in (weight_key, "weight_value", "weight_unit", "total_weight_value",
                  "total_weight_unit", "weight_basis"):
            if cur.get(k) not in (None, "") and k in cur:
                prev[k] = cur[k]
        prev["_merged_variant"] = True
    return merged


def normalize_result(parsed):
    # حالة فشل تفكيك JSON تمر كما هي بلا تعديل — n8n يتعامل معها كفشل تقني.
    if not isinstance(parsed, dict) or "raw_response" in parsed:
        return parsed

    items = []
    raw_items = _merge_weight_variant_lines(
        [x for x in (parsed.get("items") or []) if isinstance(x, dict)]
    )
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        weight_value, weight_unit = _norm_weight(raw_item)
        line_total = _num(raw_item.get("line_total"))
        unit_price = _num(raw_item.get("price"))
        quantity = _num(raw_item.get("quantity"))
        quantity = int(quantity) if quantity is not None else None
        if line_total is None and unit_price is not None:
            line_total = round(unit_price * (quantity or 1), 2)

        basis = str(raw_item.get("weight_basis") or "").strip().lower()
        if basis not in ("per_unit", "line_total"):
            basis = None

        total_value, total_unit = _norm_weight({
            "weight_value": raw_item.get("total_weight_value"),
            "weight_unit": raw_item.get("total_weight_unit"),
            "weight": None,
        })
        total_weight_g = _grams(total_value, total_unit)
        unit_weight_g = _grams(weight_value, weight_unit)
        if total_weight_g is None and unit_weight_g is not None:
            if basis == "line_total":
                total_weight_g = unit_weight_g
            else:
                total_weight_g = round(unit_weight_g * (quantity or 1), 2)

        items.append({
            "code": _norm_code(raw_item),
            "name": _clean_name(raw_item.get("name")),
            "quantity": quantity,
            "weight_value": weight_value,
            "weight_unit": weight_unit,
            "weight": raw_item.get("weight"),
            "weight_basis": basis,
            "total_weight_g": total_weight_g,
            "price": unit_price,
            "line_total": line_total,
        })

    order_code = parsed.get("order_code")
    order_code = str(order_code).strip() if order_code not in (None, "", "null") else None

    field_conf = parsed.get("field_confidence") or {}
    if not isinstance(field_conf, dict):
        field_conf = {}

    platform = _norm_platform(parsed.get("platform") or parsed.get("order_source_hint"))
    branch = _norm_branch(parsed.get("branch"))
    order_total = _num(parsed.get("order_total"))

    medium = str(parsed.get("evidence_medium") or "").strip().lower()
    if medium not in _MEDIUM:
        medium = "unknown"

    # شاشة تطبيق تحضير بلا اسم شركة ولا فرع ولا إجمالي مطبوع = هنجر.
    # يُعلَّم مصدر المنصة حتى يعرف n8n أنها استنتاج من نوع الدليل لا قراءة مباشرة.
    platform_source = "read" if platform != "unknown" else "none"
    if platform == "unknown" and medium == "app_screen" and branch is None and order_total is None:
        platform = "hunger"
        platform_source = "inferred_medium"

    invoice_items = _norm_invoice_items(_merge_weight_variant_lines(
        [x for x in (parsed.get("invoice_items") or []) if isinstance(x, dict)],
        price_keys=("line_total", "unit_price"),
    ))
    invoice_items, invoice_sum_check = _reconcile_invoice_items(
        invoice_items, items, order_total)
    prepared_items = _norm_prepared_items(parsed.get("prepared_items"))
    fulfillment = _norm_fulfillment(parsed.get("fulfillment"), prepared_items)

    field_confidence = {
        "order_code": _norm_conf(field_conf.get("order_code")) if order_code else "low",
        "platform": _norm_conf(field_conf.get("platform")) if platform != "unknown" else "low",
        "branch": _norm_conf(field_conf.get("branch")) if branch else "low",
        "order_total": _norm_conf(field_conf.get("order_total")) if order_total else "low",
    }

    return {
        "order_code": order_code,
        "platform": platform,
        "branch": branch,
        "order_date": parsed.get("order_date") or None,
        "order_total": order_total,
        "currency": parsed.get("currency") or "SAR",
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
        "self_check": _self_check(order_code, platform, order_total, items,
                                  invoice_sum_check, field_confidence),
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
        "مهمتك: تحليل الإطارات المرفقة من الفيديو لاستخراج معلومات الطلب والتحقق من الأصناف، "
        "ومقارنتها بنص الفاتورة إن توفر.\n\n"
        "تمييز مهم بين نوعين مختلفين من الأكواد — لا تخلط بينهما أبداً:\n"
        "1) order_code (رقم الطلب الحقيقي): رقم طويل عادة من 9 إلى 10 خانات، يظهر على شاشة "
        "تطبيق التوصيل (شاشة جوال المندوب أو تطبيق الطلبات)، وليس مطبوعاً على المنتج نفسه. "
        "ابحث عنه فقط في الإطارات التي تُظهر شاشة جوال/تطبيق.\n"
        "2) كود الصنف / SKU: رمز قصير (مثل R210) مطبوع على ملصق المنتج أو التغليف، يعرّف "
        "الصنف وليس الطلب. لا تضع كود الصنف مكان order_code أبداً حتى لو كان هو الرقم الوحيد "
        "الظاهر بوضوح في بعض الإطارات.\n"
        "إذا لم يظهر order_code بوضوح في أي إطار، ضع قيمته null بدلاً من تخمينه من كود صنف.\n\n"
        "الأصناف بدون ملصق واضح:\n"
        "إذا ظهر صنف بدون ملصق مقروء أو بدون كود صنف واضح، تعرّف عليه بصرياً (الشكل، اللون، "
        "التغليف، الحجم) وطابقه مع أي كتالوج مصوّر أو ورقة أصناف نصية تظهر في الفيديو نفسه، إن "
        "وُجدت. إذا تعذّر التطابق بثقة، أدرج الصنف بوصف مختصر لما تراه بدل اختلاق كود له.\n"
        "سجّل في order_source_hint أي مرجع استخدمته للتعرف على الأصناف بدون ملصق واضح:\n"
        "- 'image_catalog' إذا اعتمدت على كتالوج صور ظاهر بالفيديو\n"
        "- 'text_list' إذا اعتمدت على ورقة نصية بأسماء/أكواد الأصناف ظاهرة بالفيديو\n"
        "- 'mixed' إذا استخدمت الاثنين معاً لأصناف مختلفة\n"
        "- 'not_applicable' إذا كانت كل الأصناف عليها ملصق واضح ولم تحتج مرجعاً بديلاً\n\n"
        "تفاصيل إضافية مطلوبة لكل صنف على حدة:\n"
        "- weight: الوزن أو الحجم المطبوع على ملصق العبوة نفسها فقط، كما يظهر نصياً بالضبط "
        "(مثال: '250 جرام'، '1 كيلو'). استخرجه من الملصق فقط، وضع null إذا لم يظهر وزن/حجم "
        "واضح ومقروء على العبوة.\n"
        "- price: سعر هذا الصنف تحديداً كما يظهر على شاشة تطبيق التوصيل (شاشة تفاصيل الطلب "
        "في الفيديو) — وليس من ملصق العبوة أو من أي مصدر آخر. ضع الرقم فقط بدون رمز العملة "
        "إذا ظهر بوضوح مرتبطاً بهذا الصنف تحديداً، أو null إذا لم يظهر سعر فردي واضح لهذا "
        "الصنف على شاشة التطبيق.\n"
        "لا تخمّن أي قيمة وزن أو سعر غير ظاهرة بوضوح — استخدم null دائماً بدل التخمين.\n\n"
        "مهم جداً بخصوص السعر تحديداً: شاشة تطبيق التوصيل التي تُظهر سعر كل صنف قد لا تظهر "
        "إلا في إطار واحد فقط من بين كل الإطارات المرفقة لك (قد تكون في بداية الفيديو أو "
        "وسطه أو آخره)، بينما تُظهر بقية الإطارات فتح الطرد أو ملصقات المنتجات. لذلك قبل أن "
        "تضع price كـ null لأي صنف، افحص كل إطار مرفق لك بالكامل، واحداً تلو الآخر، بحثاً عن "
        "شاشة تفاصيل الطلب — ولا تكتفِ بفحص أول إطار أو آخر إطار فقط. عدم ظهور شاشة السعر في "
        "الإطارات الأولى لا يعني إطلاقاً عدم وجودها في إطار لاحق.\n\n"
        "نوع الدليل المصوَّر — حدّده أولاً قبل أي استخراج، وضعه في evidence_medium:\n"
        "- 'printed_receipt': الفيديو يعرض فاتورة ورقية مطبوعة، فيها عادةً اسم منصة التوصيل واسم الفرع "
        "وقائمة الأصناف وسطر إجمالي (Total).\n"
        "- 'app_screen': الفيديو يعرض شاشة تطبيق تحضير الطلبات على جوال أو جهاز لوحي — قائمة طلبات، "
        "بطاقات منتجات بصور، تبويبات مثل To pick / Picked / Not Found — ولا توجد فاتورة ورقية.\n"
        "- 'unknown': لا هذا ولا ذاك.\n"
        "قاعدة إلزامية: إذا كان evidence_medium = 'app_screen' ولم يظهر اسم شركة توصيل ولا اسم فرع ولا "
        "إجمالي مطبوع للطلب، فالمنصة هي hunger — ضع platform = 'hunger' ولا تضع unknown.\n\n"
        "حقول إضافية مطلوبة على مستوى الطلب ككل — استخرجها من شاشة تطبيق التوصيل:\n"
        "- platform: المنصة التي جاء منها الطلب، من شعار التطبيق أو اسمه الظاهر على الشاشة. "
        "القيم المسموحة فقط: keeta | jahez | hunger | ninja | thechefz | marsool | toyou | unknown. "
        "لا تستنتج المنصة من شكل رقم الطلب إطلاقاً — فقط من الشعار أو الاسم الظاهر بالفيديو.\n"
        "- branch: الفرع أو المخزن الظاهر على الملصق أو الشاشة. القيم المتوقعة: "
        "Al Masiaf أو Al Wisham أو Al Khaleej أو Al Yasmin أو Dhahrat Laban، أو رمز المخزن "
        "من 0001 إلى 0005، أو null إن لم يظهر.\n"
        "- order_date: تاريخ الطلب بصيغة YYYY-MM-DD إن ظهر، وإلا null.\n"
        "- order_total: الإجمالي النهائي للطلب كما هو مطبوع على شاشة تفاصيل الطلب شاملاً الضريبة، "
        "رقم فقط بدون رمز العملة. لا تحسبه بنفسك بجمع الأصناف — استخرجه كما هو مطبوع، وضع null "
        "إن لم يظهر إجمالي واضح.\n\n"
        "حقول إضافية مطلوبة لكل صنف على حدة:\n"
        "- code: كود الصنف بصيغة حرف R متبوعاً برقم مثل R253. قد يظهر بالعربية (ر253) أو داخل "
        "أقواس — طبّعه دائماً إلى الصيغة R253. ضع null إن لم يظهر كود على الملصق.\n"
        "- quantity: عدد القطع من هذا الصنف كرقم صحيح. انتبه جيداً: الكمية غير الوزن. صنف وزن "
        "عبوته 250 جرام وعدد قطعه اثنتان يكون quantity = 2 و weight_value = 250. ضع null إن لم "
        "يظهر العدد.\n"
        "- weight_value و weight_unit: نفس الوزن المذكور أعلاه لكن مفصولاً — رقم مجرد بلا وحدة "
        "في weight_value، والوحدة في weight_unit بقيمة g أو kg فقط.\n"
        "- ربط الوزن بالصنف الصحيح: خذ الوزن من ملصق عبوة هذا الصنف نفسه فقط. إذا ظهرت في "
        "الفيديو عدة عبوات ولم تجزم بأن الوزن الذي تراه يخص هذا الصنف تحديداً، ضع weight_value "
        "و total_weight_value بقيمة null. لا تنسب وزن عبوة إلى صنف آخر إطلاقاً، ولا تخمّن وزناً "
        "من اسم الصنف أو من سعره.\n"
        "- weight_basis: ماذا يمثل الوزن الذي استخرجته؟ 'per_unit' إذا كان وزن العبوة الواحدة "
        "من هذا الصنف، أو 'line_total' إذا كان الوزن المطبوع يمثل كامل كمية هذا السطر مجتمعة "
        "(عبوة واحدة مجمّعة، أو وزن إجمالي مكتوب للسطر). ضع null إن لم يظهر وزن.\n"
        "- total_weight_value و total_weight_unit: الوزن الإجمالي لهذا السطر بكامل كميته. إذا "
        "كان weight_basis = 'per_unit' فاضرب وزن العبوة الواحدة في الكمية (مثال: قطعتان وزن "
        "كل عبوة 200 جرام يعني total_weight_value = 400 و total_weight_unit = g). وإذا كان "
        "'line_total' فانقل الوزن كما هو بلا ضرب. ضع null إن لم يظهر وزن.\n"
        "- line_total: إجمالي هذا السطر شاملاً الضريبة. إذا كان الظاهر سعر القطعة الواحدة فقط "
        "فاضربه في الكمية. ضع null إن تعذّر.\n\n"
        "بنية السطرين للصنف الواحد في فواتير المنصات (جاهز/كيتا/بلند) — انتبه لها جيداً:\n"
        "كل منتج يُطبع على سطرين متتاليين: سطر علوي بارز فيه العدد واسم المنتج وكود R وسعر أساسي، "
        "وتحته مباشرة سطر مُزاح للداخل يحمل متغيّر الوزن (500g أو 250g أو 1kg…) وسعر فرق الوزن. "
        "السطران منتج واحد لا منتجان، والسعر الفعلي للصنف = مجموع سعري السطرين.\n"
        "مثال حقيقي من فاتورة جاهز ترويستها '3 Items' ومجموعها 134.92:\n"
        "  1X Japanese Mixed Nuts R76          29.98\n"
        "     1X Japanese mixed nuts R76 500g  29.98   <- نفس الصنف، فرق وزن\n"
        "  1X Japanese Nuts R514               29.98\n"
        "     1X 500g Japanese nuts R514       29.98   <- الوزن قبل الاسم هنا\n"
        "  1X Natural Plant Sugar R138         15.00\n"
        "     1X Natural Plant Sugar 250g       0.00   <- فرق الوزن صفر\n"
        "النتيجة الصحيحة ثلاثة أصناف: R76 بـ59.96 و R514 بـ59.96 و R138 بـ15.00، ومجموعها 134.92.\n"
        "القواعد:\n"
        "- ادمج السطرين في عنصر واحد: الاسم من السطر العلوي، والوزن من السطر السفلي، والسعر مجموع السعرين.\n"
        "- إذا كان سعر السطر السفلي 0.00 فالسعر النهائي هو سعر السطر العلوي وحده.\n"
        "- لا تعتمد على كود R وحده للربط: بعض الأسطر السفلية لا تحمل الكود إطلاقاً، وبعضها يضع الوزن "
        "قبل الاسم. اعتمد أيضاً على التجاور (السطر التالي مباشرة والمُزاح للداخل) وعلى التطابق الجزئي بالاسم.\n"
        "- لا تُنشئ عنصرين منفصلين، ولا تُسقط السطر السفلي، ولا تعدّه كمية إضافية.\n"
        "- سطر 'N Items' أعلى القائمة يساوي عدد الأصناف بعد الدمج — استخدمه للتحقق من عددها.\n"
        "- تحقّق أخيراً: مجموع أسعار الأصناف بعد الدمج يجب أن يساوي SubTotal/Total المطبوع. إن لم يساوِه "
        "فراجع الدمج قبل إخراج النتيجة.\n"
        "- استثناء: سطران متطابقان تماماً (نفس الاسم ونفس الوزن ونفس السعر) هما قطعتان مستقلتان من "
        "الصنف نفسه، لا متغيّر وزن — اجمع كميتهما ولا تعاملهما معاملة السطرين أعلاه.\n\n"
        "مطلوب منك بعد ذلك قائمتان مستقلتان تماماً — لا تدمجهما ولا تدع إحداهما تؤثر في الأخرى:\n"
        "1) invoice_items — ما طلبه العميل كما هو مكتوب على الفاتورة الورقية أو شاشة تطبيق الطلبات فقط. "
        "لكل سطر: name كما هو مكتوب، quantity، unit_price، line_total، و code إن كان كود R مطبوعاً على "
        "الفاتورة نفسها (كثير من الفواتير لا تطبعه — ضع null حينها). لا تأخذ شيئاً هنا من ملصقات العبوات.\n"
        "invoice_items و items قراءتان لنفس الفاتورة: يجب أن تتطابقا بنداً ببند بعد دمج "
        "أسطر متغيّر الوزن — نفس الأكواد ونفس الأسعار — ومجموع line_total في كلٍّ منهما "
        "يجب أن يساوي order_total المطبوع. راجع الجمع قبل أن ترد.\n"
        "2) prepared_items — ما رأيته فعلاً من عبوات مادية محضّرة في الفيديو. لكل صنف رأيت عبوته: code من "
        "ملصقها، name من ملصقها، seen_count = عدد العبوات المتطابقة التي رأيتها من هذا الصنف، و label_weight "
        "كما هو مطبوع على الملصق نصياً.\n"
        "ممنوع منعاً قاطعاً: لا تُدرج في prepared_items أي صنف لم ترَ عبوته فعلاً في إطار من الإطارات، حتى "
        "لو كان مذكوراً في الفاتورة، وحتى لو كان وجوده منطقياً. prepared_items شهادة بصرية لا استنتاج. "
        "وبالمقابل، إذا رأيت عبوة لصنف غير مذكور في الفاتورة فأدرجها كما هي.\n"
        "3) fulfillment — مقارنتك بين القائمتين:\n"
        "- coverage: 'full' إذا أظهر الفيديو كل العبوات المحضّرة بوضوح يكفي للحكم، 'partial' إذا أظهر "
        "بعضها فقط، 'none' إذا لم يُظهر أي عبوة بوضوح.\n"
        "- verdict: 'matched' أو 'mismatch' أو 'not_verifiable'.\n"
        "- lines: سطر لكل كود ظهر في أي من القائمتين، فيه code و status و note مختصرة. قيم status:\n"
        "  'matched' موجود بالفاتورة ورأيته محضّراً بنفس العدد والوزن؛ 'missing' بالفاتورة ولم أره وأنا "
        "واثق لأن الفيديو أظهر كل ما جُهِّز؛ 'extra' رأيت عبوة لصنف ليس بالفاتورة؛ 'weight_diff' موجود في "
        "الاثنين لكن وزن الملصق يخالف وزن الفاتورة؛ 'not_seen' بالفاتورة ولم أستطع رؤيته بوضوح كافٍ للحكم.\n"
        "القاعدة الحاسمة: لا تستخدم 'missing' إلا إذا كان coverage = 'full' وكنت متأكداً أن الفيديو عرض كل "
        "ما جُهِّز. في أي حالة شك استخدم 'not_seen'. الفرق بينهما جوهري: 'missing' اتهام للموظف، "
        "و'not_seen' اعتراف بأن الصورة لم تكفِ. الاعتراف أفضل من اتهام خاطئ.\n\n"
        "وأخيراً field_confidence: درجة ثقتك في كل حقل حرج على حدة (high أو medium أو low). "
        "أي حقل وضعت قيمته null يجب أن تكون ثقته low.\n\n"
        "أعد النتيجة بصيغة JSON فقط بدون أي نص إضافي، وفق الحقول التالية بالضبط:\n"
        '{"order_code": "الرقم الطويل من شاشة التطبيق، أو null إن لم يظهر", '
        '"platform": "keeta|jahez|hunger|ninja|thechefz|marsool|toyou|unknown", '
        '"branch": "اسم الفرع أو رمز المخزن أو null", '
        '"order_date": "YYYY-MM-DD أو null", '
        '"order_total": "الإجمالي النهائي كرقم أو null", '
        '"currency": "SAR", '
        '"items": [{"code": "R253 أو null", '
        '"name": "اسم الصنف بدون الكود", '
        '"quantity": "عدد القطع كرقم أو null", '
        '"weight_value": "الوزن كرقم مجرد أو null", '
        '"weight_unit": "g أو kg", '
        '"weight_basis": "per_unit أو line_total أو null", '
        '"total_weight_value": "الوزن الإجمالي لكامل كمية السطر كرقم أو null", '
        '"total_weight_unit": "g أو kg", '
        '"weight": "الوزن/الحجم من ملصق العبوة أو null", '
        '"price": "سعر الصنف من شاشة التطبيق أو null", '
        '"line_total": "إجمالي السطر أو null"}], '
        '"evidence_medium": "printed_receipt|app_screen|unknown", '
        '"invoice_items": [{"code": "R253 أو null", "name": "اسم الصنف كما هو مكتوب بالفاتورة", '
        '"quantity": "عدد أو null", "unit_price": "سعر القطعة أو null", "line_total": "إجمالي السطر أو null"}], '
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

