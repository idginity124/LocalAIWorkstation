import { test, expect } from '@playwright/test';
import { createRequire } from 'node:module';
import fs from 'node:fs';
const require = createRequire(import.meta.url);
const esbuild = require('esbuild');
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAgElEQVR4nOXOQQEAIBCAMCSSSYxje41xD5Zga9/zCJM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iXM6MO0DENMCebB4ujoAAAAASUVORK5CYII=', 'base64');

async function mount(page: any) {
  const bundle = await esbuild.build({stdin:{contents:`
    import React from 'react';
    import {createRoot} from 'react-dom/client';
    import {KritaEditor} from './src/components/KritaEditor';
    import {setLang} from './src/i18n';
    setLang('tr');
    createRoot(document.getElementById('root')).render(<KritaEditor selectedImage='/selected.png'
      onClose={()=>{document.body.dataset.closed='yes'}}
      onSendToAI={async file=>{document.body.dataset.aiFile=file.name}}/>);
  `, loader:'tsx',resolveDir:process.cwd(),sourcefile:'krita-editor-test.tsx'},bundle:true,write:false,format:'iife'});
  let layers: any[]=[];
  let regionSubmitted=false;
  let version=0;
  const commands:any[]=[];
  await page.route('http://127.0.0.1:8000/**', async (route: any) => {
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/v1/session')return route.fulfill({json:{csrf_token:'token'}});
    if(path==='/api/v1/image/edit-engines')return route.fulfill({json:{lama:{ready:true,available:true},sdxl:{ready:true,available:true}}});
    if(path==='/api/v1/image/jobs' && route.request().method()==='POST') {
      const payload=route.request().postDataJSON();
      expect(payload.edit_mask).toMatch(/^data:image\/png;base64,/);
      expect(['flux','lama','sdxl']).toContain(payload.engine);
      if(payload.prompt.startsWith('Replace the existing text')){
        expect(payload.engine).toBe('flux');expect(payload.prompt).toContain('"24" with "25"');expect(payload.prompt).toContain('existing font');
      } else expect(payload.prompt).toBe(payload.engine==='flux'?'Remove the marked text':payload.engine==='lama'?'Remove marked content':'a red flower');
      regionSubmitted=true;
      return route.fulfill({json:{id:'region-job',status:'QUEUED'}});
    }
    if(path==='/api/v1/image/jobs/region-job')return route.fulfill({json:{id:'region-job',status:'COMPLETED',result:{url:'/result.png'}}});
    if(path==='/api/v1/krita/command') {
      const data=route.request().postDataJSON();
      commands.push(data);
      expect(route.request().headers()['x-csrf-token']).toBe('token');
      if(data.op==='open')layers=[{id:'one',name:'Background',visible:true,opacity:255}];
      if(data.op==='apply_result'){expect(regionSubmitted).toBeTruthy();layers=layers.map(l=>({...l,visible:false}));}
      if(data.op==='add'||data.op==='apply_result')layers.unshift({id:'two',name:'Layer',visible:true,opacity:255});
      if(data.op==='layer')layers=layers.map(l=>l.id===data.id?{...l,...data}:l);
      return route.fulfill({json:{version:'test:'+String(++version),features:['text_replacement'],width:layers.length?64:0,height:layers.length?64:0,layers}});
    }
    if(path.endsWith('.png')||path==='/api/v1/krita/preview')return route.fulfill({body:png,contentType:'image/png'});
    return route.fulfill({body:'<html><body><div id="root"></div></body></html>',contentType:'text/html'});
  });
  await page.goto('/');
  await page.addStyleTag({content:fs.readFileSync('src/components/krita-editor.css','utf8')});
  await page.addScriptTag({content:bundle.outputFiles[0].text});
  await expect(page.getByRole('dialog')).toBeVisible();
  return commands;
}

test('Krita editor imports layers, edits opacity and returns the result to AI',async({page})=>{
  const errors: string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await mount(page);
  await page.locator('.krita-open-card input').setInputFiles({name:'test.png',mimeType:'image/png',buffer:png});
  await expect(page.locator('.krita-layer')).toHaveCount(1);
  await page.getByRole('button',{name:'Seçili görseli getir'}).click();
  await expect(page.locator('.krita-layer')).toHaveCount(2);
  const layer=page.locator('.krita-layer').first();
  await layer.getByRole('checkbox').uncheck();
  await expect(layer.getByRole('checkbox')).not.toBeChecked();
  await page.getByRole('slider').fill('128');
  await page.getByRole('button',{name:'Uygula'}).click();
  await expect(page.locator('.krita-layer-properties output')).toHaveText('50%');
  await page.locator('.krita-export summary').click();
  await page.getByRole('button',{name:'KRA hazırla'}).click();
  await expect(page.getByRole('link',{name:'KRA indir'})).toHaveAttribute('href','/api/v1/krita/project');
  await page.screenshot({path:'../runtime-reports/krita-editor-desktop.png'});
  await page.getByRole('button',{name:'AI düzenlemesine gönder'}).click();
  await expect(page.locator('body')).toHaveAttribute('data-ai-file','krita-edit.png');
  await expect(page.locator('body')).toHaveAttribute('data-closed','yes');
  expect(errors).toEqual([]);
});

test('Krita editor fits a mobile screen',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await mount(page);
  await page.getByRole('button',{name:'Seçili görseli getir'}).click();
  await expect(page.locator('.krita-layer')).toHaveCount(1);
  expect(await page.locator('dialog').evaluate((el:any)=>el.scrollWidth<=el.clientWidth)).toBeTruthy();
  await page.screenshot({path:'../runtime-reports/krita-editor-mobile.png'});
});


test('brushed region opens an instruction bubble and imports the AI result',async({page})=>{
  await mount(page);
  await page.getByRole('button',{name:'Seçili görseli getir'}).click();
  await expect(page.locator('.krita-overlay')).toBeVisible();
  await page.getByRole('spinbutton',{name:'Boyut',exact:true}).fill('5');
  const box=(await page.locator('.krita-overlay').boundingBox())!;
  await page.mouse.move(box.x+box.width*.3,box.y+box.height*.4);
  await page.mouse.down();
  await page.mouse.move(box.x+box.width*.6,box.y+box.height*.5,{steps:10});
  await page.mouse.up();
  await expect(page.locator('.krita-prompt-bubble')).toBeVisible();
  await page.getByRole('combobox',{name:'Alan işlemi'}).selectOption('instruction');
  await page.getByRole('textbox',{name:'Seçili alan için AI talimatı'}).fill('Remove the marked text');
  await page.screenshot({path:'../runtime-reports/krita-region-bubble.png'});
  await page.getByRole('button',{name:'Bu alanı düzelt',exact:true}).click();
  await expect(page.locator('.krita-layer')).toHaveCount(2);
  await expect(page.locator('.krita-prompt-bubble')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Önce',exact:true})).toBeVisible();
});

test('AI marking supports undo, redo, reversible clear and selection-only erasing',async({page})=>{
  await mount(page);
  await page.getByRole('button',{name:'Seçili görseli getir'}).click();
  await page.getByRole('spinbutton',{name:'Boyut',exact:true}).fill('8');
  const canvas=page.locator('.krita-overlay');
  const box=(await canvas.boundingBox())!;
  const point={x:box.x+box.width*.25,y:box.y+box.height*.25};
  const alpha=()=>canvas.evaluate((el:any)=>el.getContext('2d').getImageData(16,16,1,1).data[3]);
  await page.mouse.click(point.x,point.y);
  await page.getByRole('combobox',{name:'Alan işlemi'}).selectOption('instruction');
  await expect.poll(alpha).toBeGreaterThan(0);
  await page.getByRole('textbox',{name:'Seçili alan için AI talimatı'}).fill('Keep this instruction');
  await page.getByRole('button',{name:'İşareti temizle',exact:true}).click();
  await expect.poll(alpha).toBe(0);
  await page.getByRole('button',{name:'İşareti geri al',exact:true}).click();
  await expect.poll(alpha).toBeGreaterThan(0);
  await expect(page.getByRole('textbox',{name:'Seçili alan için AI talimatı'})).toHaveValue('Keep this instruction');
  // Focus without another stroke; editor shortcuts must not call native document undo.
  await canvas.focus();await page.keyboard.press('Control+z');
  await expect.poll(alpha).toBe(0);
  await page.keyboard.press('Control+Shift+z');
  await expect.poll(alpha).toBeGreaterThan(0);
  await page.getByRole('button',{name:'AI işaretini sil',exact:true}).click();
  await page.mouse.click(point.x,point.y);
  await expect.poll(alpha).toBe(0);
  await page.getByRole('button',{name:'İşareti geri al',exact:true}).click();
  await expect.poll(alpha).toBeGreaterThan(0);
  await page.getByRole('button',{name:'İşareti yinele',exact:true}).click();
  await expect.poll(alpha).toBe(0);
  await expect(page.locator('.krita-layer')).toHaveCount(1);
});

test('native textarea undo is not intercepted and zoom keeps document coordinates',async({page})=>{
  await mount(page);
  await page.getByRole('button',{name:'Seçili görseli getir'}).click();
  const canvas=page.locator('.krita-overlay');
  await page.getByRole('combobox',{name:'Yakınlaştırma'}).selectOption('200');
  await expect(page.locator('.krita-image-surface')).toHaveCSS('width','128px');
  const box=(await canvas.boundingBox())!;
  await page.mouse.click(box.x+box.width*.25,box.y+box.height*.25);
  await page.getByRole('combobox',{name:'Alan işlemi'}).selectOption('instruction');
  const input=page.getByRole('textbox',{name:'Seçili alan için AI talimatı'});
  await input.fill('Replace');await input.press('End');await input.pressSequentially(' text');
  await input.press('Control+z');
  await expect(page.locator('.krita-prompt-bubble')).toBeVisible();
  await page.getByRole('button',{name:'AI işaretini sil',exact:true}).click();
  await canvas.focus();await page.keyboard.press('Escape');
  await expect(page.getByRole('button',{name:'İşareti temizle',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'İşareti geri al',exact:true}).click();
  await expect(page.getByRole('button',{name:'İşareti temizle',exact:true})).toBeEnabled();
});

test('text replacement requests matching source lettering and never overlays native text',async({page})=>{
  const commands=await mount(page);
  await page.getByRole('button',{name:'Seçili görseli getir'}).click();
  const canvas=page.locator('.krita-overlay');const box=(await canvas.boundingBox())!;
  await page.mouse.click(box.x+box.width*.2,box.y+box.height*.2);
  await expect(page.getByRole('button',{name:'Sil ve doldur',exact:true})).toBeEnabled();
  await expect(page.getByRole('textbox',{name:'Seçili alan için AI talimatı'})).toHaveCount(0);
  await page.getByRole('combobox',{name:'Alan işlemi'}).selectOption('text');
  await page.getByRole('textbox',{name:'Eski metin',exact:true}).fill('24');
  await page.getByRole('textbox',{name:'Yeni metin',exact:true}).fill('25');
  await page.getByRole('button',{name:'Metni değiştir',exact:true}).click();
  await expect.poll(()=>commands.filter(c=>c.op==='apply_result').length).toBe(1);
  const applied=commands.find(c=>c.op==='apply_result');
  expect(applied.text).toBeUndefined();expect(applied.expected).toMatch(/^test:/);
  expect(applied.rect).toBeUndefined();
  expect(commands.filter(c=>c.op==='text')).toHaveLength(0);
});

test('new content uses the masked SDXL workflow',async({page})=>{
  await mount(page);
  await page.getByRole('button',{name:'Seçili görseli getir'}).click();
  const box=(await page.locator('.krita-overlay').boundingBox())!;
  await page.mouse.click(box.x+box.width*.2,box.y+box.height*.2);
  await page.getByRole('combobox',{name:'Alan işlemi'}).selectOption('fill');
  await page.getByRole('textbox',{name:'Seçili alan için AI talimatı'}).fill('a red flower');
  await page.getByRole('button',{name:'Bu alanı düzelt',exact:true}).click();
  await expect(page.locator('.krita-layer')).toHaveCount(2);
});
