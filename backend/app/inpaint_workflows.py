"""Local masked workflows. No model downloads or third-party code execution here."""
import io
from PIL import Image

CHECKPOINT = 'RealVisXL_V5.0_fp16.safetensors'
LAMA = 'big-lama.pt'
HEAD = 'fooocus_inpaint_head.pth'
PATCH = 'inpaint_v26.fooocus.patch'


def assets(root, engine):
    names = [('inpaint', LAMA)] if engine == 'lama' else [('checkpoints', CHECKPOINT), ('inpaint', HEAD), ('inpaint', PATCH)]
    return [root / 'models' / folder / name for folder, name in names]


def inputs(source, selection, context, engine):
    image = source.crop(context).convert('RGB')
    mask = selection.crop(context)
    # Dedicated inpainting must receive the mask, including feathered boundaries.
    # Keep modest native crops; cap large ones, and use aligned SDXL dimensions.
    if engine == 'sdxl':
        scale = min(1024 / max(image.size), max(1, 512 / (image.width * image.height) ** .5))
        size = tuple(max(64, round(side * scale / 64) * 64) for side in image.size)
        image = image.resize(size, Image.Resampling.LANCZOS)
        mask = mask.resize(size, Image.Resampling.BILINEAR)
    elif max(image.size) > 1024:
        size = tuple(max(1, round(side * 1024 / max(image.size))) for side in image.size)
        image = image.resize(size, Image.Resampling.LANCZOS)
        mask = mask.resize(size, Image.Resampling.BILINEAR)
    def png(value):
        buffer = io.BytesIO(); value.save(buffer, format='PNG'); return buffer.getvalue()
    return png(image), png(mask), image.size


def workflow(engine, image_name, mask_name, prompt, seed):
    graph = {
        '1': {'class_type':'LoadImage', 'inputs':{'image':image_name}},
        '2': {'class_type':'LoadImage', 'inputs':{'image':mask_name}},
        '3': {'class_type':'ImageToMask', 'inputs':{'image':['2',0], 'channel':'red'}},
    }
    if engine == 'lama':
        graph.update({
            '4': {'class_type':'INPAINT_LoadInpaintModel', 'inputs':{'model_name':LAMA}},
            '5': {'class_type':'INPAINT_InpaintWithModel', 'inputs':{'inpaint_model':['4',0], 'image':['1',0], 'mask':['3',0], 'seed':seed}},
            '20': {'class_type':'SaveImage', 'inputs':{'images':['5',0], 'filename_prefix':'LocalAIWorkstation/LaMa-Remove'}},
        })
    elif engine == 'sdxl':
        graph.update({
            '4': {'class_type':'CheckpointLoaderSimple', 'inputs':{'ckpt_name':CHECKPOINT}},
            '5': {'class_type':'CLIPTextEncode', 'inputs':{'clip':['4',1], 'text':prompt}},
            '6': {'class_type':'CLIPTextEncode', 'inputs':{'clip':['4',1], 'text':'blurry, distorted, watermark'}},
            '7': {'class_type':'VAEEncodeForInpaint', 'inputs':{'pixels':['1',0], 'vae':['4',2], 'mask':['3',0], 'grow_mask_by':8}},
            '8': {'class_type':'INPAINT_LoadFooocusInpaint', 'inputs':{'head':HEAD, 'patch':PATCH}},
            '9': {'class_type':'INPAINT_ApplyFooocusInpaint', 'inputs':{'model':['4',0], 'patch':['8',0], 'latent':['7',0]}},
            '10': {'class_type':'KSampler', 'inputs':{'model':['9',0], 'seed':seed, 'steps':20, 'cfg':5.0, 'sampler_name':'dpmpp_2m', 'scheduler':'karras', 'positive':['5',0], 'negative':['6',0], 'latent_image':['7',0], 'denoise':1.0}},
            '11': {'class_type':'VAEDecode', 'inputs':{'samples':['10',0], 'vae':['4',2]}},
            '20': {'class_type':'SaveImage', 'inputs':{'images':['11',0], 'filename_prefix':'LocalAIWorkstation/SDXL-Inpaint'}},
        })
    else:
        raise ValueError('Bilinmeyen alan düzenleme motoru.')
    return graph
