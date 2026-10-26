export function validateSlots(rows) {
  if (!Array.isArray(rows) || !rows.length || rows.length > 24) throw Error('Plan musi zawierać od 1 do 24 przedziałów.');
  let previous = -1;
  return rows.map((row, index) => {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(row.start)) throw Error('Podaj poprawną godzinę rozpoczęcia.');
    const [h, m] = row.start.split(':').map(Number), minute = h * 60 + m;
    if ((!index && minute !== 0) || minute <= previous) throw Error('Plan musi zaczynać się o 00:00, a godziny muszą rosnąć.');
    if (String(row.temperature).trim() === '') throw Error('Podaj temperaturę w każdym przedziale.');
    const temperature = Number(row.temperature);
    if (!Number.isFinite(temperature) || temperature < 5 || temperature > 30 || !Number.isInteger(temperature * 2)) throw Error('Temperatura musi być od 5 do 30°C, z krokiem 0,5°C.');
    previous = minute;
    return { start: row.start, temperature };
  });
}

export function readPlan(state, room) {
  const attrs = state?.attributes;
  if (!attrs || JSON.stringify(attrs.weekdays) !== '["daily"]') throw Error('Ten edytor obsługuje plan codzienny. Nie zmieni planu o innym kalendarzu.');
  if (!Array.isArray(attrs.timeslots) || attrs.timeslots.length !== attrs.actions?.length) throw Error('Niekompletna definicja harmonogramu.');
  const rows = attrs.timeslots.map((slot, index) => {
    if (!/^([01]\d|2[0-3]):[0-5]\d:00 - ([01]\d|2[0-3]):[0-5]\d:00$/.test(slot)) throw Error('Edytor wymaga godzin z dokładnością do minuty.');
    const [start, stop] = slot.split(' - ');
    const next = attrs.timeslots[index + 1]?.split(' - ')[0] ?? '00:00:00';
    if (stop !== next) throw Error('Przedziały muszą pokrywać całą dobę bez przerw.');
    const action = attrs.actions[index], data = action?.data;
    if (action?.service !== 'mqtt.publish' || data?.topic !== `smart_heating/${room.key}/schedule/set` || data?.retain !== false) throw Error('Harmonogram nie jest zgodny z mostem SmartHeating v2.');
    let payload;
    try {payload = JSON.parse(data.payload);} catch {throw Error("Nie można odczytać temperatur z planu. Nie dokonano zmian.");}
    if (payload.source !== room.schedule) throw Error('Harmonogram ma inne źródło poleceń.');
    return {start: start.slice(0, 5), temperature: payload.temperature};
  });
  return validateSlots(rows);
}

export function editData(rows, room) {
  const valid = validateSlots(rows);
  return {entity_id: room.schedule, timeslots: valid.map((row, index) => ({
    start: row.start + ':00', stop: (valid[index + 1]?.start ?? '00:00') + ':00',
    actions: [{service: 'mqtt.publish', service_data: {
      topic: `smart_heating/${room.key}/schedule/set`, retain: false,
      payload: JSON.stringify({source: room.schedule, slot: index, temperature: row.temperature}),
    }}],
  }))};
}

const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const signature = state => JSON.stringify([state?.state, state?.attributes?.weekdays, state?.attributes?.timeslots, state?.attributes?.actions]);

export class SmartHeatingSchedule extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode: 'open'}); this._rows = []; this._dirty = false;
    this.shadowRoot.addEventListener('click', event => this._click(event));
    this.shadowRoot.addEventListener('input', event => this._input(event));
    this.shadowRoot.addEventListener('change', event => {
      if (event.target.id !== 'room') return;
      if (this._dirty && !window.confirm('Porzucić niezapisane zmiany tego pokoju?')) {event.target.value = this._room; return;}
      this._room = event.target.value; this._load();
    });
  }
  setConfig(config) {
    if (!Array.isArray(config.rooms) || !config.rooms.length) throw Error('Wskaż pokoje i ich harmonogramy.');
    this._config = config; this._room ||= config.rooms[0].key;
    if (this._hass) this._load();
  }
  get room() {return this._config.rooms.find(room => room.key === this._room);}
  set hass(hass) {
    this._hass = hass; if (!this._config) return;
    const state = hass.states[this.room.schedule], next = signature(state);
    if (this._pending) {
      try {
        if (JSON.stringify(readPlan(state, this.room)) === JSON.stringify(this._pending)) {
          clearTimeout(this._timeout); this._pending = null; this._dirty = false;
          this._message = 'Plan zapisany i potwierdzony w Home Assistant.'; this._load(false); return;
        }
      } catch { /* Invalid or incomplete readback cannot acknowledge a save. */ }
    }
    if (next === this._signature) return;
    if (this._dirty) {this._conflict = true; this._message = 'Plan zmienił się w HA. Wczytaj go ponownie przed zapisem.'; this._render();}
    else this._load();
  }
  _load(clear = true) {
    this._signature = signature(this._hass?.states[this.room.schedule]);
    this._dirty = false; this._conflict = false; this._error = '';
    if (clear) this._message = '';
    try {this._rows = readPlan(this._hass.states[this.room.schedule], this.room);}
    catch (error) {this._rows = []; this._error = error.message;}
    this._render();
  }
  _input(event) {
    const field = event.target.dataset.field, index = Number(event.target.dataset.index);
    if (!field || this._pending) return;
    this._rows[index][field] = event.target.value; this._dirty = true; this._message = '';
    this.shadowRoot.querySelector('#save').disabled = Boolean(this._conflict);
    this.shadowRoot.querySelector('#notice').textContent = 'Zmiany nie są zapisane.';
  }
  async _click(event) {
    const action = event.target.closest('[data-action]')?.dataset.action;
    if (!action || this._pending) return;
    if (action === 'reload') {if (!this._dirty || window.confirm('Porzucić niezapisane zmiany?')) this._load(); return;}
    if (action === 'remove') {
      const index = Number(event.target.closest('[data-action]').dataset.index);
      if (!index) return;
      this._rows.splice(index, 1); this._dirty = true; this._render(); return;
    }
    if (action === 'add') {
      const last = this._rows.at(-1); if (!last || this._rows.length >= 24) return;
      const [h, m] = last.start.split(':').map(Number), minute = h * 60 + m + 30;
      if (minute >= 1440) {this._message = 'Przesuń ostatni przedział wcześniej, aby dodać kolejny.'; this._render(); return;}
      this._rows.push({start: `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`, temperature: last.temperature});
      this._dirty = true; this._render(); return;
    }
    if (action !== 'save' || this._conflict || !this._dirty) return;
    try {
      const rows = validateSlots(this._rows), data = editData(rows, this.room);
      if (signature(this._hass.states[this.room.schedule]) !== this._signature) throw Error('Plan zmienił się w HA. Wczytaj go ponownie.');
      this._pending = rows; this._message = 'Czekam na potwierdzenie zapisu w HA…'; this._render();
      this._timeout = setTimeout(() => {
        if (!this._pending) return;
        this._pending = null; this._conflict = true;
        this._message = 'Brak potwierdzenia zapisu. Wczytaj plan z HA, aby sprawdzić wynik.'; this._render();
      }, 25000);
      await this._hass.callService('scheduler', 'edit', data);
    } catch (error) {
      clearTimeout(this._timeout); this._pending = null; this._message = error.message; this._render();
    }
  }
  getCardSize() {return 6;}
  disconnectedCallback() {clearTimeout(this._timeout); if (this._pending) {this._pending = null; this._conflict = true; this._message = 'Wczytaj plan ponownie, aby sprawdzić wynik zapisu.';}}
  _render() {
    const disabled = this._pending ? 'disabled' : '';
    const state = this._hass?.states[this.room.schedule];
    this.shadowRoot.innerHTML = `<style>
      :host {display:block;color:var(--primary-text-color,#1b263b);font-family:var(--ha-font-family,inherit)}
      ha-card {padding:20px} h2 {font-size:20px;font-weight:500;margin:0 0 8px}
      p {line-height:1.5;color:var(--secondary-text-color,#5a6575);margin:8px 0 16px;font-size:14px}
      label {display:block;font-size:14px;margin-bottom:8px} select,input {font:inherit;box-sizing:border-box;border:1px solid var(--divider-color,#d7dde5);border-radius:8px;background:var(--card-background-color,#fff);color:inherit;padding:10px;min-height:44px}
      select {width:100%;margin:0 0 20px} input {width:100%;min-width:0}
      .row,.labels {display:grid;grid-template-columns:minmax(100px,1fr) minmax(100px,1fr) 44px;gap:10px;align-items:center;margin-bottom:10px}
      .labels {font-size:13px;color:var(--secondary-text-color,#5a6575)}
      button {font:inherit;cursor:pointer;border:1px solid var(--divider-color,#d7dde5);border-radius:8px;padding:10px 12px;min-height:44px;background:var(--card-background-color,#fff);color:var(--primary-color,#1565c0)}
      button.primary {background:var(--primary-color,#1565c0);color:var(--text-primary-color,#fff);border-color:transparent}
      button:disabled {opacity:.5;cursor:default} :is(button,input,select):focus-visible {outline:3px solid var(--primary-color,#1565c0);outline-offset:2px}
      .actions {display:flex;flex-wrap:wrap;gap:8px;margin-top:16px} #notice {font-size:14px;line-height:1.5;min-height:24px;margin-top:16px}
      .error {color:var(--error-color,#b3261e)} @media(max-width:420px) {ha-card{padding:16px}.row,.labels{gap:6px;grid-template-columns:minmax(90px,1fr) minmax(80px,1fr) 44px}}
      </style><ha-card><h2>Plan temperatur</h2><p>Ten sam plan każdego dnia. Początek następnego przedziału kończy poprzedni.</p>
      <label for="room">Pokój</label><select id="room" ${disabled}>${this._config.rooms.map(r => `<option value="${esc(r.key)}" ${r.key === this._room ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}</select>
      ${state?.state === 'off' ? '<p class="error">Harmonogram jest wyłączony. Pokój nie uczestniczy w automatycznym sterowaniu.</p>' : ''}
      ${this._error ? `<p class="error">${esc(this._error)}</p>` : `<div class="labels"><span>Od godziny</span><span>Cel w °C</span><span></span></div>${this._rows.map((row, index) => `<div class="row"><input aria-label="Początek przedziału ${index + 1}" type="time" step="60" value="${esc(row.start)}" data-field="start" data-index="${index}" ${index === 0 ? 'disabled' : disabled}><input aria-label="Temperatura przedziału ${index + 1}" type="number" inputmode="decimal" min="5" max="30" step="0.5" value="${esc(row.temperature)}" data-field="temperature" data-index="${index}" ${disabled}><button aria-label="Usuń przedział ${index + 1}" data-action="remove" data-index="${index}" ${index === 0 ? 'disabled' : disabled}>×</button></div>`).join('')}`}
      <div class="actions"><button data-action="add" ${disabled || (this._error ? 'disabled' : '')}>Dodaj przedział</button><button id="save" class="primary" data-action="save" ${this._dirty && !this._pending && !this._conflict ? '' : 'disabled'}>Zapisz plan pokoju</button><button data-action="reload" ${disabled}>Wczytaj z HA</button></div>
      <div id="notice" role="status" aria-live="polite">${esc(this._message || (this._dirty ? 'Zmiany nie są zapisane.' : 'Zmiany temperatur zaczną obowiązywać po zapisaniu.'))}</div></ha-card>`;
  }
}
if (!customElements.get('smartheating-schedule')) customElements.define('smartheating-schedule', SmartHeatingSchedule);

if (typeof window !== "undefined") {window.customCards = window.customCards || []; window.customCards.push({type:"smartheating-schedule",name:"SmartHeating — plan temperatur",description:"Edytor codziennego planu dla SmartHeating v2"});}
