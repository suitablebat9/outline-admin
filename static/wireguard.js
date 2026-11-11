async function wireguardDevices() {
  try {
    const result = await api('/api/wireguard');
    $('#wg-add').hidden = !result.installed;
    $('#wg-status').textContent = result.installed
      ? 'Create one profile per device. Adding or revoking a device briefly reconnects WireGuard clients.'
      : 'Install the WireGuard gateway in this guest to create devices.';
    $('#wg-devices').replaceChildren(...result.devices.map(name => {
      const row = el('tr');
      const downloads = el('td');
      const url = '/api/wireguard/' + encodeURIComponent(name);
      for (const [label, extension] of [['WireGuard (.conf)', 'conf'], ['Shadowsocks · sing-box (.json)', 'json']]) {
        const link = el('a', label, 'text-button');
        link.href = url + '/' + extension;
        link.download = name + '.' + extension;
        downloads.append(link, document.createTextNode(' '));
      }
      const actions = el('td');
      const remove = el('button', 'Revoke', 'revoke');
      remove.onclick = async () => {
        if (!confirm('Revoke both profiles for ' + name + '?')) return;
        remove.disabled = true;
        try { await api(url, {method:'DELETE'}); await wireguardDevices(); }
        catch (error) { toast(error.message); remove.disabled = false; }
      };
      actions.append(remove);
      row.append(el('td', name), downloads, actions);
      return row;
    }));
  } catch (error) { $('#wg-status').textContent = error.message; }
}
$('#wg-panel').addEventListener('toggle', () => { if ($('#wg-panel').open) wireguardDevices(); });
$('#wg-add').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.target;
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    await api('/api/wireguard', {method:'POST', body:JSON.stringify({name:form.elements.name.value.trim()})});
    form.reset();
    await wireguardDevices();
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
});
