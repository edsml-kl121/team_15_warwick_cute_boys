for (const quiz of document.querySelectorAll('[data-quiz]')) {
  const feedback = quiz.querySelector('.feedback');
  const choices = quiz.querySelectorAll('button');

  quiz.addEventListener('click', event => {
    const answer = event.target.closest('button[data-feedback]');
    if (!answer) return;

    for (const choice of choices) {
      choice.toggleAttribute('data-selected', choice === answer);
      choice.setAttribute('aria-pressed', String(choice === answer));
    }

    feedback.textContent = answer.dataset.feedback;
  });
}
