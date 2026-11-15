"""Measure two real local masked jobs; requires the UI's managed ComfyUI service."""
import argparse
import base64
import io
import json
from pathlib import Path
import time
import urllib.request
import uuid
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE='http://127.0.0.1:8000'


def request(path, data=None, token=None):
    headers={'Content-Type':'application/json'}
    if token:headers['X-CSRF-Token']=token
    value=urllib.request.Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
    with OPENER.open(value,timeout=15) as response:return json.load(response)


def run(engine):
    root=ROOT/'runtime-reports'/('inpaint-speed-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    root.mkdir(parents=True,mode=0o700)
    report={'engine':engine,'runs':[],'passed':False}
    current=None;token=None
    try:
        token=request('/api/v1/session')['csrf_token']
        status=request('/api/v1/image/edit-engines')
        if not status[engine]['available']:raise RuntimeError('Modelleri kurup uygulamadaki ComfyUI servisini başlatın.')
        source=Image.new('RGB',(384,384))
        for y in range(384):
            for x in range(384):source.putpixel((x,y),(160+x//8,170+y//8,180))
        ImageDraw.Draw(source).rectangle((166,166,217,217),fill='#2244ff')
        mask=Image.new('L',source.size,0);ImageDraw.Draw(mask).rectangle((160,160,223,223),fill=255)
        source.save(root/'source.png');mask.save(root/'mask.png')
        def encoded(image):
            out=io.BytesIO();image.save(out,format='PNG');return base64.b64encode(out.getvalue()).decode()
        for index in range(2):
            start=time.monotonic()
            job=request('/api/v1/image/jobs',{'mode':'edit','engine':engine,'prompt':'a red apple on a gray surface' if engine=='sdxl' else 'Remove marked content',
                        'init_image':encoded(source),'edit_mask':encoded(mask),'seed':index+100,'idempotency_key':str(uuid.uuid4())},token)
            current=job['id'];print(f'{engine}: {index+1}. iş başladı…',flush=True)
            while time.monotonic()-start<660:
                state=request('/api/v1/image/jobs/'+current)
                if state['status']=='COMPLETED':break
                if state['status'] in {'FAILED','INTERRUPTED','RECOVERY_REQUIRED'}:raise RuntimeError(str(state.get('error',state['status'])))
                time.sleep(.5)
            else:raise TimeoutError('İş tamamlanmadı.')
            current=None
            result=state['result'];url=result['url']
            if not url.startswith('/api/v1/image/output/'):raise ValueError('Beklenmeyen çıktı adresi.')
            with OPENER.open(BASE+url,timeout=15) as response:raw=response.read()
            path=root/f'result-{index+1}.png';path.write_bytes(raw)
            with Image.open(io.BytesIO(raw)) as image:
                image=image.convert('RGB')
                if image.size!=source.size:raise AssertionError('Çıktı boyutu değişti.')
                for y in range(384):
                    for x in range(384):
                        if not mask.getpixel((x,y)) and image.getpixel((x,y))!=source.getpixel((x,y)):
                            raise AssertionError('Maske dışındaki piksel değişti.')
            seconds=round(time.monotonic()-start,2)
            report['runs'].append({'seconds':seconds,'result':result,'outside_mask_preserved':True})
            print(f'{engine}: {index+1}. iş {seconds} saniye; maske dışı korundu.',flush=True)
        report['passed']=True
        print('Görsel kaliteyi source.png ile result dosyalarını karşılaştırarak kontrol edin.',flush=True)
    except BaseException as error:
        report['error']=str(error) or type(error).__name__
        print('Test tamamlanamadı: '+report['error'],flush=True)
    finally:
        if current and token:
            try:request('/api/v1/image/jobs/'+current+'/cancel',{},token)
            except Exception:pass
        (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print('Rapor: '+str(root/'report.json'),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--engine',choices=['lama','sdxl'],default='lama')
    raise SystemExit(run(parser.parse_args().engine))
