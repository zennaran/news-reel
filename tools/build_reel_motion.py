#!/usr/bin/env python3
"""Build a ~1-minute vertical (9:16) reel with an ANIMATED background.

Motion layers: panning + hue-drifting gradient, drifting aurora blobs,
rising particles (2 speeds = parallax), periodic light sweep, pop-in telop,
optional per-scene category tag ("tag": "経済"), and a top progress bar.
Scene JSON is identical to daily-reel build_reel.py ("tag" is optional).

Usage:
    python build_reel.py script.json [--bgm music.mp3]

script.json:
{
  "output": "/mnt/user-data/outputs/2026-10-06_reel.mp4",
  "speed": 1.1,                      # narration speed (optional, default 1.1)
  "voice": 20,                       # VOICEVOX style id (optional; see voices.py)
  "scenes": [
    {"part": "hook",    "telop": "画面に出す短い文字", "narration": "読み上げる文", "image": "/path/photo.jpg"},
    {"part": "empathy", "telop": "...", "narration": "...", "image": null},
    {"part": "closing", "telop": "...", "narration": "...", "image": null}
  ]
}
part: hook / empathy / special / closing  (controls layout & colors)
Use "\n" in telop to force a line break.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H, FPS = 1080, 1920, 30
PAN = 1.10  # background is rendered 10% larger and slowly panned

FONT_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", 0),
]

# gradient colors for text-only scenes, per part
PALETTE = {
    "hook":    ((20, 20, 35), (90, 30, 70)),
    "empathy": ((25, 45, 70), (60, 110, 140)),
    "special": ((70, 40, 20), (190, 120, 50)),
    "closing": ((20, 30, 30), (40, 100, 90)),
}
ACCENT = {"hook": (255, 225, 60), "empathy": (255, 255, 255),
          "special": (255, 225, 60), "closing": (255, 255, 255)}
NO_LINE_START = set("、。，．・：；？！ー～〜…‥）」』】〕〉》’”ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ,.!?)")


def font(size):
    for path, idx in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size, index=idx)
    sys.exit("Japanese font not found. Install fonts-noto-cjk.")


def wrap(text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if cur and fnt.getlength(cur + ch) > max_w and ch not in NO_LINE_START:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def load_photo(path):
    try:
        if path.lower().endswith((".heic", ".heif")):
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                tmp = tempfile.mktemp(suffix=".jpg")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, tmp], check=True)
                path = tmp
        return ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    except Exception as e:
        print(f"[warn] could not read image {path}: {e} -> using text-only background")
        return None


def background(scene, size):
    bw, bh = size
    img = load_photo(scene["image"]) if scene.get("image") else None
    if img is not None:
        # cover-crop
        bg = ImageOps.fit(img, (bw, bh), Image.LANCZOS)
        return bg
    top, bottom = PALETTE.get(scene.get("part"), PALETTE["empathy"])
    t = np.linspace(0, 1, bh)[:, None, None]
    arr = (np.array(top) * (1 - t) + np.array(bottom) * t).astype(np.uint8)
    arr = np.repeat(arr, bw, axis=1)
    return Image.fromarray(arr, "RGB")


def overlay(scene, has_photo):
    """Transparent PNG with telop text (fixed, does not pan)."""
    part = scene.get("part", "empathy")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    big = part in ("hook", "closing")
    size = 116 if big else 96
    max_w = W - 120
    n_para = scene["telop"].count("\n") + 1
    # shrink until each author-specified line fits on one row (no awkward auto-wraps)
    while True:
        fnt = font(size)
        lines = wrap(scene["telop"], fnt, max_w)
        if len(lines) <= n_para or size <= 64:
            break
        size -= 4
    lh = int(size * 1.35)
    block_h = lh * len(lines)
    # Photos: keep text in the lower-middle so the photo stays visible,
    # but above Instagram's bottom UI (~bottom 20%). Text-only: centered.
    if part == "hook" or not has_photo:
        y0 = int(H * 0.42) - block_h // 2
    else:
        y0 = int(H * 0.66) - block_h // 2

    if has_photo:  # dark band behind text for readability
        band = Image.new("L", (W, H), 0)
        bd = ImageDraw.Draw(band)
        bd.rectangle([0, y0 - 60, W, y0 + block_h + 60], fill=150)
        band = band.filter(ImageFilter.GaussianBlur(40))
        ov.paste((0, 0, 0, 255), (0, 0, W, H), band)
        d = ImageDraw.Draw(ov)

    color = ACCENT.get(part, (255, 255, 255))
    for i, line in enumerate(lines):
        w = fnt.getlength(line)
        d.text(((W - w) / 2, y0 + i * lh), line, font=fnt, fill=color,
               stroke_width=max(4, size // 14), stroke_fill=(0, 0, 0))
    return ov


VV_DIR = os.environ.get("VOICEVOX_DIR", os.path.expanduser("~/.cache/voicevox"))
_SYN = {}


def voicevox_synth(text, voice, speed, intonation):
    """High-quality TTS via VOICEVOX CORE. Returns (int16 array, sr) or None."""
    try:
        from voicevox_core.blocking import Onnxruntime, OpenJtalk, Synthesizer, VoiceModelFile
    except ImportError:
        return None
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from voices import VOICES
    if voice not in VOICES:
        sys.exit(f"unknown voice id {voice}")
    vvm = os.path.join(VV_DIR, "vvms", f"{VOICES[voice][0]}.vvm")
    if not os.path.exists(vvm):
        print(f"[warn] {vvm} not found. Run: bash setup_voicevox.sh {voice}")
        return None
    if "syn" not in _SYN:
        ort_lib = os.path.join(VV_DIR, "voicevox_onnxruntime-linux-x64-1.17.3", "lib",
                               "libvoicevox_onnxruntime.so.1.17.3")
        ort = Onnxruntime.load_once(filename=ort_lib)
        _SYN["syn"] = Synthesizer(ort, OpenJtalk(os.path.join(VV_DIR, "open_jtalk_dic_utf_8-1.11")))
    syn = _SYN["syn"]
    if vvm not in _SYN:
        with VoiceModelFile.open(vvm) as m:
            syn.load_voice_model(m)
        _SYN[vvm] = True
    q = syn.create_audio_query(text, voice)
    q.speed_scale = speed
    q.intonation_scale = intonation
    q.pre_phoneme_length = 0.1
    q.post_phoneme_length = 0.1
    wav_bytes = syn.synthesis(q, voice)
    import io
    with wave.open(io.BytesIO(wav_bytes)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    return x, sr


def tts(text, speed, out_wav, voice=None, intonation=1.15):
    res = voicevox_synth(text, voice, speed, intonation) if voice is not None else None
    if res is None:
        if voice is not None:
            print("[warn] VOICEVOX unavailable -> falling back to pyopenjtalk (robotic voice)")
            _SYN["fallback"] = True
        import pyopenjtalk
        x, sr = pyopenjtalk.tts(text, speed=speed)
    else:
        x, sr = res
    x = np.clip(x, -32768, 32767).astype(np.int16)
    pad_head = np.zeros(int(sr * 0.25), np.int16)
    pad_tail = np.zeros(int(sr * 0.45), np.int16)
    x = np.concatenate([pad_head, x, pad_tail])
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(x.tobytes())
    return len(x) / sr



PART_HUE = {"hook": 0, "empathy": 1, "special": 2, "closing": 3}


def periodic_layer(seed, kind, color, w=W, h=H):
    """RGBA canvas of size w x 2h whose top half == bottom half (seamless vertical loop)."""
    rng = np.random.default_rng(seed)
    # draw on a 3h canvas (wrapped copies) and blur there, then keep the middle third,
    # so the blur never fades out at the tile edges (no visible seam when looping)
    base = Image.new("RGBA", (w, 3 * h), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    if kind == "blobs":
        for _ in range(6):
            r = int(rng.uniform(220, 420)); x = rng.uniform(0, w); y = rng.uniform(0, h)
            c = tuple(int(min(255, v * rng.uniform(0.8, 1.3))) for v in color)
            for dy in (-h, 0, h):  # draw wrapped copies so the tile is seamless
                d.ellipse([x - r, y + h + dy - r, x + r, y + h + dy + r], fill=c + (70,))
        base = base.filter(ImageFilter.GaussianBlur(90))
    else:  # particles
        n = 70 if kind == "dots_far" else 28
        for _ in range(n):
            r = rng.uniform(2, 5) if kind == "dots_far" else rng.uniform(6, 13)
            a = int(rng.uniform(90, 200)) if kind == "dots_far" else int(rng.uniform(60, 130))
            x = rng.uniform(0, w); y = rng.uniform(0, h)
            for dy in (-h, 0, h):
                d.ellipse([x - r, y + h + dy - r, x + r, y + h + dy + r], fill=color + (a,))
        if kind == "dots_near":
            base = base.filter(ImageFilter.GaussianBlur(3))
    base = base.crop((0, h, w, 2 * h))
    tall = Image.new("RGBA", (w, 2 * h)); tall.paste(base, (0, 0)); tall.paste(base, (0, h))
    return tall


def sweep_layer():
    """Diagonal soft light band (RGBA, W x H)."""
    band = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(band)
    d.polygon([(W * 0.35, 0), (W * 0.55, 0), (W * 0.35, H), (W * 0.15, H)], fill=60)
    band = band.filter(ImageFilter.GaussianBlur(50))
    ov = Image.new("RGBA", (W, H), (255, 255, 255, 0)); ov.putalpha(band)
    return ov


def text_sprite(scene, has_photo):
    """Telop cropped to its bbox + its centre (cx, cy) on the frame, for pop-in scaling."""
    ov = overlay(scene, has_photo)
    if has_photo:
        return ov, None
    bbox = ov.getbbox() or (0, 0, W, H)
    pad = 20
    bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(W, bbox[2] + pad), min(H, bbox[3] + pad))
    spr = ov.crop(bbox)
    return spr, ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def tag_sprite(tag, part):
    fnt = font(58)
    tw = int(fnt.getlength(tag)); pw, ph = tw + 80, 96
    im = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    acc = ACCENT.get(part, (255, 255, 255))
    fill = (255, 225, 60) if acc == (255, 255, 255) else acc
    d.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=ph // 2, fill=fill + (235,))
    d.text(((pw - tw) / 2, (ph - 58) / 2 - 8), tag, font=fnt, fill=(20, 20, 20))
    return im


def render_scene(i, scene, wav, dur, start, total, tmp):
    bw, bh = int(W * PAN), int(H * PAN)
    has_photo = bool(scene.get("image")) and load_photo(scene["image"]) is not None
    part = scene.get("part", "empathy")
    bg = background(scene, (bw, bh))
    files = {}
    def save(name, im):
        p = os.path.join(tmp, f"{name}{i}.png"); im.save(p); files[name] = p
    save("bg", bg)
    top, bottom = PALETTE.get(part, PALETTE["empathy"])
    blob_col = tuple(min(255, int(c * 1.6) + 40) for c in bottom)
    acc = ACCENT.get(part, (255, 255, 255))
    save("blob", periodic_layer(100 + i, "blobs", blob_col))
    save("far", periodic_layer(200 + i, "dots_far", (255, 255, 255)))
    save("near", periodic_layer(300 + i, "dots_near", acc))
    save("sweep", sweep_layer())
    spr, centre = text_sprite(scene, has_photo)
    save("txt", spr)
    tag = scene.get("tag")
    if tag:
        save("tag", tag_sprite(tag, part))

    dx, dy = bw - W, bh - H
    if i % 2 == 0:
        xexpr, yexpr = f"{dx}*t/{dur:.3f}", f"{dy}*t/{dur:.3f}"
    else:
        xexpr, yexpr = f"{dx}*(1-t/{dur:.3f})", f"{dy}/2"
    inputs, n = [], 0
    def add(path):
        nonlocal n
        inputs.extend(["-loop", "1", "-t", f"{dur:.3f}", "-i", path]); n += 1
        return n - 1
    ib, il, ifa, ine, isw, itx = (add(files[k]) for k in ("bg", "blob", "far", "near", "sweep", "txt"))
    itg = add(files["tag"]) if tag else None
    ia = n; inputs.extend(["-i", wav])
    hue = "" if has_photo else f",hue=h='25*sin(2*PI*(t+{start:.2f})/9)'"
    # pop-in: damped overshoot spring, settles to 1.0 in ~0.4s
    s = "(1-0.45*exp(-9*t)*cos(16*t))"
    fc = [f"[{ib}:v]crop={W}:{H}:x='{xexpr}':y='{yexpr}'{hue},fps={FPS},format=rgba[b0]"]
    fc.append(f"[b0][{il}:v]overlay=x=0:y='-mod((t+{start:.2f})*45\\,{H})':format=auto[b1]")
    fc.append(f"[b1][{ifa}:v]overlay=x=0:y='-mod((t+{start:.2f})*70\\,{H})'[b2]")
    fc.append(f"[b2][{ine}:v]overlay=x='30*sin(t*1.3)':y='-mod((t+{start:.2f})*170\\,{H})'[b3]")
    fc.append(f"[b3][{isw}:v]overlay=x='mod((t+{start:.2f})*700\\,{W*4})-{W}':y=0[b4]")
    last = "b4"
    if tag:
        fc.append(f"[{itg}:v]fade=t=in:st=0.1:d=0.25:alpha=1[tg]")
        fc.append(f"[{last}][tg]overlay=x='(W-w)/2':y='{int(H*0.42)-330}-max(0\\,60-t*400)'[b5]")
        last = "b5"
    if centre:
        cx, cy = centre
        fc.append(f"[{itx}:v]scale=w='trunc(iw*{s}/2)*2':h='trunc(ih*{s}/2)*2':eval=frame[tx]")
        fc.append(f"[{last}][tx]overlay=x='{cx:.0f}-w/2':y='{cy:.0f}-h/2':eval=frame[b6]")
    else:
        fc.append(f"[{last}][{itx}:v]overlay=0:0[b6]")
    pc = "0xFFE13C" if acc != (255, 255, 255) else "0xFFFFFF"
    fc.append(f"[b6]drawbox=x=0:y=0:w={W}:h=14:color=black@0.35:t=fill,"
              f"drawbox=x=0:y=0:w='{W}*({start:.3f}+t)/{total:.3f}':h=14:color={pc}@0.95:t=fill,"
              f"fade=t=in:st=0:d=0.2,format=yuv420p[v]")
    out = os.path.join(tmp, f"s{i}.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs,
           "-filter_complex", ";".join(fc), "-map", "[v]", "-map", f"{ia}:a",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", str(FPS),
           "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k",
           "-t", f"{dur:.3f}", out]
    subprocess.run(cmd, check=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--bgm", help="optional background music file (mixed quietly)")
    a = ap.parse_args()
    spec = json.load(open(a.script, encoding="utf-8"))
    speed = float(spec.get("speed", 1.1))
    voice = spec.get("voice")
    voice = int(voice) if voice is not None else None
    intonation = float(spec.get("intonation", 1.15))
    out = spec["output"]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="reel_")
    # pass 1: narration (need total length for the progress bar)
    wavs, durs = [], []
    for i, sc in enumerate(spec["scenes"]):
        wav = os.path.join(tmp, f"s{i}.wav")
        d = tts(sc["narration"], speed, wav, voice, intonation)
        wavs.append(wav); durs.append(max(d, float(sc.get("min_sec", 2.0))))
    total = sum(durs)
    # pass 2: video
    parts, start = [], 0.0
    for i, sc in enumerate(spec["scenes"]):
        parts.append(render_scene(i, sc, wavs[i], durs[i], start, total, tmp))
        print(f"scene {i+1} [{sc.get('part')}] {durs[i]:.1f}s")
        start += durs[i]
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    joined = os.path.join(tmp, "joined.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", joined], check=True)
    if a.bgm:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", joined,
                        "-stream_loop", "-1", "-i", a.bgm, "-filter_complex",
                        "[1:a]volume=0.12[b];[0:a][b]amix=inputs=2:duration=first[a]",
                        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", out], check=True)
    else:
        shutil.move(joined, out)
    cover = os.path.splitext(out)[0] + "_cover.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.0", "-i", out,
                    "-frames:v", "1", cover], check=True)
    print(f"TOTAL {total:.1f}s -> {out}")
    print(f"cover -> {cover}")
    if voice is not None and not _SYN.get("fallback"):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from voices import VOICES
        name = VOICES[voice][1]
        if name == "もち子さん":
            name = "もち子(cv 明日葉よもぎ)"
        print(f"CREDIT (put this in the caption): VOICEVOX:{name}")
    if not 40 <= total <= 75:
        print("[warn] total length is outside 40-75s; adjust narration length.")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
