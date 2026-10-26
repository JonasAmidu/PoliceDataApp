document.querySelectorAll('.navbar-nav .nav-link').forEach(link => {
    if (new URL(link.href).pathname === window.location.pathname) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
    }
});
