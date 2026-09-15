import { expect, test } from '@playwright/test'

async function login(page: import('@playwright/test').Page, username: string, password: string) {
  await page.goto('/ops/')
  await page.getByLabel('帳號').fill(username)
  await page.getByLabel('密碼').fill(password)
  await page.getByRole('button', { name: '登入' }).click()
  await expect(page.getByRole('heading', { name: '登入' })).toHaveCount(0)
}

const completionImage = {
  name: 'completion.png',
  mimeType: 'image/png',
  buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
}

async function resetAndPrepareCleaningTask(page: import('@playwright/test').Page) {
  await login(page, 'admin', 'admin-demo')
  const task = await page.evaluate(async () => {
    const reset = await fetch('/api/demo/reset', { method: 'POST' })
    if (!reset.ok) throw new Error(`reset failed: ${reset.status}`)
    const response = await fetch('/api/decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_id: 'F2-RDE-0160-front', decision: 'confirm' }),
    })
    if (!response.ok) throw new Error(`prepare failed: ${response.status}`)
    return (await response.json()).task as { id: number }
  })
  await page.goto('/ops/inbox')
  await expect(page.locator('.ev').filter({ hasText: 'RDE-0160' }).first()).toBeVisible()
  await page.getByRole('button', { name: '登出' }).click()
  return task.id
}

async function stationCompletesCleaningTask(page: import('@playwright/test').Page) {
  await login(page, 'station', 'station-demo')
  const card = page.locator('.tcard').filter({ hasText: 'RDE-0160' })
  await card.getByRole('button', { name: '我來接單' }).click()
  await expect(card.getByText('已接單 · 待開工')).toBeVisible()
  await card.getByRole('button', { name: '開工' }).click()
  const chooserPromise = page.waitForEvent('filechooser')
  await card.getByRole('button', { name: '拍完工照' }).click()
  await (await chooserPromise).setFiles(completionImage)
  await expect(card.getByRole('button', { name: '✓ 完工', exact: true })).toBeEnabled()
  await card.getByRole('button', { name: '✓ 完工', exact: true }).click()
  await expect(card).toHaveCount(0)
  await page.getByRole('button', { name: '登出' }).click()
}

async function adminVerifiesCompletedTask(page: import('@playwright/test').Page, taskId: number) {
  await login(page, 'admin', 'admin-demo')
  await page.goto(`/ops/tasks/${taskId}`)
  await expect(page.getByText('已完成', { exact: true }).first()).toBeVisible()
  for (const label of ['Assigned / Claimed', 'Started', 'Photo Uploaded', 'Completed', 'Baseline Available']) {
    await expect(page.locator('.tl-title').filter({ hasText: label }).first()).toBeVisible()
  }
  await expect(page.getByText('清潔組 A · station').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: '完工照 · Completion Evidence' })
    .locator('xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " section ")][1]')
    .locator('.photo img')).toHaveCount(1)
  await page.getByRole('button', { name: '登出' }).click()
}

test('Phase 3 Admin role UI smoke', async ({ page }) => {
  await page.goto('/ops/')
  await expect(page.getByLabel('Demo 快速登入')).toBeVisible()
  await expect(page.getByRole('button', { name: '管理者 · admin' })).toBeVisible()
  await expect(page.getByRole('button', { name: '站點人員 · station' })).toBeVisible()
  await login(page, 'admin', 'admin-demo')
  await expect(page.getByRole('heading', { name: '通知中心' })).toBeVisible()
  await expect(page.getByText('RCR-7661').first()).toBeVisible()

  await page.locator('.ev').filter({ hasText: 'RCR-7661' }).first().click()
  await expect(page.getByText('Task Created')).toBeVisible()
  await expect(page.getByText('RCR-7661').first()).toBeVisible()

  await page.getByRole('button', { name: '關閉' }).click()
  await page.getByRole('link', { name: /整備看板/ }).click()
  await expect(page.getByRole('heading', { name: '整備看板' })).toBeVisible()
  for (const title of ['待處理', '處理中', '已完成']) {
    await expect(page.locator('.khead').filter({ hasText: title })).toBeVisible()
  }
})

test('Phase 3 Station role and capability smoke', async ({ page }) => {
  await login(page, 'station', 'station-demo')
  await expect(page.getByText('站點人員手機版')).toBeVisible()
  await expect(page.getByText('清潔組 A', { exact: true })).toBeVisible()
  const task = page.locator('.tcard').filter({ hasText: 'RCR-7661' })
  await expect(task).toBeVisible()
  await expect(task.getByRole('button', { name: '我來接單' })).toBeVisible()
  await expect(task.getByRole('button', { name: '開工' })).toHaveCount(0)
  await expect(task.getByRole('button', { name: /完工/ })).toHaveCount(0)

  await page.goto('/ops/settings')
  await expect(page).toHaveURL(/\/ops\/m$/)
  await expect(page.getByRole('heading', { name: '整備與通知設定' })).toHaveCount(0)
})

test('Phase 4 full Admin to Station lifecycle', async ({ page }) => {
  await login(page, 'admin', 'admin-demo')
  const event = page.locator('.ev').filter({ hasText: 'RDE-0160' }).first()
  await expect(event).toBeVisible()
  await event.click()
  await expect(page.getByText('Task Created')).toBeVisible()
  await expect(page.getByText('確認異常並建立任務')).toBeVisible()
  const taskUrl = page.url()
  await page.getByRole('button', { name: '關閉' }).click()
  await page.getByRole('button', { name: '登出' }).click()

  await login(page, 'station', 'station-demo')
  let card = page.locator('.tcard').filter({ hasText: 'RDE-0160' })
  await expect(card.getByRole('button', { name: '我來接單' })).toBeVisible()
  await card.getByRole('button', { name: '我來接單' }).click()
  await expect(card.getByRole('button', { name: '開工' })).toBeVisible()
  await card.getByRole('button', { name: '開工' }).click()
  await expect(card.getByRole('button', { name: '拍完工照' })).toBeVisible()

  const chooserPromise = page.waitForEvent('filechooser')
  await card.getByRole('button', { name: '拍完工照' }).click()
  const chooser = await chooserPromise
  await chooser.setFiles(completionImage)
  await expect(card.getByRole('button', { name: '✓ 完工', exact: true })).toBeEnabled()
  await card.getByRole('button', { name: '✓ 完工', exact: true }).click()
  await expect(card).toHaveCount(0)
  await page.getByRole('button', { name: '登出' }).click()

  await login(page, 'admin', 'admin-demo')
  await page.goto(taskUrl)
  await expect(page.getByText('已完成', { exact: true }).first()).toBeVisible()
  for (const label of ['Assigned / Claimed', 'Started', 'Photo Uploaded', 'Completed', 'Baseline Available']) {
    await expect(page.locator('.tl-title').filter({ hasText: label }).first()).toBeVisible()
  }
  await expect(page.getByText('清潔組 A · station').first()).toBeVisible()
  const completionEvidence = page.getByRole('heading', { name: '完工照 · Completion Evidence' })
    .locator('xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " section ")][1]')
  await expect(completionEvidence).toBeVisible()
  await expect(completionEvidence.locator('.photo img')).toHaveCount(1)
})

test('Phase 4.5 Demo reset supports two complete runs', async ({ page }) => {
  for (let round = 0; round < 2; round += 1) {
    const taskId = await resetAndPrepareCleaningTask(page)
    await stationCompletesCleaningTask(page)
    await adminVerifiesCompletedTask(page, taskId)
  }
})
