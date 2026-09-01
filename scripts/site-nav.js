(() => {
  const toggle = document.querySelector('.site-nav__toggle');
  const navigation = document.querySelector('#primary-navigation');

  if (!toggle || !navigation) return;

  const mobileQuery = window.matchMedia('(max-width: 63.999rem)');
  document.documentElement.classList.add('js');

  const closeMenu = (restoreFocus = false) => {
    toggle.setAttribute('aria-expanded', 'false');
    navigation.classList.remove('is-open');
    if (restoreFocus) toggle.focus();
  };

  const openMenu = () => {
    toggle.setAttribute('aria-expanded', 'true');
    navigation.classList.add('is-open');
  };

  toggle.addEventListener('click', () => {
    if (toggle.getAttribute('aria-expanded') === 'true') closeMenu();
    else openMenu();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
      closeMenu(true);
    }
  });

  navigation.addEventListener('click', (event) => {
    if (mobileQuery.matches && event.target.closest('a')) closeMenu();
  });

  mobileQuery.addEventListener('change', () => {
    closeMenu();
  });
})();
