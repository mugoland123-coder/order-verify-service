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

console.log('\n' + '='.repeat(60));
if (failed) { console.log('سقطت ' + failed + ' حالة'); process.exit(1); }
console.log('كل الاختبارات نجحت ✅');
