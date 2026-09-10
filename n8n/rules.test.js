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

console.log('\n' + '='.repeat(60));
if (failed) { console.log('سقطت ' + failed + ' حالة'); process.exit(1); }
console.log('كل الاختبارات نجحت ✅');
