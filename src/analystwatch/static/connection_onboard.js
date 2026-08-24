(() => {
  const MICROSOFT_PREFIX = '/api/connections/microsoft';
  const GOOGLE_PREFIX = '/api/connections/google';

  function byId(id) {
    return document.getElementById(id);
  }

  function setInput(id, value) {
    const input = byId(id);
    if (!input) return;
    input.value = value ?? '';
    input.dispatchEvent(new Event('input', {bubbles: true}));
  }

  function errorMessage(body, status) {
    const detail = body && body.detail;
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
      return detail.message;
    }
    if (typeof detail === 'string') return detail;
    return `Request failed with HTTP ${status}.`;
  }

  async function postJson(url, payload) {
    const options = {method: 'POST', headers: {}};
    if (payload !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(url, options);
    let body = null;
    try {
      body = await response.json();
    } catch (_error) {
      body = null;
    }
    if (!response.ok) throw new Error(errorMessage(body, response.status));
    return body;
  }

  function renderStatus(element, message, kind = 'info') {
    element.hidden = false;
    element.textContent = message;
    if (kind === 'ok') element.className = 'healthy-note span-two';
    else if (kind === 'error') element.className = 'contract-issue issue-error span-two';
    else if (kind === 'warning') element.className = 'contract-issue issue-warning span-two';
    else element.className = 'rule-empty span-two';
  }

  function setBusy(button, busy, busyText) {
    if (!button.dataset.originalText) button.dataset.originalText = button.textContent;
    button.disabled = busy;
    button.textContent = busy ? busyText : button.dataset.originalText;
  }

  function replaceOptions(select, items, labelFor, valueFor) {
    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = items.length ? 'Choose…' : 'No matching resources found';
    select.append(placeholder);
    for (const item of items) {
      const option = document.createElement('option');
      option.value = valueFor(item);
      option.textContent = labelFor(item);
      option._analystwatchItem = item;
      select.append(option);
    }
    select.disabled = !items.length;
  }

  function selectedItem(select) {
    const option = select.options[select.selectedIndex];
    return option ? option._analystwatchItem || null : null;
  }

  function identityLabel(identity) {
    const primary = identity.display_name || identity.email || identity.subject_id;
    if (identity.email && identity.email !== primary) return `${primary} · ${identity.email}`;
    return primary;
  }

  function excelColumnLabel(columnCount) {
    let value = columnCount;
    let label = '';
    while (value > 0) {
      value -= 1;
      label = String.fromCharCode(65 + (value % 26)) + label;
      value = Math.floor(value / 26);
    }
    return label;
  }

  function boundedGoogleRange(sheet) {
    if (!Number.isInteger(sheet.row_count) || !Number.isInteger(sheet.column_count)) return null;
    if (sheet.row_count < 1 || sheet.column_count < 1) return null;
    if (sheet.row_count > 5000 || sheet.column_count > 100) return null;
    const title = `'${String(sheet.title).replaceAll("'", "''")}'`;
    return `${title}!A1:${excelColumnLabel(sheet.column_count)}${sheet.row_count}`;
  }

  function injectMicrosoftBrowser() {
    const container = byId('microsoft-fields');
    const grid = container && container.querySelector('.microsoft-grid');
    if (!grid) return;

    const browser = document.createElement('div');
    browser.className = 'form-grid span-two';
    browser.innerHTML = `
      <div class="form-section span-two">
        <strong>Browse connected Microsoft files</strong>
        <span>Optional. Test the standard server connection, verify the connected account, choose a drive/workbook/table, then review the ordinary connector fields below. Manual IDs remain available.</span>
      </div>
      <div class="form-actions span-two">
        <button id="microsoft-connection-test" class="secondary" type="button">Test Microsoft connection</button>
        <button id="microsoft-identity-test" class="secondary" type="button">Verify connected account</button>
        <button id="microsoft-browse-drives" class="secondary" type="button">Browse drives</button>
      </div>
      <div id="microsoft-connection-status" class="rule-empty span-two">Browse/test uses the server's standard Microsoft credential; the saved source still uses the credential reference below.</div>
      <label><span>Available drive</span><select id="microsoft-drive-select" disabled><option value="">Browse drives first</option></select></label>
      <label><span>Workbook search</span><input id="microsoft-workbook-query" placeholder="forecast or sales"></label>
      <div class="form-actions span-two"><button id="microsoft-search-workbooks" class="secondary" type="button" disabled>Search workbooks</button></div>
      <label class="span-two"><span>Workbook</span><select id="microsoft-workbook-select" disabled><option value="">Search a drive first</option></select></label>
      <div class="form-actions span-two"><button id="microsoft-load-tables" class="secondary" type="button" disabled>Load workbook tables</button></div>
      <label class="span-two"><span>Excel table</span><select id="microsoft-table-select" disabled><option value="">Load a workbook first</option></select></label>`;
    grid.prepend(browser);

    const testButton = byId('microsoft-connection-test');
    const identityButton = byId('microsoft-identity-test');
    const drivesButton = byId('microsoft-browse-drives');
    const status = byId('microsoft-connection-status');
    const driveSelect = byId('microsoft-drive-select');
    const queryInput = byId('microsoft-workbook-query');
    const searchButton = byId('microsoft-search-workbooks');
    const workbookSelect = byId('microsoft-workbook-select');
    const tablesButton = byId('microsoft-load-tables');
    const tableSelect = byId('microsoft-table-select');

    testButton.addEventListener('click', async () => {
      setBusy(testButton, true, 'Testing…');
      try {
        const result = await postJson(`${MICROSOFT_PREFIX}/check`);
        if (result.reachable) renderStatus(status, 'Microsoft connection is reachable.', 'ok');
        else renderStatus(status, result.error || 'Microsoft connection is not reachable.', 'warning');
      } catch (error) {
        renderStatus(status, String(error), 'error');
      } finally {
        setBusy(testButton, false, 'Testing…');
      }
    });

    identityButton.addEventListener('click', async () => {
      setBusy(identityButton, true, 'Verifying…');
      try {
        const identity = await postJson(`${MICROSOFT_PREFIX}/identity`);
        renderStatus(status, `Connected Microsoft account: ${identityLabel(identity)}.`, 'ok');
      } catch (error) {
        renderStatus(status, String(error), 'error');
      } finally {
        setBusy(identityButton, false, 'Verifying…');
      }
    });

    drivesButton.addEventListener('click', async () => {
      setBusy(drivesButton, true, 'Loading…');
      try {
        const drives = await postJson(`${MICROSOFT_PREFIX}/drives`);
        replaceOptions(
          driveSelect,
          drives,
          item => item.drive_type ? `${item.name} · ${item.drive_type}` : item.name,
          item => item.id
        );
        renderStatus(status, `${drives.length} Microsoft drive(s) available.`, drives.length ? 'ok' : 'info');
      } catch (error) {
        renderStatus(status, String(error), 'error');
      } finally {
        setBusy(drivesButton, false, 'Loading…');
      }
    });

    driveSelect.addEventListener('change', () => {
      const drive = selectedItem(driveSelect);
      setInput('microsoft-drive-id', drive ? drive.id : '');
      searchButton.disabled = !drive;
      workbookSelect.disabled = true;
      tablesButton.disabled = true;
      tableSelect.disabled = true;
    });

    queryInput.addEventListener('input', () => {
      searchButton.disabled = !selectedItem(driveSelect) || !queryInput.value.trim();
    });

    searchButton.addEventListener('click', async () => {
      const drive = selectedItem(driveSelect);
      if (!drive || !queryInput.value.trim()) return;
      setBusy(searchButton, true, 'Searching…');
      try {
        const workbooks = await postJson(`${MICROSOFT_PREFIX}/workbooks`, {
          drive_id: drive.id,
          query: queryInput.value.trim()
        });
        replaceOptions(workbookSelect, workbooks, item => item.name, item => item.item_id);
        renderStatus(status, `${workbooks.length} Excel workbook(s) matched.`, workbooks.length ? 'ok' : 'info');
      } catch (error) {
        renderStatus(status, String(error), 'error');
      } finally {
        setBusy(searchButton, false, 'Searching…');
      }
    });

    workbookSelect.addEventListener('change', () => {
      const workbook = selectedItem(workbookSelect);
      setInput('microsoft-item-id', workbook ? workbook.item_id : '');
      tablesButton.disabled = !workbook;
      tableSelect.disabled = true;
    });

    tablesButton.addEventListener('click', async () => {
      const drive = selectedItem(driveSelect);
      const workbook = selectedItem(workbookSelect);
      if (!drive || !workbook) return;
      setBusy(tablesButton, true, 'Loading…');
      try {
        const tables = await postJson(`${MICROSOFT_PREFIX}/tables`, {
          drive_id: drive.id,
          item_id: workbook.item_id
        });
        replaceOptions(tableSelect, tables, item => item.name, item => item.name);
        renderStatus(status, `${tables.length} Excel table(s) available.`, tables.length ? 'ok' : 'info');
      } catch (error) {
        renderStatus(status, String(error), 'error');
      } finally {
        setBusy(tablesButton, false, 'Loading…');
      }
    });

    tableSelect.addEventListener('change', () => {
      const table = selectedItem(tableSelect);
      setInput('microsoft-table', table ? table.name : '');
    });
  }

  function injectGoogleBrowser() {
    const container = byId('google-fields');
    const grid = container && container.querySelector('.google-grid');
    if (!grid) return;

    const browser = document.createElement('div');
    browser.className = 'form-grid span-two';
    browser.innerHTML = `
      <div class="form-section span-two">
        <strong>Browse connected Google Sheets</strong>
        <span>Optional. Test the standard server connection, verify the connected account, choose a spreadsheet and sheet, then review the explicit A1 range below. Manual IDs/ranges remain available.</span>
      </div>
      <div class="form-actions span-two">
        <button id="google-connection-test" class="secondary" type="button">Test Google connection</button>
        <button id="google-identity-test" class="secondary" type="button">Verify connected account</button>
        <button id="google-browse-spreadsheets" class="secondary" type="button">Browse spreadsheets</button>
      </div>
      <div id="google-connection-status" class="rule-empty span-two">Browse/test uses the server's standard Google credential; the saved source still uses the credential reference below.</div>
      <label class="span-two"><span>Spreadsheet</span><select id="google-spreadsheet-select" disabled><option value="">Browse spreadsheets first</option></select></label>
      <div class="form-actions span-two"><button id="google-load-sheets" class="secondary" type="button" disabled>Load sheets</button></div>
      <label class="span-two"><span>Sheet / tab</span><select id="google-sheet-select" disabled><option value="">Load a spreadsheet first</option></select></label>`;
    grid.prepend(browser);

    const testButton = byId('google-connection-test');
    const identityButton = byId('google-identity-test');
    const browseButton = byId('google-browse-spreadsheets');
    const status = byId('google-connection-status');
    const spreadsheetSelect = byId('google-spreadsheet-select');
    const loadSheetsButton = byId('google-load-sheets');
    const sheetSelect = byId('google-sheet-select');

    testButton.addEventListener('click', async () => {
      setBusy(testButton, true, 'Testing…');
      try {
        const result = await postJson(`${GOOGLE_PREFIX}/check`);
        if (result.reachable) renderStatus(status, 'Google connection is reachable.', 'ok');
        else renderStatus(status, result.error || 'Google connection is not reachable.', 'warning');
      } catch (error) {
        renderStatus(status, String(error), 'error');
      } finally {
        setBusy(testButton, false, 'Testing…');
      }
    });

    identityButton.addEventListener('click', async () => {
      setBusy(identityButton, true, 'Verifying…');
      try {
        const identity = await postJson(`${GOOGLE_PREFIX}/identity`);
        renderStatus(status, `Connected Google account: ${identityLabel(identity)}.`, 'ok');
      } catch (error) {
        renderStatus(status, String(error), 'error');
      } finally {
        setBusy(identityButton, false, 'Verifying…');
      }
    });

    browseButton.addEventListener('click', async () => {
      setBusy(browseButton, true, 'Loading…');
      try {
        const spreadsheets = await postJson(`${GOOGLE_PREFIX}/spreadsheets`);
        replaceOptions(spreadsheetSelect, spreadsheets, item => item.name, item => item.id);
        renderStatus(status, `${spreadsheets.length} Google spreadsheet(s) available.`, spreadsheets.length ? 'ok' : 'info');
      } catch (error) {
        renderStatus(status, String(error), 'error');
      } finally {
        setBusy(browseButton, false, 'Loading…');
      }
    });

    spreadsheetSelect.addEventListener('change', () => {
      const spreadsheet = selectedItem(spreadsheetSelect);
      setInput('google-spreadsheet-id', spreadsheet ? spreadsheet.id : '');
      loadSheetsButton.disabled = !spreadsheet;
      sheetSelect.disabled = true;
    });

    loadSheetsButton.addEventListener('click', async () => {
      const spreadsheet = selectedItem(spreadsheetSelect);
      if (!spreadsheet) return;
      setBusy(loadSheetsButton, true, 'Loading…');
      try {
        const sheets = await postJson(`${GOOGLE_PREFIX}/sheets`, {
          spreadsheet_id: spreadsheet.id
        });
        replaceOptions(sheetSelect, sheets, item => item.title, item => String(item.sheet_id));
        renderStatus(status, `${sheets.length} grid sheet(s) available.`, sheets.length ? 'ok' : 'info');
      } catch (error) {
        renderStatus(status, String(error), 'error');
      } finally {
        setBusy(loadSheetsButton, false, 'Loading…');
      }
    });

    sheetSelect.addEventListener('change', () => {
      const sheet = selectedItem(sheetSelect);
      if (!sheet) return;
      const range = boundedGoogleRange(sheet);
      if (range) {
        setInput('google-range', range);
        renderStatus(status, 'A bounded A1 range was filled from the sheet grid dimensions. Review it before preflight.', 'ok');
      } else {
        setInput('google-range', '');
        renderStatus(
          status,
          'Sheet selected, but its grid is missing or larger than the 5,000-row / 100-column safe suggestion limit. Enter an explicit A1 range before preflight.',
          'warning'
        );
      }
    });
  }

  injectMicrosoftBrowser();
  injectGoogleBrowser();
})();