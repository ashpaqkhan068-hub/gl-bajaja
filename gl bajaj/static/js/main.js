// KaamNearby Main JavaScript

document.addEventListener('DOMContentLoaded', function () {
  // 1. Initialize Lucide Icons if available
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }

  // 2. Mobile Navigation Toggle
  const mobileToggle = document.getElementById('mobileNavToggle');
  const navLinks = document.getElementById('navLinks');
  if (mobileToggle && navLinks) {
    mobileToggle.addEventListener('click', function () {
      navLinks.classList.toggle('show');
    });
  }

  // 3. User Dropdown Menu
  const userDropdownTrigger = document.getElementById('userDropdownTrigger');
  const userDropdownMenu = document.getElementById('userDropdownMenu');
  if (userDropdownTrigger && userDropdownMenu) {
    userDropdownTrigger.addEventListener('click', function (e) {
      e.stopPropagation();
      userDropdownMenu.classList.toggle('show');
    });

    document.addEventListener('click', function (e) {
      if (!userDropdownMenu.contains(e.target) && e.target !== userDropdownTrigger) {
        userDropdownMenu.classList.remove('show');
      }
    });
  }

  // 4. Flash Alerts Dismissal
  const alertCloses = document.querySelectorAll('.alert-close');
  alertCloses.forEach(function (btn) {
    btn.addEventListener('click', function () {
      const alert = btn.closest('.alert');
      if (alert) {
        alert.style.opacity = '0';
        alert.style.transform = 'translateY(-10px)';
        setTimeout(() => alert.remove(), 250);
      }
    });
  });

  // Auto-dismiss success flash alerts after 5 seconds
  const autoAlerts = document.querySelectorAll('.alert-success, .alert-info');
  autoAlerts.forEach(function (alert) {
    setTimeout(function () {
      if (alert) {
        alert.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
        alert.style.opacity = '0';
        alert.style.transform = 'translateY(-10px)';
        setTimeout(() => alert.remove(), 400);
      }
    }, 5000);
  });

  // 5. Password Show/Hide Toggle
  const togglePassBtns = document.querySelectorAll('.toggle-password');
  togglePassBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      const targetId = btn.getAttribute('data-target');
      const input = document.getElementById(targetId);
      if (input) {
        if (input.type === 'password') {
          input.type = 'text';
          btn.innerHTML = '<i data-lucide="eye-off"></i>';
        } else {
          input.type = 'password';
          btn.innerHTML = '<i data-lucide="eye"></i>';
        }
        if (typeof lucide !== 'undefined') lucide.createIcons();
      }
    });
  });

  // 6. Generic Confirmation Form Submissions
  const confirmForms = document.querySelectorAll('form[data-confirm]');
  confirmForms.forEach(function (form) {
    form.addEventListener('submit', function (e) {
      const msg = form.getAttribute('data-confirm') || 'Are you sure you want to proceed?';
      if (!confirm(msg)) {
        e.preventDefault();
      }
    });
  });
});

