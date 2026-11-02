<template>
  <div class="layout">
    <header class="topbar">
      <div class="brand">BJ-House Insight</div>
      <nav class="nav">
        <RouterLink
          v-for="item in topNav"
          :key="item.path"
          :to="item.path"
          class="nav-link"
          :class="{ on: isActive(item) }"
        >{{ item.title }}</RouterLink>
      </nav>
      <div class="mode">
        <span class="dot" :class="isStatic ? 'static' : 'http'" />
        {{ isStatic ? '静态数据模式（只读）' : '接口模式（完整系统）' }}
      </div>
    </header>

    <div class="body">
      <aside class="side">
        <template v-for="group in sideGroups" :key="group.name">
          <div class="group-name">{{ group.name }}</div>
          <RouterLink
            v-for="item in group.items"
            :key="item.path"
            :to="item.path"
            class="side-link"
            :class="{ on: isActive(item) }"
          >{{ item.title }}</RouterLink>
        </template>
      </aside>

      <main class="content">
        <RouterView v-slot="{ Component }">
          <component :is="Component" />
        </RouterView>
      </main>
    </div>

    <footer class="foot">
      数据源：2890 条挂牌房源（2024-08 快照）｜
      单价口径：算术均值 64,765 元/㎡，面积加权 64,028 元/㎡｜
      极值只标记不删除（72 行）
    </footer>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { isStatic } from '@/api'

const route = useRoute()

const NAV = [
  { path: '/overview', title: '概览', group: '分析' },
  { path: '/analytics', title: '分析看板', group: '分析' },
  { path: '/search', title: '检索', group: '找房' },
  { path: '/compare', title: '对比', group: '找房' },
  { path: '/valuation', title: '估价', group: '辅助' },
  { path: '/admin', title: '管理', group: '管理' }
]

const topNav = NAV

/**
 * 侧栏只放"一定会有内容"的入口。
 * 详情页与小区画像需要具体 id，硬编码 /houses/1 之类会显得莫名其妙，
 * 因此改为从真实数据进入：概览页的小区卡片 → 小区画像；检索/概览的结果行 → 房源详情。
 */
const sideGroups = computed(() => {
  const groups = {}
  NAV.forEach((item) => {
    if (!groups[item.group]) groups[item.group] = []
    groups[item.group].push(item)
  })
  return Object.entries(groups).map(([name, items]) => ({ name, items }))
})

function isActive(item) {
  if (item.path.startsWith('/houses/')) return route.path.startsWith('/houses/')
  if (item.path.startsWith('/communities/')) return route.path.startsWith('/communities/')
  return route.path === item.path
}
</script>

<style scoped>
.layout { min-height: 100%; display: flex; flex-direction: column; }

.topbar {
  height: var(--topbar-h);
  background: var(--c-primary);
  color: #fff;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 20px;
  position: sticky;
  top: 0;
  z-index: 20;
}
.brand { font-weight: 700; letter-spacing: .5px; white-space: nowrap; }
.nav { display: flex; gap: 2px; flex-wrap: wrap; }
.nav-link {
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  opacity: .85;
  white-space: nowrap;
}
.nav-link:hover { background: rgba(255, 255, 255, .12); opacity: 1; }
.nav-link.on { background: rgba(255, 255, 255, .2); opacity: 1; font-weight: 600; }
.mode {
  margin-left: auto;
  font-size: 12px;
  opacity: .9;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.dot.http { background: #4ade80; }
.dot.static { background: #fbbf24; }

.body { flex: 1; display: flex; min-height: 0; }

.side {
  width: var(--side-w);
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid var(--c-line);
  padding: 12px 0;
}
.group-name {
  font-size: 11px;
  color: var(--c-muted);
  letter-spacing: 1px;
  padding: 8px 20px 4px;
}
.side-link {
  display: block;
  padding: 9px 20px;
  font-size: 13px;
  border-left: 3px solid transparent;
}
.side-link:hover { background: #f1f5f9; }
.side-link.on {
  border-left-color: var(--c-primary);
  background: var(--c-primary-soft);
  color: var(--c-primary);
  font-weight: 600;
}

.content { flex: 1; padding: 24px; min-width: 0; }

.foot {
  padding: 16px 24px;
  font-size: 11px;
  color: var(--c-muted);
  text-align: center;
  border-top: 1px solid var(--c-line);
}

@media (max-width: 1024px) {
  .side { display: none; }
  .content { padding: 16px; }
}
</style>
