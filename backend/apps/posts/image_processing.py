from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps


def optimize_post_image(
    image_file,
    *,
    max_width: int = 1600,
    max_height: int = 1600,
    quality: int = 80,
):
    image = Image.open(image_file)
    image = ImageOps.exif_transpose(image)
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")
    image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", optimize=True, progressive=True, quality=quality)
    return ContentFile(buffer.getvalue(), name="post-image.jpg")
