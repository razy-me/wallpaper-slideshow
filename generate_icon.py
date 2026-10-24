import os
from PIL import Image, ImageDraw

def generate_ico(output_path):
    img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded card frame (blue)
    d.rounded_rectangle([2, 4, 30, 26], radius=4, fill=(41, 128, 185, 255), outline=(255, 255, 255, 255), width=2)

    # Sun (yellow)
    d.ellipse([7, 8, 13, 14], fill=(241, 196, 15, 255))

    # Mountains (emerald green)
    d.polygon([(4, 25), (14, 13), (23, 25)], fill=(46, 204, 113, 255))
    d.polygon([(16, 25), (22, 17), (29, 25)], fill=(39, 174, 96, 255))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    img.save(output_path, format='ICO', sizes=[(32, 32), (16, 16)])
    print(f"Icon generated: {output_path}")

if __name__ == '__main__':
    ico_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
    generate_ico(ico_file)
