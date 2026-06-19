await page.wait_for_selector('text=Add button', timeout=10000, state='visible')
locator = page.locator('text=Add button')
target = locator.first
await expect(target).to_be_visible(timeout=5000)
await target.click()