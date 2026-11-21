import argparse
import math
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .scene import FPS, HEIGHT, SECONDS, WIDTH, Actor, world


def background() -> Image.Image:
    scene = Image.new("RGB", (WIDTH, HEIGHT), "#353e3d")
    draw = ImageDraw.Draw(scene)
    rng = random.Random(19)
    for y in range(18, HEIGHT, 28):
        for x in range(-38 if (y // 28) % 2 else 0, WIDTH, 118):
            value = rng.randrange(54, 72)
            draw.rectangle((x + 1, y + 1, x + 116, y + 26), fill=(value, value + 3, value))
            draw.line((x + 6, y + 4, x + 99, y + 4), fill=(value + 3, value + 6, value + 4))
    draw.rectangle((0, 0, 960, 26), fill="#252c2b")
    draw.rectangle((0, 0, 23, 600), fill="#282c2a")
    draw.rounded_rectangle((54, 41, 474, 83), radius=9, fill="#25352e")
    for x in range(75, 455, 36):
        shade = rng.choice(["#526958", "#465a43", "#344d40"])
        draw.ellipse((x - 14, 46, x + 19, 78), fill=shade)
        draw.line((x - 4, 73, x + 6, 49), fill="#637461", width=2)

    for cx, cy, r in [(255, 235, 39), (143, 385, 32), (370, 397, 39)]:
        for dy in (-49, 49):
            draw.rounded_rectangle((cx - 20, cy + dy - 15, cx + 20, cy + dy + 15),
                                   radius=8, fill="#798077", outline="#2a3231", width=2)
        draw.ellipse((cx - r + 4, cy - r + 7, cx + r + 6, cy + r + 8), fill="#303736")
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill="#9b785d",
                     outline="#b29270", width=3)
        draw.arc((cx - r + 4, cy - r + 6, cx + r - 5, cy + r - 5), 178, 280, fill="#b89573")
        if cx != 370:
            for dx, dy in [(-15, 6), (13, -10)]:
                draw.ellipse((cx + dx - 8, cy + dy - 8, cx + dx + 8, cy + dy + 8), fill="#d0c5aa")
                draw.ellipse((cx + dx - 4, cy + dy - 4, cx + dx + 4, cy + dy + 4), fill="#655248")
    draw.rounded_rectangle((353, 385, 385, 408), 3, fill="#393a41", outline="#b2a397", width=2)
    draw.line((360, 404, 380, 404), fill="#80888c", width=2)

    draw.rounded_rectangle((792, 70, 949, 486), 12, fill="#343a36")
    draw.rounded_rectangle((793, 60, 941, 478), 11, fill="#59645c", outline="#6c7365", width=2)
    draw.rounded_rectangle((782, 54, 840, 474), 11, fill="#887252", outline="#aa8e67", width=3)
    for y in range(69, 467, 8):
        draw.line((786, y, 833, y), fill="#927d59")
    for y in (106, 146, 385, 418):
        draw.rounded_rectangle((795, y, 827, y + 24), 4, fill="#333c3a", outline="#b39976")
    draw.rounded_rectangle((798, 184, 822, 211), 3, fill="#414d46", outline="#c4aa84")
    draw.rectangle((804, 189, 817, 199), fill="#a7c29f")
    for y in (267, 307, 342):
        draw.ellipse((797, y, 816, y + 19), fill="#d8c9ac", outline="#705e49")
        draw.ellipse((801, y + 4, 812, y + 15), fill="#503d34")

    for y in range(192, 436, 26):
        draw.line((674, y, 674, y + 12), fill="#9a9478", width=2)
    draw.rounded_rectangle((644, 500, 793, 558), 6, fill="#2e3734", outline="#737f72", width=2)
    for y in range(506, 554, 7):
        draw.line((651, y, 786, y), fill="#424c45")
    draw.line((616, 580, 813, 580), fill="#7b8573", width=3)
    draw.line((655, 592, 779, 592), fill="#58675e", width=4)
    font = ImageFont.load_default(size=13)
    draw.text((785, 495), "COUNTER", anchor="rm", fill="#c6c1a7", font=font)
    draw.text((718, 533), "ENTRY", anchor="mm", fill="#bac5b5", font=font)

    return scene


def actor_image(actor: Actor) -> Image.Image:
    image = Image.new("RGBA", (58, 58))
    draw = ImageDraw.Draw(image)
    draw.ellipse((7, 19, 53, 46), fill=(24, 27, 25, 115))
    draw.rounded_rectangle((10, 25, 48, 42), radius=8, fill=actor.color, outline="#272c29", width=2)
    draw.ellipse((17, 11, 41, 34), fill="#c19270", outline="#382e28", width=2)
    draw.arc((18, 11, 40, 31), 0, 180, fill="#51453a", width=5)
    draw.ellipse((26, 13, 31, 17), fill="#d3a484")
    return image.rotate(-math.degrees(actor.facing), resample=Image.Resampling.BICUBIC)


def render(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    base = background()
    process = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
         "-i", "pipe:0", "-an", "-c:v", "libx264", "-threads", "2", "-preset", "fast",
         "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None
    try:
        for index in range(FPS * SECONDS):
            frame = base.copy()
            actors, _ = world(index * 1000 // FPS)
            for actor in sorted(actors, key=lambda actor: actor.y):
                sprite = actor_image(actor)
                frame.paste(sprite, (round(actor.x) - 29, round(actor.y) - 29), sprite)
            process.stdin.write(frame.tobytes())
    finally:
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("Could not encode the demo video.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render the original café demo video.")
    parser.add_argument("output", type=Path, nargs="?", default=Path("demo/counter.mp4"))
    render(parser.parse_args().output)
