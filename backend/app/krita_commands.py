"""Bounded native editor command protocol; no arbitrary Krita actions or file paths."""
import math
import re

OPS = {'state','open','add','apply_result','save','layer','blank','duplicate','delete','reorder','move','transform',
       'text','shape','stroke','selection','clear','fill','crop','undo','redo','filter','region'}
FIELDS = {'op','id','visible','opacity','name','locked','blend','width','height','x','y','rect','points',
          'expected','size','color','text','font','bold','direction','angle','erase','kind','filter'}


def validate(command):
    if not isinstance(command, dict) or set(command)-FIELDS:
        raise ValueError('Bilinmeyen düzenleme alanı.')
    op=command.get('op')
    if not isinstance(op,str) or op not in OPS:
        raise ValueError('Bilinmeyen Krita işlemi.')
    if op=='apply_result' and (not isinstance(command.get('expected'),str) or len(command['expected'])>100):raise ValueError('AI sonucu için belge sürümü gerekli.')
    def integer(key, low, high, required=False):
        value=command.get(key)
        if value is None and not required:return
        if type(value) is not int or not low<=value<=high:raise ValueError(f'{key}: {low}–{high} arasında tam sayı olmalı.')
    if op in {'layer','duplicate','delete','reorder','move','transform','stroke','clear','fill','filter'}:
        if not isinstance(command.get('id'),str) or not 1<=len(command['id'])<=100:raise ValueError('Geçersiz katman kimliği.')
    for key in ['visible','locked','erase','bold']:
        if key in command and type(command[key]) is not bool:raise ValueError('Geçersiz doğru/yanlış alanı.')
    integer('opacity',0,255)
    for key in ['x','y']:integer(key,-4096,4096,op=='move')
    for key in ['width','height']:integer(key,1,2048,op in {'blank','transform'})
    integer('size',1,256,op in {'text','stroke'})
    integer('angle',-180,180)
    for key,limit in [('text',2000),('name',100),('font',100)]:
        if key in command and (not isinstance(command[key],str) or len(command[key])>limit):raise ValueError(f'Geçersiz {key} metni.')
    if op=='text' and (not isinstance(command.get('text'),str) or not command['text'].strip()):raise ValueError('Metin boş olamaz.')
    if op=='apply_result' and 'text' in command:
        if not command['text'].strip() or command.get('rect') is None:raise ValueError('Yeni metin ve metin alanı gerekli.')
        integer('size',1,256,True)
    if 'color' in command and not re.fullmatch(r'#[0-9a-fA-F]{6}',str(command['color'])):raise ValueError('Geçersiz renk.')
    if 'blend' in command and command['blend'] not in {'normal','multiply','screen','overlay'}:raise ValueError('Geçersiz karışım modu.')
    if op=='reorder' and command.get('direction') not in {'up','down'}:raise ValueError('Geçersiz sıralama yönü.')
    if op=='shape' and command.get('kind') not in {'rectangle','ellipse'}:raise ValueError('Geçersiz şekil.')
    if op=='filter' and command.get('filter') not in {'invert','desaturate','gaussian blur'}:raise ValueError('Geçersiz filtre.')
    rect=command.get('rect')
    if op in {'crop','shape','region'} and rect is None:raise ValueError('Önce bir alan seçin.')
    if rect is not None:
        if not isinstance(rect,list) or len(rect)!=4 or any(type(v) is not int for v in rect):raise ValueError('Geçersiz seçim alanı.')
        if not (0<=rect[0]<2048 and 0<=rect[1]<2048 and 1<=rect[2]<=2048 and 1<=rect[3]<=2048):raise ValueError('Seçim görsel sınırları içinde olmalı.')
    if op=='stroke':
        points=command.get('points')
        if not isinstance(points,list) or not 1<=len(points)<=2000:raise ValueError('Fırça izi 1–2000 nokta içermeli.')
        for point in points:
            if not isinstance(point,list) or len(point)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=2048 for v in point):raise ValueError('Geçersiz fırça noktası.')
    return command
