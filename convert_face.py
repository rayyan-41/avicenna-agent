import sys
from PIL import Image
from pathlib import Path

# Configuration: Adjust width to fit your terminal nicely
# 40-50 characters is usually good for a "logo" size
OUTPUT_WIDTH = 46 

def convert_image_to_ansi(image_path, output_path):
    try:
        img = Image.open(image_path)
    except FileNotFoundError:
        print(f"❌ Error: Could not find {image_path}")
        return

    # 1. Resize image maintaining aspect ratio
    # Terminal fonts are roughly 2x as tall as they are wide, so we adjust height
    aspect_ratio = img.height / img.width
    new_height = int(OUTPUT_WIDTH * aspect_ratio * 0.55)
    img = img.resize((OUTPUT_WIDTH, new_height), Image.Resampling.LANCZOS)
    
    # 2. Convert to RGB
    img = img.convert('RGB')
    
    # 3. Generate ANSI string
    ansi_art = []
    pixels = img.load()
    
    for y in range(img.height):
        line = ""
        for x in range(img.width):
            r, g, b = pixels[x, y]
            # \033[38;2;R;G;Bm sets the FOREGROUND color
            # █ is a full block character
            line += f"\033[38;2;{r};{g};{b}m█"
        line += "\033[0m" # Reset color at end of line
        ansi_art.append(line)
    
    # 4. Save to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ansi_art))
    
    print(f"✅ Success! Saved ANSI art to {output_path}")

if __name__ == "__main__":
    # Ensure raw image exists in root
    source = Path("avicenna.png")
    if not source.exists():
        print("❌ Place 'avicenna.png' in this folder first!")
    else:
        convert_image_to_ansi("avicenna.png", "source/avicenna/face.ans")