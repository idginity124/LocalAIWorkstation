import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app.comfy import ComfyManager
from app.inpaint_workflows import inputs, workflow
from app.image_jobs import ImageRequest


def png(image):
    out=io.BytesIO();image.save(out,format='PNG');return out.getvalue()


class InpaintTests(unittest.TestCase):
    def test_both_engines_receive_a_real_noninverted_mask(self):
        source=Image.new('RGBA',(800,600),'red');mask=Image.new('L',source.size,0)
        mask.paste(255,(350,250,450,350))
        for engine in ('lama','sdxl'):
            a,b,size=inputs(source,mask,(250,150,550,450),engine)
            with Image.open(io.BytesIO(a)) as image,Image.open(io.BytesIO(b)) as selected:
                self.assertEqual(image.size,selected.size)
                self.assertEqual(image.size,size)
                self.assertEqual(selected.getpixel((size[0]//2,size[1]//2)),255)
                self.assertEqual(selected.getpixel((0,0)),0)
            graph=workflow(engine,'source.png','mask.png','a flower',10)
            self.assertEqual(graph['2']['inputs']['image'],'mask.png')
            self.assertEqual(graph['3']['inputs']['channel'],'red')
            target='5' if engine=='lama' else '7'
            self.assertEqual(graph[target]['inputs']['mask'],['3',0])

    def test_lama_does_not_load_a_diffusion_or_text_encoder(self):
        graph=workflow('lama','a.png','b.png','ignored',1)
        names={node['class_type'] for node in graph.values()}
        self.assertNotIn('CLIPTextEncode',names);self.assertNotIn('KSampler',names)
        with self.assertRaises(ValueError):workflow('unknown','a','b','c',0)

    def test_large_inputs_are_bounded(self):
        source=Image.new('RGB',(2048,2048));mask=Image.new('L',source.size,255)
        for engine in ('lama','sdxl'):
            _,_,size=inputs(source,mask,(0,0,2048,2048),engine)
            self.assertLessEqual(max(size),1024)

    def test_real_manager_preserves_every_unselected_pixel_and_cleans_both_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=ComfyManager(Path(tmp)/'comfy',Path(tmp)/'output')
            source=Image.new('RGBA',(300,200),(33,77,11,192));mask=Image.new('L',source.size,0);mask.paste(255,(140,90,160,110))
            generated=manager.output_dir/'generated.png';generated.write_bytes(png(Image.new('RGB',(256,256),'blue')))
            def run(graph):
                directory=manager.comfy_root/'input'
                self.assertTrue((directory/graph['1']['inputs']['image']).is_file())
                self.assertTrue((directory/graph['2']['inputs']['image']).is_file())
                return ([{'filename':generated.name,'subfolder':'LocalAIWorkstation'}],.2)
            for engine in ('lama','sdxl'):
                node='INPAINT_InpaintWithModel' if engine=='lama' else 'INPAINT_ApplyFooocusInpaint'
                with patch.object(manager,'is_running',return_value=True),patch.object(manager,'inpaint_status',return_value={engine:{'ready':True}}),patch.object(manager,'_request_json',return_value={node:{}}),patch.object(manager,'_run_workflow',side_effect=run):
                    result=manager.edit('test',base64.b64encode(png(source)).decode(),edit_mask=base64.b64encode(png(mask)).decode(),engine=engine)
                self.assertEqual(result['engine'],engine)
                with Image.open(result['path']) as image:
                    for y in range(200):
                        for x in range(300):
                            self.assertEqual(image.getpixel((x,y)),(0,0,255,255) if 140<=x<160 and 90<=y<110 else source.getpixel((x,y)))
                self.assertEqual(list((manager.comfy_root/'input').iterdir()),[])

    def test_engine_is_an_enum_and_old_requests_still_default_to_flux(self):
        self.assertEqual(ImageRequest(prompt='test',idempotency_key='test').engine,'flux')
        with self.assertRaises(ValueError):ImageRequest(prompt='test',idempotency_key='test',engine='arbitrary')
