<!-- 认证页面布局：以知识路径图形呈现平台的学习闭环。 -->
<template>
  <div class="auth-layout min-h-dvh">
    <section class="auth-brand" aria-labelledby="brand-heading">
      <div class="brand-top">
        <router-link to="/" class="brand-logo" aria-label="自适应学习系统首页">
          <img src="/images/logo.svg" alt="" class="auth-logo" />
          <span>自适应学习系统</span>
        </router-link>
        <span class="brand-edition">知识图谱 · 个性化学习</span>
      </div>

      <div class="brand-content">
        <h1 id="brand-heading">看清进度，<br /><em>知道下一步。</em></h1>
        <p class="brand-subtitle">测评后查看掌握情况和学习路径。</p>

        <div class="learning-map" aria-hidden="true">
          <svg viewBox="0 0 540 270" role="presentation">
            <path class="map-track" d="M70 188 C130 188 137 74 235 74 S350 174 457 93" />
            <path class="map-active" d="M70 188 C130 188 137 74 235 74" />
            <circle class="map-halo" cx="235" cy="74" r="30" />
            <circle class="map-node" cx="70" cy="188" r="10" />
            <circle class="map-node map-node--active" cx="235" cy="74" r="13" />
            <circle class="map-node" cx="457" cy="93" r="10" />
            <text x="40" y="224">01 · 学习诊断</text>
            <text x="204" y="40">02 · 规划路径</text>
            <text x="424" y="132">03 · 巩固提升</text>
          </svg>
        </div>
      </div>

      <div class="brand-footer">
        <span>© {{ currentYear }} 自适应学习系统</span>
      </div>
    </section>

    <main class="auth-form-area">
      <div class="form-container">
        <router-view v-slot="{ Component, route }">
          <transition name="auth-fade" mode="out-in">
            <component :is="Component" :key="route.path" />
          </transition>
        </router-view>
      </div>
    </main>
  </div>
</template>

<script setup>
/**
 * 认证布局组件。
 */
import { computed } from 'vue'

const currentYear = computed(() => new Date().getFullYear())
</script>

<style scoped>
.auth-layout { display: grid; grid-template-columns: minmax(460px, 52%) minmax(0, 1fr); }
.auth-brand {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
  min-height: 100dvh;
  padding: 40px clamp(36px, 5vw, 88px);
  color: #eaf4ff;
  background: radial-gradient(circle at 12% 12%, #245987 0%, transparent 38%),
    linear-gradient(150deg, #153b62 0%, #0d2743 76%);
}
.auth-brand::before {
  content: '';
  position: absolute;
  inset: 0;
  opacity: 0.2;
  background-image: linear-gradient(rgba(195, 223, 245, 0.17) 1px, transparent 1px),
    linear-gradient(90deg, rgba(195, 223, 245, 0.17) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: linear-gradient(to bottom, transparent, #000 34%, #000 82%, transparent);
  pointer-events: none;
}
.brand-top, .brand-content, .brand-footer { position: relative; z-index: 1; }
.brand-top, .brand-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.brand-logo { display: inline-flex; align-items: center; gap: 12px; color: inherit; font-size: 16px; font-weight: 750; text-decoration: none; }
.brand-logo:hover { color: #fff; text-decoration: none; }
.auth-logo { width: 42px; height: 42px; padding: 4px; border-radius: 12px; background: #fff; }
.brand-edition { color: #a9cee9; font-size: 12px; letter-spacing: 0.06em; }
.brand-content { width: min(100%, 640px); margin: 44px auto 0; }
.brand-content h1 { margin: 0; font-size: clamp(42px, 4.3vw, 68px); font-weight: 760; line-height: 1.22; letter-spacing: -0.045em; }
.brand-content h1 em { color: #bce5fa; font-style: normal; }
.brand-subtitle { max-width: 34ch; margin: 24px 0 0; color: #c2d6e7; font-size: 16px; line-height: 1.9; }
.learning-map { max-width: 540px; margin: 16px -12px -8px; }
.learning-map svg { display: block; width: 100%; height: auto; overflow: visible; }
.learning-map text { fill: #cce2f3; font-size: 13px; font-weight: 700; letter-spacing: 0.02em; }
.map-track, .map-active { fill: none; stroke-linecap: round; stroke-width: 3; }
.map-track { stroke: rgba(203, 227, 246, 0.4); stroke-dasharray: 6 11; }
.map-active { stroke: #8cdded; }
.map-halo { fill: rgba(110, 208, 233, 0.15); }
.map-node { fill: #d6eaf8; stroke: #153b62; stroke-width: 5; }
.map-node--active { fill: #74d9ed; }
.brand-footer { color: #95b6cf; font-size: 12px; }
.auth-form-area {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: 40px clamp(24px, 5vw, 92px);
  background: #f5f8fb;
}
.form-container { width: min(100%, 420px); }
.auth-fade-enter-active, .auth-fade-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.auth-fade-enter-from { opacity: 0; transform: translateY(10px); }
.auth-fade-leave-to { opacity: 0; transform: translateY(-10px); }

@media (max-width: 900px) {
  .auth-layout { display: flex; flex-direction: column; }
  .auth-brand { min-height: auto; padding: 24px clamp(20px, 5vw, 48px) 28px; }
  .brand-content { margin: 32px auto 0; }
  .brand-content h1 { font-size: clamp(28px, 5vw, 42px); }
  .brand-subtitle { margin-top: 12px; font-size: 14px; }
  .brand-edition, .learning-map, .brand-footer { display: none; }
  .auth-form-area { flex: 1; padding: 40px 24px; }
}
@media (max-width: 480px) {
  .brand-content { margin-top: 22px; }
  .brand-content h1 br { display: none; }
  .auth-form-area { align-items: flex-start; padding: 38px 20px 56px; }
}
@media (prefers-reduced-motion: reduce) {
  .auth-fade-enter-active, .auth-fade-leave-active { transition: none; }
}
</style>
