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
            "هذه فريمات من فيديو تحضير طلب. اقرأ رقم/كود الطلب (مثل R###) "
            "والأصناف الظاهرة في الفاتورة أو التغليف. "
            "أرجع JSON فقط بالشكل: "
            '{"order_code": "...", "items": ["..."], "confidence": "high|medium|low"}'
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
