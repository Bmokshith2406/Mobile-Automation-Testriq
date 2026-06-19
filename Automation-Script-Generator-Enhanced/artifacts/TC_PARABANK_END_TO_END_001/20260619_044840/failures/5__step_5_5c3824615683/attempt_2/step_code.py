locator = page.get_by_role('textbox', name='Last name')
target = locator.first
await expect(target).to_be_visible(timeout=5000)
await target.fill('last name')