(function(){
  const page = document.body.getAttribute('data-page');
  const file = (page||'') + '.html';
  document.querySelectorAll('#mainNav .nav-link').forEach(a=>{
    if (a.getAttribute('href')===file){ a.classList.add('active'); }
  });
})();