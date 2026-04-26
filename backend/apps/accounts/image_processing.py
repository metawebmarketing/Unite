from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image


def optimize_profile_image(
    image_file,
    *,
    crop_x: int | None = None,
    crop_y: int | None = None,
    crop_size: int | None = None,
    output_size: int = 256,
):
    image = Image.open(image_file).convert("RGB")
    width, height = image.size
    if crop_size and crop_size > 0:
        x = max(0, int(crop_x or 0))
        y = max(0, int(crop_y or 0))
        size = min(int(crop_size), width - x, height - y)
        if size > 0:
            image = image.crop((x, y, x + size, y + size))
    else:
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        image = image.crop((left, top, left + side, top + side))
    image = image.resize((output_size, output_size))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", optimize=True, quality=85)
    return ContentFile(buffer.getvalue(), name="profile.jpg")
