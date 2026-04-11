document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('user-search-input');
    const profileSelect = document.getElementById('id_profile_select');
    
    if (!searchInput || !profileSelect) return;

    let debounceTimer;
    let searchResults = [];

    // Create dropdown container
    const dropdown = document.createElement('div');
    dropdown.className = 'user-search-dropdown';
    dropdown.style.display = 'none';
    searchInput.parentNode.appendChild(dropdown);

    // Search function
    function performSearch(query) {
        if (query.length < 2) {
            dropdown.style.display = 'none';
            return;
        }

        fetch(`./search-user/?q=${encodeURIComponent(query)}`)
            .then(response => response.json())
            .then(data => {
                searchResults = data.results || [];
                displayResults(searchResults);
            })
            .catch(error => {
                console.error('Search error:', error);
                dropdown.style.display = 'none';
            });
    }

    // Display results in dropdown
    function displayResults(results) {
        if (results.length === 0) {
            dropdown.style.display = 'none';
            return;
        }

        dropdown.innerHTML = '';
        
        results.forEach(user => {
            const item = document.createElement('div');
            item.className = 'user-search-item';
            item.innerHTML = `
                <div class="user-search-item-main">
                    <strong>${escapeHtml(user.username)}</strong>
                    <span class="user-search-item-email">${escapeHtml(user.email)}</span>
                </div>
                <div class="user-search-item-code">Code: ${escapeHtml(user.referral_code)}</div>
            `;
            
            item.addEventListener('click', function() {
                selectUser(user);
            });
            
            dropdown.appendChild(item);
        });

        dropdown.style.display = 'block';
    }

    // Select user and update profile field
    function selectUser(user) {
        // Update profile select
        const option = new Option(user.display, user.id, true, true);
        profileSelect.innerHTML = '';
        profileSelect.add(option);
        profileSelect.value = user.id;
        
        // Update search input to show selected user
        searchInput.value = user.display;
        searchInput.setAttribute('data-selected-id', user.id);
        
        // Hide dropdown
        dropdown.style.display = 'none';
        
        // Visual feedback
        searchInput.classList.add('user-selected');
        setTimeout(() => searchInput.classList.remove('user-selected'), 500);
    }

    // Escape HTML to prevent XSS
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Event listeners
    searchInput.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        const query = this.value.trim();
        
        // If field is cleared, reset profile selection
        if (!query) {
            profileSelect.value = '';
            searchInput.removeAttribute('data-selected-id');
            dropdown.style.display = 'none';
            return;
        }
        
        debounceTimer = setTimeout(() => performSearch(query), 300);
    });

    searchInput.addEventListener('focus', function() {
        if (searchResults.length > 0 && this.value.trim().length >= 2) {
            dropdown.style.display = 'block';
        }
    });

    searchInput.addEventListener('blur', function() {
        setTimeout(() => {
            dropdown.style.display = 'none';
        }, 200);
    });

    searchInput.addEventListener('keydown', function(e) {
        const items = dropdown.querySelectorAll('.user-search-item');
        const activeItem = dropdown.querySelector('.user-search-item.active');
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            let index = activeItem ? Array.from(items).indexOf(activeItem) + 1 : 0;
            if (index >= items.length) index = 0;
            
            if (activeItem) activeItem.classList.remove('active');
            items[index].classList.add('active');
            items[index].scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            let index = activeItem ? Array.from(items).indexOf(activeItem) - 1 : items.length - 1;
            if (index < 0) index = items.length - 1;
            
            if (activeItem) activeItem.classList.remove('active');
            items[index].classList.add('active');
            items[index].scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (activeItem) activeItem.click();
        } else if (e.key === 'Escape') {
            dropdown.style.display = 'none';
        }
    });

    // Form submission validation
    const form = searchInput.closest('form');
    if (form) {
        form.addEventListener('submit', function(e) {
            const selectedId = searchInput.getAttribute('data-selected-id');
            if (!profileSelect.value && !selectedId) {
                e.preventDefault();
                alert('Veuillez sélectionner un utilisateur avant de créer le paiement.');
                searchInput.focus();
                return false;
            }
            
            // Ensure profile field has the value
            if (selectedId) {
                profileSelect.value = selectedId;
            }
        });
    }
});
