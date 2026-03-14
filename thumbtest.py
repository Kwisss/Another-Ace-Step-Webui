from PIL import Image, ImageDraw, ImageFilter
import random
import math

def neon_line(base_img, points, color):
    width, height = base_img.size
    for w, blur in [(16, 12), (8, 6), (3, 0)]:
        temp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        td = ImageDraw.Draw(temp)
        td.line(points, fill=color + (255,), width=w)

        if blur > 0:
            temp = temp.filter(ImageFilter.GaussianBlur(blur))

        base_img.alpha_composite(temp)

def triangle_wave(x):
    return 2 * abs(2 * (x % 1) - 1) - 1

def square_wave(x):
    return 1 if math.sin(x * 2 * math.pi) >= 0 else -1

def generate_memorable_neon(seed=42, width=1000, height=1000):
    random.seed(seed)
    base = Image.new("RGBA", (width, height), (0, 0, 0, 255))

    neon_colors = [
        (255, 50, 190),
        (50, 255, 50),
        (50, 100, 255),
        (255, 200, 50),
        (0, 255, 255),
        (255, 80, 80),
        (180, 80, 255),
    ]

    cx, cy = width // 2, height // 2

    # Global identity rules
    orientation = random.choice(["horizontal", "vertical", "diag_up", "diag_down"])
    waveform = random.choice(["sine", "triangle", "square"])

    def wave_func(t):
        if waveform == "sine":
            return math.sin(t)
        elif waveform == "triangle":
            return triangle_wave(t / (2 * math.pi))
        else:
            return square_wave(t / (2 * math.pi))

    amplitude = random.randint(80, 200)
    freq = random.uniform(0.005, 0.02)
    phase = random.uniform(0, math.pi * 2)
    spacing = random.randint(40, 80)

    # Generate coherent parallel waves
    for i in range(6):
        color = random.choice(neon_colors)
        offset = (i - 3) * spacing
        points = []

        for t in range(0, width, 5):
            val = wave_func(t * freq + phase) * amplitude

            if orientation == "horizontal":
                x = t
                y = int(cy + offset + val)

            elif orientation == "vertical":
                x = int(cx + offset + val)
                y = t

            elif orientation == "diag_up":
                x = t
                y = int((t * 0.5) + offset + val)

            else:  # diag_down
                x = t
                y = int((height - t * 0.5) + offset + val)

            # Only keep points that are on-screen
            if 0 <= x < width and 0 <= y < height:
                points.append((x, y))
            else:
                # Break the line when it exits screen to avoid long connecting strokes
                if len(points) > 1:
                    neon_line(base, points, color)
                points = []

        # Draw any remaining segment
        if len(points) > 1:
            neon_line(base, points, color)

    # Strict 2-color arc palette
    arc_palette = random.sample(neon_colors, 2)

    for _ in range(12):
        color = random.choice(arc_palette)
        radius = random.randint(100, 400)
        start = random.randint(0, 360)
        end = start + random.randint(40, 120)

        bbox = [(cx - radius, cy - radius), (cx + radius, cy + radius)]

        for w, blur in [(14, 10), (6, 4), (2, 0)]:
            temp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            td = ImageDraw.Draw(temp)
            td.arc(bbox, start=start, end=end, fill=color + (255,), width=w)

            if blur > 0:
                temp = temp.filter(ImageFilter.GaussianBlur(blur))

            base.alpha_composite(temp)

    final = Image.alpha_composite(
        Image.new("RGBA", (width, height), (0, 0, 0, 255)),
        base
    )
    return final.convert("RGB")

if __name__ == "__main__":
    img = generate_memorable_neon(seed=15)
    img.save("memorable_neon.png")
