import os, subprocess, tempfile, base64, json
from pathlib import Path
import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from anthropic import Anthropic

app = FastAPI()
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

class VerifyRequest(BaseModel):
    video_url: str
    invoice_text: str | None = None

def extract_frames(video_path: str, out_dir: str, fps: float = 1.0):
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vf", f"fps={fps}", f"{out_dir}/frame_%03d.jpg"],
        check=True, capture_output=True
    )
    return sorted(Path(out_dir).glob("frame_*.jpg"))

@app.post("/verify-order")
def verify_order(req: VerifyRequest):
    with tempfile.TemporaryDirectory() as tmp:
        video_path = f"{tmp}/video.mp4"
        with httpx.stream("GET", req.video_url, follow_redirects=True) as r:
            with open(video_path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)

        frames = extract_frames(video_path, tmp)
        if not frames:
            return {"status": "error", "reason": "no_frames_extracted"}

        content = []
        for fp in frames[:20]:
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
                        "أعد النتيجة بصيغة JSON فقط بدون أي نص إضافي، وفق الحقول التالية بالضبط:\n"
                        '{"order_code": "الرقم الطويل من شاشة التطبيق، أو null إن لم يظهر", '
                        '"items": ["قائمة الأصناف المكتشفة، كل صنف بكوده إن توفر أو وصفه إن لم يتوفر كود"], '
                        '"order_source_hint": "image_catalog|text_list|mixed|not_applicable", '
                        '"confidence": "high|medium|low"}'
        )
        if req.invoice_text:
            prompt += f"\n\nنص الفاتورة المتوقع للمقارنة:\n{req.invoice_text}"

        content.append({"type": "text", "text": prompt})

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": content}]
        )

        raw = msg.content[0].text.strip()
        raw = raw.replace("json", "").replace("", "").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw_response": raw}

        return {"status": "ok", "result": parsed}

@app.get("/health")
def health():
    return {"status": "ok"}
