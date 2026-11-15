"""Native Krita document worker; all document calls run on the Qt main thread."""
import importlib
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4
from krita import Krita, Extension, InfoObject, Selection, QtCore
QtGui = importlib.import_module('PyQt' + QtCore.QT_VERSION_STR[0] + '.QtGui')
ANNOTATION = 'ai-workstation-editor-v1'


class Bridge(Extension):
    def setup(self):
        self.root = Path(os.environ['AI_KRITA_BRIDGE_ROOT'])
        # This must be set before openDocument, not after a dialog may open.
        Krita.instance().setBatchmode(True)
        self.document = None
        self.metadata = {}
        self.worker_id=uuid4().hex
        self.revision=0
        self.undo_stack, self.redo_stack = [], []
        self.history = self.root / 'history'
        self.history.mkdir(exist_ok=True)
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)
        (self.root / 'ready').write_text('ready')

    def createActions(self, window):
        pass

    def tick(self):
        request = self.root / 'request.json'
        if not request.exists(): return
        try:
            data = json.loads(request.read_text()); request.unlink()
            self.trace(data['op'] + ': start')
            result = {'ok': True, 'result': self.execute(data)}
        except Exception as error:
            result = {'ok': False, 'error': str(error)}
        self.trace('response: ' + ('ok' if result['ok'] else 'error'))
        tmp = self.root / 'response.tmp'
        tmp.write_text(json.dumps(result)); tmp.replace(self.root / 'response.json')

    def trace(self, stage):
        with (self.root/'operations.log').open('a') as stream:
            stream.write(str(time.time())+' '+stage+'\n')
            stream.flush()

    def ensure_view(self):
        app=Krita.instance()
        if not any(view.document()==self.doc() for view in app.views()):
            window=app.activeWindow()
            if window is None: raise RuntimeError('Sanal Krita penceresi hazır değil.')
            if window.addView(self.doc()) is None: raise RuntimeError('Krita belge görünümü oluşturulamadı.')
        self.doc().waitForDone()

    def doc(self):
        if self.document is None: raise ValueError('Önce bir görsel açın.')
        return self.document

    def input_path(self,data):
        name=data.get('_input_file')
        if not isinstance(name,str) or Path(name).name!=name or not name.startswith('input-') or not name.endswith('.png'):
            raise ValueError('Geçersiz geçici görsel adı.')
        return self.root/name

    def nodes(self): return self.doc().rootNode().childNodes()

    def node(self, data):
        node = next((n for n in self.nodes() if n.uniqueId().toString() == data.get('id')), None)
        if node is None: raise ValueError('Katman bulunamadı.')
        return node

    def paint_node(self, data):
        node = self.node(data)
        if node.locked(): raise ValueError('Katmanın kilidini açın.')
        if node.type() != 'paintlayer': raise ValueError('Bu işlem için bir piksel katmanı seçin.')
        return node

    def check_capacity(self):
        if len(self.nodes()) >= 20: raise ValueError('En fazla 20 katman kullanılabilir.')

    def annotate(self):
        self.doc().setAnnotation(ANNOTATION, 'Local AI editable layers', json.dumps(self.metadata).encode())

    def snapshot(self):
        doc = self.doc(); self.annotate(); doc.waitForDone()
        path = self.history / ('undo-' + uuid4().hex + '.kra')
        previous = doc.fileName()
        if not doc.saveAs(str(path)): raise RuntimeError('Geri alma kaydı oluşturulamadı; işlem yapılmadı.')
        doc.setFileName(previous)
        return path

    def restore(self, path):
        doc = Krita.instance().openDocument(str(path))
        if not doc: raise RuntimeError('Geri alma kaydı açılamadı.')
        doc.setBatchmode(True)
        old = self.document; self.document = doc
        try: self.metadata = json.loads(bytes(doc.annotation(ANNOTATION)))
        except (ValueError, TypeError): self.metadata = {}
        doc.setFileName('')
        if old: old.close()

    def trim_history(self):
        while len(self.undo_stack) > 8 or (len(self.undo_stack) > 1 and sum(p.stat().st_size for p in self.undo_stack) > 256*1024**2):
            self.undo_stack.pop(0).unlink(missing_ok=True)

    def execute(self, data):
        op = data['op']
        if op=='apply_result' and data.get('expected')!=self.version():raise ValueError('Belge AI çalışırken değişti. Sonuç galeride saklandı; mevcut çalışma değiştirilmedi.')
        if op=='apply_result' and 'text' in data:
            if len(self.nodes())>18:raise ValueError('Temizlenmiş görsel ve metin için iki boş katman yeri gerekli.')
            self.rect(data['rect'])
        if op == 'undo' or op == 'redo':
            source, target = (self.undo_stack,self.redo_stack) if op=='undo' else (self.redo_stack,self.undo_stack)
            if source:
                current=self.snapshot(); previous=source.pop()
                try: self.restore(previous)
                except Exception: source.append(previous); current.unlink(missing_ok=True); raise
                target.append(current); previous.unlink(missing_ok=True)
            self.revision+=1
            return self.state()
        checkpoint = None
        if self.document and op not in {'state','save','region'}: checkpoint=self.snapshot()
        try:
            self.mutate(data)
        except Exception:
            if checkpoint:
                self.restore(checkpoint); checkpoint.unlink(missing_ok=True)
            raise
        if checkpoint:
            self.undo_stack.append(checkpoint); self.trim_history()
            for p in self.redo_stack: p.unlink(missing_ok=True)
            self.redo_stack=[]
        if op not in {'state','save','region'}:self.revision+=1
        return self.state()

    def version(self):return self.worker_id+':'+str(self.revision)

    def rect(self, values=None):
        doc=self.doc()
        if values is None:
            selected=doc.selection()
            values=[selected.x(),selected.y(),selected.width(),selected.height()] if selected else [0,0,doc.width(),doc.height()]
        x,y,w,h=values
        if x<0 or y<0 or w<1 or h<1 or x+w>doc.width() or y+h>doc.height(): raise ValueError('Seçim görsel sınırları içinde olmalı.')
        return QtCore.QRect(x,y,w,h)

    def mutate(self, data):
        op=data['op']; app=Krita.instance()
        if op=='open':
            self.trace('open: import image')
            doc=app.openDocument(str(self.input_path(data)))
            self.trace('open: import complete')
            if not doc: raise RuntimeError('Görsel açılamadı.')
            doc.setBatchmode(True); old=self.document; self.document=doc; self.metadata={}
            if old: old.close()
            return
        if op=='blank' and not self.document:
            self.document=app.createDocument(data['width'],data['height'],'Local AI','RGBA','U8','sRGB-elle-V2-srgbtrc.icc',72)
            self.doc().setBatchmode(True)
        if op in {'blank','add','apply_result'}:
            self.check_capacity(); doc=self.doc()
            node=doc.createNode(data.get('name','Katman'),'paintlayer')
            doc.rootNode().addChildNode(node,None); doc.setActiveNode(node)
            if op in {'add','apply_result'}:
                imported=app.openDocument(str(self.input_path(data)))
                if not imported: raise RuntimeError('Katman açılamadı.')
                imported.setBatchmode(True)
                try:
                    if op=='apply_result':
                        if (imported.width(),imported.height())!=(doc.width(),doc.height()):raise ValueError('AI sonucu belge boyutuyla eşleşmiyor.')
                        for previous in self.nodes():
                            if previous.uniqueId()!=node.uniqueId():previous.setVisible(False)
                    w,h=min(doc.width(),imported.width()),min(doc.height(),imported.height())
                    if not node.setPixelData(imported.pixelData(0,0,w,h),0,0,w,h): raise RuntimeError('Katman eklenemedi.')
                finally: imported.close()
            if op=='apply_result' and 'text' in data:
                # Both layers belong to one outer checkpoint: failure restores
                # the old document, and one undo removes the whole replacement.
                self.mutate({key:value for key,value in data.items() if key in {'text','size','color','font','bold','rect'}}|{'op':'text'})
        elif op=='layer':
            node=self.node(data)
            for key, method in [('visible','setVisible'),('opacity','setOpacity'),('name','setName'),('locked','setLocked'),('blend','setBlendingMode')]:
                if key in data: getattr(node,method)(data[key])
        elif op=='duplicate':
            self.check_capacity(); node=self.node(data); clone=node.duplicate()
            if not clone: raise RuntimeError('Katman çoğaltılamadı.')
            self.doc().rootNode().addChildNode(clone,node); clone.setName(node.name()+' (2)')
            metadata=self.metadata.get(node.uniqueId().toString())
            if metadata: self.metadata[clone.uniqueId().toString()]=dict(metadata)
        elif op=='delete':
            node=self.node(data)
            if node.locked(): raise ValueError('Katmanın kilidini açın.')
            self.metadata.pop(node.uniqueId().toString(),None); node.remove()
        elif op=='reorder':
            nodes=self.nodes(); node=self.node(data); index=nodes.index(node)
            other=index+(1 if data['direction']=='up' else -1)
            if 0<=other<len(nodes):
                nodes[index],nodes[other]=nodes[other],nodes[index]
                self.doc().rootNode().setChildNodes(nodes)
        elif op=='move':
            node=self.node(data)
            if node.locked(): raise ValueError('Katmanın kilidini açın.')
            previous=node.position()
            metadata=self.metadata.get(node.uniqueId().toString())
            if metadata and metadata.get('kind')=='text':
                metadata['x']=metadata.get('x',30)+data['x']-previous.x()
                metadata['y']=metadata.get('y',60)+data['y']-previous.y()
            node.move(data['x'],data['y'])
        elif op=='transform':
            node=self.node(data)
            if node.locked(): raise ValueError('Katmanın kilidini açın.')
            self.metadata.pop(node.uniqueId().toString(),None)
            bounds=node.bounds()
            if bounds.width()<1 or bounds.height()<1:raise ValueError('Boş katman dönüştürülemez.')
            node.scaleNode(QtCore.QPointF(bounds.x(),bounds.y()),data['width'],data['height'],'Bicubic')
            if data.get('angle'): node.rotateNode(math.radians(data['angle']))
        elif op in {'text','shape'}:
            # The SVG text importer crashed in the user's Krita 6 build. Keep
            # editable parameters in a KRA annotation and render a dedicated
            # paint layer with Qt; do not invoke that unstable importer.
            self.trace('text/shape: raster parameters')
            node=self.node(data) if data.get('id') else None
            if node:
                if node.locked() or node.type()!='paintlayer' or node.uniqueId().toString() not in self.metadata:raise ValueError('Bu katman bu araçla düzenlenemez.')
                if node.position().x() or node.position().y():node.move(0,0)
            else:
                self.check_capacity();node=self.doc().createNode('Metin' if op=='text' else 'Şekil','paintlayer')
                self.doc().rootNode().addChildNode(node,None)
            w,h=self.doc().width(),self.doc().height()
            image=QtGui.QImage(w,h,QtGui.QImage.Format.Format_ARGB32);image.fill(QtCore.Qt.GlobalColor.transparent)
            painter=QtGui.QPainter(image);painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing);painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
            try:
                color=QtGui.QColor(data.get('color','#ffffff'))
                if op=='text':
                    family=data.get('font','Noto Sans')
                    if family not in {'Noto Sans','DejaVu Sans','Liberation Sans','Arial'}:raise ValueError('Desteklenmeyen yazı tipi.')
                    font=QtGui.QFont(family);font.setPixelSize(data['size']);font.setBold(data.get('bold',False));painter.setFont(font);painter.setPen(color)
                    if data.get('rect') is not None:
                        r=self.rect(data['rect'])
                        painter.setClipRect(r)
                        if '\n' in data['text']:raise ValueError('Bu araçta yeni metin tek satır olmalı.')
                        metrics=QtGui.QFontMetricsF(font)
                        bounds=metrics.boundingRect(data['text'])
                        ratio=min(1.0,r.width()/max(1,bounds.width()),r.height()/max(1,bounds.height()))
                        data['size']=max(1,int(data['size']*ratio));font.setPixelSize(data['size']);painter.setFont(font)
                        bounds=QtGui.QFontMetricsF(font).boundingRect(data['text'])
                        data['x']=round(r.x()+(r.width()-bounds.width())/2-bounds.x())
                        data['y']=round(r.y()+(r.height()-bounds.height())/2-bounds.y())
                    for index,line in enumerate(data['text'].splitlines()):painter.drawText(QtCore.QPointF(data.get('x',30),data.get('y',60)+index*data['size']*1.25),line)
                    node.setName(data['text'].splitlines()[0][:40])
                else:
                    r=self.rect(data['rect']);painter.setPen(QtCore.Qt.PenStyle.NoPen);painter.setBrush(QtGui.QBrush(color))
                    if data['kind']=='rectangle':painter.drawRect(r)
                    else:painter.drawEllipse(r)
            finally:painter.end()
            if not node.setPixelData(bytes(image.constBits().asstring(image.sizeInBytes())),0,0,w,h):raise RuntimeError('Metin/şekil katmanı yazılamadı.')
            self.metadata[node.uniqueId().toString()]={k:v for k,v in data.items() if k not in {'op','id'}}|{'kind':op}
            self.trace('text/shape: render complete')
        elif op=='selection':
            if data.get('rect') is None: self.doc().setSelection(None)
            else:
                r=self.rect(data['rect']); selected=Selection(); selected.select(r.x(),r.y(),r.width(),r.height(),255);self.doc().setSelection(selected)
        elif op in {'stroke','clear','fill'}:
            node=self.paint_node(data); self.metadata.pop(node.uniqueId().toString(),None); doc=self.doc(); w,h=doc.width(),doc.height()
            raw=bytes(node.pixelData(0,0,w,h))
            image=QtGui.QImage(raw,w,h,w*4,QtGui.QImage.Format.Format_ARGB32).copy()
            painter=QtGui.QPainter(image); painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setClipRect(self.rect())
            try:
                if op=='clear' or data.get('erase'): painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_DestinationOut)
                color=QtGui.QColor('#ffffff' if op=='clear' or data.get('erase') else data.get('color','#ffffff'))
                if op in {'clear','fill'}: painter.fillRect(self.rect(),color)
                else:
                    pen=QtGui.QPen(color,data['size'],QtCore.Qt.PenStyle.SolidLine,QtCore.Qt.PenCapStyle.RoundCap,QtCore.Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen); points=data['points']
                    if len(points)==1: painter.drawPoint(QtCore.QPointF(*points[0]))
                    else:
                        path=QtGui.QPainterPath(QtCore.QPointF(*points[0]))
                        for point in points[1:]:path.lineTo(QtCore.QPointF(*point))
                        painter.drawPath(path)
            finally:painter.end()
            if not node.setPixelData(bytes(image.constBits().asstring(image.sizeInBytes())),0,0,w,h): raise RuntimeError('Pikseller güncellenemedi.')
        elif op=='filter':
            node=self.paint_node(data); self.metadata.pop(node.uniqueId().toString(),None); name=data['filter']
            if name not in app.filters(): raise ValueError('Bu filtre kurulu Krita sürümünde yok.')
            r=self.rect();app.filter(name).apply(node,r.x(),r.y(),r.width(),r.height())
        elif op=='crop':
            r=self.rect(data['rect']);self.doc().crop(r.x(),r.y(),r.width(),r.height());self.doc().setSelection(None)
        elif op=='save':
            self.annotate()
            if not self.doc().saveAs(str(self.root/'project.kra')):raise RuntimeError('Proje kaydedilemedi.')
        elif op not in {'state','region'}:raise ValueError('Bilinmeyen işlem.')

    def state(self):
        doc=self.document
        if not doc:return {'layers':[],'width':0,'height':0,'can_undo':False,'can_redo':False,'version':self.version()}
        doc.refreshProjection();doc.waitForDone()
        self.trace('preview: export')
        preview=self.root/'preview-next.png'
        if not doc.exportImage(str(preview),InfoObject()):raise RuntimeError('Önizleme üretilemedi.')
        preview.replace(self.root/'preview.png')
        self.trace('preview: complete')
        selected=doc.selection()
        return {'version':self.version(),'features':['text_replacement'],'width':doc.width(),'height':doc.height(),'can_undo':bool(self.undo_stack),'can_redo':bool(self.redo_stack),
            'selection':[selected.x(),selected.y(),selected.width(),selected.height()] if selected else None,
            'filters':[f for f in ['invert','desaturate','gaussian blur'] if f in Krita.instance().filters()],
            'layers':[{'id':n.uniqueId().toString(),'name':n.name(),'type':n.type(),'visible':n.visible(),'opacity':n.opacity(),
                       'locked':n.locked(),'blend':n.blendingMode(),'x':n.position().x(),'y':n.position().y(),
                       'width':n.bounds().width(),'height':n.bounds().height(),'editable':self.metadata.get(n.uniqueId().toString())}
                      for n in reversed(self.nodes())]}


Krita.instance().addExtension(Bridge(Krita.instance()))
