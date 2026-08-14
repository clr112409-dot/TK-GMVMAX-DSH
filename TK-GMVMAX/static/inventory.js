// ============ Data ============
let DATA = null;

var EMBEDDED_DATA = null;

function loadData() {
  if (typeof EMBEDDED_DATA !== 'undefined') {
    DATA = EMBEDDED_DATA;
    render();
    document.getElementById("dataTime").textContent = "本地数据 - " + new Date().toLocaleString("zh-CN");
  }
  // Try to fetch latest data
  fetchData();
  // Auto-refresh every 60 seconds
  setInterval(fetchData, 60000);
}

var lastInventoryEtag = "";
function fetchData() {
  var url = "/api/inventory?ts=" + Date.now();
  var x = new XMLHttpRequest();
  x.open("GET", url, true);
  if (lastInventoryEtag) x.setRequestHeader("If-None-Match", lastInventoryEtag);
  x.onload = function() {
    if (x.status === 304) return; // 库存文件未变化
    if (x.status === 200) {
      lastInventoryEtag = x.getResponseHeader("ETag") || "";
      try {
        var newData = JSON.parse(x.responseText);
        if (newData && newData.totals) {
          DATA = newData;
          render();
          document.getElementById("dataTime").textContent = "已更新 - " + new Date().toLocaleString("zh-CN") + (newData.meta && newData.meta.file ? " · " + newData.meta.file : "");
        }
      } catch(e) {}
    }
  };
  x.onerror = function() {
    var t = document.getElementById("dataTime");
    if (t && !DATA) t.textContent = "无法连接库存数据服务，请确认面板已启动。";
  };
  x.send();
}


// ============ Colors ============
const COLORS = {
  blue: '#2563eb', green: '#10b981', red: '#ef4444', orange: '#f59e0b',
  purple: '#8b5cf6', teal: '#14b8a6', pink: '#ec4899', cyan: '#06b6d4',
  indigo: '#6366f1', slate: '#64748b', amber: '#d97706', lime: '#65a30d',
  emerald: '#059669', rose: '#f43f5e',
  palette: ['#2563eb','#10b981','#f59e0b','#ef4444','#8b5cf6','#14b8a6','#ec4899','#06b6d4','#6366f1','#d97706'],
  palette2: ['#3b82f6','#22c55e','#eab308','#f87171','#a78bfa','#2dd4bf','#f472b6','#22d3ee','#818cf8','#fbbf24']
};

// ============ Render ============
function render() {
  var d = DATA;
  if (!d) return;
  document.getElementById('dataTime').textContent = '更新时间: ' + new Date().toLocaleString('zh-CN');
  renderKPI(d);
  renderChartsRow1(d);
  renderChartsRow2(d);
  renderAgingChart(d);
  renderTable(d);
}

// ============ KPI ============
function renderKPI(d) {
  var s = d.inventory_status || {};
  var t = d.totals || {};
  var sales = d.sales || {};
  var oos = s['\u7f3a\u8d27'] || 0;
  var healthy = s['\u5065\u5eb7'] || 0;
  var low = s['\u5373\u5c06\u7f3a\u8d27'] || 0;
  var total = t.total_skus || 0;
  var oosPct = total > 0 ? (oos/total*100).toFixed(1) : 0;
  
  var cards = [
    { label:'SKU 总数', value:total.toLocaleString(), sub:'', cls:'accent-blue' },
    { label:'可用库存', value:t.available?.toFixed(0), sub:'单位', cls:'accent-green' },
    { label:'在途库存', value:t.transit?.toFixed(0), sub:'单位', cls:'accent-teal' },
    { label:'缺货 SKU', value:oos.toLocaleString(), sub:'占 ' + oosPct + '%', cls:'accent-red' },
    { label:'健康 SKU', value:healthy.toLocaleString(), cls:'accent-green' },
    { label:'近期销量 (30d)', value:sales.total_30d?.toFixed(0), sub:'单位', cls:'accent-purple' },
  ];
  document.getElementById('kpiRow').innerHTML = cards.map(function(c) {
    return '<div class="kpi-card ' + c.cls + '"><div class="label">' + c.label + '</div><div class="value">' + c.value + '</div>' + (c.sub ? '<div class="sub">' + c.sub + '</div>' : '') + '</div>';
  }).join('');
}

// ============ SVG Donut ============
function svgDonut(cx, cy, r, data, colors) {
  var total = 0;
  data.forEach(function(d) { total += d.v; });
  if (total === 0) return '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="#e2e8f0" stroke-width="28"/>';
  var paths = [];
  var startAngle = -Math.PI / 2;
  var innerR = r * 0.62;
  data.forEach(function(d, i) {
    var pct = d.v / total;
    var angle = pct * 2 * Math.PI;
    var endAngle = startAngle + angle;
    var largeArc = angle > Math.PI ? 1 : 0;
    var x1 = cx + r * Math.cos(startAngle);
    var y1 = cy + r * Math.sin(startAngle);
    var x2 = cx + r * Math.cos(endAngle);
    var y2 = cy + r * Math.sin(endAngle);
    var xi1 = cx + innerR * Math.cos(endAngle);
    var yi1 = cy + innerR * Math.sin(endAngle);
    var xi2 = cx + innerR * Math.cos(startAngle);
    var yi2 = cy + innerR * Math.sin(startAngle);
    var dStr = 'M ' + x1 + ' ' + y1 + ' A ' + r + ' ' + r + ' 0 ' + largeArc + ' 1 ' + x2 + ' ' + y2 +
               ' L ' + xi1 + ' ' + yi1 + ' A ' + innerR + ' ' + innerR + ' 0 ' + largeArc + ' 0 ' + xi2 + ' ' + yi2 + ' Z';
    var c = colors[i % colors.length];
    paths.push('<path d="' + dStr + '" fill="' + c + '" opacity="0.9"><title>' + d.label + ': ' + d.v + '</title></path>');
    startAngle = endAngle;
  });
  return paths.join('\n');
}

function svgDonutLegend(data, colors) {
  return data.map(function(d, i) {
    return '<div class="legend-item"><span class="legend-dot" style="background:' + colors[i % colors.length] + '"></span>' + d.label + ': ' + d.v + '</div>';
  }).join('');
}

// ============ Charts Row 1 ============
function renderChartsRow1(d) {
  var status = d.inventory_status || {};
  var tags = d.goods_tags || {};
  var vol = d.sales_volume || {};
  
  var statusData = [];
  var statusColors = [];
  var statusLabels = {'\u7f3a\u8d27':'缺货','\u5065\u5eb7':'健康','\u5373\u5c06\u7f3a\u8d27':'即将缺货'};
  Object.keys(status).forEach(function(k) {
    statusData.push({label: statusLabels[k] || k, v: status[k]});
    if (k === '\u7f3a\u8d27') statusColors.push(COLORS.red);
    else if (k === '\u5065\u5eb7') statusColors.push(COLORS.green);
    else statusColors.push(COLORS.orange);
  });
  
  var tagsData = [];
  var tagsColors = [];
  Object.keys(tags).forEach(function(k, i) {
    tagsData.push({label: k, v: tags[k]});
    tagsColors.push(COLORS.palette[i % COLORS.palette.length]);
  });
  
  var volData = [];
  var volColors = [];
  Object.keys(vol).forEach(function(k, i) {
    volData.push({label: k + ' 件', v: vol[k]});
    volColors.push(COLORS.palette2[i % COLORS.palette2.length]);
  });

  document.getElementById('chartsRow1').innerHTML = [
    '<div class="chart-card"><h3>库存状态分布</h3><div class="chart-wrap"><svg width="220" height="220" viewBox="0 0 220 220">' + svgDonut(110,110,85,statusData,statusColors) + '</svg></div><div class="legend">' + svgDonutLegend(statusData,statusColors) + '</div></div>',
    '<div class="chart-card"><h3>商品标签分布</h3><div class="chart-wrap"><svg width="220" height="220" viewBox="0 0 220 220">' + svgDonut(110,110,85,tagsData,tagsColors) + '</svg></div><div class="legend">' + svgDonutLegend(tagsData,tagsColors) + '</div></div>',
    '<div class="chart-card"><h3>近30天销量分布 (SKU数)</h3><div class="chart-wrap"><svg width="220" height="220" viewBox="0 0 220 220">' + svgDonut(110,110,85,volData,volColors) + '</svg></div><div class="legend">' + svgDonutLegend(volData,volColors) + '</div></div>'
  ].join('');
}

// ============ SVG Bar ============
function svgBarChart(data, width, height, barColor, labelWidth) {
  if (!data || data.length === 0) return '';
  labelWidth = labelWidth || 80;
  var maxV = 0;
  data.forEach(function(d) { if (d.v > maxV) maxV = d.v; });
  maxV = maxV * 1.15 || 1;
  var chartW = width - labelWidth - 40;
  var chartH = data.length * 32 + 10;
  var bars = [];
  var offset = 0;
  data.forEach(function(d, i) {
    var barW = (d.v / maxV) * chartW;
    var y = offset + 6;
    var labelX = labelWidth;
    bars.push('<text x="0" y="' + (y + 14) + '" font-size="11" fill="#64748b" text-anchor="end">' + d.label + '</text>');
    bars.push('<rect x="' + labelWidth + '" y="' + y + '" width="' + Math.max(barW, 2) + '" height="20" rx="3" fill="' + barColor + '" opacity="0.85"><title>' + d.v + '</title></rect>');
    if (barW > 30) {
      bars.push('<text x="' + (labelWidth + barW - 6) + '" y="' + (y + 15) + '" font-size="10" fill="white" text-anchor="end" font-weight="600">' + d.v + '</text>');
    } else {
      bars.push('<text x="' + (labelWidth + barW + 4) + '" y="' + (y + 15) + '" font-size="10" fill="#475569" text-anchor="start">' + d.v + '</text>');
    }
    offset += 32;
  });
  return '<svg width="' + width + '" height="' + Math.max(50, offset + 10) + '" viewBox="0 0 ' + width + ' ' + Math.max(50, offset + 10) + '">' + bars.join('\n') + '</svg>';
}

// ============ Charts Row 2 ============
function renderChartsRow2(d) {
  var dos = d.dos_distribution || {};
  var brands = d.brands || {};
  
  var dosData = [];
  dosData.push({label:'缺货 (0天)', v: dos.zero || 0});
  dosData.push({label:'低库存 (<30天)', v: dos.low_under30 || 0});
  dosData.push({label:'健康 (30-90天)', v: dos.healthy_30to90 || 0});
  dosData.push({label:'过剩库存 (>90天)', v: dos.overstock_over90 || 0});
  
  var brandAvailData = [];
  var brandSalesData = [];
  var brandOOSData = [];
  Object.keys(brands).forEach(function(k) {
    var b = brands[k];
    brandAvailData.push({label: k, v: b.available});
    brandSalesData.push({label: k, v: b.sales_30d});
    brandOOSData.push({label: k, v: b.oos});
  });
  
  document.getElementById('chartsRow2').innerHTML = [
    '<div class="chart-card"><h3>供应天数分布 (SKU数)</h3><div class="chart-wrap">' + svgBarChart(dosData, 400, 200, COLORS.blue, 90) + '</div></div>',
    '<div class="chart-card"><h3>品牌对比</h3><div class="chart-wrap">' + 
      '<div style="display:grid;gap:12px">' +
        brandAvailData.map(function(b) {
          var sales = brandSalesData.find(function(s) { return s.label === b.label; });
          var oos = brandOOSData.find(function(o) { return o.label === b.label; });
          var bb = brands[b.label];
          return '<div style="background:#f8fafc;border-radius:6px;padding:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">' +
            '<div style="font-weight:600;min-width:100px">' + b.label + '</div>' +
            '<div style="display:flex;gap:16px;font-size:12px;flex-wrap:wrap">' +
              '<span>SKU: <strong>' + (bb?.skus||0) + '</strong></span>' +
              '<span>可用: <strong style="color:var(--success)">' + (b.v||0).toFixed(0) + '</strong></span>' +
              '<span>在途: <strong style="color:var(--primary)">' + (bb?.transit||0).toFixed(0) + '</strong></span>' +
              '<span>销量30d: <strong style="color:var(--purple)">' + (sales?.v||0).toFixed(0) + '</strong></span>' +
              '<span>缺货: <strong style="color:var(--danger)">' + (oos?.v||0) + '</strong></span>' +
            '</div></div>';
        }).join('') +
      '</div></div>'
  ].join('');
}

// ============ Canvas Aging Chart ============
function renderAgingChart(d) {
  var skus = d.skus || [];
  var buckets = ["0-30","31-60","61-90",">90"];
  var bucketKeys = ["aging_0_30","aging_31_60","aging_61_90","aging_over_90"];
  
  // Aggregate aging by product code
  var pcAging = {};
  skus.forEach(function(s) {
    var pc = s.product_code || "\u672a\u77e5";
    if (!pcAging[pc]) pcAging[pc] = {"0-30":0,"31-60":0,"61-90":0,">90":0};
    pcAging[pc]["0-30"] += s.aging_0_30 || 0;
    pcAging[pc]["31-60"] += s.aging_31_60 || 0;
    pcAging[pc]["61-90"] += s.aging_61_90 || 0;
    pcAging[pc][">90"] += s.aging_over_90 || 0;
  });
  
  // Per-bucket totals and product breakdowns
  var bucketData = [];
  buckets.forEach(function(b, bi) {
    var total = 0;
    var products = [];
    Object.keys(pcAging).forEach(function(pc) {
      var v = pcAging[pc][b];
      if (v > 0) { total += v; products.push({pc:pc, val:v}); }
    });
    products.sort(function(a,b){ return b.val - a.val; });
    bucketData.push({bucket:b, total:total, products:products, key:bucketKeys[bi]});
  });
  
  var maxVal = 0;
  bucketData.forEach(function(bd) { if (bd.total > maxVal) maxVal = bd.total; });
  maxVal = maxVal * 1.15 || 1;
  
  var canvas = document.getElementById("agingChart");
  var ctx = canvas.getContext("2d");
  var container = canvas.parentElement;
  var ratio = window.devicePixelRatio || 1;
  var W = container.clientWidth - 0;
  canvas.width = W * ratio;
  canvas.height = 300 * ratio;
  canvas.style.width = W + "px";
  canvas.style.height = "300px";
  ctx.scale(ratio, ratio);
  
  var pad = {top:20, bottom:30, left:50, right:20};
  var cw = W - pad.left - pad.right;
  var ch = 300 - pad.top - pad.bottom;
  var barW = Math.min(80, cw / buckets.length * 0.55);
  var gap = (cw - barW * buckets.length) / (buckets.length + 1);
  
  // Store bar positions for hover
  window._agingBarData = [];
  
  ctx.clearRect(0, 0, W, 300);
  
  // Grid lines
  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#94a3b8";
  ctx.font = "10px sans-serif";
  ctx.textAlign = "right";
  for (var gi = 0; gi <= 4; gi++) {
    var gy = pad.top + ch - (ch * gi / 4);
    ctx.beginPath(); ctx.moveTo(pad.left, gy); ctx.lineTo(W-pad.right, gy); ctx.stroke();
    ctx.fillText(Math.round(maxVal * gi / 4), pad.left - 6, gy + 4);
  }
  
  // Draw bars
  var colors = ["#2563eb","#059669","#d97706","#dc2626"];
  buckets.forEach(function(b, bi) {
    var bd = bucketData[bi];
    var x = pad.left + gap + bi * (barW + gap);
    var h = (bd.total / maxVal) * ch;
    var y = pad.top + ch - h;
    
    // Gradient
    var grad = ctx.createLinearGradient(x, y, x, pad.top + ch);
    grad.addColorStop(0, colors[bi % colors.length]);
    grad.addColorStop(1, colors[bi % colors.length] + "55");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.roundRect(x, y, barW, Math.max(h, 1), [3,3,0,0]);
    ctx.fill();
    
    // Value on top
    ctx.fillStyle = "#475569";
    ctx.font = "bold 11px sans-serif";
    ctx.textAlign = "center";
    if (h > 20) ctx.fillText(Math.round(bd.total), x + barW/2, y - 4);
    else ctx.fillText(Math.round(bd.total), x + barW/2, y - 8);
    
    // Label
    ctx.fillStyle = "#64748b";
    ctx.font = "11px sans-serif";
    ctx.fillText(b + " \u5929", x + barW/2, pad.top + ch + 16);
    
    // Store bar for hover
    window._agingBarData.push({bucket:b, total:bd.total, products:bd.products, x:x, y:pad.top, w:barW, h:ch, barY:y, barH:h});
  });
  
  // Y-axis label
  ctx.fillStyle = "#94a3b8";
  ctx.font = "10px sans-serif";
  ctx.textAlign = "center";
  ctx.save();
  ctx.translate(14, pad.top + ch/2);
  ctx.rotate(-Math.PI/2);
  ctx.fillText("\u5e93\u5b58\u5355\u4f4d", 0, 0);
  ctx.restore();
  
  // Hover tooltip
  canvas.onmousemove = function(e) {
    var rect = canvas.getBoundingClientRect();
    var mx = (e.clientX - rect.left) * (W / rect.width);
    var my = (e.clientY - rect.top) * (300 / rect.height);
    var tooltip = document.getElementById("agingTooltip");
    var found = null;
    
    for (var bi = 0; bi < (window._agingBarData||[]).length; bi++) {
      var bar = window._agingBarData[bi];
      if (mx >= bar.x && mx <= bar.x + bar.w && my >= bar.barY && my <= bar.barY + bar.barH) {
        found = bar;
        break;
      }
    }
    
    if (found && found.products.length > 0) {
      tooltip.style.display = "block";
      var html = "<div style=\"font-weight:700;margin-bottom:3px\">" + found.bucket + " \u5929: " + Math.round(found.total) + " \u5355\u4f4d</div>";
      found.products.forEach(function(p) {
        html += "<div>" + p.pc + ": " + Math.round(p.val) + "</div>";
      });
      tooltip.innerHTML = html;
      var tx = e.clientX - rect.left + 16;
      var ty = e.clientY - rect.top - 10;
      if (tx + 120 > W) tx = e.clientX - rect.left - 140;
      if (ty < 0) ty = 5;
      if (ty + 40 > 300) ty = 300 - 45;
      tooltip.style.left = tx + "px";
      tooltip.style.top = ty + "px";
    } else {
      tooltip.style.display = "none";
    }
  };
  canvas.onmouseleave = function() {
    var tooltip = document.getElementById("agingTooltip");
    if (tooltip) tooltip.style.display = "none";
  };
}function renderTable(d) {
  var fullSkus = d.skus || [];

  // Build product groups
  var groups = {};
  fullSkus.forEach(function(r) {
    var pc = r.product_code || r.sku.replace(/^([A-Z]+\d+).*/, "$1");
    if (!groups[pc]) {
      groups[pc] = {
        product_code: pc,
        skus: [],
        total_avail: 0, total_transit: 0, total_sales: 0,
        oos: 0, low: 0, healthy: 0
      };
    }
    var g = groups[pc];
    g.skus.push(r);
    g.total_avail += r.available || 0;
    g.total_transit += r.transit || 0;
    g.total_sales += r.sales_30d || 0;
    if (r.status === "缺货") g.oos++;
    else if (r.status === "即将缺货") g.low++;
    else g.healthy++;
  });
  
  window._groupData = groups;
  window._expandedGroups = {};
  window._allGroups = Object.keys(groups).sort();
  
  renderGroupedTable();
}

function renderGroupedTable() {
  var q = (document.getElementById("searchInput").value || "").toLowerCase().trim();
  var sf = document.getElementById("statusFilter").value;
  var groups = window._groupData || {};
  var expanded = window._expandedGroups || {};
  
  var filteredGroups = {};
  Object.keys(groups).forEach(function(pc) {
    var g = groups[pc];
    var skus_match = false;
    g.skus.forEach(function(r) {
      var name = (r.name || "").toLowerCase();
      var sku = (r.sku || "").toLowerCase();
      var status = r.status || "";
      var match = true;
      if (q && name.indexOf(q) < 0 && sku.indexOf(q) < 0 && pc.toLowerCase().indexOf(q) < 0) match = false;
      if (sf && status !== sf) match = false;
      if (match) skus_match = true;
    });
    var group_match = true;
    if (q && pc.toLowerCase().indexOf(q) < 0 && !skus_match) group_match = false;
    if (!q && !sf) group_match = true;
    if ((q || sf) && skus_match) group_match = true;
    if ((q || sf) && !skus_match) group_match = false;
    if (group_match) filteredGroups[pc] = g;
  });
  
  var totalSKUs = Object.values(groups).reduce(function(s,g){return s+g.skus.length;},0);
  var shownSKUs = Object.values(filteredGroups).reduce(function(s,g){return s+g.skus.length;},0);
  document.getElementById("rowCount").textContent = "显示 "+shownSKUs+" / "+totalSKUs+" 个SKU，共 "+Object.keys(filteredGroups).length+" 个产品组";
  
  var cols = [
    {key:"toggle", label:"", sortable:false},
    {key:"product_code", label:"产品代码", sortable:true},
    {key:"sku_count", label:"SKU数", sortable:true},
    {key:"goods_id", label:"Goods ID", sortable:false},
    {key:"available", label:"可用", sortable:true},
    {key:"transit", label:"在途", sortable:true},
    {key:"sales_30d", label:"销量30d", sortable:true},
    {key:"status", label:"状态", sortable:true},
    {key:"dos_30d", label:"供应天数", sortable:true},
    {key:"aging", label:"库龄分布", sortable:false},
    {key:"demand_30d", label:"需求预测30d", sortable:true},
  ];
  
  document.getElementById("tableHeaders").innerHTML = cols.map(function(c) {
    if (c.key === "toggle") return "<th style=\"width:28px\"></th>";
    var arrow = "";
    if (window._sortCol === c.key) arrow = window._sortDir === 1 ? " \u25b2" : " \u25bc";
    return "<th onclick=\"sortTable('"+c.key+"')\" data-col='"+c.key+"'>"+c.label+arrow+"</th>";
  }).join("");
  
  var sortedPCs = Object.keys(filteredGroups).sort(function(a,b) {
    var col = window._sortCol || "product_code";
    var dir = window._sortDir || 1;
    var va = col === "product_code" ? a : filteredGroups[a][col];
    var vb = col === "product_code" ? b : filteredGroups[b][col];
    if (typeof va === "string") va = va.toLowerCase();
    if (typeof vb === "string") vb = vb.toLowerCase();
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return 0;
  });
  
  if (!window._childSort) window._childSort = {};
  
  var tbody = document.getElementById("tableBody");
  tbody.innerHTML = "";
  
  sortedPCs.forEach(function(pc) {
    var g = filteredGroups[pc];
    var isExpanded = expanded[pc];
    
    var ss = "";
    if (g.oos > 0) ss += "<span style=\"color:#ef4444;font-weight:600\">"+g.oos+" \u7f3a\u8d27</span>";
    if (g.low > 0) { if(ss) ss+=" / "; ss+= "<span style=\"color:#f59e0b;font-weight:600\">"+g.low+" \u5373\u5c06\u7f3a\u8d27</span>"; }
    if (g.healthy > 0) { if(ss) ss+=" / "; ss+= "<span style=\"color:#10b981;font-weight:600\">"+g.healthy+" \u5065\u5eb7</span>"; }
    
    var cs = window._childSort[pc] || { col:"sku", dir:1 };
    
    var tr = document.createElement("tr");
    tr.className = "group-row";
    tr.style.cssText = "background:#f0f4ff;border-top:2px solid #e2e8f0";
    tr.innerHTML = [
      "<td style=\"text-align:center;font-size:14px;cursor:pointer\" onclick=\"toggleGroup('"+pc+"')\">"+(isExpanded?"\u25bc":"\u25b6")+"</td>",
      "<td style=\"font-weight:700;font-size:14px;cursor:pointer\" onclick=\"toggleGroup('"+pc+"')\">"+pc+"</td>",
      "<td style=\"cursor:pointer;user-select:none\" onclick=\"childSort('"+pc+"','sku')\" title=\"\u70b9\u51fb\u6309SKU\u6392\u5e8f\">"+g.skus.length+(cs.col==="sku"?" <span style=\"font-size:10px;color:#6366f1\">"+(cs.dir===1?"\u25b2":"\u25bc")+"</span>":"")+"</td>",
      "<td style=\"color:#64748b;font-size:11px\">"+g.skus[0].goods_id.substring(0,6)+(g.skus.length>1?"\u2026":"")+"</td>",
      "<td style=\"font-weight:700;color:#10b981;cursor:pointer;user-select:none\" onclick=\"childSort('"+pc+"','available')\" title=\"\u70b9\u51fb\u6309\u53ef\u7528\u5e93\u5b58\u6392\u5e8f\">"+Math.round(g.total_avail)+(cs.col==="available"?" <span style=\"font-size:10px;color:#6366f1\">"+(cs.dir===1?"\u25b2":"\u25bc")+"</span>":"")+"</td>",
      "<td style=\"cursor:pointer;user-select:none\" onclick=\"childSort('"+pc+"','transit')\" title=\"\u70b9\u51fb\u6309\u5728\u9014\u6392\u5e8f\">"+Math.round(g.total_transit)+(cs.col==="transit"?" <span style=\"font-size:10px;color:#6366f1\">"+(cs.dir===1?"\u25b2":"\u25bc")+"</span>":"")+"</td>",
      "<td style=\"font-weight:700;cursor:pointer;user-select:none\" onclick=\"childSort('"+pc+"','sales_30d')\" title=\"\u70b9\u51fb\u6309\u9500\u91cf\u6392\u5e8f\">"+Math.round(g.total_sales)+(cs.col==="sales_30d"?" <span style=\"font-size:10px;color:#6366f1\">"+(cs.dir===1?"\u25b2":"\u25bc")+"</span>":"")+"</td>",
      "<td onclick=\"toggleGroup('"+pc+"')\" style=\"cursor:pointer\">"+ss+"</td>",
      "<td onclick=\"toggleGroup('"+pc+"')\" style=\"cursor:pointer\">-</td>",
      "<td onclick=\"toggleGroup('"+pc+"')\" style=\"cursor:pointer\">—</td>",
      "<td onclick=\"toggleGroup('"+pc+"')\" style=\"cursor:pointer\">"+g.skus.filter(function(r){return r.demand_30d>0;}).length+" \u6709\u6570\u636e</td>",
    ].join("");
    tbody.appendChild(tr);
    
    if (isExpanded) {
      var skusData = [].concat(g.skus);
      if (q || sf) {
        skusData = skusData.filter(function(r) {
          var name = (r.name||"").toLowerCase();
          var sku = (r.sku||"").toLowerCase();
          var status = r.status||"";
          if (q && name.indexOf(q)<0 && sku.indexOf(q)<0) return false;
          if (sf && status!==sf) return false;
          return true;
        });
      }
      var dir = cs.dir||1;
      var col = cs.col||"sku";
      skusData.sort(function(a,b) {
        var va = col === "sku" ? (a[col]||"") : (Number(a[col])||0);
        var vb = col === "sku" ? (b[col]||"") : (Number(b[col])||0);
        if (col === "sku") {
          var re = /^(.*?)(\d+(?:\.\d+)?)$/;
          var ma = String(va).toLowerCase().match(re);
          var mb = String(vb).toLowerCase().match(re);
          if (ma && mb) {
            if (ma[1] !== mb[1]) { var cmp = ma[1] < mb[1] ? -1 : 1; return cmp * dir; }
            return (parseFloat(ma[2]) - parseFloat(mb[2])) * dir;
          }
        }
        if (va < vb) return -1*dir;
        if (va > vb) return 1*dir;
        return 0;
      });
      
      skusData.forEach(function(r) {
        var sc = "status-"+(r.status||"");
        var dc = "";
        if (r.dos_30d === 0) dc = "color:#ef4444";
        else if (r.dos_30d < 30) dc = "color:#f59e0b";
        var ct = document.createElement("tr");
        ct.className = "child-row";
        ct.style.cssText = "background:#fafcff";
        ct.innerHTML = [
          "<td style=\"background:#e8f0fe;width:28px\"></td>",
          "<td><span style=\"font-weight:500;font-family:'Consolas','Courier New',monospace;font-size:12px\">"+r.sku+"</span></td>",
          "<td></td>",
          "<td style=\"color:#64748b;font-size:11px\">"+r.goods_id+"</td>",
          "<td style=\"font-weight:600\">"+Math.round(r.available)+"</td>",
          "<td>"+Math.round(r.transit)+"</td>",
          "<td>"+Math.round(r.sales_30d)+"</td>",
          "<td><span class=\"status-badge "+sc+"\">"+(r.status||"-")+"</span></td>",
          "<td style=\""+dc+";font-weight:600\">"+(r.dos_30d>=999?"\u221e":r.dos_30d.toFixed(1))+"</td>",
          "<td style=\"font-size:11px;font-family:monospace\">"+function(r){var a=[];if(r.aging_0_30>0)a.push("0-30:"+Math.round(r.aging_0_30));if(r.aging_31_60>0)a.push("31-60:"+Math.round(r.aging_31_60));if(r.aging_61_90>0)a.push("61-90:"+Math.round(r.aging_61_90));if(r.aging_over_90>0)a.push(">90:"+Math.round(r.aging_over_90));return a.length?a.join(" "):"-";}(r)+"</td>",
      "<td>"+Math.round(r.demand_30d)+"</td>",
        ].join("");
        tbody.appendChild(ct);
      });
    }
  });
}
function toggleGroup(pc) {
  var expanded = window._expandedGroups || {};
  expanded[pc] = !expanded[pc];
  window._expandedGroups = expanded;
  renderGroupedTable();
}

function childSort(pc, col) {
  if (!window._childSort) window._childSort = {};
  var cs = window._childSort[pc] || { col:"sku", dir:1 };
  if (cs.col === col) cs.dir *= -1;
  else { cs.col = col; cs.dir = 1; }
  window._childSort[pc] = cs;
  renderGroupedTable();
}

function filterTable() {
  renderGroupedTable();
}

function sortTable(col) {
  if (window._sortCol === col) window._sortDir *= -1;
  else { window._sortCol = col; window._sortDir = 1; }
  renderGroupedTable();
  // Update header arrows
  document.querySelectorAll("#tableHeaders th").forEach(function(th) {
    var key = th.getAttribute("data-col");
    var arrow = "";
    if (key === window._sortCol) arrow = window._sortDir === 1 ? " \u25b2" : " \u25bc";
    th.innerHTML = th.innerHTML.replace(/[\u25b2\u25bc]/g, "") + arrow;
  });
}


// ============ Init ============
window.addEventListener('load', loadData);
window.addEventListener('resize', function() { if (DATA) renderAgingChart(DATA); });

function toggleTheme() {
  var t = document.documentElement.getAttribute('data-theme') === 'dark' ? '' : 'dark';
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('gmvTheme', t); } catch (e) {}
}
