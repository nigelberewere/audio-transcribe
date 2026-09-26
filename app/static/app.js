const $ = (id) => document.getElementById(id);

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

$('loginForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const body = new FormData(event.target);
  try {
    await request('/api/login', {method: 'POST', body});
    location.href = '/home';
  } catch (error) {
    $('loginError').textContent = error.message;
  }
});

// If the user is already authenticated with a valid cookie, redirect straight to /home
request('/api/me').then(() => {
  location.href = '/home';
}).catch(() => {});
