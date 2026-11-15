import base64
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from app.masked_edit import prepare_region, composite_region, region_megapixels
from app.comfy import ComfyManager
from app.krita_commands import validate


def png(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


class MaskedEditingTests(unittest.TestCase):
    def test_processing_budget_tracks_crop_area_with_detail_floor_and_cap(self):
        self.assertEqual(region_megapixels((250, 450, 521, 727)), .262144)
        self.assertEqual(region_megapixels((10, 20, 810, 820)), .64)
        self.assertEqual(region_megapixels((0, 0, 2048, 2048)), 1.0)

    def test_every_unselected_pixel_including_alpha_is_preserved(self):
        original=Image.new('RGBA',(300,200),(31,77,123,190))
        mask=Image.new('RGBA',original.size,(255,255,255,0))
        for x in range(140,160):
            for y in range(90,110):mask.putpixel((x,y),(255,255,255,255))
        source,selection,context,_=prepare_region(png(original),png(mask))
        generated=png(Image.new('RGB',(27,51),'red'))
        with Image.open(io.BytesIO(composite_region(source,selection,context,generated))) as result:
            self.assertEqual(result.size,original.size)
            for y in range(original.height):
                for x in range(original.width):
                    expected=(255,0,0,255) if 140<=x<160 and 90<=y<110 else original.getpixel((x,y))
                    self.assertEqual(result.getpixel((x,y)),expected)

    def test_empty_and_mismatched_masks_rejected(self):
        source=png(Image.new('RGB',(20,20),'blue'))
        for mask in [Image.new('L',(20,20),0),Image.new('L',(19,20),255)]:
            with self.assertRaises(ValueError):prepare_region(source,png(mask))

    def test_instruction_workflow_returns_full_composited_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manager=ComfyManager(root/'comfy',root/'output')
            generated=manager.output_dir/'generated.png';generated.write_bytes(png(Image.new('RGB',(64,64),'green')))
            source=Image.new('RGB',(300,200),'red');mask=Image.new('L',source.size,0)
            mask.paste(255,(100,50,130,80))
            with patch.object(manager,'is_running',return_value=True),patch.object(manager,'edit_status',return_value={'ready':True}),patch.object(manager,'_run_workflow',return_value=([{'filename':generated.name,'subfolder':'LocalAIWorkstation'}],1.0)) as run:
                result=manager.edit('make green',base64.b64encode(png(source)).decode(),edit_mask=base64.b64encode(png(mask)).decode())
            self.assertEqual(run.call_args.args[0]['5']['inputs']['megapixels'], .262144)
            self.assertEqual(result['processing_megapixels'], .262144)
            self.assertTrue(result['masked']);self.assertEqual((result['width'],result['height']),(300,200))
            with Image.open(result['path']) as image:
                self.assertEqual(image.convert('RGB').getpixel((5,5)),(255,0,0))
                self.assertEqual(image.convert('RGB').getpixel((115,65)),(0,128,0))

    def test_unbounded_or_invalid_tool_commands_rejected(self):
        cases=[{'op':'stroke','id':'id','size':5,'points':[[float('nan'),2]]},
               {'op':'crop','rect':[-1,0,20,20]}, {'op':'move','id':'id','x':99999,'y':0},
               {'op':'text','text':'a','size':99999}, {'op':'layer','id':'id','locked':'yes'},
               {'op':'filter','id':'id','filter':'arbitrary'}]
        for data in cases:
            with self.subTest(data=data),self.assertRaises(ValueError):validate(data)

    def test_combined_text_result_requires_valid_text_bounds_and_size(self):
        base={'op':'apply_result','expected':'worker:1','text':'25','rect':[0,0,20,20],'size':18}
        self.assertEqual(validate(base),base)
        for override in ({'text':''},{'text':23},{'rect':None},{'rect':[-1,0,20,20]},{'size':None},{'size':9999}):
            with self.subTest(override=override),self.assertRaises(ValueError):validate(base|override)
