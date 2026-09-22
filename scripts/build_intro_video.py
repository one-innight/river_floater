from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

PROJECT_DIR = Path(__file__).resolve().parent.parent
ASSET_DIR = PROJECT_DIR / "video_assets"
SCREEN_DIR = ASSET_DIR / "screens"
AUDIO_DIR = ASSET_DIR / "audio"
FRAME_DIR = ASSET_DIR / "frames"
OUTPUT_DIR = PROJECT_DIR / "项目文档"
OUTPUT_VIDEO = OUTPUT_DIR / "河道主动巡护系统功能介绍.mp4"
OUTPUT_SUBTITLES = OUTPUT_DIR / "河道主动巡护系统功能介绍.srt"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 25
WIDTH = 1920
HEIGHT = 1080

SEGMENTS = [
    ("01_login.png", "河道主动巡护系统，为河道漂浮物识别、主动预警和事件闭环处置提供一体化支持。"),
    ("02_dashboard.png", "登录后，管理端集中展示今日识别、待处理事件、严重预警和模型运行状态，巡护情况一目了然。"),
    ("03_recognize.png", "巡护人员可上传现场图片并自定义河段名称。系统调用漂浮物检测模型，自动输出目标数量、检测框和置信度。"),
    ("04_camera.png", "系统支持浏览器摄像头以及 OpenCV、RTSP 视频巡护，可按设定间隔持续抽帧分析，降低人工值守压力。"),
    ("05_events.png", "发现漂浮物后，系统按数量生成黄色、橙色或红色预警，并自动建立事件台账，保留图片和处理记录。"),
    ("06_mobile_inspect.png", "移动端适配手机浏览器，支持现场拍照或从相册选择图片，随时完成河段巡查和识别上报。"),
    ("07_mobile_events.png", "事件按照确认、派单、处理、复核和归档顺序流转。上传清理后的照片后，模型会给出复核结论，形成完整处置闭环。"),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ["msyhbd.ttc" if bold else "msyh.ttc", "simhei.ttf"]
    font_dir = Path(r"C:\Windows\Fonts")
    for name in names:
        candidate = font_dir / name
        if candidate.exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def synthesize(text: str, output: Path) -> None:
    escaped_text = text.replace("'", "''")
    escaped_output = str(output).replace("'", "''")
    command = (
        "Add-Type -AssemblyName System.Speech; "
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SelectVoice('Microsoft Huihui Desktop'); $s.Rate=0; $s.Volume=100; "
        f"$s.SetOutputToWaveFile('{escaped_output}'); $s.Speak('{escaped_text}'); "
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True)


def audio_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, text_font) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if draw.textbbox((0, 0), candidate, font=text_font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def compose_frame(source_path: Path, subtitle: str, mobile: bool) -> Image.Image:
    source = Image.open(source_path).convert("RGB")
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#071d20")
    background = source.resize((WIDTH, HEIGHT)).filter(ImageFilter.GaussianBlur(25))
    background = ImageEnhance.Brightness(background).enhance(0.28)
    canvas.paste(background)
    draw = ImageDraw.Draw(canvas, "RGBA")

    if mobile:
        target_h = 820
        target_w = round(source.width * target_h / source.height)
        phone = source.resize((target_w, target_h), Image.Resampling.LANCZOS)
        x, y = 180, 80
        draw.rounded_rectangle((x - 18, y - 18, x + target_w + 18, y + target_h + 18), 38, fill="#081719", outline="#66cfc1", width=4)
        canvas.paste(phone, (x, y))
        draw.text((780, 255), "移动巡护", font=font(76, True), fill="#f3fbf9")
        draw.text((784, 360), "拍照识别 · 事件处置 · 现场复核", font=font(34), fill="#83dace")
        draw.rounded_rectangle((780, 430, 1660, 585), 22, fill=(12, 55, 57, 220), outline=(91, 185, 174, 190), width=2)
        draw.text((830, 470), "随时随地掌握河道事件进展", font=font(38, True), fill="#e9f8f5")
    else:
        max_h = 820
        scale = min(1760 / source.width, max_h / source.height)
        display = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS)
        x = (WIDTH - display.width) // 2
        y = 55
        draw.rounded_rectangle((x - 8, y - 8, x + display.width + 8, y + display.height + 8), 18, fill="#0a2426", outline="#4c9189", width=3)
        canvas.paste(display, (x, y))

    draw.rectangle((0, 870, WIDTH, HEIGHT), fill=(3, 17, 19, 235))
    subtitle_font = font(39, True)
    lines = wrap_text(draw, subtitle, 1660, subtitle_font)
    line_height = 58
    top = 906 + max(0, (2 - len(lines)) * 25)
    for index, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=subtitle_font)
        draw.text(((WIDTH - (bbox[2] - bbox[0])) / 2, top + index * line_height), line, font=subtitle_font, fill="#ffffff", stroke_width=2, stroke_fill="#000000")
    draw.text((68, 42), "RIVER PATROL", font=font(24, True), fill="#74d8ca")
    return canvas


def timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def main() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    concat_lines: list[str] = []
    subtitle_lines: list[str] = []
    elapsed = 0.0

    for index, (screen_name, subtitle) in enumerate(SEGMENTS, start=1):
        audio_path = AUDIO_DIR / f"{index:02d}.wav"
        frame_path = FRAME_DIR / f"{index:02d}.png"
        segment_path = FRAME_DIR / f"{index:02d}.mp4"
        synthesize(subtitle, audio_path)
        duration = audio_duration(audio_path) + 1.0
        frame = compose_frame(SCREEN_DIR / screen_name, subtitle, "mobile" in screen_name)
        frame.save(frame_path, quality=95)
        subprocess.run(
            [
                FFMPEG, "-y", "-loop", "1", "-i", str(frame_path), "-i", str(audio_path),
                "-t", f"{duration:.3f}", "-r", str(FPS), "-vf", "fade=t=in:st=0:d=0.45,fade=t=out:st=" + f"{max(0.5, duration - 0.45):.3f}:d=0.45",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-af", "apad=pad_dur=1", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", str(segment_path),
            ],
            check=True,
        )
        concat_lines.append(f"file '{segment_path.as_posix()}'")
        subtitle_lines.extend([str(index), f"{timestamp(elapsed)} --> {timestamp(elapsed + duration)}", subtitle, ""])
        elapsed += duration

    concat_path = FRAME_DIR / "concat.txt"
    concat_path.write_text("\n".join(concat_lines), encoding="utf-8")
    OUTPUT_SUBTITLES.write_text("\n".join(subtitle_lines), encoding="utf-8-sig")
    subprocess.run(
        [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", "-movflags", "+faststart", str(OUTPUT_VIDEO)],
        check=True,
    )
    print(f"Video: {OUTPUT_VIDEO}")
    print(f"Subtitles: {OUTPUT_SUBTITLES}")
    print(f"Duration: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
