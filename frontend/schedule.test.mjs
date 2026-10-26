import assert from 'node:assert/strict';
import test from 'node:test';
globalThis.HTMLElement = class {};
globalThis.customElements = {get() {return false;}, define() {}};
const {validateSlots, readPlan, editData} = await import('./smartheating-schedule.mjs');
const room = {key: 'bedroom', schedule: 'switch.schedule_bedroomheating'};
const rows = [{start:'00:00',temperature:18},{start:'06:00',temperature:22},{start:'22:00',temperature:19}];
function state(plan = rows) {
  const data = editData(plan, room);
  return {state:'on', attributes:{weekdays:['daily'], timeslots:data.timeslots.map(x => `${x.start} - ${x.stop}`), actions:data.timeslots.map(x => ({service:'mqtt.publish',data:x.actions[0].service_data}))}};
}
test('bridge serialization preserves source, room, non-retained commands and midnight coverage', () => {
  const data = editData(rows,room);
  assert.equal(data.entity_id,room.schedule);
  assert.equal(data.timeslots.at(-1).stop,'00:00:00');
  assert.deepEqual(readPlan(state(),room),rows);
  assert.equal(data.timeslots[1].actions[0].service_data.retain,false);
  assert.deepEqual(JSON.parse(data.timeslots[1].actions[0].service_data.payload),{source:room.schedule,slot:1,temperature:22});
});
test('reject missing midnight, overlaps, invalid hours and invalid temperatures', () => {
  for (const invalid of [[],[{start:'06:00',temperature:20}], [{start:'00:00',temperature:20},{start:'00:00',temperature:22}], [{start:'00:00',temperature:20},{start:'24:00',temperature:22}], [{start:'00:00',temperature:NaN}], [{start:'00:00',temperature:''}], [{start:'00:00',temperature:20.3}], [{start:'00:00',temperature:35}]]) assert.throws(() => validateSlots(invalid));
});
test('reject other calendars, missing intervals and unrelated or retained MQTT actions', () => {
  let s=state();s.attributes.weekdays=['workday'];assert.throws(()=>readPlan(s,room));
  s=state();s.attributes.timeslots[0]='00:00:00 - 05:00:00';assert.throws(()=>readPlan(s,room));
  s=state();s.attributes.actions[0].data.topic='other/topic';assert.throws(()=>readPlan(s,room));
  s=state();s.attributes.actions[0].data.retain=true;assert.throws(()=>readPlan(s,room));
  s=state();s.attributes.actions[0].data.payload=JSON.stringify({source:'switch.unrelated',temperature:20});assert.throws(()=>readPlan(s,room));
  s=state();s.attributes.actions[0].service='climate.set_temperature';assert.throws(()=>readPlan(s,room));
});

test('refuse second precision rather than silently rounding a plan', () => {
  const s=state();s.attributes.timeslots[0]='00:00:30 - 06:00:00';
  assert.throws(()=>readPlan(s,room));
});
