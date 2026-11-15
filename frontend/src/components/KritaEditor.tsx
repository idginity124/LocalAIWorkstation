import React from 'react';
import { t, localizeMessage } from '../i18n';
import { responseJson, sendJson } from '../lib/shared';
import { Icon } from './Icon';
import { textEditPrompt } from '../lib/textEdit';

type Layer = { id: string; name: string; visible: boolean; opacity: number; locked?:boolean; type?:string; blend?:string; x?:number; y?:number; width?:number; height?:number; editable?:Record<string,unknown> };
type Document = { version?:string; features?:string[]; width: number; height: number; layers: Layer[]; can_undo?:boolean; can_redo?:boolean; selection?:number[]|null; filters?:string[] };
type Tool = 'mark'|'unmark'|'select'|'brush'|'erase'|'move'|'text'|'crop'|'shape';
type MaskStroke = { points:number[][]; size:number; erase:boolean; clear?:boolean };
type Props = { embedded?:boolean;  onClose: () => void; selectedImage?: string; onSendToAI: (file: File) => Promise<void> };

function encode(file: Blob): Promise<string> {
  if (file.size > 12 * 1024 ** 2) return Promise.reject(new Error(t('Görsel en fazla 12 MiB olmalı.')));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error(t('Görsel yüklenemedi.')));
    reader.readAsDataURL(file);
  });
}

export function KritaEditor({ onClose, selectedImage, onSendToAI, embedded=false }: Props) {
  const dialog = React.useRef<HTMLDialogElement>(null);
  const lock = React.useRef(false);
  const mounted=React.useRef(true);
  React.useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const [doc, setDoc] = React.useState<Document | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const [revision, setRevision] = React.useState(0);
  const [projectReady, setProjectReady] = React.useState(false);
  const [opacity, setOpacity] = React.useState<Record<string, number>>({});
  const [starting, setStarting] = React.useState(false);
  const [dragging, setDragging] = React.useState(false);
  const [activeId, setActiveId] = React.useState('');
  const hasImage = !!doc?.width;
  const activeLayer = doc?.layers.find(layer => layer.id === activeId) ?? doc?.layers[0];
  const [tool,setTool]=React.useState<Tool>('mark');
  const [size,setSize]=React.useState(40);
  const [color,setColor]=React.useState('#ffffff');
  const [text,setText]=React.useState('');
  const [font,setFont]=React.useState('Noto Sans');
  const [bold,setBold]=React.useState(true);
  const [textPoint,setTextPoint]=React.useState<[number,number]>([40,80]);
  const [rect,setRect]=React.useState<number[]|null>(null);
  const [shapeKind,setShapeKind]=React.useState('rectangle');
  const [marked,setMarked]=React.useState(false);
  const [bubble,setBubble]=React.useState<[number,number]>([50,50]);
  const [instruction,setInstruction]=React.useState('');
  const [regionMode,setRegionMode]=React.useState<'remove'|'fill'|'text'|'instruction'>('remove');
  const [replacement,setReplacement]=React.useState('');
  const [originalText,setOriginalText]=React.useState('');
  const [engines,setEngines]=React.useState<Record<string,{ready:boolean;available:boolean}>|null>(null);
  const [engineError,setEngineError]=React.useState(false);
  const refreshEngines=()=>{
    setEngineError(false);
    void fetch('/api/v1/image/edit-engines').then(responseJson).then(value=>setEngines(value as Record<string,{ready:boolean;available:boolean}>)).catch(()=>setEngineError(true));
  };
  React.useEffect(()=>{if(hasImage)refreshEngines();},[hasImage]);
  const [aiJob,setAiJob]=React.useState('');
  const [showBefore,setShowBefore]=React.useState(false);
  const [zoom,setZoom]=React.useState('fit');
  const [cursor,setCursor]=React.useState<[number,number]|null>(null);
  const [layerName,setLayerName]=React.useState('');
  const [transform,setTransform]=React.useState({width:1,height:1,angle:0});
  React.useEffect(()=>{if(activeLayer){setLayerName(activeLayer.name);setTransform({width:Math.max(1,activeLayer.width??1),height:Math.max(1,activeLayer.height??1),angle:0});}},[activeLayer?.id]);
  const maskCanvas=React.useRef<HTMLCanvasElement|null>(null);
  const maskBase=React.useRef<HTMLCanvasElement|null>(null);
  const maskPast=React.useRef<MaskStroke[]>([]);
  const maskFuture=React.useRef<MaskStroke[]>([]);
  const [maskHistory,setMaskHistory]=React.useState({undo:false,redo:false});
  const overlay=React.useRef<HTMLCanvasElement>(null);
  const gesture=React.useRef<{points:number[][];start:[number,number];mask?:MaskStroke}|null>(null);
  const regionKey=React.useRef({fingerprint:'',key:''});
  const baseImage=React.useRef('');
  const preview = `/api/v1/krita/preview?v=${revision}`;
  React.useEffect(()=>{drawMaskPreview();},[showBefore,revision]);

  React.useEffect(() => { if (!embedded) dialog.current?.showModal(); }, [embedded]);

  const run = async (operation: () => Promise<void>) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await operation(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t('İşlem başarısız.')); }
    finally { lock.current = false; setBusy(false); setStarting(false); drawMaskPreview(); }
  };
  const command = async (data: Record<string, unknown>) => {
    const result = await sendJson('/api/v1/krita/command', 'POST', data) as unknown as Document;
    setShowBefore(false);setDoc(result); setOpacity({}); setRevision(value => value + 1);
    setActiveId(current => ['open','add','apply_result','text','shape','blank','duplicate'].includes(String(data.op)) || !result.layers.some(layer => layer.id === current) ? result.layers[0]?.id ?? '' : current);
    setProjectReady(data.op === 'save');
    setRect(result.selection ?? null);
    if(data.op==='open'){baseImage.current='';setZoom('fit');setCursor(null);}
    if (['open','crop','undo','redo'].includes(String(data.op))) clearMask();
  };
  const importFile = (file: File | undefined, op: 'open' | 'add') => {
    if (!file) return;
    void run(async () => { setStarting(!doc); await command({ op, image: await encode(file) }); });
  };
  const importSelected = (op: 'open' | 'add') => void run(async () => {
    if (!selectedImage) return;
    setStarting(!doc);
    const response = await fetch(selectedImage);
    if (!response.ok) throw new Error(t('Görsel yüklenemedi.'));
    await command({ op, image: await encode(await response.blob()) });
  });

  const fileInput = (op: 'open' | 'add') => <input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy}
    onChange={event => { importFile(event.target.files?.[0], op); event.target.value = ''; }}/>;
  const sendToAI = () => void run(async () => {
    const response = await fetch(preview);
    if (!response.ok) throw new Error(t('Görsel yüklenemedi.'));
    await onSendToAI(new File([await response.blob()], 'krita-edit.png', { type: 'image/png' }));
    onClose();
  });

  function drawMaskPreview() {
    const view=overlay.current,mask=maskCanvas.current;
    if(!view)return;
    const ctx=view.getContext('2d')!;ctx.clearRect(0,0,view.width,view.height);
    if(!mask || showBefore)return;
    ctx.drawImage(mask,0,0);ctx.globalCompositeOperation='source-in';ctx.fillStyle='rgba(172,154,255,.5)';
    ctx.fillRect(0,0,view.width,view.height);ctx.globalCompositeOperation='source-over';
  }
  function clearMask() {
    maskPast.current=[];maskFuture.current=[];maskBase.current=null;
    setMaskHistory({undo:false,redo:false});gesture.current=null;
    maskCanvas.current=null;setMarked(false);setInstruction('');
    const view=overlay.current;view?.getContext('2d')?.clearRect(0,0,view.width,view.height);
  }
  function paintMask(canvas:HTMLCanvasElement,stroke:MaskStroke) {
    const ctx=canvas.getContext('2d')!;
    if(stroke.clear){ctx.clearRect(0,0,canvas.width,canvas.height);return;}
    ctx.save();ctx.globalCompositeOperation=stroke.erase?'destination-out':'source-over';
    ctx.strokeStyle='#fff';ctx.fillStyle='#fff';ctx.lineWidth=stroke.size;ctx.lineCap='round';ctx.lineJoin='round';
    const points=stroke.points;if(!points.length){ctx.restore();return;}
    ctx.beginPath();
    if(points.length===1){ctx.arc(points[0][0],points[0][1],stroke.size/2,0,Math.PI*2);ctx.fill();}
    else {ctx.moveTo(...points[0] as [number,number]);for(const p of points.slice(1))ctx.lineTo(...p as [number,number]);ctx.stroke();}
    ctx.restore();
  }
  function newMaskCanvas() {
    const canvas=document.createElement('canvas');canvas.width=doc!.width;canvas.height=doc!.height;return canvas;
  }
  function replayMask() {
    const canvas=maskCanvas.current??newMaskCanvas();maskCanvas.current=canvas;
    const ctx=canvas.getContext('2d')!;ctx.clearRect(0,0,canvas.width,canvas.height);
    if(maskBase.current)ctx.drawImage(maskBase.current,0,0);
    for(const stroke of maskPast.current)paintMask(canvas,stroke);
    const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
    let any=false;for(let i=3;i<pixels.length;i+=4){if(pixels[i]){any=true;break;}}
    setMarked(any);drawMaskPreview();
    setMaskHistory({undo:!!maskPast.current.length,redo:!!maskFuture.current.length});
  }
  function commitMask(stroke:MaskStroke) {
    maskPast.current.push(stroke);maskFuture.current=[];
    // Bound undo memory without losing older painted pixels. Up to 100 gestures
    // are editable; older vectors are flattened into one baseline canvas.
    if(maskPast.current.length>100){
      maskBase.current??=newMaskCanvas();paintMask(maskBase.current,maskPast.current.shift()!);
    }
    replayMask();
  }
  function undoMask(redo=false) {
    if(lock.current||gesture.current)return;
    const from=redo?maskFuture.current:maskPast.current,to=redo?maskPast.current:maskFuture.current;
    const stroke=from.pop();if(!stroke)return;to.push(stroke);replayMask();
  }
  const maskTool=tool==='mark'||tool==='unmark';
  function undo(redo=false) {
    if(lock.current||gesture.current)return;
    if(maskTool && (maskPast.current.length||maskFuture.current.length)){undoMask(redo);return;}
    if(redo?doc?.can_redo:doc?.can_undo)void run(()=>command({op:redo?'redo':'undo'}));
  }
  function keyboard(event:React.KeyboardEvent) {
    const target=event.target as HTMLElement;
    if(target.closest('input,textarea,select,[contenteditable="true"]')||busy||!hasImage)return;
    if((event.ctrlKey||event.metaKey)&&['z','y'].includes(event.key.toLowerCase())){
      event.preventDefault();event.stopPropagation();undo(event.shiftKey||event.key.toLowerCase()==='y');
    } else if(event.key==='Escape'&&marked){event.preventDefault();event.stopPropagation();commitMask({points:[],size:1,erase:false,clear:true});}
  }
  function position(event: React.PointerEvent<HTMLCanvasElement>):[number,number] {
    const bounds=event.currentTarget.getBoundingClientRect();
    return [Math.max(0,Math.min(doc!.width-1,(event.clientX-bounds.left)/bounds.width*doc!.width)),
      Math.max(0,Math.min(doc!.height-1,(event.clientY-bounds.top)/bounds.height*doc!.height))];
  }
  function markPath(points:number[][],erase=false) {
    if(!maskCanvas.current){const canvas=document.createElement('canvas');canvas.width=doc!.width;canvas.height=doc!.height;maskCanvas.current=canvas;}
    paintMask(maskCanvas.current,{points:points.slice(-2),size,erase});
    drawMaskPreview();
  }
  const pointerDown=(event:React.PointerEvent<HTMLCanvasElement>)=>{
    if(busy || event.button!==0)return;
    setError('');
    if(['brush','erase','move'].includes(tool)&&activeLayer?.locked){setError(t('Önce katmanın kilidini açın.'));return;}
    if(showBefore){setShowBefore(false);return;}
    const p=position(event);event.currentTarget.setPointerCapture(event.pointerId);gesture.current={points:[p],start:p};
    event.currentTarget.focus();
    if(maskTool){gesture.current.mask={points:gesture.current.points,size,erase:tool==='unmark'||event.shiftKey};markPath([p],gesture.current.mask.erase);}
    if(tool==='text'){setTextPoint([Math.round(p[0]),Math.round(p[1])]);gesture.current=null;}
  };
  const pointerMove=(event:React.PointerEvent<HTMLCanvasElement>)=>{
    if(doc)setCursor(position(event));
    if(!gesture.current||busy)return;
    const p=position(event),g=gesture.current;
    if(g.points.length>=2000)return;
    g.points.push(p);
    if(g.mask)markPath(g.points,g.mask.erase);
    else if(['select','crop','shape'].includes(tool))setRect([Math.floor(Math.min(p[0],g.start[0])),Math.floor(Math.min(p[1],g.start[1])),Math.max(1,Math.round(Math.abs(p[0]-g.start[0]))),Math.max(1,Math.round(Math.abs(p[1]-g.start[1])))]);
    else if(['brush','erase'].includes(tool)) {
      const ctx=overlay.current!.getContext('2d')!;ctx.strokeStyle=tool==='erase'?'#f28c96':color;ctx.lineWidth=size;ctx.lineCap='round';
      ctx.beginPath();ctx.moveTo(...g.points[g.points.length-2] as [number,number]);ctx.lineTo(...p);ctx.stroke();
    }
  };
  const pointerUp=(event:React.PointerEvent<HTMLCanvasElement>)=>{
    const g=gesture.current;if(!g)return;gesture.current=null;
    const p=position(event);
    if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
    if(g.points.length<2000)g.points.push(p);
    if(g.mask){commitMask(g.mask);setBubble([p[0]/doc!.width*100,p[1]/doc!.height*100]);return;}
    if(['select','crop','shape'].includes(tool)){
      const r=[Math.floor(Math.min(p[0],g.start[0])),Math.floor(Math.min(p[1],g.start[1])),Math.max(1,Math.round(Math.abs(p[0]-g.start[0]))),Math.max(1,Math.round(Math.abs(p[1]-g.start[1])))];
      setRect(r);if(tool!=='shape')void run(()=>command({op:'selection',rect:r}));return;
    }
    if(!activeLayer)return;
    if(tool==='move')void run(()=>command({op:'move',id:activeLayer.id,x:Math.round((activeLayer.x??0)+p[0]-g.start[0]),y:Math.round((activeLayer.y??0)+p[1]-g.start[1])}));
    if(['brush','erase'].includes(tool))void run(async()=>{await command({op:'stroke',id:activeLayer.id,points:g.points,size,color,erase:tool==='erase'});drawMaskPreview();});
  };
  const editRegion=()=>void run(async()=>{
    if(!marked || !maskCanvas.current)return;
    if((regionMode==='text'?(!originalText.trim()||!replacement.trim()||originalText.trim()===replacement.trim()):regionMode!=='remove'&&!instruction.trim()))return;
    const engine=regionMode==='instruction'||regionMode==='text'?'flux':regionMode==='fill'?'sdxl':'lama';
    const original=await fetch(preview);if(!original.ok)throw new Error(t('Görsel yüklenemedi.'));
    const init=await encode(await original.blob()),mask=maskCanvas.current.toDataURL('image/png');
    const expected=doc!.version;
    if(!expected)throw new Error(t('Yeni araçlar için AI uygulamasını yeniden başlatın.'));
    baseImage.current=init;
    const payload={mode:'edit',engine,prompt:regionMode==='text'?textEditPrompt(originalText,replacement):regionMode==='remove'?'Remove marked content':instruction.trim(),seed:-1,steps:regionMode==='fill'?20:4,cfg:regionMode==='fill'?5:1,width:1024,height:1024,init_image:init,edit_mask:mask};
    const fingerprint=JSON.stringify({payload,regionMode});
    if(regionKey.current.fingerprint!==fingerprint)regionKey.current={fingerprint,key:crypto.randomUUID()};
    const job=await sendJson('/api/v1/image/jobs','POST',{...payload,idempotency_key:regionKey.current.key});
    setAiJob(String(job.id));
    try {
      for(;;){
        await new Promise(resolve=>setTimeout(resolve,1200));
        if(!mounted.current)return;
        const state=await responseJson(await fetch('/api/v1/image/jobs/'+encodeURIComponent(String(job.id))));
        if(state.status==='COMPLETED'){
          const result=state.result as {url:string};const response=await fetch(result.url);
          if(!response.ok)throw new Error(t('Görsel yüklenemedi.'));
          await command({op:'apply_result',expected,image:await encode(await response.blob()),name:engine==='flux'?'AI':engine==='lama'?'LaMa':'SDXL'});
          clearMask();regionKey.current={fingerprint:'',key:''};break;
        }
        if(['FAILED','INTERRUPTED','RECOVERY_REQUIRED'].includes(String(state.status)))throw new Error(String(state.error||t('İşlem başarısız.')));
      }
    } finally {setAiJob('');}
  });
  const tools:[Tool,string][]=[['mark',t('AI alanını fırçala')],['unmark',t('AI işaretini sil')],['select',t('Alan seç')],['brush',t('Fırça')],['erase',t('Silgi')],['move',t('Taşı')],['text',t('Metin')],['crop',t('Kırp')],['shape',t('Şekil')]];
  const content=<>
    <header className="krita-header">
      <div className="krita-heading"><span className="krita-brand"><Icon name="layers" size={22}/></span>
        <div><small>{t('Görsel')}</small><h2 id="krita-title">{t('Katmanlı düzenleyici')}</h2></div>
      </div>
      <div className="krita-header-actions">
        {hasImage && <button className="krita-primary krita-ai-action" type="button" disabled={busy} onClick={sendToAI}><Icon name="sparkles" size={17}/>{t('AI düzenlemesine gönder')}</button>}
        {!embedded && <button className="krita-close" type="button" aria-label={t('Kapat')} disabled={busy} onClick={onClose}><Icon name="x" size={20}/></button>}
      </div>
    </header>

    {hasImage && <div className="krita-toolbar">
      <div className="krita-tool-group">
        {baseImage.current && <button type="button" disabled={busy} aria-pressed={showBefore} onClick={()=>setShowBefore(value=>!value)}>{showBefore?t('Sonra'):t('Önce')}</button>}
        <button type="button" disabled={busy} onClick={()=>void run(()=>command({op:'blank',width:doc!.width,height:doc!.height,name:t('Katman')}))}>{t('Boş katman')}</button>
        <button type="button" title="Ctrl+Z" disabled={busy||!(maskTool&&(maskHistory.undo||maskHistory.redo)?maskHistory.undo:doc?.can_undo)} onClick={()=>undo()}>{t('Geri al')}</button>
        <button type="button" title="Ctrl+Shift+Z / Ctrl+Y" disabled={busy||!(maskTool&&(maskHistory.undo||maskHistory.redo)?maskHistory.redo:doc?.can_redo)} onClick={()=>undo(true)}>{t('Yinele')}</button>
        <label className={busy ? 'disabled' : ''}><Icon name="folder" size={16}/>{t('Görsel aç')}{fileInput('open')}</label>
        <span className="krita-tool-divider"/>
        <label className={busy ? 'disabled' : ''}><Icon name="plus" size={16}/>{t('Katman ekle')}{fileInput('add')}</label>
        {selectedImage && <button type="button" disabled={busy} onClick={() => importSelected('add')}><Icon name="image" size={16}/>{t('Seçili görseli getir')}</button>}
      </div>
      <details className="krita-export">
        <summary><Icon name="arrow-down" size={16}/>{t('İndir')}<Icon name="chevron-down" size={14}/></summary>
        <div>
          <a href={preview} download="workstation.png" aria-disabled={busy} onClick={event => { if (busy) event.preventDefault(); }}><Icon name="image" size={16}/>{t('PNG indir')}</a>
          <button type="button" disabled={busy} onClick={() => void run(() => command({ op: 'save' }))}><Icon name="layers" size={16}/>{t('KRA hazırla')}</button>
          {projectReady && <a href="/api/v1/krita/project" download><Icon name="arrow-down" size={16}/>{t('KRA indir')}</a>}
        </div>
      </details>
    </div>}
    {hasImage && <div className="krita-tool-options">
      <div className="krita-tools" role="group" aria-label={t('Düzenleme araçları')}>{tools.map(([id,label])=><button type="button" key={id} disabled={busy} aria-pressed={tool===id} onClick={()=>{setTool(id);drawMaskPreview();}}>{label}</button>)}</div>
      <div className="krita-brush-options"><label>{t('Boyut')}<input type="number" min={1} max={256} value={size} disabled={busy} onChange={e=>setSize(Math.max(1,Math.min(256,Number(e.target.value)||1)))}/></label><input type="color" aria-label={t('Renk')} value={color} disabled={busy} onChange={e=>setColor(e.target.value)}/>
      <label>{t('Yakınlaştırma')}<select value={zoom} disabled={busy} onChange={e=>{setZoom(e.target.value);setCursor(null);}}><option value="fit">{t('Ekrana sığdır')}</option>{[25,50,100,150,200,300].map(value=><option key={value} value={String(value)}>{value}%</option>)}</select></label>
      {(marked||maskHistory.undo||maskHistory.redo) && <span className="krita-mask-controls" role="group" aria-label={t('AI seçimi')}>
        <button type="button" disabled={busy||!maskHistory.undo} onClick={()=>undoMask()}>{t('İşareti geri al')}</button>
        <button type="button" disabled={busy||!maskHistory.redo} onClick={()=>undoMask(true)}>{t('İşareti yinele')}</button>
        <button type="button" disabled={busy||!marked} onClick={()=>commitMask({points:[],size:1,erase:false,clear:true})}>{t('İşareti temizle')}</button>
      </span>}
      {maskTool && <small>{t('Mor alan AI seçimidir. Shift ile silin; Ctrl+Z ile geri alın.')}</small>}
      {rect && <><button type="button" disabled={busy} onClick={()=>void run(()=>command({op:'selection',rect:null}))}>{t('Seçimi kaldır')}</button>{tool==='crop'&&<button type="button" disabled={busy} onClick={()=>void run(()=>command({op:'crop',rect}))}>{t('Kırpmayı uygula')}</button>}</>}
      </div>
    </div>}
    {error && <div className="krita-error" role="alert"><Icon name="info" size={17}/>{localizeMessage(error)}</div>}

    <div className={`krita-layout${dragging ? ' is-dragging' : ''}`} aria-busy={busy}
      onDragOver={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); if (!busy) setDragging(true); } }}
      onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }}
      onDrop={event => { event.preventDefault(); setDragging(false); if (!busy) importFile(event.dataTransfer.files[0], hasImage ? 'add' : 'open'); }}>
      {hasImage ? <>
        <div className={`krita-canvas${zoom!=='fit'?' is-zoomed':''}`}><div className="krita-image-surface" style={zoom!=='fit'?{width:doc!.width*Number(zoom)/100}:undefined}><img src={showBefore&&baseImage.current?baseImage.current:preview} alt={t('Görsel önizleme')} draggable={false}/>
          <canvas ref={overlay} className="krita-overlay" tabIndex={0} width={doc!.width} height={doc!.height} aria-label={t('Görsel üzerinde alan işaretle')}
            onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerLeave={()=>setCursor(null)} onPointerCancel={()=>{gesture.current=null;setRect(doc?.selection??null);replayMask();}}/>
          {cursor&&!busy&&!showBefore&&['mark','unmark','brush','erase'].includes(tool) && <span className={`krita-brush-cursor${tool==='unmark'||tool==='erase'?' is-eraser':''}`} style={{left:cursor[0]/doc!.width*100+'%',top:cursor[1]/doc!.height*100+'%',width:size/doc!.width*100+'%',height:size/doc!.height*100+'%'}}/>}
          {rect && <div className="krita-selection" style={{left:rect[0]/doc!.width*100+'%',top:rect[1]/doc!.height*100+'%',width:rect[2]/doc!.width*100+'%',height:rect[3]/doc!.height*100+'%'}}/>}
          {marked && tool==='mark' && !busy && <div className="krita-prompt-bubble" style={{left:`clamp(6px, ${bubble[0]}%, max(6px, calc(100% - 276px)))`,top:`clamp(6px, ${bubble[1]}%, max(6px, calc(100% - min(500px, 65dvh))))`}}>
            <strong><Icon name="sparkles" size={15}/>{t('Burada ne değişsin?')}</strong>
            <select aria-label={t('Alan işlemi')} value={regionMode} onChange={e=>setRegionMode(e.target.value as typeof regionMode)}>
              <option value="remove">{t('Hızlı sil ve doldur')}</option><option value="fill">{t('Alana yeni içerik ekle')}</option><option value="text">{t('Yazıyı değiştir')}</option><option value="instruction">{t('Talimatla düzenle (FLUX)')}</option>
            </select>
            {regionMode==='remove'?<small>{t('Boyanan nesneyi siler, çevresiyle doldurur. Talimat gerekmez.')}</small>:regionMode==='text'?<>
              <input maxLength={500} aria-label={t('Eski metin')} placeholder={t('Eski metin')} value={originalText} onChange={e=>setOriginalText(e.target.value.replace(/[\r\n]/g,''))}/>
              <input maxLength={500} aria-label={t('Yeni metin')} placeholder={t('Yeni metin')} value={replacement} onChange={e=>setReplacement(e.target.value.replace(/[\r\n]/g,''))}/>
              <small>{t('Eski yazının tamamını boya. AI yazıyı mevcut biçimini koruyarak değiştirmeye çalışır.')}</small>
              <small>{t('Font eşleşmesi ve metin doğruluğu sonucu kontrol ederek doğrulanmalıdır.')}</small>
            </>:<textarea maxLength={8000} aria-label={t('Seçili alan için AI talimatı')} value={instruction} onChange={e=>setInstruction(e.target.value)} placeholder={regionMode==='fill'?t('Örn. Kırmızı bir çiçek'):t('Örn. Bu yazıyı temizle, arka planı koru.')}/>}
            {regionMode==='fill'&&<small>{t('Alanın yeni içeriğini tarif et. SDXL için İngilizce daha güvenilirdir.')}</small>}
            <small>{regionMode==='fill'?'SDXL · Fooocus Inpaint':regionMode==='remove'?'LaMa':'FLUX.2 klein'}</small>
            {['remove','fill'].includes(regionMode)&&!engines?.[regionMode==='fill'?'sdxl':'lama']?.ready&&<div className="krita-model-notice"><small>{engineError?t('Model durumu kontrol edilemedi.'):t('Bu araç için modeller henüz hazır değil.')}</small><code>bash scripts/krita-modelleri-kur.sh</code><button type="button" onClick={refreshEngines}>{t('Yeniden kontrol et')}</button></div>}
            <small>{t('Yalnızca fırçalanan alan değişir. ComfyUI açık olmalı.')}</small>
            <button className="krita-primary" type="button" disabled={(regionMode==='text'?(!originalText.trim()||!replacement.trim()||originalText.trim()===replacement.trim()):regionMode!=='remove'&&!instruction.trim())||(['remove','fill'].includes(regionMode)&&!engines?.[regionMode==='fill'?'sdxl':'lama']?.ready)} onClick={editRegion}>{regionMode==='remove'?t('Sil ve doldur'):regionMode==='text'?t('Metni değiştir'):t('Bu alanı düzelt')}</button>
          </div>}
        </div></div>
        <aside className="krita-inspector" aria-label={t('Katmanlar')}>
          <div className="krita-native-properties">
          {tool==='text' && <><h3>{t('Metin')}</h3><textarea maxLength={2000} aria-label={t('Metin')} value={text} onChange={e=>setText(e.target.value)} disabled={busy}/><select aria-label={t('Yazı tipi')} value={font} disabled={busy} onChange={e=>setFont(e.target.value)}>{['Noto Sans','DejaVu Sans','Liberation Sans','Arial'].map(f=><option key={f}>{f}</option>)}</select><label><input type="checkbox" checked={bold} disabled={busy} onChange={e=>setBold(e.target.checked)}/>{t('Kalın')}</label><small>{textPoint[0]}, {textPoint[1]} px</small><button type="button" disabled={busy||!text.trim()} onClick={()=>void run(()=>command({op:'text',text,size,color,font,bold,x:textPoint[0],y:textPoint[1]}))}>{t('Metin ekle')}</button>
            {activeLayer?.editable?.kind==='text' && <><button type="button" disabled={busy} onClick={()=>{const e=activeLayer.editable!;setText(String(e.text));setSize(Number(e.size));setColor(String(e.color));setFont(String(e.font||'Noto Sans'));setBold(Boolean(e.bold));setTextPoint([Number(e.x),Number(e.y)]);}}>{t('Metni yükle')}</button><button type="button" disabled={busy||!text.trim()} onClick={()=>void run(()=>command({op:'text',id:activeLayer.id,text,size,color,font,bold,x:textPoint[0],y:textPoint[1]}))}>{t('Metni güncelle')}</button></>}
          </>}
          {tool==='shape' && <><select aria-label={t('Şekil')} value={shapeKind} onChange={e=>setShapeKind(e.target.value)}><option value="rectangle">{t('Dikdörtgen')}</option><option value="ellipse">{t('Elips')}</option></select><button type="button" disabled={busy||!rect} onClick={()=>void run(()=>command({op:'shape',kind:shapeKind,rect,color}))}>{t('Şekil ekle')}</button></>}
          </div>
          <div className="krita-inspector-heading"><h3><Icon name="layers" size={16}/>{t('Katmanlar')}</h3><span>{doc!.layers.length}</span></div>
          <div className="krita-layer-list">{doc!.layers.map((layer, index) => <div className={`krita-layer${activeLayer?.id === layer.id ? ' is-active' : ''}`} key={layer.id}>
            <label className="krita-layer-visibility"><input type="checkbox" checked={layer.visible} disabled={busy} aria-label={`${t('Katman')} ${doc!.layers.length - index}`}
              onChange={event => void run(() => command({ op: 'layer', id: layer.id, visible: event.target.checked }))}/></label>
            <button className="krita-layer-select" type="button" aria-pressed={activeLayer?.id === layer.id} onClick={() => setActiveId(layer.id)}>
              <span className="krita-layer-symbol"><Icon name="image" size={19}/></span><span>{layer.name || `${t('Katman')} ${doc!.layers.length - index}`}</span>
            </button>
          </div>)}</div>
          {activeLayer && <div className="krita-layer-properties">
            <div className="krita-layer-actions">
              <button type="button" disabled={busy} onClick={()=>void run(()=>command({op:'blank',width:doc!.width,height:doc!.height,name:t('Katman')}))}>＋</button>
              <button type="button" disabled={busy} aria-label={t('Katmanı çoğalt')} onClick={()=>void run(()=>command({op:'duplicate',id:activeLayer.id}))}><Icon name="layers" size={15}/></button>
              <button type="button" disabled={busy} aria-label={t('Yukarı taşı')} onClick={()=>void run(()=>command({op:'reorder',id:activeLayer.id,direction:'up'}))}>↑</button>
              <button type="button" disabled={busy} aria-label={t('Aşağı taşı')} onClick={()=>void run(()=>command({op:'reorder',id:activeLayer.id,direction:'down'}))}>↓</button>
              <button type="button" disabled={busy} aria-label={t('Katmanı sil')} onClick={()=>void run(()=>command({op:'delete',id:activeLayer.id}))}><Icon name="trash" size={15}/></button>
            </div>
            <label>{t('Katman adı')}<input aria-label={t('Katman adı')} value={layerName} maxLength={100} disabled={busy} onChange={e=>setLayerName(e.target.value)}/></label><button type="button" disabled={busy||!layerName.trim()} onClick={()=>void run(()=>command({op:'layer',id:activeLayer.id,name:layerName}))}>{t('Adı uygula')}</button>
            <details className="krita-transform"><summary>{t('Boyut ve döndürme')}</summary>
              <label>{t('Genişlik')}<input type="number" min={1} max={2048} value={transform.width} disabled={busy} onChange={e=>setTransform(v=>({...v,width:Number(e.target.value)}))}/></label>
              <label>{t('Yükseklik')}<input type="number" min={1} max={2048} value={transform.height} disabled={busy} onChange={e=>setTransform(v=>({...v,height:Number(e.target.value)}))}/></label>
              <label>{t('Açı')}<input type="number" min={-180} max={180} value={transform.angle} disabled={busy} onChange={e=>setTransform(v=>({...v,angle:Number(e.target.value)}))}/></label>
              <button type="button" disabled={busy} onClick={()=>void run(()=>command({op:'transform',id:activeLayer.id,...transform}))}>{t('Dönüştür')}</button>
            </details>
            <label><input type="checkbox" checked={!!activeLayer.locked} disabled={busy} onChange={e=>void run(()=>command({op:'layer',id:activeLayer.id,locked:e.target.checked}))}/>{t('Katmanı kilitle')}</label>
            <select aria-label={t('Karışım modu')} disabled={busy} value={activeLayer.blend||'normal'} onChange={e=>void run(()=>command({op:'layer',id:activeLayer.id,blend:e.target.value}))}>{['normal','multiply','screen','overlay'].map(m=><option key={m}>{m}</option>)}</select>
            <label htmlFor="krita-opacity">{t('Opaklık')}<output>{Math.round((opacity[activeLayer.id] ?? activeLayer.opacity) / 255 * 100)}%</output></label>
            <input id="krita-opacity" type="range" min={0} max={255} step={1} value={opacity[activeLayer.id] ?? activeLayer.opacity} disabled={busy}
              onChange={event => setOpacity(values => ({ ...values, [activeLayer.id]: Number(event.target.value) }))}/>
            <button type="button" disabled={busy || opacity[activeLayer.id] === undefined || opacity[activeLayer.id] === activeLayer.opacity}
              onClick={() => void run(() => command({ op: 'layer', id: activeLayer.id, opacity: opacity[activeLayer.id] }))}>{t('Uygula')}</button>
            {rect && <><button type="button" disabled={busy} onClick={()=>void run(()=>command({op:'clear',id:activeLayer.id}))}>{t('Seçili alanı sil')}</button><button type="button" disabled={busy} onClick={()=>void run(()=>command({op:'fill',id:activeLayer.id,color}))}>{t('Seçili alanı boya')}</button></>}
            {!!doc?.filters?.length && <select aria-label={t('Filtre uygula')} value="" disabled={busy} onChange={e=>{if(e.target.value)void run(()=>command({op:'filter',id:activeLayer.id,filter:e.target.value}));}}><option value="">{t('Filtre uygula')}</option>{doc.filters.map(f=><option value={f} key={f}>{f}</option>)}</select>}
          </div>}
        </aside>
      </> : <div className="krita-start">
        <div className="krita-start-heading"><span className="krita-start-symbol"><Icon name="image" size={30}/></span>
          <h3>{t('Bir fikirle başlayın.')}</h3><p>{t('Bir görsel açın veya galerideki görseli getirin.')}</p></div>
        <div className={`krita-start-options${selectedImage ? ' with-selected' : ''}`}>
          <label className={`krita-open-card${busy ? ' disabled' : ''}`}><span className="krita-open-icon"><Icon name="upload" size={24}/></span>
            <strong>{t('Görsel aç')}</strong><small>PNG · JPG · WebP</small><span className="krita-card-action"><Icon name="plus" size={15}/>{t('Görsel aç')}</span>{fileInput('open')}
          </label>
          {selectedImage && <button className="krita-selected-card" type="button" disabled={busy} onClick={() => importSelected('open')}>
            <div className="krita-selected-thumbnail"><img src={selectedImage} alt=""/></div>
            <span><strong>{t('Seçili görseli getir')}</strong><Icon name="arrow-right" size={17}/></span>
          </button>}
        </div>
        <button className="krita-resume" type="button" disabled={busy} onClick={() => void run(async () => { setStarting(true); await command({ op: 'state' }); })}><Icon name="layers" size={15}/>{t('Önceki oturuma bağlan')}<Icon name="arrow-right" size={14}/></button>
      </div>}
      {busy && <div className="krita-busy"><span className="krita-spinner"/><p role="status">{aiJob ? t('AI seçili alanı düzenliyor…') : starting ? t('Krita hazırlanıyor; ilk açılış iki dakika sürebilir.') : t('İşleniyor…')}</p>{aiJob && <button type="button" onClick={()=>void sendJson('/api/v1/image/jobs/'+aiJob+'/cancel','POST',{}).catch(reason=>setError(String(reason)))}>{t('İptal et')}</button>}</div>}
    </div>
    <footer className="krita-footer"><span>{hasImage ? <><span className="krita-ready-dot"/>{doc!.width} × {doc!.height} px<span className="krita-footer-divider">·</span>{doc!.layers.length} {t('Katman')}</> : t('En fazla 2048 piksel kenar · 12 MiB · 20 katman')}</span>
      <details className="krita-help"><summary aria-label={t('Görsel bilgileri')}><Icon name="info" size={16}/></summary><p>{t('Fırçayla alan işaretleyin ve yanındaki baloncuğa talimat yazın. Sonuç yeni katmana eklenir. PNG veya KRA indirerek kaydedin.')}</p></details>
    </footer>
  </>;
  const className=`krita-editor${hasImage?' has-image':' is-empty'}${embedded?' is-embedded':''}`;
  return embedded ? <section className={className} onKeyDown={keyboard} aria-labelledby="krita-title">{content}</section> : <dialog ref={dialog} className={className} onKeyDown={keyboard} aria-labelledby="krita-title" onCancel={event=>{event.preventDefault();if(!busy)onClose();}}>{content}</dialog>;
}
