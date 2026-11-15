"""Exercise the real offscreen Krita engine without changing the main UI."""
from pathlib import Path
import io
import json
import sys
import time
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'backend'))
from PIL import Image, ImageChops
from app.krita_bridge import KritaBridge


def png(color):
    output = io.BytesIO()
    Image.new('RGBA', (64, 64), color).save(output, format='PNG')
    return output.getvalue()


def run():
    root = PROJECT / 'runtime-reports' / ('krita-bridge-' + time.strftime('%Y%m%d-%H%M%S'))
    root.mkdir(parents=True, mode=0o700)
    bridge = KritaBridge(root, progress=lambda message: print(message, flush=True))
    report = {'passed': False, 'checks': [], 'directory': str(root)}
    try:
        print('Krita görünür pencere açmadan başlatılıyor…', flush=True)
        assert bridge.execute({'op': 'state'})['width'] == 0
        report['checks'].append('Krita Python eklentisi hazır')
        state = bridge.execute({'op': 'open'}, png('red'))
        assert state['width'] == 64 and state['height'] == 64
        assert len(state['layers']) == 1
        report['checks'].append('Görsel açıldı')
        first = state['layers'][0]['id']
        state = bridge.execute({'op': 'add'}, png('blue'))
        assert len(state['layers']) == 2
        added = next(n['id'] for n in state['layers'] if n['id'] != first)
        report['checks'].append('İkinci görsel ayrı katmana eklendi')
        bridge.execute({'op': 'layer', 'id': added, 'opacity': 128})
        state = bridge.execute({'op': 'layer', 'id': added, 'visible': False})
        assert not next(n for n in state['layers'] if n['id'] == added)['visible']
        with Image.open(root / 'preview.png') as image:
            assert image.convert('RGB').getpixel((32, 32)) == (255, 0, 0)
        report['checks'].append('Katman görünürlüğü/saydamlığı değiştirildi; PNG sonucu doğrulandı')
        bridge.execute({'op': 'save'})
        with zipfile.ZipFile(root / 'project.kra') as project:
            assert project.read('mimetype') == b'application/x-krita'
        report['checks'].append('Katmanlı Krita projesi doğrulandı')
        print('Genişletilmiş araçlar sınanıyor…', flush=True)
        bridge.execute({'op':'selection','rect':[8,8,16,16]})
        bridge.execute({'op':'fill','id':first,'color':'#00ff00'})
        with Image.open(root/'preview.png') as image:
            assert image.convert('RGB').getpixel((10,10))==(0,255,0), 'Seçim içi dolgu'
            assert image.convert('RGB').getpixel((1,1))==(255,0,0), 'Seçim dışı koruma'
        bridge.execute({'op':'undo'})
        with Image.open(root/'preview.png') as image:assert image.convert('RGB').getpixel((10,10))==(255,0,0), 'Geri alma'
        bridge.execute({'op':'redo'})
        state=bridge.execute({'op':'stroke','id':first,'points':[[10,10],[16,16]],'size':3,'color':'#000000'})
        bridge.execute({'op':'clear','id':first})
        with Image.open(root/'preview.png') as image:assert image.convert('RGBA').getpixel((10,10))[3]==0, 'Seçili alanı silme'
        bridge.execute({'op':'selection','rect':None})
        state=bridge.execute({'op':'move','id':first,'x':2,'y':3})
        moved=next(n for n in state['layers'] if n['id']==first)
        assert (moved['x'],moved['y'])==(2,3), 'Katman taşıma'
        report['checks'].append('Seçim, dolgu, fırça, silme, taşıma, geri alma/yineleme')
        print('Metin aracı sınanıyor…',flush=True)
        state=bridge.execute({'op':'text','text':'NowLearn','size':12,'color':'#ffffff','font':'Noto Sans','bold':True,'x':4,'y':20})
        text_layer=next(n for n in state['layers'] if n.get('editable',{} ) and n['editable'].get('kind')=='text')
        state=bridge.execute({'op':'text','id':text_layer['id'],'text':'Academy','size':12,'color':'#ffffff','font':'Noto Sans','bold':True,'x':4,'y':20})
        assert next(n for n in state['layers'] if n['id']==text_layer['id'])['editable']['text']=='Academy'
        state=bridge.execute({'op':'duplicate','id':text_layer['id']})
        state=bridge.execute({'op':'shape','kind':'ellipse','rect':[4,4,8,8],'color':'#ffff00'})
        report['checks'].append('Parametreleri saklanan metin katmanı, çoğaltma ve şekil')
        state=bridge.execute({'op':'crop','rect':[0,0,32,32]})
        assert (state['width'],state['height'])==(32,32)
        state=bridge.execute({'op':'undo'})
        assert (state['width'],state['height'])==(64,64)
        report['checks'].append('Kırpma ve kırpmayı geri alma')
        bridge.execute({'op':'save'})
        # A full composited result must not double the original alpha when
        # installed as an AI layer above the preserved document.
        transparent=png((31,77,123,128))
        state=bridge.execute({'op':'open'},transparent)
        with Image.open(root/'preview.png') as image:before=image.convert('RGBA').tobytes()
        state=bridge.execute({'op':'apply_result','name':'AI','expected':state['version']},transparent)
        with Image.open(root/'preview.png') as image:assert image.convert('RGBA').tobytes()==before, 'AI katmanı alfa koruması'
        assert sum(n['visible'] for n in state['layers'])==1
        bridge.execute({'op':'undo'})
        report['checks'].append('AI sonuç katmanı, orijinal katmanları koruma ve şeffaflık doğrulaması')
        state=bridge.execute({'op':'state'})
        state=bridge.execute({'op':'apply_result','expected':state['version'],'text':'25','size':24,'rect':[16,16,32,32],
                              'font':'Noto Sans','bold':True,'color':'#000000'},png((255,255,255,255)))
        text_layers=[n for n in state['layers'] if n.get('editable',{}).get('kind')=='text']
        assert len(text_layers)==1 and text_layers[0]['editable']['text']=='25'
        with Image.open(root/'preview.png') as image:
            changed=ImageChops.difference(image.convert('RGB'),Image.new('RGB',(64,64),'white')).getbbox()
            assert changed and changed[0]>=16 and changed[1]>=16 and changed[2]<=48 and changed[3]<=48
        bridge.execute({'op':'undo'})
        with Image.open(root/'preview.png') as image:assert image.convert('RGBA').tobytes()==before
        report['checks'].append('Metni aynen yazma, ayrı metin katmanı ve birleşik işlemi tek hamlede geri alma')
        report['passed'] = True
        print('BAŞARILI: Krita motoru arayüz bağlantısı için hazır.', flush=True)
    except KeyboardInterrupt:
        report['error'] = 'Test kullanıcı tarafından durduruldu.'
        print(report['error'], flush=True)
    except Exception as error:
        report['error'] = str(error)
        print('Test tamamlanamadı: ' + str(error), flush=True)
    finally:
        bridge.close()
        (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('Rapor: ' + str(root / 'report.json'), flush=True)
        print('Krita kaydı: ' + str(root / 'worker.log'), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(run())
