<template>
  <div class="stat-card">
    <div class="label">{{ label }}</div>
    <div class="value num">
      {{ value }}<span v-if="unit" class="unit">{{ unit }}</span>
    </div>
    <div v-if="field" class="field-name">{{ field }}</div>
    <div v-if="desc" class="desc">{{ desc }}</div>
  </div>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  unit: { type: String, default: '' },
  field: { type: String, default: '' },
  desc: { type: String, default: '' }
})
</script>

<style scoped>
.stat-card {
  background: #fff;
  border: 1px solid var(--c-line);
  border-radius: var(--radius);
  padding: 16px;
}
.label { font-size: 12px; color: var(--c-muted); }
.value {
  font-size: 26px;
  font-weight: 700;
  color: var(--c-primary);
  line-height: 1.3;
  margin-top: 2px;
}
.unit { font-size: 13px; font-weight: 500; color: var(--c-muted); margin-left: 4px; }
.field-name { margin-top: 2px; }
.desc {
  font-size: 11px;
  color: var(--c-muted);
  margin-top: 8px;
  border-top: 1px dashed var(--c-line);
  padding-top: 6px;
}
</style>
