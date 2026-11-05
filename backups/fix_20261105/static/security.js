/* CSRF + escaping helpers for КРЕВЕТКА POS */
(function () {
  'use strict';
  var meta = document.querySelector('meta[name="csrf-token"]');
  var token = meta ? meta.getAttribute('content') : '';
  window.CSRF_TOKEN = token;

  window.esc = function (value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };

  if (window.fetch) {
    var originalFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      init = init || {};
      var method = (init.method || (input && input.method) || 'GET').toUpperCase();
      if (method !== 'GET' && method !== 'HEAD') {
        var headers = new Headers(init.headers || {});
        if (token && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', token);
        init.headers = headers;
      }
      return originalFetch(input, init);
    };
  }

  function addCsrfInputs() {
    if (!token) return;
    var forms = document.querySelectorAll('form');
    for (var i = 0; i < forms.length; i++) {
      var form = forms[i];
      var method = (form.getAttribute('method') || 'get').toLowerCase();
      if (method !== 'post') continue;
      if (form.querySelector('input[name="csrf_token"]')) continue;
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'csrf_token';
      input.value = token;
      form.appendChild(input);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', addCsrfInputs);
  } else {
    addCsrfInputs();
  }
})();
