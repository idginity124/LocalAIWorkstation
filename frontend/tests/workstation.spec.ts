import { test, expect } from '@playwright/test';

test('navigation preserves drafts; models, gallery and settings load without browser errors', async ({page}) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('#assistant-question')).toBeVisible();
  await page.locator('#assistant-question').fill('Kaybolmaması gereken taslak');
  await page.getByRole('button', {name: 'Görsel', exact: true}).click();
  await expect(page.locator('.studio-canvas')).toBeVisible();
  await page.getByRole('button', {name:'Tüm geçmiş', exact:true}).click();
  await expect(page.getByRole('dialog', {name:'Çalışmalarınız'})).toBeVisible();
  await expect(page.getByRole('textbox', {name:'Geçmişte ara'})).toBeVisible();
  await page.getByRole('button', {name:'Geçmişi kapat'}).click();
  await page.getByRole('button', {name: 'Asistan', exact: true}).click();
  await expect(page.locator('#assistant-question')).toHaveValue('Kaybolmaması gereken taslak');
  await page.reload();
  await expect(page.locator('#assistant-question')).toHaveValue('Kaybolmaması gereken taslak');
  await page.locator('#assistant-question').fill('');
  await page.screenshot({path:'../runtime-reports/ui-chat.png', fullPage:true, animations:"disabled"});
  await page.getByRole('button', {name:'Model Yönetimi', exact:true}).click();
  await expect(page.locator('.model-card').first()).toBeVisible();
  await page.getByRole('button', {name:'Görsel', exact:true}).click();
  await expect(page.locator('.studio-controls')).toBeVisible();
  await page.screenshot({path:'../runtime-reports/ui-image.png', fullPage:true, animations:"disabled"});
  await page.getByRole('button', {name:'Sistem ve Tercihler', exact:true}).click();
  await expect(page.getByRole('dialog', {name:'Sistem ve Tercihler'})).toBeVisible();
  await expect(page.getByRole('group', {name:'Tema', exact:true})).toBeVisible();
  await expect(page.getByRole('button', {name:'Ayarları kaydet', exact:true})).toHaveCount(0);
  await page.getByRole('button', {name:'Paneli kapat'}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  expect(errors).toEqual([]);
});

test('mobile and light layouts fit the viewport and language control works', async ({page}) => {
  await page.setViewportSize({width:390, height:844});
  await page.goto('/');
  await expect(page.locator('#assistant-question')).toBeVisible();
  await page.route('**/api/v1/settings', route => route.fulfill({json:{theme:'light',telemetry_refresh_seconds:5}}));
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await page.screenshot({path:'../runtime-reports/ui-mobile-light.png',fullPage:true, animations:"disabled"});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.getByRole('button', {name:'Dil', exact:true}).click();
  await page.getByRole('menuitemradio', {name: /English/}).click();
  await expect(page.locator('html')).toHaveAttribute('lang','en');
  await expect(page.getByRole('button',{name:'Send',exact:true})).toBeVisible();
});

test('LLM model control stays in the sidebar and code mode uses Gemma', async ({page}) => {
  await page.route('**/api/v1/llm/models', route => route.fulfill({json:{models:[
    {model_id:'gemma-4-12b',model:'Gemma 4 12B',state:'IDLE',start_allowed:true},
    {model_id:'qwen3.5-9b-q8_0',model:'Qwen3.5 9B Q8_0',state:'IDLE',start_allowed:true},
    {model_id:'gpt-oss-20b-mxfp4',model:'gpt-oss 20B MXFP4',state:'IDLE',start_allowed:true}
  ]}}));
  await page.goto('/');
  const dock = page.locator('.sidebar-model');
  const select = dock.locator('select');
  await expect(dock).toBeVisible();
  await expect(select).toHaveValue('gemma-4-12b');
  await expect(page.locator('.assistant-model-panel')).toHaveCount(0);
  await select.selectOption('qwen3.5-9b-q8_0');
  await expect(select).toHaveValue('qwen3.5-9b-q8_0');
  await page.getByRole('button',{name:'Kod Asistanı',exact:true}).click();
  await expect(select).toHaveValue('gemma-4-12b');
  await expect(select).toBeDisabled();
  await page.getByRole('button',{name:'Asistan',exact:true}).click();
  await expect(select).toHaveValue('qwen3.5-9b-q8_0');
});

test('stage 1: collapsible sidebar preserves model selection and keeps navigation accessible', async ({ page }) => {
  await page.route('**/api/v1/llm/models', route => route.fulfill({ json: { models: [
    { model_id:'gemma-4-12b', model:'Gemma 4 12B', state:'IDLE', start_allowed:true },
    { model_id:'gpt-oss-20b-mxfp4', model:'gpt-oss 20B', state:'IDLE', start_allowed:true },
  ] } }));
  await page.goto('/');
  const selector = page.locator('#sidebar-llm-model');
  await expect(selector).toBeVisible();
  await selector.selectOption('gpt-oss-20b-mxfp4');
  await page.getByRole('button', { name: 'Menüyü daralt' }).click();
  await expect(page.locator('.shell')).toHaveClass(/shell--compact/);
  await page.getByRole('button', { name: 'Kod Asistanı', exact: true }).click();
  await expect(page.getByRole('heading', { name:'Kod Asistanı', exact:true })).toBeVisible();
  await page.getByRole('button', { name: 'Menüyü genişlet' }).click();
  await expect(selector).toHaveValue('gemma-4-12b');
  await page.getByRole('button', { name: 'Asistan', exact: true }).click();
  await expect(selector).toHaveValue('gpt-oss-20b-mxfp4');
});

test('stage 1: mobile navigation opens as a drawer and closes on escape', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const sidebar = page.locator('.sidebar');
  await expect(sidebar).not.toBeVisible();
  await page.getByRole('button', { name:'Ana menüyü aç' }).click();
  await expect(sidebar).toBeVisible();
  await expect(sidebar.locator('.sidebar-model')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(sidebar).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
