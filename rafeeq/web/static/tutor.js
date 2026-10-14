/* The tutor agent's small enhancements: answer the 3 MCQ in the page, flip flashcards. No server calls. */
(function () {
  'use strict';

  document.addEventListener('click', function (event) {
    var opt = event.target.closest('.tq-opt');
    if (opt) {
      var q = opt.closest('.tq-q');
      if (!q || q.dataset.done) return;
      q.dataset.done = '1';
      var right = parseInt(q.dataset.answer, 10);
      var picked = parseInt(opt.dataset.i, 10);
      var quiz = q.closest('.tq-quiz');
      var buttons = q.querySelectorAll('.tq-opt');
      buttons.forEach(function (b) { b.disabled = true; });
      if (buttons[right]) buttons[right].classList.add('tq-right');
      var fb = q.querySelector('.tq-fb');
      if (picked === right) {
        q.dataset.score = '1';
        fb.className = 'tq-fb tq-right';
        fb.textContent = quiz.dataset.msgOk + (q.dataset.why ? ' ' + q.dataset.why : '');
      } else {
        opt.classList.add('tq-wrong');
        fb.className = 'tq-fb tq-wrong';
        fb.textContent = quiz.dataset.msgBad + ' ' + (buttons[right] ? buttons[right].textContent : '') + (q.dataset.why ? '. ' + q.dataset.why : '');
      }
      var all = quiz.querySelectorAll('.tq-q');
      var done = quiz.querySelectorAll('.tq-q[data-done]');
      if (done.length === all.length) {
        var n = quiz.querySelectorAll('.tq-q[data-score]').length;
        quiz.querySelector('.tq-score').textContent = quiz.dataset.msgScore.replace('{n}', n).replace('{total}', all.length);
      }
      return;
    }
    var card = event.target.closest('.tq-card');
    if (card) {
      var flipped = card.classList.toggle('tq-flipped');
      card.setAttribute('aria-pressed', flipped ? 'true' : 'false');
    }
  });
}());
