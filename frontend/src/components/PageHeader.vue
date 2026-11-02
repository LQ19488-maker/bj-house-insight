<template>
  <div class="page-header">
    <h1 class="page-title">
      {{ title }}<span v-if="sub" class="page-sub">{{ sub }}</span>
    </h1>
    <div v-if="caliber" class="caliber">{{ caliber }}</div>
    <slot />
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  sub: { type: String, default: '' },
  caliber: { type: String, default: '' }
})
</script>

<style scoped>
.page-header { margin-bottom: 16px; }
</style>
