"""Local Edge smoke test: no brokerage credentials and no broker orders."""
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runtime'/'qa';OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
    page=browser.new_page(viewport={'width':1536,'height':1120},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None)
    page.goto('http://127.0.0.1:8775',wait_until='networkidle')
    page.locator('#demo').click()
    expect(page.locator('#run-status')).to_have_text('리플레이 실행 중')
    expect(page.locator('#watch-body tr')).to_have_count(3)
    expect(page.locator('#progress')).to_have_attribute('style','width: 100%;',timeout=30000)
    page.wait_for_timeout(1200)
    assert page.locator('#orders-body tr').count()>=4
    assert page.locator('#error').is_hidden()
    page.screenshot(path=str(OUT/'desk-demo.png'),full_page=True)
    page.locator('[data-view=settings]').click()
    assert page.locator('#settings-form input[name=base_rate]').input_value()=='5.5'
    page.screenshot(path=str(OUT/'settings.png'),full_page=True)
    page.locator('[data-view=journal]').click()
    assert page.locator('#fills-body tr').count()>=4
    with page.expect_download() as dl:page.get_by_text('실행 보고서 JSON ↓').click()
    assert dl.value.suggested_filename.endswith('.json')
    page.set_viewport_size({'width':390,'height':844});page.locator('[data-view=desk]').click();page.wait_for_timeout(300)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'mobile horizontal overflow'
    page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
    browser.close()
    assert not errors,errors
    print('PASS: desktop/mobile dashboard, demo fills, settings, journal, export; 0 browser errors')
