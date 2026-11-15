"""Selection-preserving composition for instruction models, not a native inpaint model."""
import io
from PIL import Image, ImageChops
from .image_files import inspect_image


def region_megapixels(context: tuple[int, int, int, int]) -> float:
    """Keep small edits near 512² instead of enlarging every crop to 1MP.

    Larger selections keep their native area up to the existing 1MP budget.
    A 512² floor retains useful context/detail for the instruction model.
    """
    x0, y0, x1, y1 = context
    return min(1.0, max(512 * 512, (x1 - x0) * (y1 - y0)) / 1_000_000)


def prepare_region(original: bytes, mask: bytes):
    info, selected_info = inspect_image(original), inspect_image(mask)
    if (info['width'],info['height']) != (selected_info['width'],selected_info['height']):
        raise ValueError('Seçim maskesi görselle aynı boyutta olmalı.')
    with Image.open(io.BytesIO(original)) as source: source=source.convert('RGBA')
    with Image.open(io.BytesIO(mask)) as image:
        selected=ImageChops.multiply(image.convert('L'),image.convert('RGBA').getchannel('A'))
    bbox=selected.getbbox()
    if bbox is None: raise ValueError('Önce fırçayla bir alan işaretleyin.')
    x0,y0,x1,y1=bbox
    context=(max(0,x0-96),max(0,y0-96),min(source.width,x1+96),min(source.height,y1+96))
    out=io.BytesIO();source.crop(context).save(out,format='PNG')
    return source,selected,context,out.getvalue()


def composite_region(source, mask, context, generated: bytes) -> bytes:
    inspect_image(generated)
    x0,y0,x1,y1=context
    with Image.open(io.BytesIO(generated)) as result:
        patch=result.convert('RGBA').resize((x1-x0,y1-y0),Image.Resampling.LANCZOS)
    merged=source.copy()
    original=source.crop(context)
    # A zero-valued mask pixel copies the original pixel exactly, including alpha.
    merged.paste(Image.composite(patch,original,mask.crop(context)),(x0,y0))
    output=io.BytesIO();merged.save(output,format='PNG')
    return output.getvalue()
