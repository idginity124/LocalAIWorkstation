"""Bounded decoding at the image upload and generated-file boundaries."""
from __future__ import annotations

import io
from pathlib import Path
import warnings
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 12 * 1024**2
MAX_IMAGE_PIXELS = 16 * 1024**2
FORMATS = {'PNG':'.png', 'JPEG':'.jpg', 'WEBP':'.webp'}


def inspect_image(source: bytes | Path, *, verify: bool = True) -> dict:
    def open_image():
        return Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with open_image() as image:
                width, height = image.size
                if image.format not in FORMATS or width < 1 or height < 1:
                    raise ValueError('Geçerli bir PNG, JPEG veya WebP görseli seçin.')
                if width * height > MAX_IMAGE_PIXELS or max(width, height) > 16384:
                    raise ValueError('Görsel en fazla 16 megapiksel olmalı.')
                info = {'width':width, 'height':height, 'extension':FORMATS[image.format]}
                if verify:
                    image.verify()
            if verify:
                with open_image() as image:
                    image.load()
            return info
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError('Görsel okunamadı.') from error
