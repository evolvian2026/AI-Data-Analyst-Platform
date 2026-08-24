import { chromium } from 'playwright'
const OUT = '/tmp/claude-0/-home-user-AI-Data-Analyst-Platform/48375cb5-1a79-5554-a43a-fd949ebd4215/scratchpad/shots'
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await ctx.newPage()
const errors = []
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message))
const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true })

await page.goto('http://127.0.0.1:4173/signin')
await page.fill('#email','demo@example.com'); await page.fill('#password','Str0ngPassw0rd!')
await page.locator('button[type=submit]').click()
await page.waitForURL('**/app', {timeout:15000})
await page.getByRole('button', {name:'Open'}).first().click()
await page.waitForURL('**/overview', {timeout:60000})
await page.waitForTimeout(2500)
await shot('04-overview')

for (const [tab, name] of [['Data Story','05-story'],['Dashboard','06-dashboard'],['Insights','07-insights'],['Ask Your Data','08-ask'],['Data Quality','09-quality'],['Explore Data','10-explore'],['Reports','11-reports']]) {
  await page.getByRole('link', { name: tab, exact: true }).first().click()
  await page.waitForTimeout(2500)
  await shot(name)
}
console.log('ERRORS:', JSON.stringify([...new Set(errors)].slice(0,15), null, 1))
await browser.close()
