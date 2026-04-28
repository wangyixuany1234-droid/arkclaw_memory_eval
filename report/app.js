// Arkclaw 记忆评估报表前端逻辑

const state = {
  summaryRows: [],
  results: [],
  merged: [], // { summary, result }
};

function showError(message) {
  const banner = document.getElementById('errorBanner');
  if (!banner) return;
  banner.textContent = typeof message === 'string' ? message : String(message);
  banner.classList.remove('hidden');
}

async function loadData() {
  const statusBadge = document.getElementById('dataStatusBadge');

  // file:// 场景说明，不阻断页面其它渲染
  if (window.location.protocol === 'file:') {
    const msgLines = [
      '当前通过 file:// 直接打开报表，浏览器的安全策略会阻止 fetch 读取本地 summary.csv / results.jsonl。',
      '请使用已部署的 HTTP(S) 链接访问，或在报表目录下启用本地静态服务器（例如：python -m http.server 8000）。',
      '在 file:// 模式下，页面结构仍可展示，但数据图表无法自动加载。',
    ];
    showError(msgLines.join('\n'));
    if (statusBadge) {
      statusBadge.textContent = '数据状态：本地 file:// 环境，无法加载数据';
      statusBadge.className =
        'px-2 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-700';
    }
    return;
  }

  const attempts = {
    summary: [],
    results: [],
  };
  let lastErrorDetail = '';

  function buildPaths() {
    const pathname = window.location.pathname || '';
    const parts = pathname.split('/').filter(Boolean);
    const dirName = parts.length >= 2 ? parts[parts.length - 2].toLowerCase() : '';
    const inReportDir = dirName === 'report';

    const summaryPaths = [];
    const resultsPaths = [];

    if (inReportDir) {
      // .../report/index.html 场景：优先同级，其次 ../result/
      summaryPaths.push('summary.csv', '../result/summary.csv');
      resultsPaths.push('results.jsonl', '../result/results.jsonl');
    } else {
      // CDN 根目录或其它路径：先同级，再尝试 result/ 与 report/ 子目录
      summaryPaths.push('summary.csv', 'result/summary.csv', 'report/summary.csv');
      resultsPaths.push('results.jsonl', 'result/results.jsonl', 'report/results.jsonl');
    }

    return { summaryPaths, resultsPaths };
  }

  function withCacheBuster(path, ts) {
    return path + (path.indexOf('?') === -1 ? `?ts=${ts}` : `&ts=${ts}`);
  }

  async function fetchWithFallback(kind, paths, ts) {
    for (const path of paths) {
      const url = withCacheBuster(path, ts);
      try {
        const res = await fetch(url);
        if (!res.ok) {
          attempts[kind].push(`${path} (HTTP ${res.status})`);
          lastErrorDetail = `HTTP ${res.status}`;
          continue;
        }
        return res;
      } catch (e) {
        const label = e && e.message ? e.message : String(e);
        attempts[kind].push(`${path} (网络错误: ${label})`);
        lastErrorDetail = label;
      }
    }
    throw new Error(`${kind} 加载失败`);
  }

  try {
    const ts = Date.now();
    const { summaryPaths, resultsPaths } = buildPaths();

    const [summaryRes, resultsRes] = await Promise.all([
      fetchWithFallback('summary', summaryPaths, ts),
      fetchWithFallback('results', resultsPaths, ts),
    ]);

    const summaryText = await summaryRes.text();
    const resultsText = await resultsRes.text();

    const summaryParsed = Papa.parse(summaryText, {
      header: true,
      skipEmptyLines: true,
    });

    if (summaryParsed.errors && summaryParsed.errors.length > 0) {
      console.warn('解析 summary.csv 时存在告警：', summaryParsed.errors);
    }

    state.summaryRows = (summaryParsed.data || []).filter((row) => row.caseId);

    state.results = resultsText
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch (e) {
          console.warn('解析 results.jsonl 行失败：', e, line);
          return null;
        }
      })
      .filter(Boolean);

    mergeSummaryAndResults();
    initFilters();
    renderAll();
  } catch (err) {
    console.error(err);
    let message = '数据加载或解析失败。';
    const summaryAttempts = attempts.summary;
    const resultsAttempts = attempts.results;

    const details = [];
    if (summaryAttempts.length) {
      details.push(`summary.csv 尝试路径：${summaryAttempts.join(' -> ')}`);
    }
    if (resultsAttempts.length) {
      details.push(`results.jsonl 尝试路径：${resultsAttempts.join(' -> ')}`);
    }
    if (details.length) {
      message += '\n' + details.join('\n');
    }
    if (lastErrorDetail) {
      message += `\n最后错误：${lastErrorDetail}`;
    } else {
      message += `\n最后错误：${err}`;
    }

    showError(message);
    const badge = document.getElementById('dataStatusBadge');
    if (badge) {
      badge.textContent = '数据状态：加载失败';
      badge.className =
        'px-2 py-1 rounded-full bg-red-50 border border-red-200 text-red-700';
    }
  }
}

function mergeSummaryAndResults() {
  const resultByCaseId = new Map();
  for (const r of state.results) {
    const meta = r.case_meta || {};
    const id = meta.case_id || (r.case_meta && r.case_meta.case_id) || r.caseId;
    if (!id) continue;
    resultByCaseId.set(String(id), r);
  }

  state.merged = state.summaryRows.map((row) => {
    const caseId = String(row.caseId);
    const result = resultByCaseId.get(caseId) || null;
    return { summary: row, result };
  });

  const allTags = new Set();
  for (const { result } of state.merged) {
    if (result && result.case_meta && result.case_meta.iterationTag) {
      allTags.add(result.case_meta.iterationTag);
    }
  }
  const iterationBadge = document.getElementById('iterationTagBadge');
  if (iterationBadge) {
    iterationBadge.textContent =
      allTags.size === 1
        ? `迭代：${Array.from(allTags)[0]}`
        : `迭代：${allTags.size || '--'} 个`; // 多个迭代时提示数量
  }

  const statusList = document.getElementById('statusList');
  if (statusList) {
    const anyArkEnabled = state.results.some((r) => r.arkclawEnabled);
    const anyLlmEnabled = state.results.some((r) => r.llmJudgeEnabled);

    statusList.innerHTML = '';
    const li1 = document.createElement('div');
    li1.textContent = `Arkclaw 网关：${anyArkEnabled ? '已配置' : '未配置（仅记录输入，无真实回答）'}`;
    li1.className = 'text-slate-600';
    const li2 = document.createElement('div');
    li2.textContent = `LLM Judge：${anyLlmEnabled ? '已启用' : '未启用（仅规则分）'}`;
    li2.className = 'text-slate-600';
    statusList.appendChild(li1);
    statusList.appendChild(li2);
  }

  const statusBadge = document.getElementById('dataStatusBadge');
  if (statusBadge) {
    statusBadge.textContent = '数据状态：已加载';
    statusBadge.className =
      'px-2 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700';
  }
}

function initFilters() {
  const priorities = new Set();
  const memoryTypes = new Set();
  const timeDims = new Set();
  const iterationTags = new Set();

  for (const { summary, result } of state.merged) {
    if (summary.priority) priorities.add(summary.priority);
    if (summary.memoryType) memoryTypes.add(summary.memoryType);
    if (summary.timeDimension) timeDims.add(summary.timeDimension);
    if (result && result.case_meta && result.case_meta.iterationTag) {
      iterationTags.add(result.case_meta.iterationTag);
    }
  }

  function fillSelect(id, values) {
    const el = document.getElementById(id);
    if (!el) return;
    const current = el.value;
    el.innerHTML = '<option value="">全部</option>';
    Array.from(values)
      .sort()
      .forEach((v) => {
        const opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v;
        el.appendChild(opt);
      });
    if (current && values.has(current)) {
      el.value = current;
    }
  }

  fillSelect('filterPriority', priorities);
  fillSelect('filterMemoryType', memoryTypes);
  fillSelect('filterTimeDimension', timeDims);
  fillSelect('filterIterationTag', iterationTags);

  ['filterPriority', 'filterMemoryType', 'filterTimeDimension', 'filterIterationTag', 'filterLLMJudge'].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('change', () => renderAll());
      }
    },
  );

  const resetBtn = document.getElementById('resetFiltersBtn');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      ['filterPriority', 'filterMemoryType', 'filterTimeDimension', 'filterIterationTag', 'filterLLMJudge'].forEach(
        (id) => {
          const el = document.getElementById(id);
          if (el) el.value = '';
        },
      );
      renderAll();
    });
  }
}

function getFiltered() {
  const pri = document.getElementById('filterPriority')?.value || '';
  const mem = document.getElementById('filterMemoryType')?.value || '';
  const time = document.getElementById('filterTimeDimension')?.value || '';
  const tag = document.getElementById('filterIterationTag')?.value || '';
  const llm = document.getElementById('filterLLMJudge')?.value || '';

  return state.merged.filter(({ summary, result }) => {
    if (pri && summary.priority !== pri) return false;
    if (mem && summary.memoryType !== mem) return false;
    if (time && summary.timeDimension !== time) return false;
    if (tag) {
      const it = result && result.case_meta && result.case_meta.iterationTag;
      if (it !== tag) return false;
    }
    if (llm) {
      const enabled = !!(result && result.llmJudgeEnabled);
      if (llm === 'enabled' && !enabled) return false;
      if (llm === 'disabled' && enabled) return false;
    }
    return true;
  });
}

function renderAll() {
  const filtered = getFiltered();
  renderOverview(filtered);
  renderCharts(filtered);
  renderTable(filtered);
}

function renderOverview(filtered) {
  const totalCasesEl = document.getElementById('totalCases');
  const passRateEl = document.getElementById('passRate');
  const avgScoresEl = document.getElementById('avgScores');

  const total = filtered.length;
  if (totalCasesEl) totalCasesEl.textContent = String(total || '--');

  let pass = 0;
  let llmSum = 0;
  let llmCount = 0;
  let ruleSum = 0;
  let ruleCount = 0;

  for (const { result } of filtered) {
    if (!result || !result.judge) continue;
    const j = result.judge;
    if (j.final_label === 'pass') pass += 1;
    const llmScore = j.llm && typeof j.llm.score === 'number' ? j.llm.score : null;
    const ruleScore = j.rule && typeof j.rule.score === 'number' ? j.rule.score : null;
    if (llmScore !== null) {
      llmSum += llmScore;
      llmCount += 1;
    }
    if (ruleScore !== null) {
      ruleSum += ruleScore;
      ruleCount += 1;
    }
  }

  const rate = total > 0 ? ((pass / total) * 100).toFixed(1) + '%' : '--';
  if (passRateEl) passRateEl.textContent = rate;

  const llmAvg = llmCount > 0 ? (llmSum / llmCount).toFixed(2) : '--';
  const ruleAvg = ruleCount > 0 ? (ruleSum / ruleCount).toFixed(2) : '--';
  if (avgScoresEl) avgScoresEl.textContent = `${llmAvg} / ${ruleAvg}`;
}

function renderCharts(filtered) {
  renderChartByMemoryType(filtered);
  renderChartByPriority(filtered);
  renderChartDuration(filtered);
  renderChartTokens(filtered);
  renderChartFailureReasons(filtered);
}

function renderChartByMemoryType(filtered) {
  const el = document.getElementById('chartByMemoryType');
  if (!el) return;
  const chart = echarts.init(el);

  const byType = new Map();
  for (const { summary, result } of filtered) {
    const key = summary.memoryType || '未标注';
    const stat = byType.get(key) || { total: 0, pass: 0 };
    stat.total += 1;
    if (result && result.judge && result.judge.final_label === 'pass') stat.pass += 1;
    byType.set(key, stat);
  }

  const types = Array.from(byType.keys());
  const passRates = types.map((t) => {
    const s = byType.get(t);
    if (!s || s.total === 0) return 0;
    return +(100 * (s.pass / s.total)).toFixed(1);
  });

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 40, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: types, axisLabel: { interval: 0 } },
    yAxis: { type: 'value', name: '%', max: 100 },
    series: [
      {
        name: '通过率',
        type: 'bar',
        data: passRates,
        itemStyle: { color: '#0ea5e9' },
      },
    ],
  });
}

function renderChartByPriority(filtered) {
  const el = document.getElementById('chartByPriority');
  if (!el) return;
  const chart = echarts.init(el);

  const byPri = new Map();
  for (const { summary, result } of filtered) {
    const key = summary.priority || '未标注';
    const stat = byPri.get(key) || { total: 0, pass: 0 };
    stat.total += 1;
    if (result && result.judge && result.judge.final_label === 'pass') stat.pass += 1;
    byPri.set(key, stat);
  }

  const pris = Array.from(byPri.keys()).sort();
  const passRates = pris.map((p) => {
    const s = byPri.get(p);
    if (!s || s.total === 0) return 0;
    return +(100 * (s.pass / s.total)).toFixed(1);
  });

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 40, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: pris },
    yAxis: { type: 'value', name: '%', max: 100 },
    series: [
      {
        name: '通过率',
        type: 'bar',
        data: passRates,
        itemStyle: { color: '#22c55e' },
      },
    ],
  });
}

function renderChartDuration(filtered) {
  const el = document.getElementById('chartDuration');
  if (!el) return;
  const chart = echarts.init(el);

  let ingestSum = 0;
  let qaSum = 0;
  let judgeSum = 0;
  let count = 0;

  for (const { result } of filtered) {
    if (!result || !result.timing) continue;
    ingestSum += Number(result.timing.ingest_ms || 0);
    qaSum += Number(result.timing.qa_ms || 0);
    judgeSum += Number(result.timing.judge_ms || 0);
    count += 1;
  }

  const avgIngest = count ? +(ingestSum / count).toFixed(1) : 0;
  const avgQa = count ? +(qaSum / count).toFixed(1) : 0;
  const avgJudge = count ? +(judgeSum / count).toFixed(1) : 0;

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 40, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: ['Ingest', 'QA', 'Judge'] },
    yAxis: { type: 'value', name: 'ms' },
    series: [
      {
        name: '平均耗时',
        type: 'bar',
        data: [avgIngest, avgQa, avgJudge],
        itemStyle: { color: '#6366f1' },
      },
    ],
  });
}

function renderChartTokens(filtered) {
  const el = document.getElementById('chartTokens');
  if (!el) return;
  const chart = echarts.init(el);

  function calcStageAvg(stage) {
    let inputSum = 0;
    let inputCount = 0;
    let outputSum = 0;
    let outputCount = 0;
    let totalSum = 0;
    let totalCount = 0;

    for (const { result } of filtered) {
      if (!result || !result.tokens || !result.tokens[stage]) continue;
      const t = result.tokens[stage] || {};

      const inputRaw = t.input_tokens ?? t.input;
      const outputRaw = t.output_tokens ?? t.output;
      const totalRaw = t.total_tokens ?? t.total;

      if (inputRaw !== null && inputRaw !== undefined) {
        const v = Number(inputRaw);
        if (!Number.isNaN(v)) {
          inputSum += v;
          inputCount += 1;
        }
      }

      if (outputRaw !== null && outputRaw !== undefined) {
        const v = Number(outputRaw);
        if (!Number.isNaN(v)) {
          outputSum += v;
          outputCount += 1;
        }
      }

      if (totalRaw !== null && totalRaw !== undefined) {
        const v = Number(totalRaw);
        if (!Number.isNaN(v)) {
          totalSum += v;
          totalCount += 1;
        }
      }
    }

    return {
      input: inputCount ? +(inputSum / inputCount).toFixed(1) : 0,
      output: outputCount ? +(outputSum / outputCount).toFixed(1) : 0,
      total: totalCount ? +(totalSum / totalCount).toFixed(1) : 0,
    };
  }

  const ingest = calcStageAvg('ingest');
  const qa = calcStageAvg('qa');
  const judge = calcStageAvg('judge');

  const categories = ['Ingest', 'QA', 'Judge'];

  const inputSeries = [ingest.input, qa.input, judge.input];
  const outputSeries = [ingest.output, qa.output, judge.output];
  const totalSeries = [ingest.total, qa.total, judge.total];

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 40, right: 20, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: categories },
    yAxis: { type: 'value', name: 'tokens' },
    series: [
      {
        name: 'Input Tokens',
        type: 'bar',
        stack: 'tokens',
        data: inputSeries,
        itemStyle: { color: '#0284c7' },
      },
      {
        name: 'Output Tokens',
        type: 'bar',
        stack: 'tokens',
        data: outputSeries,
        itemStyle: { color: '#16a34a' },
      },
      {
        name: 'Reported Total',
        type: 'line',
        data: totalSeries,
        itemStyle: { color: '#9333ea' },
        smooth: true,
      },
    ],
  });
}

function renderChartFailureReasons(filtered) {
  const el = document.getElementById('chartFailureReasons');
  if (!el) return;
  const chart = echarts.init(el);

  const counter = new Map();
  for (const { result } of filtered) {
    if (!result || !result.judge) continue;
    const reasons = result.judge.failure_reasons || [];
    for (const r of reasons) {
      const key = r || 'unknown';
      counter.set(key, (counter.get(key) || 0) + 1);
    }
  }

  const items = Array.from(counter.entries()).sort((a, b) => b[1] - a[1]);
  const names = items.map((x) => x[0]);
  const values = items.map((x) => x[1]);

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 40, right: 20, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: names, axisLabel: { interval: 0 } },
    yAxis: { type: 'value' },
    series: [
      {
        name: '出现次数',
        type: 'bar',
        data: values,
        itemStyle: { color: '#f97316' },
      },
    ],
  });
}

function renderTable(filtered) {
  const tbody = document.getElementById('casesTableBody');
  const tableSummary = document.getElementById('tableSummary');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (tableSummary) {
    tableSummary.textContent = `${filtered.length} 条记录`;
  }

  for (const { summary, result } of filtered) {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-slate-50/80';

    const judge = result && result.judge ? result.judge : null;
    const finalLabel = judge ? judge.final_label : 'unknown';
    const llmScore = judge && judge.llm && typeof judge.llm.score === 'number' ? judge.llm.score.toFixed(2) : '--';
    const ruleScore = judge && judge.rule && typeof judge.rule.score === 'number' ? judge.rule.score.toFixed(2) : '--';

    const timing = (result && result.timing) || {};
    const totalMs = timing.total_ms != null ? Number(timing.total_ms) : null;

    const llmEnabled = !!(result && result.llmJudgeEnabled);

    const cells = [
      summary.caseId,
      summary.title || summary.scenario || '',
      summary.memoryType,
      summary.timeDimension,
      summary.priority,
      finalLabel,
      llmScore,
      ruleScore,
      totalMs != null ? String(totalMs) : '--',
      llmEnabled ? '已启用' : '未启用',
    ];

    cells.forEach((val, idx) => {
      const td = document.createElement('td');
      td.className = 'px-3 py-2 align-top';
      if (idx === 5) {
        // label with color
        const span = document.createElement('span');
        span.textContent = String(val || 'unknown');
        span.className = 'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium';
        if (val === 'pass') span.classList.add('bg-emerald-50', 'text-emerald-700');
        else if (val === 'partial') span.classList.add('bg-amber-50', 'text-amber-700');
        else span.classList.add('bg-rose-50', 'text-rose-700');
        td.appendChild(span);
      } else {
        td.textContent = val == null ? '' : String(val);
        td.className += ' text-slate-700';
      }
      tr.appendChild(td);
    });

    const tdDetail = document.createElement('td');
    tdDetail.className = 'px-3 py-2 align-top text-right';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = '展开';
    btn.className =
      'inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] text-slate-600 hover:border-sky-300 hover:text-sky-700 hover:bg-sky-50';

    const detailRow = document.createElement('tr');
    const detailTd = document.createElement('td');
    detailTd.colSpan = 11;
    detailTd.className = 'px-3 pb-3 pt-0';

    const detailDiv = document.createElement('div');
    detailDiv.className = 'mt-1 hidden rounded-lg border border-slate-100 bg-slate-50 px-3 py-3';

    btn.addEventListener('click', () => {
      const visible = !detailDiv.classList.contains('hidden');
      if (visible) {
        detailDiv.classList.add('hidden');
        btn.textContent = '展开';
      } else {
        detailDiv.classList.remove('hidden');
        btn.textContent = '收起';
        if (window.Prism) {
          window.Prism.highlightAllUnder(detailDiv);
        }
      }
    });

    tdDetail.appendChild(btn);
    tr.appendChild(tdDetail);

    // 构造详情内容：对话 + judge 摘要 + 原始事件摘要
    const title = document.createElement('div');
    title.className = 'text-[11px] font-medium text-slate-500 mb-1';
    title.textContent = '逐轮对话与评估详情';
    detailDiv.appendChild(title);

    if (result) {
      const convPre = document.createElement('pre');
      convPre.className = 'language-json text-[11px] bg-slate-900/90 text-slate-50 rounded-md p-2 overflow-x-auto mb-2';
      const convCode = document.createElement('code');
      convCode.className = 'language-json';
      const dialoguePreview = (result.dialogue || []).slice(0, 12); // 防止过长
      convCode.textContent = JSON.stringify(dialoguePreview, null, 2);
      convPre.appendChild(convCode);
      detailDiv.appendChild(convPre);

      const judgePre = document.createElement('pre');
      judgePre.className = 'language-json text-[11px] bg-slate-900/90 text-slate-50 rounded-md p-2 overflow-x-auto mb-2';
      const judgeCode = document.createElement('code');
      judgeCode.className = 'language-json';
      judgeCode.textContent = JSON.stringify(result.judge || {}, null, 2);
      judgePre.appendChild(judgeCode);
      detailDiv.appendChild(judgePre);

      const eventsPre = document.createElement('pre');
      eventsPre.className = 'language-json text-[11px] bg-slate-900/90 text-slate-50 rounded-md p-2 overflow-x-auto';
      const eventsCode = document.createElement('code');
      eventsCode.className = 'language-json';
      const eventsPreview = (result.rawEvents || []).slice(0, 5);
      eventsCode.textContent = JSON.stringify(eventsPreview, null, 2);
      eventsPre.appendChild(eventsCode);
      detailDiv.appendChild(eventsPre);
    } else {
      const empty = document.createElement('p');
      empty.className = 'text-[11px] text-slate-500';
      empty.textContent = '未找到对应的 results.jsonl 记录。';
      detailDiv.appendChild(empty);
    }

    detailTd.appendChild(detailDiv);
    detailRow.appendChild(detailTd);

    tbody.appendChild(tr);
    tbody.appendChild(detailRow);
  }
}

window.addEventListener('DOMContentLoaded', () => {
  loadData();
});

