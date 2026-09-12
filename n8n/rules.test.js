// اختبارات قواعد n8n المنشورة 2026-09-10 (نُسخت حرفياً من عقد الـworkflow)
// تشغيل: node n8n/tests/rules.test.js
let failed = 0;
function check(name, cond, detail) {
  console.log((cond ? '  ✔ ' : '  ✘ ') + name + (cond ? '' : '  <<< ' + JSON.stringify(detail)));
  if (!cond) failed++;
}

// ===== 1) «طلب بلا فاتورة سماك» لا يُعلن إلا إذا كان تقرير يومه محمّلاً (±1 يوم) =====
function makeCoverage(days) {
  const SAMAK_DAYS = {}; (days || []).forEach(function (d) { if (d) SAMAK_DAYS[d] = 1; });
  return function samakDayLoaded(d) {
    const s = String(d || '').trim(); if (!s) return true;
    const t = Date.parse(s + 'T00:00:00Z'); if (isNaN(t)) return true;
    for (let k = -1; k <= 1; k++) { const dd = new Date(t + k * 86400000).toISOString().slice(0, 10); if (SAMAK_DAYS[dd]) return true; }
    return false;
  };
}
function judgeNoInvoice(orderDate, loadedDays, tries) {
  const covered = makeCoverage(loadedDays)(orderDate);
  if (tries < 3) return { s: '🔍', why: 'بانتظار فاتورة سماك — لم يُغلق اليوم بعد' };
  if (!covered) return { s: '🔍', why: 'بانتظار تقرير سماك ليوم ' + String(orderDate || '').trim() };
  return { s: '🚨', why: 'استُنفدت 3 محاولات ولم تُوجد فاتورة سماك مقابلة' };
}

console.log('\n1) تقرير سماك لنفس اليوم موجود ← 🚨 مسموح');
let r = judgeNoInvoice('2026-09-08', ['2026-09-08'], 3);
check('الحالة 🚨', r.s === '🚨', r);

console.log('\n2) التقرير لليوم التالي فقط ← مغطّى بفارق يوم ← 🚨 مسموح');
r = judgeNoInvoice('2026-09-08', ['2026-09-09'], 3);
check('الحالة 🚨', r.s === '🚨', r);
r = judgeNoInvoice('2026-09-08', ['2026-09-07'], 3);
check('واليوم السابق كذلك', r.s === '🚨', r);

console.log('\n3) لا تقرير يغطي التاريخ ← بانتظار تقرير سماك، لا 🚨');
r = judgeNoInvoice('2026-08-27', ['2026-09-10'], 3);
check('ليست 🚨', r.s !== '🚨', r);
check('السبب يذكر اليوم', r.why === 'بانتظار تقرير سماك ليوم 2026-08-27', r.why);

console.log('\n4) بلا تاريخ مقروء ← يبقى كما هو (🚨 عند استنفاد المحاولات)');
r = judgeNoInvoice('', ['2026-09-10'], 3);
check('الحالة 🚨 كما كانت', r.s === '🚨', r);

console.log('\n5) محاولات أقل من ثلاث ← بانتظار اليوم كما كان');
r = judgeNoInvoice('2026-08-27', ['2026-09-10'], 2);
check('لم تتغيّر الرسالة القديمة', r.why.indexOf('لم يُغلق اليوم بعد') >= 0, r);

// ===== 2) أخطاء منصة Anthropic لا تُحسب محاولة =====
function attemptsOf(prevPlusOne, rawResponse) {
  const a = Number(prevPlusOne) || 1;
  const rt = String(rawResponse || '');
  if (/credit balance|rate_?limit|overloaded|api_error|insufficient_quota|too many requests/i.test(rt)) return Math.max(1, a - 1);
  return a;
}
console.log('\n6) خطأ رصيد يعود نصاً غير قابل للتفكيك ← لا تُحسب محاولة');
check('المحاولة الثالثة تعود إلى 2', attemptsOf(3, "Your credit balance is too low to access the Anthropic API") === 2, attemptsOf(3, 'credit balance'));
check('rate limit كذلك', attemptsOf(2, 'rate_limit_error: too many requests') === 1, attemptsOf(2, 'rate_limit_error'));
check('overloaded كذلك', attemptsOf(3, '{"type":"overloaded_error"}') === 2, attemptsOf(3, 'overloaded_error'));
check('لا تنزل تحت 1', attemptsOf(1, 'credit balance is too low') === 1, attemptsOf(1, 'credit'));

console.log('\n7) فشل قراءة الملف نفسه ← المحاولة تُحسب كما كانت');
check('قراءة سليمة', attemptsOf(2, '') === 2, attemptsOf(2, ''));
check('نص غير مفهوم من النموذج (فشل قراءة)', attemptsOf(3, 'I cannot read this receipt clearly') === 3, attemptsOf(3, 'x'));
check('فشل ffmpeg', attemptsOf(2, 'extraction_failed: ffmpeg could not decode') === 2, attemptsOf(2, 'ffmpeg'));


// ===== 3) تاريخ الطلب: الهرمية والاحتياط (قاعدة صاحبة النظام 2026-09-10) =====
// (أ) المطبوع في الفاتورة  (ب) ملغى: تاريخ اسم الملف  (ج) يوم الرفع/القراءة ناقص يوم
const DSRC_PRINTED = 'مطبوع', DSRC_INV = 'من فاتورة سماك';
const DSRC_UPLOAD = 'يوم الرفع −1', DSRC_READ = 'يوم القراءة −1';

function dayMinus1(ts) {
  const s = String(ts || '').trim(); if (!s) return '';
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/); if (!m) return '';
  const t = Date.parse(m[0] + 'T00:00:00Z'); if (isNaN(t)) return '';
  return new Date(t - 86400000).toISOString().slice(0, 10);
}

// تُطبَّق بعد المطابقة: التاريخ المطبوع يسبق كل شيء، ثم فاتورة سماك، ثم يوم الرفع/القراءة ناقص يوم.
function adoptDate(o) {
  const r = { date: '', dsrc: '' };
  if (o.printedDate) { r.date = o.printedDate; r.dsrc = DSRC_PRINTED; return r; }
  if (o.invoiceDate) { r.date = o.invoiceDate; r.dsrc = DSRC_INV; return r; }
  let d = dayMinus1(o.driveCreated);
  if (d) { r.date = d; r.dsrc = DSRC_UPLOAD; return r; }
  d = dayMinus1(o.logReadAt);
  if (d) { r.date = d; r.dsrc = DSRC_READ; }
  return r;
}
const estimated = (dsrc) => dsrc === DSRC_UPLOAD || dsrc === DSRC_READ;

// 🚨 مع تاريخ تقديري: تقارير الأيام الثلاثة كلها مطلوبة
function windowLoaded(d, days) {
  const s = String(d || '').trim(); if (!s) return false;
  const t = Date.parse(s + 'T00:00:00Z'); if (isNaN(t)) return false;
  const set = {}; (days || []).forEach(function (x) { if (x) set[x] = 1; });
  for (let k = -1; k <= 1; k++) { if (!set[new Date(t + k * 86400000).toISOString().slice(0, 10)]) return false; }
  return true;
}
function judgeNoInvoice2(o, loadedDays, tries) {
  const a = adoptDate(o);
  const why0 = estimated(a.dsrc) ? 'تاريخ تقديري (' + a.dsrc + ')' : '';
  if (tries < 3) return { s: '🔍', why: 'بانتظار فاتورة سماك — لم يُغلق اليوم بعد', date: a.date, dsrc: a.dsrc, note: why0 };
  if (estimated(a.dsrc) && !windowLoaded(a.date, loadedDays)) {
    return { s: '🔍', why: 'بانتظار تقرير سماك ليوم ' + a.date, date: a.date, dsrc: a.dsrc, note: why0 };
  }
  if (!makeCoverage(loadedDays)(a.date)) {
    return { s: '🔍', why: 'بانتظار تقرير سماك ليوم ' + a.date, date: a.date, dsrc: a.dsrc, note: why0 };
  }
  return { s: '🚨', why: 'استُنفدت 3 محاولات ولم تُوجد فاتورة سماك مقابلة', date: a.date, dsrc: a.dsrc, note: why0 };
}

console.log('\n8) فاتورة بتاريخ مطبوع ← يُتجاهل يوم الرفع');
r = adoptDate({ printedDate: '2026-09-08', driveCreated: '2026-09-10T02:34:00.000Z', logReadAt: '2026-09-10 09:03' });
check('التاريخ 2026-09-08 لا 2026-09-09', r.date === '2026-09-08', r);
check('المصدر «مطبوع»', r.dsrc === DSRC_PRINTED, r);

console.log('\n9) هنجر بلا تاريخ مطبوع رُفع 09-10 ← تاريخه 09-09');
r = adoptDate({ printedDate: '', invoiceDate: '', driveCreated: '2026-09-10T05:12:00.000Z' });
check('التاريخ 2026-09-09', r.date === '2026-09-09', r);
check('المصدر «يوم الرفع −1»', r.dsrc === DSRC_UPLOAD, r);
check('تقديري', estimated(r.dsrc) === true, r);

console.log('\n10) طلب 01:12 AM ← يطابق فاتورة سماك في اليوم التالي');
// الفاتورة مطبوعة 08-09-2026 01:12 AM ← 2026-09-08، وفاتورة سماك في 2026-09-09
const dcTol = (vDate, iDate) => {
  if (!vDate || !iDate) return { ok: true, diff: 0 };
  const t1 = Date.parse(iDate + 'T00:00:00Z'), t2 = Date.parse(vDate + 'T00:00:00Z');
  const d = Math.abs(Math.round((t1 - t2) / 86400000));
  return { ok: d <= 2, diff: d };
};
r = adoptDate({ printedDate: '2026-09-08' });
let dc = dcTol(r.date, '2026-09-09');
check('التاريخ المعتمد 2026-09-08', r.date === '2026-09-08', r);
check('فاتورة اليوم التالي مقبولة (فارق يوم)', dc.ok === true && dc.diff === 1, dc);
check('فاتورة بعد 3 أيام مرفوضة', dcTol(r.date, '2026-09-11').ok === false, dcTol(r.date, '2026-09-11'));

console.log('\n11) التاريخ التقديري لا يُنتج 🚨 إلا بتقارير الأيام الثلاثة');
r = judgeNoInvoice2({ driveCreated: '2026-09-10T05:12:00.000Z' }, ['2026-09-09'], 3);
check('يوم واحد محمّل ← بانتظار التقرير لا 🚨', r.s === '🔍' && /بانتظار تقرير سماك ليوم 2026-09-09/.test(r.why), r);
check('السبب يذكر «تاريخ تقديري»', /تاريخ تقديري/.test(r.note), r);
r = judgeNoInvoice2({ driveCreated: '2026-09-10T05:12:00.000Z' }, ['2026-09-08', '2026-09-09', '2026-09-10'], 3);
check('الأيام الثلاثة محمّلة ← 🚨', r.s === '🚨', r);

console.log('\n12) التاريخ المطبوع يكفيه تقرير يومه (±1) لإعلان 🚨');
r = judgeNoInvoice2({ printedDate: '2026-09-08' }, ['2026-09-08'], 3);
check('🚨 مع تقرير اليوم نفسه', r.s === '🚨', r);
check('المصدر «مطبوع» فلا ملاحظة تقدير', r.dsrc === DSRC_PRINTED && r.note === '', r);
r = judgeNoInvoice2({ printedDate: '2026-08-27' }, ['2026-09-08'], 3);
check('لا تقرير ليوم مطبوع ← بانتظار التقرير', r.s === '🔍', r);

console.log('\n13) (ب) تاريخ اسم الملف ملغى — الدليل من 51 ملفاً تاريخها المطبوع معروف');
// WhatsApp Video 2026-09-06 at 8.46 لطلب مطبوع في 2026-08-27 = فارق 10 أيام
const fnameDate = (n) => { const m = String(n || '').match(/(20\d{2})-(\d{2})-(\d{2})/); return m ? m[0] : ''; };
check('اسم الملف يعطي 2026-09-06', fnameDate('WhatsApp Video 2026-09-06 at 8.46.25 AM.mp4') === '2026-09-06');
check('والمطبوع 2026-08-27 ← لا يُعتمد اسم الملف',
  adoptDate({ printedDate: '2026-08-27', fileName: 'WhatsApp Video 2026-09-06 at 8.46.25 AM.mp4' }).date === '2026-08-27');
check('لا مصدر اسمه «اسم الملف» في القاعدة',
  [DSRC_PRINTED, DSRC_INV, DSRC_UPLOAD, DSRC_READ].every(function (x) { return x.indexOf('اسم الملف') < 0; }));

console.log('\n14) تاريخ موروث من الشيت بلا سند يُعاد حسابه بالقاعدة (ج)');
function adoptWithLegacy(o) {
  // التاريخ في الشيت لا يُصدَّق إلا إذا كان مطبوعاً أو من فاتورة مطابَقة
  if (o.printedDate) return { date: o.printedDate, dsrc: DSRC_PRINTED };
  if (o.inv) return { date: o.invoiceDate || o.sheetDate, dsrc: DSRC_INV };
  return adoptDate(o);
}
r = adoptWithLegacy({ sheetDate: '2026-09-08', inv: '', printedDate: '', logReadAt: '2026-09-09 17:03' });
check('يُعاد حسابه ← 2026-09-08 بمصدر «يوم القراءة −1»',
  r.date === '2026-09-08' && r.dsrc === DSRC_READ, r);
r = adoptWithLegacy({ sheetDate: '2026-08-27', inv: 'qws-5-5260', printedDate: '' });
check('صف له فاتورة يحتفظ بتاريخه بمصدر «من فاتورة سماك»',
  r.date === '2026-08-27' && r.dsrc === DSRC_INV, r);


// ===== 4) صمود الدفعة: ملف واحد لا يُسقط الباقي، والقراءة المحفوظة لا تُشترى مرتين =====
const MAX_TRIES_R = 3;
const CONNISH = /connection|econnreset|etimedout|timeout|socket|abort|502|503|504|bad gateway|internalservererror|api_5xx|api_timeout|api_connection|offline/i;

// قرار «فحص السجل» بعد التعديل
function decide(file, logEntry, seenMd5, seenKey) {
  const e = logEntry || null;
  let parsed = null;
  if (e && e.raw) {
    try { const q = JSON.parse(e.raw); parsed = (q && q.result !== undefined) ? q.result : q; } catch (x) { parsed = null; }
    if (parsed && (parsed.read_failed || parsed.skip)) parsed = null;
  }
  const st = (e && e.state) || {};
  const crashes = Number(st.crashes || 0) || 0;
  const md5 = String(file.md5 || '');
  const size = String(file.size || '');
  let dup = null;
  if (!parsed) {
    if (md5 && seenMd5[md5] && seenMd5[md5].id !== file.id) dup = seenMd5[md5];
    if (!dup && size) { const k = String(file.name || '') + '|' + size; if (seenKey[k] && seenKey[k].id !== file.id) dup = seenKey[k]; }
  }
  if (dup) return { cached: true, result: null, skip: 'duplicate', dup_of: dup.name, attempts: 0 };
  if (crashes >= 2 && !parsed) return { cached: true, result: null, skip: 'crash', attempts: (e.tries || 0) };
  if (!e) return { cached: false, attempts: 1 };
  if (e.redo) return { cached: false, attempts: 1 };
  if (!parsed) return { cached: false, attempts: (e.tries || 0) + 1 };
  return { cached: true, result: parsed, attempts: (e.tries || 1) };
}

// معالجة نتيجة الخدمة في «Parse Video Result» بعد التعديل
function parseResult(dec, svc, prevState) {
  const st = prevState || {};
  const skip = String(dec.skip || '');
  const status = String((svc && svc.status) || '');
  const err = String((svc && svc.error) || '');
  const kind = String((svc && svc.error_kind) || '');
  if (skip === 'duplicate' || skip === 'crash' || status === 'read_failed' || (!status && err)) {
    const prev = Number(st.crashes || 0) || 0;
    let note = '', crashes = prev, att = Number(dec.attempts || 0) || 0;
    if (skip === 'duplicate') { note = 'نسخة مكررة من ' + String(dec.dup_of || ''); att = 0; }
    else if (skip === 'crash') { note = 'الملف يُسقط الخدمة'; }
    else {
      const msg = err || 'خطأ غير معروف';
      note = 'فشل القراءة: ' + msg;
      if (CONNISH.test(msg) || CONNISH.test(kind)) { crashes = prev + 1; att = Math.max(0, (Number(dec.attempts || 1) || 1) - 1); }
    }
    return { no_row: true, note: note, attempts: att, state: { crashes: crashes, note: note }, raw_json: JSON.stringify({ read_failed: true, skip: skip || 'read_failed', note: note }) };
  }
  return { no_row: false, attempts: dec.attempts, state: { crashes: 0, note: '' }, raw_json: JSON.stringify({ result: (svc && svc.result) || {} }) };
}

const OK_RAW = JSON.stringify({ result: { platform: 'keeta', order_code: null, order_total: 38 } });

console.log('\n15) ملف واحد يفشل لا يُسقط الدفعة: سبب مكتوب وانتقال للملف التالي');
let d = decide({ id: 'f1', name: 'a.mp4', size: '100' }, null, {}, {});
let pr = parseResult(d, { status: 'read_failed', error: 'فشل القراءة: api_5xx: 502 Bad Gateway', error_kind: 'api_5xx' }, {});
check('لا صف لهذا الملف', pr.no_row === true, pr);
check('السبب يذكر «فشل القراءة»', /فشل القراءة/.test(pr.note), pr.note);
check('لا يُخزَّن كنتيجة قابلة للاستخدام', JSON.parse(pr.raw_json).read_failed === true, pr.raw_json);
d = decide({ id: 'f2', name: 'b.mp4', size: '200' }, null, {}, {});
pr = parseResult(d, { status: 'ok', result: { platform: 'keeta', order_total: 38 } }, {});
check('الملف التالي يُعالج ويُكتب له صف', pr.no_row === false && d.cached === false, [d, pr]);

console.log('\n16) أخطاء الاتصال لا تُحسب محاولة، وأخطاء أخرى تُحسب');
d = decide({ id: 'f1', name: 'a.mp4' }, { raw: '', tries: 1, redo: false, state: {} }, {}, {});
check('المحاولات ترتفع إلى 2 قبل المعالجة', d.attempts === 2, d);
pr = parseResult(d, { status: 'read_failed', error: 'connection aborted', error_kind: 'api_connection' }, { crashes: 0 });
check('خطأ اتصال ← المحاولات تعود إلى 1', pr.attempts === 1, pr);
check('عدّاد إسقاط الخدمة يرتفع إلى 1', pr.state.crashes === 1, pr.state);
pr = parseResult(d, { status: 'read_failed', error: 'api_status_400: bad request', error_kind: 'api_status_400' }, { crashes: 0 });
check('خطأ غير اتصالي ← المحاولات تبقى 2', pr.attempts === 2, pr);
check('ولا يرفع عدّاد الإسقاط', pr.state.crashes === 0, pr.state);
pr = parseResult({ attempts: 0 }, { status: 'read_failed', error: 'timeout', error_kind: 'api_timeout' }, { crashes: 0 });
check('المحاولات لا تنزل تحت صفر', pr.attempts === 0, pr);

console.log('\n17) ملف أسقط الخدمة في تشغيلين ← مراجعة يدوية بسبب «الملف يُسقط الخدمة»');
d = decide({ id: 'f1', name: 'a.mp4' }, { raw: '', tries: 1, redo: false, state: { crashes: 2 } }, {}, {});
check('لا يُرسل للخدمة', d.cached === true && d.skip === 'crash', d);
pr = parseResult(d, null, { crashes: 2 });
check('السبب «الملف يُسقط الخدمة»', pr.note === 'الملف يُسقط الخدمة', pr.note);
check('ولا صف له', pr.no_row === true, pr);
function closes(entry) {
  const tries = Number(entry.tries || 0) || 0;
  const st = entry.state || {};
  if (tries >= MAX_TRIES_R && !entry.redo && !entry.matched) return true;
  if ((Number(st.crashes || 0) || 0) >= 2 && !entry.redo) return true;
  return false;
}
check('يُنقل للمراجعة اليدوية', closes({ tries: 1, redo: false, matched: false, state: { crashes: 2 } }) === true);
check('إسقاط واحد لا يكفي', closes({ tries: 1, redo: false, matched: false, state: { crashes: 1 } }) === false);
check('«أعد المعالجة» يمنع النقل', closes({ tries: 1, redo: true, matched: false, state: { crashes: 5 } }) === false);

console.log('\n18) لا شراء قراءة مرتين: المحفوظة تُستخدم دائماً');
const savedOk = { raw: OK_RAW, tries: 1, redo: false, state: { md5: 'M1', size: '100' } };
d = decide({ id: 'f1', name: 'a.mp4', md5: 'M1', size: '100' }, savedOk, {}, {});
check('قراءة ناجحة محفوظة ← لا استدعاء API', d.cached === true && d.result, d);
check('حتى لو لم يُكتب لها صف في الشيت', d.cached === true, d);
check('وحتى لو order_code فارغ', d.result.order_code === null && d.cached === true, d);
d = decide({ id: 'f1', name: 'a.mp4', md5: 'M1', size: '100' }, Object.assign({}, savedOk, { redo: true }), {}, {});
check('«أعد المعالجة» وحده يفرض إعادة القراءة', d.cached === false && d.attempts === 1, d);
d = decide({ id: 'f1', name: 'a.mp4' }, { raw: JSON.stringify({ read_failed: true, note: 'فشل القراءة: x' }), tries: 1, redo: false, state: {} }, {}, {});
check('سجل «فشل القراءة» ليس ذاكرة صالحة ← يُعاد', d.cached === false, d);

console.log('\n19) النسخ المكررة: لا API ولا صف جديد');
const seenMd5 = { M1: { id: 'old1', name: 'VID_20260910_023329.mp4' } };
const seenKey = { 'VID_20260910_012456.mp4|17300000': { id: 'old3', name: 'VID_20260910_012456.mp4' } };
d = decide({ id: 'new1', name: 'VID_20260910_023329.mp4', md5: 'M1', size: '68700000' }, null, seenMd5, seenKey);
check('تطابق md5 ← نسخة مكررة', d.skip === 'duplicate' && d.dup_of === 'VID_20260910_023329.mp4', d);
check('لا استدعاء API', d.cached === true && d.result === null, d);
pr = parseResult(d, null, {});
check('السبب «نسخة مكررة من …»', pr.note === 'نسخة مكررة من VID_20260910_023329.mp4', pr.note);
check('ولا صف جديد', pr.no_row === true, pr);
check('ولا محاولة محسوبة', pr.attempts === 0, pr);
d = decide({ id: 'new3', name: 'VID_20260910_012456.mp4', md5: '', size: '17300000' }, null, seenMd5, seenKey);
check('بلا md5: الاسم + الحجم يكفيان', d.skip === 'duplicate' && d.dup_of === 'VID_20260910_012456.mp4', d);
d = decide({ id: 'new4', name: 'other.mp4', md5: 'ZZ', size: '999' }, null, seenMd5, seenKey);
check('ملف مختلف لا يُعدّ مكرراً', !d.skip && d.cached === false, d);
d = decide({ id: 'old1', name: 'VID_20260910_023329.mp4', md5: 'M1', size: '68700000' }, savedOk, seenMd5, seenKey);
check('الملف لا يُعدّ نسخة من نفسه', !d.skip && d.cached === true, d);


// ===== 5) حالتان ثابتتان من القراءات المحفوظة 2026-09-10 (بلا API) =====
// المصدر: سجل الاستخراج صف 93 (VID_20260910_211435 = qwd-5-1318) وصف 96 (20260910_125221 = qwd-5-1315)
// وفواتير سماك من تقرير 09-10 كما قرأها «Split Invoices & Items (Samak)» في التشغيل 820.

// نسخة حرفية من judgePrep في «Build Orders Table»
function judgePrep(prep, billed, cov) {
  cov = String(cov || 'none');
  if (!billed.length) return { st: 'not_verifiable', why: '' };
  if (!prep.length || cov === 'none') return { st: 'not_verifiable', why: 'لم تظهر أي عبوة بوضوح — تعذّر التحقق من التحضير' };
  const pm = {}, noCode = [];
  prep.forEach(function (p) {
    if (!p.r_code) { noCode.push(p.item_name || ''); return; }
    pm[p.r_code] = pm[p.r_code] || { n: 0, w: 0, name: p.item_name };
    const n = Number(p.seen_count) || 1;
    pm[p.r_code].n += n; pm[p.r_code].w += (Number(p.weight_g) || 0) * n;
  });
  const bm = {};
  billed.forEach(function (b) {
    if (!b.r_code) return;
    bm[b.r_code] = bm[b.r_code] || { q: 0, w: 0, name: b.item_name, lines: 0 };
    bm[b.r_code].q += Number(b.quantity) || 0;
    bm[b.r_code].w += Number(b.weight_g) || 0;
    bm[b.r_code].lines += 1;
  });
  const probs = [], unsure = [], review = [];
  const canAssertMissing = (cov === 'full' && noCode.length === 0);
  Object.keys(bm).forEach(function (k) {
    const b = bm[k], p = pm[k];
    if (!p) { if (canAssertMissing) probs.push(k + ' (' + (b.name || '') + ') مفوتر ولم يُحضَّر'); else unsure.push(k); return; }
    if (b.w && p.w && Math.abs(p.w - b.w) > Math.max(2, Math.round(b.w * 0.05))) {
      // وزن الملصق هو وزن العبوة الواحدة. إن كان المفوتر مضاعفاً صحيحاً لوزن العبوة
      // (500جم = علبتان 250جم) فالفرق في عدد العبوات لا في الوزن، وعدّ العبوات بصريًا
      // (seen_count) أضعف من أن يُتّهم به التحضير ⇒ «لم أتمكن من التحقق» لا «مخالفة».
      const unit = (Number(p.n) > 0) ? (p.w / Number(p.n)) : p.w;
      const mult = (unit > 0) ? (b.w / unit) : 0;
      if (unit > 0 && b.w > p.w && Math.abs(mult - Math.round(mult)) < 1e-6 && Math.round(mult) >= 2) {
        review.push(k + ': الفاتورة ' + b.w + 'جم = ' + Math.round(mult) + ' عبوة من ' + unit + 'جم ولم يظهر منها إلا ' + p.n);
      } else {
        probs.push(k + ': وزن المحضَّر ' + p.w + 'جم مقابل ' + b.w + 'جم بالفاتورة');
      }
    }
  });
  Object.keys(pm).forEach(function (k) { if (!bm[k]) probs.push(k + ' (' + (pm[k].name || '') + ') محضَّر وغير مفوتر'); });
  if (noCode.length) unsure.push(noCode.length + ' عبوة بلا كود على الملصق');
  if (probs.length) return { st: 'mismatch', why: probs.join(' ؛ ') };
  if (review.length) return { st: 'needs_review', why: review.join(' ؛ ') };
  if (unsure.length) return { st: 'not_verifiable', why: 'لم أتمكن من التحقق من: ' + unsure.join('، ') };
  if (cov === 'full') return { st: 'matched', why: '' };
  return { st: 'not_verifiable', why: 'التغطية جزئية — تحقق غير مكتمل' };
}

// نسخة حرفية من مقارنة الفيديو بسماك في «Build Orders Table»
const TOL_LINE_R = 0.50;
function compareLine(a, b, vHasMoney) {
  const probs = [], notes = [];
  const dp = Number((b.t - a.t).toFixed(2));
  const priceOk = (!vHasMoney || !a.t) ? true : Math.abs(dp) <= TOL_LINE_R;
  if (!priceOk) probs.push('سعر سماك ' + b.t.toFixed(2) + ' مقابل ' + a.t.toFixed(2) + ' بالفيديو');
  const qf = Number(a.q) > 1 ? Number(a.q) : 0;
  const wAmb = !!(qf && a.w && b.w && (Math.abs(a.w - b.w * qf) <= 1 || Math.abs(a.w * qf - b.w) <= 1));
  const wOff = (a.w && b.w) && Math.abs(Math.round(b.w - a.w)) > Math.max(1, Math.round(a.w * 0.02)) && !(wAmb && priceOk);
  const qOff = (a.q && b.q) && Math.abs(b.q - a.q) > 0.05;
  if (wOff || qOff) {
    const det = [];
    if (qOff) det.push('عدد القطع ' + b.q + ' بسماك مقابل ' + a.q + ' بالفيديو');
    if (wOff) det.push('الوزن الإجمالي ' + b.w + 'جم بسماك مقابل ' + a.w + 'جم بالفيديو');
    probs.push((priceOk ? 'المبلغ مطابق لكن ' : '') + det.join(' و'));
  }
  return { probs: probs, notes: notes };
}

// --- البيانات المحفوظة حرفياً ---
const PREP_1318 = [
  { r_code: 'R71', item_name: 'فول سوداني ملكي', seen_count: 1, weight_g: 250 },
  { r_code: 'R673', item_name: 'قضامة مالح', seen_count: 1, weight_g: 250 },
  { r_code: 'R80', item_name: 'حب دوار الشمس مالح', seen_count: 1, weight_g: 250 },
  { r_code: 'R75', item_name: 'متاي حار', seen_count: 1, weight_g: 250 },
  { r_code: 'R76', item_name: 'مكسرات يابانية مشكلة', seen_count: 1, weight_g: 250 },
  { r_code: 'R18', item_name: 'ذرة محمصة حار', seen_count: 1, weight_g: 250 },
];
// فاتورة سماك qwd-5-1318: سبعة سطور، R75 مرتين بـ0.25 كيلو لكل سطر
const BILLED_1318 = [
  { r_code: 'R18', item_name: 'ذرة محمصة حار  R18', quantity: 0.25, weight_g: 250 },
  { r_code: 'R673', item_name: 'قضامة محمصة مالحة  R673', quantity: 0.25, weight_g: 250 },
  { r_code: 'R80', item_name: 'حب دوار الشمس محمص مالح  R80', quantity: 0.25, weight_g: 250 },
  { r_code: 'R76', item_name: 'مكسرات يابانية مشكلة  R76', quantity: 0.25, weight_g: 250 },
  { r_code: 'R71', item_name: 'فول سوداني ملكي R71', quantity: 0.25, weight_g: 250 },
  { r_code: 'R75', item_name: 'متاي حار R75', quantity: 0.25, weight_g: 250 },
  { r_code: 'R75', item_name: 'متاي حار R75', quantity: 0.25, weight_g: 250 },
];
// نفس القراءة بعد بروتوكول العدّ الأعمى (التشغيل 836): R75 عبوتان بدليل الإطار 29 / الثانية 14.335
const PREP_1318_AFTER = PREP_1318.map(function (p) {
  return p.r_code === 'R75' ? { r_code: 'R75', item_name: 'متاي حار', seen_count: 2, weight_g: 250 } : p;
});
const PREP_1315 = [{ r_code: 'R373', item_name: 'صابون غار الأصلي', seen_count: 1, weight_g: 4000 }];
const BILLED_1315 = [{ r_code: 'R373', item_name: 'صابون الغار الاصلي   R373', quantity: 4, weight_g: null }];

// دالة تحويل حكم التحضير إلى حالة الصف، كما في judge() في «Build Orders Table»
function prepToStatus(st) {
  if (st === 'mismatch') return '📦';
  if (st === 'needs_review') return '🔍';
  return '✅';
}

console.log('\n20) qwd-5-1318 — القراءة الصحيحة: علبتان R75، وشبكة الأمان 🔍 لا ✅');
// (أ) القراءة الصحيحة بعد بروتوكول العدّ: R75 عبوتان ⇒ الوزن مطابق تماماً ولا ملاحظة وزن
let jp = judgePrep(PREP_1318_AFTER, BILLED_1318, 'full');
check('العدّ الصحيح (عبوتان) ⇒ لا مخالفة ولا ملاحظة وزن', jp.st === 'matched' && !jp.why, jp);
check('وحالة الصف ✅', prepToStatus(jp.st) === '✅', jp);
// (ب) شبكة الأمان: لو عاد العدّ واحداً والفاتورة علبتان ⇒ 🔍 لا ✅ ولا 📦
jp = judgePrep(PREP_1318, BILLED_1318, 'full');
check('عبوة واحدة مقابل علبتين ⇒ needs_review', jp.st === 'needs_review', jp);
check('وحالة الصف 🔍 لا ✅', prepToStatus(jp.st) === '🔍', jp);
check('بالسبب صريحاً', /R75: الفاتورة 500جم = 2 عبوة من 250جم ولم يظهر منها إلا 1/.test(jp.why), jp.why);
check('ولا يُتّهم بوزن مختلف', !/وزن المحضَّر 250جم مقابل 500جم/.test(jp.why), jp.why);
check('فاتورة سماك فيها سطران لـR75 كل منهما 250جم',
  BILLED_1318.filter(function (b) { return b.r_code === 'R75'; }).length === 2);
check('بقية الأصناف الخمسة بلا أي ملاحظة',
  !/R71|R673|R80|R76|R18/.test(jp.why), jp.why);

console.log('\n21) qwd-5-1315 — صابونة واحدة لا تُعدّ أربعاً: ⚠️ تبقى ⚠️');
jp = judgePrep(PREP_1315, BILLED_1315, 'full');
check('فحص التحضير لا يتدخّل (الفاتورة بالحبة لا بالوزن)', jp.st === 'matched', jp);
let cmp = compareLine({ q: 1, w: null, t: 40 }, { q: 4, w: null, t: 40 }, true);
check('المقارنة مع سماك ترصد فرق العدد', cmp.probs.length === 1, cmp);
check('بالنص الحرفي «المبلغ مطابق لكن عدد القطع 4 بسماك مقابل 1 بالفيديو»',
  cmp.probs[0] === 'المبلغ مطابق لكن عدد القطع 4 بسماك مقابل 1 بالفيديو', cmp.probs[0]);
check('القاعدة الجديدة لا تمسّها: b.w فارغ فلا يعمل فرع الوزن أصلاً',
  BILLED_1315[0].weight_g === null);

console.log('\n22) القاعدة الجديدة ضيّقة: لا تبتلع فروقاً حقيقية');
check('300جم مقابل علبة 250جم (ليس مضاعفاً) يبقى مخالفة',
  judgePrep([{ r_code: 'R9', seen_count: 1, weight_g: 250 }],
            [{ r_code: 'R9', quantity: 0.3, weight_g: 300 }], 'full').st === 'mismatch');
check('محضَّر أكثر من المفوتر يبقى مخالفة',
  judgePrep([{ r_code: 'R9', seen_count: 4, weight_g: 250 }],
            [{ r_code: 'R9', quantity: 0.25, weight_g: 250 }], 'full').st === 'mismatch');
check('صنف مفوتر لم يُحضَّر إطلاقاً يبقى مخالفة',
  judgePrep([{ r_code: 'R9', seen_count: 1, weight_g: 250 }],
            [{ r_code: 'R9', quantity: 0.25, weight_g: 250 }, { r_code: 'R8', quantity: 0.25, weight_g: 250 }], 'full').st === 'mismatch');
check('750جم = ثلاث علب 250جم ⇒ 🔍 لا ✅ ولا 📦',
  judgePrep([{ r_code: 'R9', seen_count: 1, weight_g: 250 }],
            [{ r_code: 'R9', quantity: 0.75, weight_g: 750 }], 'full').st === 'needs_review');
check('ولا تصبح ✅ أبداً',
  prepToStatus(judgePrep([{ r_code: 'R9', seen_count: 1, weight_g: 250 }],
            [{ r_code: 'R9', quantity: 0.75, weight_g: 750 }], 'full').st) === '🔍');

// ===== 6) الفحص الثاني المركّز: أعمى، كود واحد، ولا يُشترى مرتين (منسوخ من العقد) =====
function makeRecheck(tabRows){
  const tab = tabRows;
// ━━━━━ (3) الفحص الثاني المركّز: كود واحد في صف 🔍 ⇒ سؤال أعمى واحد، مرة واحدة ━━━━━
// المصدر هو صفوف الطلبات نفسها كما كُتبت في التشغيل السابق، فلا حالة جديدة في الشيت:
// أي صف 🔍 سببه نقص عدد عبوات لكود R يستحق سؤالاً واحداً مركّزاً عن ذلك الكود وحده.
const RCK=/(R\d+)\s*:\s*الفاتورة\s*[\d.]+\s*جم\s*=\s*\d+\s*عبوة من\s*[\d.]+\s*جم ولم يظهر منها إلا\s*\d+/g;
const PEND={};
tab.slice(1).forEach(function(r){
 const row=r||[];
 if(String(row[0]||'').indexOf('🔍')<0) return;
 const mm=String(row[1]||'').match(/[-\w]{25,}/);
 if(!mm) return;
 const txt=row.join(' ');
 const codes=[]; let m; RCK.lastIndex=0;
 while((m=RCK.exec(txt))) if(codes.indexOf(m[1])<0) codes.push(m[1]);
 if(codes.length) PEND[mm[0]]=codes;
});
// كل كود يُسأل مرة واحدة في عمر الملف: العلامة المخزّنة في عمود «حالة الملف» تمنع
// شراء القراءة مرة ثانية، ولا يُعاد السؤال إلا عند «أعد المعالجة» الذي يمسح كل شيء.
function pickRecheck(fid,st,parsed){
 const codes=PEND[fid]||[];
 if(!codes.length) return null;
 const done=(st&&st.recheck)||{};
 for(let i=0;i<codes.length;i++){
  const code=codes[i];
  const mark=String(done[code]||'');
  if(mark.indexOf('done')===0) continue;
  const frames=[];
  ((parsed&&parsed.label_sightings)||[]).forEach(function(s){
   if(String((s&&s.code)||'').toUpperCase()!==code.toUpperCase()) return;
   const f=Number(s.frame); if(f>0&&frames.indexOf(f)<0) frames.push(f);
  });
  return { code:code, frames:frames.sort(function(a,b){return a-b;}), prev:mark };
 }
 return null;
}

  return pickRecheck;
}

// نفس منطق «Parse Video Result» عند وصول رد count_only، معزولاً للاختبار
function applyRecheck(cj, cjs, svc, resultJson){
  const item = { json: { status: svc, result: resultJson } };
  const _cjs = cjs || {};
  const _svc = svc;
 // ━━━━━ رد الفحص الثاني المركّز: يُرقَّع العدد داخل القراءة المحفوظة، ولا يُشترى مرتين ━━━━━
 let _rcExtra={};
 if(cj.recheck_code){
  const _code=String(cj.recheck_code);
  const _keep=cj.keep_result?JSON.parse(JSON.stringify(cj.keep_result)):null;
  const _rk=Object.assign({},_cjs.recheck||{});
  const _cr=(_svc==='count_only'&&item.json&&item.json.result)?item.json.result:null;
  if(_cr&&_keep){
   const _n=(_cr.count===null||_cr.count===undefined)?null:Number(_cr.count);
   const _cf=String(_cr.confidence||'low');
   if(_n!==null&&_n>0&&(_cf==='high'||_cf==='medium')){
    _rk[_code]='done:'+_n;
    _rcExtra={ recheck:_rk, note:'فحص مركّز '+_code+': '+_n+' عبوة (ثقة '+_cf+')' };
    if(!Array.isArray(_keep.prepared_items)) _keep.prepared_items=[];
    let _hit=false;
    _keep.prepared_items.forEach(function(p){
     if(String((p&&p.code)||'').toUpperCase()===_code.toUpperCase()){ p.seen_count=_n; _hit=true; }
    });
    if(!_hit) _keep.prepared_items.push({ code:_code, name:'', seen_count:_n, label_weight:null });
   } else {
    // لم يحسم: الصف يبقى 🔍 كما هو، والعلامة تمنع إعادة الشراء بلا نهاية.
    _rk[_code]='done:unclear';
    _rcExtra={ recheck:_rk, note:'فحص مركّز '+_code+': لم يحسم — '+String(_cr.note||'العدّ غير واضح') };
   }
   item.json=Object.assign({},item.json,{ status:'ok', cached:true, result:_keep });
  } else if(_keep){
   // فشل استدعاء الفحص المركّز: القراءة المحفوظة لا تُمسّ ولا يُكتب «فشل القراءة»،
   // ومحاولة ثانية واحدة فقط ثم يُغلق الكود حتى لا يُشترى كل ساعة.
   const _prev=String((_cjs.recheck||{})[_code]||'');
   _rk[_code]=(_prev.indexOf('fail')===0)?'done:failed':'fail:1';
   _rcExtra={ recheck:_rk, note:'فحص مركّز '+_code+': تعذّر الاستدعاء' };
   item.json=Object.assign({},item.json,{ status:'ok', cached:true, result:_keep });
  }
 }

  return { state: _rcExtra, item: item.json };
}

const TAB = [
  ['الحالة','الفيديو','رقم الطلب'],
  ['🔍 يحتاج مراجعتي',
   '=HYPERLINK("https://drive.google.com/file/d/FILEAAAAAAAAAAAAAAAAAAAAAAAA/view","v.mp4")',
   'qwd-5-1318','2026-09-10','keeta','كيتا','Al Khaleej','Al Khaleej','','','',114.48,114.48,'أجل',
   'التحضير — R75: الفاتورة 500جم = 2 عبوة من 250جم ولم يظهر منها إلا 1'],
  ['✅ مطابق',
   '=HYPERLINK("https://drive.google.com/file/d/FILEBBBBBBBBBBBBBBBBBBBBBBBB/view","w.mp4")',
   'qwd-5-1320','2026-09-10','keeta','كيتا','Al Khaleej','Al Khaleej','','','',50,50,'أجل',
   'التحضير — R80: عبوتان × 250جم = 500جم — مطابق للفاتورة وسماك'],
  ['⚠️ فيه فرق',
   '=HYPERLINK("https://drive.google.com/file/d/FILECCCCCCCCCCCCCCCCCCCCCCCC/view","x.mp4")',
   'qwd-5-1315','2026-09-10','keeta','كيتا','Al Khaleej','Al Khaleej','','','',40,40,'أجل',
   'R373: المبلغ مطابق لكن عدد القطع 4 بسماك مقابل 1 بالفيديو'],
];
const pickRecheck = makeRecheck(TAB);
const READ = { prepared_items:[{code:'R75',name:'متاي حار',seen_count:1,label_weight:'250g'}],
               label_sightings:[{frame:7,t:3.2,code:'R75',positions:['أعلى يمين']},
                                {frame:8,t:3.6,code:'R75',positions:['أعلى يمين','أسفل']},
                                {frame:12,t:5.1,code:'R80',positions:['وسط']}] };

console.log('\n23) الكود المعلّق يُنتزع من سبب الصف 🔍 وحده');
let rc = pickRecheck('FILEAAAAAAAAAAAAAAAAAAAAAAAA', {}, READ);
check('الكود R75', rc && rc.code === 'R75', rc);
check('اللقطات هي لقطات هذا الكود فقط', JSON.stringify(rc.frames) === '[7,8]', rc);
check('صف ✅ لا يُسأل عنه أبداً', pickRecheck('FILEBBBBBBBBBBBBBBBBBBBBBBBB', {}, READ) === null);
check('صف ⚠️ بفرق عدد قطع لا يُسأل عنه (ليس نقص عبوات)',
      pickRecheck('FILECCCCCCCCCCCCCCCCCCCCCCCC', {}, READ) === null);
check('ملف لا صف له لا يُسأل عنه', pickRecheck('FILEZZZ', {}, READ) === null);
check('كود مسؤول عنه سابقاً لا يُشترى مرة ثانية',
      pickRecheck('FILEAAAAAAAAAAAAAAAAAAAAAAAA', {recheck:{R75:'done:2'}}, READ) === null);
check('ولا حتى إذا كان الجواب السابق غير حاسم',
      pickRecheck('FILEAAAAAAAAAAAAAAAAAAAAAAAA', {recheck:{R75:'done:unclear'}}, READ) === null);
check('محاولة فاشلة واحدة تُعاد مرة ثانية فقط',
      (pickRecheck('FILEAAAAAAAAAAAAAAAAAAAAAAAA', {recheck:{R75:'fail:1'}}, READ) || {}).code === 'R75');

console.log('\n24) الرد الواضح يُرقّع العدد في القراءة المحفوظة، وغير الواضح يُبقي الصف 🔍');
let ap = applyRecheck({recheck_code:'R75', keep_result:READ}, {crashes:0}, 'count_only',
                      {code:'R75', count:2, confidence:'high', per_frame:[], note:null});
check('seen_count صار 2', ap.item.result.prepared_items[0].seen_count === 2, ap.item.result.prepared_items);
check('العلامة تمنع الشراء ثانية', ap.state.recheck.R75 === 'done:2', ap.state);
check('السبب يذكر العدد والثقة', /فحص مركّز R75: 2 عبوة \(ثقة high\)/.test(ap.state.note), ap.state.note);
check('القراءة المحفوظة الأصلية لم تُمسّ (نسخة لا مرجع)', READ.prepared_items[0].seen_count === 1);
check('الرد يُعاد كقراءة سليمة لا كفشل', ap.item.status === 'ok' && ap.item.cached === true, ap.item.status);

ap = applyRecheck({recheck_code:'R75', keep_result:READ}, {crashes:0}, 'count_only',
                  {code:'R75', count:null, confidence:'low', per_frame:[], note:'الملصق محجوب'});
check('عدد غير محسوم لا يُرقّع شيئاً', ap.item.result.prepared_items[0].seen_count === 1, ap.item.result.prepared_items);
check('ويُعلَّم مغلقاً حتى لا يُشترى كل ساعة', ap.state.recheck.R75 === 'done:unclear', ap.state);
check('والسبب يقول لم يحسم', /لم يحسم/.test(ap.state.note), ap.state.note);

ap = applyRecheck({recheck_code:'R75', keep_result:READ}, {crashes:0}, 'count_only',
                  {code:'R75', count:3, confidence:'low', per_frame:[], note:null});
check('ثقة منخفضة لا تُرقّع ولو أعطت عدداً', ap.item.result.prepared_items[0].seen_count === 1, ap.item.result);

ap = applyRecheck({recheck_code:'R75', keep_result:READ}, {crashes:1}, 'read_failed', null);
check('فشل الفحص المركّز لا يمسح القراءة المحفوظة',
      ap.item.result && ap.item.result.prepared_items[0].seen_count === 1, ap.item);
check('ولا يُكتب «فشل القراءة» على الملف', ap.item.status === 'ok', ap.item.status);
check('محاولة أولى تُعلَّم fail:1', ap.state.recheck.R75 === 'fail:1', ap.state);
ap = applyRecheck({recheck_code:'R75', keep_result:READ}, {crashes:1, recheck:{R75:'fail:1'}}, 'read_failed', null);
check('والثانية تُغلق الكود نهائياً', ap.state.recheck.R75 === 'done:failed', ap.state);

ap = applyRecheck({recheck_code:'R99', keep_result:READ}, {crashes:0}, 'count_only',
                  {code:'R99', count:2, confidence:'high', per_frame:[], note:null});
check('كود لم يُرَ في القراءة يُضاف بندَ عبوات لا يُلقى',
      ap.item.result.prepared_items.length === 2
      && ap.item.result.prepared_items[1].seen_count === 2, ap.item.result.prepared_items);

// ===== 7) تغطية سماك بالتاريخ والفرع معاً + بقاء نقص العبوات في السبب =====
const BR = [['0001','Al Masiaf','المصيف'],['0002','Al Wisham','الوشم'],['0003','Al Khaleej','الخليج'],
            ['0004','Al Yasmin','الياسمين'],['0005','Dhahrat Laban','ظهرة لبن']];
function makeCov(freshInv){
  const SAMAK_DAYS={}, SAMAK_COV={};
  (freshInv||[]).forEach(function(v){ const dd=String(v.date||'').trim(); if(!dd) return; SAMAK_DAYS[dd]=1;
    const bc=String(v.branch_code||'').trim(); if(bc) SAMAK_COV[dd+'|'+bc]=1; });
  function dayHas(dd,bc){ if(!SAMAK_DAYS[dd]) return false; if(!bc) return true; return !!SAMAK_COV[dd+'|'+bc]; }
  function brAr(bc){ const r=BR.filter(function(b){ return b[0]===bc; })[0]; return r?r[2]:''; }
  function waitWhy(d,bc,bn){ const dd=String(d||'').trim();
    return bc ? ('بانتظار تقرير سماك لفرع '+(bn||bc)+' ليوم '+dd) : ('بانتظار تقرير سماك ليوم '+dd); }
  function samakDayLoaded(d,bc){ const s=String(d||'').trim(); if(!s) return true;
    const t=Date.parse(s+'T00:00:00Z'); if(isNaN(t)) return true;
    if(bc) return dayHas(s,bc);
    for(let k=-1;k<=1;k++){ const dd=new Date(t+k*86400000).toISOString().slice(0,10); if(dayHas(dd,bc)) return true; }
    return false; }
  function samakWindowLoaded(d,bc){ const s2=String(d||'').trim(); if(!s2) return false;
    const t2=Date.parse(s2+'T00:00:00Z'); if(isNaN(t2)) return false;
    for(let k=-1;k<=1;k++){ const dd=new Date(t2+k*86400000).toISOString().slice(0,10); if(!dayHas(dd,bc)) return false; }
    return true; }
  return { samakDayLoaded:samakDayLoaded, samakWindowLoaded:samakWindowLoaded, waitWhy:waitWhy, brAr:brAr };
}

// التقارير المحمَّلة فعلاً في 2026-09-12 (مقيسة من تشغيل حقيقي):
// 09-10 الخليج فقط · 09-09 الخليج فقط · 09-08 الفروع الخمسة · 08-27 الخمسة · 08-28 الياسمين فقط
const FRESH = [].concat(
  [{date:'2026-09-10',branch_code:'0003'}],
  [{date:'2026-09-09',branch_code:'0003'}],
  ['0001','0002','0003','0004','0005'].map(function(b){ return {date:'2026-09-08',branch_code:b}; }),
  ['0001','0002','0003','0004','0005'].map(function(b){ return {date:'2026-08-27',branch_code:b}; }),
  [{date:'2026-08-28',branch_code:'0004'}]);
const CV = makeCov(FRESH);

console.log('\n25) 🚨 لا تُعلن إلا إذا كان التقرير يغطي التاريخ والفرع معاً');
check('الخليج 09-09 مغطى ⇒ البوابة مفتوحة', CV.samakDayLoaded('2026-09-09','0003') === true);
check('الياسمين 09-09 غير مغطى ⇒ لا 🚨', CV.samakDayLoaded('2026-09-09','0004') === false);
check('وتغطية الياسمين في اليوم المجاور (09-08) لا تكفي',
      CV.samakDayLoaded('2026-09-09','0004') === false);
check('الياسمين 09-08 مغطى ⇒ البوابة مفتوحة', CV.samakDayLoaded('2026-09-08','0004') === true);
check('ظهرة لبن 08-28 غير مغطى ⇒ لا 🚨', CV.samakDayLoaded('2026-08-28','0005') === false);
check('يوم بلا أي تقرير يبقى غير مغطى لكل الفروع',
      CV.samakDayLoaded('2026-09-01','0003') === false);
check('فرع غير مقروء يرجع للقاعدة القديمة (تاريخ ±يوم)',
      CV.samakDayLoaded('2026-09-09','') === true);
check('وبلا تاريخ مقروء لا تُمنع 🚨 كما كان', CV.samakDayLoaded('','0004') === true);

console.log('\n26) نص الانتظار يسمّي الفرع، وبلا فرع يبقى كما كان');
check('بالفرع', CV.waitWhy('2026-09-09','0004',CV.brAr('0004'))
      === 'بانتظار تقرير سماك لفرع الياسمين ليوم 2026-09-09');
check('بلا فرع', CV.waitWhy('2026-09-09','','')
      === 'بانتظار تقرير سماك ليوم 2026-09-09');
check('اسم الفرع عربي لا إنجليزي', CV.brAr('0003') === 'الخليج');
check('كود مجهول لا يكسر النص', CV.waitWhy('2026-09-09','0009','') === 'بانتظار تقرير سماك لفرع 0009 ليوم 2026-09-09');

console.log('\n27) التاريخ التقديري يشترط الأيام الثلاثة لنفس الفرع');
check('الخليج: 09-08 و09-09 و09-10 كلها مغطاة ⇒ نافذة مكتملة',
      CV.samakWindowLoaded('2026-09-09','0003') === true);
check('الياسمين: 09-09 و09-10 غير مغطيين ⇒ نافذة ناقصة',
      CV.samakWindowLoaded('2026-09-09','0004') === false);
check('الخليج 08-27: يوم 08-26 غير محمّل ⇒ نافذة ناقصة',
      CV.samakWindowLoaded('2026-08-27','0003') === false);

console.log('\n28) نقص العبوات يبقى في السبب حتى مع مخالفة وزن أخرى');
function prepWhy(probs, review, okNotes){
  // نفس ترتيب judgePrep بعد الإصلاح
  if(probs.length) return { st:'mismatch', why:probs.concat(review).join(' ؛ ') };
  if(review.length) return { st:'needs_review', why:okNotes.concat(review).join(' ؛ ') };
  return { st:'matched', why:okNotes.join(' ؛ ') };
}
let pw = prepWhy(['R248: وزن المحضَّر 500جم مقابل 1000جم بالفاتورة'],
                 ['R247: الفاتورة 1000جم = 2 عبوة من 500جم ولم يظهر منها إلا 1'], []);
check('الحالة تبقى مخالفة', pw.st === 'mismatch', pw);
check('ونقص العبوات لم يُحذف من السبب', /ولم يظهر منها إلا 1/.test(pw.why), pw.why);
check('والمخالفة الأصلية باقية أولاً', pw.why.indexOf('R248') < pw.why.indexOf('R247'), pw.why);
pw = prepWhy([], ['R75: الفاتورة 500جم = 2 عبوة من 250جم ولم يظهر منها إلا 1'], []);
check('بلا مخالفة أخرى تبقى 🔍 كما كانت', pw.st === 'needs_review', pw);
check('صف بلا نقص ولا مخالفة يبقى مطابقاً بلا نص زائد',
      prepWhy([], [], ['R80: عبوتان × 250جم = 500جم — مطابق للفاتورة وسماك']).st === 'matched');


console.log('\n29) قائمة سماك البيضاء — بالرمز أولاً، ثم الاسم، ثم مستبعدة/مجهولة');
// منقولة حرفياً من «Split Invoices & Items (Samak)»
const WHITE_CODES = { '3':['toyou','تويو'], '5':['hunger','هنجر'], '21':['jahez','جاهز'],
                      '31':['marsool','مرسول'], '52':['thechefz','شيفز'], '342':['keeta','كيتا'],
                      '355':['ninja','نينجا'] };
const BLACK_CODES = { '19':'امازون', '7':'سلة', '379':'مضارب نجدية' };
const BLACK_NAMES = ['الموردين المحليين'];
function arNormT(s){ return String(s==null?'':s).replace(/[ً-ْـ]/g,'').replace(/[یى]/g,'ي')
  .replace(/[ک]/g,'ك').replace(/[أإآ]/g,'ا').replace(/ة/g,'ه').replace(/\s+/g,''); }
const PF_T = [['keeta','كيتا',['keeta','كيتا']],['jahez','جاهز',['jahez','جاهز']],
 ['hunger','هنجر',['hunger','hungerstation','هنجر','هنقر','هنجرستيشن']],
 ['ninja','نينجا',['ninja','نينجا','نينجه']],['thechefz','شيفز',['thechefz','chefz','شيفز','شيقز']],
 ['marsool','مرسول',['marsool','مرسول']],['toyou','تويو',['toyou','تويو']]];
function platInfoT(v){ const raw=String(v==null?'':v).trim(); if(!raw) return {code:'',ar:''};
 const low=raw.toLowerCase(); const ar=arNormT(raw);
 for(const p of PF_T) for(const a of p[2]){
  if(/^[a-z]+$/.test(a)){ if(low.indexOf(a)>=0) return {code:p[0],ar:p[1]}; }
  else { if(ar.indexOf(arNormT(a))>=0) return {code:p[0],ar:p[1]}; } }
 return {code:'',ar:''}; }
function normCustCode(v){ if(v===null||v===undefined) return '';
 let s=String(v).replace(/\s+/g,'').trim(); if(!s) return '';
 s=s.replace(/\.0+$/,''); if(!/^\d+$/.test(s)) return s; s=s.replace(/^0+(?=\d)/,''); return s; }
function classifyCustomer(code,name,p){
 if(code && Object.prototype.hasOwnProperty.call(WHITE_CODES,code))
  return {state:'accepted',via:'code',platform:WHITE_CODES[code][0]};
 if(p && p.code) return {state:'accepted',via:'name',platform:p.code};
 if(code && Object.prototype.hasOwnProperty.call(BLACK_CODES,code))
  return {state:'excluded',via:'code',why:BLACK_CODES[code]};
 const arn=arNormT(name||'');
 for(const bn of BLACK_NAMES){ const b=arNormT(bn); if(arn&&b&&arn.indexOf(b)>=0) return {state:'excluded',via:'name',why:bn}; }
 return {state:'unknown',via:'',why:''}; }
function CLS(code,name){ const r=classifyCustomer(normCustCode(code), name||'', platInfoT(name||''));
 return r.state + (r.platform?(':'+r.platform):(r.why?(':'+r.why):'')); }

check('رمز 3 = تويو ولا يطابق 31 ولا 342 ولا 355 ولا 379',
  CLS('3','')==='accepted:toyou' && CLS('31','')==='accepted:marsool' &&
  CLS('342','')==='accepted:keeta' && CLS('355','')==='accepted:ninja' &&
  CLS('379','مضارب نجدية')==='excluded:مضارب نجدية');
check('رمز 5 = هنجر ولا يطابق 52 ولا 355', CLS('5','')==='accepted:hunger' && CLS('52','')==='accepted:thechefz');
check('رمز 7 = سلة مستبعدة ولا يطابق 21 ولا 31 ولا 52',
  CLS('7','')==='excluded:سلة' && CLS('21','')==='accepted:jahez' && CLS('31','')==='accepted:marsool');
check('«03» و«3.0» و« 3 » و«0003.00» كلها تويو',
  ['03','3.0',' 3 ','0003.00'].every(c=>CLS(c,'')==='accepted:toyou'));
check('الخانة الفارغة ليست صفراً', normCustCode('')==='' && normCustCode('0')==='0');
check('لا احتواء: «35» و«3550» ليستا نينجا', CLS('35','')==='unknown' && CLS('3550','')==='unknown');
check('«شركة كيتا» تُقبل بالرمز 342 وحده مع اسم فارغ', CLS('342','')==='accepted:keeta');
check('اسم هنجر بالحروف الفارسية يُقبل بالاسم وحده بلا رمز',
  CLS('','شرکه هنجرستیشن المحدوده-Hunger Station')==='accepted:hunger');
check('بلا رمز واسم فيه مرسول ⇒ مقبولة', CLS('','مؤسسة مرسول للتوصيل')==='accepted:marsool');
check('«الموردين المحليين» بلا رمز ⇒ مستبعدة', CLS('','الموردين المحليين')==='excluded:الموردين المحليين');
check('رمز 19 امازون و7 سلة ⇒ مستبعدتان', CLS('19','Amazon')==='excluded:امازون' && CLS('7','سلة')==='excluded:سلة');
check('رمز 99 واسم غير معروف ⇒ مجهولة لا مستبعدة', CLS('99','مورد غير معروف')==='unknown');
check('الرمز يسبق الاسم عند التعارض', CLS('5','شركة كيتا')==='accepted:hunger');
// تقرير يوم كامل حقيقي§ 83 فاتورة و8 عملاء
const FIXTURE = [['شرکه هنجرستیشن المحدوده-Hunger Station','5',20,'accepted'],
 ['شركة نينجا - Ninja','355',7,'accepted'],['شركة كيتا','342',7,'accepted'],
 ['شركة جاهز -Jahez','21',6,'accepted'],['امازون ','19',22,'excluded'],
 ['الموردين المحليين','',18,'excluded'],['شركة تطبيق سلة لتقنية المعلومات','7',2,'excluded'],
 ['شركة مضارب نجدية التراثي شركة شخص واحد','379',1,'excluded']];
let acc=0, exc=0, unk=0, totalFx=0;
FIXTURE.forEach(function(c){ const st=CLS(c[1],c[0]).split(':')[0]; totalFx+=c[2];
 if(st!==c[3]) unk+=c[2]; else if(st==='accepted') acc+=c[2]; else exc+=c[2]; });
check('83 فاتورة ⇒ 40 مقبولة و43 مستبعدة و0 مجهولة',
  totalFx===83 && acc===40 && exc===43 && unk===0, {totalFx:totalFx,acc:acc,exc:exc,unk:unk});

console.log('\n30) مفتاح الفاتورة§ التطبيع والنسخة المطابقة والتعارض الحقيقي');
function normInvNo(v){ return String(v==null?'':v).trim().toLowerCase().replace(/\s+/g,''); }
check('صيغتان للرقم نفسه ⇒ مفتاح واحد', normInvNo('QWS-5-5468')===normInvNo(' qws-5-5468 '));
check('الأصفار البادئة لا تُحذف', normInvNo('0005-10178')==='0005-10178' && normInvNo('0005-10178')!==normInvNo('5-10178'));
const DIFF_FIELDS=[['المبلغ','amount'],['الفرع','branch'],['التاريخ','date']];
function diffOf(a,b){ const out=[]; DIFF_FIELDS.forEach(function(f){ const x=a[f[1]],y=b[f[1]];
 if(x===undefined||x===null||y===undefined||y===null) return;
 if(String(x)!==String(y)) out.push({field:f[0],values:[x,y]}); }); return out; }
check('نسخة مكررة مطابقة ليست تعارضاً',
  diffOf({amount:50,branch:'المصيف',date:'2026-09-07'},{amount:50,branch:'المصيف',date:'2026-09-07'}).length===0);
let dd = diffOf({amount:50,branch:'المصيف',date:'2026-09-07'},{amount:70,branch:'المصيف',date:'2026-09-07'});
check('اختلاف المبلغ ⇒ تعارض حقيقي بالقيمتين',
  dd.length===1 && dd[0].field==='المبلغ' && dd[0].values[0]===50 && dd[0].values[1]===70, dd);
check('اختلاف الفرع ⇒ تعارض حقيقي',
  diffOf({amount:50,branch:'المصيف'},{amount:50,branch:'الخليج'}).length===1);
check('حقل غائب عن أحد الطرفين لا يُعدّ اختلافاً',
  diffOf({amount:50},{amount:50,branch:'الخليج'}).length===0);

console.log('\n31) سطر نبض النظام§ المدى يتبع الترويسة، وغير المتاح «—»');
function pulseRow(header, raw){
 const DASH='—';
 const val=function(v){ const s=(v===null||v===undefined)?'':String(v); return s.trim()===''?DASH:s; };
 const colLetter=function(n){ let s=''; while(n>0){ const r=(n-1)%26; s=String.fromCharCode(65+r)+s; n=Math.floor((n-1)/26); } return s; };
 const row=[]; for(let i=0;i<header.length;i++) row.push(val(raw[i]));
 return { range:'نبض النظام!A1:'+colLetter(header.length)+'2', values:[header,row] };
}
const H5=['آخر تشغيل ناجح (الرياض)','معرّف التشغيل','عدد الصفوف','نوع التشغيل','تقرير بوابة سماك'];
let P = pulseRow(H5, ['2026-09-12 16:00:00','950',129,'production','مجهولة 0 | تعارضات 0']);
check('المدى يغطي كل أعمدة الترويسة', P.range==='نبض النظام!A1:E2', P.range);
check('طول الصف = طول الترويسة', P.values[1].length===H5.length);
check('لا خلية فارغة في نطاق الترويسة', P.values[1].every(x=>String(x).trim()!==''));
P = pulseRow(H5, ['2026-09-12 16:00:00', null, undefined, '', 'مجهولة 0 | تعارضات 0']);
check('قيمة غير متاحة تُكتب «—» لا فراغاً',
  P.values[1][1]==='—' && P.values[1][2]==='—' && P.values[1][3]==='—', P.values[1]);
const H7 = H5.concat(['عمود سادس','عمود سابع']);
P = pulseRow(H7, ['a','b','c','d','e']);
check('إضافة عمودين ⇒ المدى يتسع تلقائياً بلا تعديل يدوي', P.range==='نبض النظام!A1:G2', P.range);
check('العمودان الجديدان يُكتبان «—» فلا تبقى قيمة تشغيل أقدم',
  P.values[1].length===7 && P.values[1][5]==='—' && P.values[1][6]==='—', P.values[1]);


console.log('\n32) عدّاد المحاولات§ تعريف واحد في كل النظام (المصدر الواحد + تصنيف الأعطال + السقف)');
// نُسخت حرفياً من «ثوابت النظام» ومن العقد المستهلكة بعد التوحيد.
const SERVICE_FAULT_PATTERN = 'connection|econnreset|etimedout|socket hang up|socket|abort|network|offline|dns|502|503|504|429|bad gateway|gateway timeout|service unavailable|internalservererror|api_5xx|api_timeout|api_connection|credit balance|insufficient_quota|quota|rate_?limit|too many requests|overloaded|server_error';

function makeCounter(MAX_TRIES) {
  const SF = new RegExp(SERVICE_FAULT_PATTERN, 'i');
  function isServiceFault() {
    for (let i = 0; i < arguments.length; i++) { const s = String(arguments[i] || ''); if (s && SF.test(s)) return true; }
    return false;
  }
  function clampTries(n) { n = Number(n) || 0; if (n < 0) n = 0; if (n > MAX_TRIES) n = MAX_TRIES; return n; }
  // «فحص السجل»: يقرر الأساس وهل هذه محاولة تُحتسب — بلا أي زيادة هنا
  function ladder(e, opts) {
    const o = opts || {};
    if (o.dup) return { attempts_base: 0, count_attempt: false, skip: 'duplicate' };
    if (o.crash) return { attempts_base: (e && e.tries) || 0, count_attempt: false, skip: 'crash' };
    if (!e) return { attempts_base: 0, count_attempt: true };
    if (e.redo) return { attempts_base: 0, count_attempt: true };
    if (!o.parsed) return { attempts_base: (e.tries || 0), count_attempt: true };
    if (o.recheck) return { attempts_base: (e.tries || 1), count_attempt: false };
    return { attempts_base: (e.tries || 1), count_attempt: false };
  }
  // «Parse Video Result»: موضع الزيادة الوحيد — القرار قبل الزيادة، ثم السقف
  function finalAttempts(dec, outcome) {
    const o = outcome || {};
    if (dec.skip === 'duplicate') return 0;
    const fault = (dec.skip === 'crash') ? false : isServiceFault(o.error, o.error_kind, o.raw_response);
    return clampTries(Number(dec.attempts_base || 0) + ((dec.count_attempt && !fault) ? 1 : 0));
  }
  // «Filter Media Files» / «تحديد الملفات المقفلة»
  function isClosed(tries, redo) { return (Number(tries) || 0) >= MAX_TRIES && !redo; }
  // «Build Orders Table»
  function noInvoiceWhy(tries) {
    return ((Number(tries) || 0) >= MAX_TRIES) ? ('استُنفدت ' + MAX_TRIES + ' محاولات ولم تُوجد فاتورة سماك مقابلة') : null;
  }
  // «فحص ذاتي»
  function selfCheck(rows) {
    let bad = 0;
    rows.forEach(function (r) { const n = Number(r); if (!(n >= 0 && n <= MAX_TRIES)) bad++; });
    return bad ? (bad + ' صف بعدد محاولات خارج النطاق 0..' + MAX_TRIES) : '';
  }
  return { isServiceFault, clampTries, ladder, finalAttempts, isClosed, noInvoiceWhy, selfCheck, MAX_TRIES };
}

const C = makeCounter(3);

// (أ) عطل خدمة/رصيد/اتصال ⇒ العدّاد لا يتغير إطلاقاً (لا زيادة ثم خصم)
[['502 Bad Gateway', 'api_5xx'], ['ECONNRESET socket hang up', ''], ['Your credit balance is too low', ''],
 ['429 too many requests', ''], ['overloaded_error', ''], ['insufficient_quota', '']].forEach(function (p) {
  const dec = C.ladder({ tries: 1 }, { parsed: false });
  const got = C.finalAttempts(dec, { error: p[0], error_kind: p[1] });
  check('عطل خدمة «' + p[0].slice(0, 28) + '» ⇒ العدّاد يبقى 1', got === 1, got);
});
check('عطل خدمة على مسار النجاح (raw_response فيه rate limit) ⇒ ملف جديد يبقى 0',
  C.finalAttempts(C.ladder(null, { parsed: false }), { raw_response: '429 rate limit exceeded' }) === 0);

// (ب) خطأ حقيقي ⇒ +1 ولا يتجاوز MAX_TRIES في أي مسار
check('خطأ حقيقي ⇒ 2 تصير 3',
  C.finalAttempts(C.ladder({ tries: 2 }, { parsed: false }), { error: 'ValueError: could not parse frames' }) === 3);
check('ملف جديد بقراءة ناجحة ⇒ 1',
  C.finalAttempts(C.ladder(null, { parsed: false }), { raw_response: '' }) === 1);
check('مسار closed بسجل ناقص§ أساس 3 + خطأ حقيقي ⇒ 3 لا 4 (السقف عند موضع الزيادة)',
  C.finalAttempts(C.ladder({ tries: 3 }, { parsed: false }), { error: 'bad frames' }) === 3);
check('قيمة تالفة في السجل (9) لا تخرج من النطاق بعد المرور',
  C.finalAttempts(C.ladder({ tries: 9 }, { parsed: false }), { error: 'bad frames' }) === 3);
check('لا يُعتمد على الاستبعاد الأعلى§ الملف المقفل يُستبعد أصلاً', C.isClosed(3, false) === true);
check('علم «أعد المعالجة» يفتح المقفل ويُصفّر الأساس',
  C.isClosed(3, true) === false && C.ladder({ tries: 3, redo: true }, { parsed: false }).attempts_base === 0);

// (ج) العدّاد 0 ⇒ لا إنذار، و(د) النسخة المكررة عدّادها 0
check('العدّاد 0 لا يُنتج إنذاراً', C.selfCheck([0, 1, 2, 3]) === '');
check('العدّاد 4 يُنتج إنذاراً بالنطاق الصحيح', C.selfCheck([0, 4]) === '1 صف بعدد محاولات خارج النطاق 0..3');
const dupDec = C.ladder({ tries: 2 }, { dup: true });
check('نسخة مكررة ⇒ عدّادها 0', C.finalAttempts(dupDec, { error: '502' }) === 0 && dupDec.count_attempt === false);
check('نسخة مكررة ⇒ صفر إنذار', C.selfCheck([C.finalAttempts(dupDec, {})]) === '');

// (هـ) تغيير MAX_TRIES في المصدر الواحد ⇒ كل المواضع تتبعه
[2, 5].forEach(function (M) {
  const K = makeCounter(M);
  check('MAX=' + M + '§ السقف يتبع',
    K.finalAttempts(K.ladder({ tries: 99 }, { parsed: false }), { error: 'bad frames' }) === M);
  check('MAX=' + M + '§ الإقفال يتبع',
    K.isClosed(M, false) === true && K.isClosed(M - 1, false) === false);
  check('MAX=' + M + '§ نص «بلا فاتورة» يتبع',
    K.noInvoiceWhy(M) === ('استُنفدت ' + M + ' محاولات ولم تُوجد فاتورة سماك مقابلة') && K.noInvoiceWhy(M - 1) === null);
  check('MAX=' + M + '§ نطاق الفحص الذاتي يتبع',
    K.selfCheck([M]) === '' && K.selfCheck([M + 1]) === '1 صف بعدد محاولات خارج النطاق 0..' + M);
});
// حارس: أي موضع يُبقي الحد مكتوباً رقماً لن يتغير مع MAX — نكشفه بالمقارنة بين حدّين
const A = makeCounter(2), B = makeCounter(5);
check('كشف أي موضع لم يتبع المصدر الواحد',
  A.clampTries(9) !== B.clampTries(9) && A.isClosed(3, false) !== B.isClosed(3, false) &&
  A.selfCheck([3]) !== B.selfCheck([3]) && A.noInvoiceWhy(3) !== B.noInvoiceWhy(3));

// (و) نص النسخة المكررة يذكر أساس المطابقة والمعرّفين
function dupNote(basis, name, curId, origId) {
  return 'نسخة مكررة (تطابق ' + String(basis || 'غير محدد') + ') من «' + String(name || '') + '» — المعرّف الحالي ' +
    String(curId || '') + ' ؛ المعرّف الأصلي ' + (String(origId || '') || 'غير مسجّل');
}
const NT = dupNote('md5', 'TWIN.mp4', 'idA', 'idB');
check('النص يذكر أساس المطابقة', NT.indexOf('تطابق md5') > 0, NT);
check('النص يذكر المعرّفين ولا يكرر معرّفاً واحداً',
  NT.indexOf('idA') > 0 && NT.indexOf('idB') > 0 && NT.indexOf('idA') !== NT.indexOf('idB'), NT);
check('أساس «الاسم+الحجم» يظهر كما هو', dupNote('الاسم+الحجم', 'x.mp4', 'i1', 'i2').indexOf('تطابق الاسم+الحجم') > 0);
check('معرّف أصلي غير مسجّل يُكتب صراحةً', dupNote('وسم محفوظ من تشغيل سابق', 'x.mp4', 'i1', '').indexOf('غير مسجّل') > 0);

console.log('\n33) تبويب «اليوم» + «بصمات الصفوف»§ مرآة لا مصدر حقيقة');
// نُسخت حرفياً من عقدة «بناء اليوم والبصمات».
const TODAY_WIDTH = 17;
const normCell = function (v) { return String(v === null || v === undefined ? '' : v).replace(/\r/g, '').replace(/\s+/g, ' ').trim(); };
// البصمة تُقاس على القيمة المعنوية للخلية لا على تمثيلها (منشور b44f8e44)
const URL_RE33 = /https?:\/\/[^\s"'<>)]+/gi;
const idOfUrl = function (u) {
  const s = String(u).replace(/[)"'\\.,;]+$/, '');
  const m = s.match(/\/d\/([A-Za-z0-9_-]{10,})/) || s.match(/[?&]id=([A-Za-z0-9_-]{10,})/);
  if (m) return 'drive:' + m[1];
  return s.split('#')[0].split('?')[0].replace(/\/+$/, '').toLowerCase();
};
const semOf = function (v) {
  const s = normCell(v);
  if (s.charAt(0) !== '=') return s;
  const urls = s.match(URL_RE33) || [];
  const ids = [];
  urls.forEach(function (u) { const t = idOfUrl(u); if (t && ids.indexOf(t) < 0) ids.push(t); });
  if (ids.length) return 'f|' + ids.join('|');
  const lits = s.match(/"(?:[^"]|"")*"|-?\d+(?:\.\d+)?/g) || [];
  return 'f|' + lits.map(function (t) { return normCell(t).replace(/^"|"$/g, '').replace(/""/g, '"'); }).join('|');
};
const hashOf = function (cells) {
  const s = cells.join(String.fromCharCode(31));
  let h1 = 0x811c9dc5 >>> 0, h2 = 0x01000193 >>> 0;
  for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i);
    h1 = ((h1 ^ c) >>> 0); h1 = Math.imul(h1, 0x01000193) >>> 0;
    h2 = (h2 + Math.imul(c, 131)) >>> 0; h2 = ((h2 ^ (h2 << 7)) >>> 0); }
  return ('00000000' + h1.toString(16)).slice(-8) + ('00000000' + h2.toString(16)).slice(-8) + '-' + s.length;
};
const fpOf = function (r) { const c = []; for (let i = 0; i < TODAY_WIDTH; i++) c.push(semOf(r[i])); return 'v2:' + hashOf(c); };
const fpLegacyOf = function (r) { const c = []; for (let i = 0; i < TODAY_WIDTH; i++) c.push(normCell(r[i])); return hashOf(c); };
const RANK = [['🚨', 0], ['⚠️', 1], ['🔍', 2], ['🔵', 3], ['✅', 4]];
const rankOf = function (s) { const t = String(s || ''); for (let i = 0; i < RANK.length; i++) { if (t.indexOf(RANK[i][0]) === 0) return RANK[i][1]; } return 9; };
// دالة التطبيع الواحدة القائمة في «Build Orders Table» @199 — المفتاح يُبنى منها لا من نسخة ثانية
const normInvNo33 = function (v) { return String(v == null ? '' : v).trim().toLowerCase().replace(/\s+/g, ''); };
const fileIdOf33 = function (s) { const m = String(s || '').match(/[-\w]{25,}/); return m ? m[0] : ''; };
const keyOf = function (link, inv) { const f = fileIdOf33(link); return f ? ('FILE:' + f) : ('INV:' + normInvNo33(inv)); };

// مفاتيح ترتيب «اليوم» — منسوخة حرفياً من «بناء اليوم والبصمات» (منشور مع ترتيب الفروع)
const DEFAULT_BRANCH_ORDER = [
  { name: 'المصيف',    aliases: ['المصيف', 'Al Masiaf', 'Al Masyaf', 'Masiaf', 'Masyaf', '1'] },
  { name: 'الوشم',     aliases: ['الوشم', 'Al Wisham', 'Al Washm', 'Wisham', 'Washm', '2'] },
  { name: 'الخليج',    aliases: ['الخليج', 'Al Khaleej', 'Al Khalij', 'Khaleej', 'Khalij', '3'] },
  { name: 'الياسمين',  aliases: ['الياسمين', 'Al Yasmin', 'Al Yasameen', 'Yasmin', 'Yasameen', '4'] },
  { name: 'ظهرة لبن',  aliases: ['ظهرة لبن', 'ظهره لبن', 'Dhahrat Laban', 'Dhahret Laban', 'Laban', '5'] }
];
const normBranch = function (v) {
  let s = String(v == null ? '' : v).toLowerCase();
  s = s.replace(/[\u064B-\u0652\u0640]/g, '');
  s = s.replace(/[\u0623\u0625\u0622\u0671]/g, '\u0627').replace(/\u0649/g, '\u064A').replace(/\u0624/g, '\u0648').replace(/\u0626/g, '\u064A').replace(/\u0629/g, '\u0647');
  s = s.replace(/[^0-9a-z\u0621-\u064A]/g, '');
  s = s.replace(/^\u0627\u0644/, '').replace(/^al/, '');
  return s;
};
const branchIndex = function (order) {
  const names = [], map = {};
  (order || []).forEach(function (b, i) {
    const nm = (b && b.name) || String(b || ''); names.push(nm);
    (((b && b.aliases) || []).concat([nm])).forEach(function (a) { const k = normBranch(a); if (k && map[k] === undefined) map[k] = i; });
  });
  return { names: names, map: map, unknown: names.length };
};
const branchRawOf = function (r) { const s = String(r[7] == null ? '' : r[7]).trim(); return s || String(r[6] == null ? '' : r[6]).trim(); };
const dateKeyOf = function (v) {
  const s = String(v == null ? '' : v).trim(); if (!s) return 0;
  let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  m = s.match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})$/);
  if (m) return Date.UTC(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
  if (/^\d{5}$/.test(s)) return Date.UTC(1899, 11, 30) + Number(s) * 86400000;
  const t = Date.parse(s); return isNaN(t) ? 0 : t;
};
const invKeyOf = function (v) { const s = String(v == null ? '' : v).trim().toLowerCase(); return s || '\uFFFF'; };

function buildToday(prevPrints, rows, keys, now, prevTodayRows, header, order) {
  const TS = now, TODAY = String(now).slice(0, 10);
  const BI = branchIndex(order || DEFAULT_BRANCH_ORDER);
  const unkBranch = {}; let noBranchRows = 0;
  const prevMap = {};
  prevPrints.slice(1).forEach(function (r) { const k = normCell(r && r[0]); if (!k) return; prevMap[k] = { fp: String(r[1] || ''), at: String(r[2] || '') }; });
  const seen = {}, outPrints = [], todayRows = [];
  let nNew = 0, nChanged = 0, nSame = 0, dup = 0;
  rows.forEach(function (r, i) {
    const k = normCell(keys[i]); if (!k) return;
    if (seen[k]) { dup++; return; }
    seen[k] = 1;
    const fp = fpOf(r), fpLegacy = fpLegacyOf(r), old = prevMap[k];
    const isNew = !old;
    const oldFp = old ? String(old.fp || '') : '';
    const legacyStored = !!old && oldFp.indexOf('v2:') !== 0;
    const changed = isNew || (legacyStored ? (oldFp !== fpLegacy) : (oldFp !== fp));
    if (isNew) nNew++; else if (changed) nChanged++; else nSame++;
    const at = changed ? TS : (old.at || TS);
    outPrints.push([k, fp, at]);
    // «اليوم» سجل تغييرات لا مرآة: يدخله الصف الجديد أو المتغيّر وحده
    const brRaw = branchRawOf(r);
    const bk = normBranch(brRaw);
    const brIdx = (bk && BI.map[bk] !== undefined) ? BI.map[bk] : BI.unknown;
    if (brIdx === BI.unknown) { if (brRaw) unkBranch[brRaw] = (unkBranch[brRaw] || 0) + 1; else noBranchRows++; }
    if (changed) todayRows.push({ r: r, at: at, st: String(r[0] || ''), br: brIdx, dt: dateKeyOf(r[3]), inv: invKeyOf(r[2]) });
  });
  let kept = 0;
  Object.keys(prevMap).forEach(function (k) { if (seen[k]) return; kept++; outPrints.push([k, prevMap[k].fp, prevMap[k].at]); });
  // الفرع بترتيب الثوابت ⇒ التاريخ الأحدث أولاً ⇒ الحالة الأسوأ أولاً ⇒ رقم فاتورة سماك تصاعدياً
  todayRows.sort(function (a, b) {
    return (a.br - b.br) || (b.dt - a.dt) || (rankOf(a.st) - rankOf(b.st)) || (a.inv < b.inv ? -1 : (a.inv > b.inv ? 1 : 0));
  });
  const todayValues = [header];
  if (todayRows.length) todayRows.forEach(function (x) { const rr = x.r.slice(); while (rr.length < TODAY_WIDTH) rr.push(''); todayValues.push(rr.slice(0, TODAY_WIDTH)); });
  else { const b = new Array(TODAY_WIDTH).fill(''); b[0] = 'لا تغييرات اليوم'; b[14] = 'آخر تحديث: ' + TS + ' (الرياض)'; todayValues.push(b); }
  while (todayValues.length < prevTodayRows) todayValues.push(new Array(TODAY_WIDTH).fill(''));
  const expectedToday = nNew + nChanged, actualToday = todayRows.length, guardOk = actualToday === expectedToday;
  const printValues = [['مفتاح الصف', 'البصمة', 'آخر تغيّر (الرياض)']].concat(outPrints);
  return { writeToday: guardOk, writePrints: guardOk,
    todayValues: guardOk ? todayValues : [], printValues: guardOk ? printValues : [],
    stats: { newKeys: nNew, changedKeys: nChanged, unchanged: nSame, todayCount: actualToday,
      expectedToday: expectedToday, guardOk: guardOk, keptAbsent: kept, duplicateKeys: dup,
      branchOrder: BI.names, unknownBranches: unkBranch, noBranchRows: noBranchRows } };
}

const H17 = ['الحالة', 'رابط الفيديو', 'رقم فاتورة سماك', 'التاريخ', 'المنصة (من الفيديو)', 'المنصة (من سماك)',
  'الفرع (من الفيديو)', 'الفرع (من سماك)', 'المنتجات (من الفيديو)', 'المنتجات (من سماك)', 'المحضَّر فعلياً',
  'الإجمالي (من الفيديو)', 'الإجمالي (من سماك)', 'طريقة الدفع', 'السبب', 'نتيجة الفحص الذاتي', 'مصدر التاريخ'];
const mkRow = function (st, link, inv, extra) { const r = new Array(17).fill(''); r[0] = st; r[1] = link; r[2] = inv; r[14] = extra || ''; return r; };
const LINK = 'https://drive.google.com/file/d/1vorb6Qy2UNE63hJS_3sO8SDnLe4n57GV/view';

check('المفتاح من معرّف الملف حين يوجد فيديو', keyOf(LINK, 'qwd-5-1') === 'FILE:1vorb6Qy2UNE63hJS_3sO8SDnLe4n57GV');
check('المفتاح INV§ برقم مطبَّع حين لا فيديو', keyOf('', '  QWF-5-1101 ') === 'INV:qwf-5-1101');
check('المفتاح لا يتغيّر بتغيّر باقي الخلايا',
  keyOf(LINK, 'a') === keyOf(LINK, 'b'));
check('الأصفار البادئة تبقى في المفتاح', keyOf('', '0005-12') === 'INV:0005-12');

const R1 = mkRow('✅ مطابق', LINK, 'qwd-5-1');
check('البصمة ثابتة لنفس القيم', fpOf(R1) === fpOf(R1.slice()));
check('البصمة تتغيّر بتغيّر أي خلية', fpOf(R1) !== fpOf(mkRow('⚠️ فيه فرق', LINK, 'qwd-5-1')));
check('فروق المسافات وحدها لا تغيّر البصمة',
  fpOf(mkRow('✅ مطابق', LINK, 'qwd-5-1', 'سبب  ما')) === fpOf(mkRow('✅ مطابق', LINK, 'qwd-5-1', ' سبب ما ')));

const rows = [mkRow('🚨 طلب بلا فاتورة سماك', 'https://x/d/AAAAAAAAAAAAAAAAAAAAAAAAAAA/v', ''),
              mkRow('⚠️ فيه فرق', 'https://x/d/BBBBBBBBBBBBBBBBBBBBBBBBBBB/v', ''),
              mkRow('🔍 يحتاج مراجعتي', '', 'inv-1'),
              mkRow('🔵 قراءة ضعيفة', 'https://x/d/CCCCCCCCCCCCCCCCCCCCCCCCCCC/v', ''),
              mkRow('✅ مطابق', 'https://x/d/DDDDDDDDDDDDDDDDDDDDDDDDDDD/v', '')];
const keys = rows.map(function (r) { return keyOf(r[1], r[2]); });
const NOW = '2026-09-12 20:00:00', YEST = '2026-09-11 22:10:00';

let S = buildToday([['مفتاح الصف', 'البصمة', 'آخر تغيّر (الرياض)']], rows, keys, NOW, 0, H17);
check('أول تشغيل§ كل الصفوف جديدة وتدخل «اليوم»', S.stats.newKeys === 5 && S.stats.todayCount === 5);
check('ترويسة «اليوم» مطابقة لترويسة «الطلبات» حرفياً', JSON.stringify(S.todayValues[0]) === JSON.stringify(H17));
check('الترتيب 🚨 ثم ⚠️ ثم 🔍 ثم 🔵 ثم ✅',
  S.todayValues.slice(1).map(function (r) { return rankOf(r[0]); }).join(',') === '0,1,2,3,4');

const prevSame = [['مفتاح الصف', 'البصمة', 'آخر تغيّر (الرياض)']].concat(keys.map(function (k, i) { return [k, fpOf(rows[i]), YEST]; }));
S = buildToday(prevSame, rows, keys, NOW, 6, H17);
check('لا تغيّر ⇒ صفر صف يدخل «اليوم» (لا تدخل كل الصفوف كل ساعة)',
  S.stats.newKeys === 0 && S.stats.changedKeys === 0 && S.stats.unchanged === 5 && S.stats.todayCount === 0);
check('الفراغ يُكتب سطراً لا يُحذف', S.todayValues[1][0] === 'لا تغييرات اليوم' && String(S.todayValues[1][14]).indexOf('آخر تحديث') === 0);
check('المسح§ يُملأ ما زاد من صفوف الجولة السابقة', S.todayValues.length === 6);
check('البصمات لا تتغيّر حين لا تغيّر',
  JSON.stringify(S.printValues.slice(1).map(function (r) { return r[2]; })) === JSON.stringify([YEST, YEST, YEST, YEST, YEST]));

const rows2 = rows.slice(); rows2[1] = mkRow('⚠️ فيه فرق', 'https://x/d/BBBBBBBBBBBBBBBBBBBBBBBBBBB/v', '', 'سبب جديد');
S = buildToday(prevSame, rows2, keys, NOW, 6, H17);
check('تغيّر صف واحد ⇒ يدخل وحده', S.stats.changedKeys === 1 && S.stats.todayCount === 1 && rankOf(S.todayValues[1][0]) === 1);
check('وقت التغيّر يُحدَّث للمتغيّر وحده',
  S.printValues[2][2] === NOW && S.printValues[1][2] === YEST);

const prevGhost = prevSame.concat([['FILE:GHOSTGHOSTGHOSTGHOSTGHOSTG', 'deadbeefdeadbeef-9', '2026-09-05 10:00:00']]);
S = buildToday(prevGhost, rows, keys, NOW, 6, H17);
check('مفتاح غاب عن «الطلبات»§ تُحفظ بصمته كما هي', S.stats.keptAbsent === 1 && S.printValues.length === 7);
check('ولا يدخل «اليوم»', S.stats.todayCount === 0);
check('بصمته ووقتها لم يُمسّا',
  S.printValues[6][1] === 'deadbeefdeadbeef-9' && S.printValues[6][2] === '2026-09-05 10:00:00');

// القاعدة الجديدة (b44f8e44): «اليوم» سجل تغييرات لا مرآة — الوقت لم يعد يُدخل صفاً
const prevToday = [['مفتاح الصف', 'البصمة', 'آخر تغيّر (الرياض)']].concat(keys.map(function (k, i) { return [k, fpOf(rows[i]), '2026-09-12 09:00:00']; }));
S = buildToday(prevToday, rows, keys, NOW, 6, H17);
check('صف تغيّر في تشغيل سابق ولم يتغيّر الآن لا يدخل «اليوم»', S.stats.changedKeys === 0 && S.stats.todayCount === 0);
S = buildToday(prevSame, rows, keys, '2026-09-13 00:10:00', 6, H17);
check('لا شيء يتغيّر ⇒ «اليوم» فارغ بسطره', S.stats.todayCount === 0 && S.todayValues[1][0] === 'لا تغييرات اليوم');

const dupKeys = keys.slice(); dupKeys[4] = dupKeys[0];
S = buildToday(prevSame, rows, dupKeys, NOW, 6, H17);
check('مفتاح مكرر يُعدّ ولا يُكتب مرتين', S.stats.duplicateKeys === 1 && S.printValues.length === 5 + 1 - 1 + 1);

// صف التفريغ يغطي كل أعمدة الترويسة دائماً — لا عمود يبقى بقيمة تشغيل أقدم
function padBody(body, prevRows, header) {
  const b = body.map(function (r) { return r.slice(); });
  while (b.length < prevRows) b.push(new Array(header.length).fill(''));
  return b;
}
const OLD = ['قيمة قديمة', 'x', 'y'];
let PB = padBody([H17, ['✅ مطابق'].concat(new Array(16).fill(''))], 5, H17);
check('صف التفريغ بطول الترويسة كاملاً', PB.slice(2).every(function (r) { return r.length === H17.length; }), PB[2] && PB[2].length);
check('صف التفريغ لا يحمل أي قيمة', PB.slice(2).every(function (r) { return r.every(function (c) { return c === ''; }); }));
check('العمود الأخير (Q) يُمسح في صف التفريغ',
  PB.slice(2).every(function (r) { return r[H17.length - 1] === '' && r.length > 16; }));
const H18 = H17.concat(['عمود ثامن عشر']);
PB = padBody([H18], 3, H18);
check('إضافة عمود ثامن عشر§ التفريغ يتبع بلا تعديل يدوي',
  PB.slice(1).every(function (r) { return r.length === 18 && r[17] === ''; }), PB[1] && PB[1].length);
check('لا خلية في نطاق الترويسة تحمل قيمة من تشغيل أقدم',
  padBody([H17], 2, H17)[1].filter(function (c, i) { return c === OLD[i]; }).length === 0);

console.log('\n34) البصمة على المعنى + «اليوم» سجل تغييرات + حارس العدد (منشور b44f8e44)');
const hlink = function (id, sep, label) {
  return '=HYPERLINK("https://drive.google.com/file/d/' + id + '/view"' + sep + '"' + (label || 'WhatsApp Video.mp4') + '")';
};
const rowL = function (id, sep, inv, st, why) {
  const r = new Array(17).fill(''); r[0] = st || '✅ مطابق'; r[1] = hlink(id, sep); r[2] = inv; r[14] = why || ''; return r;
};
const ID1 = '1z-6BRcBl5ZouvwRW73GbSwv3j_0vA_1Q';
const PH34 = ['مفتاح الصف', 'البصمة', 'آخر تغيّر (الرياض)'];

// (أ) الفاصل داخل صيغة الرابط تمثيل لا معنى
check('فاصلة أو فاصلة منقوطة داخل HYPERLINK ⇒ بصمة واحدة',
  fpOf(rowL(ID1, ';', 'qwf-5-1130')) === fpOf(rowL(ID1, ',', 'qwf-5-1130')));
check('اسم الملف المعروض لا يدخل البصمة',
  fpOf(rowL(ID1, ';', 'qwf-5-1130')) === fpOf((function () { const r = rowL(ID1, ';', 'qwf-5-1130'); r[1] = hlink(ID1, ';', 'اسم آخر تماماً.mp4'); return r; })()));
check('تغيّر معرّف Drive ⇒ بصمة مختلفة',
  fpOf(rowL(ID1, ';', 'qwf-5-1130')) !== fpOf(rowL('1BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB', ';', 'qwf-5-1130')));
check('تغيّر عمود عادي ⇒ بصمة مختلفة',
  fpOf(rowL(ID1, ';', 'qwf-5-1130')) !== fpOf(rowL(ID1, ';', 'qwf-5-1130', 'سبب جديد')));

// (ب) 171 بلا تغيير و4 متغيّرة ⇒ «اليوم» 4 لا 175
const mk34 = function (n, sep) { const a = []; for (let i = 0; i < n; i++) a.push(rowL('1FILE' + String(i) + 'xxxxxxxxxxxxxxxxxxxxxxxxxxx', sep, 'inv-' + i)); return a; };
const K34 = []; for (let i = 0; i < 175; i++) K34.push('FILE:k' + i);
const before34 = mk34(175, ';');
const seed34 = buildToday([PH34], before34, K34, '2026-09-12 21:04:11', 0, H17);
check('البذرة ⇒ 175 جديدة و«اليوم» 175', seed34.stats.newKeys === 175 && seed34.stats.todayCount === 175);
const after34 = before34.map(function (r) { return r.slice(); });
after34[0][1] = hlink('1FILE0xxxxxxxxxxxxxxxxxxxxxxxxxxx', ',');
after34[1][1] = hlink('1FILE1xxxxxxxxxxxxxxxxxxxxxxxxxxx', ',');
[10, 11, 12, 13].forEach(function (i) { after34[i][14] = 'سبب جديد ' + i; });
const S34 = buildToday(seed34.printValues, after34, K34, '2026-09-12 22:01:45', 176, H17);
check('تمثيل مختلف لا يُحسب تغيّراً، و4 حقيقية فقط',
  S34.stats.changedKeys === 4 && S34.stats.newKeys === 0 && S34.stats.unchanged === 171, S34.stats);
check('«اليوم» 4 صفوف لا 175', S34.stats.todayCount === 4);
check('المكتوب يساوي changed + new', S34.stats.todayCount === S34.stats.changedKeys + S34.stats.newKeys && S34.stats.guardOk === true);
check('بقية الصفوف تُمسح بالحشو', S34.todayValues.length === 176);

// (ج) كل الصفوف بلا تغيير ⇒ «اليوم» فارغ بسطره
const S34b = buildToday(S34.printValues, after34, K34, '2026-09-12 23:00:05', 176, H17);
check('لا تغييرات ⇒ صفر، وسطر «لا تغييرات اليوم»',
  S34b.stats.todayCount === 0 && S34b.stats.guardOk === true && S34b.todayValues[1][0] === 'لا تغييرات اليوم');

// (د) الحارس: نسخة تختار بمنطق الوقت القديم ⇒ يمنع الكتابة
function buildTodayBuggy(prevPrints, rows, keys, now, prevTodayRows, header) {
  const S = buildToday(prevPrints, rows, keys, now, prevTodayRows, header);
  const TODAY = String(now).slice(0, 10);
  let picked = 0;
  S.printValues.slice(1).forEach(function (r) { if (String(r[2]).slice(0, 10) === TODAY) picked++; });
  const guardOk = picked === S.stats.newKeys + S.stats.changedKeys;
  return { writeToday: guardOk, writePrints: guardOk, todayValues: guardOk ? S.todayValues : [], printValues: guardOk ? S.printValues : [],
    stats: { newKeys: S.stats.newKeys, changedKeys: S.stats.changedKeys, todayCount: picked, expectedToday: S.stats.newKeys + S.stats.changedKeys, guardOk: guardOk } };
}
const BUG = buildTodayBuggy(seed34.printValues, after34, K34, '2026-09-12 22:01:45', 176, H17);
check('النسخة المعيبة تختار 175 والمتوقع 4', BUG.stats.todayCount === 175 && BUG.stats.expectedToday === 4, BUG.stats);
check('الحارس يمنع كتابة «اليوم» والبصمات معاً', BUG.guardOk !== true && BUG.writeToday === false && BUG.writePrints === false);
check('ولا تُرسَل أي قيم للكتابة', BUG.todayValues.length === 0 && BUG.printValues.length === 0);

// (هـ) ترقية البصمة المخزَّنة v1 ⇒ v2 بلا اعتبارها تغييراً
const RM = rowL('1MIGRATExxxxxxxxxxxxxxxxxxxxxxxx', ',', 'qwf-5-1135');
const prevLegacy = [PH34, ['K1', fpLegacyOf(RM), '2026-09-12 22:01:45']];
const MIG = buildToday(prevLegacy, [RM], ['K1'], '2026-09-12 23:00:05', 2, H17);
check('بصمة قديمة مطابقة ⇒ unchanged لا changed', MIG.stats.unchanged === 1 && MIG.stats.changedKeys === 0, MIG.stats);
check('ولا تدخل «اليوم»', MIG.stats.todayCount === 0);
check('وتُخزَّن بالصيغة الجديدة v2', String(MIG.printValues[1][1]).indexOf('v2:') === 0);
check('ووقت آخر تغيّر يبقى كما هو', MIG.printValues[1][2] === '2026-09-12 22:01:45');

console.log('\n35) ترتيب «اليوم»: الفرع ⇒ التاريخ ⇒ الحالة ⇒ رقم الفاتورة');
const rowB = function (st, sBr, vBr, date, inv) { const r = new Array(17).fill(''); r[0] = st; r[2] = inv || ''; r[3] = date || ''; r[6] = vBr || ''; r[7] = sBr || ''; return r; };
const seed35 = function (rows, order) {
  const ks = rows.map(function (_, i) { return 'K' + i; });
  return buildToday([['مفتاح الصف', 'البصمة', 'آخر تغيّر (الرياض)']], rows, ks, '2026-09-13 01:00:00', 0, H17, order);
};
const bodyOf = function (S) { return S.todayValues.slice(1).filter(function (r) { return String(r[0]) !== 'لا تغييرات اليوم'; }); };
const brLabel = function (r) { return String(r[7] || '').trim() || String(r[6] || '').trim() || '(بلا فرع)'; };
const contiguous35 = function (seq) { const seen = []; let last = null; for (let i = 0; i < seq.length; i++) { const v = seq[i]; if (v !== last) { if (seen.indexOf(v) >= 0) return false; seen.push(v); last = v; } } return true; };

let S35 = seed35([
  rowB('✅ مطابق', 'Dhahrat Laban', '', '2026-09-11', 'i1'),
  rowB('✅ مطابق', 'Al Yasmin', '', '2026-09-11', 'i2'),
  rowB('✅ مطابق', 'Al Masiaf', '', '2026-09-11', 'i3'),
  rowB('✅ مطابق', 'Al Khaleej', '', '2026-09-11', 'i4'),
  rowB('✅ مطابق', 'Al Wisham', '', '2026-09-11', 'i5'),
  rowB('✅ مطابق', 'Al Yasmin', '', '2026-09-10', 'i6'),
  rowB('✅ مطابق', 'Al Masiaf', '', '2026-09-10', 'i7')]);
check('الفروع بالترتيب المعلَن',
  bodyOf(S35).map(brLabel).join(',') === 'Al Masiaf,Al Masiaf,Al Wisham,Al Khaleej,Al Yasmin,Al Yasmin,Dhahrat Laban', bodyOf(S35).map(brLabel));
check('صفوف كل فرع متجاورة', contiguous35(bodyOf(S35).map(brLabel)));

S35 = seed35([
  rowB('✅ مطابق', 'Al Khaleej', '', '2026-09-09', 'a'),
  rowB('🔍 يحتاج مراجعتي', 'Al Khaleej', '', '2026-09-11', 'b'),
  rowB('✅ مطابق', 'Al Khaleej', '', '2026-09-10', 'c'),
  rowB('⚠️ فيه فرق', 'Al Khaleej', '', '2026-09-11', 'd'),
  rowB('✅ مطابق', 'Al Khaleej', '', '', 'e')]);
check('التواريخ تنازلياً والفارغ آخر مجموعات فرعه',
  bodyOf(S35).map(function (r) { return String(r[3] || '(فارغ)'); }).join(',') === '2026-09-11,2026-09-11,2026-09-10,2026-09-09,(فارغ)');
check('كل تاريخ متجاور', contiguous35(bodyOf(S35).map(function (r) { return String(r[3]); })));
check('التاريخ يُقارن كتاريخ لا كنص',
  bodyOf(seed35([rowB('✅ مطابق', 'Al Khaleej', '', '2026-9-9', 'x'), rowB('✅ مطابق', 'Al Khaleej', '', '2026-09-10', 'y')])).map(function (r) { return r[2]; }).join(',') === 'y,x');

S35 = seed35([
  rowB('✅ مطابق', 'Al Wisham', '', '2026-09-11', 'a'),
  rowB('🔵 قراءة ضعيفة', 'Al Wisham', '', '2026-09-11', 'b'),
  rowB('🚨 طلب بلا فاتورة سماك', 'Al Wisham', '', '2026-09-11', 'c'),
  rowB('🔍 يحتاج مراجعتي', 'Al Wisham', '', '2026-09-11', 'd'),
  rowB('⚠️ فيه فرق', 'Al Wisham', '', '2026-09-11', 'e')]);
check('داخل (فرع + تاريخ): 🚨 ⚠️ 🔍 🔵 ✅',
  bodyOf(S35).map(function (r) { return rankOf(r[0]); }).join(',') === '0,1,2,3,4');

S35 = seed35([
  rowB('✅ مطابق', 'Al Yasmin', '', '2026-09-11', 'qwf-5-1135'),
  rowB('✅ مطابق', 'Al Yasmin', '', '2026-09-11', 'qwf-5-1130'),
  rowB('✅ مطابق', 'Al Yasmin', '', '2026-09-11', 'qwd-5-1300'),
  rowB('✅ مطابق', 'Al Yasmin', '', '2026-09-11', '')]);
check('تساوي الثلاثة ⇒ رقم الفاتورة تصاعدياً والفارغ آخراً',
  bodyOf(S35).map(function (r) { return String(r[2] || '(فارغ)'); }).join(',') === 'qwd-5-1300,qwf-5-1130,qwf-5-1135,(فارغ)');

S35 = seed35([
  rowB('✅ مطابق', 'AL  YASMIN', '', '2026-09-11', 'a'),
  rowB('✅ مطابق', 'الياسمين', '', '2026-09-11', 'b'),
  rowB('✅ مطابق', 'Al-Yasmin', '', '2026-09-11', 'c'),
  rowB('✅ مطابق', 'ياسمين', '', '2026-09-11', 'd'),
  rowB('✅ مطابق', 'Al Khaleej', '', '2026-09-11', 'e'),
  rowB('✅ مطابق', 'الخليج ', '', '2026-09-11', 'f')]);
check('صيغ الكتابة المختلفة تُجمع في فرع واحد', bodyOf(S35).map(function (r) { return r[2]; }).join(',') === 'e,f,a,b,c,d');
check('ولا تُحسب فرعاً مجهولاً', Object.keys(S35.stats.unknownBranches).length === 0, S35.stats.unknownBranches);
check('فرع سماك هو المعتمد وإلا الفيديو',
  bodyOf(seed35([rowB('✅ مطابق', '', 'Al Masiaf', '2026-09-11', 'a'), rowB('✅ مطابق', 'Al Khaleej', 'Al Masiaf', '2026-09-11', 'b')])).map(function (r) { return r[2]; }).join(',') === 'a,b');

S35 = seed35([
  rowB('🚨 طلب بلا فاتورة سماك', 'Mugo Land', '', '2026-09-12', 'z1'),
  rowB('✅ مطابق', '', '', '2026-09-12', 'z2'),
  rowB('✅ مطابق', 'Al Masiaf', '', '2026-09-01', 'a'),
  rowB('✅ مطابق', 'ظهرة لبن', '', '2026-09-01', 'b'),
  rowB('🔵 قراءة ضعيفة', 'فرع جديد', '', '2026-09-12', 'z3')]);
check('المجهول والفارغ بعد الفروع المعلَنة كلها', bodyOf(S35).map(function (r) { return r[2]; }).slice(0, 2).join(',') === 'a,b');
check('ولا يُسقط أي صف', bodyOf(S35).length === 5);
check('الأسماء المجهولة تُسرد حرفياً', S35.stats.unknownBranches['Mugo Land'] === 1 && S35.stats.unknownBranches['فرع جديد'] === 1, S35.stats.unknownBranches);
check('والفارغ يُعدّ بلا اسم', S35.stats.noBranchRows === 1);

const ROWS6 = [rowB('✅ مطابق', 'Al Narjis', '', '2026-09-11', 'n'), rowB('✅ مطابق', 'Dhahrat Laban', '', '2026-09-11', 'l'), rowB('✅ مطابق', 'Al Masiaf', '', '2026-09-11', 'm')];
const SIXTH = { name: 'النرجس', aliases: ['النرجس', 'Al Narjis', 'Narjis', '6'] };
const B6 = seed35(ROWS6);
check('قبل إعلانه: النرجس مجهول وآخر الجدول',
  bodyOf(B6).map(function (r) { return r[2]; }).join(',') === 'm,l,n' && B6.stats.unknownBranches['Al Narjis'] === 1);
const A6 = seed35(ROWS6, DEFAULT_BRANCH_ORDER.concat([SIXTH]));
check('بعد إعلانه في الثوابت: يأخذ موضعه بلا تعديل منطق الفرز',
  bodyOf(A6).map(function (r) { return r[2]; }).join(',') === 'm,l,n' && Object.keys(A6.stats.unknownBranches).length === 0);
const A6b = seed35(ROWS6, [SIXTH].concat(DEFAULT_BRANCH_ORDER));
check('ولو وُضع أولاً في الثوابت تبعه الترتيب', bodyOf(A6b).map(function (r) { return r[2]; }).join(',') === 'n,m,l');
check('أسماء الفروع في الإحصاء تأتي من الثوابت',
  JSON.stringify(A6.stats.branchOrder) === JSON.stringify(['المصيف', 'الوشم', 'الخليج', 'الياسمين', 'ظهرة لبن', 'النرجس']));

console.log('\n' + '='.repeat(60));
if (failed) { console.log('سقطت ' + failed + ' حالة'); process.exit(1); }
console.log('كل الاختبارات نجحت ✅');
