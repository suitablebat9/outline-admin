const nativePanel = $('#native-panel');
let nativeLoading = false;
function nativeSecret(name, password) {
  $('#native-owner').textContent = name;
  $('#native-value').value = password;
  $('#native-secret').showModal();
}
$('#native-secret').addEventListener('close', () => { $('#native-value').value = ''; });

async function refreshNative() {
  if (nativeLoading || !nativePanel.open || $('#dashboard').hidden || document.hidden) return;
  nativeLoading = true;
  try {
    const data = await api('/api/native');
    $('#native-add').hidden = !data.installed;
    $('#native-status').textContent = !data.installed ? 'Install the native gateway in this guest to manage accounts.' :
      data.online ? 'Server and Remote ID: ' + data.hostname : 'Gateway unavailable. Session counts are unknown.';
    const rows = data.users.map(user => {
      const row = el('tr');
      for (const value of [user.name, data.online ? user.sessions : '—',
        data.online ? bytes(user.upload) : '—', data.online ? bytes(user.download) : '—']) row.append(el('td', value));
      const actions = el('td');
      const show = el('button', 'View password', 'text-button');
      const revoke = el('button', 'Revoke', 'revoke');
      const url = '/api/native/' + encodeURIComponent(user.name);
      show.onclick = async () => {
        try { nativeSecret(user.name, (await api(url + '/password')).password); }
        catch (error) { toast(error.message); }
      };
      revoke.onclick = async () => {
        if (!window.confirm('Revoke VPN access and disconnect ' + user.name + '?')) return;
        revoke.disabled = true;
        try { await api(url, {method:'DELETE'}); await refreshNative(); }
        catch (error) { toast(error.message); revoke.disabled = false; }
      };
      actions.append(show, revoke);
      row.append(actions);
      return row;
    });
    $('#native-users').replaceChildren(...rows);
  } catch (error) { $('#native-status').textContent = error.message; }
  finally { nativeLoading = false; }
}
$('#native-add').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.target;
  const submit = form.querySelector('button');
  submit.disabled = true;
  try {
    const result = await api('/api/native', {method:'POST', body:JSON.stringify({name:form.elements.name.value})});
    form.reset();
    nativeSecret(result.name, result.password);
    await refreshNative();
  } catch (error) { toast(error.message); }
  finally { submit.disabled = false; }
});
nativePanel.addEventListener('toggle', refreshNative);
setInterval(refreshNative, 5000);
