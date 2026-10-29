// KaamNearby Dashboard & Price Negotiation JavaScript

document.addEventListener('DOMContentLoaded', function () {
  // 1. Counter-Offer Form Toggle
  const toggleCounterBtn = document.getElementById('toggleCounterBtn');
  const counterOfferBox = document.getElementById('counterOfferBox');
  if (toggleCounterBtn && counterOfferBox) {
    toggleCounterBtn.addEventListener('click', function () {
      if (counterOfferBox.style.display === 'none' || counterOfferBox.style.display === '') {
        counterOfferBox.style.display = 'block';
        toggleCounterBtn.textContent = 'Hide Counter Form';
      } else {
        counterOfferBox.style.display = 'none';
        toggleCounterBtn.textContent = 'Make Counter-Offer';
      }
    });
  }

  // 2. Interactive Star Rating Selector
  const starWidget = document.getElementById('starRatingWidget');
  const ratingInput = document.getElementById('ratingInput');
  if (starWidget && ratingInput) {
    const stars = starWidget.querySelectorAll('span');
    stars.forEach(function (star, index) {
      star.addEventListener('click', function () {
        const val = index + 1;
        ratingInput.value = val;
        updateStars(val);
      });

      star.addEventListener('mouseenter', function () {
        highlightStars(index + 1);
      });
    });

    starWidget.addEventListener('mouseleave', function () {
      updateStars(parseInt(ratingInput.value) || 5);
    });

    function updateStars(val) {
      stars.forEach(function (s, i) {
        if (i < val) {
          s.style.color = '#EAB308';
        } else {
          s.style.color = '#CBD5E1';
        }
      });
    }

    function highlightStars(val) {
      stars.forEach(function (s, i) {
        if (i < val) {
          s.style.color = '#FACC15';
        } else {
          s.style.color = '#CBD5E1';
        }
      });
    }

    // Initial state
    updateStars(parseInt(ratingInput.value) || 5);
  }
});

