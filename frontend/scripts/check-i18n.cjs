const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const root = path.resolve(__dirname, '../src');

// Load the actual TypeScript modules in Node without a browser or emitted files.
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      fileName: filename,
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true, target: ts.ScriptTarget.ES2022 },
    });
    module._compile(output.outputText, filename);
  };
}
const stored = new Map();
global.window = { localStorage: { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) } };
global.document = { documentElement: { lang: '', dir: '' } };
const { t, tr, LANGS, setLang, getLocale, localizeMessage, formatNumber, formatDate } = require('../src/i18n.ts');
const en = require('../src/locales/en.json');
const { renderToStaticMarkup } = require('react-dom/server');
const React = require('react');
const { SystemPreferences } = require('../src/components/SystemPreferences.tsx');
const { SidebarModel } = require('../src/components/SidebarModel.tsx');

function sourceFile(filename) { return ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true); }
const base = {};
function readBase(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText() === 'trBase') {
    for (const property of node.initializer.expression.properties) {
      if (ts.isStringLiteral(property.initializer)) base[property.name.text] = property.initializer.text;
    }
  }
  ts.forEachChild(node, readBase);
}
readBase(sourceFile(path.join(root, 'i18n.ts')));

function applicationCopy() {
  const copy = new Set();
  const unlocalized = [];
  function walk(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const filename = path.join(directory, entry.name);
      if (entry.isDirectory()) { if (entry.name !== 'locales') walk(filename); continue; }
      if (!/\.tsx?$/.test(entry.name) || entry.name.startsWith('i18n')) continue;
      const source = sourceFile(filename);
      function visit(node) {
        if (ts.isCallExpression(node) && node.expression.getText(source) === 't' && ts.isStringLiteral(node.arguments[0])) copy.add(node.arguments[0].text);
        if (ts.isPropertyAccessExpression(node) && node.expression.getText(source) === 'tr' && base[node.name.text]) copy.add(base[node.name.text]);
        const translatedLiteral = node.parent && ts.isCallExpression(node.parent) && node.parent.expression.getText(source) === 't';
        if ((ts.isJsxText(node) || ts.isStringLiteral(node)) && /[çğıöşüÇĞİÖŞÜ]/.test(node.text) && !translatedLiteral) {
          unlocalized.push(`${path.relative(root, filename)}:${source.getLineAndCharacterOfPosition(node.getStart()).line + 1}: ${node.text}`);
        }
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
  walk(root);
  return { copy, unlocalized };
}

test('every active UI message has a translation in every selectable language', () => {
  const { copy, unlocalized } = applicationCopy();
  assert.deepEqual(unlocalized, [], 'Application copy must go through the translation catalog');
  assert.ok(copy.size > 300, 'The audit must cover all workspaces');
  for (const { code } of LANGS) {
    if (code === 'tr') continue;
    const catalog = require(`../src/locales/${code}.json`);
    setLang(code);
    for (const source of copy) {
      assert.ok(en[source], `Missing English entry: ${source}`);
      if (en[source] !== source) assert.ok(catalog[source], `${code}: ${source}`);
      assert.equal(t(source), catalog[source] ?? en[source], `${code}: ${source}`);
    }
    assert.notEqual(tr.workspace, base.workspace, `${code}: workspace fell back to Turkish`);
  }
});

test('language changes update existing notices, document direction, persistence, dates and numbers', () => {
  setLang('fr');
  const saved = t('Kaydedildi');
  setLang('en');
  assert.equal(localizeMessage(saved), 'Saved');
  assert.equal(document.documentElement.lang, 'en');
  assert.equal(document.documentElement.dir, 'ltr');
  assert.equal(stored.get('ai-workstation-lang'), 'en');
  assert.equal(formatNumber(1.5), '1.5');
  setLang('fr');
  assert.equal(formatNumber(1.5), '1,5');
  assert.equal(formatDate('2026-11-13 14:10:37'), new Date('2026-11-13T14:10:37').toLocaleString('fr'));
  for (const lang of ['ar', 'ur']) { setLang(lang); assert.equal(document.documentElement.dir, 'rtl'); }
  setLang('zh');
  assert.equal(getLocale(), 'zh-Hans');
  assert.equal(document.documentElement.lang, 'zh-Hans');
  setLang('tr');
  assert.equal(localizeMessage(saved), 'Kaydedildi');
  assert.equal(t(saved), 'Kaydedildi');
});

test('preferences and model controls render localized labels in all languages', () => {
  for (const { code } of LANGS) {
    setLang(code);
    const preferences = renderToStaticMarkup(React.createElement(SystemPreferences, {
      open: false, onClose() {}, settings: { theme: 'dark', telemetry_refresh_seconds: 5 }, settingsReady: true,
      settingsError: false, hardware: null, hardwareError: false, saving: false, message: '', onChange: async () => {},
    }));
    const sidebar = renderToStaticMarkup(React.createElement(SidebarModel, {
      modelId: 'example', models: [{ model_id: 'example', model: 'Test Model' }], status: { state: 'IDLE', start_allowed: true },
      disabled: false, busy: false, notice: '', onChange() {}, onStart() {}, onStop() {},
    }));
    if (code !== 'tr') {
      for (const phrase of ['Sistem ve Tercihler', 'Görünüm', 'Kaynaklar', 'Gelişmiş', 'Donanım ayrıntıları', 'Model seçimi']) {
        assert.ok(!(preferences + sidebar).includes(phrase), `${code}: ${phrase}`);
      }
    }
    assert.ok(sidebar.includes('Test Model'), 'Model names must remain unchanged');
  }
});

test('audio preparation UI renders in every language without offering generation before engine setup', () => {
  const { AudioWorkspace } = require('../src/pages/AudioWorkspace.tsx');
  for (const { code } of LANGS) {
    setLang(code);
    const html = renderToStaticMarkup(React.createElement(AudioWorkspace, { isActive: true }));
    assert.ok(html.includes('class="audio-studio-grid"'));
    const generateButton = html.split('<button').find(button => button.includes('title=') && button.includes('primary-button'));
    assert.ok(generateButton?.includes('disabled=""'), `${code}: generation must stay disabled`);
    if (code !== 'tr') assert.ok(!html.includes('Ses çalışma modu'), `${code}: audio labels fell back to Turkish`);
  }
});

test('service errors are localized without altering user content or model identifiers', () => {
  for (const { code } of LANGS) {
    setLang(code);
    assert.equal(t('gemma-4-12b'), 'gemma-4-12b');
    if (code === 'tr') continue;
    assert.equal(localizeMessage('Sohbet modeli GPU belleğini kullanıyor. Üst çubuktan belleği boşaltın.'), t('Önce çalışan servisi sol menüden durdurun.'));
    assert.equal(localizeMessage('Sunucudan bilinmeyen bir hata geldi.'), t('Servis isteği tamamlanamadı. Ayrıntılar için servis günlüklerini inceleyin.'));
  }
});

test('truncated responses show a localized continuation action in every language', () => {
  const { ChatCompletionNotice } = require('../src/lib/shared.tsx');
  for (const { code } of LANGS) {
    setLang(code);
    const messages = [{ id:'answer', role:'assistant', content:'User content', created_at:'', finish_reason:'length' }];
    const html = renderToStaticMarkup(React.createElement(ChatCompletionNotice, {messages, busy:false, omitted:2, onContinue() {}}));
    assert.ok(html.includes(t('Devam ettir')), code);
    assert.ok(html.includes(t('Yanıt uzunluk sınırına ulaştı.')), code);
    assert.ok(html.includes(t('Sohbet geçmişi saklanır; model bağlama sığan son mesajları kullanır.')), code);
    const busy = renderToStaticMarkup(React.createElement(ChatCompletionNotice, {messages, busy:true, omitted:0, onContinue() {}}));
    assert.ok(busy.includes('disabled=""'), code);
    const complete = renderToStaticMarkup(React.createElement(ChatCompletionNotice, {messages:[{...messages[0],finish_reason:'stop'}], busy:false, omitted:0, onContinue() {}}));
    assert.equal(complete, '');
  }
});

test('chat SSE preserves truncation metadata and sends continuation without a duplicate user message', async () => {
  const { streamConversation } = require('../src/lib/shared.tsx');
  const originalFetch = global.fetch;
  const requests = [];
  const events = [
    {type:'delta',text:'İkinci bölüm'},
    {type:'done',conversation:{id:'chat',title:'Question'},messages:[{id:'u',role:'user',content:'Question'}, {id:'a',role:'assistant',content:'First\n\nİkinci bölüm',finish_reason:'length'}],tokens_per_second:4,omitted_messages:8},
  ];
  const bytes = new TextEncoder().encode(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(''));
  global.fetch = async (url, options) => {
    requests.push({url,options});
    if (url === '/api/v1/session') return new Response(JSON.stringify({csrf_token:'fixture'}));
    let position = 0;
    return new Response(new ReadableStream({pull(controller) {
      if (position === bytes.length) { controller.close(); return; }
      const next = Math.min(position + 7,bytes.length);
      controller.enqueue(bytes.slice(position,next));position=next;
    }}));
  };
  try {
    let text='';
    const result=await streamConversation('chat',{continue:true},part => text+=part);
    assert.equal(text,'İkinci bölüm');
    assert.deepEqual(JSON.parse(requests[1].options.body),{continue:true});
    assert.equal(result.messages.at(-1).finish_reason,'length');
    assert.equal(result.omitted_messages,8);
    assert.equal(result.messages.length,2);
  } finally { global.fetch=originalFetch; }
});

test('invalid chat streams cancel their reader instead of leaving generation connected', async () => {
  const { streamConversation } = require('../src/lib/shared.tsx');
  const originalFetch=global.fetch;
  let cancelled=false;
  global.fetch=async url => url === '/api/v1/session' ? new Response(JSON.stringify({csrf_token:'fixture'})) : new Response(new ReadableStream({
    start(controller) {controller.enqueue(new TextEncoder().encode('data: broken-json\n'));},
    cancel() {cancelled=true;},
  }));
  try {
    await assert.rejects(streamConversation('chat',{content:'Question'},() => {}));
    assert.equal(cancelled,true);
  } finally {global.fetch=originalFetch;}
});

test('image job failures and cancellations update the primary notification', async () => {
  const { ImageWorkspace } = require('../src/pages/ImageWorkspace.tsx');
  const names=[...fs.readFileSync(path.join(root,'pages/ImageWorkspace.tsx'),'utf8').matchAll(/const \[(\w+), \w+\] = React\.useState/g)].map(item=>item[1]);
  const originalFetch=global.fetch;
  const originalTimer=window.setTimeout;
  const methods={useState:React.useState,useEffect:React.useEffect,useRef:React.useRef,useCallback:React.useCallback};
  try {
    for (const status of ['FAILED','RECOVERY_REQUIRED','INTERRUPTED']) {
      let index=0;const effects=[];const updates=new Map();
      React.useState=initial=>{
        const name=names[index++];let value=typeof initial==='function'?initial():initial;
        return [value,next=>{value=typeof next==='function'?next(value):next;updates.set(name,value);}];
      };
      React.useEffect=callback=>effects.push(callback);
      React.useRef=value=>({current:value});React.useCallback=callback=>callback;
      window.setTimeout=()=>0;
      global.fetch=async()=>new Response(JSON.stringify({jobs:[{id:'fixture',status,prompt:'fixture',error:'Known fixture failure'}]}));
      ImageWorkspace();
      const poll=effects.find(effect=>effect.toString().includes('/api/v1/image/jobs'));
      assert.ok(poll);
      const cleanup=poll();
      await new Promise(resolve=>setImmediate(resolve));
      cleanup();
      assert.equal(updates.get('generateError'),status!=='INTERRUPTED',status);
      assert.ok(updates.get('generateMessage'),status);
    }
  } finally { Object.assign(React,methods);global.fetch=originalFetch;window.setTimeout=originalTimer; }
});

test('image references retain their original bytes and configured paths are copied', async () => {
  const {readOriginalImage,imageOutputPath}=require('../src/lib/image-studio.ts');
  const originalReader=global.FileReader;
  global.FileReader=class {
    readAsDataURL(file) {this.result=file.original;this.onload();}
  };
  try {
    for(const mime of ['image/png','image/jpeg','image/webp']) {
      const original=`data:${mime};base64,YWxwaGEtb3JpZ2luYWwtcGl4ZWxz`;
      assert.equal(await readOriginalImage({size:100,type:mime,original}),original);
    }
    await assert.rejects(readOriginalImage({size:13*1024**2}));
    assert.equal(imageOutputPath({filename:'test.png'},'/custom/outputs/'),'/custom/outputs/test.png');
    assert.equal(imageOutputPath({filename:'test.png',path:'/actual/output.png'},'/other'),'/actual/output.png');
    assert.throws(()=>imageOutputPath({filename:'test.png'}));
  } finally {global.FileReader=originalReader;}
});

test('image setting validation matches the backend range and rejects fractional steps', () => {
  const {validateImageSettings}=require('../src/lib/image-studio.ts');
  for(const settings of [[-1,1,.5],[0,30,10],[Number.MAX_SAFE_INTEGER,8,1]])assert.doesNotThrow(()=>validateImageSettings(...settings));
  for(const settings of [[-2,8,1],[1.5,8,1],[-1,8.5,1],[-1,31,1],[-1,8,NaN],[-1,8,11]])assert.throws(()=>validateImageSettings(...settings));
});

test('singing conversion stays disabled until its own mode has been verified', () => {
  const { AudioWorkspace }=require('../src/pages/AudioWorkspace.tsx');
  const names=[...fs.readFileSync(path.join(root,'pages/AudioWorkspace.tsx'),'utf8').split('export function AudioWorkspace')[1].matchAll(/const \[(\w+), \w+\] = React\.useState/g)].map(item=>item[1]);
  const methods={useState:React.useState,useEffect:React.useEffect,useRef:React.useRef};
  setLang('en');
  try {
    for(const verified of [false,true]) {
      let index=0;
      React.useState=initial=>{
        const name=names[index++];
        const presets={tab:'conversion',conversion:'singing',status:{engine_available:true,engines:{tts:true,conversion:true,singing:verified},packs:{}},jobsReady:true,profiles:[{id:'voice',filename:'voice.wav',audio:{size:100}}],selectedId:'voice',source:{name:'source.wav',size:100}};
        const value=Object.prototype.hasOwnProperty.call(presets,name)?presets[name]:typeof initial==='function'?initial():initial;
        return [value,()=>{}];
      };
      React.useEffect=()=>{};React.useRef=value=>({current:value});
      const html=renderToStaticMarkup(React.createElement(AudioWorkspace,{isActive:true}));
      const button=html.split('<button').find(item=>item.includes('title=')&&item.includes('primary-button'));
      assert.equal(button.includes('disabled=""'),!verified);
    }
  } finally {Object.assign(React,methods);}
});

test('text replacement keeps literal strings and asks for in-place lettering edits',()=>{
  const {textEditPrompt}=require('../src/lib/textEdit.ts');
  const prompt=textEditPrompt(' 24 ','25');
  assert.ok(prompt.startsWith('Replace the existing text "24" with "25"'));
  assert.ok(prompt.includes('existing font'));
  assert.ok(prompt.includes('old text must disappear'));
  const quoted=textEditPrompt('İŞ "24"','ŞUBAT 25');
  assert.ok(quoted.includes(JSON.stringify('İŞ "24"')));
  assert.ok(quoted.includes(JSON.stringify('ŞUBAT 25')));
});
