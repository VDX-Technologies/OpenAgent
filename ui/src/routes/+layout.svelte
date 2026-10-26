<script lang="ts">
  import "../app.css";
  import Sidebar from "#lib/components/Sidebar.svelte";
  import Onboarding from "#lib/components/Onboarding.svelte";
  import ConsentBanner from "#lib/components/ConsentBanner.svelte";
  import Toasts from "#lib/components/Toasts.svelte";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import { onMount } from "svelte";
  let { children } = $props();

  // native app: the title bar is hidden, so leave room for the traffic lights
  onMount(() => {
    const mark = () => document.documentElement.classList.add("desktop");
    if ("pywebview" in window) mark(); else window.addEventListener("pywebviewready", mark, { once: true });
  });
</script>

<svelte:head><title>VDX OpenAgent</title></svelte:head>

<div class="pywebview-drag-region titlebar-strip"></div>
<div class="app-shell flex h-screen overflow-hidden">
  <Sidebar />
  <main class="relative flex min-w-0 flex-1 flex-col">{@render children()}</main>
  <Onboarding />
  <ConsentBanner />
  <Toasts />
  <ConfirmDialog />
</div>
