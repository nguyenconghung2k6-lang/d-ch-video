import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import time
import wave
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import srt
from imageio_ffmpeg import get_ffmpeg_exe

RATE = 24000


def run(args, **options):
    return subprocess.run(args, check=True, stdin=subprocess.DEVNULL, **options)


def ocr(ffmpeg, source, work, tesseract):
    from difflib import SequenceMatcher

    frames = work / "frames"
    frames.mkdir()
    # Read the original lower strip before cropping it out of the export.
    run([ffmpeg, "-v", "error", "-i", str(source), "-an", "-vf",
         "fps=2,crop=iw*0.76:ih*0.13:iw*0.12:ih*0.87,scale=1200:-2,format=gray,negate",
         str(frames / "%08d.pgm")])
    previous = ""
    start = 0.0
    cues = []
    for index, frame in enumerate(sorted(frames.glob("*.pgm"))):
        stamp = index / 2
        text = run([tesseract, str(frame), "stdout", "-l", "chi_sim", "--psm", "7"],
                   capture_output=True, encoding="utf-8").stdout
        text = re.sub(r"\s+", "", text)
        if len(re.findall(r"[\u3400-\u9fff]", text)) < 2:
            text = ""
        if previous and text and SequenceMatcher(None, previous, text).ratio() >= .84:
            continue
        if previous and stamp - start >= .5:
            cues.append(srt.Subtitle(len(cues) + 1, timedelta(seconds=start),
                                     timedelta(seconds=stamp), previous))
        previous, start = text, stamp
        if index % 120 == 0:
            print(f"OCR: {stamp:.0f} giây video", flush=True)
    if previous:
        cues.append(srt.Subtitle(len(cues) + 1, timedelta(seconds=start),
                                 timedelta(seconds=(index + 1) / 2), previous))
    return cues


def translate(cues, cache):
    from deep_translator import GoogleTranslator

    translator = GoogleTranslator(source="auto", target="vi")
    for cue in cues:
        key = hashlib.sha256(cue.content.encode()).hexdigest()
        target = cache / (key + ".txt")
        if not target.exists():
            for delay in (1, 8, 30):
                time.sleep(delay)
                try:
                    result = translator.translate(cue.content)
                    if not result:
                        raise ValueError("Bản dịch trống")
                    target.write_text(result, encoding="utf-8")
                    break
                except Exception:
                    if delay == 30:
                        raise
        cue.content = target.read_text(encoding="utf-8")
    return cues


async def dub(ffmpeg, cues, cache, track):
    import edge_tts

    cursor = 0
    with wave.open(str(track), "wb") as out:
        out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        for i, cue in enumerate(cues, 1):
            start = max(cursor, round(cue.start.total_seconds() * RATE))
            content = " ".join(cue.content.split())
            key = hashlib.sha256(("HoaiMy:" + content).encode()).hexdigest()
            clip = cache / (key + ".mp3")
            if not clip.exists():
                temporary = clip.with_suffix(".tmp")
                for attempt in range(4):
                    try:
                        await edge_tts.Communicate(content, "vi-VN-HoaiMyNeural",
                                                   connect_timeout=15, receive_timeout=30).save(str(temporary))
                        if temporary.stat().st_size == 0:
                            raise ValueError("Âm thanh trống")
                        temporary.replace(clip)
                        break
                    except Exception as exc:
                        temporary.unlink(missing_ok=True)
                        if attempt == 3:
                            raise RuntimeError(f"Hoài My lỗi tại dòng {i}: {exc}") from exc
                        await asyncio.sleep(2 ** (attempt + 1))
            pcm = run([ffmpeg, "-v", "error", "-i", str(clip), "-af", "atempo=1.25",
                       "-ar", str(RATE), "-ac", "1", "-f", "s16le", "-"],
                      stdout=subprocess.PIPE).stdout
            silence = start - cursor
            while silence:
                chunk = min(silence, RATE)
                out.writeframesraw(bytes(chunk * 2))
                silence -= chunk
            out.writeframesraw(pcm)
            cursor = start + len(pcm) // 2
            print(f"Giọng Hoài My: {i}/{len(cues)}", flush=True)


def render(ffmpeg, source, work, output, top, bottom, volume):
    height = (100 - top - bottom) / 100
    vf = (f"crop=trunc(iw/2)*2:trunc(ih*{height}/2)*2:0:trunc(ih*{top / 100}/2)*2,"
          "subtitles=caption.srt:force_style='FontName=Arial,FontSize=17,Outline=2,MarginV=14'")
    run([ffmpeg, "-v", "error", "-stats", "-n", "-i", str(source), "-i", "voice.wav",
         "-vf", vf, "-filter_complex",
         f"[0:a:0]volume={volume / 100}[bg];[1:a:0]apad[vi];"
         "[bg][vi]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95:level=0[a]",
         "-map", "0:v:0", "-map", "[a]", "-shortest", "-c:v", "libx264",
         "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-movflags", "+faststart", str(output)], cwd=work)


def main():
    parser = argparse.ArgumentParser(description="Tạo MP4 phụ đề Việt và giọng Hoài My.")
    parser.add_argument("video", type=Path)
    source_mode = parser.add_mutually_exclusive_group(required=True)
    source_mode.add_argument("--srt-viet", type=Path)
    source_mode.add_argument("--srt-trung", type=Path)
    source_mode.add_argument("--ocr", action="store_true")
    parser.add_argument("--ocr-only", action="store_true", help="Chỉ trích phụ đề Trung để soát")
    parser.add_argument("--tesseract", default="tesseract")
    parser.add_argument("--crop-top", type=float, default=6)
    parser.add_argument("--crop-bottom", type=float, default=12)
    parser.add_argument("--am-goc", type=float, default=15)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not (0 <= args.crop_top and 0 <= args.crop_bottom
            and args.crop_top + args.crop_bottom < 90 and 0 <= args.am_goc <= 100):
        parser.error("Tỷ lệ crop hoặc âm lượng ngoài phạm vi.")
    if args.ocr_only and not args.ocr:
        parser.error("--ocr-only cần đi cùng --ocr.")
    source = args.video.resolve()
    if not source.is_file():
        parser.error(f"Không tìm thấy {source}")
    output = (args.output or source.with_suffix(".hoai-my.mp4")).resolve()
    if output.exists() and not args.ocr_only:
        parser.error(f"File đã tồn tại: {output}. Chọn --output khác.")
    cache = source.parent / ".cache-hoai-my"
    cache.mkdir(exist_ok=True)
    ffmpeg = os.environ.get("IMAGEIO_FFMPEG_EXE") or get_ffmpeg_exe()
    try:
        with TemporaryDirectory(prefix="hoai-my-", dir=source.parent) as folder:
            work = Path(folder)
            sub = args.srt_viet or args.srt_trung
            if sub:
                cues = list(srt.parse(sub.read_text(encoding="utf-8-sig")))
            else:
                zh = source.with_suffix(".ocr.zh.srt")
                if zh.is_file():
                    cues = list(srt.parse(zh.read_text(encoding="utf-8-sig")))
                else:
                    cues = ocr(ffmpeg, source, work, args.tesseract)
                    if cues:
                        zh.write_text(srt.compose(cues), encoding="utf-8")
            cues = [c for c in srt.sort_and_reindex(cues)
                    if c.content.strip().casefold() != "[nghe không rõ]"]
            if not cues:
                raise ValueError("Không tìm thấy phụ đề để đọc.")
            if args.ocr_only:
                print(f"Đã lưu {zh}")
                return
            if not args.srt_viet:
                cues = translate(cues, cache)
                source.with_suffix(".hoai-my.vi.srt").write_text(srt.compose(cues), encoding="utf-8")
            (work / "caption.srt").write_text(srt.compose(cues), encoding="utf-8")
            asyncio.run(dub(ffmpeg, cues, cache, work / "voice.wav"))
            temporary_output = work / "render.mp4"
            render(ffmpeg, source, work, temporary_output, args.crop_top, args.crop_bottom, args.am_goc)
            if output.exists():
                raise FileExistsError(output)
            temporary_output.rename(output)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Lỗi: {exc}\n")
    print(f"Đã xuất {output}")


if __name__ == "__main__":
    main()
