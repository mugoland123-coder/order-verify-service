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
  const probs = [], unsure = [];
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
        unsure.push(k + ': الفاتورة ' + b.w + 'جم = ' + Math.round(mult) + ' عبوة من ' + unit + 'جم ولم يظهر منها إلا ' + p.n);
      } else {
        probs.push(k + ': وزن المحضَّر ' + p.w + 'جم مقابل ' + b.w + 'جم بالفاتورة');
      }
    }
  });
  Object.keys(pm).forEach(function (k) { if (!bm[k]) probs.push(k + ' (' + (pm[k].name || '') + ') محضَّر وغير مفوتر'); });
  if (noCode.length) unsure.push(noCode.length + ' عبوة بلا كود على الملصق');
  if (probs.length) return { st: 'mismatch', why: probs.join(' ؛ ') };
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
const PREP_1315 = [{ r_code: 'R373', item_name: 'صابون غار الأصلي', seen_count: 1, weight_g: 4000 }];
const BILLED_1315 = [{ r_code: 'R373', item_name: 'صابون الغار الاصلي   R373', quantity: 4, weight_g: null }];

console.log('\n20) qwd-5-1318 — علبتا R75 (250جم × 2 = 500جم) لا تُعدّ نقصاً في التحضير');
let jp = judgePrep(PREP_1318, BILLED_1318, 'full');
check('لا تُتّهم حالة التحضير بمخالفة', jp.st !== 'mismatch', jp);
check('ولا يظهر «وزن المحضَّر 250جم مقابل 500جم بالفاتورة»',
  !/وزن المحضَّر 250جم مقابل 500جم/.test(jp.why), jp.why);
check('بل ملاحظة صريحة أن الفاتورة علبتان ولم تظهر إلا واحدة',
  /R75: الفاتورة 500جم = 2 عبوة من 250جم ولم يظهر منها إلا 1/.test(jp.why), jp.why);
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
check('750جم = ثلاث علب 250جم ⇒ ملاحظة لا مخالفة',
  judgePrep([{ r_code: 'R9', seen_count: 1, weight_g: 250 }],
            [{ r_code: 'R9', quantity: 0.75, weight_g: 750 }], 'full').st === 'not_verifiable');

console.log('\n' + '='.repeat(60));
if (failed) { console.log('سقطت ' + failed + ' حالة'); process.exit(1); }
console.log('كل الاختبارات نجحت ✅');
