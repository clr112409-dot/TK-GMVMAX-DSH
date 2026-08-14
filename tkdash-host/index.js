// TK-GMVMAX 看板宿主常驻插件（host-only）。
// 迁移自动态插件 tkdash-3：服务自动启动/常驻、dashboard_query 工具、/api/tkdash 端口路由、系统提示。
// 客户端浮层 UI 由会话级动态插件 tkdash-3 提供（find-port 复用本插件启动的服务，零冲突）。
// 可移植版：路径可用环境变量覆盖（DSH_TKDASH_PYTHON / DSH_TKDASH_ROOT / DSH_TKDASH_SANDBOX_ROOT），
// 未设置时回退到本机默认路径（自动安装脚本会为目标机写入正确的环境变量）。
import { defineTool } from '@deepseek-ai/dsh-tools'

function env(name) {
  return typeof process !== 'undefined' && process.env && process.env[name] ? process.env[name] : ''
}
const PYTHON = env('DSH_TKDASH_PYTHON') || 'C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe'
const ROOT = env('DSH_TKDASH_ROOT') || 'C:/Users/Administrator/Documents/Codex/TK-GMVMAX'
const BASE_PORT = 8501
const HELPER_VERSION = 'VERSION = 16'
const HELPER_CODE = [
  '# -*- coding: utf-8 -*-',
  'import json, os, sys, time, urllib.request',
  'VERSION = 16',
  'SERVER_TAG = "TK-GMVMAX-FBT"',
  'BASE = 8501',
  'RANGE = 12',
  'def is_panel(port):',
  '    try:',
  '        req = urllib.request.Request("http://127.0.0.1:%d/" % port, headers={"User-Agent": "dsh-plugin"})',
  '        with urllib.request.urlopen(req, timeout=1.5) as resp:',
  '            return resp.headers.get("Server", "").startswith(SERVER_TAG)',
  '    except Exception:',
  '        return False',
  'def find_port():',
  '    for p in range(BASE, BASE + RANGE):',
  '        if is_panel(p):',
  '            return p',
  '    return None',
  'def ensure_dir(path):',
  '    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)',
  'def atomic_write(path, data_bytes):',
  '    ensure_dir(path)',
  '    tmp = path + ".tmp"',
  '    with open(tmp, "wb") as f:',
  '        f.write(data_bytes)',
  '    os.replace(tmp, path)',
  'def fetch_to(url, out):',
  '    req = urllib.request.Request(url, headers={"User-Agent": "dsh-plugin", "Accept-Encoding": "identity"})',
  '    with urllib.request.urlopen(req, timeout=120) as resp:',
  '        data = resp.read()',
  '    atomic_write(out, data)',
  'def fresh_cache(path, seconds):',
  '    return os.path.exists(path) and os.path.getsize(path) > 0 and time.time() - os.path.getmtime(path) < seconds',
  'def main():',
  '    cmd = sys.argv[1]',
  '    if cmd == "find-port":',
  '        out = sys.argv[2]',
  '        port = find_port()',
  '        atomic_write(out, (str(port) if port else "0").encode("utf-8"))',
  '    elif cmd == "fetch":',
  '        url, out = sys.argv[2], sys.argv[3]',
  '        cache_seconds = int(sys.argv[4]) if len(sys.argv) > 4 else 300',
  '        if not fresh_cache(out, cache_seconds):',
  '            fetch_to(url, out)',
  '    else:',
  '        sys.exit(2)',
  'main()',
  '',
].join('\n')

export default {
  name: 'tkdash-host',
  inject: ['tools', 'shell', 'fs', 'webServer', 'systemPrompt', 'timer', 'sandboxPolicy'],
  apply(ctx) {
    const SANDBOX_ROOT = env('DSH_TKDASH_SANDBOX_ROOT')
      || (ctx.sandboxPolicy && ctx.sandboxPolicy.workspaceRoot)
      || 'C:/Users/Administrator'
    const WORK = SANDBOX_ROOT + '/.tkdash'
    const HELPER = WORK + '/helper.py'
    const PORT_FILE = WORK + '/port.txt'
    const STATE_FILE = WORK + '/state.json'
    const SIG_FILE = WORK + '/sig.json'
    const DATA_FILE = WORK + '/data.json'
    const META_FILE = WORK + '/meta.json'
    const INV_FILE = WORK + '/inv.json'
    const TOP_FILE = WORK + '/top.json'
    const TREND_FILE = WORK + '/trend.json'
    const LIFE_FILE = WORK + '/lifecycle.json'
    const POLICY = { mode: 'workspace-write', workspaceRoot: WORK }

    let knownPort = 0
    let helperReady = false
    let startPromise = null
    let lastSig = ''
    const inflight = new Map()

    function q(v) {
      return '"' + String(v).replace(/"/g, '\\"') + '"'
    }
    async function runShell(command, workdir, timeoutMs) {
      const spec = ctx.shell.resolve({ command, workdir, timeoutMs, stdoutMaxBytes: 8192, sandboxPolicy: POLICY })
      const result = await ctx.shell.run(spec)
      if (result.exitCode !== 0 && result.exitCode !== null) {
        const stderrText = result.stderr && result.stderr.text ? result.stderr.text : ''
        const stdoutText = result.stdout && result.stdout.text ? result.stdout.text : ''
        throw new Error('shell 执行失败(exit=' + result.exitCode + '): ' + (stderrText || stdoutText).slice(0, 1500))
      }
      return result
    }
    async function ensureHelper() {
      if (helperReady) return
      try {
        const existing = await ctx.fs.readText(await ctx.fs.resolve(HELPER))
        if (existing.indexOf(HELPER_VERSION) >= 0) {
          helperReady = true
          return
        }
      } catch (error) {
        // 文件不存在或不可读：继续写入
      }
      await ctx.fs.writeText(await ctx.fs.resolve(HELPER), HELPER_CODE)
      helperReady = true
    }
    async function runHelper(args, timeoutMs) {
      await ensureHelper()
      const cmd = '& ' + q(PYTHON) + ' ' + q(HELPER) + ' ' + args.map(q).join(' ')
      await runShell(cmd, WORK, timeoutMs || 120000)
    }
    function fetchFile(url, file, cacheSeconds) {
      const key = file
      if (inflight.has(key)) return inflight.get(key)
      const p = (async () => {
        try {
          await runHelper(['fetch', url, file, String(cacheSeconds)], 180000)
        } finally {
          inflight.delete(key)
        }
      })()
      inflight.set(key, p)
      return p
    }
    async function readTextFile(path) {
      return ctx.fs.readText(await ctx.fs.resolve(path))
    }
    async function findPort() {
      await runHelper(['find-port', PORT_FILE], 30000)
      const text = (await readTextFile(PORT_FILE)).trim()
      const port = parseInt(text, 10)
      return Number.isFinite(port) && port > 0 ? port : 0
    }
    async function writeState(port) {
      try {
        await ctx.fs.writeText(await ctx.fs.resolve(STATE_FILE), JSON.stringify({ port, saved_at: Date.now() }))
      } catch (error) {
        console.log('tkdash-host: write state failed: ' + (error && error.message))
      }
    }
    async function spawnServer() {
      const proc = ctx.shell.start(ctx.shell.resolve({
        command: '& ' + q(PYTHON) + ' ' + q(ROOT + '/dashboard_server.py') + ' --port ' + BASE_PORT + ' --no-browser',
        workdir: ROOT,
        sandboxPolicy: POLICY,
      }))
      return proc
    }
    async function ensureServer() {
      if (startPromise) return startPromise
      startPromise = (async () => {
        try {
          if (knownPort) {
            const alive = await findPort()
            if (alive) return alive
            knownPort = 0
          }
          const existing = await findPort()
          if (existing) {
            knownPort = existing
            await writeState(existing)
            return existing
          }
          const proc = await spawnServer()
          for (let i = 0; i < 40; i++) {
            const port = await findPort()
            if (port) {
              knownPort = port
              await writeState(port)
              return port
            }
            if (proc.status !== 'running' && proc.exitCode !== null) {
              const out = proc.readOutput()
              throw new Error('看板服务启动失败: ' + ((out && out.delta) || ('status=' + proc.status)).slice(0, 300))
            }
            await ctx.timer.timeout(2000)
          }
          throw new Error('看板服务 80 秒内未就绪')
        } finally {
          startPromise = null
        }
      })()
      return startPromise
    }
    async function refreshIfStale(port) {
      try {
        await fetchFile('http://127.0.0.1:' + port + '/api/signature', SIG_FILE, 10)
        const sig = JSON.parse(await readTextFile(SIG_FILE)).signature
        if (typeof sig === 'string' && sig && sig !== lastSig) {
          lastSig = sig
          return true
        }
      } catch (error) {
        console.log('tkdash-host: signature check failed: ' + (error && error.message))
      }
      return false
    }
    async function fetchJson(url, file) {
      const stale = await refreshIfStale(knownPort)
      await fetchFile(url, file, stale ? 0 : 300)
      const text = await readTextFile(file)
      return JSON.parse(text)
    }
    function num(v) {
      const n = typeof v === 'number' ? v : parseFloat(v)
      return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0
    }
    function countMap(map, keyFn) {
      const c = {}
      if (!map || typeof map !== 'object') return c
      for (const k in map) {
        const key = keyFn(map[k], k)
        c[key] = (c[key] || 0) + 1
      }
      return c
    }
    function summarizeMeta(m) {
      m = m || {}
      const tags = m.material_tags_count || {}
      const lifecycle = m.material_lifecycle_count || {}
      return {
        rows: m.rows, files: m.files, mapping: m.mapping,
        min_date: m.min_date, max_date: m.max_date,
        missing_dates: m.missing_dates || [],
        material_tags_count: Object.keys(tags).length ? tags : countMap(m.material_tags, (v) => v),
        material_lifecycle_count: Object.keys(lifecycle).length ? lifecycle : countMap(m.material_lifecycle, (v) => (v && v.stage) || '未知'),
        notes: m.notes || [],
      }
    }
    function dateInRange(d, from, to) {
      if (!d) return true
      const s = String(d).slice(0, 10)
      if (from && s < from) return false
      if (to && s > to) return false
      return true
    }
    function pickRow(r) {
      return {
        统计日期: r['统计日期'], 产品名称: r['产品名称'], 商品ID: r['商品 ID'],
        广告计划: r['广告计划名称'], 创意类型: r['创意作品类型'], 视频标题: r['视频标题'],
        视频ID: r['视频 ID'], 素材标识: r['素材标识'], 素材标签: r['素材标签'], 状态: r['状态'],
        成本: num(r['成本']), 总收入: num(r['总收入']), ROI: num(r['ROI']),
        SKU订单数: num(r['SKU 订单数']), 曝光: num(r['商品广告曝光数']),
        点击: num(r['商品广告点击数']), 转化率: num(r['广告转化率']),
      }
    }
    function opt(cond, obj) {
      return cond ? obj : {}
    }
    function briefSku(s) {
      return {
        sku: s.sku, product: s.product_code, name: (s.name || '').slice(0, 60),
        available: num(s.available), transit: num(s.transit), reserved: num(s.reserved),
        sales_30d: num(s.sales_30d), demand_30d: num(s.demand_30d),
        datel_avail_30d: num(s.datel_avail_30d), status: s.status,
        replenishment_date: s.replenishment_date || '', replenishment_qty: s.replenishment_qty || '',
      }
    }

    // ---------- 工具: dashboard_query（全局注册，跨会话可用） ----------
    ctx.tools.register(defineTool({
      name: 'dashboard_query',
      description: '查询用户的 TK-GMVMAX 看板（TikTok 广告素材分析 + FBT 库存监管，数据来自 daily_data 广告日报与 KCXQ 库存表）。mode: meta 返回数据概况；rows 返回广告明细行（keyword/日期过滤）；top 按视频 ID 聚合排序 Top N（product/metric/日期）；trend 返回按天趋势（days=N 近 N 天 vs 前 N 天环比）；lifecycle 按素材生命周期阶段筛选（stage: 新素材/新起量/稳定/衰退中/已停投/零消耗/待观察）；inventory 返回 FBT 库存概览（支持 product/status 过滤）；alerts 返回缺货/即将缺货 SKU（支持 product 过滤）与数据检查提示。每次查询自动对比源文件签名，Excel 更新后自动失效缓存拉取最新数据。服务未启动时自动启动。返回 JSON。',
      parameters: {
        mode: { type: 'string', enum: ['meta', 'rows', 'top', 'trend', 'lifecycle', 'inventory', 'alerts'], description: '查询模式，缺省 meta。' },
        keyword: { type: 'string', description: '过滤关键词（rows 模式），匹配产品名称/视频标题/素材标识/广告计划等。' },
        product: { type: 'string', description: '产品代码过滤（top/trend/lifecycle/inventory/alerts 模式），如 SZW011。' },
        metric: { type: 'string', enum: ['revenue', 'orders', 'roi', 'impressions'], description: 'top 模式排序指标，缺省 revenue（总收入）。' },
        date_from: { type: 'string', description: '起始日期 YYYY-MM-DD（top/rows/trend 模式）。' },
        date_to: { type: 'string', description: '结束日期 YYYY-MM-DD（top/rows/trend 模式）。' },
        days: { type: 'number', description: '环比天数（trend 模式），如 7：返回最近 7 天 vs 前 7 天的趋势与变化百分比。' },
        stage: { type: 'string', enum: ['新素材', '新起量', '稳定', '衰退中', '已停投', '零消耗', '待观察'], description: '素材生命周期阶段过滤（lifecycle 模式）。' },
        status: { type: 'string', enum: ['健康', '缺货', '即将缺货'], description: '库存状态过滤（inventory 模式）。' },
        limit: { type: 'number', description: '返回行数上限（rows 缺省 30，最大 200；inventory 缺省 20；top 缺省 10，最大 50；lifecycle 缺省 50，最大 200）。' },
      },
      output: {
        schema: { type: 'json' },
        render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }],
      },
      timeoutMs: 180000,
      async execute(args, exec) {
        const mode = typeof args.mode === 'string' && args.mode ? args.mode : 'meta'
        const limit = Math.min(Math.max(parseInt(args.limit, 10) || (mode === 'top' ? 10 : (mode === 'inventory' ? 20 : (mode === 'lifecycle' ? 50 : 30))), 1), 200)
        const port = await ensureServer()
        const dataUrl = 'http://127.0.0.1:' + port + '/api/data'
        const dateFrom = typeof args.date_from === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(args.date_from) ? args.date_from : ''
        const dateTo = typeof args.date_to === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(args.date_to) ? args.date_to : ''
        const product = typeof args.product === 'string' && args.product.trim() ? args.product.trim() : ''
        const kw = typeof args.keyword === 'string' && args.keyword.trim() ? args.keyword.trim() : ''
        const statusArg = typeof args.status === 'string' && args.status ? args.status : ''
        if (mode === 'top' || mode === 'trend' || mode === 'lifecycle') {
          const endpoint = mode === 'top' ? '/api/top' : (mode === 'trend' ? '/api/trend' : '/api/lifecycle')
          const parts = []
          if (product) parts.push('product=' + encodeURIComponent(product))
          if (mode === 'top') {
            const metric = typeof args.metric === 'string' && args.metric ? args.metric : 'revenue'
            parts.push('metric=' + encodeURIComponent(metric), 'limit=' + Math.min(limit, 50))
          }
          if (mode === 'lifecycle') {
            if (typeof args.stage === 'string' && args.stage) parts.push('stage=' + encodeURIComponent(args.stage))
            parts.push('limit=' + Math.min(limit, 200))
          }
          if (dateFrom) parts.push('date_from=' + dateFrom)
          if (dateTo) parts.push('date_to=' + dateTo)
          if (mode === 'trend') {
            const days = parseInt(args.days, 10)
            if (Number.isFinite(days) && days > 0) parts.push('days=' + Math.min(days, 90))
          }
          const url = 'http://127.0.0.1:' + port + endpoint + '?' + parts.join('&')
          const file = mode === 'top' ? TOP_FILE : (mode === 'trend' ? TREND_FILE : LIFE_FILE)
          const stale = await refreshIfStale(port)
          await fetchFile(url, file, stale ? 0 : 300)
          const text = await readTextFile(file)
          const result = JSON.parse(text)
          return Object.assign({
            mode, port,
          }, opt(product, { product }), opt(dateFrom, { date_from: dateFrom }), opt(dateTo, { date_to: dateTo }),
            mode === 'top' ? { metric: typeof args.metric === 'string' && args.metric ? args.metric : 'revenue' } : {},
            mode === 'lifecycle' && typeof args.stage === 'string' && args.stage ? { stage: args.stage } : {},
            result)
        }
        if (mode === 'meta') {
          const stale = await refreshIfStale(port)
          await fetchFile('http://127.0.0.1:' + port + '/api/meta', META_FILE, stale ? 0 : 300)
          const text = await readTextFile(META_FILE)
          return { mode, port, meta: summarizeMeta(JSON.parse(text)) }
        }
        if (mode === 'rows') {
          const d = await fetchJson(dataUrl, DATA_FILE)
          const rows = Array.isArray(d.rows) ? d.rows : []
          const filtered = rows.filter((r) => {
            if (!dateInRange(r['统计日期'], dateFrom, dateTo)) return false
            if (!kw) return true
            return [r['产品名称'], r['视频标题'], r['素材标识'], r['广告计划名称'], r['商品 ID'], r['创意作品类型']].some((v) => v !== undefined && v !== null && String(v).indexOf(kw) >= 0)
          })
          return Object.assign({
            mode, port,
            total: filtered.length, returned: Math.min(filtered.length, limit),
            meta: summarizeMeta(d.meta),
            rows: filtered.slice(0, limit).map(pickRow),
          }, opt(kw, { keyword: kw }), opt(dateFrom, { date_from: dateFrom }), opt(dateTo, { date_to: dateTo }))
        }
        const inv = await fetchJson('http://127.0.0.1:' + port + '/api/inventory', INV_FILE)
        const meta = inv.meta || {}
        const allSkus = Array.isArray(inv.skus) ? inv.skus : []
        const filteredSkus = allSkus.filter((s) => {
          if (product) {
            const pc = String(s.product_code || '')
            const sc = String(s.sku || '')
            if (pc.indexOf(product) < 0 && sc.indexOf(product) < 0) return false
          }
          if (statusArg && (s.status || '') !== statusArg) return false
          return true
        })
        const summary = {}
        for (const s of filteredSkus) {
          const st = s.status || '未知'
          summary[st] = (summary[st] || 0) + 1
        }
        const sorted = filteredSkus.slice().sort((a, b) => (num(b.sales_30d) - num(a.sales_30d)))
        if (mode === 'inventory') {
          return Object.assign({
            mode, port,
            meta: { file: meta.file, updated: meta.updated, rows: meta.rows, total_skus: filteredSkus.length },
            status_summary: summary,
            skus: sorted.slice(0, limit).map(briefSku),
          }, opt(product, { product }), opt(statusArg, { status: statusArg }))
        }
        const bad = filteredSkus.filter((s) => (s.status || '') !== '健康')
        const outOfStock = bad.filter((s) => (s.status || '') === '缺货')
        const lowStock = bad.filter((s) => (s.status || '') === '即将缺货')
        const other = bad.filter((s) => (s.status || '') !== '缺货' && (s.status || '') !== '即将缺货')
        let notes = []
        try {
          const d = await fetchJson(dataUrl, DATA_FILE)
          notes = (d.meta && d.meta.notes) || []
        } catch (error) {
          console.log('tkdash-host: data notes failed: ' + (error && error.message))
        }
        return Object.assign({
          mode, port,
          inventory_meta: { file: meta.file, updated: meta.updated, rows: meta.rows },
          status_summary: summary,
          out_of_stock: outOfStock.slice(0, limit).map(briefSku),
          low_stock: lowStock.slice(0, limit).map(briefSku),
          other_alerts: other.slice(0, limit).map(briefSku),
          data_notes: notes,
        }, opt(product, { product }))
      },
    }))

    // ---------- 端口路由：供浏览器端（动态插件 📊 按钮或任意页面）读取 ----------
    ctx.webServer.register({
      kind: 'exact',
      path: '/api/tkdash',
      handler: (req, res) => {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
        res.end(JSON.stringify({
          running: knownPort > 0,
          port: knownPort,
          url: knownPort > 0 ? 'http://127.0.0.1:' + knownPort : null,
        }))
      },
    })

    // ---------- 系统提示（全局，所有会话生效） ----------
    ctx.systemPrompt.section({
      name: 'tkdash',
      order: 206,
      text: '【TK 看板】用户有一个本地 TK-GMVMAX 看板（TikTok 广告素材分析 + FBT 库存监管）。需要分析广告/素材/库存数据时，调用 dashboard_query 工具（mode: meta/rows/top/trend/lifecycle/inventory/alerts；top/rows/trend 支持 date_from/date_to；trend 的 days 返回近 N 天环比；lifecycle 的 stage 可按素材生命周期阶段筛选；inventory 支持 product/status 过滤）。每次查询自动检测源文件变化并刷新数据。分析运营问题、给建议时优先基于看板真实数据。看板页面在 http://127.0.0.1:8501（服务由宿主自动启动）。',
    })

    // ---------- 宿主就绪后自动启动看板服务（常驻，跨会话） ----------
    ctx.on('ready', () => {
      ensureServer().catch((error) => {
        console.log('tkdash-host: 看板服务自动启动失败: ' + (error && error.message))
      })
    })
  },
}
