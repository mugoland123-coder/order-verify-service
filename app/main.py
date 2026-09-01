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

@app.post("/verify-order")
def verify_order(req: VerifyRequest):
    with tempfile.TemporaryDirectory() as tmp:
        video_path = f"{tmp}/video.mp4"
        with httpx.stream("GET", req.video_url, follow_redirects=True) as r:
            with open(video_path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)

                try:
            frames = extract_frames(video_path, tmp)
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
            "أعد النتيجة بصيغة JSON فقط بدون أي نص إضافي، وفق الحقول التالية بالضبط:\n"
            '{"order_code": "الرقم الطويل من شاشة التطبيق، أو null إن لم يظهر", '
            '"items": [{"name": "اسم/كود الصنف كما يظهر أو وصفه إن لم يتوفر كود", '
            '"weight": "الوزن/الحجم من ملصق العبوة أو null", '
            '"price": "سعر الصنف من شاشة التطبيق أو null"}], '
            '"order_source_hint": "image_catalog|text_list|mixed|not_applicable", '
            '"confidence": "high|medium|low"}'
        )
        if req.invoice_text:
            prompt += f"\n\nنص الفاتورة المتوقع للمقارنة:\n{req.invoice_text}"

        content.append({"type": "text", "text": prompt})

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
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

        return {"status": "ok", "result": parsed}

@app.get("/health")
def health():
    return {"status": "ok"}
