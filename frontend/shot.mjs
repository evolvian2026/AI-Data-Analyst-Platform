import { chromium } from 'playwright'
const OUT = '/tmp/claude-0/-home-user-AI-Data-Analyst-Platform/48375cb5-1a79-5554-a43a-fd949ebd4215/scratchpad/shots'
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 })
const page = await ctx.newPage()
const errors = []
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))

async function shot(name) { await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true }) }

await page.goto('http://127.0.0.1:4173/', { waitUntil: 'networkidle' })
await shot('01-landing')

await page.goto('http://127.0.0.1:4173/signin')
await page.fill('#email', 'demo@example.com')
await page.fill('#password', 'Str0ngPassw0rd!')
const create = page.getByRole('button', { name: 'Create one' })
if (await create.count()) { await create.click(); await page.fill('#email','demo@example.com'); await page.fill('#password','Str0ngPassw0rd!') }
await page.locator('button[type=submit]').click()
await page.waitForURL('**/app', { timeout: 15000 }).catch(()=>{})
await page.waitForTimeout(1200)
await shot('02-workspace')

// load the sales sample
await page.getByRole('button', { name: /Retail Sales Performance/ }).click()
await page.waitForTimeout(1500)
await shot('03-processing')
await page.waitForURL('**/overview', { timeout: 90000 })
await page.waitForTimeout(2500)
await shot('04-overview')

for (const [tab, name] of [['Data Story','05-story'],['Dashboard','06-dashboard'],['Insights','07-insights'],['Ask Your Data','08-ask'],['Data Quality','09-quality'],['Explore Data','10-explore'],['Reports','11-reports']]) {
  await page.getByRole('link', { name: tab, exact: true }).first().click()
  await page.waitForTimeout(2200)
  await shot(name)
}
console.log('ERRORS:', JSON.stringify(errors.slice(0,20), null, 1))
await browser.close()
