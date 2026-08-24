import { chromium } from 'playwright'
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
const p = await b.newContext({ viewport:{width:1440,height:1000} }).then(c=>c.newPage())
p.on('pageerror', e => console.log('PAGEERROR', e.message))
p.on('console', m => { if(m.type()==='error') console.log('CONSOLE', m.text()) })
await p.goto('http://127.0.0.1:4173/signin')
await p.fill('#email','demo@example.com'); await p.fill('#password','Str0ngPassw0rd!')
await p.locator('button[type=submit]').click()
await p.waitForURL('**/app', {timeout:15000})
await p.getByRole('button', {name:'Open'}).first().click()
await p.waitForURL('**/overview', {timeout:60000})
await p.waitForTimeout(2500)
const info = await p.evaluate(() => {
  const svg = document.querySelector('.recharts-surface')
  const line = document.querySelector('.recharts-line-curve')
  const area = document.querySelector('.recharts-area-curve')
  const css = getComputedStyle(document.documentElement)
  return {
    svgExists: !!svg,
    svgBox: svg ? svg.getBoundingClientRect().toJSON() : null,
    lineD: line ? line.getAttribute('d')?.slice(0,120) : null,
    lineStroke: line ? line.getAttribute('stroke') : null,
    areaD: area ? area.getAttribute('d')?.slice(0,120) : null,
    series1: css.getPropertyValue('--series-1'),
    classes: [...document.querySelectorAll('.recharts-layer')].map(e=>e.getAttribute('class')).slice(0,10),
  }
})
console.log(JSON.stringify(info, null, 1))
await b.close()
