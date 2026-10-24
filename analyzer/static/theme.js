(() => {
  const storageKey = 'smart-traffic-theme';
  let theme = 'light';
  try {
    theme = localStorage.getItem(storageKey) || 'light';
  } catch (_) {
    // Keep the default theme when browser storage is unavailable.
  }
  if (theme !== 'dark' && theme !== 'light') theme = 'light';
  document.documentElement.dataset.theme = theme;

  document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;
    const label = toggle.querySelector('.theme-label');
    const icon = toggle.querySelector('.theme-icon');

    const render = () => {
      const isDark = document.documentElement.dataset.theme === 'dark';
      toggle.setAttribute('aria-pressed', String(isDark));
      toggle.setAttribute('aria-label', isDark ? '라이트 모드로 전환' : '다크 모드로 전환');
      label.textContent = isDark ? '라이트 모드' : '다크 모드';
      icon.textContent = isDark ? '☀' : '◐';
    };

    render();
    toggle.addEventListener('click', () => {
      const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = nextTheme;
      try {
        localStorage.setItem(storageKey, nextTheme);
      } catch (_) {
        // Theme still changes for this page view when storage is unavailable.
      }
      render();
      window.dispatchEvent(new CustomEvent('themechange'));
    });
  });
})();
