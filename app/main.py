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

def extract_frames(video_path: str, out_dir: str, fps: float = 1.0):
    try:
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-vf", f"fps={fps}", f"{out_dir}/frame_%03d.jpg"],
            check=True, capture_output=True
        )
    except subprocess.CalledProcessError as e:
        raise FFmpegExtractionError(str(e)) from e
    return sorted(Path(out_dir).glob("frame_*.jpg"))

def select_frames_covering_full_video(frames, max_frames: int = 30):
    """
    يرجّع مجموعة إطارات موزّعة بالتساوي على طول الفيديو كاملاً (من أوله إلى
    آخره)، بدل الاكتفاء بأول N إطار فقط. هذا مهم لأن شاشة تطبيق التوصيل
    (وبالتالي السعر) قد لا تظهر إلا في جزء متأخر من الفيديو — بعد فتح
    الطرد مثلاً — وكانت أول 20 إطاراً (أول 20 ثانية فقط عند fps=1) قد
    تفوّت هذا الجزء تماماً وترجع السعر null رغم وجوده فعلياً بالفيديو.

    إذا كان عدد الإطارات أقل من أو يساوي max_frames، تُرجع كلها كما هي.
    """
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


def _clean_name(raw_name):
    name = re.sub(r"[رR]\s?\d{1,5}", "", str(raw_name or ""))
    name = re.sub(r"\(\s*\)|\[\s*\]", " ", name)
    name = re.sub(r"\s*-\s*SKU\s*:?\s*", " ", name, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", name).strip(" -–_")


_CONF = ("high", "medium", "low")


def _norm_conf(value):
    s = str(value or "").strip().lower()
    return s if s in _CONF else "low"


def normalize_result(parsed):
    # حالة فشل تفكيك JSON تمر كما هي بلا تعديل — n8n يتعامل معها كفشل تقني.
    if not isinstance(parsed, dict) or "raw_response" in parsed:
        return parsed

    items = []
    for raw_item in (parsed.get("items") or []):
        if not isinstance(raw_item, dict):
            continue
        weight_value, weight_unit = _norm_weight(raw_item)
        line_total = _num(raw_item.get("line_total"))
        unit_price = _num(raw_item.get("price"))
        quantity = _num(raw_item.get("quantity"))
        quantity = int(quantity) if quantity is not None else None
        if line_total is None and unit_price is not None:
            line_total = round(unit_price * (quantity or 1), 2)
        items.append({
            "code": _norm_code(raw_item),
            "name": _clean_name(raw_item.get("name")),
            "quantity": quantity,
            "weight_value": weight_value,
            "weight_unit": weight_unit,
            "weight": raw_item.get("weight"),
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

    return {
        "order_code": order_code,
        "platform": platform,
        "branch": branch,
        "order_date": parsed.get("order_date") or None,
        "order_total": order_total,
        "currency": parsed.get("currency") or "SAR",
        "items": items,
        "order_source_hint": parsed.get("order_source_hint") or "not_applicable",
        "confidence": _norm_conf(parsed.get("confidence")),
        "field_confidence": {
            "order_code": _norm_conf(field_conf.get("order_code")) if order_code else "low",
            "platform": _norm_conf(field_conf.get("platform")) if platform != "unknown" else "low",
            "branch": _norm_conf(field_conf.get("branch")) if branch else "low",
            "order_total": _norm_conf(field_conf.get("order_total")) if order_total else "low",
        },
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
        "- line_total: إجمالي هذا السطر شاملاً الضريبة. إذا كان الظاهر سعر القطعة الواحدة فقط "
        "فاضربه في الكمية. ضع null إن تعذّر.\n\n"
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
        '"weight": "الوزن/الحجم من ملصق العبوة أو null", '
        '"price": "سعر الصنف من شاشة التطبيق أو null", '
        '"line_total": "إجمالي السطر أو null"}], '
        '"order_source_hint": "image_catalog|text_list|mixed|not_applicable", '
        '"confidence": "high|medium|low", '
        '"field_confidence": {"order_code": "high|medium|low", "platform": "high|medium|low", '
        '"branch": "high|medium|low", "order_total": "high|medium|low"}}'
    )
    if invoice_text:
        prompt += f"\n\nنص الفاتورة المتوقع للمقارنة:\n{invoice_text}"

    content.append({"type": "text", "text": prompt})

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
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
        try:
            frames = extract_frames(input_path, tmp)
        except FFmpegExtractionError:
            return {
                "status": "extraction_failed",
                "result": None,
                "error": "فشل استخراج إطارات الفيديو تقنياً (ffmpeg)، يحتاج مراجعة يدوية"
            }
        if not frames:
            return {"status": "error", "reason": "no_frames_extracted"}

        selected_frames = select_frames_covering_full_video(frames, max_frames=30)

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
